import re
import sys
import traceback
from configparser import RawConfigParser
from math import sqrt, ceil
from time import perf_counter_ns

import numpy as np
from PIL import Image, ImageDraw
from numpy.typing import NDArray

Pixel = NDArray[np.int_]
gen = np.random.default_rng()
perf_list = []


def has_transparency(img: Image):
    if img.format == "GIF":
        return False
    if "transparency" in img.info:
        if not img.info["transparency"]:
            return False
        version = img.info.get("version", "")
        if isinstance(version, str):
            version = version.encode()
        if version.startswith(b"GIF"):
            return False
        return True
    if img.mode == "P":
        transparent = img.info.get("transparency", -1)
        for _, index in img.getcolors():
            if index == transparent:
                return True
    elif img.mode == "RGBA":
        extrema = img.getextrema()
        if extrema[3][0] < 255:
            return True
    return False


def get_common_colors_from_image(img: Image.Image, config: RawConfigParser) -> list[tuple[int, int, int]]:
    try:
        perf()
        pixels = convert_image_to_pixels(img)
        perf("Convert image:")
        pixels = subsample(
            pixels,
            config.getint("Kmeans", "Subsample size"),
        )
        perf("Subsample:")
        # Exclude points that are too close to white (they're not interesting)
        pixels = exclude_pixels_near_white(
            pixels,
            config.getfloat("Kmeans", "White exclusion threshold"),
        )
        perf("Exclude pixels:")
        means = kmeans(
            pixels,
            config,
        )
        perf("Kmeans:")
        common_colors = sort_means(means)
        perf("Most common mean:")
        print_perf(f"Finished finding common color in")
        return common_colors
    except ValueError:
        traceback.print_exc(file=sys.stderr)
        return [(0, 0, 0)] * config.getint("Kmeans", "Cluster size")  # Return black by default


def perf(title: str = ""):
    global perf_list
    if not title:
        title = "Start"
        perf_list = []
    perf_list.append((title, perf_counter_ns()))


def print_perf(title: str = "Total:"):
    print("Performance times:")
    for i, perf_tuple in enumerate(perf_list):
        if i == 0:
            continue
        t1, t2 = perf_list[i - 1][1], perf_list[i][1]
        print(f"  {perf_tuple[0]} {(t2 - t1) / 1000:,} us")
    t1, t2 = perf_list[0][1], perf_list[-1][1]
    print(f"{title} {(t2 - t1) / 1000:,} us")


def convert_image_to_pixels(image: Image) -> NDArray[Pixel]:
    # First paste the image onto a white background, to flatten out any transparency
    bg = Image.new("RGB", image.size, (255, 255, 255))
    bg.paste(image, (0, 0), image if has_transparency(image) else None)
    pixels = np.array(bg)
    # PIL Images start out as a 2D array (B&W image where each pixel is just a number)
    # or a 3D array (row, column, pixel)
    if pixels.ndim == 2:
        pixels = np.repeat(pixels.flatten(), 3)
    elif pixels.ndim == 3:
        # Check if the pixels are n=3 (RGB) or n=4 (RGBA). If n=4, drop the last item from each pixel.
        pixel_n = pixels.shape[2]
        if pixel_n == 4:
            pixels = pixels[:, :, :3]
    else:
        raise ValueError(f"Unknown number of dimensions in image array: {pixels.ndim}")
    # Flatten the 3D array down to a 2D array (row, pixel)
    return pixels.reshape((-1, 3))


def exclude_pixels_near_white(pixels: NDArray[Pixel], distance_threshold: float) -> NDArray[Pixel]:
    # Allow method to skip pixel exclusion if people want
    if distance_threshold == 0:
        return pixels

    # Define the target pixel
    white_pixel = np.array([255, 255, 255])

    # Calculate the Euclidean distance from each pixel to the white pixel
    distances = np.linalg.norm(pixels - white_pixel, axis=1)

    # Create a boolean mask for pixels that are beyond the distance threshold
    mask = distances >= distance_threshold

    # Apply the mask to filter out pixels
    return pixels[mask]


def subsample(pixels: NDArray[Pixel], num_samples: int) -> NDArray[Pixel]:
    random_indices = np.random.choice(pixels.shape[0], num_samples, replace=False)
    return pixels[random_indices]


def kmeans(pixels: NDArray[Pixel], config: RawConfigParser) -> dict[tuple[int, int, int], NDArray[Pixel]]:
    global mean_charts
    n_clusters = config.getint("Kmeans", "Cluster size", fallback=5)
    max_iters = config.getint("Kmeans", "Max iterations", fallback=10)
    max_distance = config.getfloat("Kmeans", "Distance threshold", fallback=1.0)
    pruning_distance = config.getfloat("Kmeans", "Pruning distance", fallback=10.0)
    show_mean_charts = config.getboolean("Kmeans", "Show clustering charts", fallback=False)
    crop_mean_charts = config.getboolean("Kmeans", "Crop clustering charts", fallback=False)
    mean_charts = []
    means, pixel_groups_by_mean = subsample(pixels, n_clusters), []
    for _ in range(max_iters):
        t1 = perf_counter_ns()
        print(f"Num means: {len(means)}")
        pixel_groups_by_mean = group_pixels_by_means(means, pixels)
        # Remove any means with no associated pixel groups
        if any(p.size == 0 for p in pixel_groups_by_mean):
            x = len(pixel_groups_by_mean)
            m, p = [], []
            for i, group in enumerate(pixel_groups_by_mean):
                if group.size > 0:
                    m.append(means[i])
                    p.append(group)
            means, pixel_groups_by_mean = m, p
            y = len(pixel_groups_by_mean)
            print(f"Removed {x - y} empty groups", file=sys.stderr)
        old_means = means
        means = np.array([mean_of_pixels(group) for group in pixel_groups_by_mean])
        if show_mean_charts:
            save_mean_chart(means, pixel_groups_by_mean, crop_mean_charts=crop_mean_charts)
        t2 = perf_counter_ns()
        print(f"Finished kmeans loop in {(t2 - t1) / 1000:,} us")
        if are_pixels_within_distance(old_means, means, max_distance=max_distance):
            if not pruning_distance:
                break
            # Prune any means that are too close together and keep running kmeans as needed
            old_means = means
            means, pixel_groups_by_mean = prune_means(means, pixel_groups_by_mean, pruning_distance)
            if np.array_equal(old_means, means):
                break
    if show_mean_charts:
        show_mean_chart()
    return {pixel_to_tuple(new_mean): pixel_group for new_mean, pixel_group in zip(means, pixel_groups_by_mean)}


def create_random_pixels(n: int) -> NDArray[Pixel]:
    """Creates a list of random pixels (3-dimensional arrays) within the bounds of RGB values [0, 255]."""
    return gen.integers(0, 255, size=(n, 3))


def group_pixels_by_means(means: NDArray[Pixel], pixels: NDArray[Pixel]) -> list[NDArray[Pixel]]:
    # Calculate the squared Euclidean distance between each vector in b and each vector in a
    distances = np.linalg.norm(pixels[:, np.newaxis] - means, axis=2)
    # Find the index of the minimum distance for each vector in pixels
    closest_indices = np.argmin(distances, axis=1)
    return [pixels[np.where(closest_indices == i)] for i in range(len(means))]


def mean_of_pixels(array_of_pixels: NDArray[Pixel]) -> Pixel:
    return np.mean(array_of_pixels, axis=0)


def are_pixels_within_distance(pixels_a: np.ndarray, pixels_b: np.ndarray, max_distance: float) -> bool:
    # Calculate the Euclidean distances between corresponding pixels
    distances = np.linalg.norm(pixels_a - pixels_b, axis=1)
    # print(f"Distances: {distances}")
    # Check if all distances are within the max_distance
    return np.all(distances <= max_distance)


def prune_means(
        means: NDArray[Pixel], pixel_groups: list[NDArray[Pixel]], pruning_distance: float = 10.0
) -> tuple[NDArray[Pixel], list[NDArray[Pixel]]]:
    """
    Finds any means that are within `pruning_distance` from each other, and removes the one with the fewest pixels
    assigned to it. Returns the pruned list of arrays, as well as the pruned pixel groups to match.
    """
    # Manually compute pairwise Euclidean distances between rows of pixels using numpy.linalg.norm
    n = len(means)
    distances = np.zeros((n, n))

    for i in range(n):
        for j in range(i + 1, n):
            distances[i, j] = np.linalg.norm(means[i] - means[j])
            distances[j, i] = distances[i, j]  # Symmetric matrix

    # Find groups where distance <= pruning_distance
    mean_groups = []
    visited = set()

    for i in range(n):
        if i in visited:
            continue
        group = {i}
        for j in range(n):
            if i != j and distances[i, j] <= pruning_distance:
                group.add(j)
        visited.update(group)
        if group:
            mean_groups.append(group)

    # If there are as many mean_groups as means, it means each group has a single mean and we can end early
    if len(means) == len(mean_groups):
        return means, pixel_groups

    print(mean_groups)
    # For each group, find the array to keep based on the largest corresponding array in pixel_groups
    arrays_to_keep = set()
    for group in mean_groups:
        max_index = max(group, key=lambda idx: len(pixel_groups[idx]))
        arrays_to_keep.add(max_index)

    # Sort `arrays_to_keep` to keep original order of means
    arrays_to_keep = sorted(arrays_to_keep)

    # Delete all arrays except the ones to keep
    final_means = np.array([means[i] for i in arrays_to_keep])
    final_pixel_groups = [pixel_groups[i] for i in arrays_to_keep]
    return final_means, final_pixel_groups


mean_charts = []


def save_mean_chart(
        means: NDArray[Pixel], pixels: list[NDArray[Pixel]], mean_radius: int = 3, pixel_radius: int = 1,
        crop_mean_charts: bool = False
):
    global mean_charts
    mean_colors = ("red", "green", "blue", "orange", "yellow", "pink", "purple", "cyan", "magenta", "brown")
    # Create a blank image with white background
    image = Image.new("RGB", (255, 255), "white")
    draw = ImageDraw.Draw(image)

    def draw_pixel(draw: ImageDraw.Draw, pixel: Pixel, color: tuple[int, int, int], radius: int):
        # Just use x and y for 2D map
        x, y, _ = pixel
        x, y = int(x), int(y)
        if radius == 0:
            draw.pixel((x, y), fill=color)
        else:
            try:
                draw.ellipse(
                    (
                        max(x - radius, 0),
                        max(y - radius, 0),
                        min(x + radius, 255),
                        min(y + radius, 255),
                    ),
                    fill=color,
                )
            except ValueError as e:
                print(f"{e}: ({x}, {y})", file=sys.stderr)

    # Project 3D pixels to 2D (ignore z-coordinate for simplicity)
    min_x, min_y, max_x, max_y = 255, 255, 0, 0
    for i, mean in enumerate(means):
        color = mean_colors[i]
        for pixel in pixels[i]:
            x, y, _ = pixel
            min_x, min_y, max_x, max_y = min(x, min_x), min(y, min_y), max(x, max_x), max(y, max_y)
            draw_pixel(draw, pixel, color, pixel_radius)
        draw_pixel(draw, mean, color, mean_radius)

    if crop_mean_charts:
        # Crop image down to reduce unused whitespace
        min_x, min_y = max(0,   int(min_x) - 10), max(0,   int(min_y) - 10)
        max_x, max_y = min(255, int(max_x) + 10), min(255, int(max_y) + 10)
        image = image.crop((min_x, min_y, max_x, max_y))

    image = image.resize((255 * 2, 255 * 2))
    mean_charts.append(image)


def show_mean_chart():
    global mean_charts
    if not mean_charts:
        return
    cell_width = 255 * 2
    border = 15
    x = ceil(sqrt(len(mean_charts)))
    width = (cell_width + border) * x + border
    height = (cell_width + border) * ceil(len(mean_charts) / x) + border
    bg = Image.new("RGB", (width, height), "black")
    for i, chart in enumerate(mean_charts):
        x = i % 3 * (cell_width + border) + border
        y = i // 3 * (cell_width + border) + border
        bg.paste(chart, (x, y))
    import threading
    t = threading.Thread(target=bg.show)
    t.start()


def pixels_to_tuples(pixels: NDArray[Pixel]) -> list[tuple[int, int, int]]:
    return [pixel_to_tuple(p) for p in pixels]


def pixel_to_tuple(pixel: Pixel) -> tuple[int, int, int]:
    rounded_array = np.round(pixel)
    return tuple(int(x) for x in rounded_array)


def sort_means(means: dict[tuple[int, int, int], NDArray[Pixel]]) -> list[tuple[int, int, int]]:
    items = means.items()
    # for mean, pixel_group in items:
    #     print(f"{mean}: {len(pixel_group)}")
    s = sorted(items, key=lambda x: len(x[1]), reverse=True)
    return [x[0] for x in s]


def get_common_color(means: list[tuple[int, int, int]], config_value: str) -> tuple[int, int, int]:
    """
    Parses config value to determine which common color to use. If the image ends in digits (e.g. kmeans2), use the
    number at the end to determine which common color to use. Otherwise, assume index=0.

    The number will be reduced by 1 to determine what index to use. E.g. kmeans2 will use index=1.
    """
    m = re.search(r"^.*?(\d+)$", config_value)
    if m:
        index = int(m.group(1)) - 1
        return means[max(0, min(index, len(means) - 1))]
    return means[0]

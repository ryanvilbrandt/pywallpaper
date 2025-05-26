import logging
from configparser import RawConfigParser
from math import sqrt, ceil
from time import perf_counter_ns

import numpy as np
from PIL import Image, ImageDraw
from numpy.typing import NDArray

from image_utils import convert_image_to_pixels, exclude_pixels_near_white, subsample, Pixel, pixel_to_tuple, \
    sort_means, pixels_to_tuples, downscale_image
from utils import perf, log_perf

logger = logging.getLogger(__name__)


def get_common_colors_from_image(img: Image, config: RawConfigParser) -> list[tuple[int, int, int]]:
    try:
        perf()

        max_dim = config.getint("Kmeans", "Max dimension for downscaling", fallback=700)
        if max_dim > 0:
            img = downscale_image(img, max_dim)
            perf("Downscaling Image:")

        pixels = convert_image_to_pixels(img)
        perf("Convert image:")

        subsample_size = config.getint("Kmeans", "Subsample size", fallback=-1)
        if subsample_size > 0:
            pixels = subsample(pixels, subsample_size)
            perf("Subsample:")

        # Exclude points that are too close to white (they're not interesting)
        pixels = exclude_pixels_near_white(
            pixels,
            config.getfloat("Kmeans", "White exclusion threshold"),
        )
        perf("Exclude pixels:")

        means = kmeans(pixels, config)
        perf("Kmeans:")

        common_colors = sort_means(means)
        perf("Most common mean:")

        log_perf(f"Finished finding common color in")

        return pixels_to_tuples(common_colors)
    except ValueError:
        logger.exception("Error when processing kmeans")
        return [(0, 0, 0)] * config.getint("Kmeans", "Cluster size")  # Return black by default


def kmeans(pixels: NDArray[Pixel], config: RawConfigParser) -> dict[Pixel, int]:
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
        logger.debug(f"Num means: {len(means)}")
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
            logger.warning(f"Removed {x - y} empty groups")
        old_means = means
        means = np.array([mean_of_pixels(group) for group in pixel_groups_by_mean])
        if show_mean_charts:
            save_mean_chart(means, pixel_groups_by_mean, crop_mean_charts=crop_mean_charts)
        t2 = perf_counter_ns()
        logger.info(f"Finished kmeans loop in {(t2 - t1) / 1_000_000:.2f} ms")
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
    return {pixel_to_tuple(new_mean): len(pixel_group) for new_mean, pixel_group in zip(means, pixel_groups_by_mean)}


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
    logger.debug(f"Distances: {distances}")
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

    logger.debug(mean_groups)
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
                logger.error(f"{e}: ({x}, {y})")

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

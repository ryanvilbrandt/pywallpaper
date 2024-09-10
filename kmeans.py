import sys
import traceback
from configparser import RawConfigParser
from time import perf_counter_ns

import numpy as np
from PIL import Image, ImageDraw
from numpy.typing import NDArray

Pixel = NDArray[np.int_]
gen = np.random.default_rng()
perf_list = []


def get_common_color_from_image(img: Image.Image, config: RawConfigParser) -> tuple[int, int, int]:
    try:
        perf()
        pixels = convert_image_to_pixels(img)
        perf("Convert image:")
        pixels = subsample(
            pixels,
            config.getint("Advanced", "Kmeans subsample size"),
        )
        perf("Subsample:")
        # Exclude points that are too close to white (they're not interesting)
        pixels = exclude_pixels_near_white(
            pixels,
            config.getfloat("Advanced", "White exclusion threshold"),
        )
        perf("Exclude pixels:")
        means = kmeans(
            pixels,
            config.getint("Advanced", "Kmeans cluster size"),
            config.getint("Advanced", "Kmeans max iterations"),
            config.getfloat("Advanced", "Kmeans distance threshold"),
        )
        perf("Kmeans:")
        bg_color = get_most_common_mean(means)
        perf("Most common mean:")
        print_perf(f"Finished finding common color in")
        return bg_color
    except ValueError:
        traceback.print_exc(file=sys.stderr)
        return 0, 0, 0  # Return black by default


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
    pixels = np.array(image)
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


def kmeans(pixels: NDArray[Pixel], n_clusters: int, max_iters: int = 10, max_distance: float = 1.0
           ) -> dict[tuple[int, int, int], NDArray[Pixel]]:
    # print(pixels)
    means, pixel_groups_by_mean = subsample(pixels, n_clusters), []
    # print(means)
    # print("=========")
    for _ in range(max_iters):
        t1 = perf_counter_ns()
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
            print(f"Removed {x - y} empty groups")
        old_means = means
        means = np.array([mean_of_pixels(group) for group in pixel_groups_by_mean])
        # print(f"New means: {means}")
        # show_means(means, pixel_groups_by_mean)
        t2 = perf_counter_ns()
        print(f"Finished kmeans loop in {(t2 - t1) / 1000:,} us")
        if are_pixels_within_distance(old_means, means, max_distance=max_distance):
            break
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
    print(f"Distances: {distances}")
    # Check if all distances are within the max_distance
    return np.all(distances <= max_distance)


def show_means(means: NDArray[Pixel], pixels: list[NDArray[Pixel]],
               mean_colors: list[tuple[int, int, int]]=((255, 0, 0), (0, 255, 0), (0, 0, 255)),
               mean_radius=3, pixel_radius=1):
    # Create a blank image with white background
    image = Image.new("RGB", (255, 255), "white")
    draw = ImageDraw.Draw(image)

    def draw_pixel(draw: ImageDraw.Draw, pixel: Pixel, color: tuple[int, int, int], radius: int):
        # Just use x and y for 2D map
        x, y, _ = pixel
        if radius == 0:
            draw.pixel((x, y), fill=color)
        else:
            draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=color)

    # Project 3D pixels to 2D (ignore z-coordinate for simplicity)
    for i, color in enumerate(mean_colors):
        for pixel in pixels[i]:
            draw_pixel(draw, pixel, color, pixel_radius)
        draw_pixel(draw, means[i], color, mean_radius)

    image = image.resize((255 * 3, 255 * 3))
    image.show()


def pixel_to_tuple(pixel: Pixel) -> tuple[int, int, int]:
    rounded_array = np.round(pixel)
    return tuple(int(x) for x in rounded_array)


def get_most_common_mean(means: dict[tuple[int, int, int], NDArray[Pixel]]) -> tuple[int, int, int]:
    for mean, pixel_group in means.items():
        print(f"{mean}: {len(pixel_group)}")
    biggest_group_size = 0
    biggest_mean = None
    for mean, pixels in means.items():
        if len(pixels) > biggest_group_size:
            biggest_mean = mean
            biggest_group_size = len(pixels)
    return biggest_mean


def main():
    pixels = create_random_pixels(10)
    pixels = np.append(pixels, [[254, 254, 254]], axis=0)
    print(pixels)
    new_pixels = exclude_pixels_near_white(pixels, 20)
    print(new_pixels)
    pixels = [pixel_to_tuple(p) for p in pixels]
    new_pixels = [pixel_to_tuple(p) for p in new_pixels]
    print(f"Excluded pixels: {set(pixels).difference(new_pixels)}")


if __name__ == '__main__':
    main()

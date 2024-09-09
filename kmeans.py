from time import perf_counter_ns

import numpy as np
from PIL import Image, ImageDraw
from numpy.typing import NDArray

Pixel = NDArray[np.int_]
gen = np.random.default_rng()


def convert_image_to_pixels(image: Image) -> NDArray[Pixel]:
    pixels = np.array(image)
    return pixels.reshape((-1, 3))


def exclude_pixels_near_white(pixels: NDArray[Pixel], distance_threshold: float) -> NDArray[Pixel]:
    # Define the target pixel
    white_pixel = np.array([255, 255, 255])

    # Calculate the Euclidean distance from each pixel to the white pixel
    distances = np.linalg.norm(pixels - white_pixel, axis=1)

    # Create a boolean mask for pixels that are beyond the distance threshold
    mask = distances >= distance_threshold

    # Apply the mask to filter out pixels
    return pixels[mask]


def kmeans(pixels: NDArray[Pixel], n_clusters: int, max_iters: int = 10) -> dict[tuple[int, int, int], NDArray[Pixel]]:
    # print(pixels)
    means, pixel_groups_by_mean = create_random_pixels(n_clusters), []
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
        if are_pixels_within_distance(old_means, means, max_distance=0.1):
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


def get_most_common_mean(pixels: NDArray[Pixel], n_clusters: int):
    t1 = perf_counter_ns()
    means = kmeans(pixels, n_clusters)
    for mean, pixel_group in means.items():
        print(f"{mean}: {len(pixel_group)}")
    biggest_group_size = 0
    biggest_mean = None
    for mean, pixels in means.items():
        if len(pixels) > biggest_group_size:
            biggest_mean = mean
            biggest_group_size = len(pixels)
    t2 = perf_counter_ns()
    print(f"Finished finding most common mean in {(t2 - t1) / 1000:,} us")
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

import sys
import traceback
from collections import defaultdict
from configparser import RawConfigParser

import numpy as np
from PIL import Image
from numpy._typing import NDArray

from image_utils import convert_image_to_pixels, subsample, exclude_pixels_near_white, Pixel, pixels_to_tuples, \
    downscale_image, sort_means
from utils import perf, print_perf, load_config


def get_common_colors_from_image(
        img: Image, config: RawConfigParser, show_plot: bool = False
) -> list[tuple[int, int, int]]:
    try:
        perf()

        max_dim = config.getint("Mean Shift", "Max dimension for downscaling", fallback=700)
        if max_dim > 0:
            img = downscale_image(img, max_dim)
            perf("Downscaling Image:")

        pixels = convert_image_to_pixels(img)
        perf("Convert image:")

        subsample_size = config.getint("Mean Shift", "Subsample size", fallback=-1)
        if subsample_size > 0:
            pixels = subsample(pixels, subsample_size)
            perf("Subsample:")

        # Exclude points that are too close to white (they're not interesting)
        pixels = exclude_pixels_near_white(
            pixels,
            config.getfloat("Mean Shift", "White exclusion threshold", fallback=100),
        )
        perf("Exclude pixels:")

        cluster_centers = mean_shift_with_removal(
            pixels,
            config.getfloat("Mean Shift", "Radius", fallback=30),
            config.getfloat("Mean Shift", "Tolerance", fallback=0.001),
            config.getint("Mean Shift", "Max Iterations", fallback=100),
        )
        perf("Mean shift:")

        # Sort the colors and counts
        sorted_colors = sort_means(cluster_centers)
        perf("Sort colors:")

        print_perf(f"Finished finding common color in")

        if show_plot:
            # Plot the dominant colors
            plot_colors(cluster_centers)

        return pixels_to_tuples(sorted_colors)
    except ValueError:
        traceback.print_exc(file=sys.stderr)
        # return [(0, 0, 0)] * config.getint("Kmeans", "Cluster size")  # Return black by default


def mean_shift_with_removal(
        data: NDArray[Pixel], radius: float = 30, tolerance: float = 0.001, max_iters: int = 300
) -> dict[Pixel, int]:
    """Mean Shift clustering with removal of assigned points."""
    points = data.copy()
    cluster_centers = defaultdict(int)

    while len(points) > 0:  # Keep looping until all points are assigned
        print(f"Points remaining: {len(points)}")

        # Pick the first available point
        center = points[0].copy()

        for _ in range(max_iters):
            # Find all points within the radius
            distances = np.linalg.norm(points - center, axis=1)
            within_radius = distances < radius
            # Check for if we have no points within the radius
            if np.sum(within_radius) == 0:
                print("Found cluster with no points. Skipping.")
                break
            new_center = points[within_radius].mean(axis=0)

            if np.linalg.norm(new_center - center) < tolerance:
                break
            center = new_center
        else:
            print("Hit max_iters")

        if np.sum(within_radius) == 0:
            points = points[1:]
        else:
            cluster_centers[tuple(center)] += np.sum(within_radius)
            # Remove assigned points from `points`
            points = points[~within_radius]  # Keep only points that are NOT within radius
    print("Done finding clusters")

    return cluster_centers


def plot_colors(cluster_centers: dict[Pixel, int]):
    """Plot the extracted dominant colors by number of pixels in the group."""
    print("Plotting color orders...")

    import matplotlib
    matplotlib.use("TkAgg")
    from matplotlib import pyplot

    sorted_colors = sorted(cluster_centers.items(), key=lambda x: x[1], reverse=True)  # Sort by frequency
    colors, counts = zip(*sorted_colors)
    colors = np.array(colors, dtype=np.uint8)
    counts = np.array(counts)

    pyplot.figure(figsize=(10, 5))
    pyplot.bar(range(len(colors)), counts, color=colors / 255.0, edgecolor='black')
    pyplot.xticks([])  # Remove x-axis labels
    pyplot.ylabel("Pixel Count")
    pyplot.title("Dominant Colors by Pixel Count")
    pyplot.show()


if __name__ == '__main__':
    image_path = r""
    c = load_config()
    get_common_colors_from_image(Image.open(image_path), c, show_plot=True)

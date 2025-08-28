import re

import numpy as np
from PIL import Image
from numpy._typing import NDArray


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


Pixel = NDArray[np.int_]


def convert_image_to_pixels(image: Image) -> NDArray[Pixel]:
    # First, paste the image onto a white background to flatten out any transparency
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


def pixels_to_tuples(pixels: list[Pixel]) -> list[tuple[int, int, int]]:
    return [pixel_to_tuple(p) for p in pixels]


def pixel_to_tuple(pixel: Pixel) -> tuple[int, int, int]:
    rounded_array = np.round(pixel)
    return tuple(int(x) for x in rounded_array)


def get_common_color(means: list[tuple[int, int, int]], config_value: str) -> tuple[int, int, int]:
    """
    Parses config value to determine which common color to use. If the image ends in digits (e.g., kmeans2), use the
    number at the end to determine which common color to use. Otherwise, assume index=0.

    The number will be reduced by 1 to determine what index to use. E.g., kmeans2 will use index=1.
    """
    m = re.search(r"^.*?(\d+)$", config_value)
    if m:
        index = int(m.group(1)) - 1
        return tuple(means[max(0, min(index, len(means) - 1))])
    return tuple(means[0])


gen = np.random.default_rng()


def create_random_pixels(n: int) -> NDArray[Pixel]:
    """Creates a list of random pixels (3-dimensional arrays) within the bounds of RGB values [0, 255]."""
    return gen.integers(0, 255, size=(n, 3))


def downscale_image(image: Image, max_dim: int) -> Image:
    """Resize the image so the largest dimension matches max_dim while keeping the aspect ratio."""
    width, height = image.size
    scale = max_dim / max(width, height)
    if scale > 1:
        # Don't increase image size if it's smaller than the max dimension, just return the original image
        return image
    new_size = (int(width * scale), int(height * scale))
    return image.resize(new_size, Image.LANCZOS)


def sort_means(means: dict[Pixel, int]) -> list[Pixel]:
    s = sorted(means.items(), key=lambda x: x[1], reverse=True)
    return [x[0] for x in s]

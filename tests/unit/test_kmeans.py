from unittest import TestCase

import numpy as np

from src.kmeans import exclude_pixels_near_white, pixels_to_tuples, prune_means


class TestKmeans(TestCase):

    def test_white_exclusion(self):
        pixels = [[1, 104, 221], [84, 120, 39], [209, 92, 192]]
        pixels = np.array(pixels)
        pixels = np.append(pixels, [[254, 254, 254]], axis=0)
        self.assertTrue(np.array_equal(
            np.array([(1, 104, 221), (84, 120, 39), (209, 92, 192), (254, 254, 254)]),
            pixels,
        ))
        new_pixels = exclude_pixels_near_white(pixels, 20)
        self.assertTrue(np.array_equal(
            np.array([(1, 104, 221), (84, 120, 39), (209, 92, 192)]),
            new_pixels,
        ))
        pixels = pixels_to_tuples(pixels)
        new_pixels = pixels_to_tuples(new_pixels)
        self.assertEqual(
            {(254, 254, 254)},
            set(pixels).difference(new_pixels),
        )

    def test_pruning_distance(self):
        means = np.array([[1, 2, 3], [4, 5, 6], [1.5, 2.5, 3.5], [10, 10, 10]])
        pixel_groups = [
            np.array([[7, 8, 9], [10, 11, 12]]),
            np.array([[13, 14, 15]]),
            np.array([[1, 1, 1], [2, 2, 2], [3, 3, 3]]),
            np.array([[14, 14, 14]])
        ]
        means, pixel_groups = prune_means(means, pixel_groups, pruning_distance=2)
        self.assertTrue(np.array_equal(
            np.array([[4, 5, 6], [1.5, 2.5, 3.5], [10, 10, 10]]),
            means,
        ))
        new_pixel_groups = [
            np.array([[13, 14, 15]]),
            np.array([[1, 1, 1], [2, 2, 2], [3, 3, 3]]),
            np.array([[14, 14, 14]])
        ]
        for pg, npg in zip(pixel_groups, new_pixel_groups):
            self.assertTrue(np.array_equal(pg, npg))

    def test_pruning_distance_no_prune(self):
        means = np.array([[1, 2, 3], [4, 5, 6], [1.5, 2.5, 3.5], [10, 10, 10]])
        pixel_groups = [
            np.array([[7, 8, 9], [10, 11, 12]]),
            np.array([[13, 14, 15]]),
            np.array([[1, 1, 1], [2, 2, 2], [3, 3, 3]]),
            np.array([[14, 14, 14]])
        ]
        means, pixel_groups = prune_means(means, pixel_groups, pruning_distance=0.1)
        self.assertTrue(np.array_equal(
            np.array([[1, 2, 3], [4, 5, 6], [1.5, 2.5, 3.5], [10, 10, 10]]),
            means,
        ))
        new_pixel_groups = [
            np.array([[7, 8, 9], [10, 11, 12]]),
            np.array([[13, 14, 15]]),
            np.array([[1, 1, 1], [2, 2, 2], [3, 3, 3]]),
            np.array([[14, 14, 14]])
        ]
        for pg, npg in zip(pixel_groups, new_pixel_groups):
            self.assertTrue(np.array_equal(pg, npg))

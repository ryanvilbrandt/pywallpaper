import os
from collections import defaultdict
from unittest import TestCase
from unittest.mock import ANY, patch, Mock

from src.db import Db


class TestDb(TestCase):

    table = "images_integration_tests"

    @classmethod
    def setUpClass(cls):
        while not os.path.isdir("database"):
            os.chdir("..")
        with Db(cls.table) as db:
            db.make_images_table()

    def setUp(self):
        with Db(self.table) as db:
            sql = "DELETE FROM images_integration_tests;"
            db.cur.execute(sql)

    def test_add_eagle_folder_new(self):
        with Db(self.table) as db:
            db.add_eagle_folder(r"\\NAS\Eagle\Library", {"Art": "ABCDEFG"})
            self.assertEqual(
                [{
                    "id": ANY,
                    "filepath": r"\\NAS\Eagle\Library",
                    "active": 1,
                    "is_directory": 1,
                    "times_used": 0,
                    "total_times_used": 0,
                    "include_subdirectories": 0,
                    "ephemeral": 0,
                    "is_eagle_directory": 1,
                    "eagle_folder_data": '{"Art": "ABCDEFG"}',
                }],
                [dict(d) for d in db._fetch_all(f"SELECT * FROM {self.table};")],
            )

    def test_add_eagle_folder_add_same_id(self):
        with Db(self.table) as db:
            db.add_eagle_folder(r"\\NAS\Eagle\Library", {"Art": "ABCDEFG"})
            db.add_eagle_folder(r"\\NAS\Eagle\Library", {"Art Again": "ABCDEFG"})
            self.assertEqual(
                [{
                    "id": ANY,
                    "filepath": r"\\NAS\Eagle\Library",
                    "active": 1,
                    "is_directory": 1,
                    "times_used": 0,
                    "total_times_used": 0,
                    "include_subdirectories": 0,
                    "ephemeral": 0,
                    "is_eagle_directory": 1,
                    "eagle_folder_data": '{"Art": "ABCDEFG", "Art Again": "ABCDEFG"}',
                }],
                [dict(d) for d in db._fetch_all(f"SELECT * FROM {self.table};")],
            )

    def test_add_eagle_folder_add_two_ids(self):
        with Db(self.table) as db:
            db.add_eagle_folder(r"\\NAS\Eagle\Library", {"Art": "ABCDEFG"})
            db.add_eagle_folder(r"\\NAS\Eagle\Library", {"Art Again": "ZYXWV"})
            self.assertEqual(
                [{
                    "id": ANY,
                    "filepath": r"\\NAS\Eagle\Library",
                    "active": 1,
                    "is_directory": 1,
                    "times_used": 0,
                    "total_times_used": 0,
                    "include_subdirectories": 0,
                    "ephemeral": 0,
                    "is_eagle_directory": 1,
                    "eagle_folder_data": '{"Art": "ABCDEFG", "Art Again": "ZYXWV"}',
                }],
                [dict(d) for d in db._fetch_all(f"SELECT * FROM {self.table};")],
            )

    def test_remove_ephemeral_images_in_folder(self):
        with Db(self.table) as db:
            db.add_images([
                r"//NAS/Library1/ABC.png",
                r"//NAS/Library1/DEF.jpg",
                r"//NAS/Library2/ZYX.gif",
            ], ephemeral=True)
            db.remove_ephemeral_images_in_folder(r"//NAS/Library1")
            self.assertEqual(
                [{
                    "id": ANY,
                    "filepath": r"//NAS/Library2/ZYX.gif",
                    "active": 1,
                    "is_directory": 0,
                    "times_used": 0,
                    "total_times_used": 0,
                    "include_subdirectories": 0,
                    "ephemeral": 1,
                    "is_eagle_directory": 0,
                    "eagle_folder_data": None,
                }],
                [dict(d) for d in db._fetch_all(f"SELECT * FROM {self.table};")],
            )

    @patch("src.db.choices", return_value=[r"//NAS/Library1/ABC.png"])
    def test_get_random_image_with_weighting(self, choices_mock: Mock):
        with Db(self.table) as db:
            filepaths = [
                r"//NAS/Library1/ABC.png",
                r"//NAS/Library1/DEF.jpg",
                r"//NAS/Library2/ZYX.gif",
                r"//NAS/Library2/WVU.gif",
            ]
            db.add_images(filepaths, ephemeral=True)
            db.increment_times_used(filepaths[0])
            db.increment_times_used(filepaths[1])
            db.increment_times_used(filepaths[1])
            db.increment_times_used(filepaths[2])
            db.increment_times_used(filepaths[2])
            db.increment_times_used(filepaths[2])
            db.increment_times_used(filepaths[2])
            db.increment_times_used(filepaths[3])
            self.assertEqual(filepaths[0], db.get_random_image_with_weighting())
            choices_mock.assert_called_once_with(tuple(filepaths), weights=[4, 3, 1, 4])
            # Check for times_used normalization
            sql = "SELECT filepath, times_used FROM images_integration_tests;"
            self.assertEqual(
                [
                    ("//NAS/Library1/ABC.png", 1),
                    ("//NAS/Library1/DEF.jpg", 1),
                    ("//NAS/Library2/ZYX.gif", 3),
                    ("//NAS/Library2/WVU.gif", 0),
                ],
                db.cur.execute(sql).fetchall(),
            )

    def test_weighted_random_spread(self):
        with Db(self.table) as db:
            filepaths = [
                r"//NAS/Library1/ABC.png",
                r"//NAS/Library1/DEF.jpg",
                r"//NAS/Library1/GHI.jpg",
                r"//NAS/Library2/ZYX.gif",
                r"//NAS/Library2/WVU.gif",
                r"//NAS/Library2/TSR.gif",
            ]
            db.add_images(filepaths, ephemeral=True)
            db.increment_times_used(filepaths[0])
            db.increment_times_used(filepaths[1])
            db.increment_times_used(filepaths[1])
            db.increment_times_used(filepaths[2])
            db.increment_times_used(filepaths[2])
            db.increment_times_used(filepaths[2])
            db.increment_times_used(filepaths[3])
            db.increment_times_used(filepaths[3])
            db.increment_times_used(filepaths[3])
            db.increment_times_used(filepaths[3])
            db.increment_times_used(filepaths[4])
            db.increment_times_used(filepaths[4])
            db.increment_times_used(filepaths[4])
            db.increment_times_used(filepaths[4])
            db.increment_times_used(filepaths[4])
            db.increment_times_used(filepaths[5])
            db.increment_times_used(filepaths[5])
            db.increment_times_used(filepaths[5])
            db.increment_times_used(filepaths[5])
            db.increment_times_used(filepaths[5])
            db.increment_times_used(filepaths[5])
            db.normalize_times_used()
            sql = "SELECT filepath, times_used FROM images_integration_tests;"
            self.assertEqual(
                [
                    ("//NAS/Library1/ABC.png", 0),
                    ("//NAS/Library1/DEF.jpg", 1),
                    ("//NAS/Library1/GHI.jpg", 2),
                    ("//NAS/Library2/ZYX.gif", 3),
                    ("//NAS/Library2/WVU.gif", 4),
                    ("//NAS/Library2/TSR.gif", 5),
                ],
                db.cur.execute(sql).fetchall(),
            )
            # Pick a random image with weighting many times and track when each image is picked
            d = defaultdict(int)
            max_iters = 210000
            for _ in range(max_iters):
                filepath = db.get_random_image_with_weighting(increment=False)
                d[filepath] += 1
            print(dict(d))

            n = 6
            a = n * (n + 1) // 2
            print(a)
            # Expected count for the last image (i.e. the one with the most times used)
            b = max_iters // a
            print(b)
            # All other images will be expected to be used a multiple of that number, inversely proportional to
            # number of times used
            self.assertAlmostEqual(d["//NAS/Library1/ABC.png"], 6 * b, delta=1000)
            self.assertAlmostEqual(d["//NAS/Library1/DEF.jpg"], 5 * b, delta=1000)
            self.assertAlmostEqual(d["//NAS/Library1/GHI.jpg"], 4 * b, delta=1000)
            self.assertAlmostEqual(d["//NAS/Library2/ZYX.gif"], 3 * b, delta=1000)
            self.assertAlmostEqual(d["//NAS/Library2/WVU.gif"], 2 * b, delta=1000)
            self.assertAlmostEqual(d["//NAS/Library2/TSR.gif"], 1 * b, delta=1000)

    @patch("src.db.choice", return_value=r"//NAS/Library1/ABC.png")
    def test_get_random_image_from_least_used(self, choice_mock: Mock):
        with Db(self.table) as db:
            filepaths = [
                r"//NAS/Library1/ABC.png",
                r"//NAS/Library1/DEF.jpg",
                r"//NAS/Library2/ZYX.gif",
                r"//NAS/Library2/WVU.gif",
            ]
            db.add_images(filepaths, ephemeral=True)
            db.increment_times_used(filepaths[0])
            db.increment_times_used(filepaths[1])
            db.increment_times_used(filepaths[1])
            db.increment_times_used(filepaths[2])
            db.increment_times_used(filepaths[2])
            db.increment_times_used(filepaths[2])
            db.increment_times_used(filepaths[2])
            db.increment_times_used(filepaths[3])
            self.assertEqual(filepaths[0], db.get_random_image_from_least_used())
            choice_mock.assert_called_once_with(['//NAS/Library1/ABC.png', '//NAS/Library2/WVU.gif'])
            # Check for times_used normalization
            sql = "SELECT filepath, times_used FROM images_integration_tests;"
            self.assertEqual(
                [
                    ("//NAS/Library1/ABC.png", 1),
                    ("//NAS/Library1/DEF.jpg", 1),
                    ("//NAS/Library2/ZYX.gif", 3),
                    ("//NAS/Library2/WVU.gif", 0),
                ],
                db.cur.execute(sql).fetchall(),
            )

    def test_normalize_times_used(self):
        with Db(self.table) as db:
            filepaths = [
                r"//NAS/Library1/ABC.png",
                r"//NAS/Library1/DEF.jpg",
                r"//NAS/Library2/ZYX.gif",
                r"//NAS/Library2/WVU.gif",
            ]
            db.add_images(filepaths, ephemeral=True)
            db.increment_times_used(filepaths[0])
            db.increment_times_used(filepaths[0])
            db.increment_times_used(filepaths[0])
            db.increment_times_used(filepaths[1])
            db.increment_times_used(filepaths[1])
            db.increment_times_used(filepaths[2])
            db.increment_times_used(filepaths[2])
            db.increment_times_used(filepaths[2])
            db.increment_times_used(filepaths[2])
            db.increment_times_used(filepaths[3])
            db.increment_times_used(filepaths[3])
            db.normalize_times_used()
            sql = "SELECT filepath, times_used FROM images_integration_tests;"
            self.assertEqual(
                [
                    ("//NAS/Library1/ABC.png", 1),
                    ("//NAS/Library1/DEF.jpg", 0),
                    ("//NAS/Library2/ZYX.gif", 2),
                    ("//NAS/Library2/WVU.gif", 0),
                ],
                db.cur.execute(sql).fetchall(),
            )


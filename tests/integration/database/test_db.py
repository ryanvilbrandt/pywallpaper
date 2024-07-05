import os
from unittest import TestCase
from unittest.mock import ANY

from database.db import Db


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
                [
                    {"id": ANY, "filepath": r"\\NAS\Eagle\Library", "active": 1, "is_directory": 1,
                     "include_subdirectories": 0, "ephemeral": 0, "is_eagle_directory": 1,
                     "eagle_folder_data": '{"Art": "ABCDEFG"}'},
                ],
                list(db._fetch_all(f"SELECT * FROM {self.table};")),
            )

    def test_add_eagle_folder_add_same_id(self):
        with Db(self.table) as db:
            db.add_eagle_folder(r"\\NAS\Eagle\Library", {"Art": "ABCDEFG"})
            db.add_eagle_folder(r"\\NAS\Eagle\Library", {"Art Again": "ABCDEFG"})
            self.assertEqual(
                [
                    {"id": ANY, "filepath": r"\\NAS\Eagle\Library", "active": 1, "is_directory": 1,
                     "include_subdirectories": 0, "ephemeral": 0, "is_eagle_directory": 1,
                     "eagle_folder_data": '{"Art": "ABCDEFG", "Art Again": "ABCDEFG"}'},
                ],
                list(db._fetch_all(f"SELECT * FROM {self.table};")),
            )

    def test_add_eagle_folder_add_two_ids(self):
        with Db(self.table) as db:
            db.add_eagle_folder(r"\\NAS\Eagle\Library", {"Art": "ABCDEFG"})
            db.add_eagle_folder(r"\\NAS\Eagle\Library", {"Art Again": "ZYXWV"})
            self.assertEqual(
                [
                    {"id": ANY, "filepath": r"\\NAS\Eagle\Library", "active": 1, "is_directory": 1,
                     "include_subdirectories": 0, "ephemeral": 0, "is_eagle_directory": 1,
                     "eagle_folder_data": '{"Art": "ABCDEFG", "Art Again": "ZYXWV"}'},
                ],
                list(db._fetch_all(f"SELECT * FROM {self.table};")),
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
                [
                    {"id": ANY, "filepath": r"//NAS/Library2/ZYX.gif", "active": 1, "is_directory": 0,
                     "include_subdirectories": 0, "ephemeral": 1, "is_eagle_directory": 0,
                     "eagle_folder_data": None},
                ],
                list(db._fetch_all(f"SELECT * FROM {self.table};")),
            )
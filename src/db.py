import json
import sqlite3
import sys
from collections import OrderedDict, defaultdict
from random import choice, choices
from sqlite3 import Cursor, OperationalError
from typing import Optional, Iterator, Union, Sequence


class Db:
    table = None
    auto_commit = False
    auto_close = False
    ids = None

    def __init__(self, table="images", filename="database/main.db", auto_commit=True, auto_close=True):
        self.table = table
        self.conn = sqlite3.connect(filename)
        self.cur = self.conn.cursor()
        self.auto_commit = auto_commit
        self.auto_close = auto_close

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.conn:
            try:
                if exc_type:
                    self.conn.rollback()
                elif self.auto_commit:
                    self.conn.commit()
            finally:
                if self.auto_close:
                    self.close()

    def close(self):
        if self.conn:
            self.conn.close()

    def _row_to_dict(self, row) -> dict:
        d = OrderedDict()
        if self.cur.description is None:
            raise TypeError(
                "Cursor description is None. Did you make another DB query while iterating through "
                "a fetchall, perchance?"
            )
        for i, col in enumerate(self.cur.description):
            d[col[0]] = row[i]
        return d

    def _execute(self, sql, params=None) -> Cursor:
        args = [sql]
        if params is not None:
            args.append(params)
        return self.cur.execute(*args)

    def _scalar(self, sql, params=None) -> Union[str, int, bool, None]:
        result = self._execute(sql, params).fetchone()
        if result is None:
            return None
        return result[0]

    def _fetch_one(self, sql, params=None) -> Optional[dict]:
        result = self._execute(sql, params).fetchone()
        if result is None:
            return None
        return self._row_to_dict(result)

    def _fetch_all(self, sql, params=None) -> Iterator[dict]:
        for row in self._execute(sql, params).fetchall():
            yield self._row_to_dict(row)

    # MIGRATIONS

    def migrate(self):
        version = self.get_version()
        if version < 1:
            self.version1()
        if version < 2:
            self.version2()
        if version < 3:
            self.version3()

    def get_version(self) -> int:
        sql = "SELECT version FROM version;"
        try:
            return self._fetch_one(sql)["version"]
        except OperationalError:
            # No table found, return version=0
            return 0

    def version1(self):
        sql = """
        CREATE TABLE IF NOT EXISTS version (
            version INTEGER
        );
        INSERT INTO version (version) VALUES (1);
        """
        self.cur.executescript(sql)

    def version2(self):
        image_tables = self.get_image_tables()
        for table_name in image_tables:
            sql = f"""
            ALTER TABLE images_{table_name}
            ADD COLUMN total_times_used INTEGER DEFAULT 0;
            UPDATE images_{table_name} SET total_times_used=times_used;
            """
            self.cur.executescript(sql)
        sql = """
        UPDATE version SET version=2;
        """
        self._execute(sql)

    def version3(self):
        image_tables = self.get_image_tables()
        for table_name in image_tables:
            sql = f"""
            ALTER TABLE images_{table_name}
            ADD COLUMN color_cache JSON DEFAULT NULL;
            """
            self.cur.executescript(sql)
        sql = """
        UPDATE version SET version=3;
        """
        self._execute(sql)

    # IMAGES

    def make_images_table(self):
        sql = f"""
        CREATE TABLE IF NOT EXISTS {self.table} (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            filepath TEXT UNIQUE,
            times_used INTEGER DEFAULT 0,
            total_times_used INTEGER DEFAULT 0,
            active BOOLEAN DEFAULT TRUE,
            is_directory BOOLEAN DEFAULT FALSE,
            include_subdirectories BOOLEAN DEFAULT FALSE,
            ephemeral BOOLEAN DEFAULT FALSE,
            is_eagle_directory BOOLEAN DEFAULT FALSE,
            eagle_folder_data TEXT DEFAULT NULL,
            color_cache JSON DEFAULT NULL
        );"""
        self.cur.execute(sql)

    def get_image_tables(self):
        sql = """
        SELECT name
        FROM sqlite_master
        WHERE type='table' AND name LIKE 'images_%';
        """
        return [row["name"][7:] for row in self._fetch_all(sql)]

    def get_all_images(self) -> Iterator[dict]:
        sql = f"""
        SELECT * FROM {self.table} AND is_directory=0 ORDER BY filepath;
        """
        return self._fetch_all(sql)

    def get_all_active_images(self) -> Iterator[dict]:
        sql = f"""
        SELECT * FROM {self.table} WHERE active=1 AND is_directory=0;
        """
        return self._fetch_all(sql)

    def get_all_active_count(self) -> int:
        sql = f"""
        SELECT COUNT(*) FROM {self.table} WHERE active=1 AND is_directory=0;
        """
        return self._scalar(sql)

    def get_random_image(self, increment: bool = True) -> str:
        sql = f"""
        SELECT filepath FROM {self.table} WHERE active=1 AND is_directory=0 ORDER BY RANDOM() LIMIT 1;
        """
        result = self._fetch_one(sql)
        filepath = result["filepath"]
        if increment:
            self.increment_times_used(filepath)
        self.normalize_times_used()
        return filepath

    def get_random_image_v2(self, increment: bool = True) -> str:
        if self.ids is None:
            sql = f"""
            SELECT id FROM {self.table} WHERE active=1 AND is_directory=0;
            """
            self.ids = self.cur.execute(sql).fetchall()
        sql = f"""
        SELECT filepath FROM {self.table} WHERE id=?;
        """
        result = self._fetch_one(sql, [choice(self.ids)[0]])
        filepath = result["filepath"]
        if increment:
            self.increment_times_used(filepath)
        self.normalize_times_used()
        return filepath

    def get_random_image_with_weighting(self, increment: bool = True) -> str:
        # Get all images and the times they've been used
        sql = f"""
        SELECT filepath, times_used 
        FROM {self.table} 
        WHERE active=1 AND is_directory=0;
        """
        images = self.cur.execute(sql).fetchall()
        # Break out filepaths and times_used into their own lists
        filepaths, times_used = zip(*[(im[0], im[1]) for im in images])
        # Invert times_used, so we can use it as weights
        max_times_used = max(times_used)
        weights = [max_times_used - w + 1 for w in times_used]
        # Pick a random image with the generated weights
        filepath = choices(filepaths, weights=weights)[0]
        if increment:
            self.increment_times_used(filepath)
        self.normalize_times_used()
        return filepath

    def get_random_image_from_least_used(self, increment: bool = True) -> str:
        # Get all images and the times they've been used
        sql = f"""
        SELECT filepath, times_used 
        FROM {self.table} 
        WHERE active=1 AND is_directory=0;
        """
        images = self.cur.execute(sql).fetchall()
        # Sort into buckets by times used
        weights_dict = defaultdict(list)
        for filepath, times_used in images:
            weights_dict[times_used].append(filepath)
        # Get the least used images and pick a random image from that
        least_times_used = min(weights_dict)
        filepath = choice(weights_dict[least_times_used])
        if increment:
            # Increase the counter for how many times this image has been used and return
            self.increment_times_used(filepath)
        self.normalize_times_used()
        return filepath

    def increment_times_used(self, filepath: str) -> None:
        # TODO add normalization of times_used values
        sql = f"""
        UPDATE {self.table}
        SET times_used = times_used + 1,
            total_times_used = total_times_used + 1
        WHERE filepath=?;
        """
        self.cur.execute(sql, [filepath])

    def normalize_times_used(self):
        sql = f"""
        WITH least_used AS (
            SELECT min(times_used) AS m
            FROM {self.table}
            WHERE is_directory=0 AND active=1
        )
        UPDATE {self.table} 
        SET times_used = times_used - (SELECT m FROM least_used)
        WHERE is_directory=0 AND active=1;
        """
        self.cur.execute(sql)

    def get_active_folders(self) -> Iterator[dict]:
        sql = f"""
        SELECT filepath, include_subdirectories, is_eagle_directory, eagle_folder_data 
        FROM {self.table} WHERE active=1 AND is_directory=1;
        """
        return self._fetch_all(sql)

    def get_folder_info(self, dir_path: str) -> Optional[dict]:
        sql = f"""
        SELECT filepath, include_subdirectories, is_eagle_directory, eagle_folder_data
        FROM {self.table}
        WHERE active=1 AND is_directory=1 AND filepath=?;
        """
        return self._fetch_one(sql, [dir_path])

    def add_images(self, filepaths: Sequence[str], ephemeral: bool = False):
        sql = f"""
        INSERT INTO {self.table}(filepath, ephemeral)
        VALUES (?, ?)
        ON CONFLICT (filepath) DO NOTHING;
        """
        self.cur.executemany(sql, [(f, ephemeral) for f in filepaths])

    def add_directory(self, dir_path: str, include_subdirectories: bool = True):
        sql = f"""
        INSERT INTO {self.table}(filepath, is_directory, include_subdirectories)
        VALUES (?, ?, ?)
        ON CONFLICT (filepath) DO NOTHING;
        """
        self.cur.execute(sql, [dir_path, True, include_subdirectories])

    def add_eagle_folder(self, eagle_library_path: str, eagle_folder_data: dict[str, str]) -> dict[str, str]:
        sql = f"""
        SELECT eagle_folder_data
        FROM {self.table}
        WHERE filepath = ?;
        """
        data = self._scalar(sql, [eagle_library_path])
        if data is None:
            sql = f"""
            INSERT INTO {self.table}(filepath, is_directory, is_eagle_directory, eagle_folder_data)
            VALUES (?, ?, ?, ?)
            ON CONFLICT (filepath) DO NOTHING;
            """
            self.cur.execute(sql, [eagle_library_path, True, True, json.dumps(eagle_folder_data)])
            return eagle_folder_data

        d = json.loads(data)
        d.update(eagle_folder_data)
        sql = f"""
        UPDATE {self.table}
        SET eagle_folder_data = ?
        WHERE filepath = ?;
        """
        self.cur.execute(sql, [json.dumps(d), eagle_library_path])
        return d

    def remove_ephemeral_images(self):
        sql = """
        DELETE FROM {self.table} WHERE ephemeral=1;
        """
        self.cur.execute(sql)

    def remove_ephemeral_images_in_folder(self, dir_path: str):
        sql = f"""
        DELETE FROM {self.table} 
        WHERE filepath LIKE ?
          AND is_directory=0
          AND ephemeral=1;
        """
        self._execute(sql, [dir_path + "%"])

    def set_image_to_inactive(self, filepath: str):
        sql = f"""
        UPDATE {self.table} SET active=false WHERE filepath=?;
        """
        filepath = filepath.replace("\\", "/")
        ret = self._execute(sql, [filepath])
        if ret.rowcount == 0:
            print(f"Failed to set image to inactive: {filepath}", file=sys.stderr)

    def delete_image(self, filepath: str):
        sql = f"""
        DELETE FROM {self.table} WHERE filepath=?;
        """
        filepath = filepath.replace("\\", "/")
        ret = self._execute(sql, [filepath])
        if ret.rowcount == 0:
            print(f"Failed to delete image from database: {filepath}", file=sys.stderr)

    def get_common_color_cache(self, filepath: str) -> list[tuple[int, int, int]] | None:
        sql = f"""
        SELECT color_cache FROM {self.table} WHERE filepath=?;
        """
        filepath = filepath.replace("\\", "/")
        color_cache = self._fetch_one(sql, [filepath])["color_cache"]
        return json.loads(color_cache) if color_cache is not None else None

    def set_common_color_cache(self, filepath: str, color_cache: list[tuple[int, int, int]]):
        sql = f"""
        UPDATE {self.table} SET color_cache=? WHERE filepath=?;
        """
        filepath = filepath.replace("\\", "/")
        ret = self._execute(sql, [json.dumps(color_cache), filepath])
        if ret.rowcount == 0:
            print(f"Failed to set color cache for image: {filepath}", file=sys.stderr)

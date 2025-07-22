import json
import logging
import random
import re
import sqlite3
import string
from collections import OrderedDict, defaultdict
from random import choice, choices
from sqlite3 import Cursor, OperationalError
from typing import Optional, Iterator, Union, Sequence, Any

logger = logging.getLogger(__name__)


class Db:
    table_id = None
    conn, cur = None, None

    def __init__(self, file_list: str = None, filename: str = "database/main.db", auto_commit: bool = True,
                 auto_close: bool = True):
        """
        :param file_list: If defined, will be used to identify the correct table to do all further queries against.
            Leave undefined only in cases where querying image tables isn't needed. E.g., during DB migrations
        :param filename:
        :param auto_commit:
        :param auto_close:
        """
        self.file_list = file_list
        self.filename = filename
        self.auto_commit = auto_commit
        self.auto_close = auto_close

    def __enter__(self):
        self.connect()
        if self.file_list and not self.table_id:
            self.table_id = self.get_table_id(self.file_list)
            if not self.table_id:
                self.make_images_table()
        return self

    def connect(self):
        self.conn = sqlite3.connect(self.filename)
        self.cur = self.conn.cursor()

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

    def _execute(self, sql, params: list[str] = None) -> Cursor:
        args = [sql]
        if params is not None:
            args.append(params)
        return self.cur.execute(*args)

    def _scalar(self, sql, params: list[str] = None) -> Union[str, int, bool, None]:
        result = self._execute(sql, params).fetchone()
        if result is None:
            return None
        return result[0]

    def _fetch_one(self, sql, params: list[str] = None) -> Optional[dict]:
        result = self._execute(sql, params).fetchone()
        if result is None:
            return None
        return self._row_to_dict(result)

    def _fetch_all(self, sql, params: list[str] = None) -> Iterator[dict]:
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
        if version < 4:
            self.version4()
        if version < 5:
            self.version5()

    def get_version(self) -> int:
        sql = "SELECT version FROM version;"
        try:
            return self._fetch_one(sql)["version"]
        except OperationalError:
            # No table found, return version=0
            return 0

    def version1(self):
        print("Apply DB migration version 1...")
        sql = """
        CREATE TABLE IF NOT EXISTS version (
            version INTEGER
        );
        INSERT INTO version (version) VALUES (1);
        """
        self.cur.executescript(sql)

    def version2(self):
        print("Apply DB migration version 2...")
        image_tables = self.get_image_tables()
        if image_tables is not None:
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
        print("Apply DB migration version 3...")
        image_tables = self.get_image_tables()
        if image_tables is not None:
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

    def version4(self):
        print("Apply DB migration version 4...")
        # Create file_lists table
        self._execute("""
        CREATE TABLE IF NOT EXISTS file_lists
        (
            name     TEXT,
            table_id TEXT
        );
        """)

        # Find all tables starting with "image_"
        image_tables = self._fetch_all("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'image_%';")
        image_tables = [row["name"] for row in image_tables]

        for original_name in image_tables:
            # Generate a random suffix
            suffix = ''.join(random.choices(string.ascii_lowercase + string.digits, k=6))
            new_table_name = f"{original_name}_{suffix}"

            # Rename the table
            self._execute(f'ALTER TABLE "{original_name}" RENAME TO "{new_table_name}"')

            # Create display name
            display_name = original_name
            if display_name.startswith("images_"):
                display_name = display_name[len("images_"):]
            display_name = display_name.replace("_", " ").title()

            # Insert into file_lists
            self._execute("INSERT INTO file_lists (name, table_id) VALUES (?, ?)", (display_name, new_table_name))

        self._execute("""
        UPDATE version SET version=4;
        """)

    def version5(self):
        print("Apply DB migration version 5...")
        """Add hidden column to image tables"""
        
        # Find all tables starting with "image_"
        image_tables = self._fetch_all("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'image_%';")
        image_tables = [row["name"] for row in image_tables]

        for name in image_tables:
            self._execute(f"""
            ALTER TABLE {name} ADD COLUMN hidden BOOLEAN DEFAULT FALSE;
            """)

        self._execute("""
        UPDATE version SET version=5;
        """)

    # IMAGES

    def get_table_id(self, file_list: str) -> str:
        sql = """
            SELECT table_id 
            FROM file_lists 
            WHERE name=?
        """
        return self._scalar(sql, (file_list,))

    def make_images_table(self):
        normalized_name = re.sub(r"[^a-z_]", "", self.file_list.lower().replace(" ", "_"))
        suffix = ''.join(random.choices(string.ascii_lowercase + string.digits, k=6))
        self.table_id = f"images_{normalized_name}_{suffix}"

        self._execute(
            "INSERT INTO file_lists (name, table_id) VALUES (?, ?)",
            (self.file_list, self.table_id),
        )
        self._execute(f"""
        CREATE TABLE IF NOT EXISTS {self.table_id} (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            filepath TEXT UNIQUE,
            times_used INTEGER DEFAULT 0,
            total_times_used INTEGER DEFAULT 0,
            active BOOLEAN DEFAULT TRUE,
            is_directory BOOLEAN DEFAULT FALSE,
            include_subdirectories BOOLEAN DEFAULT FALSE,
            ephemeral BOOLEAN DEFAULT FALSE,
            hidden BOOLEAN DEFAULT FALSE,
            is_eagle_directory BOOLEAN DEFAULT FALSE,
            eagle_folder_data TEXT DEFAULT NULL,
            color_cache JSON DEFAULT NULL
        );""")

    def get_image_tables(self) -> list[str] | None:
        file_lists_table_exists = self._scalar("""
            SELECT 1
            FROM sqlite_master
            WHERE type = 'table' AND name = 'file_lists'
        """)
        if not file_lists_table_exists:
            return None

        sql = """
        SELECT name FROM file_lists
        """
        return [row["name"] for row in self._fetch_all(sql)]

    def get_rows(self, sort_key: str, sort_asc: bool, offset: int, limit: int, **kwargs) -> Iterator[dict]:
        sql = f"""
        SELECT * FROM {self.table_id}
        WHERE TRUE
        """
        filter_sql, params = self._add_rows_filter(**kwargs)
        sql += filter_sql

        # Map header to DB column
        sort_column_map = {
            "Active": "active",
            "Is Directory": "is_directory",
            "Incl. Subdirs": "include_subdirectories",
            "Ephemeral": "ephemeral",
            "Times Used": "times_used",
            "Total Times Used": "total_times_used",
        }
        order_by = sort_column_map.get(sort_key, "filepath")
        sql += f"""
        ORDER BY {order_by} {"DESC" if not sort_asc else ""}
        LIMIT {limit} OFFSET {offset};
        """
        return self._fetch_all(sql, params)

    def get_row_count(self, **kwargs) -> int:
        sql = f"""
        SELECT COUNT(*) FROM {self.table_id}
        WHERE TRUE
        """
        filter_sql, params = self._add_rows_filter(**kwargs)
        sql += filter_sql
        return self._scalar(sql, params)

    @staticmethod
    def _add_rows_filter(
            file_path_match: str = None,
            is_active: bool = None,
            is_directory: bool = None,
            is_hidden: bool = None,
            include_ephemeral_images: bool = False,
    ) -> tuple[str, list[Any]]:
        sql = ""
        params = []
        if file_path_match:
            sql += "AND filepath LIKE ?\n"
            params.append('%' + file_path_match + '%')
        if is_active is not None:
            sql += "AND active=?\n"
            params.append(is_active)
        if is_directory is not None:
            sql += "AND is_directory=?\n"
            params.append(is_directory)
        if is_hidden is not None:
            sql += "AND hidden=?\n"
            params.append(is_hidden)
        if not include_ephemeral_images:
            sql += "AND ephemeral=?\n"
            params.append(False)
        return sql, params

    def get_all_images(self) -> Iterator[dict]:
        sql = f"""
        SELECT * FROM {self.table_id} WHERE is_directory=0 AND hidden=0 ORDER BY filepath;
        """
        return self._fetch_all(sql)

    def get_all_active_images(self) -> Iterator[dict]:
        sql = f"""
        SELECT * FROM {self.table_id} WHERE active=1 AND is_directory=0 AND hidden=0;
        """
        return self._fetch_all(sql)

    def get_all_active_count(self) -> int:
        sql = f"""
        SELECT COUNT(*) FROM {self.table_id} WHERE active=1 AND is_directory=0 AND hidden=0;
        """
        return self._scalar(sql)

    def get_all_ephemeral_images(self, folder_name: str) -> Iterator[dict]:
        sql = f"""
        SELECT * FROM {self.table_id}
        WHERE ephemeral=1 AND is_directory=0 AND hidden=0
        """
        if folder_name:
            sql += f"AND filepath LIKE '{folder_name}%'"
        return self._fetch_all(sql)

    def get_random_image(self, increment: bool = True) -> str:
        sql = f"""
        SELECT filepath
        FROM {self.table_id}
        WHERE active=1 AND is_directory=0 AND hidden=0
        ORDER BY RANDOM() LIMIT 1;
        """
        result = self._fetch_one(sql)
        filepath = result["filepath"]
        if increment:
            self.increment_times_used(filepath)
        self.normalize_times_used()
        return filepath

    def get_random_image_with_weighting(self, increment: bool = True) -> str:
        # Get all images and the times they've been used
        sql = f"""
        SELECT filepath, times_used 
        FROM {self.table_id} 
        WHERE active=1 AND is_directory=0 AND hidden=0;
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
        FROM {self.table_id} 
        WHERE active=1 AND is_directory=0 AND hidden=0;
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
        sql = f"""
        UPDATE {self.table_id}
        SET times_used = times_used + 1,
            total_times_used = total_times_used + 1
        WHERE filepath=?;
        """
        self.cur.execute(sql, [filepath])

    def normalize_times_used(self):
        sql = f"""
        WITH least_used AS (
            SELECT min(times_used) AS m
            FROM {self.table_id}
            WHERE is_directory=0 AND active=1
        )
        UPDATE {self.table_id} 
        SET times_used = times_used - (SELECT m FROM least_used)
        WHERE is_directory=0 AND active=1;
        """
        self.cur.execute(sql)

    def get_active_folders(self, folder_name: str = None) -> Iterator[dict]:
        sql = f"""
        SELECT filepath, include_subdirectories, is_eagle_directory, eagle_folder_data 
        FROM {self.table_id} 
        WHERE active=1
          AND is_directory=1
          AND hidden=0
        """
        params = []
        if folder_name:
            sql += "  AND filepath = ?"
            params.append(folder_name)
        return self._fetch_all(sql, params)

    def get_folder_info(self, dir_path: str) -> Optional[dict]:
        sql = f"""
        SELECT filepath, include_subdirectories, is_eagle_directory, eagle_folder_data
        FROM {self.table_id}
        WHERE active=1 AND is_directory=1 AND filepath=?;
        """
        return self._fetch_one(sql, [dir_path])

    def add_images(self, filepaths: Sequence[str], ephemeral: bool = False):
        sql = f"""
        INSERT INTO {self.table_id}(filepath, ephemeral)
        VALUES (?, ?)
        ON CONFLICT(filepath) DO UPDATE SET hidden=FALSE;
        """
        self.cur.executemany(sql, [(f, ephemeral) for f in filepaths])

    def add_directory(self, dir_path: str, include_subdirectories: bool = True):
        sql = f"""
        INSERT INTO {self.table_id}(filepath, is_directory, include_subdirectories)
        VALUES (?, ?, ?)
        ON CONFLICT (filepath) DO NOTHING;
        """
        self.cur.execute(sql, [dir_path, True, include_subdirectories])

    def add_eagle_folder(self, eagle_library_path: str, eagle_folder_data: dict[str, str]) -> dict[str, str]:
        sql = f"""
        SELECT eagle_folder_data
        FROM {self.table_id}
        WHERE filepath = ?;
        """
        data = self._scalar(sql, [eagle_library_path])
        if data is None:
            sql = f"""
            INSERT INTO {self.table_id}(filepath, is_directory, is_eagle_directory, eagle_folder_data)
            VALUES (?, ?, ?, ?)
            ON CONFLICT (filepath) DO NOTHING;
            """
            self.cur.execute(sql, [eagle_library_path, True, True, json.dumps(eagle_folder_data)])
            return eagle_folder_data

        d = json.loads(data)
        d.update(eagle_folder_data)
        sql = f"""
        UPDATE {self.table_id}
        SET eagle_folder_data = ?
        WHERE filepath = ?;
        """
        self.cur.execute(sql, [json.dumps(d), eagle_library_path])
        return d

    def hide_images(self, filepaths: Sequence[str]):
        sql = f"""
        UPDATE {self.table_id}
        SET hidden=TRUE
        WHERE filepath IN ({','.join(['?'] * len(filepaths))});
        """
        self.cur.execute(sql, list(filepaths))

    def remove_ephemeral_images(self):
        sql = """
        DELETE FROM {self.table_id} WHERE ephemeral=1;
        """
        self.cur.execute(sql)

    def remove_ephemeral_images_in_folder(self, dir_path: str):
        sql = f"""
        DELETE FROM {self.table_id} 
        WHERE filepath LIKE ?
          AND is_directory=0
          AND ephemeral=1;
        """
        self._execute(sql, [dir_path + "%"])

    def set_active_flag(self, filepath: str, active: bool):
        sql = f"""
        UPDATE {self.table_id} SET active=? WHERE filepath=?;
        """
        filepath = filepath.replace("\\", "/")
        ret = self._execute(sql, [active, filepath])
        if ret.rowcount == 0:
            logger.error(f"Failed to set image to inactive: {filepath}")

    def delete_image(self, filepath: str):
        sql = f"""
        DELETE FROM {self.table_id} WHERE filepath=?;
        """
        filepath = filepath.replace("\\", "/")
        ret = self._execute(sql, [filepath])
        if ret.rowcount == 0:
            logger.error(f"Failed to delete image from database: {filepath}")

    def get_common_color_cache(self, filepath: str) -> list[tuple[int, int, int]] | None:
        sql = f"""
        SELECT color_cache FROM {self.table_id} WHERE filepath=?;
        """
        filepath = filepath.replace("\\", "/")
        color_cache = self._fetch_one(sql, [filepath])["color_cache"]
        return json.loads(color_cache) if color_cache is not None else None

    def set_common_color_cache(self, filepath: str, color_cache: list[tuple[int, int, int]]):
        sql = f"""
        UPDATE {self.table_id} SET color_cache=? WHERE filepath=?;
        """
        filepath = filepath.replace("\\", "/")
        ret = self._execute(sql, [json.dumps(color_cache), filepath])
        if ret.rowcount == 0:
            logger.error(f"Failed to set color cache for image: {filepath}")

import os.path
import sqlite3
from collections import OrderedDict
from random import choice
from sqlite3 import Cursor
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

    # IMAGES

    def make_images_table(self):
        sql = f"""
        CREATE TABLE IF NOT EXISTS {self.table} (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            filepath TEXT UNIQUE,
            active BOOLEAN DEFAULT TRUE,
            is_directory BOOLEAN DEFAULT FALSE,
            include_subdirectories BOOLEAN DEFAULT FALSE,
            ephemeral BOOLEAN DEFAULT FALSE,
            is_eagle_directory BOOLEAN DEFAULT FALSE,
            eagle_folder_name TEXT DEFAULT NULL,
            eagle_folder_id TEXT DEFAULT NULL
        );"""
        self.cur.execute(sql)

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

    def get_random_image(self) -> str:
        sql = f"""
        SELECT filepath FROM {self.table} WHERE active=1 AND is_directory=0 ORDER BY RANDOM() LIMIT 1;
        """
        result = self._fetch_one(sql)
        return result["filepath"]

    def get_random_image_v2(self) -> str:
        if self.ids is None:
            sql = f"""
            SELECT id FROM {self.table} WHERE active=1 AND is_directory=0;
            """
            self.ids = self.cur.execute(sql).fetchall()
        sql = f"""
        SELECT filepath FROM {self.table} WHERE id=?;
        """
        result = self._fetch_one(sql, [choice(self.ids)[0]])
        return result["filepath"]

    def get_active_folders(self) -> Iterator[dict]:
        sql = f"""
        SELECT filepath, include_subdirectories, is_eagle_directory, eagle_folder_id 
        FROM {self.table} WHERE active=1 AND is_directory=1;
        """
        return self._fetch_all(sql)

    def add_images(self, filepaths: Sequence[str], ephemeral: bool = False) -> None:
        sql = f"""
        INSERT INTO {self.table}(filepath, ephemeral)
        VALUES (?, ?)
        ON CONFLICT (filepath) DO NOTHING;
        """
        self.cur.executemany(sql, [(f, ephemeral) for f in filepaths])

    def add_directory(self, dir_path: str, include_subdirectories: bool = True) -> None:
        sql = f"""
        INSERT INTO {self.table}(filepath, is_directory, include_subdirectories)
        VALUES (?, ?, ?)
        ON CONFLICT (filepath) DO NOTHING;
        """
        self.cur.execute(sql, [dir_path, True, include_subdirectories])

    def add_eagle_folder(self, eagle_library_path: str, eagle_folder_name: str, eagle_folder_id: str) -> None:
        sql = f"""
        INSERT INTO {self.table}(filepath, is_directory, is_eagle_directory, eagle_folder_name, eagle_folder_id)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT (filepath) DO NOTHING;
        """
        self.cur.execute(sql, [eagle_library_path, True, True, eagle_folder_name, eagle_folder_id])

    def remove_ephemeral_images(self):
        sql = """
        DELETE FROM {self.table} WHERE ephemeral=1;
        """
        self.cur.execute(sql)

    def set_image_to_inactive(self, filepath: str):
        sql = f"""
        UPDATE {self.table} SET active=false WHERE filepath=?;
        """
        self._execute(sql, [filepath])

    def delete_image(self, filepath: str):
        sql = f"""
        DELETE FROM {self.table} WHERE filepath=?;
        """
        self._execute(sql, [filepath])

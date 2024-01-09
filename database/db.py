import os.path
import sqlite3
from collections import OrderedDict
from random import choice
from sqlite3 import Cursor
from typing import Optional, Iterator, Union, Sequence

from database.build_db import build_db


class Db:
    table = None
    auto_commit = False
    auto_close = False
    ids = None

    def __init__(self, table="images", filename="database/main.db"):
        self.table = table
        if not os.path.isfile(filename):
            build_db()
        self.conn = sqlite3.connect(filename)
        self.cur = self.conn.cursor()

    def __enter__(self, auto_commit=True, auto_close=True):
        self.auto_commit = True
        self.auto_close = True
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

    def get_all_images(self) -> Iterator[dict]:
        sql = f"""
            SELECT * FROM {self.table} ORDER BY filepath;
        """
        return self._fetch_all(sql)

    def get_all_active_images(self) -> Iterator[dict]:
        sql = f"""
            SELECT * FROM {self.table} WHERE active=1;
        """
        return self._fetch_all(sql)

    def get_all_active_count(self) -> int:
        sql = f"""
            SELECT COUNT(*) FROM {self.table} WHERE active=1;
        """
        return self._scalar(sql)

    def get_random_image(self) -> str:
        sql = f"""
            SELECT filepath FROM {self.table} ORDER BY RANDOM() LIMIT 1;
        """
        result = self._fetch_one(sql)
        return result["filepath"]

    def get_random_image_v2(self) -> str:
        if self.ids is None:
            sql = f"""
                SELECT id FROM {self.table};
            """
            self.ids = self.cur.execute(sql).fetchall()
        sql = f"""
            SELECT filepath FROM {self.table} WHERE id=?;
        """
        result = self._fetch_one(sql, [choice(self.ids)[0]])
        return result["filepath"]

    def add_images(self, filepaths: Sequence[str]):
        sql = f"""
        INSERT INTO {self.table}(filepath)
        VALUES (?)
        ON CONFLICT (filepath) DO NOTHING;
        """
        self.cur.executemany(sql, [(f,) for f in filepaths])

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

import logging
import os
import shutil
from configparser import ConfigParser
from time import perf_counter_ns

import wx

from db import Db
from eagle import get_file_list_in_eagle_folder

logger = logging.getLogger(__name__)
__config = None
perf_list = []


def load_config() -> ConfigParser:
    global __config
    if not __config:
        __config = ConfigParser()
        if not os.path.isfile("conf/config.ini"):
            shutil.copy("conf/config.ini.dist", "conf/config.ini")
        __config.read("conf/config.ini")
    return __config


class PerformanceTimer:
    """Class to do my own hand-blown performance timing."""

    def __init__(self):
        self.perf_list = [("Start", perf_counter_ns())]

    def increment(self, title: str):
        self.perf_list.append((title, perf_counter_ns()))

    inc = increment

    def output_to_log(self, title: str = "Total:"):
        logger.info("Performance times:")
        for i, perf_tuple in enumerate(self.perf_list):
            if i == 0:
                continue
            t1, t2 = self.perf_list[i - 1][1], self.perf_list[i][1]
            logger.info(f"  {perf_tuple[0]} {(t2 - t1) / 1_000_000:.2f} ms")
        t1, t2 = self.perf_list[0][1], self.perf_list[-1][1]
        logger.info(f"{title} {(t2 - t1) / 1_000_000:.2f} ms")


def perf(title: str = ""):
    global perf_list
    if not title:
        title = "Start"
        perf_list = []
    perf_list.append((title, perf_counter_ns()))


def log_perf(title: str = "Total:"):
    logger.info("Performance times:")
    for i, perf_tuple in enumerate(perf_list):
        if i == 0:
            continue
        t1, t2 = perf_list[i - 1][1], perf_list[i][1]
        logger.info(f"  {perf_tuple[0]} {(t2 - t1) / 1_000_000:.2f} ms")
    t1, t2 = perf_list[0][1], perf_list[-1][1]
    logger.info(f"{title} {(t2 - t1) / 1_000_000:.2f} ms")


def error_dialog(parent: wx.Frame, message: str, title: str = None):
    with wx.MessageDialog(parent, message, "Error" if title is None else title,
                          style=wx.OK | wx.ICON_ERROR) as dialog:
        dialog.ShowModal()


def refresh_ephemeral_images(db: Db, folder_name: str = None, force_refresh: bool = False):
    # TODO Add checking for more precise folder prefixes.
    #  Consider whether `include_subdirectories` is set, or if folders are inside other folders.
    if folder_name and not os.path.isdir(folder_name):
        logger.warning("Couldn't access folder, skipping refreshing ephemeral images")
    folders = list(db.get_active_folders(folder_name))
    new_file_paths = []
    for folder in folders:
        logger.info(f"Refreshing ephemeral images for {folder['filepath']}")
        if folder["is_eagle_directory"]:
            new_file_paths += get_file_list_in_eagle_folder(
                folder["filepath"], folder["eagle_folder_data"], show_progress_dialog=force_refresh,
            )
        else:
            new_file_paths += get_file_list_in_folder(folder["filepath"], folder["include_subdirectories"])
    new_file_paths = set(new_file_paths)
    ephemeral_images = db.get_all_ephemeral_images(folder_name)
    existing_file_paths = set([f["filepath"] for f in ephemeral_images])
    file_paths_to_add = new_file_paths.difference(existing_file_paths)
    if file_paths_to_add:
        db.add_images(file_paths_to_add, ephemeral=True)
    if new_file_paths:
        file_paths_to_hide = existing_file_paths.difference(new_file_paths)
        if file_paths_to_hide:
            db.hide_images(file_paths_to_hide)
    else:
        logger.warning("New file paths is empty. Possibly due to issue connecting to storage. Not hiding any images.")


def get_file_list_in_folder(dir_path: str, include_subfolders: bool) -> list[str]:
    file_paths = []
    config = load_config()
    allowed_extensions = ["." + f.strip(" ").strip(".")
                          for f in config.get("Advanced", "Image types").lower().split(",")]
    for dir_path, dir_names, filenames in os.walk(dir_path):
        # If we don't want to include subfolders, clearing the `dir_names` list will stop os.walk() at the
        # top-level directory.
        if not include_subfolders:
            dir_names.clear()
        for filename in filenames:
            if filename == "Thumbs.db":
                continue
            ext = os.path.splitext(filename)[1].lower()
            if ext in allowed_extensions:
                file_paths.append(os.path.join(dir_path, filename).replace("\\", "/"))
    return file_paths

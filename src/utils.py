import json
import logging
import os
import shutil
from configparser import ConfigParser
from glob import glob
from time import perf_counter_ns
from typing import Sequence, Optional

import wx
import yaml

from db import Db

logging_config_set = False
__config = None
perf_list = []
processing_eagle = False


def get_logger(name: str) -> logging.Logger:
    global logging_config_set

    if not logging_config_set:
        # Load logging config file
        with open("conf/logging.yaml", "r") as f:
            raw = f.read()

        # Expand out env vars and apply config
        expanded = os.path.expandvars(raw).replace("\\", "/")
        config = yaml.safe_load(expanded)
        logging.config.dictConfig(config)
        logging_config_set = True

    # Find the file_handler so we can use it later
    file_handler = None
    logger = logging.getLogger(name)
    for handler in logging.getLogger().handlers:
        if isinstance(handler, logging.FileHandler):
            file_handler = handler
            break

    # Make the logging directory if needed
    if file_handler:
        log_dir_name = os.path.dirname(file_handler.baseFilename)
        os.makedirs(log_dir_name, exist_ok=True)

    # If in debug mode, or file_handler isn't set, also log to the console
    if os.getenv("PYWALLPAPER_DEBUG_MODE") or file_handler is None:
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.DEBUG)
        # Use the same formatter as defined in the YAML
        if file_handler is None:
            formatter = logging.Formatter("[%(asctime)s] %(levelname)s in %(name)s: %(message)s")
        else:
            formatter = file_handler.formatter
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)

    logger.info("Logger initialized")
    if file_handler is None:
        logger.warning("No file handler is configured. Logging to the console.")
    return logger

logger = get_logger(__name__)


def load_config():
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


def refresh_ephemeral_images(db_obj: Db, folder_list: list[str] = None):
    with db_obj as db:
        folders = list(db.get_active_folders()) if folder_list is None else folder_list
        new_file_paths = []
        for folder in folders:
            logger.info(f"Refreshing ephemeral images for {folder['filepath']}")
            if folder["is_eagle_directory"]:
                new_file_paths += get_file_list_in_eagle_folder(folder["filepath"], folder["eagle_folder_data"])
            else:
                new_file_paths += get_file_list_in_folder(folder["filepath"], folder["include_subdirectories"])
        new_file_paths = set(new_file_paths)
        ephemeral_images = db.get_all_ephemeral_images()
        existing_file_paths = set([f["filepath"] for f in ephemeral_images])
        file_paths_to_add = new_file_paths.difference(existing_file_paths)
        if file_paths_to_add:
            db.add_images(file_paths_to_add, ephemeral=True)
        file_paths_to_hide = existing_file_paths.difference(new_file_paths)
        if file_paths_to_hide:
            db.hide_images(file_paths_to_hide)


def get_file_list_in_folder(dir_path: str, include_subfolders: bool) -> Sequence[str]:
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

def get_file_list_in_eagle_folder(dir_path: str, folder_ids: list[str]) -> Sequence[str]:
    global processing_eagle
    processing_eagle = True
    progress_bar = wx.ProgressDialog("Loading Eagle library", "Scanning image folders...",
                                     style=wx.PD_APP_MODAL | wx.PD_AUTO_HIDE | wx.PD_ELAPSED_TIME | wx.PD_CAN_ABORT)
    try:
        file_list = []
        folder_list = glob(os.path.join(dir_path, "images/*"))
        total_folders = len(folder_list)
        progress_bar.SetRange(total_folders)
        progress_bar.Update(0, f"Scanning image folders... (0/{total_folders})")
        for i, folder_path in enumerate(folder_list, start=1):
            # if i % 100 == 0:
            #     print(f"Scanning Eagle folders: {i}/{total_folders}")
            file_path = parse_eagle_folder(folder_path, folder_ids, ignore_lock=True)
            if file_path is not None:
                file_list.append(file_path)
            pb_status = progress_bar.Update(i, newmsg=f"Scanning image folders... ({i}/{total_folders})")
            # If the user clicked Abort, return early
            if not pb_status[0]:
                return []
        return file_list
    finally:
        progress_bar.Close()
        processing_eagle = False


def parse_eagle_folder(dir_path: str, folder_ids: list[str], ignore_lock: bool = False) -> Optional[str]:
    global processing_eagle
    if processing_eagle and not ignore_lock:
        return None
    file_list = glob(os.path.join(dir_path, "*.*"))
    if os.path.join(dir_path, "metadata.json") not in file_list:
        logger.warning(f"No metadata.json file found in {dir_path}")
        logger.warning(file_list)
        return None
    try:
        with open(os.path.join(dir_path, "metadata.json"), "rb") as f:
            metadata = json.load(f)
    except json.JSONDecodeError:
        logger.exception(f"Error when decoding {os.path.join(dir_path, 'metadata.json')}")
        return None
    # Skip if it's not a folder_id we care about
    try:
        if not set(folder_ids).intersection(metadata["folders"]):
            return None
    except TypeError:
        logger.exception("TypeError when intersecting folder sets")
        logger.error(folder_ids)
        logger.error(metadata["folders"])
        raise
    logger.debug(f"Loading image from {dir_path}...")
    for file_path in file_list:
        if file_path.endswith("metadata.json"):
            continue
        if len(file_list) > 2 and file_path.endswith("_thumbnail.png"):
            continue
        return file_path.replace("\\", "/")
    logger.error(f"No non-thumbnail image found in {dir_path}")
    return None


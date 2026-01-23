import json
import logging
import os
import shutil
from configparser import ConfigParser
from dataclasses import dataclass
from time import perf_counter_ns
from typing import Sequence, Optional

import wx

from db import Db

logger = logging.getLogger(__name__)
__config = None
perf_list = []
processing_eagle = False


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


def refresh_ephemeral_images(db: Db, folder_name: str = None):
    # TODO Add checking for more precise folder prefixes.
    #  Consider whether `include_subdirectories` is set, or if folders are inside other folders.
    if folder_name and not os.path.isdir(folder_name):
        logger.warning("Couldn't access folder, skipping refreshing ephemeral images")
    folders = list(db.get_active_folders(folder_name))
    new_file_paths = []
    for folder in folders:
        logger.info(f"Refreshing ephemeral images for {folder['filepath']}")
        if folder["is_eagle_directory"]:
            new_file_paths += get_file_list_in_eagle_folder(folder["filepath"], folder["eagle_folder_data"])
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
    global processing_eagle, _EAGLE_META_CACHE
    logger.debug(f"Size of _EAGLE_META_CACHE: {len(_EAGLE_META_CACHE)}")
    processing_eagle = True
    progress_bar = wx.ProgressDialog("Loading Eagle library", "Scanning image folders...",
                                     style=wx.PD_APP_MODAL | wx.PD_AUTO_HIDE | wx.PD_ELAPSED_TIME | wx.PD_CAN_ABORT)
    try:
        file_list = []
        loading_times = set()
        folder_list = os.listdir(os.path.join(dir_path, "images"))
        total_folders = len(folder_list)
        progress_bar.SetRange(total_folders)
        progress_bar.Update(0, f"Scanning image folders... (0/{total_folders})")
        for i, folder_name in enumerate(folder_list, start=1):
            # if i % 100 == 0:
            #     print(f"Scanning Eagle folders: {i}/{total_folders}")
            folder_path = os.path.join(dir_path, "images", folder_name)
            t1 = perf_counter_ns()
            file_path = parse_eagle_folder(folder_path, folder_ids, ignore_lock=True)
            t2 = perf_counter_ns()
            loading_times.add(t2 - t1)
            if file_path is not None:
                file_list.append(file_path)
            pb_status = progress_bar.Update(i, newmsg=f"Scanning image folders... ({i}/{total_folders})")
            # If the user clicked Abort, return early
            if not pb_status[0]:
                return []
        avg_loading_time = sum(loading_times) / len(loading_times)
        logger.debug(f"Average loading time: {avg_loading_time} ns")
        return file_list
    finally:
        progress_bar.Close()
        processing_eagle = False


@dataclass(frozen=True)
class _MetaCacheEntry:
    mtime_ns: int
    size: int
    matched: bool
    image_relpath: str | None

_EAGLE_META_CACHE: dict[str, _MetaCacheEntry] = {}


def _get_cached_eagle_entry(metadata_path: str) -> _MetaCacheEntry | None:
    try:
        st = os.stat(metadata_path)
    except FileNotFoundError:
        _EAGLE_META_CACHE.pop(metadata_path, None)
        return None

    entry = _EAGLE_META_CACHE.get(metadata_path)
    if entry and entry.mtime_ns == st.st_mtime_ns and entry.size == st.st_size:
        return entry
    return None


def _set_cached_eagle_entry(metadata_path: str, matched: bool, image_relpath: Optional[str]) -> None:
    st = os.stat(metadata_path)
    _EAGLE_META_CACHE[metadata_path] = _MetaCacheEntry(
        mtime_ns=st.st_mtime_ns,
        size=st.st_size,
        matched=matched,
        image_relpath=image_relpath,
    )


def parse_eagle_folder(dir_path: str, folder_ids: list[str], ignore_lock: bool = False) -> Optional[str]:
    global processing_eagle
    if processing_eagle and not ignore_lock:
        return None
    # Check if the metadata.json file has changed since the last time we scanned
    metadata_path = os.path.join(dir_path, "metadata.json")
    entry = _get_cached_eagle_entry(metadata_path)
    if entry:
        return entry.image_relpath
    # Load metadata.json first
    try:
        with open(metadata_path, "rb") as f:
            metadata = json.load(f)
    except json.JSONDecodeError:
        logger.exception(f"Error when decoding {os.path.join(dir_path, 'metadata.json')}")
        return None
    except FileNotFoundError:
        logger.warning(f"No metadata.json file found in {dir_path}")
        logger.warning(os.listdir(dir_path))
        return None
    # Skip if it's not a folder_id we care about
    try:
        if not set(folder_ids).intersection(metadata["folders"]):
            _set_cached_eagle_entry(metadata_path, matched=False, image_relpath=None)
            return None
    except TypeError:
        logger.exception("TypeError when intersecting folder sets")
        logger.error(folder_ids)
        logger.error(metadata["folders"])
        raise
    logger.debug(f"Loading image from {dir_path}...")
    file_list = os.listdir(dir_path)
    for file_name in file_list:
        if file_name.endswith("metadata.json"):
            continue
        if len(file_list) > 2 and file_name.endswith("_thumbnail.png"):
            continue
        file_path = os.path.join(dir_path, file_name).replace("\\", "/")
        _set_cached_eagle_entry(metadata_path, matched=True, image_relpath=file_path)
        return file_path
    logger.error(f"No non-thumbnail image found in {dir_path}")
    return None


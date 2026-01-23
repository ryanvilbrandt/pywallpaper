import json
import logging
import os
import zipfile
from dataclasses import dataclass
from time import perf_counter_ns
from typing import Optional, Union

import wx

logger = logging.getLogger(__name__)
processing_eagle = False


def get_file_list_in_eagle_folder(dir_path: str, folder_ids: list[str]) -> Union[set[str] | list[str]]:
    global processing_eagle, _EAGLE_META_CACHE
    _load_eagle_meta_cache()
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
            file_path = parse_eagle_folder(folder_path, folder_ids, ignore_lock=True, handle_cache=False)
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
        _save_eagle_meta_cache()
        processing_eagle = False


@dataclass(frozen=True)
class _MetaCacheEntry:
    mtime_ns: int
    size: int
    matched: bool
    image_relpath: str | None


_EAGLE_META_CACHE: dict[str, _MetaCacheEntry] = {}


def _load_eagle_meta_cache():
    if _EAGLE_META_CACHE:
        return
    if os.path.isfile("eagle_meta_cache.zip"):
        t1 = perf_counter_ns()
        with zipfile.ZipFile("eagle_meta_cache.zip", "r") as z:
            with z.open("eagle_meta_cache.json") as f:
                cache_data = json.load(f)
                for d in cache_data:
                    _EAGLE_META_CACHE[d["path"]] = _MetaCacheEntry(
                        mtime_ns=d["mtime_ns"],
                        size=d["size"],
                        matched=d["matched"],
                        image_relpath=d["image_relpath"]
                    )
        t2 = perf_counter_ns()
        logger.debug(f"Loaded eagle_meta_cache.zip in {t2 - t1} ns")

def _save_eagle_meta_cache():
    if not _EAGLE_META_CACHE:
        return
    t1 = perf_counter_ns()
    cache_data = [
        {
            "path": path,
            "mtime_ns": entry.mtime_ns,
            "size": entry.size,
            "matched": entry.matched,
            "image_relpath": entry.image_relpath,
        }
        for path, entry in _EAGLE_META_CACHE.items()
    ]
    with zipfile.ZipFile("eagle_meta_cache.zip", "w", compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr("eagle_meta_cache.json", json.dumps(cache_data, ensure_ascii=False))
    t2 = perf_counter_ns()
    logger.debug(f"Saved eagle_meta_cache.zip in {t2 - t1} ns")


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


def parse_eagle_folder(
        dir_path: str, folder_ids: list[str], ignore_lock: bool = False, handle_cache: bool = True
) -> Optional[str]:
    global processing_eagle
    if processing_eagle and not ignore_lock:
        return None
    if handle_cache:
        _load_eagle_meta_cache()
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
            if handle_cache:
                _save_eagle_meta_cache()
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
        if handle_cache:
            _save_eagle_meta_cache()
        return file_path
    logger.error(f"No non-thumbnail image found in {dir_path}")
    return None

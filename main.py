import ctypes
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from configparser import ConfigParser
from typing import Sequence, Union, Optional

import pystray
import win32api
import win32evtlog
import win32evtlogutil
import wx
from PIL import Image, ImageFont, ImageDraw, UnidentifiedImageError
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from database.db import Db

# Global variables
VERSION = "0.2.1"
SPI_SET_DESKTOP_WALLPAPER = 20


class PyWallpaper(wx.Frame):

    config = None
    table_name = None
    delay = None
    error_delay = None
    font = None
    temp_image_filename = None

    original_file_path = None
    cycle_timer = None
    observer = None

    # GUI Elements
    icon, add_filepath_checkbox = None, None

    def __init__(self):
        super().__init__(None, title=f"pyWallpaper v{VERSION}")
        self.load_config()
        self.load_gui()
        self.load_db()

    def load_config(self):
        c = ConfigParser()
        if not os.path.isfile("config.ini"):
            shutil.copy("config.ini.dist", "config.ini")
        c.read("config.ini")
        self.config = c

        self.table_name = f'images_{c.get("Settings", "File list")}'
        self.delay = int(self.parse_timestring(c.get("Settings", "Delay")) * 1000)
        self.error_delay = int(self.parse_timestring(c.get("Settings", "Error delay")) * 1000)

        font_name = c.get("Filepath", "Font name")
        try:
            self.font = ImageFont.truetype(
                font_name,
                c.getint("Filepath", "Font size")
            )
        except OSError:
            print(f"Couldn't find font at '{font_name}'")
            self.font = ImageFont.load_default()

        self.temp_image_filename = os.path.join(
            os.environ["TEMP"],
            c.get("Advanced", "Temp image filename")
        )

    @staticmethod
    def parse_timestring(timestring: Union[str, int, float]) -> float:
        """
        Converts strings of 3m or 10s or 12m34s into number of seconds
        """
        if isinstance(timestring, (int, float)):
            return float(timestring)
        m = re.match(r"((\d+)h)?((\d+)m)?((\d+)s)?", timestring)
        seconds = 0.0
        try:
            seconds += int(m.group(2)) * 3600  # hours
        except TypeError:
            pass
        try:
            seconds += int(m.group(4)) * 60  # minutes
        except TypeError:
            pass
        try:
            seconds += int(m.group(6))  # seconds
        except TypeError:
            pass
        return seconds

    def load_gui(self):
        # Create a system tray icon
        image = Image.open(self.config.get("Advanced", "Icon path"))
        menu = (
            pystray.MenuItem("Advance Image", self.advance_image, default=True),
            pystray.MenuItem("Open Image File", self.open_image_file),
            # pystray.MenuItem("Copy Image to Clipboard", self.copy_image_to_clipboard),
            pystray.MenuItem("Go to Image File in Explorer", self.go_to_image_file),
            pystray.MenuItem("Remove Image", self.remove_image_from_file_list),
            pystray.MenuItem("Delete Image", self.delete_image),
            pystray.MenuItem("", None),
            pystray.MenuItem("Show Window", self.restore_from_tray),
            pystray.MenuItem("Exit", self.on_exit)
        )
        self.icon = pystray.Icon("pywallpaper", image, "pyWallpaper", menu)

        # Create GUI
        p = wx.Panel(self)

        file_list_text = wx.StaticText(p, label=f'Wallpaper list: {self.config.get("Settings", "File list")}')
        add_files_button = wx.Button(p, label="Add Files to Wallpaper List")
        add_files_button.Bind(wx.EVT_BUTTON, self.add_files_to_list)
        add_folder_button = wx.Button(p, label="Add Folder to Wallpaper List")
        add_folder_button.Bind(wx.EVT_BUTTON, self.add_folder_to_list)
        add_eagle_folder_button = wx.Button(p, label="Add Eagle Folder to Wallpaper List")
        add_eagle_folder_button.Bind(wx.EVT_BUTTON, self.add_eagle_folder_to_list)
        self.add_filepath_checkbox = wx.CheckBox(p, label="Add Filepath to Images?")
        self.add_filepath_checkbox.SetValue(self.config.getboolean("Filepath", "Add Filepath to Images"))

        # Create a sizer to manage the layout of child widgets
        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(file_list_text, wx.SizerFlags().Border(wx.TOP, 10))
        sizer.Add(add_files_button, wx.SizerFlags().Border(wx.TOP, 10))
        sizer.Add(add_folder_button, wx.SizerFlags().Border(wx.TOP, 5))
        sizer.Add(add_eagle_folder_button, wx.SizerFlags().Border(wx.TOP, 5))
        sizer.Add(self.add_filepath_checkbox, wx.SizerFlags().Border(wx.TOP, 10))

        outer_sizer = wx.BoxSizer(wx.HORIZONTAL)
        outer_sizer.Add(sizer, wx.SizerFlags().Border(wx.LEFT | wx.RIGHT, 10))

        p.SetSizerAndFit(outer_sizer)

        # Intercept window close event
        self.Bind(wx.EVT_CLOSE, self.minimize_to_tray)
        # self.Bind(wx.EVT_CLOSE, self.on_exit)

    def load_db(self):
        with Db(table=self.table_name) as db:
            db.make_images_table()

    # Loop functions
    def run(self):
        self.cycle_timer = wx.Timer()
        self.cycle_timer.Bind(wx.EVT_TIMER, self.trigger_image_loop)
        self.trigger_image_loop(None)
        self.run_icon_loop()
        self.run_watchdog()

    def trigger_image_loop(self, _event):
        self.cycle_timer.Stop()

        with Db(table=self.table_name) as db:
            count = db.get_all_active_count()
        if not count:
            print('No images have been loaded. Open the GUI and click the "Add Files to Wallpaper List" '
                  'button to get started')
            wx.CallAfter(self.cycle_timer.StartOnce, self.delay)
            return
        t = threading.Thread(name="image_loop", target=self.set_new_wallpaper, daemon=True)
        t.start()

    def set_new_wallpaper(self):
        with Db(table=self.table_name) as db:
            t1 = time.perf_counter_ns()
            self.original_file_path = db.get_random_image()
            t2 = time.perf_counter_ns()
            print(f"Time to get random image: {(t2 - t1) / 1000:,} us")
        print(f"Loading {self.original_file_path}")
        delay = self.error_delay
        try:
            file_path = self.make_image(self.original_file_path)
        except (FileNotFoundError, UnidentifiedImageError):
            print(f"Couldn't open image path {self.original_file_path!r}", file=sys.stderr)
        except OSError:
            print(f"Failed to process image file: {self.original_file_path!r}", file=sys.stderr)
        else:
            self.set_desktop_wallpaper(file_path)
            delay = self.delay
        wx.CallAfter(self.cycle_timer.StartOnce, delay)

    def make_image(self, file_path: str) -> str:
        # Open image
        img = Image.open(file_path)
        # Resize and apply to background
        img = self.resize_image_to_bg(img)
        # Add text
        if self.add_filepath_checkbox.IsChecked():
            self.add_text_to_image(img, file_path)
        # Write to temp file
        ext = os.path.splitext(file_path)[1]
        temp_file_path = self.temp_image_filename + ext
        img.save(temp_file_path)
        return temp_file_path

    def resize_image_to_bg(self, img: Image):
        # Determine aspect ratios
        image_aspect_ratio = img.width / img.height
        force_monitor_size = self.config.get("Settings", "Force monitor size")
        if force_monitor_size:
            monitor_width, monitor_height = [int(x) for x in force_monitor_size.split(", ")]
        else:
            monitor_width, monitor_height = win32api.GetSystemMetrics(0), win32api.GetSystemMetrics(1)
        bg = Image.new("RGB", (monitor_width, monitor_height), "black")
        bg_aspect_ratio = bg.width / bg.height
        # Pick new image size
        if image_aspect_ratio > bg_aspect_ratio:
            new_img_size = (bg.width, round(bg.width / img.width * img.height))
        else:
            new_img_size = (round(bg.height / img.height * img.width), bg.height)
        # Resize image to match bg
        img = img.resize(new_img_size)
        # Paste image on BG
        paste_x = (bg.width - img.width) // 2
        paste_y = (bg.height - img.height) // 2
        bg.paste(img, (paste_x, paste_y))
        return bg

    def add_text_to_image(self, img: Image, text: str):
        draw = ImageDraw.Draw(img)
        text_x, text_y, text_width, text_height = draw.textbbox((0, 0), text, font=self.font)
        text_x = img.width - text_width - 10  # 10 pixels padding from the right
        text_y = img.height - text_height - 10  # 10 pixels padding from the bottom
        draw.text(
            (text_x, text_y),
            text,
            font=self.font,
            fill=self.config.get("Filepath", "Text fill"),
            stroke_width=self.config.getint("Filepath", "Stroke width"),
            stroke_fill=self.config.get("Filepath", "Stroke fill")
        )

    def set_desktop_wallpaper(self, path: str) -> bool:
        path = os.path.abspath(path)
        # Windows doesn't return an error if we set the wallpaper to an invalid path, so do a check here first.
        if not os.path.isfile(path):
            self.create_windows_event_log(
                "Couldn't find the file {}".format(path),
                event_type=win32evtlog.EVENTLOG_ERROR_TYPE,
                event_id=2
            )
            return False
        self.create_windows_event_log("Setting wallpaper to {}".format(path))
        ctypes.windll.user32.SystemParametersInfoW(SPI_SET_DESKTOP_WALLPAPER, 0, path, 0)
        return True

    @staticmethod
    def create_windows_event_log(message, event_type=win32evtlog.EVENTLOG_INFORMATION_TYPE, event_id=0):
        win32evtlogutil.ReportEvent(
            "Python Wallpaper Cycler",
            event_id,
            eventType=event_type,
            strings=[message],
        )

    def run_icon_loop(self):
        threading.Thread(name="icon.run()", target=self.icon.run, daemon=True).start()

    def run_watchdog(self):
        self.observer = Observer()
        with Db(self.table_name) as db:
            folders = db.get_active_folders()
            for folder in folders:
                self.add_observer_schedule(
                    folder["filepath"],
                    folder["include_subdirectories"],
                    folder["eagle_folder_id"],
                )
        self.observer.start()

    def add_observer_schedule(self, dir_path: str, include_subfolders: bool = False,
                              eagle_folder_id: Optional[str] = None):
        is_eagle = eagle_folder_id is not None
        event_handler = MyEventHandler(self, dir_path, is_eagle, eagle_folder_id)
        self.observer.schedule(
            event_handler,
            dir_path,
            recursive=include_subfolders or is_eagle
        )
        print("Scheduled watchdog for folder {}".format(dir_path))

    # GUI Functions
    def add_files_to_list(self, _event):
        with wx.FileDialog(self, "Select Images", wildcard="Image Files|*.gif;*.jpg;*.jpeg;*.png|All Files|*.*",
                           style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST | wx.FD_MULTIPLE) as fileDialog:
            if fileDialog.ShowModal() == wx.ID_CANCEL:
                return
            file_paths = fileDialog.GetPaths()
        # If we're adding images to the file list for the first time, pick a random image after load
        with Db(table=self.table_name) as db:
            advance_image_after_load = bool(not db.get_all_active_count())
            db.add_images(file_paths)
        if advance_image_after_load:
            self.trigger_image_loop(None)

    def add_folder_to_list(self, _event):
        with wx.DirDialog(self, "Select Image Folder", style=wx.DD_DIR_MUST_EXIST) as dirDialog:
            if dirDialog.ShowModal() == wx.ID_CANCEL:
                return
            dir_path = dirDialog.GetPath()
        title, message = "Question", f"You selected the folder {dir_path}\nDo you want to include subfolders?"
        with wx.MessageDialog(self, message, title, style=wx.ICON_QUESTION | wx.YES_NO | wx.CANCEL) as messageDialog:
            answer = messageDialog.ShowModal()
            if answer == wx.ID_CANCEL:
                return
            include_subfolders = answer == wx.ID_YES
        dir_path = dir_path.replace("\\", "/")
        with Db(table=self.table_name) as db:
            # If we're adding images to the file list for the first time, pick a random image after load
            advance_image_after_load = bool(not db.get_all_active_count())
            db.add_directory(dir_path, include_subfolders)
            file_paths = self.get_file_list_in_folder(dir_path, include_subfolders)
            db.add_images(file_paths, ephemeral=True)
        self.add_observer_schedule(dir_path, include_subfolders=include_subfolders)
        if advance_image_after_load:
            self.trigger_image_loop(None)

    def add_eagle_folder_to_list(self, _event):
        with wx.DirDialog(self, "Select Eagle Library Folder", style=wx.DD_DIR_MUST_EXIST) as dirDialog:
            if dirDialog.ShowModal() == wx.ID_CANCEL:
                return
            dir_path = dirDialog.GetPath()
        if not os.path.isfile(os.path.join(dir_path, "metadata.json")) or \
                not os.path.isdir(os.path.join(dir_path, "images")):
            self.error_dialog(
                "The selected folder is not a valid Eagle library folder. "
                "It must contain a metadata.json file and an images folder."
            )
            return
        # Get all images from metadata.json, falling recursively through child folders.
        with open(os.path.join(dir_path, "metadata.json")) as f:
            metadata = json.load(f)
        image_folders = {}

        def add_to_image_folder_dict(folder_list: list[dict]):
            for folder in folder_list:
                image_folders[folder["name"]] = folder["id"]
                if folder["children"]:
                    add_to_image_folder_dict(folder["children"])
        add_to_image_folder_dict(metadata["folders"])

        # Prompt the user to pick a folder name
        with wx.SingleChoiceDialog(self, "Pick Folder to add to Wallpaper List", "Folders:",
                                   choices=list(image_folders.keys()),
                                   style=wx.RESIZE_BORDER | wx.ALIGN_CENTER | wx.OK | wx.CANCEL) as choice_dialog:
            if choice_dialog.ShowModal() == wx.ID_CANCEL:
                return
        folder_name = choice_dialog.GetStringSelection()
        folder_id = image_folders[folder_name]
        dir_path = dir_path.replace("\\", "/")
        with Db(table=self.table_name) as db:
            # If we're adding images to the file list for the first time, pick a random image after load
            advance_image_after_load = bool(not db.get_all_active_count())
            db.add_eagle_folder(dir_path, folder_name, folder_id)
            file_paths = self.get_file_list_in_eagle_folder(dir_path, folder_id)
            db.add_images(file_paths, ephemeral=True)
        self.add_observer_schedule(dir_path, eagle_folder_id=folder_id)
        if advance_image_after_load:
            self.trigger_image_loop(None)

    def error_dialog(self, message: str, title: str = None):
        with wx.MessageDialog(self, message, "Error" if title is None else title,
                              style=wx.OK | wx.ICON_ERROR) as dialog:
            dialog.ShowModal()

    @staticmethod
    def get_file_list_in_folder(dir_path: str, include_subfolders: bool) -> Sequence[str]:
        file_paths = []
        for dir_path, dir_names, filenames in os.walk(dir_path):
            # If we don't want to include subfolders, clearing the `dir_names` list will stop os.walk() at the
            # top-level directory.
            if not include_subfolders:
                dir_names.clear()
            for filename in filenames:
                file_paths.append(os.path.join(dir_path, filename).replace("\\", "/"))
        return file_paths

    @staticmethod
    def get_file_list_in_eagle_folder(dir_path: str, folder_id: str):
        file_list = []
        for dir_path, dir_names, filenames in os.walk(os.path.join(dir_path, "images")):
            if "metadata.json" not in filenames:
                continue
            with open(os.path.join(dir_path, "metadata.json"), "r") as f:
                metadata = json.load(f)
            if folder_id not in metadata["folders"]:
                continue
            for filename in filenames:
                if filename == "metadata.json":
                    continue
                if len(filenames) > 2 and filename.endswith("_thumbnail.png"):
                    continue
                file_list.append(os.path.join(dir_path, filename).replace("\\", "/"))
        return file_list

    def advance_image(self, _icon, _item):
        self.trigger_image_loop(None)

    def open_image_file(self, _icon, _item):
        subprocess.run(["cmd", "/c", "start", "", os.path.abspath(self.original_file_path)])

    # def copy_image_to_clipboard(self, _icon, _item):
    #     # encoded_path = urllib.parse.quote(self.original_file_path, safe="")
    #     # file_reference = f"file:{encoded_path}"
    #     # print(f"Copying {file_reference} to the clipboard")
    #     #
    #     # pyperclip.copy(file_reference)
    #
    #     img = Image.open(self.original_file_path)
    #     output = io.BytesIO()
    #     img.convert('RGB').save(output, 'BMP')
    #     data = output.getvalue()[14:]
    #     output.close()
    #
    #     win32clipboard.OpenClipboard()
    #     win32clipboard.EmptyClipboard()
    #     win32clipboard.SetClipboardData(win32clipboard.CF_HDROP, "\0")
    #     win32clipboard.SetClipboardData(49159, os.path.abspath(self.original_file_path))  # FileNameW
    #     win32clipboard.CloseClipboard()

    def go_to_image_file(self, _icon, _item):
        subprocess.Popen(["explorer", "/select,", os.path.abspath(self.original_file_path)])

    def remove_image_from_file_list(self, _icon, _item):
        with Db(table=self.table_name) as db:
            db.set_image_to_inactive(self.original_file_path)
        self.advance_image(_icon, _item)

    def delete_image(self, _icon, _item):
        path = self.original_file_path
        title, message = "Delete image?", f"Are you sure you want to delete {path}"
        with wx.MessageDialog(self, message, title, style=wx.ICON_WARNING | wx.YES_NO) as messageDialog:
            answer = messageDialog.ShowModal()
            if answer == wx.ID_NO:
                return
        ext = os.path.splitext(path)[1]
        backup_path = self.config.get("Advanced", "Deleted image path") + ext
        shutil.move(path, backup_path)
        with Db(table=self.table_name) as db:
            db.delete_image(path)
        print(f"Moving {path} to {backup_path}")
        notification = f"{os.path.basename(path)} has been deleted."
        if len(notification) > 64:
            notification = "..." + notification[-61:]
        self.icon.notify("Deleted wallpaper", notification)

        self.advance_image(_icon, _item)

    def minimize_to_tray(self, _event):
        self.Hide()  # Hide the main window

    def restore_from_tray(self, _icon, _item):
        self.Show()  # Restore the main window

    def on_exit(self, *args):
        self.icon.stop()  # Remove the system tray icon
        self.observer.stop()
        wx.Exit()


class MyEventHandler(FileSystemEventHandler):

    def __init__(self, parent: PyWallpaper, dir_path: str, eagle_mode: bool = False,
                 eagle_folder_id: Optional[str] = None):
        super().__init__()
        self.parent = parent
        self.dir_path = dir_path
        self.eagle_mode = eagle_mode
        self.eagle_folder_id = eagle_folder_id
        self.eagle_timer = None
        self.debounce_time = 3  # seconds

    def on_created(self, event):
        if event.is_directory or event.src_path.endswith("@SynoEAStream"):
            return
        print(f"File created: {event.src_path}")
        self.add_file(event.src_path)

    def on_modified(self, event):
        if event.is_directory or event.src_path.endswith("@SynoEAStream"):
            return
        print(f"File modified: {event.src_path}")
        self.add_file(event.src_path)

    def add_file(self, file_path: str):
        file_path = file_path.replace("\\", "/")
        if self.eagle_mode:
            # If an Eagle timer is added or modified, we need to rescan the whole Eagle directory
            # Because of this, we need to wait for all the file events to finish coming in,
            # and only run the update once.
            # TODO update this to only rescan the affected folder
            if self.eagle_timer:
                self.eagle_timer.cancel()
            self.eagle_timer = threading.Timer(self.debounce_time, self.add_eagle_file, args=[file_path])
            self.eagle_timer.start()
            return
        with Db(table=self.parent.table_name) as db:
            db.add_images([file_path], ephemeral=True)

    def add_eagle_file(self, file_path: str):
        print(f"Adding {file_path} to eagle mode. "
              f"dir_path={self.dir_path} eagle_folder_id={self.eagle_folder_id}")
        file_list = self.parent.get_file_list_in_eagle_folder(self.dir_path, self.eagle_folder_id)
        with Db(table=self.parent.table_name) as db:
            db.add_images(file_list, ephemeral=True)

    def on_deleted(self, event):
        if event.is_directory or event.src_path.endswith("@SynoEAStream"):
            return
        print(f"File deleted: {event.src_path}")
        file_path = event.src_path.replace("\\", "/")
        with Db(table=self.parent.table_name) as db:
            db.delete_image(file_path)


if __name__ == '__main__':
    # When this module is run (not imported) then create the app, the
    # frame, show it, and start the event loop.
    app = wx.App()
    PyWallpaper().run()
    app.MainLoop()

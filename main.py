import ctypes
import io
import os
import re
import shutil
import subprocess
import sys
import threading
import tkinter as tk
from configparser import ConfigParser
from time import time
from tkinter import messagebox, filedialog
from typing import Sequence, Union

import pystray
import win32api
import win32clipboard
import win32evtlog
import win32evtlogutil
from PIL import Image, ImageFont, ImageDraw, UnidentifiedImageError

from database.db import Db

# Global variables
SPI_SETDESKWALLPAPER = 20


class PyWallpaper:

    config = None
    table_name = None
    delay = None
    error_delay = None
    font = None
    temp_image_filename = None

    original_file_path = None
    timer_id = None

    def __init__(self):
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
        self.root = tk.Tk()
        self.root.title("pyWallpaper")

        self.root.wm_minsize(width=200, height=100)

        # Create a system tray icon
        self.image = Image.open(self.config.get("Advanced", "Icon path"))
        self.menu = (
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
        self.icon = pystray.Icon("pywallpaper", self.image, "pyWallpaper", self.menu)

        # Create GUI
        self.add_files_button = tk.Button(self.root, text="Add Files to Wallpaper List", command=self.add_files_to_list)
        self.add_files_button.pack()
        self.add_folder_button = tk.Button(self.root, text="Add Folder to Wallpaper List", command=self.add_folder_to_list)
        self.add_folder_button.pack(pady=10)
        # self.show_button = tk.Button(self.root, text="Open Wallpaper List", command=self.show_file_list)
        # self.show_button.pack()
        self.add_filepath_to_images = tk.BooleanVar(
            value=self.config.getboolean("Filepath", "Add filepath to images")
        )
        self.text_checkbox = tk.Checkbutton(
            self.root,
            text="Add Filepath to Images?",
            variable=self.add_filepath_to_images,
            onvalue=True,
            offvalue=False
        )
        self.text_checkbox.pack(pady=10)

        # Intercept window close event
        self.root.protocol("WM_DELETE_WINDOW", self.minimize_to_tray)

        # Hide main window to start
        self.root.withdraw()

    def load_db(self):
        with Db(table=self.table_name) as db:
            db.make_images_table()
            if os.path.isfile("wallpaper_files.txt"):
                with open("wallpaper_files.txt", "rb") as f:
                    wallpaper_files = f.read().decode().splitlines()
                db.add_images(wallpaper_files)
                os.remove("wallpaper_files.txt")

    # Loop functions
    def run(self):
        self.trigger_image_loop()
        self.run_icon_loop()
        self.root.mainloop()

    def trigger_image_loop(self):
        if self.timer_id:
            self.root.after_cancel(self.timer_id)

        with Db(table=self.table_name) as db:
            count = db.get_all_active_count()
        if not count:
            print('No images have been loaded. Open the GUI and click the "Add Files to Wallpaper List" '
                  'button to get started')
            self.timer_id = self.root.after(self.delay, self.trigger_image_loop)
            return
        t = threading.Thread(name="image_loop", target=self.set_new_wallpaper, daemon=True)
        t.start()

    def set_new_wallpaper(self):
        with Db(table=self.table_name) as db:
            t1 = time()
            self.original_file_path = db.get_random_image()
            t2 = time()
            print(f"Time to get random image: {t2 - t1}")
        print(self.original_file_path)
        delay = self.error_delay
        try:
            file_path = self.make_image(self.original_file_path)
        except (FileNotFoundError, UnidentifiedImageError):
            print(f"Couldn't open image path {self.original_file_path!r}", file=sys.stderr)
        except OSError:
            print(f"Failed to process image file: {self.original_file_path!r}", file=sys.stderr)
        else:
            success = self.set_desktop_wallpaper(file_path)
            # print(success)
            delay = self.delay
        self.timer_id = self.root.after(delay, self.trigger_image_loop)

    def make_image(self, file_path: str) -> str:
        # Open image
        img = Image.open(file_path)
        # Resize and apply to background
        img = self.resize_image_to_bg(img)
        # Add text
        if self.add_filepath_to_images.get():
            self.add_text_to_image(img, file_path)
        # Write to temp file
        ext = os.path.splitext(file_path)[1]
        temp_file_path = self.temp_image_filename + ext
        print(temp_file_path)
        img.save(temp_file_path)
        return temp_file_path

    def resize_image_to_bg(self, img: Image):
        # Determine aspect ratios
        image_aspect_ratio = img.width / img.height
        force_monitor_size = self.config.get("Settings", "Force monitor size")
        if force_monitor_size:
            monitor_width, monitor_height = force_monitor_size
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
        ctypes.windll.user32.SystemParametersInfoW(SPI_SETDESKWALLPAPER, 0, path, 0)
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
        # self.root.after(1, self.icon.run)
        threading.Thread(name="icon.run()", target=self.icon.run, daemon=True).start()

    # GUI Functions
    def add_files_to_list(self):
        file_paths: Sequence[str] = filedialog.askopenfilenames(
            title="Select Images",
            filetypes=(
                ("Image Files", "*.gif;*.jpg;*.jpeg;*.png"),
                ("All Files", "*.*"),
            )
        )
        # If we're adding images to the file list for the first time, pick a random image after load
        with Db(table=self.table_name) as db:
            advance_image_after_load = bool(not db.get_all_active_count())
            db.add_images(file_paths)
        if advance_image_after_load:
            self.trigger_image_loop()

    def add_folder_to_list(self):
        dir_path = filedialog.askdirectory(
            title="Select Image Folder",
        )
        include_subfolders = messagebox.askyesnocancel(
            "Question",
            f"You selected the folder {dir_path}\nDo you want to include subfolders?"
        )
        if include_subfolders is None:
            return
        file_paths = []
        for dirpath, dirnames, filenames in os.walk(dir_path):
            # If we don't want to include subfolders, clearing the `dirnames` list will stop os.walk() at the
            # top-level directory.
            if not include_subfolders:
                dirnames.clear()
            for filename in filenames:
                file_paths.append(os.path.join(dirpath, filename).replace("\\", "/"))
        # If we're adding images to the file list for the first time, pick a random image after load
        with Db(table=self.table_name) as db:
            advance_image_after_load = bool(not db.get_all_active_count())
            db.add_images(file_paths)
        if advance_image_after_load:
            self.trigger_image_loop()

    def advance_image(self, _icon, _item):
        self.trigger_image_loop()

    def open_image_file(self, _icon, _item):
        subprocess.run(["cmd", "/c", "start", "", os.path.abspath(self.original_file_path)])

    def copy_image_to_clipboard(self, _icon, _item):
        # encoded_path = urllib.parse.quote(self.original_file_path, safe="")
        # file_reference = f"file:{encoded_path}"
        # print(f"Copying {file_reference} to the clipboard")
        #
        # pyperclip.copy(file_reference)

        img = Image.open(self.original_file_path)
        output = io.BytesIO()
        img.convert('RGB').save(output, 'BMP')
        data = output.getvalue()[14:]
        output.close()

        win32clipboard.OpenClipboard()
        win32clipboard.EmptyClipboard()
        win32clipboard.SetClipboardData(win32clipboard.CF_HDROP, "\0")
        win32clipboard.SetClipboardData(49159, os.path.abspath(self.original_file_path))  # FileNameW
        win32clipboard.CloseClipboard()

    def go_to_image_file(self, _icon, _item):
        subprocess.Popen(["explorer", "/select,", os.path.abspath(self.original_file_path)])

    def remove_image_from_file_list(self, _icon, _item):
        with Db(table=self.table_name) as db:
            db.set_image_to_inactive(self.original_file_path)
        self.advance_image(_icon, _item)

    def delete_image(self, _icon, _item):
        path = self.original_file_path
        result = messagebox.askokcancel("Delete image?", f"Are you sure you want to delete {path}")
        if result:
            ext = os.path.splitext(path)[1]
            backup_path = self.config.get("Advanced", "Deleted image path") + ext
            shutil.move(path, backup_path)
            with Db(table=self.table_name) as db:
                db.delete_image(path)
            print(f"Moving {path} to {backup_path}")
            self.icon.notify("Deleted wallpaper", f"{os.path.basename(path)} has been deleted.")
            self.advance_image(_icon, _item)

    def minimize_to_tray(self):
        self.root.withdraw()  # Hide the main window

    def restore_from_tray(self, _icon, _item):
        self.root.deiconify()  # Restore the main window

    def on_exit(self, *_args):
        self.icon.stop()  # Remove the system tray icon
        self.root.destroy()


if __name__ == "__main__":
    app = PyWallpaper()
    app.run()

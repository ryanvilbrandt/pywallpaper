import ctypes
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from argparse import ArgumentParser
from glob import glob
from io import BytesIO
from json import JSONDecodeError
from typing import Sequence, Union, Optional

import pystray
import win32api
import win32clipboard
import win32evtlog
import win32evtlogutil
import wx
from PIL import Image, ImageFont, ImageDraw, UnidentifiedImageError
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

import utils
from db import Db
from image_utils import get_common_color, has_transparency
from keybind_listener import KeybindListener, KeybindDialog
from version import VERSION

SPI_SET_DESKTOP_WALLPAPER = 0x14


class PyWallpaper(wx.Frame):
    config = None
    settings = None
    table_name = None
    delay = None
    error_delay = None
    ephemeral_refresh_delay = None
    font = None
    temp_image_filename = None

    original_file_path = None
    file_path_history = []
    cycle_timer = None
    observer, event_handlers = None, {}
    processing_eagle = None
    last_ephemeral_image_refresh = 0

    # GUI Elements
    icon, file_list_dropdown, delay_value, delay_dropdown, add_filepath_checkbox = None, None, None, None, None
    left_padding, right_padding, top_padding, bottom_padding, use_padding_test_checkbox = None, None, None, None, None
    ephemeral_refresh_value, ephemeral_refresh_dropdown, enable_ephemeral_refresh_checkbox = None, None, None

    keybind_listener: KeybindListener = None

    def __init__(self, debug: bool = False):
        super().__init__(None, title=f"pyWallpaper v{VERSION}")
        utils.perf()
        self.migrate_db()
        utils.perf("migrate_db")
        self.load_config()
        utils.perf("load_config")
        self.load_gui(debug)
        utils.perf("load_gui")

        # Set delays from GUI elements
        self.set_delay(None)
        self.set_ephemeral_refresh_delay(None)

    @staticmethod
    def migrate_db():
        with Db() as db:
            db.migrate()

    def load_config(self):
        c = utils.load_config()
        self.config = c

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

        # Load settings file
        if os.path.isfile("conf/settings.json"):
            with open("conf/settings.json", "r") as f:
                self.settings = json.load(f)
        else:
            self.settings = {}

    def save_settings(self):
        with open("conf/settings.json", "w") as f:
            json.dump(self.settings, f)

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

    def load_gui(self, debug: bool):
        # Create a system tray icon
        image = Image.open(self.config.get("Advanced", "Icon path"))
        menu = (
            pystray.MenuItem("Advance Image", self.advance_image, default=True),
            pystray.MenuItem("Open Image File", self.open_image_file),
            pystray.MenuItem("Copy Image to Clipboard", self.copy_image_to_clipboard),
            pystray.MenuItem("Go to Image File in Explorer", self.go_to_image_file),
            pystray.MenuItem("Show Previous Image", self.show_previous_image),
            pystray.MenuItem("Remove Image", self.remove_image_from_file_list),
            pystray.MenuItem("Delete Image", self.delete_image),
            pystray.MenuItem("", None),
            pystray.MenuItem("Show Window", self.restore_from_tray),
            pystray.MenuItem("Exit", self.on_exit)
        )
        self.icon = pystray.Icon("pywallpaper", image, "pyWallpaper", menu)

        # Create GUI
        p = wx.Panel(self)

        with Db() as db:
            image_tables = db.get_image_tables()
        if not image_tables:
            # No image tables in the DB. Set file list to "default"
            image_tables = ["default"]
            self.table_name = "images_default"
            self.make_images_table()
        image_tables.append("<Add new file list>")
        self.file_list_dropdown = wx.ComboBox(p, choices=image_tables, style=wx.CB_READONLY)
        self.file_list_dropdown.Bind(wx.EVT_COMBOBOX, self.select_file_list)

        # Set dropdown to saved file list
        self.file_list_dropdown.SetValue(self.settings.get("selected_file_list", "default"))
        # Select "default" if the selected_file_list option isn't available in the dropdown
        selected_file_list = self.file_list_dropdown.GetValue()
        if not selected_file_list or selected_file_list == "<Add new file list>":
            self.file_list_dropdown.SetValue("default")
        self.select_file_list(None)

        self.delay_value = wx.SpinCtrl(p, min=1, initial=self.settings.get("delay_value", 3))
        self.delay_value.Bind(wx.EVT_SPINCTRL, self.set_delay)
        self.delay_value.Bind(wx.EVT_TEXT, self.set_delay)
        self.delay_dropdown = wx.ComboBox(p, choices=["seconds", "minutes", "hours"], style=wx.CB_READONLY)
        self.delay_dropdown.SetValue(self.settings.get("delay_unit", "minutes"))
        self.delay_dropdown.Bind(wx.EVT_COMBOBOX, self.set_delay)

        add_files_button = wx.Button(p, label="Add Files to Wallpaper List")
        add_files_button.Bind(wx.EVT_BUTTON, self.add_files_to_list)
        add_folder_button = wx.Button(p, label="Add Folder to Wallpaper List")
        add_folder_button.Bind(wx.EVT_BUTTON, self.add_folder_to_list)
        add_eagle_folder_button = wx.Button(p, label="Add Eagle Folder to Wallpaper List")
        add_eagle_folder_button.Bind(wx.EVT_BUTTON, self.add_eagle_folder_to_list)

        self.add_filepath_checkbox = wx.CheckBox(p, label="Add Filepath to Images?")
        self.add_filepath_checkbox.SetValue(self.config.getboolean("Filepath", "Add Filepath to Images"))

        self.left_padding = wx.SpinCtrl(p, min=0, max=10000, initial=self.settings.get("left_padding", 0))
        self.right_padding = wx.SpinCtrl(p, min=0, max=10000, initial=self.settings.get("right_padding", 0))
        self.top_padding = wx.SpinCtrl(p, min=0, max=10000, initial=self.settings.get("top_padding", 0))
        self.bottom_padding = wx.SpinCtrl(p, min=0, max=10000, initial=self.settings.get("bottom_padding", 0))
        apply_padding_button = wx.Button(p, label="Apply Padding Changes")
        apply_padding_button.Bind(wx.EVT_BUTTON, self.apply_padding)
        self.use_padding_test_checkbox = wx.CheckBox(p, label="Show test wallpaper when applying padding changes?")
        self.use_padding_test_checkbox.SetValue(False)

        self.ephemeral_refresh_value = wx.SpinCtrl(
            p, min=0, max=10000, initial=self.settings.get("ephemeral_refresh_delay_value", 10)
        )
        self.ephemeral_refresh_value.Bind(wx.EVT_SPINCTRL, self.set_ephemeral_refresh_delay)
        self.ephemeral_refresh_value.Bind(wx.EVT_TEXT, self.set_ephemeral_refresh_delay)
        self.ephemeral_refresh_dropdown = wx.ComboBox(
            p, choices=["seconds", "minutes", "hours"], style=wx.CB_READONLY
        )
        self.ephemeral_refresh_dropdown.SetValue(self.settings.get("ephemeral_refresh_delay_unit", "minutes"))
        self.ephemeral_refresh_dropdown.Bind(wx.EVT_COMBOBOX, self.set_ephemeral_refresh_delay)
        self.enable_ephemeral_refresh_checkbox = wx.CheckBox(p, label="Enable periodic rescan of folders?")
        self.enable_ephemeral_refresh_checkbox.SetValue(self.settings.get("enable_ephemeral_refresh", True))
        self.enable_ephemeral_refresh_checkbox.Bind(wx.EVT_CHECKBOX, self.set_enable_ephemeral_refresh)

        previous_image_keybind = wx.StaticText(p, label=self.settings.get("previous_image_keybind", "<not set>"))
        previous_image_keybind_set_button = wx.Button(p, label="Set")
        previous_image_keybind_set_button.SetInitialSize((30, -1))
        previous_image_keybind_set_button.Bind(
            wx.EVT_BUTTON, lambda event: self.set_keybind(previous_image_keybind, "previous")
        )
        previous_image_keybind_clear_button = wx.Button(p, label="Clear")
        previous_image_keybind_clear_button.SetInitialSize((40, -1))
        previous_image_keybind_clear_button.Bind(
            wx.EVT_BUTTON, lambda event: self.clear_keybind(previous_image_keybind, "previous")
        )
        next_image_keybind = wx.StaticText(p, label=self.settings.get("next_image_keybind", "<not set>"))
        next_image_keybind_set_button = wx.Button(p, label="Set")
        next_image_keybind_set_button.SetInitialSize((30, -1))
        next_image_keybind_set_button.Bind(
            wx.EVT_BUTTON, lambda event: self.set_keybind(next_image_keybind, "next")
        )
        next_image_keybind_clear_button = wx.Button(p, label="Clear")
        next_image_keybind_clear_button.SetInitialSize((40, -1))
        next_image_keybind_clear_button.Bind(
            wx.EVT_BUTTON, lambda event: self.clear_keybind(next_image_keybind, "next")
        )
        delete_image_keybind = wx.StaticText(p, label=self.settings.get("delete_image_keybind", "<not set>"))
        delete_image_keybind_set_button = wx.Button(p, label="Set")
        delete_image_keybind_set_button.SetInitialSize((30, -1))
        delete_image_keybind_set_button.Bind(
            wx.EVT_BUTTON, lambda event: self.set_keybind(delete_image_keybind, "delete")
        )
        delete_image_keybind_clear_button = wx.Button(p, label="Clear")
        delete_image_keybind_clear_button.SetInitialSize((40, -1))
        delete_image_keybind_clear_button.Bind(
            wx.EVT_BUTTON, lambda event: self.clear_keybind(delete_image_keybind, "delete")
        )

        # Create a sizer to manage the layout of child widgets
        sizer = wx.BoxSizer(wx.VERTICAL)
        file_list_sizer = wx.BoxSizer(wx.HORIZONTAL)
        file_list_sizer.Add(wx.StaticText(p, label=f'Wallpaper list:'), wx.SizerFlags().Border(wx.TOP | wx.RIGHT, 3))
        file_list_sizer.Add(self.file_list_dropdown)
        sizer.Add(file_list_sizer, wx.SizerFlags().Border(wx.TOP, 10))

        delay_sizer = wx.BoxSizer(wx.HORIZONTAL)
        delay_sizer.Add(wx.StaticText(p, label=f'Delay:'), wx.SizerFlags().Border(wx.TOP | wx.RIGHT, 3))
        delay_sizer.Add(self.delay_value, wx.SizerFlags().Border(wx.RIGHT, 3))
        delay_sizer.Add(self.delay_dropdown)
        sizer.Add(delay_sizer, wx.SizerFlags().Border(wx.TOP, 10))

        sizer.Add(add_files_button, wx.SizerFlags().Border(wx.TOP, 10))
        sizer.Add(add_folder_button, wx.SizerFlags().Border(wx.TOP, 5))
        sizer.Add(add_eagle_folder_button, wx.SizerFlags().Border(wx.TOP, 5))
        sizer.Add(self.add_filepath_checkbox, wx.SizerFlags().Border(wx.TOP, 10))

        sizer.Add(wx.StaticText(p, label=f'Wallpaper padding (in pixels):'), wx.SizerFlags().Border(wx.TOP, 20))
        border_sizer = wx.GridSizer(cols=3)
        border_sizer.AddMany([
            (wx.StaticText(p), wx.SizerFlags()),
            (self.top_padding, wx.SizerFlags()),
            (wx.StaticText(p), wx.SizerFlags()),
            (self.left_padding, wx.SizerFlags()),
            (wx.StaticText(p), wx.SizerFlags()),
            (self.right_padding, wx.SizerFlags()),
            (wx.StaticText(p), wx.SizerFlags()),
            (self.bottom_padding, wx.SizerFlags()),
        ])
        sizer.Add(border_sizer, wx.SizerFlags().Border(wx.TOP, 5))
        sizer.Add(apply_padding_button, wx.SizerFlags().Border(wx.TOP | wx.BOTTOM, 5))
        sizer.Add(self.use_padding_test_checkbox, wx.SizerFlags().Border(wx.TOP | wx.BOTTOM, 5))

        ephemeral_refresh_sizer = wx.BoxSizer(wx.HORIZONTAL)
        ephemeral_refresh_sizer.Add(
            wx.StaticText(p, label=f'Rescan folders delay:'),
            wx.SizerFlags().Border(wx.TOP | wx.RIGHT, 3),
        )
        ephemeral_refresh_sizer.Add(self.ephemeral_refresh_value, wx.SizerFlags().Border(wx.RIGHT, 3))
        ephemeral_refresh_sizer.Add(self.ephemeral_refresh_dropdown)
        sizer.Add(ephemeral_refresh_sizer, wx.SizerFlags().Border(wx.TOP, 10))
        sizer.Add(self.enable_ephemeral_refresh_checkbox, wx.SizerFlags().Border(wx.TOP, 5))

        keybind_box = wx.StaticBox(p, label="Universal Keybinds (usable everywhere)")
        keybind_sizer = wx.StaticBoxSizer(keybind_box, wx.VERTICAL)

        grid_sizer = wx.FlexGridSizer(3, 4, 5, 5)
        grid_sizer.AddGrowableCol(1)  # Make the second column expandable
        # Add elements for 'Previous image'
        grid_sizer.Add(wx.StaticText(p, label=f'Previous image:'),
                       wx.SizerFlags().Border(wx.RIGHT, 3).Align(wx.ALIGN_CENTER_VERTICAL))
        grid_sizer.Add(previous_image_keybind, wx.SizerFlags().Border(wx.RIGHT, 3).Align(wx.ALIGN_CENTER_VERTICAL))
        grid_sizer.Add(previous_image_keybind_set_button, wx.SizerFlags().Border(wx.RIGHT, 3))
        grid_sizer.Add(previous_image_keybind_clear_button, wx.SizerFlags().Border(wx.RIGHT, 3))
        # Add elements for 'Next image'
        grid_sizer.Add(wx.StaticText(p, label=f'Next image:'),
                       wx.SizerFlags().Border(wx.RIGHT, 3).Align(wx.ALIGN_CENTER_VERTICAL))
        grid_sizer.Add(next_image_keybind, wx.SizerFlags().Border(wx.RIGHT, 3).Align(wx.ALIGN_CENTER_VERTICAL))
        grid_sizer.Add(next_image_keybind_set_button, wx.SizerFlags().Border(wx.RIGHT, 3))
        grid_sizer.Add(next_image_keybind_clear_button, wx.SizerFlags().Border(wx.RIGHT, 3))
        # Add elements for 'Delete image'
        grid_sizer.Add(wx.StaticText(p, label=f'Delete image:'),
                       wx.SizerFlags().Border(wx.RIGHT, 3).Align(wx.ALIGN_CENTER_VERTICAL))
        grid_sizer.Add(delete_image_keybind, wx.SizerFlags().Border(wx.RIGHT, 3).Align(wx.ALIGN_CENTER_VERTICAL))
        grid_sizer.Add(delete_image_keybind_set_button, wx.SizerFlags().Border(wx.RIGHT, 3))
        grid_sizer.Add(delete_image_keybind_clear_button, wx.SizerFlags().Border(wx.RIGHT, 3))

        keybind_sizer.Add(grid_sizer, wx.SizerFlags(1).Expand())
        sizer.Add(keybind_sizer, wx.SizerFlags(1).Expand().Border(wx.TOP, 10))

        outer_sizer = wx.BoxSizer(wx.HORIZONTAL)
        outer_sizer.Add(sizer, wx.SizerFlags(1).Expand().Border(wx.LEFT | wx.RIGHT | wx.BOTTOM, 10))

        p.SetSizerAndFit(outer_sizer)
        self.Fit()

        self.SetMinSize(self.GetSize())

        if debug:
            self.Bind(wx.EVT_CLOSE, self.on_exit)
            self.Show()
        else:
            # Intercept window close event
            self.Bind(wx.EVT_CLOSE, self.minimize_to_tray)

    def start_keybind_listener(self):
        try:
            self.keybind_listener = KeybindListener("Main listener")
        except ImportError:
            msg = ("The universal keybinds feature requires the pynput package to be installed.\n"
                   "Please install it using 'pip install -r requirements.txt'")
            with wx.MessageDialog(self, msg, "pynput not installed") as dialog:
                dialog.ShowModal()
            return

        self.keybind_listener.register_callback(
            "previous_image",
            self.settings.get("previous_image_keybind"),
            lambda: wx.CallAfter(self.show_previous_image),
        )
        self.keybind_listener.register_callback(
            "next_image",
            self.settings.get("next_image_keybind"),
            lambda: wx.CallAfter(self.trigger_image_loop),
        )
        self.keybind_listener.register_callback(
            "delete_image",
            self.settings.get("delete_image_keybind"),
            lambda: wx.CallAfter(self.delete_image),
        )

        self.keybind_listener.start()

    def make_images_table(self):
        with Db(table=self.table_name) as db:
            db.make_images_table()

    def post_init(self):
        """
        Runs some setup functions that are not required for GUI initialization.
        This lets the GUI load and become responsive as quickly as possible.
        """
        utils.perf("start run")
        self.cycle_timer = wx.Timer()
        self.cycle_timer.Bind(wx.EVT_TIMER, self.trigger_image_loop)
        utils.perf("cycle_timer")
        self.trigger_image_loop(None)
        utils.perf("trigger_image_loop")
        self.run_icon_loop()
        utils.perf("run_icon_loop")
        utils.print_perf("App Init")

        # Run some functions in threads to not slow down app
        t = threading.Thread(
            name="refresh_ephemeral_images",
            target=self.refresh_ephemeral_images,
            kwargs={"force_refresh": True},
            daemon=True,
        )
        t.start()

        t = threading.Thread(name="run_watchdog", target=self.run_watchdog, daemon=True)
        t.start()

        t = threading.Thread(name="start_keybind_listener", target=self.start_keybind_listener, daemon=True)
        t.start()

    # Loop functions
    def trigger_image_loop(self, _event=None):
        self.cycle_timer.Stop()

        with Db(table=self.table_name) as db:
            count = db.get_all_active_count()
        if not count:
            self.Show()
            msg = 'No images have been loaded. Click the "Add Files to Wallpaper List" button to get started.'
            with wx.MessageDialog(self, msg, "Empty wallpaper list") as dialog:
                dialog.ShowModal()
            return
        t = threading.Thread(name="image_loop", target=self.pick_new_wallpaper, daemon=True)
        t.start()

    def pick_new_wallpaper(self):
        test_wallpaper = self.config.get("Advanced", "Load test wallpaper", fallback="").strip('"')
        test_mode = bool(test_wallpaper)
        if test_wallpaper:
            self.set_wallpaper(test_wallpaper)
            return
        if self.original_file_path:
            self.file_path_history.append(self.original_file_path)
            self.file_path_history = self.file_path_history[-1 * self.config.getint("Settings", "History size"):]
            print(f"History: {self.file_path_history}")
        with Db(table=self.table_name) as db:
            t1 = time.perf_counter_ns()
            algorithm = self.config.get("Settings", "Random algorithm").lower()
            if algorithm == "pure":
                self.original_file_path = db.get_random_image(increment=not test_mode)
            elif algorithm == "weighted":
                self.original_file_path = db.get_random_image_with_weighting(increment=not test_mode)
            elif algorithm == "least used":
                self.original_file_path = db.get_random_image_from_least_used(increment=not test_mode)
            else:
                raise ValueError(f'Invalid value in "Random algorithm" config option: {algorithm}')
            t2 = time.perf_counter_ns()
            print(f"Time to get random image: {(t2 - t1) / 1000:,} us")
        self.original_file_path = self.original_file_path.replace("/", "\\")
        self.set_wallpaper(self.original_file_path)

        self.refresh_ephemeral_images()

    def set_wallpaper(self, filepath):
        print(f"Loading {filepath}")
        delay = self.error_delay
        try:
            t1 = time.perf_counter_ns()
            file_path = self.make_image(filepath)
            t2 = time.perf_counter_ns()
            print(f"Time to load new image: {(t2 - t1) / 1000:,} us")
        except (FileNotFoundError, UnidentifiedImageError):
            print(f"Couldn't open image path {filepath!r}", file=sys.stderr)
        except OSError as e:
            print(f"Failed to process image file: {filepath}", file=sys.stderr)
            wx.MessageDialog(self, str(e), "Error").ShowModal()
        else:
            t1a = time.perf_counter_ns()
            self.set_desktop_wallpaper(file_path)
            t2a = time.perf_counter_ns()
            print(f"Time to apply image to desktop: {(t2a - t1a) / 1000:,} us")
            delay = self.delay
        wx.CallAfter(self.cycle_timer.StartOnce, delay)

    def make_image(self, file_path: str) -> str:
        # Open image
        img = Image.open(file_path)
        if img.mode == "P":
            img = img.convert("RGBA")
        # Resize and apply to background
        img = self.resize_image_to_bg(
            img,
            self.str_to_color(self.config.get("Settings", "Background color")),
            self.str_to_color(self.config.get("Settings", "Border color")),
            self.str_to_color(self.config.get("Settings", "Padding color")),
            file_path,
        )
        # Add text
        if self.add_filepath_checkbox.IsChecked():
            self.add_text_to_image(img, file_path)
        # Write to temp file
        ext = os.path.splitext(file_path)[1]
        temp_file_path = self.temp_image_filename + ext
        img.save(temp_file_path)
        return temp_file_path

    @staticmethod
    def str_to_color(color: str):
        """
        Checks if the color string is a tuple of ints, and converts it. Otherwise, returns the string unchanged.
        """
        m = re.search(r"(\d+),\s*(\d+),\s*(\d+)", color)
        if m:
            return int(m.group(1)), int(m.group(2)), int(m.group(3))
        return color

    def resize_image_to_bg(self, img: Image, bg_color: str, border_color: str = "", padding_color: str = "",
                           image_file_path: str = "", redo_cache: bool = False) -> Image:
        force_monitor_size = self.config.get("Settings", "Force monitor size")
        if force_monitor_size:
            monitor_width, monitor_height = [int(x) for x in force_monitor_size.split(", ")]
        else:
            monitor_width, monitor_height = win32api.GetSystemMetrics(0), win32api.GetSystemMetrics(1)

        bg_color, border_color, padding_color = self.get_bg_border_padding_colors(
            img, bg_color, border_color, padding_color, image_file_path, redo_cache
        )

        bg = Image.new("RGB", (monitor_width, monitor_height), bg_color)
        left_padding = self.settings.get("left_padding", 0)
        right_padding = self.settings.get("right_padding", 0)
        top_padding = self.settings.get("top_padding", 0)
        bottom_padding = self.settings.get("bottom_padding", 0)

        if img:
            # Determine aspect ratios
            image_aspect_ratio = img.width / img.height
            bg_width = bg.width - left_padding - right_padding
            bg_height = bg.height - top_padding - bottom_padding
            bg_aspect_ratio = bg_width / bg_height
            # Pick new image size
            if image_aspect_ratio > bg_aspect_ratio:
                new_img_size = (bg_width, round(bg_width / img.width * img.height))
            else:
                new_img_size = (round(bg_height / img.height * img.width), bg_height)
            # Resize image to match bg
            img = img.resize(new_img_size)
            # Draw image border first
            paste_x = (bg_width - img.width) // 2 + left_padding
            paste_y = (bg_height - img.height) // 2 + top_padding
            border_size = self.config.getint("Settings", "Border size", fallback=0)
            if border_size:
                draw = ImageDraw.Draw(bg)
                draw.rectangle(
                    (
                        paste_x - border_size,
                        paste_y - border_size,
                        paste_x + img.width + border_size,
                        paste_y + img.height + border_size,
                    ),
                    fill=border_color
                )
            # Paste image on BG
            bg.paste(img, (paste_x, paste_y), img if has_transparency(img) else None)

        # Add padding after image, to cover up border
        if padding_color:
            if left_padding:
                bg.paste(Image.new("RGB", (left_padding, bg.height), padding_color), (0, 0))
            if right_padding:
                bg.paste(Image.new("RGB", (right_padding, bg.height), padding_color), (bg.width - right_padding, 0))
            if top_padding:
                bg.paste(Image.new("RGB", (bg.width, top_padding), padding_color), (0, 0))
            if bottom_padding:
                bg.paste(Image.new("RGB", (bg.width, bottom_padding), padding_color), (0, bg.height - bottom_padding))
        return bg

    def get_bg_border_padding_colors(self, img: Image, bg_color: str, border_color: str = "", padding_color: str = "",
                                     image_file_path: str = "", redo_cache: bool = False) -> tuple[str, str, str]:
        common_colors = None

        def get_color_by_mode(config_value: str) -> str | tuple[int, int, int]:
            nonlocal common_colors
            if "kmean" not in config_value and "mean_shift" not in config_value:
                return config_value
            if common_colors is None:
                set_cache = False
                if self.settings.get("use_common_color_cache", True) and not redo_cache:
                    with Db(table=self.table_name) as db:
                        print("Using cached common colors")
                        common_colors = db.get_common_color_cache(image_file_path)
                        set_cache = True
                if common_colors is None:
                    if "kmean" in config_value:
                        import kmeans
                        common_colors = kmeans.get_common_colors_from_image(img, self.config)
                    elif "mean_shift" in config_value:
                        import mean_shift
                        common_colors = mean_shift.get_common_colors_from_image(img, self.config)
                    else:
                        raise ValueError(
                            f"Invalid config value: {config_value} "
                            f"(I probably need to fix the get_color_by_mode function)"
                        )
                if set_cache or redo_cache:
                    with Db(table=self.table_name) as db:
                        db.set_common_color_cache(image_file_path, common_colors)

            return get_common_color(common_colors, config_value)

        bg_color = get_color_by_mode(bg_color)
        border_color = get_color_by_mode(border_color)
        padding_color = get_color_by_mode(padding_color)

        return bg_color, border_color, padding_color

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

    def show_previous_image(self, _event=None):
        if not self.file_path_history:
            msg = "No previous images in history."
            with wx.MessageDialog(self, msg, "Empty history list") as dialog:
                dialog.ShowModal()
            return
        self.cycle_timer.Stop()
        self.original_file_path = self.file_path_history.pop()
        print(f"History: {self.file_path_history}")
        self.set_wallpaper(self.original_file_path)

    def run_icon_loop(self):
        threading.Thread(name="icon.run()", target=self.icon.run, daemon=True).start()

    def run_watchdog(self):
        self.observer = Observer()
        with Db(self.table_name) as db:
            folders = db.get_active_folders()
            for folder in folders:
                eagle_folder_ids = None
                if folder["eagle_folder_data"] is not None:
                    eagle_folder_ids = list(json.loads(folder["eagle_folder_data"]).values())
                self.add_observer_schedule(
                    folder["filepath"],
                    folder["include_subdirectories"],
                    eagle_folder_ids,
                )
        try:
            self.observer.start()
        except OSError as e:
            print(e, file=sys.stderr)

    def add_observer_schedule(self, dir_path: str, include_subfolders: bool = False,
                              eagle_folder_ids: Optional[list[str]] = None):
        is_eagle = eagle_folder_ids is not None
        if dir_path not in self.event_handlers:
            event_handler = MyEventHandler(self, dir_path, is_eagle, eagle_folder_ids)
            self.event_handlers[dir_path] = event_handler
        elif is_eagle:
            event_handler = self.event_handlers[dir_path]
            event_handler.eagle_folder_ids = eagle_folder_ids
        else:
            return
        self.observer.schedule(
            event_handler,
            dir_path,
            recursive=include_subfolders or is_eagle
        )
        print("Scheduled watchdog for folder {}".format(dir_path))

    # GUI Functions
    def select_file_list(self, _event):
        selected_file_list = self.file_list_dropdown.GetValue()
        if selected_file_list == "<Add new file list>":
            dlg = wx.TextEntryDialog(self, "Enter the name of the new file list:", "Creating New File List", "")
            if dlg.ShowModal() == wx.ID_CANCEL:
                self.file_list_dropdown.SetValue(self.settings.get("selected_file_list", "default"))
                return
            text = dlg.GetValue()
            file_list_name = self.normalize_file_list_name(text)
            self.table_name = f"images_{file_list_name}"
            with Db(self.table_name) as db:
                db.make_images_table()
                image_tables = db.get_image_tables()
                self.file_list_dropdown.Set(image_tables + ["<Add new file list>"])
                self.file_list_dropdown.SetValue(file_list_name)
        else:
            self.table_name = f"images_{selected_file_list}"
        if _event:
            # Only advance image if it was in response to a GUI event
            self.advance_image(None, None)
        self.settings["selected_file_list"] = selected_file_list
        self.save_settings()

    def set_delay(self, _event):
        value = self.delay_value.GetValue()
        units = {"seconds": 1, "minutes": 60, "hours": 3600}
        unit = self.delay_dropdown.GetValue()
        self.delay = value * units[unit] * 1000  # ms
        print(self.delay)
        if _event:
            self.settings["delay_value"] = value
            self.settings["delay_unit"] = unit
            self.save_settings()

    def set_enable_ephemeral_refresh(self, _event):
        value = self.enable_ephemeral_refresh_checkbox.GetValue()
        self.settings["enable_ephemeral_refresh"] = value
        self.save_settings()

    def set_ephemeral_refresh_delay(self, _event):
        value = self.ephemeral_refresh_value.GetValue()
        units = {"seconds": 1, "minutes": 60, "hours": 3600}
        unit = self.ephemeral_refresh_dropdown.GetValue()
        self.ephemeral_refresh_delay = value * units[unit]  # seconds
        print(self.ephemeral_refresh_delay)
        if _event:
            self.settings["ephemeral_refresh_delay_value"] = value
            self.settings["ephemeral_refresh_delay_unit"] = unit
            self.save_settings()

    def apply_padding(self, _event):
        self.settings["left_padding"] = self.left_padding.GetValue()
        self.settings["right_padding"] = self.right_padding.GetValue()
        self.settings["top_padding"] = self.top_padding.GetValue()
        self.settings["bottom_padding"] = self.bottom_padding.GetValue()
        self.save_settings()
        if self.use_padding_test_checkbox.GetValue():
            img = self.resize_image_to_bg(None, "red", "", "white")
            # Write to temp file
            temp_file_path = self.temp_image_filename + ".png"
            img.save(temp_file_path)
            self.set_desktop_wallpaper(temp_file_path)
        else:
            self.set_wallpaper(self.original_file_path)

    def set_keybind(self, label: wx.StaticText, keybind_name: str):
        # self.keybind_listener.stop()
        with KeybindDialog(self) as dialog:
            dialog.ShowModal()
            keybinds = dialog.key_binds
        dialog.Destroy()
        if keybinds:
            self.keybind_listener.update_keybind(keybind_name + "_image", keybinds)
            label.SetLabel(keybinds)
            self.settings[keybind_name + "_image_keybind"] = keybinds
            self.save_settings()
        # wx.CallAfter(lambda _event: self.keybind_listener.start(), 1)

    def clear_keybind(self, label: wx.StaticText, keybind_name: str):
        self.keybind_listener.update_keybind(keybind_name + "_image", None)
        label.SetLabel("<not set>")
        del self.settings[keybind_name + "_image_keybind"]
        self.save_settings()

    @staticmethod
    def normalize_file_list_name(name):
        return re.sub(r"[^a-z_]", "", name.lower().replace(" ", "_"))

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
        with open(os.path.join(dir_path, "metadata.json"), "rb") as f:
            metadata = json.load(f)
        image_folders = {}

        def add_to_image_folder_dict(folder_list: list[dict]):
            for folder in folder_list:
                image_folders[folder["name"]] = folder["id"]
                if folder["children"]:
                    add_to_image_folder_dict(folder["children"])

        add_to_image_folder_dict(metadata["folders"])

        # Prompt the user to pick a folder name
        folder_names, folder_ids = zip(*image_folders.items())
        with wx.MultiChoiceDialog(self, "Pick Folders to add to Wallpaper List", "Folders:",
                                  choices=folder_names) as choice_dialog:
            if choice_dialog.ShowModal() == wx.ID_CANCEL:
                return
        folder_data = {folder_names[i]: folder_ids[i] for i in choice_dialog.GetSelections()}
        dir_path = dir_path.replace("\\", "/")

        with Db(table=self.table_name) as db:
            # If we're adding images to the file list for the first time, pick a random image after load
            advance_image_after_load = bool(not db.get_all_active_count())
            # Add folder data to existing folder data, and return the combined data
            folder_data = db.add_eagle_folder(dir_path, folder_data)
            db.remove_ephemeral_images_in_folder(dir_path)
        folder_ids = list(folder_data.values())
        file_paths = self.get_file_list_in_eagle_folder(dir_path, folder_ids)
        if file_paths:
            with Db(table=self.table_name) as db:
                db.add_images(file_paths, ephemeral=True)
        self.add_observer_schedule(dir_path, eagle_folder_ids=folder_ids)
        if file_paths and advance_image_after_load:
            self.trigger_image_loop(None)

    def error_dialog(self, message: str, title: str = None):
        with wx.MessageDialog(self, message, "Error" if title is None else title,
                              style=wx.OK | wx.ICON_ERROR) as dialog:
            dialog.ShowModal()

    def refresh_ephemeral_images(self, force_refresh=False):
        # Check ephemeral image refresh delay first, and end early if we need to wait longer.
        if not force_refresh:
            if not self.settings.get("enable_ephemeral_refresh", True):
                return
            if self.last_ephemeral_image_refresh + self.ephemeral_refresh_delay > time.time():
                return
        with Db(table=self.table_name) as db:
            folders = list(db.get_active_folders())
            for folder in folders:
                print(f"Refreshing ephemeral images for {folder['filepath']}")
                if folder["is_eagle_directory"]:
                    file_paths = self.get_file_list_in_eagle_folder(folder["filepath"], folder["eagle_folder_data"])
                else:
                    file_paths = self.get_file_list_in_folder(folder["filepath"], folder["include_subdirectories"])
                if file_paths:
                    db.add_images(file_paths, ephemeral=True)
        self.last_ephemeral_image_refresh = time.time()

    def get_file_list_in_folder(self, dir_path: str, include_subfolders: bool) -> Sequence[str]:
        file_paths = []
        allowed_extensions = ["." + f.strip(" ").strip(".")
                              for f in self.config.get("Advanced", "Image types").lower().split(",")]
        for dir_path, dir_names, filenames in os.walk(dir_path):
            # If we don't want to include subfolders, clearing the `dir_names` list will stop os.walk() at the
            # top-level directory.
            if not include_subfolders:
                dir_names.clear()
            for filename in filenames:
                ext = os.path.splitext(filename)[1].lower()
                if ext in allowed_extensions:
                    file_paths.append(os.path.join(dir_path, filename).replace("\\", "/"))
        return file_paths

    def get_file_list_in_eagle_folder(self, dir_path: str, folder_ids: list[str]) -> Sequence[str]:
        self.processing_eagle = True
        progress_bar = wx.ProgressDialog("Loading Eagle library", "Scanning image folders...",
                                         style=wx.PD_APP_MODAL | wx.PD_AUTO_HIDE | wx.PD_ELAPSED_TIME | wx.PD_CAN_ABORT)
        try:
            file_list = []
            folder_list = glob(os.path.join(dir_path, "images/*"))
            total_folders = len(folder_list)
            progress_bar.SetRange(total_folders)
            progress_bar.Update(0, f"Scanning image folders... (0/{total_folders})")
            for i, folder_path in enumerate(folder_list):
                file_path = self.parse_eagle_folder(folder_path, folder_ids, ignore_lock=True)
                if file_path is not None:
                    file_list.append(file_path)
                pb_status = progress_bar.Update(i + 1, newmsg=f"Scanning image folders... ({i + 1}/{total_folders})")
                # If user clicked Abort, return early
                if not pb_status[0]:
                    return []
            return file_list
        finally:
            progress_bar.Close()
            self.processing_eagle = False

    def parse_eagle_folder(self, dir_path: str, folder_ids: list[str], ignore_lock: bool = False) -> Optional[str]:
        if self.processing_eagle and not ignore_lock:
            return None
        file_list = glob(os.path.join(dir_path, "*.*"))
        if os.path.join(dir_path, "metadata.json") not in file_list:
            print(f"No metadata.json file found in {dir_path}", file=sys.stderr)
            print(file_list, file=sys.stderr)
            return None
        try:
            with open(os.path.join(dir_path, "metadata.json"), "rb") as f:
                metadata = json.load(f)
        except JSONDecodeError as e:
            print(f"Error when decoding {os.path.join(dir_path, 'metadata.json')}", file=sys.stderr)
            print(e, file=sys.stderr)
            return None
        # Skip if it's not a folder_id we care about
        try:
            if not set(folder_ids).intersection(metadata["folders"]):
                return None
        except TypeError as e:
            print(folder_ids, file=sys.stderr)
            print(metadata["folders"], file=sys.stderr)
            raise
        print(f"Loading image from {dir_path}...")
        for file_path in file_list:
            if file_path.endswith("metadata.json"):
                continue
            if len(file_list) > 2 and file_path.endswith("_thumbnail.png"):
                continue
            return file_path.replace("\\", "/")
        print(f"No non-thumbnail image found in {dir_path}", file=sys.stderr)
        return None

    def advance_image(self, _icon, _item):
        self.trigger_image_loop(None)

    def open_image_file(self, _icon, _item):
        subprocess.run(["cmd", "/c", "start", "", os.path.abspath(self.original_file_path)])

    def copy_image_to_clipboard(self, _icon, _item):
        img = Image.open(self.original_file_path)

        # Convert the image to a format suitable for the clipboard (DIB)
        output = BytesIO()
        img.convert("RGB").save(output, "BMP")
        data = output.getvalue()[14:]
        output.close()

        # Open the clipboard and set the image data
        win32clipboard.OpenClipboard()
        win32clipboard.EmptyClipboard()
        win32clipboard.SetClipboardData(win32clipboard.CF_DIB, data)
        win32clipboard.CloseClipboard()

    def go_to_image_file(self, _icon, _item):
        subprocess.Popen(["explorer", "/select,", os.path.abspath(self.original_file_path)])

    def remove_image_from_file_list(self, _icon, _item):
        with Db(table=self.table_name) as db:
            db.set_image_to_inactive(self.original_file_path)
        self.advance_image(_icon, _item)

    def delete_image(self, _icon=None, _item=None):
        path = self.original_file_path
        title, message = "Delete image?", f"Are you sure you want to delete {path}"
        with wx.MessageDialog(self, message, title, style=wx.ICON_WARNING | wx.YES_NO) as messageDialog:
            answer = messageDialog.ShowModal()
            if answer == wx.ID_NO:
                return
        ext = os.path.splitext(path)[1]
        backup_path = self.config.get("Advanced", "Deleted image path") + ext
        print(f"Moving {path} to {backup_path}")
        shutil.move(path, backup_path)
        with Db(table=self.table_name) as db:
            db.delete_image(path)
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
        if self.icon:
            self.icon.stop()  # Remove the system tray icon
        if self.observer:
            self.observer.stop()
        if self.keybind_listener:
            self.keybind_listener.stop()
        wx.Exit()


class MyEventHandler(FileSystemEventHandler):

    def __init__(self, parent: PyWallpaper, dir_path: str, eagle_mode: bool = False,
                 eagle_folder_ids: Optional[list[str]] = None):
        super().__init__()
        self.parent = parent
        self.dir_path = dir_path
        self.eagle_mode = eagle_mode
        self.eagle_folder_ids = eagle_folder_ids
        self.eagle_timer = None
        self.debounce_time = 3  # seconds

    def on_created(self, event):
        if event.is_directory or event.src_path.endswith("@SynoEAStream"):
            return
        print(f"File created: {event.src_path}")
        self.add_file(event.src_path)

    def on_modified(self, event):
        # TODO Add way to remove eagle files if the folder_id in metadata.json is changed.
        if event.is_directory or event.src_path.endswith("@SynoEAStream"):
            return
        print(f"File modified: {event.src_path}")
        self.add_file(event.src_path)

    def add_file(self, file_path: str):
        file_path = file_path.replace("\\", "/")
        if self.eagle_mode:
            print(f"Adding '{file_path}' in Eagle mode. eagle_folder_ids={self.eagle_folder_ids}")
            base_dir = os.path.dirname(file_path)
            file_path = self.parent.parse_eagle_folder(base_dir, self.eagle_folder_ids)
            if file_path is None:
                return
        with Db(table=self.parent.table_name) as db:
            db.add_images([file_path], ephemeral=True)

    def on_deleted(self, event):
        if event.is_directory or event.src_path.endswith("@SynoEAStream"):
            return
        print(f"File deleted: {event.src_path}")
        file_path = event.src_path.replace("\\", "/")
        with Db(table=self.parent.table_name) as db:
            db.delete_image(file_path)


def parse_args():
    parser = ArgumentParser("PyWallpaper")
    parser.add_argument("-d", "--debug", action="store_true")
    return parser.parse_args()


if __name__ == '__main__':
    args = parse_args()
    app = wx.App()
    PyWallpaper(debug=args.debug).post_init()
    app.MainLoop()

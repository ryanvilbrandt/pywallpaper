import ctypes
import io
import os
import random
import re
import shutil
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import messagebox, filedialog

import pystray
import win32api
import win32clipboard
import win32evtlog
import win32evtlogutil
from PIL import Image, ImageFont, ImageDraw

SPI_SETDESKWALLPAPER = 20
DELAY = 3 * 60 * 1000  # 3 minutes in ms
ERROR_DELAY = 10
FILE_LIST_PATH = "wallpaper_files.txt"
ADD_FILEPATH_TO_IMAGES = True

font_path = "arial.ttf"
try:
    FONT = ImageFont.truetype(font_path, 24)
except OSError:
    print(f"Couldn't find font at '{font_path}'")
    FONT = ImageFont.load_default()
TEMP_IMAGE_FILENAME = os.path.join(os.environ["TEMP"], "wallpaper")
# Move wallpapers instead of deleting them as a safety against accidental deletion
DELETED_IMAGE_PATH = "deleted_wallpaper"

ICON_PATH = r"icon.webp"


class PyWallpaper:

    file_list = []
    original_file_path = None
    timer_id = None

    def __init__(self):
        self.root = tk.Tk()
        self.root.title("pyWallpaper")

        self.root.wm_minsize(width=200, height=100)

        # Create a system tray icon
        self.image = Image.open(ICON_PATH)
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
        self.add_button = tk.Button(self.root, text="Add Files to Wallpaper List", command=self.add_files_to_list)
        self.add_button.pack(pady=10)
        self.show_button = tk.Button(self.root, text="Open Wallpaper List", command=self.show_file_list)
        self.show_button.pack()
        self.add_filepath_to_images = tk.BooleanVar(value=ADD_FILEPATH_TO_IMAGES)
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

    # Loop functions
    def run(self):
        self.read_file_list()
        self.trigger_image_loop()
        self.run_icon_loop()
        self.root.mainloop()

    def read_file_list(self):
        if not os.path.isfile(FILE_LIST_PATH):
            self.file_list = []
        with open(FILE_LIST_PATH) as f:
            file_list = re.split(r"\r?\n", f.read())
            # Remove empty lines
            self.file_list = [path for path in file_list if path]

    def write_file_list(self):
        with open(FILE_LIST_PATH, "w") as f:
            f.write("\r\n".join(self.file_list))

    def trigger_image_loop(self):
        if self.timer_id:
            self.root.after_cancel(self.timer_id)
        self.original_file_path = random.choice(self.file_list)
        print(self.original_file_path)
        try:
            file_path = self.make_image(self.original_file_path)
        except FileNotFoundError:
            print(f"Couldn't open image path {self.original_file_path!r}", file=sys.stderr)
            self.timer_id = self.root.after(ERROR_DELAY, self.trigger_image_loop)
        else:
            success = self.set_desktop_wallpaper(file_path)
            # print(success)
            self.timer_id = self.root.after(DELAY, self.trigger_image_loop)

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
        temp_file_path = TEMP_IMAGE_FILENAME + ext
        print(temp_file_path)
        img.save(temp_file_path)
        return temp_file_path

    @staticmethod
    def resize_image_to_bg(img: Image):
        # Determine aspect ratios
        image_aspect_ratio = img.width / img.height
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

    @staticmethod
    def add_text_to_image(img: Image, text: str):
        draw = ImageDraw.Draw(img)
        text_x, text_y, text_width, text_height = draw.textbbox((0, 0), text, font=FONT)
        text_x = img.width - text_width - 10  # 10 pixels padding from the right
        text_y = img.height - text_height - 10  # 10 pixels padding from the bottom
        draw.text((text_x, text_y), text, font=FONT, fill="yellow", stroke_width=2, stroke_fill="black")

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
        file_paths = filedialog.askopenfilenames(
            title="Select Images",
            filetypes=(
                ("Image Files", "*.gif;*.jpg;*.jpeg;*.png"),
                ("All Files", "*.*"),
            )
        )
        self.file_list += file_paths
        self.write_file_list()

    def show_file_list(self):
        os.startfile(FILE_LIST_PATH)

    def advance_image(self, icon, item):
        self.trigger_image_loop()

    def open_image_file(self, icon, item):
        subprocess.run(["cmd", "/c", "start", "", self.original_file_path])

    def copy_image_to_clipboard(self, icon, item):
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
        win32clipboard.SetClipboardData(49159, self.original_file_path)  # FileNameW
        win32clipboard.CloseClipboard()

    def go_to_image_file(self, icon, item):
        subprocess.Popen(["explorer", "/select,", self.original_file_path])

    def remove_image_from_file_list(self, icon, item):
        self.remove_image_from_file_list_inner(self.original_file_path)
        self.advance_image(icon, item)

    def delete_image(self, icon, item):
        path = self.original_file_path
        result = messagebox.askokcancel("Delete image?", f"Are you sure you want to delete {path}")
        if result:
            ext = os.path.splitext(path)[1]
            backup_path = DELETED_IMAGE_PATH + ext
            shutil.move(path, backup_path)
            self.remove_image_from_file_list_inner(path)
            print(f"Moving {path} to {backup_path}")
            self.icon.notify("Deleted wallpaper", f"{path} has been deleted.")
            self.advance_image(icon, item)

    def remove_image_from_file_list_inner(self, path: str):
        self.file_list.remove(path)
        self.write_file_list()
        print("Removed {} from the file list")

    def minimize_to_tray(self):
        # self.root.iconify()  # Minimize the main window
        self.root.withdraw()  # Hide the main window
        # self.icon.notify("App minimized", "The app has been minimized to the system tray.")

    def restore_from_tray(self, icon, item):
        self.root.deiconify()  # Restore the main window

    def on_exit(self, *args):
        self.icon.stop()  # Remove the system tray icon
        self.root.destroy()


if __name__ == "__main__":
    app = PyWallpaper()
    app.run()

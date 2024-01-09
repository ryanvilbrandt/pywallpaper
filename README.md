A GUI application with a systray icon, that lets you pick a list of images to apply to your desktop background

**IMPORTANT NOTE**: Due to limitations in how Windows applies desktop backgrounds, this app will apply the same background to ALL monitors at once. If you have monitors with different sizes and orientations, this means the image will be improperly sized for some of your monitors.

# Installation

Install all required libraries with `pip install -r requirements.txt`

# Usage

1. Run `python main.py`
2. Right-click the pyWallpaper icon that popped up in your system tray and click Show Window.
3. Click the "Add Files to Wallpaper List" button.
4. Select some files to add to the list of images that will be cycled through by pyWallpaper.

And you're set! You can add more images to the list by clicking the "Add Files to Wallpaper List" button and selecting more files. You can remove files individually as they come up with the Remove Image context menu option, or Delete Image to delete the file itself.

You can change various behaviors by editing the `config.ini` file that will be created after you run the app for the first time.

# Troubleshooting

## Image isn't sized properly to the monitor I want

Change the `Force monitor size` config option to the correct monitor size. e.g. `1920, 1080`

# TODO

* Display images in a given file list
* Allow picking of file lists from within the app
* App will watch for file changes in added folders
* Option to create auto-collage of random images for each wallpaper
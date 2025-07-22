A GUI application with a systray icon, that lets you pick a list of images to apply to your desktop background

**IMPORTANT NOTE**: Due to limitations in how Windows applies desktop backgrounds, this app will apply the same background to ALL monitors at once. If you have monitors with different sizes and orientations, this means the image will be improperly sized for some of your monitors.

# Installation

1. Install [Python 3.11 or greater](https://www.python.org/downloads/)
2. Create a Python virtual environment and install all dependencies:

```commandline
python -m venv venv/
call venv/Scripts/activate.bat
pip install -r requirements.txt
```

# Usage

1. Run `run.bat`
2. Right-click the pyWallpaper icon that popped up in your system tray and click Show Window.
3. Click the "Add Files to Wallpaper List" button.
4. Select some files to add to the list of images that will be cycled through by pyWallpaper.

And you're set! You can add more images to the list by clicking the "Add Files to Wallpaper List" button and selecting more files. You can remove files individually as they come up with the Remove Image context menu option, or Delete Image to delete the file itself.

You can change various behaviors by editing the `config.ini` file that will be created after you run the app for the first time.

## Random algorithm

The `Random algorithm` config setting defines how the wallpaper images are picked. It allows for the following options:

* **Pure**: Picks a random image from all available images
* **Weighted**: Picks a random image weighted based on how often the images have previously been picked. The more often an image has been used, the less likely it is to be picked.
* **Least used**: Picks a random image from all the least used images.

## Debug Mode

You can start PyWallpaper in debug mode if you set the environment variable `PYWALLPAPER_DEBUG_MODE` to any value.

Debug mode features:

* Show PyWallpaper window on launch.
* X will close PyWallpaper, not minimize it.
* Logs will be written directly to the console.

# Troubleshooting

## Program doesn't start when I run `run.bat`

It's likely that the application is failing to start due to an invalid config or perhaps some necessary libraries weren't installed (usually happens after an update).

Run `run_in_debug.bat` to make whatever error is being thrown show up in the console window.

## Image isn't sized properly to the monitor I want

Change the `Force monitor size` config option to the correct monitor size. e.g. `1920, 1080`

# TODO

* Display images in a given file list
* Add the ability to remove folders that were added to file lists
* Option to create auto-collage of random images for each wallpaper

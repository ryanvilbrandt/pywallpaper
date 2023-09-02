A GUI application with a systray icon, that lets you pick a list of images to apply to your desktop background

**IMPORTANT NOTE**: Due to limitations in how Windows applies desktop backgrounds, this app will apply the same background to ALL monitors at once. If you have different size and orientations monitors, this means the image will be improperly sized for some of your monitors.

# Installation

Install all required libraries with `pip install -r requirements.txt`

# Usage

Run `python main.py`

You can change various behaviors by editing the variables under "# CONFIG OPTIONS" in `main.py`

**Image not sized properly to the monitor you want?** Change the `FORCE_MONITOR_SIZE` variable to the correct monitor size. e.g. (1920, 1080)
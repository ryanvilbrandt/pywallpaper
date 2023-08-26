import ctypes
from ctypes import wintypes

import win32clipboard

# Constants from Windows API
CF_HDROP = 15

class DROPFILES(ctypes.Structure):
    _fields_ = [
        ("pFiles", wintypes.DWORD),
        ("pt", wintypes.POINT),
        ("fNC", wintypes.BOOL),
        ("fWide", wintypes.BOOL)
    ]

def set_clipboard_hdrop_data(file_paths):
    dropfiles = create_dropfiles_struct(file_paths)

    # Open and set clipboard data
    win32clipboard.OpenClipboard()
    win32clipboard.EmptyClipboard()
    win32clipboard.SetClipboardData(CF_HDROP, dropfiles)
    win32clipboard.CloseClipboard()

def create_dropfiles_struct(file_paths):
    # Calculate the required memory size
    file_string = "\0".join(file_paths) + "\0\0"
    memory_size = ctypes.sizeof(DROPFILES) + len(file_string.encode("utf-16le"))

    # Allocate global memory and copy data
    hdrop = ctypes.windll.kernel32.GlobalAlloc(0x0002, memory_size)
    dropfiles = DROPFILES()
    dropfiles.pFiles = ctypes.sizeof(DROPFILES)
    dropfiles.fWide = 1  # Indicates Unicode paths

    buffer = ctypes.c_char_p(ctypes.addressof(dropfiles) + ctypes.sizeof(DROPFILES))
    ctypes.memmove(buffer, file_string.encode("utf-16le"), len(file_string.encode("utf-16le")))

    ctypes.windll.kernel32.GlobalUnlock(hdrop)
    return hdrop

if __name__ == "__main__":
    file_paths = [
        r"C:\Users\marco\Documents\Github\dnd_item_cards\images\potion_of_growth.jpeg"
    ]

    set_clipboard_hdrop_data(file_paths)
    print("Files copied to clipboard in CF_HDROP mode.")

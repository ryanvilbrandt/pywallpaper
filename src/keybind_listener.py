import sys
from typing import Union, TypedDict, Callable

import wx

# Optional import for users who haven't reinstalled their packages since a new update
try:
    from pynput import keyboard
    from pynput.keyboard import Key, KeyCode
except ImportError:
    keyboard, Key, KeyCode = None, None, None


class CallbackDict(TypedDict):
    keybinds: set[Union[Key, KeyCode]] | None
    callback: Callable


Callbacks = dict[str, CallbackDict]
MODIFIERS = {
    Key.alt, Key.alt_l, Key.alt_r, Key.alt_gr,
    Key.cmd, Key.cmd_l, Key.cmd_r,
    Key.ctrl, Key.ctrl_l, Key.ctrl_r,
    Key.shift, Key.shift_l, Key.shift_r,
}


class KeybindListener:

    def __init__(self, name: str, suppress: bool = False):
        """
        :raises ImportError: If the `pynput` library is not installed.
        """
        if keyboard is None:
            raise ImportError("pynput not installed")

        self.name = name
        self.pressed_keys: set[Union[Key, KeyCode]] = set()
        self.callbacks: Callbacks = {}

        self.listener = keyboard.Listener(
            on_press=self.on_press,
            on_release=self.on_release,
            suppress=suppress,
        )

    def register_callback(self, keybind_name: str, keybind_string: str, callback: callable):
        """
        :param keybind_name: Name of the keybinding, for reference.
        :param keybind_string: The string representation of the keybinding to listen for. E.g. "ctrl+shift+a"
        :param callback: The function to call when the specified keybinding is triggered. Must take no arguments.
        """
        if keybind_string:
            keybind_set = self.parse_keybind_combination(keybind_string)
        else:
            # If keybind is undefined, set the keybind set to None so we can easily update later.
            keybind_set = None
        self.callbacks[keybind_name] = {"keybinds": keybind_set, "callback": callback}

    def update_keybind(self, keybind_name: str, keybind_string: str | None):
        for name, d in self.callbacks.items():
            if keybind_name == name:
                d["keybinds"] = self.parse_keybind_combination(keybind_string) if keybind_string else None
                return
        else:
            raise ValueError(f"Keybind {keybind_name} not found")

    def remove_callback(self, keybind_name: str):
        del self.callbacks[keybind_name]

    def start(self):
        if self.listener.ident:
            # Listener has already grabbed a thread. Rejoin it instead of starting a new one.
            self.listener.join()
        else:
            self.listener.start()
            self.listener.wait()

    def stop(self):
        self.listener.stop()

    def on_press(self, key: Union[Key, KeyCode]):
        normalized_key = self.normalize_key(key)
        self.pressed_keys.add(normalized_key)
        # print(self.pressed_keys)
        for keybind_name, d in self.callbacks.items():
            if keybind_name == "auto_capture":
                # A special callback that triggers whenever a non-modifier key is pressed.
                # Passes the final set of Keys to the callback
                if key not in MODIFIERS:
                    d["callback"](self.pressed_keys)
                    return
            if self.pressed_keys == d["keybinds"]:
                print(self.format_keybind_combination(self.pressed_keys))
                d["callback"]()

    def on_release(self, key: Union[Key, KeyCode]):
        try:
            self.pressed_keys.remove(self.normalize_key(key))
        except KeyError as e:
            print(e, file=sys.stderr)

    def normalize_key(self, key: Union[Key, KeyCode]) -> Union[Key, KeyCode]:
        if isinstance(key, KeyCode):
            return self.listener.canonical(key)
        return key

    @staticmethod
    def parse_keybind_combination(keybind: str) -> set[Union[Key, KeyCode]]:
        """
        Converts a string keybind to a set of pynput keys.
        """
        key_parts = keybind.lower().split("+")
        keybind_combination = set()
        for part in key_parts:
            if hasattr(Key, part):
                keybind_combination.add(getattr(Key, part))
            else:
                keybind_combination.add(KeyCode.from_char(part))
        return keybind_combination

    def format_keybind_combination(self, keybind_set: set[Union[Key, KeyCode]]) -> str:
        key_names = []
        for key in keybind_set:
            if isinstance(key, KeyCode):
                key_names.append(key.char.title())
            elif isinstance(key, Key):
                key_names.append(key.name.title())
        return "+".join(sorted(key_names, key=self.keybind_sort_key))

    @staticmethod
    def keybind_sort_key(key: str) -> tuple[int, str]:
        """
        Makes sure key names are always sorted with the following priority:
        Cmd, Ctrl, Alt, Shift, Other

        Returns a tuple of (priority, key name), so that two keys with the same priority
        can be sorted lexicographically. E.g. ctrl, ctrl_l, ctrl_r
        """
        key = key.lower()
        if key.startswith("cmd"):
            priority = 0
        elif key.startswith("ctrl"):
            priority = 1
        elif key.startswith("alt"):
            priority = 2
        elif key.startswith("shift"):
            priority = 3
        else:
            priority = 4
        return priority, key


class KeybindDialog(wx.Dialog):

    def __init__(self, parent):
        super(KeybindDialog, self).__init__(parent, title="Keybind Dialog")

        self.key_binds = None

        panel = wx.Panel(self)
        text = wx.StaticText(panel, label="Type a set of keys to bind to the action", style=wx.ALIGN_CENTER)

        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(text, 1, wx.ALL | wx.ALIGN_CENTER, 5)
        panel.SetSizer(sizer)

        self.listener = KeybindListener("Dialog listener", suppress=True)
        self.listener.register_callback("auto_capture", "auto_capture", self.on_key)
        self.listener.start()

        self.Bind(wx.EVT_CLOSE, self.on_close)

    def on_key(self, key_binds: set[Union[Key, KeyCode]]):
        self.key_binds = self.listener.format_keybind_combination(key_binds)
        self.Close()

    def on_close(self, _event):
        self.listener.stop()
        del self.listener
        self.EndModal(wx.ID_OK)

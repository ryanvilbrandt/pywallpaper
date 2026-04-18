import ctypes
import logging
import sys
from typing import Union, TypedDict, Callable

import wx

# Optional import for users who haven't reinstalled their packages since a new update
try:
    from pynput import keyboard
    from pynput.keyboard import Key, KeyCode
except ImportError:
    keyboard, Key, KeyCode = None, None, None

logger = logging.getLogger(__name__)


class CallbackDict(TypedDict):
    keybinds: set[Union[Key, KeyCode]] | None
    callback: Callable


Callbacks = dict[str, CallbackDict]

if Key is not None:
    MODIFIERS = {
        Key.alt, Key.alt_l, Key.alt_r, Key.alt_gr,
        Key.cmd, Key.cmd_l, Key.cmd_r,
        Key.ctrl, Key.ctrl_l, Key.ctrl_r,
        Key.shift, Key.shift_l, Key.shift_r,
    }
    MODIFIER_CANONICAL_MAP = {
        Key.alt: Key.alt,
        Key.alt_l: Key.alt,
        Key.alt_r: Key.alt,
        Key.alt_gr: Key.alt,
        Key.cmd: Key.cmd,
        Key.cmd_l: Key.cmd,
        Key.cmd_r: Key.cmd,
        Key.ctrl: Key.ctrl,
        Key.ctrl_l: Key.ctrl,
        Key.ctrl_r: Key.ctrl,
        Key.shift: Key.shift,
        Key.shift_l: Key.shift,
        Key.shift_r: Key.shift,
    }
    # Windows virtual key codes for polling current modifier state.
    WINDOWS_MODIFIER_VKEYS = {
        Key.alt: (0x12, 0xA4, 0xA5),
        Key.cmd: (0x5B, 0x5C),
        Key.ctrl: (0x11, 0xA2, 0xA3),
        Key.shift: (0x10, 0xA0, 0xA1),
    }
else:
    MODIFIERS = set()
    MODIFIER_CANONICAL_MAP = {}
    WINDOWS_MODIFIER_VKEYS = {}


class KeybindListener:

    def __init__(self, name: str, suppress: bool = False):
        """
        :raises ImportError: If the `pynput` library is not installed.
        """
        if keyboard is None:
            raise ImportError("pynput not installed")

        self.name = name
        self.pressed_non_mod_keys: set[Union[Key, KeyCode]] = set()
        self.pressed_modifiers: set[Key] = set()
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
        if normalized_key in MODIFIERS:
            self.pressed_modifiers.add(self.canonicalize_modifier(normalized_key))
        else:
            self.pressed_non_mod_keys.add(normalized_key)
        self.pressed_keys = self.current_pressed_keys()
        # logger.debug(self.pressed_keys)
        for keybind_name, d in self.callbacks.items():
            if keybind_name == "auto_capture":
                # A special callback that triggers whenever a non-modifier key is pressed.
                # Passes the final set of Keys to the callback
                if normalized_key not in MODIFIERS:
                    d["callback"](set(self.pressed_keys))
                    return
            if d["keybinds"] and self.keybind_matches_press(d["keybinds"], normalized_key):
                logger.debug(self.format_keybind_combination(self.pressed_keys))
                d["callback"]()

    def on_release(self, key: Union[Key, KeyCode]):
        normalized_key = self.normalize_key(key)
        if normalized_key in MODIFIERS:
            self.pressed_modifiers.discard(self.canonicalize_modifier(normalized_key))
        else:
            # Use discard to recover gracefully from occasional missed or duplicated events.
            self.pressed_non_mod_keys.discard(normalized_key)
        self.pressed_keys = self.current_pressed_keys()

    def normalize_key(self, key: Union[Key, KeyCode]) -> Union[Key, KeyCode]:
        # Canonicalize all keys so modifier aliases (e.g. ctrl_l/ctrl_r) are tracked consistently.
        return self.listener.canonical(key)

    def keybind_matches_press(self, keybind_set: set[Union[Key, KeyCode]], trigger_key: Union[Key, KeyCode]) -> bool:
        """
        Match on key press using live modifier state.
        For the common case of one non-modifier key + modifiers, this avoids trusting historical
        modifier press/release bookkeeping.
        """
        current_modifiers = {k for k in self.pressed_keys if k in MODIFIERS}
        current_non_modifiers = {k for k in self.pressed_keys if k not in MODIFIERS}

        required_modifiers = {
            self.canonicalize_modifier(k) for k in keybind_set if k in MODIFIERS
        }
        required_non_modifiers = {k for k in keybind_set if k not in MODIFIERS}

        if current_modifiers != required_modifiers:
            return False

        if len(required_non_modifiers) == 1:
            return trigger_key == next(iter(required_non_modifiers))
        return current_non_modifiers == required_non_modifiers

    @staticmethod
    def canonicalize_modifier(key: Union[Key, KeyCode]) -> Union[Key, KeyCode]:
        return MODIFIER_CANONICAL_MAP.get(key, key)

    def current_pressed_keys(self) -> set[Union[Key, KeyCode]]:
        keys = set(self.pressed_non_mod_keys)
        keys.update(self.get_active_modifiers())
        if logger.isEnabledFor(logging.DEBUG):
            try:
                keys_str = self.format_keybind_combination(keys) if keys else "<none>"
                logger.debug("current_pressed_keys=%s", keys_str)
            except Exception:
                logger.exception("Failed to format current pressed keys for debug logging")
        return keys

    def get_active_modifiers(self) -> set[Key]:
        # On Windows, query modifier state directly from the OS at event time to avoid stale state.
        if sys.platform.startswith("win"):
            try:
                active_modifiers: set[Key] = set()
                for modifier, vk_codes in WINDOWS_MODIFIER_VKEYS.items():
                    if any(ctypes.windll.user32.GetAsyncKeyState(vk) & 0x8000 for vk in vk_codes):
                        active_modifiers.add(modifier)
                return active_modifiers
            except Exception:
                logger.exception("Error when polling OS modifier key state")

        # Fallback for non-Windows platforms or polling failures.
        return set(self.pressed_modifiers)

    @staticmethod
    def parse_keybind_combination(keybind: str) -> set[Union[Key, KeyCode]]:
        """
        Converts a string keybind to a set of pynput keys.
        """
        key_parts = keybind.lower().split("+")
        keybind_combination = set()
        for part in key_parts:
            if hasattr(Key, part):
                key = getattr(Key, part)
                if key in MODIFIERS:
                    key = MODIFIER_CANONICAL_MAP[key]
                keybind_combination.add(key)
            else:
                keybind_combination.add(KeyCode.from_char(part))
        return keybind_combination

    def format_keybind_combination(self, keybind_set: set[Union[Key, KeyCode]]) -> str:
        key_names = []
        for key in keybind_set:
            if isinstance(key, KeyCode):
                if key.char:
                    key_names.append(key.char.title())
                elif key.vk is not None:
                    key_names.append(f"Vk{key.vk}")
                else:
                    key_names.append(str(key))
            elif isinstance(key, Key):
                key_names.append((key.name or str(key)).title())
            else:
                key_names.append(str(key))
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

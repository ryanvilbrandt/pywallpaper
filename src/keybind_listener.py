# Optional import for users who haven't reimported their packages since a new update
try:
    from pynput import keyboard
    from pynput.keyboard import Key, KeyCode
except ImportError:
    keyboard, Key, KeyCode = None, None, None


class KeybindListener:

    listener: keyboard.Listener = None
    pressed_keys: set[Key | KeyCode] = set()
    keybind_set: set[Key | KeyCode] = set()
    callback: callable = None

    def __init__(self):
        """
        :param keybind_string: The string representation of the keybinding to listen for. E.g. "ctrl+shift+a"
        :param callback: The function to call when the specified keybinding is triggered. Must take one argument,
            the set of Key and KeyCode objects representing the pressed keys.
        :raises ImportError: If the `pynput` library is not installed.
        """
        if keyboard is None:
            raise ImportError("pynput not installed")
        self.listener = keyboard.Listener(
            on_press=self.on_press,
            on_release=self.on_release,
        )

    def register_callback(self, keybind_string: str, callback: callable):
        self.keybind_set = self.parse_keybind_combination(keybind_string)
        self.callback = callback

    def start(self):
        self.listener.start()

    def stop(self):
        self.listener.stop()

    def on_press(self, key: Key | KeyCode):
        normalized_key = self.normalize_key(key)
        self.pressed_keys.add(normalized_key)
        # print(self.pressed_keys)
        if self.pressed_keys == self.keybind_set:
            print("Do the thing!!!")
            print(self.format_keybind_combination(self.pressed_keys))
            self.callback(self.pressed_keys)

    def on_release(self, key: Key | KeyCode):
        self.pressed_keys.remove(self.normalize_key(key))

    def normalize_key(self, key: Key | KeyCode) -> Key | KeyCode:
        if isinstance(key, KeyCode):
            return self.listener.canonical(key)
        return key

    def parse_keybind_combination(self, keybind: str) -> set[Key | KeyCode]:
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

    def format_keybind_combination(self, keybind_set: set[Key | KeyCode]) -> str:
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

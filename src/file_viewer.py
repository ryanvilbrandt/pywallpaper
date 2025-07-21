from typing import Iterator

import wx

from db import Db


class FileViewerApp(wx.App):

    def __init__(self, *args, **kwargs):
        self.file_list = "Cute Girls"
        super().__init__(*args, **kwargs)

    def OnInit(self):
        frame = FileViewerFrame(self, "File Viewer")
        frame.Show()
        return True


class FileViewerFrame(wx.Frame):
    def __init__(self, parent, title):
        self.parent = parent
        super().__init__(None, title=title, size=wx.Size(800, 600))

        self.init_gui()

    def init_gui(self):
        self.SetMinSize(wx.Size(600, 400))

        self.panel = wx.Panel(self)
        self.main_sizer = wx.BoxSizer(wx.VERTICAL)

        controls_sizer = wx.BoxSizer(wx.HORIZONTAL)
        self.add_files_btn = wx.Button(self.panel, label="Add Files")
        self.add_folder_btn = wx.Button(self.panel, label="Add Folder")
        self.show_ephemeral_cb = wx.CheckBox(self.panel, label="Show Ephemeral Files")
        self.show_ephemeral_cb.SetValue(False)
        self.show_ephemeral_cb.Bind(wx.EVT_CHECKBOX, self.on_show_ephemeral_images)
        controls_sizer.Add(self.add_files_btn, 0, wx.ALL, 5)
        controls_sizer.Add(self.add_folder_btn, 0, wx.ALL, 5)
        controls_sizer.AddStretchSpacer(1)
        controls_sizer.Add(self.show_ephemeral_cb, 0, wx.ALL | wx.ALIGN_CENTER_VERTICAL, 5)
        self.main_sizer.Add(controls_sizer, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, 5)

        self.grid_panel = wx.ScrolledWindow(self.panel)
        self.grid_panel.SetScrollRate(20, 20)

        # Only create the sizer here, headers will be added in fill_grid
        self.headers = [
            "Filepath", "Active", "Is Directory", "Ephemeral", "Times Used", "Total Times Used", "Clear Cache"
        ]
        self.num_columns = len(self.headers)
        self.grid_sizer = wx.GridBagSizer()
        self.grid_sizer.AddGrowableCol(0, 1)

        self.grid_panel.SetSizer(self.grid_sizer)
        self.main_sizer.Add(self.grid_panel, 1, wx.EXPAND | wx.ALL, 5)

        self.panel.SetSizer(self.main_sizer)

        self.populate_grid()

        self.Layout()
        self.Fit()

    def populate_grid(self):
        with Db(self.parent.file_list) as db:
            data = db.get_rows(
                include_ephemeral_images=self.show_ephemeral_cb.GetValue()
            )
            self.fill_grid(data)

    def fill_grid(self, data: Iterator[dict]):
        # --- Remove all items from the grid sizer (headers and content) ---
        while self.grid_sizer.GetChildren():
            item = self.grid_sizer.GetChildren()[0]
            window = item.GetWindow()
            sizer = item.GetSizer()
            # FIX: Detach by window or sizer, not by GBSizerItem
            if window:
                self.grid_sizer.Detach(window)
                window.Destroy()
            elif sizer:
                self.grid_sizer.Detach(sizer)
                # Recursively destroy all windows in the sizer
                def destroy_sizer(s):
                    for child in s.GetChildren():
                        w = child.GetWindow()
                        cs = child.GetSizer()
                        if w:
                            w.Destroy()
                        elif cs:
                            destroy_sizer(cs)
                destroy_sizer(sizer)

        # --- Add headers ---
        for i, header in enumerate(self.headers):
            h_sizer = wx.BoxSizer(wx.HORIZONTAL)
            label = wx.StaticText(self.grid_panel, label=header, style=wx.ALIGN_CENTER)
            font = label.GetFont()
            font.SetWeight(wx.FONTWEIGHT_BOLD)
            label.SetFont(font)
            h_sizer.Add(wx.Size(5, 0))
            h_sizer.Add(label, 1, wx.ALIGN_CENTER)
            h_sizer.Add(wx.Size(5, 0))
            self.grid_sizer.Add(h_sizer, pos=(0, i), flag=wx.EXPAND)

        # --- Add data rows ---
        for row_idx, item in enumerate(data, start=1):  # Start from row 1 (after header)
            col_idx = 0

            filepath_sizer = wx.BoxSizer(wx.VERTICAL)
            filepath_text = wx.StaticText(self.grid_panel, label=str(item['filepath']))
            filepath_sizer.Add(filepath_text, 1, wx.EXPAND | wx.CENTER | wx.ALL, 5)
            self.grid_sizer.Add(filepath_sizer, pos=(row_idx, col_idx), flag=wx.EXPAND, border=1)
            col_idx += 1

            active_sizer = wx.BoxSizer(wx.VERTICAL)
            active_cb = wx.CheckBox(self.grid_panel)
            active_cb.SetValue(item['active'])
            active_cb.Bind(wx.EVT_CHECKBOX,
                          lambda evt, fp=item['filepath']: self.on_checkbox_change(evt, fp, "active"))
            active_sizer.Add(active_cb, 1, wx.ALIGN_CENTER, 5)
            self.grid_sizer.Add(active_sizer, pos=(row_idx, col_idx), flag=wx.EXPAND, border=1)
            col_idx += 1

            is_dir_sizer = wx.BoxSizer(wx.VERTICAL)
            is_dir_cb = wx.CheckBox(self.grid_panel)
            is_dir_cb.SetValue(item['is_directory'])
            is_dir_cb.Disable()  # Disable the checkbox
            is_dir_cb.Bind(wx.EVT_CHECKBOX,
                          lambda evt, fp=item['filepath']: self.on_checkbox_change(evt, fp, "is_directory"))
            is_dir_sizer.Add(is_dir_cb, 1, wx.ALIGN_CENTER, 5)
            self.grid_sizer.Add(is_dir_sizer, pos=(row_idx, col_idx), flag=wx.EXPAND, border=1)
            col_idx += 1

            ephemeral_sizer = wx.BoxSizer(wx.VERTICAL)
            ephemeral_cb = wx.CheckBox(self.grid_panel)
            ephemeral_cb.SetValue(item['ephemeral'])
            ephemeral_cb.Disable()  # Disable the checkbox
            ephemeral_cb.Bind(wx.EVT_CHECKBOX,
                          lambda evt, fp=item['filepath']: self.on_checkbox_change(evt, fp, "ephemeral"))
            ephemeral_sizer.Add(ephemeral_cb, 1, wx.ALIGN_CENTER, 5)
            self.grid_sizer.Add(ephemeral_sizer, pos=(row_idx, col_idx), flag=wx.EXPAND, border=1)
            col_idx += 1

            times_sizer = wx.BoxSizer(wx.VERTICAL)
            times_text = wx.StaticText(self.grid_panel, label=str(item['times_used']))
            times_sizer.AddStretchSpacer(1)
            times_sizer.Add(times_text, 0, wx.ALIGN_CENTER_HORIZONTAL, 5)
            times_sizer.AddStretchSpacer(1)
            self.grid_sizer.Add(times_sizer, pos=(row_idx, col_idx), flag=wx.EXPAND, border=1)
            col_idx += 1

            total_sizer = wx.BoxSizer(wx.VERTICAL)
            total_text = wx.StaticText(self.grid_panel, label=str(item['total_times_used']))
            total_sizer.AddStretchSpacer(1)
            total_sizer.Add(total_text, 0, wx.ALIGN_CENTER_HORIZONTAL, 5)
            total_sizer.AddStretchSpacer(1)
            self.grid_sizer.Add(total_sizer, pos=(row_idx, col_idx), flag=wx.EXPAND, border=1)
            col_idx += 1

            clear_sizer = wx.BoxSizer(wx.VERTICAL)
            clear_btn = wx.Button(self.grid_panel, label="Clear", size=(40, -1))
            clear_btn.Bind(wx.EVT_BUTTON,
                         lambda evt, fp=item['filepath']: self.on_clear_cache(evt, fp))
            clear_sizer.Add(clear_btn, 1, wx.ALIGN_CENTER, 5)
            self.grid_sizer.Add(clear_sizer, pos=(row_idx, col_idx), flag=wx.EXPAND, border=1)

            if row_idx >= 50:
                break

        self.grid_panel.Layout()

    def create_test_data(self):
        import random

        # Define possible file types and paths for random generation
        file_types = ['.jpg', '.png', '.gif', '.bmp', '.tiff']
        base_paths = ['/home/user/pictures', '/media/external', '/data/photos', '/projects/assets']
        folder_names = ['vacation', 'work', 'family', 'nature', 'screenshots', 'wallpapers']

        result = []
        for i in range(50):
            # Decide if this will be a directory or file
            is_dir = random.random() < 0.2  # 20% chance of being a directory

            # Create the filepath
            base_path = random.choice(base_paths)
            if is_dir:
                filepath = f"{base_path}/{random.choice(folder_names)}"
            else:
                filename = f"file{i+1}{random.choice(file_types)}"
                if random.random() < 0.5:  # 50% chance of being in a subfolder
                    filepath = f"{base_path}/{random.choice(folder_names)}/{filename}"
                else:
                    filepath = f"{base_path}/{filename}"

            # Randomize the other values
            active = random.random() < 0.8  # 80% chance of being active
            ephemeral = random.random() < 0.3  # 30% chance of being ephemeral

            # Generate usage counts
            times_used = 0 if is_dir else random.randint(0, 20)
            total_times_used = times_used
            if times_used > 0 and random.random() < 0.7:  # 70% chance of having more total uses than current uses
                total_times_used += random.randint(1, 15)

            # Add to result
            result.append({
                'filepath': filepath,
                'is_directory': is_dir,
                'active': active,
                'ephemeral': ephemeral,
                'times_used': times_used,
                'total_times_used': total_times_used
            })

        return result

    def on_show_ephemeral_images(self, _event):
        self.populate_grid()

    def on_checkbox_change(self, event, filepath, checkbox_type):
        value = event.GetEventObject().GetValue()
        if checkbox_type == "is_directory":
            self.update_is_directory(filepath, value)
        elif checkbox_type == "active":
            self.update_active_status(filepath, value)
        elif checkbox_type == "ephemeral":
            self.update_ephemeral_status(filepath, value)

    def update_is_directory(self, filepath: str, value: bool):
        print(f"[DB STUB] Updating is_directory to {value} for {filepath}")

    def update_active_status(self, filepath: str, value: bool):
        print(f"[DB STUB] Updating active status to {value} for {filepath}")

    def update_ephemeral_status(self, filepath: str, value: bool):
        print(f"[DB STUB] Updating ephemeral status to {value} for {filepath}")

    def on_clear_cache(self, event, filepath):
        print(f"[DB STUB] Clearing cache for: {filepath}")
        wx.MessageBox(f"Clearing cache for: {filepath}", "Clear Cache")


if __name__ == '__main__':
    app = FileViewerApp()
    app.MainLoop()
from typing import Iterator

import wx
import wx.grid as gridlib

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
        self.show_ephemeral_cb = wx.CheckBox(self.panel, label="Show Ephemeral Files?")
        self.show_ephemeral_cb.SetValue(False)
        self.show_ephemeral_cb.Bind(wx.EVT_CHECKBOX, self.on_show_ephemeral_images)
        controls_sizer.Add(self.add_files_btn, 0, wx.ALL, 5)
        controls_sizer.Add(self.add_folder_btn, 0, wx.ALL, 5)
        controls_sizer.AddStretchSpacer(1)
        controls_sizer.Add(self.show_ephemeral_cb, 0, wx.ALL | wx.ALIGN_CENTER_VERTICAL, 5)

        # --- Add search bar to the right of the checkbox ---
        self.search_ctrl = wx.SearchCtrl(self.panel, style=wx.TE_PROCESS_ENTER)
        self.search_ctrl.ShowSearchButton(True)
        self.search_ctrl.ShowCancelButton(True)
        controls_sizer.Add(self.search_ctrl, 0, wx.ALL | wx.ALIGN_CENTER_VERTICAL, 5)

        # --- Bind search control for delayed search ---
        self.search_timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self.on_search_timer, self.search_timer)
        self.search_ctrl.Bind(wx.EVT_TEXT, self.on_search_text)
        self.search_ctrl.Bind(wx.EVT_TEXT_ENTER, self.on_search_enter)
        # --- End search bar addition ---

        self.main_sizer.Add(controls_sizer, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, 5)

        # --- Replace grid_sizer/grid_panel with wx.Grid ---
        self.headers = [
            "Filepath", "Active", "Is Directory", "Ephemeral", "Times Used", "Total Times Used", "Clear Cache"
        ]
        self.num_columns = len(self.headers)

        self.grid_panel = wx.ScrolledWindow(self.panel)
        self.grid_panel.SetScrollRate(20, 20)
        self.grid = gridlib.Grid(self.grid_panel)
        self.grid.CreateGrid(0, self.num_columns)
        for i, header in enumerate(self.headers):
            self.grid.SetColLabelValue(i, header)
        self.grid.EnableEditing(False)
        self.grid.AutoSizeColumns()
        grid_sizer = wx.BoxSizer(wx.VERTICAL)
        grid_sizer.Add(self.grid, 1, wx.EXPAND)
        self.grid_panel.SetSizer(grid_sizer)
        self.main_sizer.Add(self.grid_panel, 1, wx.EXPAND | wx.ALL, 5)

        self.panel.SetSizer(self.main_sizer)

        self.populate_grid()

        self.Layout()
        self.Fit()

    def populate_grid(self):
        with Db(self.parent.file_list) as db:
            data = db.get_rows(
                file_path_match=self.search_ctrl.GetValue(),
                include_ephemeral_images=self.show_ephemeral_cb.GetValue(),
            )
            self.fill_grid(data)

    def fill_grid(self, data: Iterator[dict]):
        # --- Clear grid ---
        self.grid.BeginBatch()
        self.grid.ClearGrid()
        current_rows = self.grid.GetNumberRows()
        if current_rows > 0:
            self.grid.DeleteRows(0, current_rows)
        # --- Add data rows ---
        for row_idx, item in enumerate(data):
            self.grid.AppendRows(1)
            col_idx = 0
            self.grid.SetCellValue(row_idx, col_idx, str(item['filepath']))
            col_idx += 1
            self.grid.SetCellValue(row_idx, col_idx, "Yes" if item['active'] else "No")
            col_idx += 1
            self.grid.SetCellValue(row_idx, col_idx, "Yes" if item['is_directory'] else "No")
            col_idx += 1
            self.grid.SetCellValue(row_idx, col_idx, "Yes" if item['ephemeral'] else "No")
            col_idx += 1
            self.grid.SetCellValue(row_idx, col_idx, str(item['times_used']))
            col_idx += 1
            self.grid.SetCellValue(row_idx, col_idx, str(item['total_times_used']))
            col_idx += 1
            self.grid.SetCellValue(row_idx, col_idx, "Clear")
            # Optionally: set cell as read-only or style as needed
            # self.grid.SetReadOnly(row_idx, col_idx)
            if row_idx >= 50:
                break
        self.grid.AutoSizeColumns()
        self.grid.EndBatch()

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
            if times_used > 0 and random.random() < 0.7: # 70% chance of having more total uses than current uses
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

    def on_search_text(self, event):
        # Restart the timer every time text changes
        if self.search_timer.IsRunning():
            self.search_timer.Stop()
        self.search_timer.Start(1000, oneShot=True)
        event.Skip()

    def on_search_timer(self, _event):
        self.populate_grid()

    def on_search_enter(self, event):
        # Cancel timer and search immediately
        if self.search_timer.IsRunning():
            self.search_timer.Stop()
        self.populate_grid()
        event.Skip()


if __name__ == '__main__':
    app = FileViewerApp()
    app.MainLoop()
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

        self.current_page = 1
        self.total_pages = 1
        self.sort_column = "Filepath"  # Default sort by filepath
        self.sort_ascending = True

        super().__init__(None, title=title)

        # self.Bind(wx.EVT_SIZE, self.on_window_resize)

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
            "Filepath", "Active", "Is Directory", "Incl. Subdirs", "Ephemeral", "Times Used", "Total Times Used"
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
        self.grid.Bind(gridlib.EVT_GRID_LABEL_LEFT_CLICK, self.on_col_header_click)
        self.grid.Bind(gridlib.EVT_GRID_CELL_LEFT_DCLICK, self.on_grid_cell_dclick)

        self.grid.SetColSize(0, 300)  # Set a fixed initial width
        self.grid.SetColMinimalWidth(0, 100)

        # --- Set tooltip for the Active column header ---
        self.grid.GetGridColLabelWindow().Bind(
            wx.EVT_MOTION, self.on_grid_col_label_motion
        )

        grid_sizer = wx.BoxSizer(wx.VERTICAL)
        grid_sizer.Add(self.grid, 1, wx.EXPAND)
        self.grid_panel.SetSizer(grid_sizer)
        self.main_sizer.Add(self.grid_panel, 1, wx.EXPAND | wx.ALL, 5)

        self.panel.SetSizer(self.main_sizer)

        # --- Pagination controls below the grid ---
        self.pagination_sizer = wx.BoxSizer(wx.HORIZONTAL)

        # Page size dropdown (left-aligned)
        self.pagination_sizer.Add(wx.StaticText(self.panel, label="Page size:"), 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 5)
        self.page_size_choices = ["25", "50", "100", "200", "500", "1000"]
        self.page_size_choice = wx.Choice(self.panel, choices=self.page_size_choices)
        self.page_size_choice.SetSelection(0)  # Default to 25
        self.pagination_sizer.Add(self.page_size_choice, 0, wx.LEFT | wx.RIGHT | wx.ALIGN_CENTER_VERTICAL, 5)
        self.page_size_choice.Bind(wx.EVT_CHOICE, self.on_pagination_change)

        # --- Center the page selector and buttons ---
        self.pagination_sizer.AddStretchSpacer(1)

        self.center_sizer = wx.BoxSizer(wx.HORIZONTAL)

        self.first_btn = wx.Button(self.panel, label="◀◀", size=(48, -1))
        self.prev_btn = wx.Button(self.panel, label="◀", size=(32, -1))
        self.center_sizer.Add(self.first_btn, 0, wx.LEFT | wx.RIGHT, 2)
        self.center_sizer.Add(self.prev_btn, 0, wx.LEFT | wx.RIGHT, 2)
        self.first_btn.Bind(wx.EVT_BUTTON, self.on_first_page)
        self.prev_btn.Bind(wx.EVT_BUTTON, self.on_prev_page)

        self.center_sizer.Add(wx.StaticText(self.panel, label="Page:"), 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 5)
        self.page_counter = wx.TextCtrl(self.panel, value="1", size=(40, -1), style=wx.TE_PROCESS_ENTER)
        self.center_sizer.Add(self.page_counter, 0, wx.LEFT | wx.RIGHT | wx.ALIGN_CENTER_VERTICAL, 2)
        self.page_counter.Bind(wx.EVT_TEXT_ENTER, self.on_page_counter_enter)
        self.page_counter.Bind(wx.EVT_KILL_FOCUS, self.on_page_counter_enter)

        # Move "of #" label next to the page counter
        self.total_pages_label = wx.StaticText(self.panel, label="of 1")
        self.center_sizer.Add(self.total_pages_label, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT | wx.RIGHT, 8)

        self.next_btn = wx.Button(self.panel, label="▶", size=(32, -1))
        self.last_btn = wx.Button(self.panel, label="▶▶", size=(48, -1))
        self.center_sizer.Add(self.next_btn, 0, wx.LEFT | wx.RIGHT, 2)
        self.center_sizer.Add(self.last_btn, 0, wx.LEFT | wx.RIGHT, 2)
        self.next_btn.Bind(wx.EVT_BUTTON, self.on_next_page)
        self.last_btn.Bind(wx.EVT_BUTTON, self.on_last_page)

        self.pagination_sizer.Add(self.center_sizer, 0, wx.ALIGN_CENTER_VERTICAL)
        self.pagination_sizer.AddStretchSpacer(1)

        self.main_sizer.Add(self.pagination_sizer, 0, wx.EXPAND | wx.TOP | wx.BOTTOM, 8)
        # --- End pagination controls ---

        self.populate_grid()

        # --- Ensure the window grows to fit the grid on first load ---
        self.panel.Layout()
        self.Layout()
        self.grid_panel.FitInside()
        # Use the grid's best size to set the frame size if it's larger than the current size
        best_grid_size = self.grid.GetBestSize()
        grid_width, grid_height = best_grid_size.GetWidth(), best_grid_size.GetHeight()
        extra_width = 26
        extra_height = 126
        target_width = grid_width + extra_width
        target_height = grid_height + extra_height
        self.SetSize(wx.Size(target_width, target_height))
        self.Centre()
        # --- END ---

    def on_col_header_click(self, event):
        # Only handle column header clicks, not row labels
        if event.GetRow() == -1 and event.GetCol() != -1:
            col = self.headers[event.GetCol()]
            if self.sort_column == col:
                self.sort_ascending = not self.sort_ascending
            else:
                self.sort_column = col
                self.sort_ascending = True
            self.populate_grid()
            # Prevent default highlight/selection
            return
        event.Skip()

    def populate_grid(self):
        # --- Pagination logic ---
        try:
            page_size = int(self.page_size_choice.GetStringSelection())
        except Exception:
            page_size = 25
        try:
            page = int(self.page_counter.GetValue())
        except Exception:
            page = 1
        if page < 1:
            page = 1
        self.current_page = page
        self.page_size = page_size

        with Db(self.parent.file_list) as db:
            # Get total count for pagination
            total_count = db.get_row_count(
                file_path_match=self.search_ctrl.GetValue(),
                include_ephemeral_images=self.show_ephemeral_cb.GetValue(),
            )
            self.total_pages = max(1, (total_count + page_size - 1) // page_size)
            # Clamp current page
            if self.current_page > self.total_pages:
                self.current_page = self.total_pages
            self.page_counter.ChangeValue(str(self.current_page))
            self.total_pages_label.SetLabel(f"of {self.total_pages}")

            # Get paged data
            data = db.get_rows(
                file_path_match=self.search_ctrl.GetValue(),
                include_ephemeral_images=self.show_ephemeral_cb.GetValue(),
                sort_key=self.sort_column,
                sort_asc=self.sort_ascending,
                offset=(self.current_page - 1) * page_size,
                limit=page_size,
            )
            self.fill_grid(data)

        # Enable/disable navigation buttons
        self.first_btn.Enable(self.current_page > 1)
        self.prev_btn.Enable(self.current_page > 1)
        self.next_btn.Enable(self.current_page < self.total_pages)
        self.last_btn.Enable(self.current_page < self.total_pages)

        # Relayout the page counter sizers to ensure proper layout after changes
        self.center_sizer.Layout()
        self.pagination_sizer.Layout()

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
            self.grid.SetCellValue(row_idx, 0, str(item['filepath']))
            self.grid.SetCellValue(row_idx, 1, "Yes" if item['active'] else "No")
            self.grid.SetCellValue(row_idx, 2, "Yes" if item['is_directory'] else "No")
            if item['is_directory']:
                self.grid.SetCellValue(row_idx, 3, "Yes" if item['include_subdirectories'] else "No")
            else:
                self.grid.SetCellValue(row_idx, 4, "Yes" if item['ephemeral'] else "No")
                self.grid.SetCellValue(row_idx, 5, str(item['times_used']))
                self.grid.SetCellValue(row_idx, 6, str(item['total_times_used']))

        # Fill to page size to give the window something to size to.
        self.grid.AppendRows(self.page_size - self.grid.GetNumberRows())

        # Only autosize columns other than Filepath
        for i in range(1, self.num_columns):
            self.grid.AutoSizeColumn(i)
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

    def update_active_status(self, filepath: str, active: bool):
        with Db(self.parent.file_list) as db:
            db.set_active_flag(filepath, active)

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

    def on_pagination_change(self, event):
        self.current_page = 1
        self.page_counter.ChangeValue("1")
        self.populate_grid()

    def on_first_page(self, event):
        if self.current_page != 1:
            self.current_page = 1
            self.page_counter.ChangeValue("1")
            self.populate_grid()

    def on_prev_page(self, event):
        if self.current_page > 1:
            self.current_page -= 1
            self.page_counter.ChangeValue(str(self.current_page))
            self.populate_grid()

    def on_next_page(self, event):
        if self.current_page < self.total_pages:
            self.current_page += 1
            self.page_counter.ChangeValue(str(self.current_page))
            self.populate_grid()

    def on_last_page(self, event):
        if self.current_page != self.total_pages:
            self.current_page = self.total_pages
            self.page_counter.ChangeValue(str(self.current_page))
            self.populate_grid()

    def on_page_counter_enter(self, event):
        try:
            page = int(self.page_counter.GetValue())
        except Exception:
            page = 1
        if page < 1:
            page = 1
        elif page > self.total_pages:
            page = self.total_pages
        self.current_page = page
        self.page_counter.ChangeValue(str(self.current_page))
        self.populate_grid()
        event.Skip()

    def on_grid_cell_dclick(self, event):
        row = event.GetRow()
        col = event.GetCol()
        # "Active" column is index 1
        if col == 1 and row < self.grid.GetNumberRows():
            current_value = self.grid.GetCellValue(row, col)
            new_value = "No" if current_value == "Yes" else "Yes"
            self.grid.SetCellValue(row, col, new_value)
            # Optionally update the database or backend here
            # You may want to get the filepath from column 0
            filepath = self.grid.GetCellValue(row, 0)
            self.update_active_status(filepath, new_value == "Yes")
        event.Skip()

    def on_grid_col_label_motion(self, event):
        # Show tooltip and change cursor only when hovering over the Active column header (index 1)
        label_window = self.grid.GetGridColLabelWindow()
        x, y = event.GetPosition()
        col = self.grid.XToCol(x)
        if col == 1:  # Active
            msg = "Double-click an Active cell to toggle its state"
            cursor = wx.Cursor(wx.CURSOR_QUESTION_ARROW)
        else:
            msg = ""
            cursor = wx.Cursor(wx.CURSOR_ARROW)
        if label_window.GetToolTipText() != msg:
            label_window.SetToolTip(msg)
        label_window.SetCursor(cursor)
        event.Skip()

    def on_window_resize(self, event):
        size = self.GetSize()
        print(f"Window resized: {size.GetWidth()}x{size.GetHeight()}")
        event.Skip()


if __name__ == '__main__':
    app = FileViewerApp()
    app.MainLoop()
import json
import logging
import os
from typing import Iterator

import wx
import wx.grid as gridlib

import utils
from db import Db
from utils import refresh_ephemeral_images

logger = logging.getLogger(__name__)


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
        add_files_button = wx.Button(self.panel, label="Add Files")
        add_files_button.Bind(wx.EVT_BUTTON, self.add_files_to_list)
        add_folder_button = wx.Button(self.panel, label="Add Folder")
        add_folder_button.Bind(wx.EVT_BUTTON, self.add_folder_to_list)
        add_eagle_folder_button = wx.Button(self.panel, label="Add Eagle Folder")
        add_eagle_folder_button.Bind(wx.EVT_BUTTON, self.add_eagle_folder_to_list)
        delete_selected_button = wx.Button(self.panel, label="Delete Selected")
        delete_selected_button.Bind(wx.EVT_BUTTON, self.on_delete_selected)
        self.show_ephemeral_cb = wx.CheckBox(self.panel, label="Show Ephemeral Files?")
        self.show_ephemeral_cb.SetValue(False)
        self.show_ephemeral_cb.Bind(wx.EVT_CHECKBOX, self.on_show_ephemeral_images)
        controls_sizer.Add(add_files_button, 0, wx.ALL, 5)
        controls_sizer.Add(add_folder_button, 0, wx.ALL, 5)
        controls_sizer.Add(add_eagle_folder_button, 0, wx.ALL, 5)
        controls_sizer.Add(delete_selected_button, 0, wx.ALL | wx.ALIGN_CENTER_VERTICAL, 5)
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

        self.first_btn = wx.Button(self.panel, label="◀◀", size=wx.Size(48, -1))
        self.prev_btn = wx.Button(self.panel, label="◀", size=wx.Size(32, -1))
        self.center_sizer.Add(self.first_btn, 0, wx.LEFT | wx.RIGHT, 2)
        self.center_sizer.Add(self.prev_btn, 0, wx.LEFT | wx.RIGHT, 2)
        self.first_btn.Bind(wx.EVT_BUTTON, self.on_first_page)
        self.prev_btn.Bind(wx.EVT_BUTTON, self.on_prev_page)

        self.center_sizer.Add(wx.StaticText(self.panel, label="Page:"), 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 5)
        self.page_counter = wx.TextCtrl(self.panel, value="1", size=wx.Size(40, -1), style=wx.TE_PROCESS_ENTER)
        self.center_sizer.Add(self.page_counter, 0, wx.LEFT | wx.RIGHT | wx.ALIGN_CENTER_VERTICAL, 2)
        self.page_counter.Bind(wx.EVT_TEXT_ENTER, self.on_page_counter_enter)
        self.page_counter.Bind(wx.EVT_KILL_FOCUS, self.on_page_counter_enter)

        # Move "of #" label next to the page counter
        self.total_pages_label = wx.StaticText(self.panel, label="of 1")
        self.center_sizer.Add(self.total_pages_label, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT | wx.RIGHT, 8)

        self.next_btn = wx.Button(self.panel, label="▶", size=wx.Size(32, -1))
        self.last_btn = wx.Button(self.panel, label="▶▶", size=wx.Size(48, -1))
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

    def add_files_to_list(self, _event):
        with wx.FileDialog(self, "Select Images", wildcard="Image Files|*.gif;*.jpg;*.jpeg;*.png|All Files|*.*",
                           style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST | wx.FD_MULTIPLE) as fileDialog:
            if fileDialog.ShowModal() == wx.ID_CANCEL:
                return
            file_paths = fileDialog.GetPaths()
        # If we're adding images to the file list for the first time, pick a random image after load
        with Db(self.parent.file_list) as db:
            advance_image_after_load = bool(not db.get_all_active_count())
            db.add_images(file_paths)
        if advance_image_after_load:
            self.parent.trigger_image_loop(None)
        self.populate_grid()

    def add_folder_to_list(self, _event):
        with wx.DirDialog(self, "Select Image Folder", style=wx.DD_DIR_MUST_EXIST) as dirDialog:
            if dirDialog.ShowModal() == wx.ID_CANCEL:
                return
            dir_path = dirDialog.GetPath()
        title, message = "Question", f"You selected the folder {dir_path}\nDo you want to include subfolders?"
        with wx.MessageDialog(self, message, title, style=wx.ICON_QUESTION | wx.YES_NO | wx.CANCEL) as messageDialog:
            answer = messageDialog.ShowModal()
            if answer == wx.ID_CANCEL:
                return
            include_subfolders = answer == wx.ID_YES
        dir_path = dir_path.replace("\\", "/")
        with Db(self.parent.file_list) as db:
            # If we're adding images to the file list for the first time, pick a random image after load
            advance_image_after_load = bool(not db.get_all_active_count())
            db.add_directory(dir_path, include_subfolders)
            file_paths = utils.get_file_list_in_folder(dir_path, include_subfolders)
            db.add_images(file_paths, ephemeral=True)
        self.parent.add_observer_schedule(dir_path, include_subfolders=include_subfolders)
        if advance_image_after_load:
            self.parent.trigger_image_loop(None)
        self.populate_grid()

    def add_eagle_folder_to_list(self, _event):
        with wx.DirDialog(self, "Select Eagle Library Folder", style=wx.DD_DIR_MUST_EXIST) as dirDialog:
            if dirDialog.ShowModal() == wx.ID_CANCEL:
                return
            dir_path = dirDialog.GetPath()
        if not os.path.isfile(os.path.join(dir_path, "metadata.json")) or \
                not os.path.isdir(os.path.join(dir_path, "images")):
            utils.error_dialog(
                self,
                "The selected folder is not a valid Eagle library folder. "
                "It must contain a metadata.json file and an images folder."
            )
            return
        # Get all images from metadata.json, falling recursively through child folders.
        with open(os.path.join(dir_path, "metadata.json"), "rb") as f:
            metadata = json.load(f)
        image_folders = {}

        def add_to_image_folder_dict(folder_list: list[dict]):
            for folder in folder_list:
                image_folders[folder["name"]] = folder["id"]
                if folder["children"]:
                    add_to_image_folder_dict(folder["children"])

        add_to_image_folder_dict(metadata["folders"])

        # Prompt the user to pick a folder name
        folder_names, folder_ids = zip(*image_folders.items())
        with wx.MultiChoiceDialog(self, "Pick Folders to add to Wallpaper List", "Folders:",
                                  choices=folder_names) as choice_dialog:
            if choice_dialog.ShowModal() == wx.ID_CANCEL:
                return
        folder_data = {folder_names[i]: folder_ids[i] for i in choice_dialog.GetSelections()}
        dir_path = dir_path.replace("\\", "/")

        with Db(self.parent.file_list) as db:
            # If we're adding images to the file list for the first time, pick a random image after load
            advance_image_after_load = bool(not db.get_all_active_count())
            # Add folder data to existing folder data, and return the combined data
            folder_data = db.add_eagle_folder(dir_path, folder_data)
            db.remove_ephemeral_images_in_folder(dir_path)
        folder_ids = list(folder_data.values())
        file_paths = utils.get_file_list_in_eagle_folder(dir_path, folder_ids)
        if file_paths:
            with Db(self.parent.file_list) as db:
                db.add_images(file_paths, ephemeral=True)
        self.parent.add_observer_schedule(dir_path, eagle_folder_ids=folder_ids)
        if file_paths and advance_image_after_load:
            self.parent.trigger_image_loop(None)
        self.populate_grid()

    def on_delete_selected(self, _event):
        # Get selected rows
        selected_rows = set()
        # logger.debug(self.grid.GetSelectedCells())
        # logger.debug(self.grid.GetSelectedRows())
        # logger.debug(self.grid.GetSelectedCols())
        # logger.debug(self.grid.GetSelectedBlocks())
        # logger.debug(self.grid.GetSelectedRowBlocks())
        # logger.debug(self.grid.GetSelectedColBlocks())
        for cell in self.grid.GetSelectedCells():
            selected_rows.add(cell[0])
        for row in self.grid.GetSelectedRows():
            selected_rows.add(row)
        for row in self.grid.GetSelectedRowBlocks():
            selected_rows.add(row)
        for block in self.grid.GetSelectedBlocks():
            for row in range(block.TopRow, block.BottomRow + 1):
                selected_rows.add(row)
        # If no cells are selected, use the cursor row if valid
        if not selected_rows:
            row = self.grid.GetGridCursorRow()
            if 0 <= row < self.grid.GetNumberRows():
                selected_rows.add(row)
        # Confirm deletion
        if not selected_rows:
            wx.MessageBox("No rows selected.", "Delete Selected", wx.OK | wx.ICON_INFORMATION)
            return
        msg = f"Are you sure you want to delete {len(selected_rows)} selected file(s) from the database?"
        if wx.MessageBox(msg, "Delete Selected", wx.YES_NO | wx.ICON_WARNING) != wx.YES:
            return
        # Delete from DB
        filepaths = []
        folders = []
        for row in selected_rows:
            filepath = self.grid.GetCellValue(row, 0)
            filepaths.append(filepath)
            if self.grid.GetCellValue(row, 2) == "Yes":  # is_directory
                folders.append(filepath)

        with Db(self.parent.file_list) as db:
            if filepaths:
                for filepath in filepaths:
                    logger.debug(f"Deleting {filepath}...")
                    db.delete_image(filepath)
            if folders:
                for folder in folders:
                    refresh_ephemeral_images(db, folder)
        self.populate_grid()

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
        except TypeError:
            page_size = 25
        try:
            page = int(self.page_counter.GetValue())
        except TypeError:
            page = 1
        if page < 1:
            page = 1
        self.current_page = page
        self.page_size = page_size

        with Db(self.parent.file_list) as db:
            # Get total count for pagination
            total_count = db.get_row_count(
                file_path_match=self.search_ctrl.GetValue(),
                is_hidden=False,
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
                is_hidden=False,
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
        # --- Save the currently selected cell, if any ---
        selected_row = self.grid.GetGridCursorRow()
        selected_col = self.grid.GetGridCursorCol()
        if not self.grid.IsCellEditControlEnabled() and (selected_row < 0 or selected_col < 0):
            selected_row, selected_col = None, None

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

        # --- Restore the previously selected cell, if possible ---
        if (
            selected_row is not None and selected_col is not None
            and selected_row < self.grid.GetNumberRows()
            and selected_col < self.grid.GetNumberCols()
        ):
            self.grid.SetGridCursor(selected_row, selected_col)

    def on_show_ephemeral_images(self, _event):
        self.populate_grid()

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
        if col == 1 and row < self.grid.GetNumberRows():
            # Active
            filepath = self.grid.GetCellValue(row, 0)
            active = self.grid.GetCellValue(row, 1) == "Yes"
            is_directory = self.grid.GetCellValue(row, 2) == "Yes"
            self.update_active_status(filepath, not active, is_directory)
            self.populate_grid()
        elif col == 3 and row < self.grid.GetNumberRows():
            # Include Subdirectories
            is_directory = self.grid.GetCellValue(row, 2) == "Yes"
            if is_directory:
                filepath = self.grid.GetCellValue(row, 0)
                include_subdirs = self.grid.GetCellValue(row, 3) == "Yes"
                self.update_include_subdirs(filepath, not include_subdirs)
                self.populate_grid()
        event.Skip()

    def update_active_status(self, path: str, active: bool, is_directory: bool):
        with Db(self.parent.file_list) as db:
            db.set_active_flag(path, active)
            if is_directory:
                utils.refresh_ephemeral_images(db, path)

    def update_include_subdirs(self, path: str, include_subdirs: bool):
        with Db(self.parent.file_list) as db:
            db.set_include_subdirectories_flag(path, include_subdirs)
            utils.refresh_ephemeral_images(db, path)

    def on_grid_col_label_motion(self, event):
        """Show tooltip and change cursor when hovering over certain columns"""
        label_window = self.grid.GetGridColLabelWindow()
        x, y = event.GetPosition()
        col = self.grid.XToCol(x)
        if col == 1:  # Active
            msg = ("Double-clicking a cell in this column will toggle whether that file\n"
                   "is included in the list of files to pick from. If you disable a folder,\n"
                   "all ephemeral images in that folder will be disabled.")
            cursor = wx.Cursor(wx.CURSOR_QUESTION_ARROW)
        elif col == 3:  # Incl. Subdirs
            msg = ("Double-clicking a cell in this column will toggle whether subfolders are\n"
                   "included when loading files inside that folder.")
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

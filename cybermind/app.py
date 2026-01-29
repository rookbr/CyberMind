"""Main CyberMind application."""

import sys
import os
from pathlib import Path
from typing import Optional

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("Gdk", "4.0")
from gi.repository import Gtk, Gdk, Gio, GLib, Adw

from cybermind import __version__, __app_id__
from cybermind.database import Database, MindMap, Node, get_data_dir
from cybermind.canvas import MindMapCanvas
from cybermind.widgets import (
    MapsSidebar, NotesPanel, SearchDialog, 
    ShortcutsDialog, SettingsDialog
)
from cybermind.export import MindMapExporter, get_export_dir


class CyberMindWindow(Adw.ApplicationWindow):
    """Main application window."""
    
    def __init__(self, app: Adw.Application, db: Database):
        super().__init__(application=app)
        self.db = db
        self.current_map: Optional[MindMap] = None
        self.exporter = MindMapExporter(db)
        
        # Window setup
        self.set_title("CyberMind")
        self.set_default_size(1400, 900)
        
        # Load CSS
        self._load_css()
        
        # Build UI
        self._build_ui()
        
        # Setup keyboard shortcuts
        self._setup_shortcuts()
        
        # Setup auto-save timer
        self._autosave_timeout_id: Optional[int] = None
        self._setup_autosave()
        
        # Load initial map or show welcome
        maps = self.db.get_all_maps()
        if maps:
            self._load_map(maps[0])
        else:
            self._show_welcome()
    
    def _load_css(self):
        """Load custom CSS theme."""
        css_provider = Gtk.CssProvider()
        
        # Get CSS file path
        css_path = Path(__file__).parent / "theme.css"
        
        if css_path.exists():
            css_provider.load_from_path(str(css_path))
            
            Gtk.StyleContext.add_provider_for_display(
                Gdk.Display.get_default(),
                css_provider,
                Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
            )
    
    def _build_ui(self):
        """Build the main UI layout."""
        # Main container
        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        
        # Header bar
        header = self._build_header()
        main_box.append(header)
        
        # Content area with panes
        self.main_paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        self.main_paned.set_vexpand(True)
        
        # Left sidebar
        self.sidebar = MapsSidebar(self.db)
        self.sidebar.on_map_selected = self._on_map_selected
        self.sidebar.on_new_map = self._on_new_map
        self.sidebar.on_map_delete = self._on_map_delete
        self.sidebar.on_map_rename = self._on_map_rename
        
        self.sidebar_revealer = Gtk.Revealer()
        self.sidebar_revealer.set_transition_type(Gtk.RevealerTransitionType.SLIDE_RIGHT)
        self.sidebar_revealer.set_reveal_child(True)
        self.sidebar_revealer.set_child(self.sidebar)
        
        self.main_paned.set_start_child(self.sidebar_revealer)
        self.main_paned.set_shrink_start_child(False)
        self.main_paned.set_resize_start_child(False)
        
        # Center + Right pane
        self.right_paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        
        # Canvas
        self.canvas = MindMapCanvas(self.db)
        self.canvas.on_node_selected = self._on_node_selected
        self.canvas.on_node_edited = self._on_node_edited
        self.canvas.on_structure_changed = self._on_structure_changed
        
        canvas_frame = Gtk.Frame()
        canvas_frame.set_child(self.canvas)
        canvas_frame.add_css_class("canvas-container")
        
        self.right_paned.set_start_child(canvas_frame)
        self.right_paned.set_shrink_start_child(False)
        
        # Notes panel
        self.notes_panel = NotesPanel(self.db)
        self.notes_panel.on_notes_changed = self._on_notes_changed
        
        self.notes_revealer = Gtk.Revealer()
        self.notes_revealer.set_transition_type(Gtk.RevealerTransitionType.SLIDE_LEFT)
        self.notes_revealer.set_reveal_child(False)
        self.notes_revealer.set_child(self.notes_panel)
        
        self.right_paned.set_end_child(self.notes_revealer)
        self.right_paned.set_shrink_end_child(False)
        self.right_paned.set_resize_end_child(False)
        
        self.main_paned.set_end_child(self.right_paned)
        
        # Wrap in toast overlay for in-app notifications
        self.toast_overlay = Adw.ToastOverlay()
        self.toast_overlay.set_child(self.main_paned)
        main_box.append(self.toast_overlay)

        self.set_content(main_box)
    
    def _build_header(self) -> Adw.HeaderBar:
        """Build the header bar."""
        header = Adw.HeaderBar()
        header.add_css_class("flat")
        
        # Menu button
        menu_btn = Gtk.MenuButton()
        menu_btn.set_icon_name("open-menu-symbolic")
        menu_btn.set_tooltip_text("Menu")
        
        # Build menu
        menu = Gio.Menu()
        
        file_section = Gio.Menu()
        file_section.append("New Map", "win.new-map")
        file_section.append("Duplicate Map", "win.duplicate-map")
        file_section.append("Delete Map", "win.delete-map")
        menu.append_section(None, file_section)
        
        export_section = Gio.Menu()
        export_menu = Gio.Menu()
        export_menu.append("Export as PNG...", "win.export-png")
        export_menu.append("Export as PDF...", "win.export-pdf")
        export_menu.append("Export as Markdown...", "win.export-md")
        export_section.append_submenu("Export", export_menu)
        menu.append_section(None, export_section)
        
        view_section = Gio.Menu()
        view_section.append("Toggle Sidebar", "win.toggle-sidebar")
        view_section.append("Toggle Notes Panel", "win.toggle-notes")
        view_section.append("Toggle Grid", "win.toggle-grid")
        view_section.append("Toggle Minimap", "win.toggle-minimap")
        view_section.append("Auto-balance Layout", "win.auto-balance")
        view_section.append("Zoom to Fit", "win.zoom-fit")
        view_section.append("Zoom to 100%", "win.zoom-100")
        menu.append_section(None, view_section)
        
        help_section = Gio.Menu()
        help_section.append("Keyboard Shortcuts", "win.show-shortcuts")
        help_section.append("Preferences", "win.show-preferences")
        help_section.append("About CyberMind", "win.show-about")
        menu.append_section(None, help_section)
        
        popover = Gtk.PopoverMenu()
        popover.set_menu_model(menu)
        menu_btn.set_popover(popover)
        
        header.pack_start(menu_btn)
        
        # Sidebar toggle
        sidebar_btn = Gtk.ToggleButton()
        sidebar_btn.set_icon_name("sidebar-show-symbolic")
        sidebar_btn.set_tooltip_text("Toggle Sidebar (Ctrl+B)")
        sidebar_btn.set_active(True)
        sidebar_btn.connect("toggled", self._on_sidebar_toggled)
        self.sidebar_btn = sidebar_btn
        header.pack_start(sidebar_btn)
        
        # Title (editable map name) - placed on left
        self.title_entry = Gtk.Entry()
        self.title_entry.set_text("CyberMind")
        self.title_entry.set_alignment(0.0)
        self.title_entry.set_max_width_chars(25)
        self.title_entry.set_hexpand(False)
        self.title_entry.add_css_class("flat")
        self.title_entry.add_css_class("title")
        self.title_entry.connect("activate", self._on_title_changed)
        
        # Use GTK4 focus controller for focus-out
        focus_ctrl = Gtk.EventControllerFocus()
        focus_ctrl.connect("leave", lambda c: self._on_title_changed(self.title_entry))
        self.title_entry.add_controller(focus_ctrl)
        
        header.pack_start(self.title_entry)
        
        # Stylized CyberMind logo text with neon effect
        logo_label = Gtk.Label(label="CyberMind")
        logo_label.add_css_class("cybermind-logo")
        logo_box = Gtk.Box()
        logo_box.set_halign(Gtk.Align.CENTER)
        logo_box.set_hexpand(True)
        logo_box.append(logo_label)
        header.set_title_widget(logo_box)
        
        # Search button
        search_btn = Gtk.Button()
        search_btn.set_icon_name("system-search-symbolic")
        search_btn.set_tooltip_text("Search (Ctrl+F)")
        search_btn.connect("clicked", lambda b: self._show_search(global_search=False))
        header.pack_end(search_btn)
        
        # Notes toggle
        notes_btn = Gtk.ToggleButton()
        notes_btn.set_icon_name("accessories-text-editor-symbolic")
        notes_btn.set_tooltip_text("Toggle Notes Panel (Ctrl+Shift+B)")
        notes_btn.connect("toggled", self._on_notes_toggled)
        self.notes_btn = notes_btn
        header.pack_end(notes_btn)

        # Auto-balance layout (one-shot, undoable)
        balance_btn = Gtk.Button()
        balance_btn.set_icon_name("view-refresh-symbolic")
        balance_btn.set_tooltip_text("Auto-balance layout (undo with Ctrl+Z)")
        balance_btn.add_css_class("flat")
        balance_btn.connect("clicked", lambda b: self._auto_balance_layout())
        header.pack_end(balance_btn)

        # Layout mode dropdown
        layout_model = Gtk.StringList.new(["Horizontal Tree", "Radial"])
        self.layout_dropdown = Gtk.DropDown(model=layout_model)
        self.layout_dropdown.set_tooltip_text("Layout mode")
        self.layout_dropdown.set_selected(0)
        self.layout_dropdown.connect("notify::selected", self._on_layout_changed)
        header.pack_end(self.layout_dropdown)

        return header
    
    def _setup_shortcuts(self):
        """Setup keyboard shortcuts."""
        # Create actions
        actions = [
            ("new-map", self._on_new_map, "<Control>n"),
            ("save", self._on_save, "<Control>s"),
            ("duplicate-map", self._on_duplicate_map, None),
            ("delete-map", self._on_delete_map, None),
            ("toggle-sidebar", self._toggle_sidebar, "<Control>b"),
            ("toggle-notes", self._toggle_notes, "<Control><Shift>b"),
            ("toggle-grid", self._toggle_grid, None),
            ("toggle-minimap", self._toggle_minimap, "<Control>m"),
            ("zoom-fit", self._zoom_fit, "<Control>0"),
            ("zoom-100", self._zoom_100, "<Control>1"),
            ("zoom-in", self._zoom_in, "<Control>plus"),
            ("zoom-out", self._zoom_out, "<Control>minus"),
            ("search", lambda: self._show_search(False), "<Control>f"),
            ("search-global", lambda: self._show_search(True), "<Control><Shift>f"),
            ("show-shortcuts", self._show_shortcuts, "<Control>slash"),
            ("show-preferences", self._show_preferences, "<Control>comma"),
            ("show-about", self._show_about, None),
            ("undo", self._undo, "<Control>z"),
            ("redo", self._redo, "<Control><Shift>z"),
            ("export-png", self._export_png, None),
            ("export-pdf", self._export_pdf, None),
            ("export-md", self._export_md, None),
            ("quit", lambda: self.close(), "<Control>q"),
            ("open-notes", self._open_notes_for_selected, "<Control>Return"),
            ("auto-balance", self._auto_balance_layout, None),
        ]
        
        for name, callback, accel in actions:
            action = Gio.SimpleAction.new(name, None)
            action.connect("activate", lambda a, p, cb=callback: cb())
            self.add_action(action)
            
            if accel:
                self.get_application().set_accels_for_action(f"win.{name}", [accel])
        
        # Additional accelerators
        self.get_application().set_accels_for_action("win.zoom-in", ["<Control>plus", "<Control>equal"])
        self.get_application().set_accels_for_action("win.redo", ["<Control>r", "<Control><Shift>z", "<Control>y"])
        self.get_application().set_accels_for_action("win.show-shortcuts", ["<Control>slash", "F1"])

    def _auto_balance_layout(self):
        """Auto-balance node layout as fixed positions (undoable)."""
        self.canvas.auto_balance_layout()

    def _on_layout_changed(self, dropdown, _param):
        """Handle layout mode dropdown change."""
        idx = dropdown.get_selected()
        mode = "horizontal" if idx == 0 else "radial"
        self.canvas.layout_mode = mode
        if self.current_map:
            self.current_map.settings.layout_mode = mode
            self.db.update_map(self.current_map)
        self.canvas._calculate_layout()
        self.canvas.queue_draw()
    
    def _setup_autosave(self):
        """Setup auto-save timer."""
        interval = self.db.get_setting("autosave_interval", 30)
        
        if self._autosave_timeout_id:
            GLib.source_remove(self._autosave_timeout_id)
            self._autosave_timeout_id = None
        
        if interval > 0:
            self._autosave_timeout_id = GLib.timeout_add_seconds(
                interval, self._do_autosave
            )
    
    def _do_autosave(self) -> bool:
        """Perform auto-save."""
        if self.current_map:
            self.notes_panel.save_if_pending()
            # Canvas auto-saves view state on changes
            # Database auto-saves on every change
        return True  # Continue timer
    
    def _load_map(self, mind_map: MindMap):
        """Load a mindmap."""
        self.current_map = mind_map
        self.canvas.load_map(mind_map)
        self.title_entry.set_text(mind_map.name)
        self.sidebar.select_map(mind_map.id)
        self.notes_panel.show_empty_state()

        # Sync layout dropdown to map settings
        layout_idx = 1 if mind_map.settings.layout_mode == "radial" else 0
        self.layout_dropdown.set_selected(layout_idx)
    
    def _show_welcome(self):
        """Show welcome state when no maps exist."""
        self.current_map = None
        self.title_entry.set_text("CyberMind")
        self.canvas.clear()
        self.notes_panel.show_empty_state()
    
    # ==================== Event Handlers ====================
    
    def _on_map_selected(self, mind_map: MindMap):
        """Handle map selection from sidebar."""
        if self.current_map and self.current_map.id == mind_map.id:
            return
        
        # Save pending notes
        self.notes_panel.save_if_pending()
        
        self._load_map(mind_map)
    
    def _on_new_map(self, *args):
        """Create a new map."""
        mind_map = self.db.create_map("Untitled Map")
        self.sidebar.refresh()
        self._load_map(mind_map)
        
        # Focus title for editing
        self.title_entry.grab_focus()
        self.title_entry.select_region(0, -1)
    
    def _on_duplicate_map(self):
        """Duplicate current map."""
        if not self.current_map:
            return
        
        new_map = self.db.duplicate_map(
            self.current_map.id,
            f"{self.current_map.name} (Copy)"
        )
        
        if new_map:
            self.sidebar.refresh()
            self._load_map(new_map)
    
    def _on_delete_map(self):
        """Delete current map with confirmation."""
        if not self.current_map:
            return
        
        dialog = Adw.MessageDialog(
            transient_for=self,
            heading="Delete Map?",
            body=f"Are you sure you want to delete \"{self.current_map.name}\"? This cannot be undone."
        )
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("delete", "Delete")
        dialog.set_response_appearance("delete", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_default_response("cancel")
        dialog.connect("response", self._on_delete_confirmed)
        dialog.present()
    
    def _on_delete_confirmed(self, dialog, response):
        """Handle delete confirmation."""
        if response == "delete" and self.current_map:
            map_id = self.current_map.id
            self.db.delete_map(map_id)
            self.sidebar.refresh()
            
            # Load another map or show welcome
            maps = self.db.get_all_maps()
            if maps:
                self._load_map(maps[0])
            else:
                self._show_welcome()
    
    def _on_save(self):
        """Manual save."""
        self.notes_panel.save_if_pending()
        if self.current_map:
            self.db.create_backup(self.current_map.id)
    
    def _on_title_changed(self, entry):
        """Handle map title change."""
        if not self.current_map:
            return
        
        new_name = entry.get_text().strip()
        if new_name and new_name != self.current_map.name:
            self.current_map.name = new_name
            self.db.update_map(self.current_map)
            self.sidebar.refresh()
            self.sidebar.select_map(self.current_map.id)
    
    def _on_map_delete(self, mind_map: MindMap):
        """Handle map delete from sidebar context menu."""
        dialog = Adw.MessageDialog(
            transient_for=self,
            heading="Delete Map?",
            body=f"Are you sure you want to delete \"{mind_map.name}\"? This cannot be undone."
        )
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("delete", "Delete")
        dialog.set_response_appearance("delete", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_default_response("cancel")
        dialog.connect("response", lambda d, r: self._confirm_map_delete(r, mind_map))
        dialog.present()
    
    def _confirm_map_delete(self, response: str, mind_map: MindMap):
        """Confirm and delete a map."""
        if response == "delete":
            self.db.delete_map(mind_map.id)
            self.sidebar.refresh()
            
            # If we deleted current map, load another
            if self.current_map and self.current_map.id == mind_map.id:
                maps = self.db.get_all_maps()
                if maps:
                    self._load_map(maps[0])
                else:
                    self._show_welcome()
    
    def _on_map_rename(self, mind_map: MindMap):
        """Handle map rename from sidebar context menu."""
        dialog = Adw.MessageDialog(
            transient_for=self,
            heading="Rename Map",
            body="Enter a new name for the map:"
        )
        
        entry = Gtk.Entry()
        entry.set_text(mind_map.name)
        entry.set_margin_start(16)
        entry.set_margin_end(16)
        dialog.set_extra_child(entry)
        
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("rename", "Rename")
        dialog.set_default_response("rename")
        dialog.connect("response", lambda d, r: self._confirm_map_rename(r, mind_map, entry.get_text()))
        dialog.present()
        entry.grab_focus()
    
    def _confirm_map_rename(self, response: str, mind_map: MindMap, new_name: str):
        """Confirm and rename a map."""
        if response == "rename" and new_name.strip():
            mind_map.name = new_name.strip()
            self.db.update_map(mind_map)
            self.sidebar.refresh()
            
            # Update title if current map
            if self.current_map and self.current_map.id == mind_map.id:
                self.title_entry.set_text(new_name.strip())
                self.current_map.name = new_name.strip()
    
    def _on_node_selected(self, node: Optional[Node]):
        """Handle node selection."""
        if node:
            self.notes_panel.show_notes_for_node(node)
        else:
            self.notes_panel.show_empty_state()
    
    def _on_node_edited(self, node: Node, text: str):
        """Handle node text edit."""
        pass  # Canvas handles this
    
    def _on_notes_changed(self, node: Node, content: str):
        """Handle notes change."""
        self.canvas.invalidate_note_cache()
        self.canvas.queue_draw()  # Update notes indicator
    
    def _on_structure_changed(self):
        """Handle mindmap structure change."""
        pass  # Could trigger backup
    
    def _on_sidebar_toggled(self, button):
        """Handle sidebar toggle button."""
        self.sidebar_revealer.set_reveal_child(button.get_active())
    
    def _on_notes_toggled(self, button):
        """Handle notes panel toggle button."""
        self.notes_revealer.set_reveal_child(button.get_active())
    
    # ==================== Actions ====================
    
    def _toggle_sidebar(self):
        """Toggle sidebar visibility."""
        revealed = self.sidebar_revealer.get_reveal_child()
        self.sidebar_revealer.set_reveal_child(not revealed)
        self.sidebar_btn.set_active(not revealed)
    
    def _toggle_notes(self):
        """Toggle notes panel visibility."""
        revealed = self.notes_revealer.get_reveal_child()
        self.notes_revealer.set_reveal_child(not revealed)
        self.notes_btn.set_active(not revealed)
    
    def _toggle_grid(self):
        """Toggle canvas grid."""
        self.canvas.toggle_grid()
    
    def _toggle_minimap(self):
        """Toggle minimap."""
        self.canvas.toggle_minimap()
    
    def _zoom_fit(self):
        """Zoom to fit all nodes."""
        self.canvas.zoom_to_fit()
    
    def _zoom_100(self):
        """Reset zoom to 100%."""
        self.canvas.zoom_to_100()
    
    def _zoom_in(self):
        """Zoom in."""
        self.canvas.zoom_in()
    
    def _zoom_out(self):
        """Zoom out."""
        self.canvas.zoom_out()
    
    def _undo(self):
        """Undo last action."""
        # Prefer canvas-level undo since it tracks map mutations.
        # If focus is in a text widget (notes/title), GTK would otherwise undo text.
        self.canvas.undo()
    
    def _redo(self):
        """Redo last undone action."""
        self.canvas.redo()
    
    def _open_notes_for_selected(self):
        """Open notes panel for selected node."""
        if self.canvas.selected_node:
            self.notes_revealer.set_reveal_child(True)
            self.notes_btn.set_active(True)
            self.notes_panel.text_view.grab_focus()
    
    def _show_search(self, global_search: bool = False):
        """Show search dialog."""
        map_id = None if global_search else (self.current_map.id if self.current_map else None)
        
        dialog = SearchDialog(self, self.db, map_id)
        dialog.on_result_selected = self._on_search_result_selected
        dialog.present()
        dialog.search_entry.grab_focus()
    
    def _on_search_result_selected(self, map_id: int, node_id: int):
        """Handle search result selection."""
        # Load map if different
        if not self.current_map or self.current_map.id != map_id:
            mind_map = self.db.get_map(map_id)
            if mind_map:
                self._load_map(mind_map)
        
        # Find and select node
        for rendered in self.canvas.rendered_nodes:
            if rendered.node.id == node_id:
                self.canvas.select_node(rendered)
                # Center on node
                self.canvas.center_view()
                break
    
    def _show_shortcuts(self):
        """Show keyboard shortcuts dialog."""
        dialog = ShortcutsDialog(self)
        dialog.present()
    
    def _show_preferences(self):
        """Show preferences dialog."""
        dialog = SettingsDialog(self, self.db)
        dialog.on_settings_changed = self._on_settings_changed
        dialog.present()

    def _on_settings_changed(self, key: str, value):
        """Handle real-time setting changes from preferences dialog."""
        if key == "show_grid":
            self.canvas.show_grid = bool(value)
            if self.current_map:
                self.current_map.settings.show_grid = bool(value)
                self.db.update_map(self.current_map)
            self.canvas.queue_draw()
        elif key == "show_minimap":
            self.canvas.show_minimap = bool(value)
            if self.current_map:
                self.current_map.settings.show_minimap = bool(value)
                self.db.update_map(self.current_map)
            self.canvas.queue_draw()
        elif key == "node_glow":
            self.canvas.queue_draw()
        elif key == "autosave_interval":
            self._setup_autosave()
    
    def _show_about(self):
        """Show about dialog."""
        about = Adw.AboutWindow(
            transient_for=self,
            application_name="CyberMind",
            application_icon="applications-graphics",
            developer_name="CyberMind Project",
            version=__version__,
            copyright="© 2024 CyberMind Project",
            license_type=Gtk.License.MIT_X11,
            comments="A hacker-aesthetic mindmap application for Linux",
            website="https://github.com/cybermind/cybermind"
        )
        about.present()
    
    # ==================== Export ====================
    
    def _export_png(self):
        """Export current map as PNG."""
        if not self.current_map:
            return
        
        dialog = Gtk.FileDialog()
        dialog.set_title("Export as PNG")
        dialog.set_initial_name(f"{self.current_map.name}.png")
        dialog.set_initial_folder(Gio.File.new_for_path(str(get_export_dir())))
        
        filter_png = Gtk.FileFilter()
        filter_png.set_name("PNG Images")
        filter_png.add_mime_type("image/png")
        
        filters = Gio.ListStore.new(Gtk.FileFilter)
        filters.append(filter_png)
        dialog.set_filters(filters)
        
        dialog.save(self, None, self._on_export_png_response)
    
    def _on_export_png_response(self, dialog, result):
        """Handle PNG export dialog response."""
        try:
            file = dialog.save_finish(result)
            if file and self.current_map:
                filepath = file.get_path()
                if not filepath:
                    self._show_toast("Export failed: selected location is not a local file")
                    return
                self.exporter.layout_mode = self.current_map.settings.layout_mode
                positions = self.canvas.get_node_positions()
                if self.exporter.export_png(self.current_map, filepath,
                                            canvas_positions=positions):
                    self._show_toast(f"Exported to {filepath}")
                else:
                    self._show_toast("Export failed")
        except GLib.Error:
            pass  # User cancelled

    def _export_pdf(self):
        """Export current map as PDF."""
        if not self.current_map:
            return
        
        dialog = Gtk.FileDialog()
        dialog.set_title("Export as PDF")
        dialog.set_initial_name(f"{self.current_map.name}.pdf")
        dialog.set_initial_folder(Gio.File.new_for_path(str(get_export_dir())))
        
        filter_pdf = Gtk.FileFilter()
        filter_pdf.set_name("PDF Documents")
        filter_pdf.add_mime_type("application/pdf")
        
        filters = Gio.ListStore.new(Gtk.FileFilter)
        filters.append(filter_pdf)
        dialog.set_filters(filters)
        
        dialog.save(self, None, self._on_export_pdf_response)
    
    def _on_export_pdf_response(self, dialog, result):
        """Handle PDF export dialog response."""
        try:
            file = dialog.save_finish(result)
            if file and self.current_map:
                filepath = file.get_path()
                if not filepath:
                    self._show_toast("Export failed: selected location is not a local file")
                    return
                self.exporter.layout_mode = self.current_map.settings.layout_mode
                positions = self.canvas.get_node_positions()
                if self.exporter.export_pdf(self.current_map, filepath,
                                            canvas_positions=positions):
                    self._show_toast(f"Exported to {filepath}")
                else:
                    self._show_toast("Export failed")
        except GLib.Error:
            pass
    
    def _export_md(self):
        """Export current map as Markdown."""
        if not self.current_map:
            return
        
        dialog = Gtk.FileDialog()
        dialog.set_title("Export as Markdown")
        dialog.set_initial_name(f"{self.current_map.name}.md")
        dialog.set_initial_folder(Gio.File.new_for_path(str(get_export_dir())))
        
        filter_md = Gtk.FileFilter()
        filter_md.set_name("Markdown Files")
        filter_md.add_pattern("*.md")
        
        filters = Gio.ListStore.new(Gtk.FileFilter)
        filters.append(filter_md)
        dialog.set_filters(filters)
        
        dialog.save(self, None, self._on_export_md_response)
    
    def _on_export_md_response(self, dialog, result):
        """Handle Markdown export dialog response."""
        try:
            file = dialog.save_finish(result)
            if file and self.current_map:
                filepath = file.get_path()
                if not filepath:
                    self._show_toast("Export failed: selected location is not a local file")
                    return
                self.exporter.layout_mode = self.current_map.settings.layout_mode
                if self.exporter.export_markdown(self.current_map, filepath):
                    self._show_toast(f"Exported to {filepath}")
                else:
                    self._show_toast("Export failed")
        except GLib.Error:
            pass
    
    def _show_toast(self, message: str):
        """Show a toast notification."""
        toast = Adw.Toast(title=message)
        toast.set_timeout(3)
        self.toast_overlay.add_toast(toast)


class CyberMindApp(Adw.Application):
    """Main application class."""
    
    def __init__(self):
        super().__init__(
            application_id=__app_id__,
            flags=Gio.ApplicationFlags.DEFAULT_FLAGS
        )
        self.db: Optional[Database] = None
        self.window: Optional[CyberMindWindow] = None
    
    def do_startup(self):
        """Initialize application."""
        Adw.Application.do_startup(self)
        
        # Initialize database
        self.db = Database()
        
        # Set dark theme
        style_manager = Adw.StyleManager.get_default()
        style_manager.set_color_scheme(Adw.ColorScheme.FORCE_DARK)
    
    def do_activate(self):
        """Activate application."""
        if not self.window:
            self.window = CyberMindWindow(self, self.db)
        
        self.window.present()
    
    def do_shutdown(self):
        """Shutdown application."""
        if self.db:
            self.db.close()
        
        Adw.Application.do_shutdown(self)


def main() -> int:
    """Application entry point."""
    app = CyberMindApp()
    return app.run(sys.argv)


if __name__ == "__main__":
    sys.exit(main())

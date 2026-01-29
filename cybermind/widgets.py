"""Custom widgets for CyberMind application."""

from typing import Optional, Callable, List
import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Gdk, GLib, Gio, Adw, Pango

from cybermind.database import Database, MindMap, Node, Note


class MapListRow(Gtk.Box):
    """A row in the maps list sidebar."""
    
    def __init__(self, mind_map: MindMap):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.mind_map = mind_map
        
        self.set_margin_start(12)
        self.set_margin_end(12)
        self.set_margin_top(8)
        self.set_margin_bottom(8)
        
        # Map name
        self.name_label = Gtk.Label(label=mind_map.name)
        self.name_label.set_halign(Gtk.Align.START)
        self.name_label.set_ellipsize(Pango.EllipsizeMode.END)
        self.name_label.add_css_class("map-name")
        self.append(self.name_label)
        
        # Modified date
        date_str = mind_map.modified_at[:10] if mind_map.modified_at else ""
        self.date_label = Gtk.Label(label=f"Modified: {date_str}")
        self.date_label.set_halign(Gtk.Align.START)
        self.date_label.add_css_class("map-date")
        self.append(self.date_label)
    
    def update(self, mind_map: MindMap):
        """Update the row with new map data."""
        self.mind_map = mind_map
        self.name_label.set_label(mind_map.name)
        date_str = mind_map.modified_at[:10] if mind_map.modified_at else ""
        self.date_label.set_label(f"Modified: {date_str}")


class MapsSidebar(Gtk.Box):
    """Left sidebar showing list of mindmaps."""
    
    def __init__(self, db: Database):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.db = db
        
        self.add_css_class("sidebar")
        self.set_size_request(280, -1)
        
        # Callbacks
        self.on_map_selected: Optional[Callable[[MindMap], None]] = None
        self.on_new_map: Optional[Callable[[], None]] = None
        self.on_map_delete: Optional[Callable[[MindMap], None]] = None
        self.on_map_rename: Optional[Callable[[MindMap], None]] = None
        
        # Right-click target
        self._right_click_map: Optional[MindMap] = None
        self._context_popover: Optional[Gtk.PopoverMenu] = None
        
        # Header
        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        header.add_css_class("sidebar-header")
        header.set_margin_start(16)
        header.set_margin_end(8)
        header.set_margin_top(12)
        header.set_margin_bottom(12)
        
        title = Gtk.Label(label="MAPS")
        title.set_hexpand(True)
        title.set_halign(Gtk.Align.START)
        title.add_css_class("sidebar-title")
        header.append(title)
        
        # New map button
        new_btn = Gtk.Button()
        new_btn.set_icon_name("list-add-symbolic")
        new_btn.set_tooltip_text("New Map (Ctrl+N)")
        new_btn.add_css_class("flat")
        new_btn.connect("clicked", self._on_new_clicked)
        header.append(new_btn)
        
        self.append(header)
        
        # Search entry
        search_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        search_box.set_margin_start(12)
        search_box.set_margin_end(12)
        search_box.set_margin_bottom(8)
        
        self.search_entry = Gtk.SearchEntry()
        self.search_entry.set_placeholder_text("Filter maps...")
        self.search_entry.set_hexpand(True)
        self.search_entry.connect("search-changed", self._on_search_changed)
        search_box.append(self.search_entry)
        
        self.append(search_box)
        
        # Separator
        self.append(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))
        
        # Maps list
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_vexpand(True)
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        
        self.listbox = Gtk.ListBox()
        self.listbox.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.listbox.add_css_class("map-list")
        self.listbox.connect("row-selected", self._on_row_selected)
        self.listbox.set_filter_func(self._filter_func)
        
        # Right-click for context menu
        right_click = Gtk.GestureClick()
        right_click.set_button(3)
        right_click.connect("pressed", self._on_right_click)
        self.listbox.add_controller(right_click)
        
        scrolled.set_child(self.listbox)
        self.append(scrolled)
        
        # Store rows for filtering
        self.rows: List[Gtk.ListBoxRow] = []
        self.filter_text = ""
        
        # Load maps
        self.refresh()
    
    def refresh(self):
        """Refresh the maps list."""
        # Clear existing
        while True:
            row = self.listbox.get_row_at_index(0)
            if row is None:
                break
            self.listbox.remove(row)
        self.rows.clear()
        
        # Load maps
        maps = self.db.get_all_maps()
        
        for mind_map in maps:
            row = Gtk.ListBoxRow()
            row.set_child(MapListRow(mind_map))
            row.mind_map = mind_map
            self.listbox.append(row)
            self.rows.append(row)
        
        # Show empty state if no maps
        if not maps:
            self._show_empty_state()
    
    def _show_empty_state(self):
        """Show empty state message."""
        empty_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        empty_box.set_valign(Gtk.Align.CENTER)
        empty_box.set_margin_top(40)
        empty_box.set_margin_bottom(40)
        empty_box.add_css_class("empty-state")
        
        label = Gtk.Label(label="No maps yet")
        label.add_css_class("dim-label")
        empty_box.append(label)
        
        hint = Gtk.Label(label="Press Ctrl+N to create one")
        hint.add_css_class("dim-label")
        hint.set_opacity(0.6)
        empty_box.append(hint)
        
        row = Gtk.ListBoxRow()
        row.set_child(empty_box)
        row.set_selectable(False)
        row.set_activatable(False)
        self.listbox.append(row)
    
    def _filter_func(self, row: Gtk.ListBoxRow) -> bool:
        """Filter function for search."""
        if not self.filter_text:
            return True
        
        if not hasattr(row, 'mind_map'):
            return True
        
        return self.filter_text.lower() in row.mind_map.name.lower()
    
    def _on_search_changed(self, entry):
        """Handle search text change."""
        self.filter_text = entry.get_text()
        self.listbox.invalidate_filter()
    
    def _on_row_selected(self, listbox, row):
        """Handle map selection."""
        if row and hasattr(row, 'mind_map') and self.on_map_selected:
            self.on_map_selected(row.mind_map)
    
    def _on_new_clicked(self, button):
        """Handle new map button click."""
        if self.on_new_map:
            self.on_new_map()
    
    def _on_right_click(self, gesture, n_press, x, y):
        """Handle right-click for context menu."""
        # Find which row was clicked
        row = self.listbox.get_row_at_y(int(y))
        if not row or not hasattr(row, 'mind_map'):
            return
        
        self._right_click_map = row.mind_map
        self.listbox.select_row(row)
        
        # Create menu
        menu = Gio.Menu()
        menu.append("Rename", "sidebar.rename-map")
        menu.append("Delete", "sidebar.delete-map")
        
        # Create actions
        action_group = Gio.SimpleActionGroup()
        
        rename_action = Gio.SimpleAction.new("rename-map", None)
        rename_action.connect("activate", self._on_rename_map)
        action_group.add_action(rename_action)
        
        delete_action = Gio.SimpleAction.new("delete-map", None)
        delete_action.connect("activate", self._on_delete_map)
        action_group.add_action(delete_action)
        
        self.insert_action_group("sidebar", action_group)
        
        # Clean up previous popover
        if self._context_popover is not None:
            self._context_popover.unparent()
            self._context_popover = None

        # Show popover
        popover = Gtk.PopoverMenu.new_from_model(menu)
        popover.set_parent(self.listbox)
        popover.set_has_arrow(True)
        popover.set_pointing_to(Gdk.Rectangle(int(x), int(y), 1, 1))

        # Defer unparent to idle so the action callback fires first
        def _on_popover_closed(p):
            def _do_unparent():
                if self._context_popover is p:
                    p.unparent()
                    self._context_popover = None
                return False
            GLib.idle_add(_do_unparent)
        popover.connect("closed", _on_popover_closed)

        self._context_popover = popover
        popover.popup()
    
    def _on_rename_map(self, action, param):
        """Handle rename map action."""
        if self._right_click_map and self.on_map_rename:
            self.on_map_rename(self._right_click_map)
    
    def _on_delete_map(self, action, param):
        """Handle delete map action."""
        if self._right_click_map and self.on_map_delete:
            self.on_map_delete(self._right_click_map)
    
    def select_map(self, map_id: int):
        """Select a map by ID."""
        for row in self.rows:
            if hasattr(row, 'mind_map') and row.mind_map.id == map_id:
                self.listbox.select_row(row)
                break


class NotesPanel(Gtk.Box):
    """Right sidebar for editing node notes."""
    
    def __init__(self, db: Database):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.db = db
        self.current_node: Optional[Node] = None
        
        self.add_css_class("notes-panel")
        self.set_size_request(350, -1)
        
        # Callbacks
        self.on_notes_changed: Optional[Callable[[Node, str], None]] = None
        
        # Header
        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        header.add_css_class("notes-panel-header")
        header.set_margin_start(16)
        header.set_margin_end(16)
        header.set_margin_top(12)
        header.set_margin_bottom(12)
        
        title = Gtk.Label(label="NOTES")
        title.set_hexpand(True)
        title.set_halign(Gtk.Align.START)
        title.add_css_class("sidebar-title")
        header.append(title)
        
        self.append(header)
        
        # Node info
        self.node_info = Gtk.Label(label="")
        self.node_info.set_halign(Gtk.Align.START)
        self.node_info.set_margin_start(16)
        self.node_info.set_margin_bottom(8)
        self.node_info.set_ellipsize(Pango.EllipsizeMode.END)
        self.node_info.add_css_class("dim-label")
        self.append(self.node_info)
        
        self.append(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))
        
        # Text editor
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_vexpand(True)
        scrolled.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        
        self.text_view = Gtk.TextView()
        self.text_view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self.text_view.set_left_margin(16)
        self.text_view.set_right_margin(16)
        self.text_view.set_top_margin(16)
        self.text_view.set_bottom_margin(16)
        self.text_view.add_css_class("notes-editor")
        self.text_view.set_monospace(True)
        
        self.text_buffer = self.text_view.get_buffer()
        self.text_buffer.connect("changed", self._on_text_changed)
        
        scrolled.set_child(self.text_view)
        self.append(scrolled)
        
        # Save indicator / status
        self.status_bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        self.status_bar.set_margin_start(16)
        self.status_bar.set_margin_end(16)
        self.status_bar.set_margin_top(8)
        self.status_bar.set_margin_bottom(8)
        
        self.status_label = Gtk.Label(label="")
        self.status_label.set_halign(Gtk.Align.END)
        self.status_label.set_hexpand(True)
        self.status_label.add_css_class("dim-label")
        self.status_bar.append(self.status_label)
        
        self.append(self.status_bar)
        
        # Empty state (shown when no node selected)
        self.empty_state = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.empty_state.set_valign(Gtk.Align.CENTER)
        self.empty_state.set_vexpand(True)
        self.empty_state.add_css_class("empty-state")
        
        empty_label = Gtk.Label(label="No node selected")
        empty_label.add_css_class("dim-label")
        self.empty_state.append(empty_label)
        
        hint_label = Gtk.Label(label="Select a node to add notes")
        hint_label.add_css_class("dim-label")
        hint_label.set_opacity(0.6)
        self.empty_state.append(hint_label)
        
        # Auto-save timer
        self._save_timeout_id: Optional[int] = None
        self._pending_save = False
        
        # Initially show empty state
        self.show_empty_state()
    
    def show_empty_state(self):
        """Show the empty state (no node selected)."""
        self.current_node = None
        self.node_info.set_visible(False)
        self.text_view.set_visible(False)
        self.text_view.get_parent().set_visible(False)
        self.status_bar.set_visible(False)
        
        if self.empty_state.get_parent() is None:
            # Insert before status bar
            self.insert_child_after(self.empty_state, self.get_first_child().get_next_sibling().get_next_sibling())
        self.empty_state.set_visible(True)
    
    def show_notes_for_node(self, node: Node):
        """Show notes for a specific node."""
        # Cancel any pending save
        if self._save_timeout_id:
            GLib.source_remove(self._save_timeout_id)
            self._save_timeout_id = None
            if self._pending_save:
                self._do_save()
        
        self.current_node = node
        
        # Hide empty state
        self.empty_state.set_visible(False)
        
        # Show editor
        self.node_info.set_visible(True)
        self.node_info.set_label(f"Node: {node.text}")
        
        self.text_view.get_parent().set_visible(True)
        self.text_view.set_visible(True)
        self.status_bar.set_visible(True)
        
        # Load note content
        note = self.db.get_note(node.id)
        
        # Block handler while setting text
        self.text_buffer.handler_block_by_func(self._on_text_changed)
        self.text_buffer.set_text(note.content if note else "")
        self.text_buffer.handler_unblock_by_func(self._on_text_changed)
        
        self.status_label.set_label("")
        self._pending_save = False
    
    def _on_text_changed(self, buffer):
        """Handle text changes - schedule auto-save."""
        if not self.current_node:
            return
        
        self._pending_save = True
        self.status_label.set_label("Unsaved changes...")
        
        # Cancel existing timer
        if self._save_timeout_id:
            GLib.source_remove(self._save_timeout_id)
        
        # Schedule save in 1 second
        self._save_timeout_id = GLib.timeout_add(1000, self._do_save)
    
    def _do_save(self) -> bool:
        """Save the current notes."""
        self._save_timeout_id = None
        
        if not self.current_node or not self._pending_save:
            return False
        
        start = self.text_buffer.get_start_iter()
        end = self.text_buffer.get_end_iter()
        content = self.text_buffer.get_text(start, end, True)
        
        self.db.set_note(self.current_node.id, content)
        
        self._pending_save = False
        self.status_label.set_label("Saved")
        
        # Clear "Saved" message after 2 seconds
        GLib.timeout_add(2000, self._clear_status)
        
        if self.on_notes_changed:
            self.on_notes_changed(self.current_node, content)
        
        return False
    
    def _clear_status(self) -> bool:
        """Clear the status label."""
        if not self._pending_save:
            self.status_label.set_label("")
        return False
    
    def save_if_pending(self):
        """Force save if there are pending changes."""
        if self._pending_save:
            if self._save_timeout_id:
                GLib.source_remove(self._save_timeout_id)
                self._save_timeout_id = None
            self._do_save()


class SearchDialog(Gtk.Window):
    """Global search dialog."""
    
    def __init__(self, parent: Gtk.Window, db: Database, current_map_id: Optional[int] = None):
        super().__init__()
        self.db = db
        self.current_map_id = current_map_id
        
        self.set_transient_for(parent)
        self.set_modal(True)
        self.set_default_size(600, 400)
        self.set_title("Search")
        self.add_css_class("search-dialog")
        
        # Callbacks
        self.on_result_selected: Optional[Callable[[int, int], None]] = None  # map_id, node_id
        
        # Main container
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        
        # Search entry
        search_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        search_box.set_margin_start(16)
        search_box.set_margin_end(16)
        search_box.set_margin_top(16)
        search_box.set_margin_bottom(16)
        
        self.search_entry = Gtk.SearchEntry()
        self.search_entry.set_placeholder_text("Search nodes and notes...")
        self.search_entry.set_hexpand(True)
        self.search_entry.connect("search-changed", self._on_search_changed)
        self.search_entry.connect("activate", self._on_search_activate)
        search_box.append(self.search_entry)
        
        # Scope toggle
        self.scope_btn = Gtk.ToggleButton(label="All Maps")
        self.scope_btn.set_active(current_map_id is None)
        self.scope_btn.set_margin_start(8)
        self.scope_btn.connect("toggled", self._on_scope_changed)
        search_box.append(self.scope_btn)
        
        box.append(search_box)
        box.append(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))
        
        # Results list
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_vexpand(True)
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        
        self.results_list = Gtk.ListBox()
        self.results_list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.results_list.add_css_class("search-results")
        self.results_list.connect("row-activated", self._on_row_activated)
        
        scrolled.set_child(self.results_list)
        box.append(scrolled)
        
        # Status bar
        self.status_label = Gtk.Label(label="Type to search...")
        self.status_label.set_halign(Gtk.Align.START)
        self.status_label.set_margin_start(16)
        self.status_label.set_margin_end(16)
        self.status_label.set_margin_top(8)
        self.status_label.set_margin_bottom(8)
        self.status_label.add_css_class("dim-label")
        box.append(self.status_label)
        
        self.set_child(box)
        
        # Keyboard controller
        key_ctrl = Gtk.EventControllerKey()
        key_ctrl.connect("key-pressed", self._on_key_pressed)
        self.add_controller(key_ctrl)
        
        # Search timeout
        self._search_timeout_id: Optional[int] = None
    
    def _on_search_changed(self, entry):
        """Handle search text change."""
        # Cancel existing search
        if self._search_timeout_id:
            GLib.source_remove(self._search_timeout_id)
        
        # Schedule search
        self._search_timeout_id = GLib.timeout_add(300, self._do_search)
    
    def _on_search_activate(self, entry):
        """Handle Enter in search field."""
        row = self.results_list.get_selected_row()
        if row:
            self._on_row_activated(self.results_list, row)
    
    def _on_scope_changed(self, button):
        """Handle scope toggle."""
        if button.get_active():
            button.set_label("All Maps")
        else:
            button.set_label("Current Map")
        
        # Re-search
        if self._search_timeout_id:
            GLib.source_remove(self._search_timeout_id)
        self._search_timeout_id = GLib.timeout_add(100, self._do_search)
    
    def _do_search(self) -> bool:
        """Perform the search."""
        self._search_timeout_id = None
        
        query = self.search_entry.get_text().strip()
        
        # Clear results
        while True:
            row = self.results_list.get_row_at_index(0)
            if row is None:
                break
            self.results_list.remove(row)
        
        if not query or len(query) < 2:
            self.status_label.set_label("Type at least 2 characters...")
            return False
        
        # Determine scope
        map_id = None if self.scope_btn.get_active() else self.current_map_id
        
        # Search nodes and notes
        node_results = self.db.search_nodes(query, map_id)
        note_results = self.db.search_notes(query, map_id)
        
        all_results = node_results + note_results
        
        if not all_results:
            self.status_label.set_label("No results found")
            return False
        
        self.status_label.set_label(f"{len(all_results)} result(s) found")
        
        # Add results
        for result in all_results[:50]:  # Limit to 50 results
            row = self._create_result_row(result)
            self.results_list.append(row)
        
        # Select first result
        first = self.results_list.get_row_at_index(0)
        if first:
            self.results_list.select_row(first)
        
        return False
    
    def _create_result_row(self, result: dict) -> Gtk.ListBoxRow:
        """Create a row for a search result."""
        row = Gtk.ListBoxRow()
        row.result = result
        
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        box.set_margin_start(12)
        box.set_margin_end(12)
        box.set_margin_top(8)
        box.set_margin_bottom(8)
        
        # Type indicator and text
        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        
        if result["type"] == "node":
            type_label = Gtk.Label(label="NODE")
            text = result["text"]
        else:
            type_label = Gtk.Label(label="NOTE")
            text = result.get("node_text", "")
        
        type_label.add_css_class("priority-badge")
        type_label.add_css_class("priority-info")
        header.append(type_label)
        
        text_label = Gtk.Label(label=text)
        text_label.set_ellipsize(Pango.EllipsizeMode.END)
        text_label.set_hexpand(True)
        text_label.set_halign(Gtk.Align.START)
        header.append(text_label)
        
        box.append(header)
        
        # Map name
        map_label = Gtk.Label(label=f"in {result['map_name']}")
        map_label.set_halign(Gtk.Align.START)
        map_label.add_css_class("dim-label")
        box.append(map_label)
        
        # Note preview if it's a note result
        if result["type"] == "note":
            preview = result.get("content", "")[:100]
            preview_label = Gtk.Label(label=preview)
            preview_label.set_ellipsize(Pango.EllipsizeMode.END)
            preview_label.set_halign(Gtk.Align.START)
            preview_label.add_css_class("dim-label")
            preview_label.set_opacity(0.7)
            box.append(preview_label)
        
        row.set_child(box)
        return row
    
    def _on_row_activated(self, listbox, row):
        """Handle result selection."""
        if hasattr(row, 'result') and self.on_result_selected:
            result = row.result
            self.on_result_selected(result["map_id"], result["node_id"])
            self.close()
    
    def _on_key_pressed(self, controller, keyval, keycode, state):
        """Handle keyboard input."""
        if keyval == Gdk.KEY_Escape:
            self.close()
            return True
        
        elif keyval == Gdk.KEY_Down:
            row = self.results_list.get_selected_row()
            if row:
                idx = row.get_index()
                next_row = self.results_list.get_row_at_index(idx + 1)
                if next_row:
                    self.results_list.select_row(next_row)
            return True
        
        elif keyval == Gdk.KEY_Up:
            row = self.results_list.get_selected_row()
            if row:
                idx = row.get_index()
                if idx > 0:
                    prev_row = self.results_list.get_row_at_index(idx - 1)
                    if prev_row:
                        self.results_list.select_row(prev_row)
            return True
        
        return False


class ShortcutsDialog(Gtk.Window):
    """Keyboard shortcuts help dialog."""
    
    SHORTCUTS = {
        "General": [
            ("New Map", "Ctrl+N"),
            ("Save", "Ctrl+S"),
            ("Search Current Map", "Ctrl+F"),
            ("Search All Maps", "Ctrl+Shift+F"),
            ("Toggle Left Sidebar", "Ctrl+B"),
            ("Toggle Right Sidebar", "Ctrl+Shift+B"),
            ("Preferences", "Ctrl+,"),
            ("Keyboard Shortcuts", "Ctrl+/"),
            ("Quit", "Ctrl+Q"),
        ],
        "Navigation": [
            ("Pan Canvas", "Middle-click drag"),
            ("Zoom In", "Ctrl++ or Ctrl+Scroll"),
            ("Zoom Out", "Ctrl+- or Ctrl+Scroll"),
            ("Zoom to Fit", "Ctrl+0"),
            ("Zoom to 100%", "Ctrl+1"),
            ("Toggle Minimap", "Ctrl+M"),
            ("Navigate Up/Down", "↑ / ↓"),
            ("Navigate Left/Right", "← / →"),
        ],
        "Node Editing": [
            ("Create Child Node", "Tab"),
            ("Create Sibling Node", "Enter"),
            ("Edit Node Text", "F2 or just type"),
            ("Delete Node", "Delete / Backspace"),
            ("Collapse/Expand", "Ctrl+Space"),
            ("Open Notes", "Ctrl+Enter"),
            ("Undo", "Ctrl+Z"),
            ("Redo", "Ctrl+R"),
        ],
    }
    
    def __init__(self, parent: Gtk.Window):
        super().__init__()
        
        self.set_transient_for(parent)
        self.set_modal(True)
        self.set_default_size(500, 600)
        self.set_title("Keyboard Shortcuts")
        
        # Main container
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        box.set_margin_start(24)
        box.set_margin_end(24)
        box.set_margin_top(24)
        box.set_margin_bottom(24)
        
        for section, shortcuts in self.SHORTCUTS.items():
            section_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
            section_box.add_css_class("shortcuts-section")
            
            # Section title
            title = Gtk.Label(label=section.upper())
            title.set_halign(Gtk.Align.START)
            title.add_css_class("shortcuts-section-title")
            section_box.append(title)
            
            # Shortcuts
            for action, keys in shortcuts:
                row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
                row.add_css_class("shortcut-row")
                
                action_label = Gtk.Label(label=action)
                action_label.set_halign(Gtk.Align.START)
                action_label.set_hexpand(True)
                action_label.add_css_class("shortcut-action")
                row.append(action_label)
                
                keys_label = Gtk.Label(label=keys)
                keys_label.set_halign(Gtk.Align.END)
                keys_label.add_css_class("shortcut-keys")
                row.append(keys_label)
                
                section_box.append(row)
            
            box.append(section_box)
        
        scrolled.set_child(box)
        self.set_child(scrolled)
        
        # Close on Escape
        key_ctrl = Gtk.EventControllerKey()
        key_ctrl.connect("key-pressed", self._on_key_pressed)
        self.add_controller(key_ctrl)
    
    def _on_key_pressed(self, controller, keyval, keycode, state):
        if keyval == Gdk.KEY_Escape:
            self.close()
            return True
        return False


class SettingsDialog(Adw.PreferencesWindow):
    """Settings/preferences dialog."""

    def __init__(self, parent: Gtk.Window, db: Database):
        super().__init__()
        self.db = db

        # Live-apply callback: (key: str, value: Any) -> None
        self.on_settings_changed: Optional[Callable] = None

        self.set_transient_for(parent)
        self.set_modal(True)
        self.set_default_size(600, 500)
        self.set_title("Preferences")
        
        # Appearance page
        appearance_page = Adw.PreferencesPage()
        appearance_page.set_title("Appearance")
        appearance_page.set_icon_name("applications-graphics-symbolic")
        
        # Canvas group
        canvas_group = Adw.PreferencesGroup()
        canvas_group.set_title("Canvas")
        
        # Grid toggle
        grid_row = Adw.SwitchRow()
        grid_row.set_title("Show Grid")
        grid_row.set_subtitle("Display dot grid pattern on canvas")
        grid_row.set_active(self.db.get_setting("show_grid", True))
        grid_row.connect("notify::active", self._on_grid_changed)
        canvas_group.add(grid_row)
        
        # Minimap toggle
        minimap_row = Adw.SwitchRow()
        minimap_row.set_title("Show Minimap")
        minimap_row.set_subtitle("Display navigation minimap in corner")
        minimap_row.set_active(self.db.get_setting("show_minimap", True))
        minimap_row.connect("notify::active", self._on_minimap_changed)
        canvas_group.add(minimap_row)
        
        # Node glow toggle
        glow_row = Adw.SwitchRow()
        glow_row.set_title("Node Glow Effects")
        glow_row.set_subtitle("Show glow effect on selected nodes")
        glow_row.set_active(self.db.get_setting("node_glow", True))
        glow_row.connect("notify::active", self._on_glow_changed)
        canvas_group.add(glow_row)
        
        appearance_page.add(canvas_group)
        self.add(appearance_page)
        
        # Behavior page
        behavior_page = Adw.PreferencesPage()
        behavior_page.set_title("Behavior")
        behavior_page.set_icon_name("preferences-system-symbolic")
        
        # Auto-save group
        autosave_group = Adw.PreferencesGroup()
        autosave_group.set_title("Auto-Save")
        
        # Auto-save interval
        interval_row = Adw.ComboRow()
        interval_row.set_title("Auto-save Interval")
        interval_row.set_subtitle("How often to automatically save changes")
        
        intervals = Gtk.StringList.new(["Disabled", "15 seconds", "30 seconds", "1 minute", "5 minutes"])
        interval_row.set_model(intervals)
        
        current_interval = self.db.get_setting("autosave_interval", 30)
        interval_map = {0: 0, 15: 1, 30: 2, 60: 3, 300: 4}
        interval_row.set_selected(interval_map.get(current_interval, 2))
        interval_row.connect("notify::selected", self._on_interval_changed)
        
        autosave_group.add(interval_row)
        
        behavior_page.add(autosave_group)
        
        # Layout group
        layout_group = Adw.PreferencesGroup()
        layout_group.set_title("Layout")
        
        # Default auto-layout
        autolayout_row = Adw.SwitchRow()
        autolayout_row.set_title("Auto-Layout for New Maps")
        autolayout_row.set_subtitle("Automatically arrange nodes in radial layout")
        autolayout_row.set_active(self.db.get_setting("default_auto_layout", True))
        autolayout_row.connect("notify::active", self._on_autolayout_changed)
        layout_group.add(autolayout_row)
        
        behavior_page.add(layout_group)
        self.add(behavior_page)
        
        # Backup page
        backup_page = Adw.PreferencesPage()
        backup_page.set_title("Backup")
        backup_page.set_icon_name("document-save-symbolic")
        
        backup_group = Adw.PreferencesGroup()
        backup_group.set_title("Automatic Backups")
        
        # Backup count
        backup_row = Adw.SpinRow.new_with_range(0, 50, 1)
        backup_row.set_title("Backups to Keep")
        backup_row.set_subtitle("Number of backup versions to keep per map")
        backup_row.set_value(self.db.get_setting("backup_count", 10))
        backup_row.connect("notify::value", self._on_backup_count_changed)
        backup_group.add(backup_row)
        
        backup_page.add(backup_group)
        self.add(backup_page)
    
    def _notify(self, key: str, value):
        """Notify listener of a settings change."""
        if self.on_settings_changed:
            self.on_settings_changed(key, value)

    def _on_grid_changed(self, row, param):
        self.db.set_setting("show_grid", row.get_active())
        self._notify("show_grid", row.get_active())

    def _on_minimap_changed(self, row, param):
        self.db.set_setting("show_minimap", row.get_active())
        self._notify("show_minimap", row.get_active())

    def _on_glow_changed(self, row, param):
        self.db.set_setting("node_glow", row.get_active())
        self._notify("node_glow", row.get_active())

    def _on_interval_changed(self, row, param):
        values = [0, 15, 30, 60, 300]
        val = values[row.get_selected()]
        self.db.set_setting("autosave_interval", val)
        self._notify("autosave_interval", val)

    def _on_autolayout_changed(self, row, param):
        self.db.set_setting("default_auto_layout", row.get_active())
        self._notify("default_auto_layout", row.get_active())

    def _on_backup_count_changed(self, row, param):
        val = int(row.get_value())
        self.db.set_setting("backup_count", val)
        self._notify("backup_count", val)

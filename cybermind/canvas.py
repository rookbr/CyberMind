"""Canvas widget for rendering mindmap nodes and connections."""

import math
from typing import Optional, List, Dict, Tuple, Callable
from dataclasses import dataclass
import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gtk, Gdk, GLib, Graphene, Gsk, Gio

import cairo

from cybermind.database import Node, NodeStyle, MindMap, Database
from cybermind.undo import UndoManager, UndoAction, ActionType


@dataclass
class RenderedNode:
    """A node with calculated position and dimensions."""
    node: Node
    x: float
    y: float
    width: float
    height: float
    children: List["RenderedNode"]
    angle: float = 0.0  # Angle from parent (for radial layout)
    
    def contains_point(self, px: float, py: float) -> bool:
        """Check if a point is inside this node."""
        return (self.x <= px <= self.x + self.width and 
                self.y <= py <= self.y + self.height)


class MindMapCanvas(Gtk.DrawingArea):
    """Custom canvas widget for rendering mindmaps."""
    
    # Colors (matching theme.css)
    COLORS = {
        'bg_primary': (0.039, 0.039, 0.039),      # #0a0a0a
        'bg_secondary': (0.078, 0.078, 0.078),    # #141414
        'surface': (0.118, 0.118, 0.118),         # #1e1e1e
        'surface_hover': (0.145, 0.145, 0.145),   # #252525
        'border_subtle': (0.165, 0.165, 0.165),   # #2a2a2a
        'border_active': (1.0, 0.176, 0.176),     # #ff2d2d
        'text_primary': (0.878, 0.878, 0.878),    # #e0e0e0
        'text_secondary': (0.533, 0.533, 0.533),  # #888888
        'text_muted': (0.333, 0.333, 0.333),      # #555555
        'accent_primary': (1.0, 0.176, 0.176),    # #ff2d2d
        'accent_hover': (1.0, 0.267, 0.267),      # #ff4444
        'accent_secondary': (0.8, 0.0, 0.0),      # #cc0000
        'success': (0.0, 1.0, 0.255),             # #00ff41
        'warning': (1.0, 0.667, 0.0),             # #ffaa00
        'grid_dots': (0.12, 0.12, 0.12),          # Subtle grid
        'root_node': (0.15, 0.05, 0.05),           # Dark red for root
        'root_border': (0.6, 0.1, 0.1),            # Brighter red border for root
    }
    
    # Priority colors
    PRIORITY_COLORS = {
        'critical': (1.0, 0.176, 0.176),    # Red
        'high': (1.0, 0.667, 0.0),          # Orange
        'medium': (1.0, 0.533, 0.0),        # Amber
        'low': (0.0, 1.0, 0.255),           # Green
        'info': (0.302, 0.651, 1.0),        # Blue
    }
    
    # Status colors
    STATUS_COLORS = {
        'todo': (0.533, 0.533, 0.533),      # Gray
        'in_progress': (1.0, 0.667, 0.0),   # Orange
        'done': (0.0, 1.0, 0.255),          # Green
        'blocked': (1.0, 0.176, 0.176),     # Red
    }
    
    # Layout constants
    NODE_PADDING = 16
    NODE_MIN_WIDTH = 120
    NODE_MAX_WIDTH = 300
    ROOT_NODE_MIN_WIDTH = 160
    NODE_HEIGHT = 40
    ROOT_NODE_HEIGHT = 56
    HORIZONTAL_SPACING = 60
    VERTICAL_SPACING = 15
    RADIAL_RADIUS_BASE = 140
    RADIAL_RADIUS_INCREMENT = 120
    
    def __init__(self, db: Database):
        super().__init__()
        
        self.db = db
        self.current_map: Optional[MindMap] = None
        self.nodes: List[Node] = []
        self.rendered_nodes: List[RenderedNode] = []
        self.root_rendered: Optional[RenderedNode] = None
        
        # View state
        self.zoom = 1.0
        self.pan_x = 0.0
        self.pan_y = 0.0
        self.is_panning = False
        self.pan_start_x = 0.0
        self.pan_start_y = 0.0
        self.last_mouse_x = 0.0
        self.last_mouse_y = 0.0
        
        # Selection state
        self.selected_node: Optional[RenderedNode] = None
        self.hovered_node: Optional[RenderedNode] = None
        self.editing_node: Optional[RenderedNode] = None
        
        # Dragging state
        self.dragging_node: Optional[RenderedNode] = None
        self.drag_start_node_x: float = 0.0
        self.drag_start_node_y: float = 0.0
        self.edit_text: str = ""
        self.edit_cursor_pos: int = 0
        self.edit_selection_start: Optional[int] = None  # For text selection
        self.cursor_visible: bool = True
        self.cursor_blink_id: Optional[int] = None
        
        # Placeholder text (greyed out, replaced on type)
        self.is_placeholder_text: bool = False
        
        # Undo manager
        # Keep history short and predictable: 5 undo + 5 redo.
        self.undo_manager = UndoManager(max_undo=5, max_redo=5)
        
        # Note indicator cache (populated once per map load)
        self._nodes_with_notes: set = set()

        # Drag threshold
        self._drag_threshold = 5
        self._drag_exceeded_threshold = False
        self._drag_pending_node: Optional[RenderedNode] = None

        # Context popover tracking
        self._context_popover: Optional[Gtk.PopoverMenu] = None

        # Layout mode
        self.layout_mode: str = "horizontal"

        # Clipboard for copy/paste
        self.clipboard_node: Optional[Node] = None
        self.clipboard_children: List[Node] = []

        # Moving node (for right-click move)
        self.moving_node: Optional[Node] = None
        
        # Callbacks
        self.on_node_selected: Optional[Callable[[Optional[Node]], None]] = None
        self.on_node_edited: Optional[Callable[[Node, str], None]] = None
        self.on_structure_changed: Optional[Callable[[], None]] = None
        
        # Canvas settings
        self.show_grid = True
        self.grid_size = 30
        self.auto_layout = True
        self.show_minimap = True
        self.animation_enabled = True
        
        # Setup widget
        self.set_draw_func(self._on_draw)
        self.set_focusable(True)
        self.set_can_focus(True)
        
        # Setup event controllers
        self._setup_event_controllers()
        
        # Set size request
        self.set_hexpand(True)
        self.set_vexpand(True)
    
    def _setup_event_controllers(self):
        """Setup mouse and keyboard event controllers."""
        # Mouse click
        click_ctrl = Gtk.GestureClick()
        click_ctrl.connect("pressed", self._on_click)
        click_ctrl.connect("released", self._on_click_released)
        click_ctrl.set_button(0)  # All buttons
        self.add_controller(click_ctrl)
        
        # Mouse motion
        motion_ctrl = Gtk.EventControllerMotion()
        motion_ctrl.connect("motion", self._on_motion)
        motion_ctrl.connect("leave", self._on_leave)
        self.add_controller(motion_ctrl)
        
        # Scroll (zoom)
        scroll_ctrl = Gtk.EventControllerScroll()
        scroll_ctrl.set_flags(Gtk.EventControllerScrollFlags.BOTH_AXES)
        scroll_ctrl.connect("scroll", self._on_scroll)
        self.add_controller(scroll_ctrl)
        
        # Keyboard
        key_ctrl = Gtk.EventControllerKey()
        key_ctrl.connect("key-pressed", self._on_key_pressed)
        self.add_controller(key_ctrl)
        
        # Drag for panning (left mouse button)
        drag_ctrl = Gtk.GestureDrag()
        drag_ctrl.set_button(1)  # Left mouse button
        drag_ctrl.connect("drag-begin", self._on_drag_begin)
        drag_ctrl.connect("drag-update", self._on_drag_update)
        drag_ctrl.connect("drag-end", self._on_drag_end)
        self.add_controller(drag_ctrl)
        
        # Right-click for context menu
        right_click = Gtk.GestureClick()
        right_click.set_button(3)  # Right mouse button
        right_click.connect("pressed", self._on_right_click)
        self.add_controller(right_click)
    
    def clear(self):
        """Clear the canvas."""
        self.current_map = None
        self.nodes = []
        self.rendered_nodes = []
        self.root_rendered = None
        self.selected_node = None
        self.editing_node = None
        self.queue_draw()
    
    def load_map(self, mind_map: MindMap):
        """Load a mindmap for display."""
        self.current_map = mind_map
        self.nodes = self.db.get_nodes_for_map(mind_map.id)

        # Apply saved view settings
        self.zoom = mind_map.settings.zoom_level
        self.pan_x = mind_map.settings.pan_x
        self.pan_y = mind_map.settings.pan_y
        self.auto_layout = mind_map.settings.auto_layout
        self.show_grid = mind_map.settings.show_grid
        self.show_minimap = mind_map.settings.show_minimap
        self.layout_mode = mind_map.settings.layout_mode

        # Populate note cache
        self._nodes_with_notes = self.db.get_node_ids_with_notes(mind_map.id)

        # Clear selection
        self.selected_node = None
        self.editing_node = None

        # Check if root already has a saved position before layout
        root_nodes = [n for n in self.nodes if n.parent_id is None]
        root_had_position = root_nodes and root_nodes[0].position_x is not None

        # Calculate layout
        self._calculate_layout()

        # Center view if no saved pan, or if the root had no saved position
        # (handles both new maps and transition from widget-relative origins)
        if (mind_map.settings.pan_x == 0 and mind_map.settings.pan_y == 0) or not root_had_position:
            self.center_view()

        self.queue_draw()

    def invalidate_note_cache(self):
        """Rebuild the note indicator cache from the database."""
        if self.current_map:
            self._nodes_with_notes = self.db.get_node_ids_with_notes(self.current_map.id)
    
    def _calc_node_size(self, node: Node, is_root: bool = False) -> Tuple[float, float]:
        """Calculate node dimensions based on text."""
        text_width = len(node.text) * 9 + self.NODE_PADDING * 2
        if is_root:
            width = max(self.ROOT_NODE_MIN_WIDTH, min(self.NODE_MAX_WIDTH, text_width))
            height = self.ROOT_NODE_HEIGHT
        else:
            width = max(self.NODE_MIN_WIDTH, min(self.NODE_MAX_WIDTH, text_width))
            height = self.NODE_HEIGHT
        return width, height

    def _flatten_rendered(self, node: RenderedNode, result: List[RenderedNode]):
        """Flatten rendered tree into a list."""
        result.append(node)
        for child in node.children:
            self._flatten_rendered(child, result)

    def _calculate_layout(self):
        """Dispatch to the appropriate layout algorithm."""
        if not self.nodes:
            self.rendered_nodes = []
            self.root_rendered = None
            return

        root_nodes = [n for n in self.nodes if n.parent_id is None]
        if not root_nodes:
            self.rendered_nodes = []
            self.root_rendered = None
            return

        if self.layout_mode == "radial":
            self._calculate_radial_layout()
        else:
            self._calculate_horizontal_layout()

        # In manual mode, persist every node position so restarts are stable
        if not self.auto_layout:
            self._persist_rendered_positions()

    def _calculate_horizontal_layout(self):
        """Calculate horizontal tree layout positions."""
        root_nodes = [n for n in self.nodes if n.parent_id is None]
        root = root_nodes[0]

        def calc_subtree_height(node: Node) -> float:
            children = [n for n in self.nodes if n.parent_id == node.id and not node.is_collapsed]
            if not children or node.is_collapsed:
                return self.NODE_HEIGHT + self.VERTICAL_SPACING
            total = 0
            for child in children:
                total += calc_subtree_height(child)
            return max(self.NODE_HEIGHT + self.VERTICAL_SPACING, total)

        def build_rendered_tree(node: Node, depth: int = 0,
                               parent_right_x: float = 0, parent_center_y: float = 0,
                               y_offset: float = 0) -> RenderedNode:
            is_root = depth == 0
            w, h = self._calc_node_size(node, is_root)

            if is_root:
                # Use saved position if available, otherwise fixed origin
                if node.position_x is not None and node.position_y is not None:
                    x = node.position_x
                    y = node.position_y
                else:
                    x = -w / 2
                    y = -h / 2
            elif self.auto_layout:
                x = parent_right_x + self.HORIZONTAL_SPACING
                y = y_offset
            else:
                if node.position_x is not None and node.position_y is not None:
                    x = node.position_x
                    y = node.position_y
                else:
                    x = parent_right_x + self.HORIZONTAL_SPACING
                    y = y_offset

            rendered = RenderedNode(
                node=node, x=x, y=y, width=w, height=h,
                children=[], angle=0
            )

            children = [n for n in self.nodes if n.parent_id == node.id and not node.is_collapsed]
            children.sort(key=lambda n: n.sort_order)

            if children and not node.is_collapsed:
                total_height = sum(calc_subtree_height(c) for c in children)
                child_y = y + h / 2 - total_height / 2

                for child in children:
                    child_height = calc_subtree_height(child)
                    child_rendered = build_rendered_tree(
                        child, depth + 1,
                        x + w, y + h / 2,
                        child_y + child_height / 2 - self.NODE_HEIGHT / 2
                    )
                    rendered.children.append(child_rendered)
                    child_y += child_height

            return rendered

        self.root_rendered = build_rendered_tree(root)

        self.rendered_nodes = []
        self._flatten_rendered(self.root_rendered, self.rendered_nodes)

        if not self.auto_layout and self.rendered_nodes:
            self._avoid_overlaps_for_unpositioned_nodes()

    def _calculate_radial_layout(self):
        """Calculate radial layout positions."""
        root_nodes = [n for n in self.nodes if n.parent_id is None]
        root = root_nodes[0]

        def count_leaves(node: Node) -> int:
            children = [n for n in self.nodes if n.parent_id == node.id and not node.is_collapsed]
            if not children or node.is_collapsed:
                return 1
            return sum(count_leaves(c) for c in children)

        def build_radial_tree(node: Node, depth: int,
                              parent_cx: float, parent_cy: float,
                              start_angle: float, angle_span: float) -> RenderedNode:
            is_root = depth == 0
            w, h = self._calc_node_size(node, is_root)

            if is_root:
                # Use saved position if available, otherwise fixed origin
                if node.position_x is not None and node.position_y is not None:
                    x = node.position_x
                    y = node.position_y
                else:
                    x = -w / 2
                    y = -h / 2
                cx = x + w / 2
                cy = y + h / 2
            elif not self.auto_layout and node.position_x is not None and node.position_y is not None:
                x = node.position_x
                y = node.position_y
                cx = x + w / 2
                cy = y + h / 2
            else:
                radius = self.RADIAL_RADIUS_BASE + self.RADIAL_RADIUS_INCREMENT * (depth - 1)
                mid_angle = start_angle + angle_span / 2
                cx = parent_cx + radius * math.cos(mid_angle)
                cy = parent_cy + radius * math.sin(mid_angle)
                x = cx - w / 2
                y = cy - h / 2

            rendered = RenderedNode(
                node=node, x=x, y=y, width=w, height=h,
                children=[], angle=start_angle + angle_span / 2 if depth > 0 else 0
            )

            children = [n for n in self.nodes if n.parent_id == node.id and not node.is_collapsed]
            children.sort(key=lambda n: n.sort_order)

            if children and not node.is_collapsed:
                total_leaves = sum(count_leaves(c) for c in children)
                if total_leaves == 0:
                    total_leaves = len(children)

                if depth == 0:
                    child_start = -math.pi / 2
                    full_span = 2 * math.pi
                else:
                    child_start = start_angle
                    full_span = angle_span

                for child in children:
                    child_leaves = count_leaves(child)
                    child_span = full_span * (child_leaves / total_leaves)
                    child_rendered = build_radial_tree(
                        child, depth + 1,
                        cx, cy,
                        child_start, child_span
                    )
                    rendered.children.append(child_rendered)
                    child_start += child_span

            return rendered

        self.root_rendered = build_radial_tree(root, 0, 0, 0, 0, 2 * math.pi)

        self.rendered_nodes = []
        self._flatten_rendered(self.root_rendered, self.rendered_nodes)

        if not self.auto_layout and self.rendered_nodes:
            self._avoid_overlaps_for_unpositioned_nodes()

    def _rects_overlap(self,
                       ax: float, ay: float, aw: float, ah: float,
                       bx: float, by: float, bw: float, bh: float,
                       padding: float = 10.0) -> bool:
        return not (
            ax + aw + padding <= bx or
            bx + bw + padding <= ax or
            ay + ah + padding <= by or
            by + bh + padding <= ay
        )

    def _find_non_overlapping_position(self,
                                       desired_x: float,
                                       desired_y: float,
                                       width: float,
                                       height: float,
                                       exclude_node_id: Optional[int] = None,
                                       padding: float = 10.0) -> Tuple[float, float]:
        """Find a nearby position that doesn't overlap other rendered nodes."""

        def overlaps(x: float, y: float) -> bool:
            for other in self.rendered_nodes:
                if exclude_node_id is not None and other.node.id == exclude_node_id:
                    continue
                if self._rects_overlap(x, y, width, height,
                                       other.x, other.y, other.width, other.height,
                                       padding=padding):
                    return True
            return False

        if not overlaps(desired_x, desired_y):
            return desired_x, desired_y

        step = 18.0
        for radius_steps in range(1, 60):
            radius = radius_steps * step
            for angle_steps in range(0, 24):
                angle = (2 * math.pi) * (angle_steps / 24.0)
                x = desired_x + radius * math.cos(angle)
                y = desired_y + radius * math.sin(angle)
                if not overlaps(x, y):
                    return x, y

        return desired_x, desired_y

    def _avoid_overlaps_for_unpositioned_nodes(self):
        """Nudge nodes without saved positions away from fixed nodes."""
        # Consider nodes with explicit position as fixed.
        fixed_ids = {r.node.id for r in self.rendered_nodes
                     if r.node.position_x is not None and r.node.position_y is not None}

        for rendered in self.rendered_nodes:
            # Never move root automatically.
            if rendered.node.parent_id is None:
                continue
            if rendered.node.id in fixed_ids:
                continue

            # If this auto-placed node overlaps anything, move it to a free spot.
            new_x, new_y = self._find_non_overlapping_position(
                rendered.x,
                rendered.y,
                rendered.width,
                rendered.height,
                exclude_node_id=rendered.node.id,
                padding=10.0,
            )
            rendered.x = new_x
            rendered.y = new_y

    # ==================== Auto-balance ====================

    def auto_balance_layout(self):
        """Apply a non-overlapping auto layout as fixed positions (undoable)."""
        if not self.current_map:
            return

        map_id = self.current_map.id

        # Snapshot current state for undo (include root)
        old_auto_layout = bool(self.auto_layout)
        old_nodes = self.db.get_nodes_for_map(map_id)
        old_positions = []
        for n in old_nodes:
            old_positions.append({
                "node_id": n.id,
                "position_x": n.position_x,
                "position_y": n.position_y,
            })

        # Compute new positions using the existing tree layout.
        prev_auto_layout = self.auto_layout
        try:
            self.auto_layout = True
            self._calculate_layout()
            new_positions = []
            for r in self.rendered_nodes:
                new_positions.append({
                    "node_id": r.node.id,
                    "position_x": float(r.x),
                    "position_y": float(r.y),
                })
        finally:
            self.auto_layout = prev_auto_layout

        # Apply as fixed/manual positions (include root).
        self.auto_layout = False
        self.current_map.settings.auto_layout = False
        self.db.update_map(self.current_map)

        pos_map = {p["node_id"]: (p["position_x"], p["position_y"]) for p in new_positions}
        for n in old_nodes:
            if n.id in pos_map:
                x, y = pos_map[n.id]
                n.position_x = x
                n.position_y = y
                self.db.update_node(n)

        # Push undo action
        self.undo_manager.push(UndoAction(
            action_type=ActionType.MAP_LAYOUT,
            description="Auto-balance layout",
            data={
                "map_id": map_id,
                "auto_layout": old_auto_layout,
                "positions": old_positions,
            },
            redo_data={
                "map_id": map_id,
                "auto_layout": False,
                "positions": new_positions,
            }
        ))

        # Reload and redraw
        self.nodes = self.db.get_nodes_for_map(map_id)
        self._calculate_layout()
        self.queue_draw()

        if self.on_structure_changed:
            self.on_structure_changed()
    
    def _on_draw(self, area, cr, width, height):
        """Main drawing function."""
        cr.save()
        
        # Fill background
        bg = self.COLORS['bg_primary']
        cr.set_source_rgb(*bg)
        cr.paint()
        
        # Draw grid if enabled
        if self.show_grid:
            self._draw_grid(cr, width, height)
        
        # Apply zoom and pan transformations
        cr.translate(self.pan_x, self.pan_y)
        cr.scale(self.zoom, self.zoom)
        
        # Draw connections first (behind nodes)
        if self.root_rendered:
            self._draw_connections(cr, self.root_rendered)
        
        # Draw nodes
        for rendered in self.rendered_nodes:
            self._draw_node(cr, rendered)
        
        cr.restore()
        
        # Draw minimap (not affected by zoom/pan)
        if self.show_minimap and self.rendered_nodes:
            self._draw_minimap(cr, width, height)
    
    def _draw_grid(self, cr, width: float, height: float):
        """Draw dot grid pattern."""
        cr.save()
        
        grid_color = self.COLORS['grid_dots']
        cr.set_source_rgb(*grid_color)
        
        # Adjust grid based on zoom and pan
        effective_grid = self.grid_size * self.zoom
        
        # Calculate grid offset based on pan
        offset_x = self.pan_x % effective_grid
        offset_y = self.pan_y % effective_grid
        
        # Draw dots
        x = offset_x
        while x < width:
            y = offset_y
            while y < height:
                cr.arc(x, y, 1.5, 0, 2 * math.pi)
                cr.fill()
                y += effective_grid
            x += effective_grid
        
        cr.restore()
    
    def _draw_connections(self, cr, parent: RenderedNode):
        """Draw bezier connections between nodes."""
        parent_cx = parent.x + parent.width / 2
        parent_cy = parent.y + parent.height / 2
        
        for child in parent.children:
            child_cx = child.x + child.width / 2
            child_cy = child.y + child.height / 2
            
            # Calculate control points for bezier curve
            dx = child_cx - parent_cx
            dy = child_cy - parent_cy
            
            # Control point distance
            ctrl_dist = math.sqrt(dx * dx + dy * dy) * 0.4
            
            # Start point (edge of parent node)
            angle = math.atan2(dy, dx)
            start_x = parent_cx + (parent.width / 2) * math.cos(angle)
            start_y = parent_cy + (parent.height / 2) * math.sin(angle)
            
            # End point (edge of child node)
            end_x = child_cx - (child.width / 2) * math.cos(angle)
            end_y = child_cy - (child.height / 2) * math.sin(angle)
            
            # Control points
            ctrl1_x = start_x + ctrl_dist * math.cos(angle)
            ctrl1_y = start_y + ctrl_dist * math.sin(angle)
            ctrl2_x = end_x - ctrl_dist * math.cos(angle)
            ctrl2_y = end_y - ctrl_dist * math.sin(angle)
            
            # Draw gradient line
            # Create gradient
            gradient = cairo.LinearGradient(start_x, start_y, end_x, end_y)
            accent = self.COLORS['accent_primary']
            secondary = self.COLORS['accent_secondary']
            gradient.add_color_stop_rgba(0, *accent, 0.8)
            gradient.add_color_stop_rgba(1, *secondary, 0.6)
            
            cr.set_source(gradient)
            cr.set_line_width(max(1.5, 3 - len(parent.children) * 0.2))
            cr.set_line_cap(cairo.LINE_CAP_ROUND)
            
            cr.move_to(start_x, start_y)
            cr.curve_to(ctrl1_x, ctrl1_y, ctrl2_x, ctrl2_y, end_x, end_y)
            cr.stroke()
            
            # Recursive draw
            self._draw_connections(cr, child)
    
    def _draw_node(self, cr, rendered: RenderedNode):
        """Draw a single node."""
        node = rendered.node
        x, y, w, h = rendered.x, rendered.y, rendered.width, rendered.height
        is_root = node.parent_id is None
        is_selected = self.selected_node == rendered
        is_hovered = self.hovered_node == rendered
        is_editing = self.editing_node == rendered
        
        cr.save()
        
        # Node background
        radius = 8 if is_root else 6
        self._draw_rounded_rect(cr, x, y, w, h, radius)
        
        # Fill color based on state
        if is_root:
            bg = self.COLORS['root_node']  # Distinct root color
        elif is_selected:
            bg = self.COLORS['surface_hover']
        elif is_hovered:
            bg = self.COLORS['surface_hover']
        else:
            bg = self.COLORS['surface']
        
        # Apply custom color if set
        if node.style.color:
            try:
                # Parse hex color
                color = node.style.color.lstrip('#')
                r = int(color[0:2], 16) / 255
                g = int(color[2:4], 16) / 255
                b = int(color[4:6], 16) / 255
                bg = (r, g, b)
            except (ValueError, IndexError):
                pass
        
        cr.set_source_rgb(*bg)
        cr.fill_preserve()
        
        # Border
        if is_root and not is_selected and not is_editing:
            border_color = self.COLORS['root_border']  # Distinct root border
            cr.set_line_width(2)
        elif is_selected or is_editing:
            border_color = self.COLORS['border_active']
            cr.set_line_width(2)
            
            # Glow effect for selected
            if is_selected and not is_editing:
                cr.save()
                for i in range(3):
                    alpha = 0.15 - i * 0.04
                    cr.set_source_rgba(*self.COLORS['accent_primary'], alpha)
                    self._draw_rounded_rect(cr, x - i * 2, y - i * 2, 
                                           w + i * 4, h + i * 4, radius + i * 2)
                    cr.stroke()
                cr.restore()
                self._draw_rounded_rect(cr, x, y, w, h, radius)
        elif is_hovered:
            border_color = self.COLORS['text_muted']
            cr.set_line_width(1.5)
        else:
            border_color = self.COLORS['border_subtle']
            cr.set_line_width(1)
        
        cr.set_source_rgb(*border_color)
        cr.stroke()
        
        # Priority indicator
        if node.style.priority:
            priority_color = self.PRIORITY_COLORS.get(node.style.priority, self.COLORS['text_muted'])
            indicator_size = 8
            cr.arc(x + indicator_size + 4, y + h / 2, indicator_size / 2, 0, 2 * math.pi)
            cr.set_source_rgb(*priority_color)
            cr.fill()
        
        # Status indicator (small icon in corner)
        if node.style.status:
            status_color = self.STATUS_COLORS.get(node.style.status, self.COLORS['text_muted'])
            cr.rectangle(x + w - 20, y + 4, 16, 4)
            cr.set_source_rgb(*status_color)
            cr.fill()
        
        # Node text
        text_x = x + self.NODE_PADDING
        text_y = y + h / 2
        
        if node.style.priority:
            text_x += 12  # Offset for priority indicator
        
        if is_editing:
            # Draw text with cursor
            self._draw_edit_text(cr, text_x, text_y, w - self.NODE_PADDING * 2, is_root)
        else:
            # Draw normal text
            cr.set_source_rgb(*self.COLORS['text_primary'])
            cr.select_font_face("JetBrains Mono", cairo.FONT_SLANT_NORMAL, 
                              cairo.FONT_WEIGHT_BOLD if is_root else cairo.FONT_WEIGHT_NORMAL)
            cr.set_font_size(15 if is_root else 13)
            
            # Truncate text if too long
            text = node.text
            extents = cr.text_extents(text)
            max_width = w - self.NODE_PADDING * 2 - (12 if node.style.priority else 0)
            while extents.width > max_width and len(text) > 3:
                text = text[:-4] + "..."
                extents = cr.text_extents(text)
            
            cr.move_to(text_x, text_y + extents.height / 2 - 2)
            cr.show_text(text)
        
        # Collapse/expand indicator
        children = [n for n in self.nodes if n.parent_id == node.id]
        if children:
            indicator_x = x + w - 16
            indicator_y = y + h / 2
            
            cr.set_source_rgb(*self.COLORS['text_muted'])
            cr.set_font_size(12)
            
            if node.is_collapsed:
                # Plus sign
                cr.move_to(indicator_x - 4, indicator_y)
                cr.line_to(indicator_x + 4, indicator_y)
                cr.move_to(indicator_x, indicator_y - 4)
                cr.line_to(indicator_x, indicator_y + 4)
                cr.set_line_width(1.5)
                cr.stroke()
                
                # Child count
                cr.move_to(indicator_x - 4, indicator_y + 14)
                cr.set_font_size(9)
                cr.show_text(str(len(children)))
            else:
                # Minus sign
                cr.move_to(indicator_x - 4, indicator_y)
                cr.line_to(indicator_x + 4, indicator_y)
                cr.set_line_width(1.5)
                cr.stroke()
        
        # Notes indicator (uses cached set instead of DB query per frame)
        if node.id in self._nodes_with_notes:
            cr.set_source_rgba(*self.COLORS['accent_primary'], 0.8)
            cr.arc(x + w - 8, y + 8, 4, 0, 2 * math.pi)
            cr.fill()
        
        cr.restore()
    
    def _draw_edit_text(self, cr, x: float, y: float, max_width: float, is_root: bool):
        """Draw text being edited with cursor and selection."""
        cr.select_font_face("JetBrains Mono", cairo.FONT_SLANT_NORMAL, 
                          cairo.FONT_WEIGHT_BOLD if is_root else cairo.FONT_WEIGHT_NORMAL)
        cr.set_font_size(15 if is_root else 13)
        
        extents = cr.text_extents(self.edit_text) if self.edit_text else type('obj', (object,), {'height': 14, 'width': 0})()
        
        # Draw selection highlight if any
        if self.edit_selection_start is not None:
            sel_start = min(self.edit_selection_start, self.edit_cursor_pos)
            sel_end = max(self.edit_selection_start, self.edit_cursor_pos)
            
            start_text = self.edit_text[:sel_start]
            start_extents = cr.text_extents(start_text) if start_text else type('obj', (object,), {'width': 0})()
            sel_text = self.edit_text[sel_start:sel_end]
            sel_extents = cr.text_extents(sel_text) if sel_text else type('obj', (object,), {'width': 0})()
            
            # Draw selection background
            cr.set_source_rgba(*self.COLORS['accent_primary'], 0.3)
            cr.rectangle(x + start_extents.width, y - extents.height / 2 - 2, 
                        sel_extents.width, extents.height + 4)
            cr.fill()
        
        # Draw text
        if self.is_placeholder_text:
            cr.set_source_rgb(*self.COLORS['text_muted'])
        else:
            cr.set_source_rgb(*self.COLORS['text_primary'])
        
        cr.move_to(x, y + extents.height / 2 - 2)
        cr.show_text(self.edit_text)
        
        # Draw cursor
        if self.cursor_visible:
            cursor_text = self.edit_text[:self.edit_cursor_pos]
            cursor_extents = cr.text_extents(cursor_text) if cursor_text else type('obj', (object,), {'width': 0})()
            cursor_x = x + cursor_extents.width
            
            cr.set_source_rgb(*self.COLORS['accent_primary'])
            cr.set_line_width(2)
            cr.move_to(cursor_x, y - extents.height / 2)
            cr.line_to(cursor_x, y + extents.height / 2 + 2)
            cr.stroke()
    
    def _draw_rounded_rect(self, cr, x: float, y: float, w: float, h: float, radius: float):
        """Draw a rounded rectangle path."""
        cr.new_path()
        cr.arc(x + w - radius, y + radius, radius, -math.pi / 2, 0)
        cr.arc(x + w - radius, y + h - radius, radius, 0, math.pi / 2)
        cr.arc(x + radius, y + h - radius, radius, math.pi / 2, math.pi)
        cr.arc(x + radius, y + radius, radius, math.pi, 3 * math.pi / 2)
        cr.close_path()
    
    def _draw_minimap(self, cr, width: float, height: float):
        """Draw minimap in corner."""
        minimap_width = 180
        minimap_height = 120
        padding = 16
        
        mm_x = width - minimap_width - padding
        mm_y = height - minimap_height - padding
        
        # Background
        cr.save()
        self._draw_rounded_rect(cr, mm_x, mm_y, minimap_width, minimap_height, 4)
        cr.set_source_rgba(*self.COLORS['bg_secondary'], 0.9)
        cr.fill_preserve()
        cr.set_source_rgb(*self.COLORS['border_subtle'])
        cr.set_line_width(1)
        cr.stroke()
        
        # Clip to minimap bounds for all content
        cr.rectangle(mm_x + 2, mm_y + 2, minimap_width - 4, minimap_height - 4)
        cr.clip()
        
        # Calculate bounds of all nodes
        if not self.rendered_nodes:
            cr.restore()
            return
        
        min_x = min(n.x for n in self.rendered_nodes)
        max_x = max(n.x + n.width for n in self.rendered_nodes)
        min_y = min(n.y for n in self.rendered_nodes)
        max_y = max(n.y + n.height for n in self.rendered_nodes)
        
        map_width = max_x - min_x + 100
        map_height = max_y - min_y + 100
        
        # Scale factor
        scale = min(
            (minimap_width - 8) / map_width,
            (minimap_height - 8) / map_height
        )
        
        # Offset to center
        offset_x = mm_x + 4 + ((minimap_width - 8) - map_width * scale) / 2
        offset_y = mm_y + 4 + ((minimap_height - 8) - map_height * scale) / 2
        
        # Draw nodes as small rectangles
        for rendered in self.rendered_nodes:
            nx = offset_x + (rendered.x - min_x + 50) * scale
            ny = offset_y + (rendered.y - min_y + 50) * scale
            nw = max(4, rendered.width * scale)
            nh = max(2, rendered.height * scale)
            
            if rendered == self.selected_node:
                cr.set_source_rgb(*self.COLORS['accent_primary'])
            else:
                cr.set_source_rgb(*self.COLORS['text_muted'])
            
            cr.rectangle(nx, ny, nw, nh)
            cr.fill()
        
        # Draw viewport indicator (clipped to minimap bounds)
        vp_x = offset_x + (-self.pan_x / self.zoom - min_x + 50) * scale
        vp_y = offset_y + (-self.pan_y / self.zoom - min_y + 50) * scale
        vp_w = width / self.zoom * scale
        vp_h = height / self.zoom * scale
        
        cr.set_source_rgba(*self.COLORS['accent_primary'], 0.3)
        cr.rectangle(vp_x, vp_y, vp_w, vp_h)
        cr.fill()
        
        cr.set_source_rgb(*self.COLORS['accent_primary'])
        cr.set_line_width(1)
        cr.rectangle(vp_x, vp_y, vp_w, vp_h)
        cr.stroke()
        
        cr.restore()
    
    def _find_node_at(self, x: float, y: float) -> Optional[RenderedNode]:
        """Find the node at the given screen coordinates."""
        # Convert to canvas coordinates
        canvas_x = (x - self.pan_x) / self.zoom
        canvas_y = (y - self.pan_y) / self.zoom
        
        # Check in reverse order (top-most first)
        for rendered in reversed(self.rendered_nodes):
            if rendered.contains_point(canvas_x, canvas_y):
                return rendered
        
        return None
    
    def _on_click(self, gesture, n_press, x, y):
        """Handle mouse click."""
        # Grab focus so we can receive keyboard events
        self.grab_focus()
        
        button = gesture.get_current_button()
        
        if button == 1:  # Left click
            clicked_node = self._find_node_at(x, y)
            
            if n_press == 2 and clicked_node:
                # Double click - start editing with all text selected
                self.start_editing_select_all(clicked_node)
            elif n_press == 1:
                if self.editing_node and clicked_node != self.editing_node:
                    # Clicked outside editing node - commit edit
                    self.commit_edit()
                
                if clicked_node:
                    self.select_node(clicked_node)
                else:
                    self.select_node(None)
            
            self.grab_focus()
    
    def _on_click_released(self, gesture, n_press, x, y):
        """Handle mouse release."""
        pass
    
    def _on_motion(self, controller, x, y):
        """Handle mouse motion."""
        self.last_mouse_x = x
        self.last_mouse_y = y
        
        # Update hovered node
        new_hover = self._find_node_at(x, y)
        if new_hover != self.hovered_node:
            self.hovered_node = new_hover
            self.queue_draw()
    
    def _on_leave(self, controller):
        """Handle mouse leaving canvas."""
        if self.hovered_node:
            self.hovered_node = None
            self.queue_draw()
    
    def _on_scroll(self, controller, dx, dy):
        """Handle scroll for zooming."""
        # Check if Ctrl is held
        state = controller.get_current_event_state()
        if state & Gdk.ModifierType.CONTROL_MASK:
            # Zoom
            old_zoom = self.zoom
            zoom_factor = 1.1 if dy < 0 else 0.9
            self.zoom = max(0.25, min(4.0, self.zoom * zoom_factor))
            
            # Zoom towards mouse position
            if old_zoom != self.zoom:
                mouse_x, mouse_y = self.last_mouse_x, self.last_mouse_y
                self.pan_x = mouse_x - (mouse_x - self.pan_x) * (self.zoom / old_zoom)
                self.pan_y = mouse_y - (mouse_y - self.pan_y) * (self.zoom / old_zoom)
                self.queue_draw()
            
            return True
        
        return False
    
    def _on_drag_begin(self, gesture, start_x, start_y):
        """Handle start of drag - either pan or node move."""
        clicked_node = self._find_node_at(start_x, start_y)

        if clicked_node and not self.editing_node:
            # Don't commit to drag yet; wait for threshold
            self._drag_pending_node = clicked_node
            self._drag_exceeded_threshold = False
            self.dragging_node = None
            self.drag_start_node_x = clicked_node.x
            self.drag_start_node_y = clicked_node.y
            self.is_panning = False
            self.select_node(clicked_node)
        else:
            self._drag_pending_node = None
            self._drag_exceeded_threshold = False
            self.dragging_node = None
            self.is_panning = True
            self.pan_start_x = self.pan_x
            self.pan_start_y = self.pan_y

    def _on_drag_update(self, gesture, offset_x, offset_y):
        """Handle drag movement - either pan or node move."""
        if self._drag_pending_node and not self._drag_exceeded_threshold:
            dist = math.sqrt(offset_x ** 2 + offset_y ** 2)
            if dist >= self._drag_threshold:
                self._drag_exceeded_threshold = True
                self.dragging_node = self._drag_pending_node
            else:
                return  # Below threshold, don't move anything

        if self.dragging_node:
            self.dragging_node.x = self.drag_start_node_x + offset_x / self.zoom
            self.dragging_node.y = self.drag_start_node_y + offset_y / self.zoom
            self.queue_draw()
        elif self.is_panning:
            self.pan_x = self.pan_start_x + offset_x
            self.pan_y = self.pan_start_y + offset_y
            self.queue_draw()

    def _on_drag_end(self, gesture, offset_x, offset_y):
        """Handle end of drag."""
        # If threshold was never exceeded, treat as a click (no position save)
        if self._drag_pending_node and not self._drag_exceeded_threshold:
            self._drag_pending_node = None
            self.dragging_node = None
            self.is_panning = False
            return

        self._drag_pending_node = None

        if self.dragging_node:
            node = self.dragging_node.node
            
            # Check if dropped on another node (for reparenting)
            drop_x = self.drag_start_node_x + offset_x / self.zoom + self.dragging_node.width / 2
            drop_y = self.drag_start_node_y + offset_y / self.zoom + self.dragging_node.height / 2
            
            # Find node at drop position (excluding the dragged node)
            target_node = None
            for rendered in self.rendered_nodes:
                if rendered.node.id == node.id:
                    continue
                if (rendered.x <= drop_x <= rendered.x + rendered.width and
                    rendered.y <= drop_y <= rendered.y + rendered.height):
                    target_node = rendered
                    break
            
            if target_node and node.parent_id is not None:
                # Check we're not dropping on a descendant
                if not self._is_descendant(target_node.node.id, node.id):
                    # Reparent the node
                    old_parent_id = node.parent_id
                    old_sort_order = node.sort_order
                    new_parent_id = target_node.node.id
                    new_sort_order = (
                        max((n.sort_order for n in self.nodes if n.parent_id == new_parent_id and n.id != node.id), default=-1)
                        + 1
                    )
                    
                    node.parent_id = new_parent_id
                    node.sort_order = new_sort_order
                    if self.auto_layout:
                        node.position_x = None  # Reset position for auto-layout
                        node.position_y = None
                    else:
                        # Manual mode: drop near the target without overlaps.
                        desired_x = target_node.x + target_node.width + self.HORIZONTAL_SPACING
                        desired_y = target_node.y
                        x, y = self._find_non_overlapping_position(
                            desired_x,
                            desired_y,
                            self.dragging_node.width,
                            self.dragging_node.height,
                            exclude_node_id=node.id,
                            padding=10.0,
                        )
                        node.position_x = x
                        node.position_y = y
                        self.dragging_node.x = x
                        self.dragging_node.y = y
                    self.db.update_node(node)
                    
                    # Push undo action
                    self.undo_manager.push(UndoAction(
                        action_type=ActionType.NODE_MOVE,
                        description="Move node",
                        data={"node_id": node.id, "parent_id": old_parent_id, "sort_order": old_sort_order},
                        redo_data={"node_id": node.id, "parent_id": new_parent_id, "sort_order": new_sort_order}
                    ))
                    
                    # Reload layout
                    self.nodes = self.db.get_nodes_for_map(self.current_map.id)
                    self._calculate_layout()
                    
                    if self.on_structure_changed:
                        self.on_structure_changed()
            else:
                # Just save node position (manual positioning)
                x, y = self._find_non_overlapping_position(
                    self.dragging_node.x,
                    self.dragging_node.y,
                    self.dragging_node.width,
                    self.dragging_node.height,
                    exclude_node_id=node.id,
                    padding=10.0,
                )
                self.dragging_node.x = x
                self.dragging_node.y = y
                node.position_x = x
                node.position_y = y
                self.db.update_node(node)
                
                # Disable auto-layout since user manually positioned
                if self.auto_layout and self.current_map:
                    self.auto_layout = False
                    self.current_map.settings.auto_layout = False
                    self.db.update_map(self.current_map)
            
            self.dragging_node = None
        
        self.is_panning = False
        self._save_view_state()
        self.queue_draw()
    
    def _is_descendant(self, node_id: int, potential_ancestor_id: int) -> bool:
        """Check if node_id is a descendant of potential_ancestor_id."""
        for n in self.nodes:
            if n.id == node_id:
                if n.parent_id == potential_ancestor_id:
                    return True
                if n.parent_id:
                    return self._is_descendant(n.parent_id, potential_ancestor_id)
        return False
    
    def _on_key_pressed(self, controller, keyval, keycode, state):
        """Handle keyboard input."""
        ctrl = state & Gdk.ModifierType.CONTROL_MASK
        shift = state & Gdk.ModifierType.SHIFT_MASK
        
        # Editing mode
        if self.editing_node:
            return self._handle_edit_key(keyval, keycode, state)
        
        # Navigation and commands
        if keyval == Gdk.KEY_Tab:
            # Create child node
            if self.selected_node:
                self.create_child_node()
            return True
        
        elif keyval == Gdk.KEY_Return and not ctrl:
            # Create sibling node
            if self.selected_node:
                self.create_sibling_node()
            return True
        
        elif keyval == Gdk.KEY_Delete or keyval == Gdk.KEY_BackSpace:
            # Delete node
            if self.selected_node and self.selected_node.node.parent_id is not None:
                self.delete_selected_node()
            return True
        
        elif keyval == Gdk.KEY_F2:
            # Start editing
            if self.selected_node:
                self.start_editing(self.selected_node)
            return True
        
        elif keyval == Gdk.KEY_space and ctrl:
            # Toggle collapse
            if self.selected_node:
                self.toggle_collapse()
            return True
        
        # Arrow key navigation
        elif keyval == Gdk.KEY_Up:
            self.navigate_up()
            return True
        elif keyval == Gdk.KEY_Down:
            self.navigate_down()
            return True
        elif keyval == Gdk.KEY_Left:
            self.navigate_left()
            return True
        elif keyval == Gdk.KEY_Right:
            self.navigate_right()
            return True
        
        # Undo/Redo
        elif keyval == Gdk.KEY_z and ctrl and not shift:
            self.undo()
            return True
        elif keyval == Gdk.KEY_z and ctrl and shift:
            self.redo()
            return True
        elif keyval == Gdk.KEY_y and ctrl:
            self.redo()
            return True
        elif keyval == Gdk.KEY_r and ctrl:
            self.redo()
            return True
        
        # Copy/Paste
        elif keyval == Gdk.KEY_c and ctrl:
            self.copy_node()
            return True
        elif keyval == Gdk.KEY_v and ctrl:
            self.paste_node()
            return True
        
        # Zoom shortcuts
        elif keyval == Gdk.KEY_plus or keyval == Gdk.KEY_equal:
            if ctrl:
                self.zoom_in()
                return True
        elif keyval == Gdk.KEY_minus:
            if ctrl:
                self.zoom_out()
                return True
        elif keyval == Gdk.KEY_0:
            if ctrl:
                self.zoom_to_fit()
                return True
        elif keyval == Gdk.KEY_1:
            if ctrl:
                self.zoom_to_100()
                return True
        
        # Start typing to edit (supports Unicode)
        else:
            uc = Gdk.keyval_to_unicode(keyval)
            if uc and chr(uc).isprintable() and not ctrl:
                if self.selected_node:
                    self.start_editing(self.selected_node)
                    self.edit_text = chr(uc)
                    self.edit_cursor_pos = 1
                    self.queue_draw()
                    return True

        return False
    
    def _handle_edit_key(self, keyval, keycode, state) -> bool:
        """Handle keyboard input during editing."""
        ctrl = state & Gdk.ModifierType.CONTROL_MASK
        
        if keyval == Gdk.KEY_Return:
            self.commit_edit()
            return True
        
        elif keyval == Gdk.KEY_Escape:
            self.cancel_edit()
            return True
        
        elif keyval == Gdk.KEY_BackSpace:
            if self.edit_selection_start is not None:
                # Delete selection
                self._delete_selection()
            elif self.edit_cursor_pos > 0:
                self.edit_text = self.edit_text[:self.edit_cursor_pos-1] + self.edit_text[self.edit_cursor_pos:]
                self.edit_cursor_pos -= 1
            self.queue_draw()
            return True
        
        elif keyval == Gdk.KEY_Delete:
            if self.edit_selection_start is not None:
                # Delete selection
                self._delete_selection()
            elif self.edit_cursor_pos < len(self.edit_text):
                self.edit_text = self.edit_text[:self.edit_cursor_pos] + self.edit_text[self.edit_cursor_pos+1:]
            self.queue_draw()
            return True
        
        elif keyval == Gdk.KEY_Left:
            self.edit_selection_start = None
            if self.edit_cursor_pos > 0:
                self.edit_cursor_pos -= 1
            self.queue_draw()
            return True
        
        elif keyval == Gdk.KEY_Right:
            self.edit_selection_start = None
            if self.edit_cursor_pos < len(self.edit_text):
                self.edit_cursor_pos += 1
            self.queue_draw()
            return True
        
        elif keyval == Gdk.KEY_Home:
            self.edit_selection_start = None
            self.edit_cursor_pos = 0
            self.queue_draw()
            return True
        
        elif keyval == Gdk.KEY_End:
            self.edit_selection_start = None
            self.edit_cursor_pos = len(self.edit_text)
            self.queue_draw()
            return True
        
        elif keyval == Gdk.KEY_a and ctrl:
            # Select all
            self.edit_selection_start = 0
            self.edit_cursor_pos = len(self.edit_text)
            self.queue_draw()
            return True
        
        else:
            # Insert printable character (supports Unicode)
            uc = Gdk.keyval_to_unicode(keyval)
            if uc and chr(uc).isprintable():
                char = chr(uc)
                if self.edit_selection_start is not None:
                    self._delete_selection()
                if self.is_placeholder_text:
                    self.edit_text = char
                    self.edit_cursor_pos = 1
                    self.is_placeholder_text = False
                else:
                    self.edit_text = self.edit_text[:self.edit_cursor_pos] + char + self.edit_text[self.edit_cursor_pos:]
                    self.edit_cursor_pos += 1
                self.queue_draw()
                return True

        return False
    
    def select_node(self, rendered: Optional[RenderedNode]):
        """Select a node."""
        self.selected_node = rendered
        self.queue_draw()
        
        if self.on_node_selected:
            self.on_node_selected(rendered.node if rendered else None)
    
    def start_editing(self, rendered: RenderedNode):
        """Start editing a node's text."""
        self.editing_node = rendered
        self.edit_text = rendered.node.text
        self.edit_cursor_pos = len(self.edit_text)
        self.edit_selection_start = None
        self.cursor_visible = True
        
        # Start cursor blink
        if self.cursor_blink_id:
            GLib.source_remove(self.cursor_blink_id)
        self.cursor_blink_id = GLib.timeout_add(530, self._blink_cursor)
        
        self.queue_draw()
    
    def start_editing_select_all(self, rendered: RenderedNode):
        """Start editing a node's text with all text selected."""
        self.editing_node = rendered
        self.edit_text = rendered.node.text
        self.edit_cursor_pos = len(self.edit_text)
        self.edit_selection_start = 0  # Select from start
        self.cursor_visible = True
        
        # Start cursor blink
        if self.cursor_blink_id:
            GLib.source_remove(self.cursor_blink_id)
        self.cursor_blink_id = GLib.timeout_add(530, self._blink_cursor)
        
        self.queue_draw()
    
    def _blink_cursor(self) -> bool:
        """Toggle cursor visibility."""
        if self.editing_node:
            self.cursor_visible = not self.cursor_visible
            self.queue_draw()
            return True
        return False
    
    def commit_edit(self):
        """Commit the current edit."""
        if self.editing_node and self.edit_text.strip():
            node = self.editing_node.node
            old_text = node.text
            new_text = self.edit_text.strip()

            if new_text != old_text:
                node.text = new_text
                self.db.update_node(node)

                # Push undo action
                self.undo_manager.push(UndoAction(
                    action_type=ActionType.NODE_EDIT,
                    description="Edit node text",
                    data={"node_id": node.id, "text": old_text},
                    redo_data={"node_id": node.id, "text": new_text}
                ))

                if self.on_node_edited:
                    self.on_node_edited(node, node.text)
        
        self._stop_editing()
        self._calculate_layout()
        self.queue_draw()
    
    def cancel_edit(self):
        """Cancel the current edit."""
        self._stop_editing()
        self.queue_draw()
    
    def _stop_editing(self):
        """Stop editing mode."""
        self.editing_node = None
        self.edit_text = ""
        self.edit_cursor_pos = 0
        self.edit_selection_start = None
        self.is_placeholder_text = False
        
        if self.cursor_blink_id:
            GLib.source_remove(self.cursor_blink_id)
            self.cursor_blink_id = None
    
    def _delete_selection(self):
        """Delete the selected text."""
        if self.edit_selection_start is None:
            return
        start = min(self.edit_selection_start, self.edit_cursor_pos)
        end = max(self.edit_selection_start, self.edit_cursor_pos)
        self.edit_text = self.edit_text[:start] + self.edit_text[end:]
        self.edit_cursor_pos = start
        self.edit_selection_start = None
    
    def create_child_node(self):
        """Create a child node of the selected node."""
        if not self.selected_node or not self.current_map:
            return
        
        parent = self.selected_node.node
        new_node = self.db.create_node(
            map_id=self.current_map.id,
            parent_id=parent.id,
            text="New Topic"
        )
        
        # Push undo action
        self.undo_manager.push(UndoAction(
            action_type=ActionType.NODE_CREATE,
            description="Create child node",
            data={
                "node_id": new_node.id,
                "map_id": self.current_map.id,
                "parent_id": parent.id,
                "text": new_node.text,
                "sort_order": new_node.sort_order,
                "position_x": new_node.position_x,
                "position_y": new_node.position_y,
                "is_collapsed": new_node.is_collapsed,
                "style": new_node.style.to_json(),
            },
            redo_data={
                "node_id": new_node.id,
                "map_id": self.current_map.id,
                "parent_id": parent.id,
                "text": new_node.text,
                "sort_order": new_node.sort_order,
                "position_x": new_node.position_x,
                "position_y": new_node.position_y,
                "is_collapsed": new_node.is_collapsed,
                "style": new_node.style.to_json(),
            }
        ))
        
        # Reload and select new node
        self.nodes = self.db.get_nodes_for_map(self.current_map.id)
        self._calculate_layout()
        
        # Find and select new node
        for rendered in self.rendered_nodes:
            if rendered.node.id == new_node.id:
                self.select_node(rendered)
                # In manual mode, assign a non-overlapping saved position so it
                # doesn't collide with nearby nodes.
                if not self.auto_layout:
                    x, y = self._find_non_overlapping_position(
                        rendered.x,
                        rendered.y,
                        rendered.width,
                        rendered.height,
                        exclude_node_id=rendered.node.id,
                        padding=10.0,
                    )
                    rendered.x = x
                    rendered.y = y
                    rendered.node.position_x = x
                    rendered.node.position_y = y
                    self.db.update_node(rendered.node)
                self.start_editing_placeholder(rendered)
                break
        
        self.queue_draw()
        
        if self.on_structure_changed:
            self.on_structure_changed()
    
    def create_sibling_node(self):
        """Create a sibling node of the selected node."""
        if not self.selected_node or not self.current_map:
            return
        
        selected = self.selected_node.node
        
        # Can't create sibling of root
        if selected.parent_id is None:
            return
        
        new_node = self.db.create_node(
            map_id=self.current_map.id,
            parent_id=selected.parent_id,
            text="New Topic",
            after_node_id=selected.id
        )
        
        # Push undo action
        self.undo_manager.push(UndoAction(
            action_type=ActionType.NODE_CREATE,
            description="Create sibling node",
            data={
                "node_id": new_node.id,
                "map_id": self.current_map.id,
                "parent_id": selected.parent_id,
                "text": new_node.text,
                "sort_order": new_node.sort_order,
                "position_x": new_node.position_x,
                "position_y": new_node.position_y,
                "is_collapsed": new_node.is_collapsed,
                "style": new_node.style.to_json(),
            },
            redo_data={
                "node_id": new_node.id,
                "map_id": self.current_map.id,
                "parent_id": selected.parent_id,
                "text": new_node.text,
                "sort_order": new_node.sort_order,
                "position_x": new_node.position_x,
                "position_y": new_node.position_y,
                "is_collapsed": new_node.is_collapsed,
                "style": new_node.style.to_json(),
            }
        ))
        
        # Reload and select new node
        self.nodes = self.db.get_nodes_for_map(self.current_map.id)
        self._calculate_layout()
        
        # Find and select new node
        for rendered in self.rendered_nodes:
            if rendered.node.id == new_node.id:
                self.select_node(rendered)
                if not self.auto_layout:
                    x, y = self._find_non_overlapping_position(
                        rendered.x,
                        rendered.y,
                        rendered.width,
                        rendered.height,
                        exclude_node_id=rendered.node.id,
                        padding=10.0,
                    )
                    rendered.x = x
                    rendered.y = y
                    rendered.node.position_x = x
                    rendered.node.position_y = y
                    self.db.update_node(rendered.node)
                self.start_editing_placeholder(rendered)
                break
        
        self.queue_draw()
        
        if self.on_structure_changed:
            self.on_structure_changed()
    
    def _collect_subtree_for_undo(self, node: Node) -> List[dict]:
        """Collect an entire subtree as serialisable dicts for undo storage."""
        result = []
        children = [n for n in self.nodes if n.parent_id == node.id]
        children.sort(key=lambda n: n.sort_order)
        for child in children:
            result.append({
                "node_id": child.id,
                "map_id": child.map_id,
                "parent_id": child.parent_id,
                "text": child.text,
                "sort_order": child.sort_order,
                "position_x": child.position_x,
                "position_y": child.position_y,
                "is_collapsed": child.is_collapsed,
                "style": child.style.to_json(),
            })
            result.extend(self._collect_subtree_for_undo(child))
        return result

    def _restore_children_recursive(self, children_data: List[dict]):
        """Restore children from undo data, in order so parents exist first."""
        for cdata in children_data:
            child_node = Node(
                id=cdata["node_id"],
                map_id=cdata["map_id"],
                parent_id=cdata["parent_id"],
                text=cdata["text"],
                sort_order=cdata.get("sort_order", 0),
                position_x=cdata.get("position_x"),
                position_y=cdata.get("position_y"),
                is_collapsed=bool(cdata.get("is_collapsed", False)),
                style=NodeStyle.from_json(cdata.get("style")),
            )
            self.db.restore_node(child_node)

    def delete_selected_node(self):
        """Delete the selected node."""
        if not self.selected_node or not self.current_map:
            return

        node = self.selected_node.node

        # Can't delete root
        if node.parent_id is None:
            return

        # Capture entire subtree before deleting
        children_data = self._collect_subtree_for_undo(node)

        parent_id = node.parent_id
        self.undo_manager.push(UndoAction(
            action_type=ActionType.NODE_DELETE,
            description="Delete node",
            data={
                "node_id": node.id,
                "map_id": node.map_id,
                "parent_id": node.parent_id,
                "text": node.text,
                "sort_order": node.sort_order,
                "position_x": node.position_x,
                "position_y": node.position_y,
                "is_collapsed": node.is_collapsed,
                "style": node.style.to_json(),
                "children_data": children_data,
            },
            redo_data={"node_id": node.id}
        ))

        self.db.delete_node(node.id)

        # Reload
        self.nodes = self.db.get_nodes_for_map(self.current_map.id)
        self._calculate_layout()

        # Select parent
        for rendered in self.rendered_nodes:
            if rendered.node.id == parent_id:
                self.select_node(rendered)
                break
        else:
            self.select_node(None)

        self.queue_draw()

        if self.on_structure_changed:
            self.on_structure_changed()
    
    def toggle_collapse(self):
        """Toggle collapse state of selected node."""
        if not self.selected_node:
            return
        
        node = self.selected_node.node
        node.is_collapsed = not node.is_collapsed
        self.db.update_node(node)
        
        # Reload layout
        self.nodes = self.db.get_nodes_for_map(self.current_map.id)
        self._calculate_layout()
        self.queue_draw()
    
    def navigate_up(self):
        """Navigate to previous sibling or parent."""
        if not self.selected_node:
            if self.root_rendered:
                self.select_node(self.root_rendered)
            return
        
        node = self.selected_node.node
        if node.parent_id is None:
            return
        
        # Find siblings
        siblings = [n for n in self.rendered_nodes if n.node.parent_id == node.parent_id]
        siblings.sort(key=lambda n: n.node.sort_order)
        
        idx = next((i for i, n in enumerate(siblings) if n.node.id == node.id), -1)
        if idx > 0:
            self.select_node(siblings[idx - 1])
    
    def navigate_down(self):
        """Navigate to next sibling."""
        if not self.selected_node:
            if self.root_rendered:
                self.select_node(self.root_rendered)
            return
        
        node = self.selected_node.node
        if node.parent_id is None:
            # If at root, go to first child
            children = [n for n in self.rendered_nodes if n.node.parent_id == node.id]
            if children:
                children.sort(key=lambda n: n.node.sort_order)
                self.select_node(children[0])
            return
        
        # Find siblings
        siblings = [n for n in self.rendered_nodes if n.node.parent_id == node.parent_id]
        siblings.sort(key=lambda n: n.node.sort_order)
        
        idx = next((i for i, n in enumerate(siblings) if n.node.id == node.id), -1)
        if idx < len(siblings) - 1:
            self.select_node(siblings[idx + 1])
    
    def navigate_left(self):
        """Navigate to parent."""
        if not self.selected_node:
            return
        
        node = self.selected_node.node
        if node.parent_id is None:
            return
        
        # Find parent
        for rendered in self.rendered_nodes:
            if rendered.node.id == node.parent_id:
                self.select_node(rendered)
                break
    
    def navigate_right(self):
        """Navigate to first child."""
        if not self.selected_node:
            return
        
        node = self.selected_node.node
        children = [n for n in self.rendered_nodes if n.node.parent_id == node.id]
        
        if children:
            children.sort(key=lambda n: n.node.sort_order)
            self.select_node(children[0])
    
    def zoom_in(self):
        """Increase zoom level."""
        self.zoom = min(4.0, self.zoom * 1.2)
        self._save_view_state()
        self.queue_draw()
    
    def zoom_out(self):
        """Decrease zoom level."""
        self.zoom = max(0.25, self.zoom / 1.2)
        self._save_view_state()
        self.queue_draw()
    
    def zoom_to_fit(self):
        """Zoom to fit all nodes."""
        if not self.rendered_nodes:
            return
        
        width = self.get_width()
        height = self.get_height()
        
        min_x = min(n.x for n in self.rendered_nodes)
        max_x = max(n.x + n.width for n in self.rendered_nodes)
        min_y = min(n.y for n in self.rendered_nodes)
        max_y = max(n.y + n.height for n in self.rendered_nodes)
        
        map_width = max_x - min_x + 100
        map_height = max_y - min_y + 100
        
        self.zoom = min(
            (width - 40) / map_width,
            (height - 40) / map_height,
            1.0  # Don't zoom in beyond 100%
        )
        
        # Center
        center_x = (min_x + max_x) / 2
        center_y = (min_y + max_y) / 2
        
        self.pan_x = width / 2 - center_x * self.zoom
        self.pan_y = height / 2 - center_y * self.zoom
        
        self._save_view_state()
        self.queue_draw()
    
    def zoom_to_100(self):
        """Reset zoom to 100%."""
        self.zoom = 1.0
        self._save_view_state()
        self.queue_draw()
    
    def center_view(self):
        """Center the view on the root node."""
        if not self.root_rendered:
            return
        
        width = self.get_width()
        height = self.get_height()
        
        root = self.root_rendered
        center_x = root.x + root.width / 2
        center_y = root.y + root.height / 2
        
        self.pan_x = width / 2 - center_x * self.zoom
        self.pan_y = height / 2 - center_y * self.zoom
        
        self._save_view_state()
        self.queue_draw()
    
    def _persist_rendered_positions(self):
        """Save all current rendered positions to the database.

        Called after layout calculation in manual mode so that positions
        survive an app restart without being recalculated.
        """
        if not self.current_map:
            return
        for rn in self.rendered_nodes:
            node = rn.node
            if node.position_x != rn.x or node.position_y != rn.y:
                node.position_x = rn.x
                node.position_y = rn.y
                self.db.update_node(node)

    def get_node_positions(self) -> dict:
        """Return current rendered positions as {node_id: (x, y, w, h)}.

        Used by the exporter for WYSIWYG export.
        """
        return {
            rn.node.id: (rn.x, rn.y, rn.width, rn.height)
            for rn in self.rendered_nodes
        }

    def _save_view_state(self):
        """Save current view state to database."""
        if self.current_map:
            self.current_map.settings.zoom_level = self.zoom
            self.current_map.settings.pan_x = self.pan_x
            self.current_map.settings.pan_y = self.pan_y
            self.current_map.settings.layout_mode = self.layout_mode
            self.db.update_map(self.current_map)
    
    def set_node_priority(self, priority: Optional[str]):
        """Set priority for selected node."""
        if not self.selected_node:
            return

        node = self.selected_node.node
        old_style = node.style.to_json()
        node.style.priority = priority
        self.db.update_node(node)

        self.undo_manager.push(UndoAction(
            action_type=ActionType.NODE_STYLE,
            description="Change priority",
            data={"node_id": node.id, "style": old_style},
            redo_data={"node_id": node.id, "style": node.style.to_json()}
        ))
        self.queue_draw()

    def set_node_status(self, status: Optional[str]):
        """Set status for selected node."""
        if not self.selected_node:
            return

        node = self.selected_node.node
        old_style = node.style.to_json()
        node.style.status = status
        self.db.update_node(node)

        self.undo_manager.push(UndoAction(
            action_type=ActionType.NODE_STYLE,
            description="Change status",
            data={"node_id": node.id, "style": old_style},
            redo_data={"node_id": node.id, "style": node.style.to_json()}
        ))
        self.queue_draw()

    def set_node_color(self, color: Optional[str]):
        """Set custom color for selected node."""
        if not self.selected_node:
            return

        node = self.selected_node.node
        old_style = node.style.to_json()
        node.style.color = color
        self.db.update_node(node)

        self.undo_manager.push(UndoAction(
            action_type=ActionType.NODE_STYLE,
            description="Change color",
            data={"node_id": node.id, "style": old_style},
            redo_data={"node_id": node.id, "style": node.style.to_json()}
        ))
        self.queue_draw()
    
    def toggle_grid(self):
        """Toggle grid visibility."""
        self.show_grid = not self.show_grid
        if self.current_map:
            self.current_map.settings.show_grid = self.show_grid
            self.db.update_map(self.current_map)
        self.queue_draw()
    
    def toggle_minimap(self):
        """Toggle minimap visibility."""
        self.show_minimap = not self.show_minimap
        if self.current_map:
            self.current_map.settings.show_minimap = self.show_minimap
            self.db.update_map(self.current_map)
        self.queue_draw()
    
    def toggle_auto_layout(self):
        """Toggle auto-layout."""
        self.auto_layout = not self.auto_layout
        if self.current_map:
            self.current_map.settings.auto_layout = self.auto_layout
            self.db.update_map(self.current_map)
        self._calculate_layout()
        self.queue_draw()
    
    # ==================== Right-Click Context Menu ====================
    
    def _on_right_click(self, gesture, n_press, x, y):
        """Handle right-click for context menu."""
        clicked_node = self._find_node_at(x, y)
        
        # Create popover menu
        menu = Gio.Menu()
        
        if self.moving_node:
            # We're in move mode - show "Move Here" option
            if clicked_node:
                menu.append("Move Here", "canvas.move-here")
            menu.append("Cancel Move", "canvas.cancel-move")
        elif clicked_node:
            # Clicked on a node
            self.select_node(clicked_node)
            menu.append("Edit", "canvas.edit-node")
            menu.append("Add Subtopic", "canvas.add-child")
            if clicked_node.node.parent_id is not None:
                menu.append("Add Sibling", "canvas.add-sibling")
                menu.append("Move To...", "canvas.start-move")
                menu.append("Delete", "canvas.delete-node")
            menu.append("Copy", "canvas.copy-node")
            if self.clipboard_node:
                menu.append("Paste as Child", "canvas.paste-node")
        else:
            # Clicked on empty canvas
            menu.append("Add Topic", "canvas.add-floating")
            if self.clipboard_node:
                menu.append("Paste", "canvas.paste-floating")
        
        # Create and setup actions
        action_group = Gio.SimpleActionGroup()
        
        edit_action = Gio.SimpleAction.new("edit-node", None)
        edit_action.connect("activate", lambda a, p: self.start_editing(self.selected_node) if self.selected_node else None)
        action_group.add_action(edit_action)
        
        add_child_action = Gio.SimpleAction.new("add-child", None)
        add_child_action.connect("activate", lambda a, p: self.create_child_node())
        action_group.add_action(add_child_action)
        
        add_sibling_action = Gio.SimpleAction.new("add-sibling", None)
        add_sibling_action.connect("activate", lambda a, p: self.create_sibling_node())
        action_group.add_action(add_sibling_action)
        
        delete_action = Gio.SimpleAction.new("delete-node", None)
        delete_action.connect("activate", lambda a, p: self.delete_selected_node())
        action_group.add_action(delete_action)
        
        copy_action = Gio.SimpleAction.new("copy-node", None)
        copy_action.connect("activate", lambda a, p: self.copy_node())
        action_group.add_action(copy_action)
        
        paste_action = Gio.SimpleAction.new("paste-node", None)
        paste_action.connect("activate", lambda a, p: self.paste_node())
        action_group.add_action(paste_action)
        
        paste_floating_action = Gio.SimpleAction.new("paste-floating", None)
        paste_floating_action.connect("activate", lambda a, p: self.paste_node_floating(x, y))
        action_group.add_action(paste_floating_action)
        
        add_floating_action = Gio.SimpleAction.new("add-floating", None)
        add_floating_action.connect("activate", lambda a, p: self.create_floating_topic(x, y))
        action_group.add_action(add_floating_action)
        
        start_move_action = Gio.SimpleAction.new("start-move", None)
        start_move_action.connect("activate", lambda a, p: self.start_move_node())
        action_group.add_action(start_move_action)
        
        move_here_action = Gio.SimpleAction.new("move-here", None)
        move_here_action.connect("activate", lambda a, p: self.complete_move_node(clicked_node))
        action_group.add_action(move_here_action)
        
        cancel_move_action = Gio.SimpleAction.new("cancel-move", None)
        cancel_move_action.connect("activate", lambda a, p: self.cancel_move_node())
        action_group.add_action(cancel_move_action)
        
        self.insert_action_group("canvas", action_group)
        
        # Unparent previous popover if still attached
        if self._context_popover is not None:
            self._context_popover.unparent()
            self._context_popover = None

        # Create popover positioned at click location
        popover = Gtk.PopoverMenu.new_from_model(menu)
        popover.set_parent(self)
        popover.set_has_arrow(True)

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

        rect = Gdk.Rectangle()
        rect.x = int(x)
        rect.y = int(y)
        rect.width = 1
        rect.height = 1
        popover.set_pointing_to(rect)
        popover.popup()
    
    # ==================== Undo/Redo ====================
    
    def undo(self):
        """Undo the last action."""
        action = self.undo_manager.undo()
        if not action:
            return
        
        self._apply_undo_action(action, is_undo=True)
    
    def redo(self):
        """Redo the last undone action."""
        action = self.undo_manager.redo()
        if not action:
            return
        
        self._apply_undo_action(action, is_undo=False)
    
    def _apply_undo_action(self, action: UndoAction, is_undo: bool):
        """Apply an undo or redo action."""
        data = action.data if is_undo else action.redo_data
        
        if action.action_type == ActionType.NODE_CREATE:
            if is_undo:
                # Delete the created node
                self.db.delete_node(data["node_id"])
            else:
                # Recreate the node (prefer restoring the same ID)
                if "sort_order" in data:
                    node = Node(
                        id=data["node_id"],
                        map_id=data["map_id"],
                        parent_id=data.get("parent_id"),
                        text=data.get("text", "New Topic"),
                        position_x=data.get("position_x"),
                        position_y=data.get("position_y"),
                        is_collapsed=bool(data.get("is_collapsed", False)),
                        sort_order=int(data.get("sort_order", 0)),
                        style=NodeStyle.from_json(data.get("style")),
                    )
                    self.db.restore_node(node)
                else:
                    # Back-compat for older in-memory actions
                    self.db.create_node(
                        map_id=data["map_id"],
                        parent_id=data.get("parent_id"),
                        text=data.get("text", "New Topic")
                    )
        
        elif action.action_type == ActionType.NODE_DELETE:
            if is_undo:
                # Restore the deleted node
                node = Node(
                    id=data["node_id"],
                    map_id=data["map_id"],
                    parent_id=data["parent_id"],
                    text=data["text"],
                    position_x=data.get("position_x"),
                    position_y=data.get("position_y"),
                    is_collapsed=bool(data.get("is_collapsed", False)),
                    sort_order=data.get("sort_order", 0),
                    style=NodeStyle.from_json(data.get("style")),
                )
                self.db.restore_node(node)
                # Restore children if they were captured
                children_data = data.get("children_data", [])
                if children_data:
                    self._restore_children_recursive(children_data)
            else:
                # Delete again
                self.db.delete_node(data["node_id"])
        
        elif action.action_type == ActionType.NODE_EDIT:
            # Update text
            node = self.db.get_node(data["node_id"])
            if node:
                node.text = data["text"]
                self.db.update_node(node)
        
        elif action.action_type == ActionType.NODE_MOVE:
            # Move node to previous parent
            node = self.db.get_node(data["node_id"])
            if node:
                node.parent_id = data["parent_id"]
                node.sort_order = data["sort_order"]
                self.db.update_node(node)

        elif action.action_type == ActionType.NODE_STYLE:
            # Restore node style
            node = self.db.get_node(data["node_id"])
            if node:
                node.style = NodeStyle.from_json(data.get("style"))
                self.db.update_node(node)

        elif action.action_type == ActionType.MAP_LAYOUT:
            # Restore/apply per-node positions and auto_layout flag.
            map_id = data.get("map_id")
            if self.current_map and map_id == self.current_map.id:
                self.auto_layout = bool(data.get("auto_layout", False))
                self.current_map.settings.auto_layout = self.auto_layout
                self.db.update_map(self.current_map)

            for p in data.get("positions", []):
                node = self.db.get_node(p.get("node_id"))
                if not node:
                    continue
                node.position_x = p.get("position_x")
                node.position_y = p.get("position_y")
                self.db.update_node(node)
        
        # Reload and redraw
        if self.current_map:
            self.nodes = self.db.get_nodes_for_map(self.current_map.id)
            self._calculate_layout()
            self.queue_draw()
            
            if self.on_structure_changed:
                self.on_structure_changed()
    
    # ==================== Copy/Paste ====================
    
    def _collect_subtree(self, root_node: Node) -> List[Node]:
        """Recursively collect a node and all its descendants."""
        result = [root_node]
        children = [n for n in self.nodes if n.parent_id == root_node.id]
        for child in children:
            result.extend(self._collect_subtree(child))
        return result

    def copy_node(self):
        """Copy the selected node and its entire subtree to clipboard."""
        if not self.selected_node:
            return

        self.clipboard_node = self.selected_node.node
        self.clipboard_children = self._collect_subtree(self.clipboard_node)

    def paste_node(self):
        """Paste clipboard node as child of selected node."""
        if not self.clipboard_node or not self.current_map:
            return

        parent_id = self.selected_node.node.id if self.selected_node else None
        self._paste_node_tree(self.clipboard_node, parent_id)

    def paste_node_floating(self, x: float, y: float):
        """Paste clipboard node at a specific position (disconnected)."""
        if not self.clipboard_node or not self.current_map:
            return

        # Create as child of root if no selection
        if self.root_rendered:
            parent_id = self.root_rendered.node.id
        else:
            parent_id = None

        self._paste_node_tree(self.clipboard_node, parent_id)

    def _paste_node_tree(self, source_node: Node, parent_id: Optional[int]):
        """Recursively paste a node and its entire subtree with ID remapping."""
        id_map: Dict[int, int] = {}

        def paste_recursive(src: Node, new_parent_id: Optional[int]):
            new_node = self.db.create_node(
                map_id=self.current_map.id,
                parent_id=new_parent_id,
                text=src.text + (" (copy)" if src.id == source_node.id else "")
            )
            # Copy style
            new_node.style = NodeStyle.from_json(src.style.to_json())
            self.db.update_node(new_node)
            id_map[src.id] = new_node.id

            # Recurse into children from clipboard
            children = [n for n in self.clipboard_children if n.parent_id == src.id]
            children.sort(key=lambda n: n.sort_order)
            for child in children:
                paste_recursive(child, new_node.id)

        paste_recursive(source_node, parent_id)

        # Reload
        self.nodes = self.db.get_nodes_for_map(self.current_map.id)
        self._calculate_layout()
        self.queue_draw()

        if self.on_structure_changed:
            self.on_structure_changed()
    
    # ==================== Move Node ====================
    
    def start_move_node(self):
        """Start moving the selected node."""
        if self.selected_node and self.selected_node.node.parent_id is not None:
            self.moving_node = self.selected_node.node
    
    def complete_move_node(self, target_rendered: Optional[RenderedNode]):
        """Complete moving node to new parent."""
        if not self.moving_node or not target_rendered or not self.current_map:
            self.cancel_move_node()
            return
        
        target_node = target_rendered.node
        
        # Prevent moving to self or descendant
        if target_node.id == self.moving_node.id:
            self.cancel_move_node()
            return
        
        # Check if target is a descendant
        def is_descendant(node_id: int, potential_ancestor_id: int) -> bool:
            for n in self.nodes:
                if n.id == node_id and n.parent_id == potential_ancestor_id:
                    return True
                if n.id == node_id and n.parent_id:
                    return is_descendant(n.parent_id, potential_ancestor_id)
            return False
        
        if is_descendant(target_node.id, self.moving_node.id):
            self.cancel_move_node()
            return
        
        # Save for undo
        old_parent_id = self.moving_node.parent_id
        old_sort_order = self.moving_node.sort_order
        new_parent_id = target_node.id
        new_sort_order = (
            max((n.sort_order for n in self.nodes if n.parent_id == new_parent_id and n.id != self.moving_node.id), default=-1)
            + 1
        )
        
        # Move the node
        self.moving_node.parent_id = new_parent_id
        self.moving_node.sort_order = new_sort_order
        self.db.update_node(self.moving_node)
        
        # Push undo action
        self.undo_manager.push(UndoAction(
            action_type=ActionType.NODE_MOVE,
            description="Move node",
            data={"node_id": self.moving_node.id, "parent_id": old_parent_id, "sort_order": old_sort_order},
            redo_data={"node_id": self.moving_node.id, "parent_id": new_parent_id, "sort_order": new_sort_order}
        ))
        
        self.moving_node = None
        
        # Reload
        self.nodes = self.db.get_nodes_for_map(self.current_map.id)
        self._calculate_layout()
        self.queue_draw()
        
        if self.on_structure_changed:
            self.on_structure_changed()
    
    def cancel_move_node(self):
        """Cancel node move operation."""
        self.moving_node = None
    
    # ==================== Floating Topic ====================
    
    def create_floating_topic(self, x: float, y: float):
        """Create a new topic at the clicked position."""
        if not self.current_map or not self.root_rendered:
            return
        
        # Create as child of root
        new_node = self.db.create_node(
            map_id=self.current_map.id,
            parent_id=self.root_rendered.node.id,
            text="New Topic"
        )
        
        # Reload and select
        self.nodes = self.db.get_nodes_for_map(self.current_map.id)
        self._calculate_layout()
        
        for rendered in self.rendered_nodes:
            if rendered.node.id == new_node.id:
                self.select_node(rendered)
                self.start_editing_placeholder(rendered)
                break
        
        self.queue_draw()
        
        if self.on_structure_changed:
            self.on_structure_changed()
    
    def start_editing_placeholder(self, rendered: RenderedNode):
        """Start editing with placeholder text (greyed, replaced on type)."""
        self.editing_node = rendered
        self.edit_text = rendered.node.text
        self.edit_cursor_pos = len(self.edit_text)
        self.is_placeholder_text = True
        self.cursor_visible = True
        
        if self.cursor_blink_id:
            GLib.source_remove(self.cursor_blink_id)
        self.cursor_blink_id = GLib.timeout_add(530, self._blink_cursor)
        
        self.queue_draw()

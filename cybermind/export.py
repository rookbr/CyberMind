"""Export functionality for CyberMind mindmaps."""

import os
import math
from pathlib import Path
from typing import Optional, List
from datetime import datetime

import gi
gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, GLib

import cairo

from cybermind.database import Database, MindMap, Node, get_data_dir


class MindMapExporter:
    """Handles exporting mindmaps to various formats."""
    
    # Colors matching canvas
    COLORS = {
        'bg_primary': (0.039, 0.039, 0.039),
        'surface': (0.118, 0.118, 0.118),
        'border_subtle': (0.165, 0.165, 0.165),
        'text_primary': (0.878, 0.878, 0.878),
        'accent_primary': (1.0, 0.176, 0.176),
        'accent_secondary': (0.8, 0.0, 0.0),
    }
    
    NODE_PADDING = 16
    NODE_MIN_WIDTH = 120
    NODE_MAX_WIDTH = 300
    ROOT_NODE_MIN_WIDTH = 160
    NODE_HEIGHT = 40
    ROOT_NODE_HEIGHT = 56
    RADIAL_RADIUS_BASE = 200
    RADIAL_RADIUS_INCREMENT = 180
    
    HORIZONTAL_SPACING = 60
    VERTICAL_SPACING = 15

    def __init__(self, db: Database):
        self.db = db
        self.layout_mode: str = "horizontal"
    
    def export_png(self, mind_map: MindMap, filepath: str,
                   scale: float = 2.0, transparent: bool = False,
                   canvas_positions: Optional[dict] = None) -> bool:
        """Export mindmap to PNG image.

        If canvas_positions is provided it is used directly (WYSIWYG),
        otherwise positions are calculated from scratch.
        """
        nodes = self.db.get_nodes_for_map(mind_map.id)
        if not nodes:
            return False

        positions = canvas_positions if canvas_positions else self._calculate_positions(nodes)
        
        if not positions:
            return False
        
        # Calculate bounds
        min_x = min(p[0] for p in positions.values())
        max_x = max(p[0] + p[2] for p in positions.values())
        min_y = min(p[1] for p in positions.values())
        max_y = max(p[1] + p[3] for p in positions.values())
        
        padding = 50
        width = int((max_x - min_x + padding * 2) * scale)
        height = int((max_y - min_y + padding * 2) * scale)
        
        # Create surface
        surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, width, height)
        cr = cairo.Context(surface)
        
        # Scale and translate
        cr.scale(scale, scale)
        cr.translate(-min_x + padding, -min_y + padding)
        
        # Background
        if not transparent:
            cr.set_source_rgb(*self.COLORS['bg_primary'])
            cr.paint()
        
        # Draw connections
        self._draw_connections(cr, nodes, positions)
        
        # Draw nodes
        for node in nodes:
            if node.id in positions:
                self._draw_node(cr, node, positions[node.id])
        
        # Save
        surface.write_to_png(filepath)
        return True
    
    def export_pdf(self, mind_map: MindMap, filepath: str,
                   page_size: str = "A4",
                   canvas_positions: Optional[dict] = None) -> bool:
        """Export mindmap to PDF."""
        nodes = self.db.get_nodes_for_map(mind_map.id)
        if not nodes:
            return False

        positions = canvas_positions if canvas_positions else self._calculate_positions(nodes)
        
        if not positions:
            return False
        
        # Page sizes in points (72 points = 1 inch)
        PAGE_SIZES = {
            "A4": (595, 842),
            "Letter": (612, 792),
            "Auto": None
        }
        
        # Calculate bounds
        min_x = min(p[0] for p in positions.values())
        max_x = max(p[0] + p[2] for p in positions.values())
        min_y = min(p[1] for p in positions.values())
        max_y = max(p[1] + p[3] for p in positions.values())
        
        map_width = max_x - min_x + 100
        map_height = max_y - min_y + 100
        
        if page_size == "Auto":
            width = map_width
            height = map_height
        else:
            width, height = PAGE_SIZES.get(page_size, PAGE_SIZES["A4"])
            # Scale to fit
            scale_x = (width - 40) / map_width
            scale_y = (height - 40) / map_height
            scale = min(scale_x, scale_y, 1.0)
        
        # Create PDF surface
        surface = cairo.PDFSurface(filepath, width, height)
        cr = cairo.Context(surface)
        
        # Set metadata
        surface.set_metadata(cairo.PDF_METADATA_TITLE, mind_map.name)
        surface.set_metadata(cairo.PDF_METADATA_CREATE_DATE, 
                           datetime.now().isoformat())
        
        # Background
        cr.set_source_rgb(*self.COLORS['bg_primary'])
        cr.paint()
        
        # Center and scale
        if page_size != "Auto":
            cr.translate(width / 2, height / 2)
            cr.scale(scale, scale)
            cr.translate(-(min_x + max_x) / 2, -(min_y + max_y) / 2)
        else:
            cr.translate(-min_x + 50, -min_y + 50)
        
        # Draw
        self._draw_connections(cr, nodes, positions)
        for node in nodes:
            if node.id in positions:
                self._draw_node(cr, node, positions[node.id])
        
        surface.finish()
        return True
    
    def export_markdown(self, mind_map: MindMap, filepath: str,
                       include_notes: bool = True) -> bool:
        """Export mindmap to Markdown outline."""
        nodes = self.db.get_nodes_for_map(mind_map.id)
        if not nodes:
            return False
        
        # Build tree
        node_map = {n.id: n for n in nodes}
        root_nodes = [n for n in nodes if n.parent_id is None]
        
        if not root_nodes:
            return False
        
        root = root_nodes[0]
        
        lines = []
        
        # Frontmatter
        lines.append("---")
        lines.append(f"title: {mind_map.name}")
        lines.append(f"created: {mind_map.created_at}")
        lines.append(f"modified: {mind_map.modified_at}")
        lines.append("---")
        lines.append("")
        
        # Title
        lines.append(f"# {root.text}")
        lines.append("")
        
        # Build tree recursively
        def add_node(node: Node, depth: int):
            children = sorted(
                [n for n in nodes if n.parent_id == node.id],
                key=lambda n: n.sort_order
            )
            
            for child in children:
                # Heading or bullet based on depth
                if depth == 1:
                    lines.append(f"## {child.text}")
                elif depth == 2:
                    lines.append(f"### {child.text}")
                else:
                    indent = "  " * (depth - 3)
                    lines.append(f"{indent}- {child.text}")
                
                # Add note if exists
                if include_notes:
                    note = self.db.get_note(child.id)
                    if note and note.content.strip():
                        note_indent = "  " * (depth - 2) if depth > 2 else "  "
                        for note_line in note.content.strip().split("\n"):
                            lines.append(f"{note_indent}> {note_line}")
                        lines.append("")
                
                # Recurse
                add_node(child, depth + 1)
        
        add_node(root, 1)
        
        # Write file
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write("\n".join(lines))
        
        return True
    
    def _calc_size(self, node: Node, is_root: bool = False):
        text_width = len(node.text) * 9 + self.NODE_PADDING * 2
        if is_root:
            width = max(self.ROOT_NODE_MIN_WIDTH, min(self.NODE_MAX_WIDTH, text_width))
            height = self.ROOT_NODE_HEIGHT
        else:
            width = max(self.NODE_MIN_WIDTH, min(self.NODE_MAX_WIDTH, text_width))
            height = self.NODE_HEIGHT
        return width, height

    def _calculate_positions(self, nodes: List[Node]) -> dict:
        """Dispatch to appropriate layout algorithm."""
        if not nodes:
            return {}
        root_nodes = [n for n in nodes if n.parent_id is None]
        if not root_nodes:
            return {}
        if self.layout_mode == "radial":
            return self._calculate_radial_positions(nodes)
        return self._calculate_horizontal_positions(nodes)

    def _calculate_horizontal_positions(self, nodes: List[Node]) -> dict:
        """Calculate horizontal tree layout matching the canvas algorithm."""
        root_nodes = [n for n in nodes if n.parent_id is None]
        root = root_nodes[0]
        positions: dict = {}

        center_x = 500.0
        center_y = 400.0

        def calc_subtree_height(node: Node) -> float:
            children = sorted(
                [n for n in nodes if n.parent_id == node.id],
                key=lambda n: n.sort_order
            )
            if not children:
                return self.NODE_HEIGHT + self.VERTICAL_SPACING
            return max(
                self.NODE_HEIGHT + self.VERTICAL_SPACING,
                sum(calc_subtree_height(c) for c in children)
            )

        def layout(node: Node, depth: int,
                   parent_right_x: float, y_offset: float):
            is_root = depth == 0
            w, h = self._calc_size(node, is_root)

            if is_root:
                x = center_x - w / 2
                y = center_y - h / 2
            elif node.position_x is not None and node.position_y is not None:
                x = node.position_x
                y = node.position_y
            else:
                x = parent_right_x + self.HORIZONTAL_SPACING
                y = y_offset

            positions[node.id] = (x, y, w, h)

            children = sorted(
                [n for n in nodes if n.parent_id == node.id],
                key=lambda n: n.sort_order
            )

            if children:
                total_height = sum(calc_subtree_height(c) for c in children)
                child_y = y + h / 2 - total_height / 2
                for child in children:
                    child_height = calc_subtree_height(child)
                    layout(
                        child, depth + 1,
                        x + w,
                        child_y + child_height / 2 - self.NODE_HEIGHT / 2
                    )
                    child_y += child_height

        layout(root, 0, 0, 0)
        return positions

    def _calculate_radial_positions(self, nodes: List[Node]) -> dict:
        """Calculate radial layout positions with leaf-count weighting."""
        root_nodes = [n for n in nodes if n.parent_id is None]
        root = root_nodes[0]
        positions: dict = {}

        def count_leaves(node: Node) -> int:
            children = [n for n in nodes if n.parent_id == node.id]
            if not children:
                return 1
            return sum(count_leaves(c) for c in children)

        def layout_tree(node: Node, depth: int,
                       parent_cx: float, parent_cy: float,
                       start_angle: float, angle_span: float):
            is_root = depth == 0
            w, h = self._calc_size(node, is_root)

            if is_root:
                cx, cy = 500.0, 400.0
                x = cx - w / 2
                y = cy - h / 2
            elif node.position_x is not None and node.position_y is not None:
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

            positions[node.id] = (x, y, w, h)

            children = sorted(
                [n for n in nodes if n.parent_id == node.id],
                key=lambda n: n.sort_order
            )

            if children:
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
                    layout_tree(
                        child, depth + 1,
                        cx, cy,
                        child_start, child_span
                    )
                    child_start += child_span

        layout_tree(root, 0, 0, 0, 0, 2 * math.pi)
        return positions
    
    def _draw_connections(self, cr, nodes: List[Node], positions: dict):
        """Draw bezier connections between nodes."""
        for node in nodes:
            if node.parent_id and node.parent_id in positions and node.id in positions:
                px, py, pw, ph = positions[node.parent_id]
                cx, cy, cw, ch = positions[node.id]
                
                parent_cx = px + pw / 2
                parent_cy = py + ph / 2
                child_cx = cx + cw / 2
                child_cy = cy + ch / 2
                
                dx = child_cx - parent_cx
                dy = child_cy - parent_cy
                dist = math.sqrt(dx * dx + dy * dy)
                ctrl_dist = dist * 0.4
                
                angle = math.atan2(dy, dx)
                
                start_x = parent_cx + (pw / 2) * math.cos(angle)
                start_y = parent_cy + (ph / 2) * math.sin(angle)
                end_x = child_cx - (cw / 2) * math.cos(angle)
                end_y = child_cy - (ch / 2) * math.sin(angle)
                
                ctrl1_x = start_x + ctrl_dist * math.cos(angle)
                ctrl1_y = start_y + ctrl_dist * math.sin(angle)
                ctrl2_x = end_x - ctrl_dist * math.cos(angle)
                ctrl2_y = end_y - ctrl_dist * math.sin(angle)
                
                # Gradient line
                gradient = cairo.LinearGradient(start_x, start_y, end_x, end_y)
                gradient.add_color_stop_rgba(0, *self.COLORS['accent_primary'], 0.8)
                gradient.add_color_stop_rgba(1, *self.COLORS['accent_secondary'], 0.6)
                
                cr.set_source(gradient)
                cr.set_line_width(2)
                cr.set_line_cap(cairo.LINE_CAP_ROUND)
                
                cr.move_to(start_x, start_y)
                cr.curve_to(ctrl1_x, ctrl1_y, ctrl2_x, ctrl2_y, end_x, end_y)
                cr.stroke()
    
    def _draw_node(self, cr, node: Node, pos: tuple):
        """Draw a single node."""
        x, y, w, h = pos
        is_root = node.parent_id is None
        
        # Rounded rectangle
        radius = 8 if is_root else 6
        self._draw_rounded_rect(cr, x, y, w, h, radius)
        
        # Fill
        cr.set_source_rgb(*self.COLORS['surface'])
        cr.fill_preserve()
        
        # Border
        cr.set_source_rgb(*self.COLORS['border_subtle'])
        cr.set_line_width(1)
        cr.stroke()
        
        # Text
        cr.set_source_rgb(*self.COLORS['text_primary'])
        cr.select_font_face("Sans", cairo.FONT_SLANT_NORMAL,
                          cairo.FONT_WEIGHT_BOLD if is_root else cairo.FONT_WEIGHT_NORMAL)
        cr.set_font_size(15 if is_root else 13)
        
        extents = cr.text_extents(node.text)
        text_x = x + self.NODE_PADDING
        text_y = y + h / 2 + extents.height / 2 - 2
        
        cr.move_to(text_x, text_y)
        cr.show_text(node.text)
    
    def _draw_rounded_rect(self, cr, x, y, w, h, radius):
        """Draw a rounded rectangle path."""
        cr.new_path()
        cr.arc(x + w - radius, y + radius, radius, -math.pi / 2, 0)
        cr.arc(x + w - radius, y + h - radius, radius, 0, math.pi / 2)
        cr.arc(x + radius, y + h - radius, radius, math.pi / 2, math.pi)
        cr.arc(x + radius, y + radius, radius, math.pi, 3 * math.pi / 2)
        cr.close_path()


def get_export_dir() -> Path:
    """Get the default export directory."""
    export_dir = get_data_dir() / "exports"
    export_dir.mkdir(exist_ok=True)
    return export_dir

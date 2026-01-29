"""Undo/Redo system for CyberMind."""

from typing import Optional, List, Callable, Any
from dataclasses import dataclass
from enum import Enum
from copy import deepcopy


class ActionType(Enum):
    """Types of undoable actions."""
    NODE_CREATE = "node_create"
    NODE_DELETE = "node_delete"
    NODE_EDIT = "node_edit"
    NODE_MOVE = "node_move"
    NODE_STYLE = "node_style"
    NOTE_EDIT = "note_edit"
    MAP_RENAME = "map_rename"
    MAP_LAYOUT = "map_layout"


@dataclass
class UndoAction:
    """Represents an undoable action."""
    action_type: ActionType
    description: str
    data: dict  # Action-specific data for undo
    redo_data: dict  # Action-specific data for redo


class UndoManager:
    """Manages undo/redo history."""
    
    def __init__(self, max_undo: int = 100, max_redo: int = 100):
        self.max_undo = max_undo
        self.max_redo = max_redo
        self._undo_stack: List[UndoAction] = []
        self._redo_stack: List[UndoAction] = []
        self._is_undoing = False
        
        # Callbacks
        self.on_state_changed: Optional[Callable[[], None]] = None
    
    @property
    def can_undo(self) -> bool:
        """Check if undo is available."""
        return len(self._undo_stack) > 0
    
    @property
    def can_redo(self) -> bool:
        """Check if redo is available."""
        return len(self._redo_stack) > 0
    
    @property
    def undo_description(self) -> str:
        """Get description of next undo action."""
        if self._undo_stack:
            return self._undo_stack[-1].description
        return ""
    
    @property
    def redo_description(self) -> str:
        """Get description of next redo action."""
        if self._redo_stack:
            return self._redo_stack[-1].description
        return ""
    
    def push(self, action: UndoAction):
        """Push a new action to the undo stack."""
        if self._is_undoing:
            return
        
        self._undo_stack.append(action)
        self._redo_stack.clear()  # Clear redo on new action
        
        # Trim history if needed
        while len(self._undo_stack) > self.max_undo:
            self._undo_stack.pop(0)
        
        self._notify_changed()
    
    def undo(self) -> Optional[UndoAction]:
        """Pop and return the last action for undoing."""
        if not self._undo_stack:
            return None
        
        self._is_undoing = True
        action = self._undo_stack.pop()
        self._redo_stack.append(action)
        while len(self._redo_stack) > self.max_redo:
            self._redo_stack.pop(0)
        self._is_undoing = False
        
        self._notify_changed()
        return action
    
    def redo(self) -> Optional[UndoAction]:
        """Pop and return the last undone action for redoing."""
        if not self._redo_stack:
            return None
        
        self._is_undoing = True
        action = self._redo_stack.pop()
        self._undo_stack.append(action)
        while len(self._undo_stack) > self.max_undo:
            self._undo_stack.pop(0)
        self._is_undoing = False
        
        self._notify_changed()
        return action
    
    def clear(self):
        """Clear all history."""
        self._undo_stack.clear()
        self._redo_stack.clear()
        self._notify_changed()
    
    def _notify_changed(self):
        """Notify that undo/redo state changed."""
        if self.on_state_changed:
            self.on_state_changed()
    
    # ==================== Action Factories ====================
    
    @staticmethod
    def create_node_action(node_id: int, map_id: int, parent_id: Optional[int],
                          text: str, sort_order: int) -> UndoAction:
        """Create action for node creation."""
        return UndoAction(
            action_type=ActionType.NODE_CREATE,
            description=f"Create node '{text[:20]}...' " if len(text) > 20 else f"Create node '{text}'",
            data={
                "node_id": node_id,
            },
            redo_data={
                "map_id": map_id,
                "parent_id": parent_id,
                "text": text,
                "sort_order": sort_order,
            }
        )
    
    @staticmethod
    def delete_node_action(node_id: int, map_id: int, parent_id: Optional[int],
                          text: str, sort_order: int, style: dict,
                          children_data: List[dict]) -> UndoAction:
        """Create action for node deletion."""
        return UndoAction(
            action_type=ActionType.NODE_DELETE,
            description=f"Delete node '{text[:20]}...'" if len(text) > 20 else f"Delete node '{text}'",
            data={
                "node_id": node_id,
                "map_id": map_id,
                "parent_id": parent_id,
                "text": text,
                "sort_order": sort_order,
                "style": style,
                "children_data": children_data,
            },
            redo_data={
                "node_id": node_id,
            }
        )
    
    @staticmethod
    def edit_node_action(node_id: int, old_text: str, new_text: str) -> UndoAction:
        """Create action for node text edit."""
        return UndoAction(
            action_type=ActionType.NODE_EDIT,
            description=f"Edit node text",
            data={
                "node_id": node_id,
                "text": old_text,
            },
            redo_data={
                "node_id": node_id,
                "text": new_text,
            }
        )
    
    @staticmethod
    def move_node_action(node_id: int, old_parent_id: Optional[int], 
                        new_parent_id: Optional[int],
                        old_sort_order: int, new_sort_order: int) -> UndoAction:
        """Create action for node move."""
        return UndoAction(
            action_type=ActionType.NODE_MOVE,
            description="Move node",
            data={
                "node_id": node_id,
                "parent_id": old_parent_id,
                "sort_order": old_sort_order,
            },
            redo_data={
                "node_id": node_id,
                "parent_id": new_parent_id,
                "sort_order": new_sort_order,
            }
        )
    
    @staticmethod
    def style_node_action(node_id: int, old_style: dict, new_style: dict) -> UndoAction:
        """Create action for node style change."""
        return UndoAction(
            action_type=ActionType.NODE_STYLE,
            description="Change node style",
            data={
                "node_id": node_id,
                "style": old_style,
            },
            redo_data={
                "node_id": node_id,
                "style": new_style,
            }
        )
    
    @staticmethod
    def edit_note_action(node_id: int, old_content: str, new_content: str) -> UndoAction:
        """Create action for note edit."""
        return UndoAction(
            action_type=ActionType.NOTE_EDIT,
            description="Edit note",
            data={
                "node_id": node_id,
                "content": old_content,
            },
            redo_data={
                "node_id": node_id,
                "content": new_content,
            }
        )

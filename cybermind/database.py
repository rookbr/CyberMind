"""SQLite database layer for CyberMind."""

import sqlite3
import json
import os
from pathlib import Path
from datetime import datetime
from typing import Optional, List, Dict, Any
from dataclasses import dataclass, field, asdict


def get_data_dir() -> Path:
    """Get the application data directory."""
    data_dir = Path.home() / ".local" / "share" / "cybermind"
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "exports").mkdir(exist_ok=True)
    (data_dir / "backups").mkdir(exist_ok=True)
    return data_dir


def get_db_path() -> Path:
    """Get the database file path."""
    return get_data_dir() / "cybermind.db"


@dataclass
class NodeStyle:
    """Style configuration for a node."""
    color: Optional[str] = None
    icon: Optional[str] = None
    priority: Optional[str] = None  # critical, high, medium, low, info
    status: Optional[str] = None    # todo, in_progress, done, blocked
    
    def to_json(self) -> str:
        return json.dumps(asdict(self))
    
    @classmethod
    def from_json(cls, data: Optional[str]) -> "NodeStyle":
        if not data:
            return cls()
        try:
            return cls(**json.loads(data))
        except (json.JSONDecodeError, TypeError):
            return cls()


@dataclass
class MapSettings:
    """Settings for a specific map."""
    auto_layout: bool = True
    zoom_level: float = 1.0
    pan_x: float = 0.0
    pan_y: float = 0.0
    show_grid: bool = True
    layout_mode: str = "horizontal"
    show_minimap: bool = True

    def to_json(self) -> str:
        return json.dumps(asdict(self))

    @classmethod
    def from_json(cls, data: Optional[str]) -> "MapSettings":
        if not data:
            return cls()
        try:
            d = json.loads(data)
            # Filter to only known fields to handle schema evolution
            known = {f.name for f in cls.__dataclass_fields__.values()}
            return cls(**{k: v for k, v in d.items() if k in known})
        except (json.JSONDecodeError, TypeError):
            return cls()


@dataclass
class MindMap:
    """Represents a mindmap."""
    id: int = 0
    name: str = "Untitled Map"
    created_at: str = ""
    modified_at: str = ""
    settings: MapSettings = field(default_factory=MapSettings)
    is_archived: bool = False


@dataclass
class Node:
    """Represents a node in the mindmap."""
    id: int = 0
    map_id: int = 0
    parent_id: Optional[int] = None
    text: str = "New Topic"
    position_x: Optional[float] = None
    position_y: Optional[float] = None
    is_collapsed: bool = False
    sort_order: int = 0
    style: NodeStyle = field(default_factory=NodeStyle)
    created_at: str = ""
    modified_at: str = ""
    children: List["Node"] = field(default_factory=list)


@dataclass
class Note:
    """Represents a note attached to a node."""
    id: int = 0
    node_id: int = 0
    content: str = ""
    modified_at: str = ""


@dataclass
class Relationship:
    """Represents a non-hierarchical connection between nodes."""
    id: int = 0
    map_id: int = 0
    source_node_id: int = 0
    target_node_id: int = 0
    label: str = ""
    style: Optional[str] = None


class Database:
    """Database manager for CyberMind."""
    
    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or get_db_path()
        self._conn: Optional[sqlite3.Connection] = None
        self._init_db()
    
    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(str(self.db_path))
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA foreign_keys = ON")
            self._conn.execute("PRAGMA journal_mode = WAL")
        return self._conn
    
    def _init_db(self):
        """Initialize the database schema."""
        cursor = self.conn.cursor()
        
        cursor.executescript("""
            -- Maps table
            CREATE TABLE IF NOT EXISTS maps (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                modified_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                settings JSON,
                is_archived BOOLEAN DEFAULT 0
            );

            -- Nodes table
            CREATE TABLE IF NOT EXISTS nodes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                map_id INTEGER NOT NULL,
                parent_id INTEGER,
                text TEXT NOT NULL DEFAULT 'New Topic',
                position_x REAL,
                position_y REAL,
                is_collapsed BOOLEAN DEFAULT 0,
                sort_order INTEGER DEFAULT 0,
                style JSON,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                modified_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (map_id) REFERENCES maps(id) ON DELETE CASCADE,
                FOREIGN KEY (parent_id) REFERENCES nodes(id) ON DELETE CASCADE
            );

            -- Notes table
            CREATE TABLE IF NOT EXISTS notes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                node_id INTEGER NOT NULL UNIQUE,
                content TEXT,
                modified_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (node_id) REFERENCES nodes(id) ON DELETE CASCADE
            );

            -- Relationships table
            CREATE TABLE IF NOT EXISTS relationships (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                map_id INTEGER NOT NULL,
                source_node_id INTEGER NOT NULL,
                target_node_id INTEGER NOT NULL,
                label TEXT,
                style JSON,
                FOREIGN KEY (map_id) REFERENCES maps(id) ON DELETE CASCADE,
                FOREIGN KEY (source_node_id) REFERENCES nodes(id) ON DELETE CASCADE,
                FOREIGN KEY (target_node_id) REFERENCES nodes(id) ON DELETE CASCADE
            );

            -- App settings table
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value JSON
            );

            -- Create indexes
            CREATE INDEX IF NOT EXISTS idx_nodes_map_id ON nodes(map_id);
            CREATE INDEX IF NOT EXISTS idx_nodes_parent_id ON nodes(parent_id);
            CREATE INDEX IF NOT EXISTS idx_notes_node_id ON notes(node_id);
            CREATE INDEX IF NOT EXISTS idx_relationships_map_id ON relationships(map_id);
        """)
        
        # Create FTS tables if they don't exist
        try:
            cursor.execute("""
                CREATE VIRTUAL TABLE IF NOT EXISTS nodes_fts USING fts5(
                    text, content='nodes', content_rowid='id'
                )
            """)
            cursor.execute("""
                CREATE VIRTUAL TABLE IF NOT EXISTS notes_fts USING fts5(
                    content, content='notes', content_rowid='id'
                )
            """)
        except sqlite3.OperationalError:
            pass  # FTS tables might already exist
        
        # Create triggers for FTS sync
        cursor.executescript("""
            CREATE TRIGGER IF NOT EXISTS nodes_ai AFTER INSERT ON nodes BEGIN
                INSERT INTO nodes_fts(rowid, text) VALUES (new.id, new.text);
            END;
            
            CREATE TRIGGER IF NOT EXISTS nodes_ad AFTER DELETE ON nodes BEGIN
                INSERT INTO nodes_fts(nodes_fts, rowid, text) VALUES('delete', old.id, old.text);
            END;
            
            CREATE TRIGGER IF NOT EXISTS nodes_au AFTER UPDATE ON nodes BEGIN
                INSERT INTO nodes_fts(nodes_fts, rowid, text) VALUES('delete', old.id, old.text);
                INSERT INTO nodes_fts(rowid, text) VALUES (new.id, new.text);
            END;
            
            CREATE TRIGGER IF NOT EXISTS notes_ai AFTER INSERT ON notes BEGIN
                INSERT INTO notes_fts(rowid, content) VALUES (new.id, new.content);
            END;
            
            CREATE TRIGGER IF NOT EXISTS notes_ad AFTER DELETE ON notes BEGIN
                INSERT INTO notes_fts(notes_fts, rowid, content) VALUES('delete', old.id, old.content);
            END;
            
            CREATE TRIGGER IF NOT EXISTS notes_au AFTER UPDATE ON notes BEGIN
                INSERT INTO notes_fts(notes_fts, rowid, content) VALUES('delete', old.id, old.content);
                INSERT INTO notes_fts(rowid, content) VALUES (new.id, new.content);
            END;
        """)
        
        self.conn.commit()
    
    def close(self):
        """Close the database connection."""
        if self._conn:
            self._conn.close()
            self._conn = None
    
    # ==================== Map Operations ====================
    
    def create_map(self, name: str = "Untitled Map") -> MindMap:
        """Create a new mindmap with a root node."""
        cursor = self.conn.cursor()
        now = datetime.now().isoformat()
        # Note: this is an app-level preference applied at map creation time.
        settings = MapSettings(
            auto_layout=bool(self.get_setting("default_auto_layout", True))
        )
        
        cursor.execute(
            "INSERT INTO maps (name, created_at, modified_at, settings) VALUES (?, ?, ?, ?)",
            (name, now, now, settings.to_json())
        )
        map_id = cursor.lastrowid
        
        # Create root node
        cursor.execute(
            "INSERT INTO nodes (map_id, text, sort_order) VALUES (?, ?, ?)",
            (map_id, "Central Topic", 0)
        )
        
        self.conn.commit()
        
        return MindMap(
            id=map_id,
            name=name,
            created_at=now,
            modified_at=now,
            settings=settings
        )
    
    def get_map(self, map_id: int) -> Optional[MindMap]:
        """Get a mindmap by ID."""
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM maps WHERE id = ?", (map_id,))
        row = cursor.fetchone()
        
        if not row:
            return None
        
        return MindMap(
            id=row["id"],
            name=row["name"],
            created_at=row["created_at"],
            modified_at=row["modified_at"],
            settings=MapSettings.from_json(row["settings"]),
            is_archived=bool(row["is_archived"])
        )
    
    def get_all_maps(self, include_archived: bool = False) -> List[MindMap]:
        """Get all mindmaps."""
        cursor = self.conn.cursor()
        
        if include_archived:
            cursor.execute("SELECT * FROM maps ORDER BY modified_at DESC")
        else:
            cursor.execute("SELECT * FROM maps WHERE is_archived = 0 ORDER BY modified_at DESC")
        
        maps = []
        for row in cursor.fetchall():
            maps.append(MindMap(
                id=row["id"],
                name=row["name"],
                created_at=row["created_at"],
                modified_at=row["modified_at"],
                settings=MapSettings.from_json(row["settings"]),
                is_archived=bool(row["is_archived"])
            ))
        
        return maps
    
    def update_map(self, mind_map: MindMap):
        """Update a mindmap."""
        cursor = self.conn.cursor()
        now = datetime.now().isoformat()
        
        cursor.execute(
            """UPDATE maps SET name = ?, modified_at = ?, settings = ?, is_archived = ?
               WHERE id = ?""",
            (mind_map.name, now, mind_map.settings.to_json(), mind_map.is_archived, mind_map.id)
        )
        self.conn.commit()
    
    def delete_map(self, map_id: int):
        """Delete a mindmap and all its nodes."""
        cursor = self.conn.cursor()
        cursor.execute("DELETE FROM maps WHERE id = ?", (map_id,))
        self.conn.commit()
    
    def duplicate_map(self, map_id: int, new_name: str) -> Optional[MindMap]:
        """Duplicate a mindmap."""
        original = self.get_map(map_id)
        if not original:
            return None
        
        # Create new map
        new_map = self.create_map(new_name)
        
        # Delete auto-created root node
        cursor = self.conn.cursor()
        cursor.execute("DELETE FROM nodes WHERE map_id = ?", (new_map.id,))
        
        # Copy nodes
        original_nodes = self.get_nodes_for_map(map_id)
        id_mapping = {}  # old_id -> new_id
        
        # First pass: create all nodes without parent references
        for node in original_nodes:
            cursor.execute(
                """INSERT INTO nodes (map_id, text, position_x, position_y, is_collapsed, sort_order, style)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (new_map.id, node.text, node.position_x, node.position_y,
                 node.is_collapsed, node.sort_order, node.style.to_json())
            )
            id_mapping[node.id] = cursor.lastrowid
            
            # Copy note if exists
            note = self.get_note(node.id)
            if note:
                cursor.execute(
                    "INSERT INTO notes (node_id, content) VALUES (?, ?)",
                    (id_mapping[node.id], note.content)
                )
        
        # Second pass: update parent references
        for node in original_nodes:
            if node.parent_id and node.parent_id in id_mapping:
                cursor.execute(
                    "UPDATE nodes SET parent_id = ? WHERE id = ?",
                    (id_mapping[node.parent_id], id_mapping[node.id])
                )
        
        self.conn.commit()
        return new_map
    
    # ==================== Node Operations ====================
    
    def get_nodes_for_map(self, map_id: int) -> List[Node]:
        """Get all nodes for a map."""
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT * FROM nodes WHERE map_id = ? ORDER BY sort_order",
            (map_id,)
        )
        
        nodes = []
        for row in cursor.fetchall():
            nodes.append(Node(
                id=row["id"],
                map_id=row["map_id"],
                parent_id=row["parent_id"],
                text=row["text"],
                position_x=row["position_x"],
                position_y=row["position_y"],
                is_collapsed=bool(row["is_collapsed"]),
                sort_order=row["sort_order"],
                style=NodeStyle.from_json(row["style"]),
                created_at=row["created_at"],
                modified_at=row["modified_at"]
            ))
        
        return nodes
    
    def get_node(self, node_id: int) -> Optional[Node]:
        """Get a node by ID."""
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM nodes WHERE id = ?", (node_id,))
        row = cursor.fetchone()
        
        if not row:
            return None
        
        return Node(
            id=row["id"],
            map_id=row["map_id"],
            parent_id=row["parent_id"],
            text=row["text"],
            position_x=row["position_x"],
            position_y=row["position_y"],
            is_collapsed=bool(row["is_collapsed"]),
            sort_order=row["sort_order"],
            style=NodeStyle.from_json(row["style"]),
            created_at=row["created_at"],
            modified_at=row["modified_at"]
        )
    
    def get_root_node(self, map_id: int) -> Optional[Node]:
        """Get the root node of a map."""
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT * FROM nodes WHERE map_id = ? AND parent_id IS NULL ORDER BY sort_order LIMIT 1",
            (map_id,)
        )
        row = cursor.fetchone()
        
        if not row:
            return None
        
        return Node(
            id=row["id"],
            map_id=row["map_id"],
            parent_id=row["parent_id"],
            text=row["text"],
            position_x=row["position_x"],
            position_y=row["position_y"],
            is_collapsed=bool(row["is_collapsed"]),
            sort_order=row["sort_order"],
            style=NodeStyle.from_json(row["style"]),
            created_at=row["created_at"],
            modified_at=row["modified_at"]
        )
    
    def get_children(self, node_id: int) -> List[Node]:
        """Get child nodes of a node."""
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT * FROM nodes WHERE parent_id = ? ORDER BY sort_order",
            (node_id,)
        )
        
        children = []
        for row in cursor.fetchall():
            children.append(Node(
                id=row["id"],
                map_id=row["map_id"],
                parent_id=row["parent_id"],
                text=row["text"],
                position_x=row["position_x"],
                position_y=row["position_y"],
                is_collapsed=bool(row["is_collapsed"]),
                sort_order=row["sort_order"],
                style=NodeStyle.from_json(row["style"]),
                created_at=row["created_at"],
                modified_at=row["modified_at"]
            ))
        
        return children
    
    def create_node(self, map_id: int, parent_id: Optional[int] = None, 
                    text: str = "New Topic", after_node_id: Optional[int] = None) -> Node:
        """Create a new node."""
        cursor = self.conn.cursor()
        now = datetime.now().isoformat()
        
        # Determine sort order
        if after_node_id:
            cursor.execute("SELECT sort_order FROM nodes WHERE id = ?", (after_node_id,))
            row = cursor.fetchone()
            sort_order = (row["sort_order"] + 1) if row else 0
            
            # Increment sort order of following siblings
            cursor.execute(
                """UPDATE nodes SET sort_order = sort_order + 1 
                   WHERE parent_id = ? AND sort_order >= ?""",
                (parent_id, sort_order)
            )
        else:
            cursor.execute(
                "SELECT COALESCE(MAX(sort_order), -1) + 1 FROM nodes WHERE parent_id IS ?",
                (parent_id,)
            )
            sort_order = cursor.fetchone()[0]
        
        cursor.execute(
            """INSERT INTO nodes (map_id, parent_id, text, sort_order, created_at, modified_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (map_id, parent_id, text, sort_order, now, now)
        )
        node_id = cursor.lastrowid
        
        # Update map modified time
        cursor.execute("UPDATE maps SET modified_at = ? WHERE id = ?", (now, map_id))
        
        self.conn.commit()
        
        return Node(
            id=node_id,
            map_id=map_id,
            parent_id=parent_id,
            text=text,
            sort_order=sort_order,
            created_at=now,
            modified_at=now
        )
    
    def update_node(self, node: Node):
        """Update a node."""
        cursor = self.conn.cursor()
        now = datetime.now().isoformat()
        
        cursor.execute(
                """UPDATE nodes SET parent_id = ?, text = ?, position_x = ?, position_y = ?, 
                    is_collapsed = ?, sort_order = ?, style = ?, modified_at = ?
                    WHERE id = ?""",
                (node.parent_id, node.text, node.position_x, node.position_y, node.is_collapsed,
                 node.sort_order, node.style.to_json(), now, node.id)
        )
        
        # Update map modified time
        cursor.execute("UPDATE maps SET modified_at = ? WHERE id = ?", (now, node.map_id))
        
        self.conn.commit()
    
    def delete_node(self, node_id: int):
        """Delete a node and all its descendants."""
        cursor = self.conn.cursor()
        
        # Get map_id for updating modified time
        cursor.execute("SELECT map_id FROM nodes WHERE id = ?", (node_id,))
        row = cursor.fetchone()
        if row:
            map_id = row["map_id"]
            cursor.execute("DELETE FROM nodes WHERE id = ?", (node_id,))
            cursor.execute("UPDATE maps SET modified_at = ? WHERE id = ?", 
                          (datetime.now().isoformat(), map_id))
            self.conn.commit()
    
    def move_node(self, node_id: int, new_parent_id: Optional[int], new_sort_order: int):
        """Move a node to a new parent or position."""
        cursor = self.conn.cursor()
        now = datetime.now().isoformat()
        
        cursor.execute(
            "UPDATE nodes SET parent_id = ?, sort_order = ?, modified_at = ? WHERE id = ?",
            (new_parent_id, new_sort_order, now, node_id)
        )
        self.conn.commit()
    
    def restore_node(self, node: Node):
        """Restore a deleted node (for undo)."""
        cursor = self.conn.cursor()
        now = datetime.now().isoformat()
        
        cursor.execute(
            """INSERT INTO nodes (id, map_id, parent_id, text, position_x, position_y,
               is_collapsed, sort_order, style, created_at, modified_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (node.id, node.map_id, node.parent_id, node.text, node.position_x,
             node.position_y, node.is_collapsed, node.sort_order, 
             node.style.to_json(), now, now)
        )
        
        cursor.execute("UPDATE maps SET modified_at = ? WHERE id = ?", (now, node.map_id))
        self.conn.commit()
    
    # ==================== Note Operations ====================
    
    def get_note(self, node_id: int) -> Optional[Note]:
        """Get a note for a node."""
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM notes WHERE node_id = ?", (node_id,))
        row = cursor.fetchone()
        
        if not row:
            return None
        
        return Note(
            id=row["id"],
            node_id=row["node_id"],
            content=row["content"],
            modified_at=row["modified_at"]
        )
    
    def set_note(self, node_id: int, content: str) -> Note:
        """Set or update a note for a node."""
        cursor = self.conn.cursor()
        now = datetime.now().isoformat()
        
        # Try update first
        cursor.execute(
            "UPDATE notes SET content = ?, modified_at = ? WHERE node_id = ?",
            (content, now, node_id)
        )
        
        if cursor.rowcount == 0:
            # Insert new note
            cursor.execute(
                "INSERT INTO notes (node_id, content, modified_at) VALUES (?, ?, ?)",
                (node_id, content, now)
            )
        
        self.conn.commit()
        return self.get_note(node_id)
    
    def delete_note(self, node_id: int):
        """Delete a note."""
        cursor = self.conn.cursor()
        cursor.execute("DELETE FROM notes WHERE node_id = ?", (node_id,))
        self.conn.commit()

    def get_node_ids_with_notes(self, map_id: int) -> set:
        """Return set of node IDs that have non-empty notes for a given map."""
        cursor = self.conn.cursor()
        cursor.execute(
            """SELECT nt.node_id FROM notes nt
               JOIN nodes n ON nt.node_id = n.id
               WHERE n.map_id = ? AND nt.content IS NOT NULL AND nt.content != ''""",
            (map_id,)
        )
        return {row["node_id"] for row in cursor.fetchall()}
    
    # ==================== Search Operations ====================
    
    @staticmethod
    def _sanitize_fts_query(query: str) -> str:
        """Sanitize a query string for FTS5 MATCH by quoting it."""
        # Escape internal double-quotes and wrap in double-quotes
        escaped = query.replace('"', '""')
        return f'"{escaped}"*'

    def search_nodes(self, query: str, map_id: Optional[int] = None) -> List[Dict[str, Any]]:
        """Search nodes by text."""
        cursor = self.conn.cursor()
        safe_query = self._sanitize_fts_query(query)

        try:
            if map_id:
                cursor.execute(
                    """SELECT n.*, m.name as map_name FROM nodes n
                       JOIN maps m ON n.map_id = m.id
                       WHERE n.map_id = ? AND n.id IN (
                           SELECT rowid FROM nodes_fts WHERE nodes_fts MATCH ?
                       )""",
                    (map_id, safe_query)
                )
            else:
                cursor.execute(
                    """SELECT n.*, m.name as map_name FROM nodes n
                       JOIN maps m ON n.map_id = m.id
                       WHERE n.id IN (
                           SELECT rowid FROM nodes_fts WHERE nodes_fts MATCH ?
                       )""",
                    (safe_query,)
                )
        except sqlite3.OperationalError:
            return []

        results = []
        for row in cursor.fetchall():
            results.append({
                "type": "node",
                "node_id": row["id"],
                "map_id": row["map_id"],
                "map_name": row["map_name"],
                "text": row["text"]
            })

        return results

    def search_notes(self, query: str, map_id: Optional[int] = None) -> List[Dict[str, Any]]:
        """Search notes by content."""
        cursor = self.conn.cursor()
        safe_query = self._sanitize_fts_query(query)

        try:
            if map_id:
                cursor.execute(
                    """SELECT nt.*, n.text as node_text, n.map_id, m.name as map_name
                       FROM notes nt
                       JOIN nodes n ON nt.node_id = n.id
                       JOIN maps m ON n.map_id = m.id
                       WHERE n.map_id = ? AND nt.id IN (
                           SELECT rowid FROM notes_fts WHERE notes_fts MATCH ?
                       )""",
                    (map_id, safe_query)
                )
            else:
                cursor.execute(
                    """SELECT nt.*, n.text as node_text, n.map_id, m.name as map_name
                       FROM notes nt
                       JOIN nodes n ON nt.node_id = n.id
                       JOIN maps m ON n.map_id = m.id
                       WHERE nt.id IN (
                           SELECT rowid FROM notes_fts WHERE notes_fts MATCH ?
                       )""",
                    (safe_query,)
                )
        except sqlite3.OperationalError:
            return []

        results = []
        for row in cursor.fetchall():
            results.append({
                "type": "note",
                "node_id": row["node_id"],
                "map_id": row["map_id"],
                "map_name": row["map_name"],
                "node_text": row["node_text"],
                "content": row["content"][:100]
            })

        return results
    
    # ==================== Settings Operations ====================
    
    def get_setting(self, key: str, default: Any = None) -> Any:
        """Get an application setting."""
        cursor = self.conn.cursor()
        cursor.execute("SELECT value FROM settings WHERE key = ?", (key,))
        row = cursor.fetchone()
        
        if not row:
            return default
        
        try:
            return json.loads(row["value"])
        except json.JSONDecodeError:
            return default
    
    def set_setting(self, key: str, value: Any):
        """Set an application setting."""
        cursor = self.conn.cursor()
        cursor.execute(
            "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
            (key, json.dumps(value))
        )
        self.conn.commit()
    
    # ==================== Backup Operations ====================
    
    def create_backup(self, map_id: int):
        """Create a backup of a map."""
        backup_dir = get_data_dir() / "backups"
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        mind_map = self.get_map(map_id)
        if not mind_map:
            return

        backup_file = backup_dir / f"map_{map_id}_{timestamp}.db"

        # Create a temporary database with just this map
        temp_db = Database(backup_file)

        # Copy map
        cursor = temp_db.conn.cursor()
        cursor.execute(
            "INSERT INTO maps (name, created_at, modified_at, settings) VALUES (?, ?, ?, ?)",
            (mind_map.name, mind_map.created_at, mind_map.modified_at, mind_map.settings.to_json())
        )
        new_map_id = cursor.lastrowid

        # Copy nodes
        nodes = self.get_nodes_for_map(map_id)
        id_mapping = {}

        for node in nodes:
            cursor.execute(
                """INSERT INTO nodes (map_id, text, position_x, position_y, is_collapsed, sort_order, style)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (new_map_id, node.text, node.position_x, node.position_y,
                 node.is_collapsed, node.sort_order, node.style.to_json())
            )
            id_mapping[node.id] = cursor.lastrowid

            # Copy note if exists
            note = self.get_note(node.id)
            if note and note.content is not None:
                cursor.execute(
                    "INSERT INTO notes (node_id, content, modified_at) VALUES (?, ?, ?)",
                    (id_mapping[node.id], note.content, note.modified_at or datetime.now().isoformat())
                )

        # Update parent references
        for node in nodes:
            if node.parent_id and node.parent_id in id_mapping:
                cursor.execute(
                    "UPDATE nodes SET parent_id = ? WHERE id = ?",
                    (id_mapping[node.parent_id], id_mapping[node.id])
                )

        # Copy relationships (if any exist). Note: relationships are not currently exposed
        # via the UI, but backing them up makes the backup format future-proof.
        src_cur = self.conn.cursor()
        src_cur.execute(
            "SELECT * FROM relationships WHERE map_id = ?",
            (map_id,)
        )
        for rel in src_cur.fetchall():
            src_id = rel["source_node_id"]
            tgt_id = rel["target_node_id"]
            if src_id in id_mapping and tgt_id in id_mapping:
                cursor.execute(
                    """INSERT INTO relationships (map_id, source_node_id, target_node_id, label, style)
                       VALUES (?, ?, ?, ?, ?)""",
                    (new_map_id, id_mapping[src_id], id_mapping[tgt_id], rel["label"], rel["style"])
                )

        temp_db.conn.commit()
        temp_db.close()

        # Clean old backups (keep last N)
        backup_count = self.get_setting("backup_count", 10)
        backups = sorted(backup_dir.glob(f"map_{map_id}_*.db"), reverse=True)
        for old_backup in backups[backup_count:]:
            old_backup.unlink()

"""Built-in icon definitions for CyberMind nodes."""

# Icon categories and their symbols
# These use Unicode symbols that work with monospace fonts
# In a full implementation, these would be SVG icons

ICONS = {
    "network": {
        "server": "🖥",
        "firewall": "🛡",
        "router": "📡",
        "cloud": "☁",
        "endpoint": "💻",
        "database": "🗄",
        "network": "🌐",
    },
    "security": {
        "lock": "🔒",
        "unlock": "🔓",
        "shield": "🛡",
        "bug": "🐛",
        "key": "🔑",
        "warning": "⚠",
        "alert": "🚨",
    },
    "status": {
        "check": "✓",
        "cross": "✗",
        "question": "?",
        "info": "ℹ",
        "star": "★",
        "flag": "⚑",
    },
    "actions": {
        "attack": "⚔",
        "defend": "🛡",
        "scan": "🔍",
        "analyze": "📊",
        "report": "📝",
        "execute": "▶",
    },
    "assets": {
        "file": "📄",
        "folder": "📁",
        "user": "👤",
        "users": "👥",
        "credential": "🔐",
        "money": "💰",
    },
    "arrows": {
        "right": "→",
        "left": "←",
        "up": "↑",
        "down": "↓",
        "bidirectional": "↔",
    },
    "priority": {
        "critical": "🔴",
        "high": "🟠",
        "medium": "🟡",
        "low": "🟢",
        "info": "🔵",
    }
}


def get_icon(category: str, name: str) -> str:
    """Get an icon by category and name."""
    return ICONS.get(category, {}).get(name, "")


def get_all_icons() -> dict:
    """Get all icons organized by category."""
    return ICONS


def get_category_icons(category: str) -> dict:
    """Get all icons in a category."""
    return ICONS.get(category, {})

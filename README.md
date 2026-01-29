# CyberMind

A hacker-aesthetic mindmap application for Linux (Wayland/GNOME).

![CyberMind](cybermind_horizontal.png)

## Features

- **Dark cyberpunk/terminal operator aesthetic** - Immersive hacker-themed UI
- **Keyboard-driven workflow** - Efficient navigation and editing
- **Fast local search** - Full-text search across nodes and notes (FTS)
- **Rich per-node notes** - Plain text / Markdown-friendly notes panel
- **SQLite persistence** - Fully offline, local database storage
- **Undo/redo** - Full undo/redo support for canvas edits
- **Multiple layouts** - Horizontal tree and radial layout modes
- **Manual positioning** - Drag nodes + auto-balance layout option
- **Minimap + grid** - Navigation aids for large mindmaps
- **Copy/paste subtrees** - Duplicate and move node branches
- **Export options** - PNG, PDF, and Markdown export
- **Automatic backups** - On-demand backup creation on save

## Requirements

- **Fedora 43+** / GNOME 49+ / Wayland
- GTK4 and libadwaita
- Python 3.11+

CyberMind enforces a strict preflight check for Fedora + GNOME at launch.
To bypass for development/testing on other setups, set `CYBERMIND_SKIP_PREFLIGHT=1`.

## Installation

### Quick Install (Recommended)

The installation script installs CyberMind to `/opt/cybermind` with full desktop integration:

```bash
# Clone the repository
git clone https://github.com/YOUR_USERNAME/CyberMind.git
cd CyberMind

# Run the installer (requires sudo)
sudo ./install.sh
```

After installation:
- Run from terminal: `cybermind`
- Or find **CyberMind** in your application menu

### Uninstall

```bash
sudo ./uninstall.sh
```

Note: Your user data in `~/.local/share/cybermind/` is preserved during uninstall.

### Manual Installation (Development)

```bash
# Install system dependencies
sudo dnf install gtk4-devel libadwaita-devel python3-gobject cairo-devel python3-pip

# Create virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install Python dependencies
pip install -r requirements.txt

# Run the application
python3 -m cybermind
```

If the app exits with a preflight error, it will print the missing dependency
and the suggested `dnf install ...` command.

## Migration (move to a new machine)

CyberMind stores all data locally under `~/.local/share/cybermind/`.
The easiest and most reliable way to move everything (including notes) is to
export an archive on the old machine and import it on the new machine.

Important: close CyberMind before migrating.

### Recommended: `cybermind-migrate` archive

On the old machine:

```bash
cybermind-migrate export --out ~/cybermind-backup.tar.gz
# Optional: also include your generated exports (PNGs/PDFs/MD files)
# cybermind-migrate export --out ~/cybermind-backup.tar.gz --include-exports

# Optional sanity-check the archive before copying it
cybermind-migrate verify --archive ~/cybermind-backup.tar.gz
```

Copy `~/cybermind-backup.tar.gz` to the new Fedora machine.

On the new machine:

```bash
cybermind-migrate import --archive ~/cybermind-backup.tar.gz --overwrite

# Verify the local DB after import
cybermind-migrate verify
```

This replaces the target `cybermind.db` (and keeps a safety copy under
`~/.local/share/cybermind/migrate-backups/<timestamp>/`).

### Manual fallback (if you don’t want the script)

1) Close CyberMind.
2) Copy the entire folder `~/.local/share/cybermind/` to the new machine.

This includes the main database, per-map backups, and exports.

## Keyboard Shortcuts

| Action | Shortcut |
|--------|----------|
| New Map | `Ctrl+N` |
| Save | `Ctrl+S` |
| Search | `Ctrl+F` |
| Search All Maps | `Ctrl+Shift+F` |
| New Child Node | `Tab` |
| New Sibling | `Enter` |
| Delete Node | `Delete` |
| Undo / Redo | `Ctrl+Z` / `Ctrl+R` |
| Toggle Sidebar | `Ctrl+B` |
| Toggle Notes Panel | `Ctrl+Shift+B` |
| Zoom In/Out | `Ctrl++`/`Ctrl+-` |
| Zoom to Fit | `Ctrl+0` |
| Reset Zoom | `Ctrl+1` |

## Version History

- **1.0.0** - Initial public release

## License

MIT License - See [LICENSE](LICENSE) file for details.

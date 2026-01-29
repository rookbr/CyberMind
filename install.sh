#!/bin/bash
# CyberMind Installation Script
# Installs CyberMind to /opt/cybermind with system-wide integration

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

INSTALL_DIR="/opt/cybermind"
VENV_DIR="$INSTALL_DIR/.venv"
DESKTOP_FILE="/usr/share/applications/cybermind.desktop"
ICON_DIR="/usr/share/icons/hicolor"
BIN_LINK="/usr/local/bin/cybermind"

echo -e "${CYAN}"
echo "╔═══════════════════════════════════════════════════════════╗"
echo "║              CyberMind Installer v1.0                     ║"
echo "║     A Hacker-Aesthetic Mindmap Application for Linux      ║"
echo "╚═══════════════════════════════════════════════════════════╝"
echo -e "${NC}"

# Check if running as root
if [[ $EUID -ne 0 ]]; then
    echo -e "${RED}Error: This script must be run as root (sudo)${NC}"
    echo "Usage: sudo ./install.sh"
    exit 1
fi

# Check for Fedora
if [[ ! -f /etc/os-release ]] || ! grep -qi "fedora" /etc/os-release; then
    echo -e "${YELLOW}Warning: CyberMind is designed for Fedora Linux.${NC}"
    echo -e "${YELLOW}Installation may work on other distributions but is not guaranteed.${NC}"
    read -p "Continue anyway? (y/N) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
fi

# Get the directory where this script is located (source files)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo -e "${GREEN}[1/6]${NC} Installing system dependencies..."
dnf install -y gtk4-devel libadwaita-devel python3-gobject python3-pip cairo-devel python3-devel 2>/dev/null || {
    echo -e "${RED}Failed to install system dependencies.${NC}"
    echo "Please manually run: sudo dnf install gtk4-devel libadwaita-devel python3-gobject python3-pip cairo-devel python3-devel"
    exit 1
}

echo -e "${GREEN}[2/6]${NC} Creating installation directory..."
# Remove existing installation if present
if [[ -d "$INSTALL_DIR" ]]; then
    echo -e "${YELLOW}Existing installation found. Removing...${NC}"
    rm -rf "$INSTALL_DIR"
fi
mkdir -p "$INSTALL_DIR"

echo -e "${GREEN}[3/6]${NC} Copying application files..."
# Copy application files
cp -r "$SCRIPT_DIR/cybermind" "$INSTALL_DIR/"
cp "$SCRIPT_DIR/requirements.txt" "$INSTALL_DIR/"
cp "$SCRIPT_DIR/setup.py" "$INSTALL_DIR/"
cp "$SCRIPT_DIR/run.py" "$INSTALL_DIR/"
cp "$SCRIPT_DIR/README.md" "$INSTALL_DIR/"
cp "$SCRIPT_DIR/LICENSE" "$INSTALL_DIR/"

# Copy images if they exist
for img in cybermind.png cybermind_logo.png cybermind_horizontal.png cybermind_vertical.png; do
    if [[ -f "$SCRIPT_DIR/$img" ]]; then
        cp "$SCRIPT_DIR/$img" "$INSTALL_DIR/"
    fi
done

echo -e "${GREEN}[4/6]${NC} Creating Python virtual environment..."
python3 -m venv "$VENV_DIR"
source "$VENV_DIR/bin/activate"

echo -e "${GREEN}[5/6]${NC} Installing Python dependencies..."
pip install --upgrade pip wheel setuptools >/dev/null 2>&1
CYBERMIND_SKIP_PREFLIGHT=1 pip install -e "$INSTALL_DIR" >/dev/null 2>&1 || {
    echo -e "${YELLOW}Editable install failed, trying regular install...${NC}"
    pip install -r "$INSTALL_DIR/requirements.txt" >/dev/null 2>&1
}

echo -e "${GREEN}[6/6]${NC} Setting up system integration..."

# Create launcher script
cat > "$INSTALL_DIR/cybermind-launcher.sh" << 'LAUNCHER'
#!/bin/bash
# CyberMind Launcher
source /opt/cybermind/.venv/bin/activate
cd /opt/cybermind
exec python3 -m cybermind "$@"
LAUNCHER
chmod +x "$INSTALL_DIR/cybermind-launcher.sh"

# Create symlink in /usr/local/bin
rm -f "$BIN_LINK"
ln -s "$INSTALL_DIR/cybermind-launcher.sh" "$BIN_LINK"

# Install desktop file
cat > "$DESKTOP_FILE" << DESKTOP
[Desktop Entry]
Name=CyberMind
Comment=A hacker-aesthetic mindmap application
Exec=/opt/cybermind/cybermind-launcher.sh
Icon=cybermind
Terminal=false
Type=Application
Categories=Office;Graphics;
Keywords=mindmap;mind;map;brainstorm;diagram;security;
StartupNotify=true
DESKTOP

# Install icon (multiple sizes if available)
# Try various icon file names
ICON_SRC=""
for icon_file in cybermind.png cybermind_logo.png cybermind_horizontal.png cybermind_vertical.png; do
    if [[ -f "$INSTALL_DIR/$icon_file" ]]; then
        ICON_SRC="$INSTALL_DIR/$icon_file"
        break
    fi
done

if [[ -n "$ICON_SRC" ]]; then
    mkdir -p "$ICON_DIR/256x256/apps"
    mkdir -p "$ICON_DIR/128x128/apps"
    mkdir -p "$ICON_DIR/64x64/apps"
    mkdir -p "$ICON_DIR/48x48/apps"
    
    # Copy to various sizes (using same image, system will scale)
    cp "$ICON_SRC" "$ICON_DIR/256x256/apps/cybermind.png"
    cp "$ICON_SRC" "$ICON_DIR/128x128/apps/cybermind.png"
    cp "$ICON_SRC" "$ICON_DIR/64x64/apps/cybermind.png"
    cp "$ICON_SRC" "$ICON_DIR/48x48/apps/cybermind.png"
    
    # Update icon cache
    gtk-update-icon-cache -f -t "$ICON_DIR" 2>/dev/null || true
fi

# Update desktop database
update-desktop-database /usr/share/applications 2>/dev/null || true

# Set ownership (keep root for system install)
chmod -R 755 "$INSTALL_DIR"

echo ""
echo -e "${GREEN}╔═══════════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║          CyberMind installed successfully!                ║${NC}"
echo -e "${GREEN}╚═══════════════════════════════════════════════════════════╝${NC}"
echo ""
echo -e "Installation directory: ${CYAN}$INSTALL_DIR${NC}"
echo -e "Run from terminal:      ${CYAN}cybermind${NC}"
echo -e "Or find it in your application menu as ${CYAN}'CyberMind'${NC}"
echo ""
echo -e "${YELLOW}Note: User data is stored in ~/.local/share/cybermind/${NC}"
echo ""

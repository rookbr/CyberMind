#!/bin/bash
# CyberMind Uninstallation Script
# Removes CyberMind from /opt/cybermind

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

INSTALL_DIR="/opt/cybermind"
DESKTOP_FILE="/usr/share/applications/cybermind.desktop"
ICON_DIR="/usr/share/icons/hicolor"
BIN_LINK="/usr/local/bin/cybermind"

echo -e "${CYAN}CyberMind Uninstaller${NC}"
echo ""

if [[ $EUID -ne 0 ]]; then
    echo -e "${RED}Error: This script must be run as root (sudo)${NC}"
    echo "Usage: sudo ./uninstall.sh"
    exit 1
fi

echo -e "${YELLOW}This will remove CyberMind from your system.${NC}"
echo -e "${YELLOW}Your user data in ~/.local/share/cybermind/ will NOT be removed.${NC}"
read -p "Continue? (y/N) " -n 1 -r
echo

if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "Uninstallation cancelled."
    exit 0
fi

echo -e "${GREEN}Removing application files...${NC}"
rm -rf "$INSTALL_DIR"

echo -e "${GREEN}Removing desktop integration...${NC}"
rm -f "$DESKTOP_FILE"
rm -f "$BIN_LINK"

# Remove icons
rm -f "$ICON_DIR/256x256/apps/cybermind.png"
rm -f "$ICON_DIR/128x128/apps/cybermind.png"
rm -f "$ICON_DIR/64x64/apps/cybermind.png"
rm -f "$ICON_DIR/48x48/apps/cybermind.png"

# Update caches
gtk-update-icon-cache -f -t "$ICON_DIR" 2>/dev/null || true
update-desktop-database /usr/share/applications 2>/dev/null || true

echo ""
echo -e "${GREEN}CyberMind has been uninstalled.${NC}"
echo -e "${YELLOW}Note: Your data in ~/.local/share/cybermind/ was preserved.${NC}"
echo -e "${YELLOW}Remove it manually if you want to delete all user data.${NC}"

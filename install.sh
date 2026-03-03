#!/bin/bash
set -e

echo "Installing Voice-to-Text dependencies..."
echo ""

# Check for Python 3
if ! command -v python3 &> /dev/null; then
    echo "Error: python3 not found. Install it with: sudo apt install python3"
    exit 1
fi

# Check for pip3
if ! command -v pip3 &> /dev/null; then
    echo "Error: pip3 not found. Install it with: sudo apt install python3-pip"
    exit 1
fi

# Python packages
pip3 install -r requirements.txt

# tkinter (not available via pip, needed for the GUI)
echo ""
echo "Installing tkinter..."
sudo apt install -y python3-tk

# Linux system dependencies for clipboard and focus management
if [[ "$XDG_SESSION_TYPE" == "wayland" ]]; then
    echo "Detected Wayland - installing wtype and wl-clipboard..."
    sudo apt install -y wtype wl-clipboard
else
    echo "Detected X11 - installing xdotool and xclip..."
    sudo apt install -y xdotool xclip
fi

echo ""
echo "Done! Run: python3 speech_to_text.py"

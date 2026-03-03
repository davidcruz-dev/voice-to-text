# Voice-to-Text

A floating microphone widget that transcribes your speech and types it wherever your cursor is. Powered by OpenAI's Whisper running locally — no cloud, no API keys, fully offline after setup.

Works on **Windows**, **Linux**, and **WSL2**.

## Quick Start

### Windows

1. Double-click **`install.bat`** (works directly from the WSL folder — no need to copy files)
2. Double-click **`start.bat`**

### Linux

```bash
chmod +x install.sh
./install.sh
python3 speech_to_text.py
```

### WSL2

```bash
pip install -r requirements.txt    # only once
python.exe speech_to_text.py
```

## How to Use

1. A small floating mic button appears in the bottom-right corner
2. Click where you want to type (terminal, browser, any text field)
3. **Click the mic button** — it turns red (recording)
4. Speak — text appears in chunks every ~3 seconds
5. **Click the mic button again** — it turns orange (processing last chunk), then done
6. Right-click drag the button to move it anywhere

## Features

- **Live streaming** — text appears as you speak, not after you stop
- **Always-on-top widget** — small floating mic button, right-click drag to reposition
- **Auto-paste** — text goes directly into whatever window you were typing in
- **Offline** — runs 100% locally after initial model download (~500MB)
- **Hallucination filter** — suppresses common Whisper artifacts like "thank you for watching"
- **Pause detection** — adds spacing when you pause between sentences
- **Cross-platform** — Windows, Linux (X11 + Wayland), and WSL2

## Requirements

| Platform | Requirements |
|----------|-------------|
| **Windows** | Python 3.8+, a microphone |
| **Linux (X11)** | Python 3.8+, a microphone, `python3-tk`, `xdotool`, `xclip` |
| **Linux (Wayland)** | Python 3.8+, a microphone, `python3-tk`, `wtype`, `wl-copy` |
| **WSL2** | Windows Python 3.8+ (`python.exe`), a microphone |

Linux system dependencies are installed automatically by `install.sh`.

## Configuration

Edit these values at the top of `speech_to_text.py`:

| Setting | Default | Description |
|---------|---------|-------------|
| `MODEL_SIZE` | `"small"` | Whisper model (see table below) |
| `CHUNK_SECONDS` | `3` | How often text appears (lower = faster but less context) |

### Model comparison

| Model | Download | Speed | Accuracy |
|-------|----------|-------|----------|
| `tiny` | ~75MB | Fastest | Low |
| `base` | ~150MB | Fast | OK |
| **`small`** | **~500MB** | **Good** | **Good (default)** |
| `medium` | ~1.5GB | Slower | High |
| `large-v3` | ~3GB | Slowest | Highest |

The model downloads automatically on first run.

## Auto-Start with Windows (optional)

1. Press `Win+R`, type `shell:startup`, press Enter
2. Create a file called `speech-to-text.vbs` with this content:

```vbs
Set WshShell = CreateObject("WScript.Shell")
WshShell.Run "python.exe ""C:\path\to\speech_to_text.py""", 0, False
```

Replace `C:\path\to\` with the actual path to the script.

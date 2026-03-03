# Voice-to-Text

A floating microphone widget that transcribes your speech and types it wherever your cursor is. Powered by OpenAI's Whisper running locally — no cloud, no API keys, fully offline after setup.

## Quick Start (Windows)

1. **Install dependencies** — double-click `install.bat` or run:
   ```
   pip install -r requirements.txt
   ```

2. **Launch** — double-click `start.bat` or run:
   ```
   python speech_to_text.py
   ```

3. **Use it:**
   - Click the floating mic button to **start recording**
   - Speak — text appears in chunks every ~3 seconds
   - Click again to **stop**
   - Text is automatically pasted where your cursor was

## Features

- **Live streaming** — text appears as you speak, not after you stop
- **Always-on-top widget** — small floating mic button, right-click drag to reposition
- **Auto-paste** — text goes directly into whatever window you were typing in
- **Offline** — runs 100% locally after initial model download (~500MB)
- **Hallucination filter** — suppresses common Whisper artifacts like "thank you for watching"
- **Pause detection** — adds spacing when you pause between sentences

## Configuration

Edit these values at the top of `speech_to_text.py`:

| Setting | Default | Description |
|---------|---------|-------------|
| `MODEL_SIZE` | `"small"` | Whisper model: `tiny`, `base`, `small`, `medium`, `large-v3` |
| `CHUNK_SECONDS` | `3` | How often text appears (lower = faster but less context) |
| `SAMPLE_RATE` | `16000` | Audio sample rate (don't change unless needed) |

### Model comparison

| Model | Download | Speed | Accuracy |
|-------|----------|-------|----------|
| `tiny` | ~75MB | Fastest | Low |
| `base` | ~150MB | Fast | OK |
| `small` | ~500MB | Good | Good |
| `medium` | ~1.5GB | Slower | High |
| `large-v3` | ~3GB | Slowest | Highest |

## Requirements

- Windows 10/11
- Python 3.8+
- A microphone

## Auto-Start with Windows (optional)

Create a file called `speech-to-text.vbs` in your Startup folder:

```
Shell:startup
```

With this content:
```vbs
Set WshShell = CreateObject("WScript.Shell")
WshShell.Run "python.exe ""C:\path\to\speech_to_text.py""", 0, False
```

## WSL Users

Run with Windows Python to access the microphone:
```bash
python.exe speech_to_text.py
```

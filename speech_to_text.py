"""
Voice-to-Text Floating Widget
==============================
Cross-platform: Works on Windows, Linux, and WSL2.

A small floating microphone button that stays on top of all windows.
  - Click the button to START recording
  - Text appears in LIVE CHUNKS as you speak
  - Click again to STOP

Usage:
  Windows / WSL2:  python speech_to_text.py
  Linux:           python3 speech_to_text.py
"""

import sys
import os
import platform
import tempfile
import threading
import time
import subprocess
import numpy as np
import sounddevice as sd
import tkinter as tk

# Suppress faster-whisper logging noise
import logging
logging.getLogger("faster_whisper").setLevel(logging.ERROR)
logging.getLogger("ctranslate2").setLevel(logging.ERROR)

from faster_whisper import WhisperModel


SAMPLE_RATE = 16000
CHUNK_SECONDS = 3
MODEL_SIZE = "small"

# --- Platform detection ---
IS_WINDOWS = platform.system() == "Windows" or "microsoft" in platform.release().lower()
IS_LINUX = platform.system() == "Linux" and "microsoft" not in platform.release().lower()


# =============================================================================
# Platform-specific: Focus tracking and text pasting
# =============================================================================

if IS_WINDOWS:
    import ctypes
    user32 = ctypes.windll.user32

    class FocusTracker:
        """Track the last focused window (Windows)."""

        def __init__(self):
            self.last_hwnd = None
            self.our_hwnd = None
            self._running = True
            self._thread = threading.Thread(target=self._poll, daemon=True)
            self._thread.start()

        def set_our_hwnd(self, hwnd):
            self.our_hwnd = hwnd

        def register_widget(self, root):
            hwnd = root.winfo_id()
            top = user32.GetAncestor(hwnd, 2)
            self.set_our_hwnd(top)

        def _poll(self):
            while self._running:
                try:
                    hwnd = user32.GetForegroundWindow()
                    if hwnd and hwnd != self.our_hwnd:
                        self.last_hwnd = hwnd
                except Exception:
                    pass
                time.sleep(0.15)

        def stop(self):
            self._running = False

    def paste_text(hwnd, text):
        """Copy to clipboard and paste via Ctrl+V (Windows)."""
        # Copy to clipboard
        process = subprocess.Popen(
            ["clip.exe"],
            stdin=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
        process.communicate(input=text.encode("utf-16-le"))
        time.sleep(0.05)
        # Restore focus
        if hwnd:
            user32.SetForegroundWindow(hwnd)
            time.sleep(0.15)
        # Simulate Ctrl+V
        VK_CONTROL, VK_V = 0x11, 0x56
        KEYEVENTF_KEYUP = 0x0002
        user32.keybd_event(VK_CONTROL, 0, 0, 0)
        user32.keybd_event(VK_V, 0, 0, 0)
        time.sleep(0.05)
        user32.keybd_event(VK_V, 0, KEYEVENTF_KEYUP, 0)
        user32.keybd_event(VK_CONTROL, 0, KEYEVENTF_KEYUP, 0)

else:
    # Linux (X11 with xdotool/xclip, or Wayland with wtype/wl-copy)

    def _has_cmd(cmd):
        try:
            subprocess.run(
                ["which", cmd], capture_output=True, check=True
            )
            return True
        except (subprocess.CalledProcessError, FileNotFoundError):
            return False

    _USE_WAYLAND = os.environ.get("XDG_SESSION_TYPE") == "wayland"
    _HAS_XDOTOOL = _has_cmd("xdotool")
    _HAS_XCLIP = _has_cmd("xclip")
    _HAS_XSEL = _has_cmd("xsel")
    _HAS_WTYPE = _has_cmd("wtype")
    _HAS_WL_COPY = _has_cmd("wl-copy")

    class FocusTracker:
        """Track the last focused window (Linux)."""

        def __init__(self):
            self.last_hwnd = None
            self.our_hwnd = None
            self._running = True
            self._thread = threading.Thread(target=self._poll, daemon=True)
            self._thread.start()

        def set_our_hwnd(self, hwnd):
            self.our_hwnd = hwnd

        def register_widget(self, root):
            self.set_our_hwnd(root.winfo_id())

        def _poll(self):
            while self._running:
                try:
                    if _HAS_XDOTOOL and not _USE_WAYLAND:
                        result = subprocess.run(
                            ["xdotool", "getactivewindow"],
                            capture_output=True, text=True, timeout=1,
                        )
                        if result.returncode == 0:
                            hwnd = int(result.stdout.strip())
                            if hwnd != self.our_hwnd:
                                self.last_hwnd = hwnd
                except Exception:
                    pass
                time.sleep(0.15)

        def stop(self):
            self._running = False

    def _clipboard_copy(text):
        """Copy text to clipboard (Linux)."""
        if _USE_WAYLAND and _HAS_WL_COPY:
            proc = subprocess.Popen(
                ["wl-copy"], stdin=subprocess.PIPE, stderr=subprocess.DEVNULL,
            )
            proc.communicate(input=text.encode("utf-8"))
        elif _HAS_XCLIP:
            proc = subprocess.Popen(
                ["xclip", "-selection", "clipboard"],
                stdin=subprocess.PIPE, stderr=subprocess.DEVNULL,
            )
            proc.communicate(input=text.encode("utf-8"))
        elif _HAS_XSEL:
            proc = subprocess.Popen(
                ["xsel", "--clipboard", "--input"],
                stdin=subprocess.PIPE, stderr=subprocess.DEVNULL,
            )
            proc.communicate(input=text.encode("utf-8"))

    def _simulate_paste():
        """Simulate Ctrl+V (Linux)."""
        if _USE_WAYLAND and _HAS_WTYPE:
            subprocess.run(
                ["wtype", "-M", "ctrl", "-P", "v", "-p", "v", "-m", "ctrl"],
                stderr=subprocess.DEVNULL,
            )
        elif _HAS_XDOTOOL:
            subprocess.run(
                ["xdotool", "key", "--clearmodifiers", "ctrl+v"],
                stderr=subprocess.DEVNULL,
            )

    def _focus_window(hwnd):
        """Restore focus to a window (Linux)."""
        if hwnd and _HAS_XDOTOOL and not _USE_WAYLAND:
            subprocess.run(
                ["xdotool", "windowactivate", str(hwnd)],
                stderr=subprocess.DEVNULL,
            )

    def paste_text(hwnd, text):
        """Copy to clipboard, focus window, and paste (Linux)."""
        _clipboard_copy(text)
        time.sleep(0.05)
        _focus_window(hwnd)
        time.sleep(0.15)
        _simulate_paste()


# =============================================================================
# Cross-platform: Speech-to-Text engine
# =============================================================================

class SpeechToText:
    def __init__(self):
        self.model = None
        self.recording = False
        self.frames = []
        self.stream = None
        self.chunk_index = 0
        self._lock = threading.Lock()

    def load_model(self):
        self.model = WhisperModel(MODEL_SIZE, device="cpu", compute_type="int8")

    def audio_callback(self, indata, frame_count, time_info, status):
        if self.recording:
            with self._lock:
                self.frames.append(indata.copy())

    def start_recording(self):
        with self._lock:
            self.frames = []
            self.chunk_index = 0
        self.recording = True
        self.stream = sd.InputStream(
            samplerate=SAMPLE_RATE,
            channels=1,
            dtype="float32",
            callback=self.audio_callback,
        )
        self.stream.start()

    def stop_recording(self):
        self.recording = False
        if self.stream:
            self.stream.stop()
            self.stream.close()
            self.stream = None

    def get_new_audio_chunk(self):
        with self._lock:
            if self.chunk_index >= len(self.frames):
                return None
            new_frames = self.frames[self.chunk_index:]
            self.chunk_index = len(self.frames)
        return np.concatenate(new_frames, axis=0).flatten()

    def get_remaining_audio(self):
        return self.get_new_audio_chunk()

    def save_wav(self, audio_data, path):
        import wave
        audio_int16 = (audio_data * 32767).astype(np.int16)
        with wave.open(path, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(SAMPLE_RATE)
            wf.writeframes(audio_int16.tobytes())

    HALLUCINATIONS = {
        "thank you for watching", "thanks for watching",
        "thank you for listening", "thanks for listening",
        "please subscribe", "like and subscribe",
        "see you in the next video", "see you next time",
        "bye", "goodbye", "bye bye",
        "you", "the end", "...",
    }

    def transcribe(self, audio_data):
        if audio_data is None or len(audio_data) < SAMPLE_RATE * 0.3:
            return ""
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            wav_path = f.name
            self.save_wav(audio_data, wav_path)
        try:
            segments, _ = self.model.transcribe(
                wav_path,
                beam_size=3,
                language="en",
                vad_filter=True,
            )
            text = " ".join(seg.text.strip() for seg in segments).strip()
            if text.lower().rstrip(".!,") in self.HALLUCINATIONS:
                return ""
            return text
        finally:
            try:
                os.unlink(wav_path)
            except OSError:
                pass


# =============================================================================
# Cross-platform: Floating mic widget (tkinter)
# =============================================================================

class MicWidget:
    BG = "#1e1e2e"
    IDLE_FILL = "#313244"
    IDLE_RING = "#585b70"
    ICON_COLOR = "#cdd6f4"
    REC_FILL = "#d32f2f"
    REC_RING = "#ef5350"
    REC_PULSE = "#b71c1c"
    PROC_FILL = "#f57c00"
    PROC_RING = "#ffb74d"
    TIP_BG = "#313244"
    TIP_FG = "#cdd6f4"

    def __init__(self, stt, focus_tracker):
        self.stt = stt
        self.focus_tracker = focus_tracker
        self._stop_pulse = True
        self._streaming = False
        self._target_hwnd = None
        self._loading = True

        self.root = tk.Tk()
        self.root.title("Voice")
        self.root.attributes("-topmost", True)
        self.root.overrideredirect(True)
        try:
            self.root.attributes("-alpha", 0.92)
        except tk.TclError:
            pass  # Some Linux WMs don't support alpha
        self.root.configure(bg=self.BG)

        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        widget_size = 56
        pad = 24
        x = screen_w - widget_size - pad
        y = screen_h - widget_size - pad - 50
        self.root.geometry(f"{widget_size}x{widget_size}+{x}+{y}")

        self.canvas = tk.Canvas(
            self.root,
            width=widget_size,
            height=widget_size,
            bg=self.BG,
            highlightthickness=0,
        )
        self.canvas.pack()

        # Shadow ring
        self.canvas.create_oval(
            2, 2, 54, 54, fill="", outline="#11111b", width=2
        )

        # Main circle
        self.circle = self.canvas.create_oval(
            4, 4, 52, 52, fill=self.IDLE_FILL, outline=self.IDLE_RING, width=2
        )

        # Microphone icon
        cx, cy = 28, 24
        self.mic_body = self.canvas.create_oval(
            cx - 5, cy - 9, cx + 5, cy + 3,
            fill=self.ICON_COLOR, outline=""
        )
        self.mic_arc = self.canvas.create_arc(
            cx - 9, cy - 6, cx + 9, cy + 8,
            start=180, extent=180, style="arc",
            outline=self.ICON_COLOR, width=2
        )
        self.mic_stem = self.canvas.create_line(
            cx, cy + 8, cx, cy + 13,
            fill=self.ICON_COLOR, width=2
        )
        self.mic_base = self.canvas.create_line(
            cx - 5, cy + 13, cx + 5, cy + 13,
            fill=self.ICON_COLOR, width=2
        )

        # Status dot
        self.dot = self.canvas.create_oval(
            38, 38, 50, 50, fill=self.BG, outline=""
        )
        self.dot_inner = self.canvas.create_oval(
            40, 40, 48, 48, fill=self.IDLE_RING, outline=""
        )

        # Events
        self.canvas.bind("<Enter>", self._on_hover)
        self.canvas.bind("<Leave>", self._on_leave)
        self.canvas.bind("<Button-1>", self.on_click)

        # Right-click drag
        self._drag_x = 0
        self._drag_y = 0
        self.canvas.bind("<Button-3>", self._start_drag)
        self.canvas.bind("<B3-Motion>", self._do_drag)

        self.status_label = None

        self.root.after(100, lambda: self.focus_tracker.register_widget(self.root))

    def _on_hover(self, event):
        if not self.stt.recording:
            self.canvas.itemconfig(self.circle, outline="#89b4fa")
            self.root.configure(cursor="hand2")

    def _on_leave(self, event):
        if not self.stt.recording:
            self.canvas.itemconfig(self.circle, outline=self.IDLE_RING)
            self.root.configure(cursor="")

    def _start_drag(self, event):
        self._drag_x = event.x
        self._drag_y = event.y

    def _do_drag(self, event):
        x = self.root.winfo_x() + event.x - self._drag_x
        y = self.root.winfo_y() + event.y - self._drag_y
        self.root.geometry(f"+{x}+{y}")

    def on_click(self, event):
        if self._loading:
            return
        if not self.stt.recording:
            self._target_hwnd = self.focus_tracker.last_hwnd
            self.stt.start_recording()
            self._streaming = True
            self.set_recording_state(True)
            threading.Thread(target=self._stream_loop, daemon=True).start()
        else:
            self._streaming = False
            self.stt.stop_recording()
            self.set_processing_state()
            threading.Thread(target=self._flush_remaining, daemon=True).start()

    def _has_trailing_silence(self, audio, threshold=0.01, tail_seconds=0.5):
        tail_samples = int(SAMPLE_RATE * tail_seconds)
        if len(audio) < tail_samples:
            return False
        tail = audio[-tail_samples:]
        energy = np.sqrt(np.mean(tail ** 2))
        return energy < threshold

    def _stream_loop(self):
        while self._streaming:
            time.sleep(CHUNK_SECONDS)
            if not self._streaming:
                break

            chunk = self.stt.get_new_audio_chunk()
            if chunk is None or len(chunk) < SAMPLE_RATE * 0.5:
                continue

            has_pause = self._has_trailing_silence(chunk)

            text = self.stt.transcribe(chunk)
            if text:
                suffix = "  " if has_pause else " "
                paste_text(self._target_hwnd, text + suffix)
                self.root.after(0, lambda t=text: self._show_tooltip(t[:30]))

    def _flush_remaining(self):
        remaining = self.stt.get_remaining_audio()
        if remaining is not None and len(remaining) >= SAMPLE_RATE * 0.3:
            text = self.stt.transcribe(remaining)
            if text:
                paste_text(self._target_hwnd, " " + text + " ")

        self.root.after(0, lambda: self.set_idle_state("Done!"))

    def set_recording_state(self, recording):
        if recording:
            self.canvas.itemconfig(self.circle, fill=self.REC_FILL, outline=self.REC_RING)
            self.canvas.itemconfig(self.dot_inner, fill=self.REC_RING)
            self.canvas.itemconfig(self.mic_body, fill="#ffffff")
            self.canvas.itemconfig(self.mic_arc, outline="#ffffff")
            self.canvas.itemconfig(self.mic_stem, fill="#ffffff")
            self.canvas.itemconfig(self.mic_base, fill="#ffffff")
            self._pulse()
        else:
            self._stop_pulse = True

    def set_processing_state(self):
        self._stop_pulse = True
        self.canvas.itemconfig(self.circle, fill=self.PROC_FILL, outline=self.PROC_RING)
        self.canvas.itemconfig(self.dot_inner, fill=self.PROC_RING)

    def set_idle_state(self, msg=""):
        self.canvas.itemconfig(self.circle, fill=self.IDLE_FILL, outline=self.IDLE_RING)
        self.canvas.itemconfig(self.dot_inner, fill=self.IDLE_RING)
        self.canvas.itemconfig(self.mic_body, fill=self.ICON_COLOR)
        self.canvas.itemconfig(self.mic_arc, outline=self.ICON_COLOR)
        self.canvas.itemconfig(self.mic_stem, fill=self.ICON_COLOR)
        self.canvas.itemconfig(self.mic_base, fill=self.ICON_COLOR)
        if msg:
            self._show_tooltip(msg)

    def _pulse(self):
        self._stop_pulse = False
        self._pulse_on = True
        self._do_pulse()

    def _do_pulse(self):
        if self._stop_pulse:
            return
        if self._pulse_on:
            self.canvas.itemconfig(self.dot_inner, fill=self.REC_RING)
        else:
            self.canvas.itemconfig(self.dot_inner, fill=self.REC_PULSE)
        self._pulse_on = not self._pulse_on
        self.root.after(500, self._do_pulse)

    def _show_tooltip(self, text):
        if self.status_label:
            try:
                self.status_label.destroy()
            except Exception:
                pass
        x = self.root.winfo_x() - 80
        y = self.root.winfo_y() - 36

        self.status_label = tk.Toplevel(self.root)
        self.status_label.overrideredirect(True)
        self.status_label.attributes("-topmost", True)
        try:
            self.status_label.attributes("-alpha", 0.95)
        except tk.TclError:
            pass
        self.status_label.geometry(f"+{x}+{y}")
        self.status_label.configure(bg=self.TIP_BG)

        frame = tk.Frame(self.status_label, bg=self.TIP_BG, padx=1, pady=1)
        frame.pack()
        lbl = tk.Label(
            frame, text=text,
            bg=self.TIP_BG, fg=self.TIP_FG,
            font=("Segoe UI", 9),
            padx=10, pady=4,
        )
        lbl.pack()
        self.status_label.after(2500, self.status_label.destroy)

    def run(self):
        self.root.mainloop()
        self.focus_tracker.stop()


# =============================================================================
# Main
# =============================================================================

def main():
    if IS_LINUX:
        missing = []
        if not _USE_WAYLAND and not _HAS_XDOTOOL:
            missing.append("xdotool")
        if not _USE_WAYLAND and not _HAS_XCLIP and not _HAS_XSEL:
            missing.append("xclip")
        if _USE_WAYLAND and not _HAS_WTYPE:
            missing.append("wtype")
        if _USE_WAYLAND and not _HAS_WL_COPY:
            missing.append("wl-copy")
        if missing:
            print(f"Missing Linux dependencies: {', '.join(missing)}")
            print(f"Install with: sudo apt install {' '.join(missing)}")
            sys.exit(1)

    stt = SpeechToText()
    focus_tracker = FocusTracker()
    widget = MicWidget(stt, focus_tracker)

    widget._show_tooltip("Loading model...")

    def _load_model():
        print("Loading Whisper model...")
        stt.load_model()
        widget._loading = False
        widget.root.after(0, lambda: widget._show_tooltip("Ready!"))
        if IS_WINDOWS:
            plat = "Windows/WSL2"
        elif IS_LINUX and _USE_WAYLAND:
            plat = "Linux (Wayland)"
        else:
            plat = "Linux (X11)"
        print(f"Ready! Platform: {plat}")
        print(f"Streaming mode: text appears every ~{CHUNK_SECONDS}s while speaking.")
        print("Press Ctrl+C here to quit.\n")

    threading.Thread(target=_load_model, daemon=True).start()
    widget.run()


if __name__ == "__main__":
    main()

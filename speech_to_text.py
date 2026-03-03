"""
Speech-to-Text Floating Widget (WSL2 compatible)
=================================================
Run with Windows Python:  python.exe ~/speech-to-text.py

A small floating microphone button that stays on top of all windows.
  - Click the button to START recording
  - Text appears in LIVE CHUNKS as you speak
  - Click again to STOP

Uses 'base' model for fast streaming chunks.
First run downloads the Whisper model (~150MB).
"""

import sys
import os
import tempfile
import threading
import time
import ctypes
import subprocess
import numpy as np
import sounddevice as sd
import tkinter as tk

# Suppress logging noise before importing whisper
import logging
logging.disable(logging.WARNING)

from faster_whisper import WhisperModel


SAMPLE_RATE = 16000
CHUNK_SECONDS = 3  # Balance of speed and context
MODEL_SIZE = "small"  # Good accuracy, still fast

# Windows API
user32 = ctypes.windll.user32


class FocusTracker:
    """Continuously tracks the last focused window that isn't our widget."""

    def __init__(self):
        self.last_hwnd = None
        self.our_hwnd = None
        self._running = True
        self._thread = threading.Thread(target=self._poll, daemon=True)
        self._thread.start()

    def set_our_hwnd(self, hwnd):
        self.our_hwnd = hwnd

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


def copy_to_clipboard(text):
    """Copy text to Windows clipboard."""
    process = subprocess.Popen(
        ["clip.exe"],
        stdin=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    process.communicate(input=text.encode("utf-16-le"))


def paste_via_ctrl_v():
    """Simulate Ctrl+V keypress."""
    VK_CONTROL = 0x11
    VK_V = 0x56
    KEYEVENTF_KEYUP = 0x0002

    user32.keybd_event(VK_CONTROL, 0, 0, 0)
    user32.keybd_event(VK_V, 0, 0, 0)
    time.sleep(0.05)
    user32.keybd_event(VK_V, 0, KEYEVENTF_KEYUP, 0)
    user32.keybd_event(VK_CONTROL, 0, KEYEVENTF_KEYUP, 0)


def paste_text(hwnd, text):
    """Focus target window and paste text."""
    copy_to_clipboard(text)
    time.sleep(0.05)
    if hwnd:
        user32.SetForegroundWindow(hwnd)
        time.sleep(0.15)
    paste_via_ctrl_v()


class SpeechToText:
    def __init__(self):
        self.model = None
        self.recording = False
        self.frames = []
        self.stream = None
        self.chunk_index = 0  # Tracks how many frames have been transcribed
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
        """Get audio recorded since last chunk was taken."""
        with self._lock:
            if self.chunk_index >= len(self.frames):
                return None
            new_frames = self.frames[self.chunk_index:]
            self.chunk_index = len(self.frames)
        return np.concatenate(new_frames, axis=0).flatten()

    def get_remaining_audio(self):
        """Get any audio not yet transcribed."""
        return self.get_new_audio_chunk()

    def save_wav(self, audio_data, path):
        import wave
        audio_int16 = (audio_data * 32767).astype(np.int16)
        with wave.open(path, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(SAMPLE_RATE)
            wf.writeframes(audio_int16.tobytes())

    # Common Whisper hallucinations during silence
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
            # Filter out Whisper hallucinations
            if text.lower().rstrip(".!,") in self.HALLUCINATIONS:
                return ""
            return text
        finally:
            try:
                os.unlink(wav_path)
            except OSError:
                pass


class MicWidget:
    # Color scheme
    BG = "#1e1e2e"          # Dark background
    IDLE_FILL = "#313244"   # Slate gray button
    IDLE_RING = "#585b70"   # Subtle border
    ICON_COLOR = "#cdd6f4"  # Light text/icon
    REC_FILL = "#d32f2f"    # Red recording
    REC_RING = "#ef5350"    # Light red border
    REC_PULSE = "#b71c1c"   # Dark red pulse
    PROC_FILL = "#f57c00"   # Orange processing
    PROC_RING = "#ffb74d"   # Light orange border
    TIP_BG = "#313244"      # Tooltip background
    TIP_FG = "#cdd6f4"      # Tooltip text

    def __init__(self, stt, focus_tracker):
        self.stt = stt
        self.focus_tracker = focus_tracker
        self._stop_pulse = True
        self._streaming = False
        self._target_hwnd = None

        self.root = tk.Tk()
        self.root.title("Voice")
        self.root.attributes("-topmost", True)
        self.root.overrideredirect(True)
        self.root.attributes("-alpha", 0.92)
        self.root.configure(bg=self.BG)

        # Larger, easier to click
        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        widget_size = 56
        pad = 24
        x = screen_w - widget_size - pad
        y = screen_h - widget_size - pad - 50
        self.root.geometry(f"{widget_size}x{widget_size}+{x}+{y}")

        # Canvas
        self.canvas = tk.Canvas(
            self.root,
            width=widget_size,
            height=widget_size,
            bg=self.BG,
            highlightthickness=0,
        )
        self.canvas.pack()

        # Shadow ring (depth effect)
        self.canvas.create_oval(
            2, 2, 54, 54, fill="", outline="#11111b", width=2
        )

        # Main circle button
        self.circle = self.canvas.create_oval(
            4, 4, 52, 52, fill=self.IDLE_FILL, outline=self.IDLE_RING, width=2
        )

        # Draw a microphone icon with canvas shapes
        cx, cy = 28, 24
        # Mic body (rounded rectangle via oval)
        self.mic_body = self.canvas.create_oval(
            cx - 5, cy - 9, cx + 5, cy + 3,
            fill=self.ICON_COLOR, outline=""
        )
        # Mic stand arc
        self.mic_arc = self.canvas.create_arc(
            cx - 9, cy - 6, cx + 9, cy + 8,
            start=180, extent=180, style="arc",
            outline=self.ICON_COLOR, width=2
        )
        # Mic stem
        self.mic_stem = self.canvas.create_line(
            cx, cy + 8, cx, cy + 13,
            fill=self.ICON_COLOR, width=2
        )
        # Mic base
        self.mic_base = self.canvas.create_line(
            cx - 5, cy + 13, cx + 5, cy + 13,
            fill=self.ICON_COLOR, width=2
        )

        # Status indicator dot (bottom-right)
        self.dot = self.canvas.create_oval(
            38, 38, 50, 50, fill=self.BG, outline=""
        )
        self.dot_inner = self.canvas.create_oval(
            40, 40, 48, 48, fill=self.IDLE_RING, outline=""
        )

        # Hover effect
        self.canvas.bind("<Enter>", self._on_hover)
        self.canvas.bind("<Leave>", self._on_leave)
        self.canvas.bind("<Button-1>", self.on_click)

        # Right-click drag
        self._drag_x = 0
        self._drag_y = 0
        self.canvas.bind("<Button-3>", self._start_drag)
        self.canvas.bind("<B3-Motion>", self._do_drag)

        self.status_label = None

        self.root.after(100, self._register_hwnd)

    def _on_hover(self, event):
        if not self.stt.recording:
            self.canvas.itemconfig(self.circle, outline="#89b4fa")
            self.root.configure(cursor="hand2")

    def _on_leave(self, event):
        if not self.stt.recording:
            self.canvas.itemconfig(self.circle, outline=self.IDLE_RING)
            self.root.configure(cursor="")

    def _register_hwnd(self):
        hwnd = self.root.winfo_id()
        top = user32.GetAncestor(hwnd, 2)
        self.focus_tracker.set_our_hwnd(top)

    def _start_drag(self, event):
        self._drag_x = event.x
        self._drag_y = event.y

    def _do_drag(self, event):
        x = self.root.winfo_x() + event.x - self._drag_x
        y = self.root.winfo_y() + event.y - self._drag_y
        self.root.geometry(f"+{x}+{y}")

    def on_click(self, event):
        if not self.stt.recording:
            # Remember where to paste
            self._target_hwnd = self.focus_tracker.last_hwnd
            self.stt.start_recording()
            self._streaming = True
            self.set_recording_state(True)
            # Start the streaming transcription loop
            threading.Thread(target=self._stream_loop, daemon=True).start()
        else:
            # Stop recording
            self._streaming = False
            self.stt.stop_recording()
            self.set_processing_state()
            # Transcribe any remaining audio
            threading.Thread(target=self._flush_remaining, daemon=True).start()

    def _has_trailing_silence(self, audio, threshold=0.01, tail_seconds=0.5):
        """Check if the last portion of audio is silence (a pause)."""
        tail_samples = int(SAMPLE_RATE * tail_seconds)
        if len(audio) < tail_samples:
            return False
        tail = audio[-tail_samples:]
        energy = np.sqrt(np.mean(tail ** 2))
        return energy < threshold

    def _stream_loop(self):
        """Transcribe audio in chunks while recording."""
        while self._streaming:
            time.sleep(CHUNK_SECONDS)
            if not self._streaming:
                break

            chunk = self.stt.get_new_audio_chunk()
            if chunk is None or len(chunk) < SAMPLE_RATE * 0.5:
                continue

            # Detect if speaker paused at end of this chunk
            has_pause = self._has_trailing_silence(chunk)

            text = self.stt.transcribe(chunk)
            if text:
                suffix = "  " if has_pause else " "
                paste_text(self._target_hwnd, text + suffix)
                self.root.after(0, lambda t=text: self._show_tooltip(t[:30]))

    def _flush_remaining(self):
        """Transcribe any leftover audio after stop."""
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
            # White icon on red
            for item in (self.mic_body,):
                self.canvas.itemconfig(item, fill="#ffffff")
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
        # Restore icon color
        for item in (self.mic_body,):
            self.canvas.itemconfig(item, fill=self.ICON_COLOR)
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
        self.status_label.attributes("-alpha", 0.95)
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


def main():
    print("Loading Whisper model...")
    stt = SpeechToText()
    stt.load_model()
    print("Ready! The microphone widget should appear on screen.")
    print(f"Streaming mode: text appears every ~{CHUNK_SECONDS}s while speaking.")
    print("Press Ctrl+C here to quit.\n")

    focus_tracker = FocusTracker()
    widget = MicWidget(stt, focus_tracker)
    widget.run()


if __name__ == "__main__":
    main()

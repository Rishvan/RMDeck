"""
RMDeck (RV's Mix Deck) - mix the audio of the apps you pick (plus your mic)
and play the mix live on another output, e.g. the one feeding a streaming PC.

Windows 10 2004+ only. Requires: PyAudioWPatch, pycaw, psutil, numpy  (see requirements.txt)
"""
import os
import sys
import ctypes
import json
import logging
import logging.handlers
import queue
import threading
import time
import traceback
import tkinter as tk
from tkinter import messagebox, filedialog

import numpy as np
import psutil
import pyaudiowpatch as pyaudio
from PIL import ImageTk

import app_info
import ui_kit as ui
from ui_kit import (BG, CARD, BORDER, TEXT, MUTED, FAINT, GREEN, RED, ACCENT, HOVER,
                    font, set_bg)

try:
    import pystray
except Exception:  # tray icon is optional
    pystray = None

try:
    from pycaw.pycaw import AudioUtilities
except Exception:  # pycaw is optional - only used for the "Playing" status
    AudioUtilities = None

try:
    import app_capture
    if not app_capture.supported():
        app_capture = None
except Exception:  # per-app capture needs Windows 10 2004+
    app_capture = None

# pseudo-device used as the source when mixing the apps ticked in the list
APPS_SOURCE = {"index": -100, "name": "Selected apps", "kind": "apps",
               "maxInputChannels": 2, "defaultSampleRate": 48000}


APP_NAME = "RMDeck"
APP_FULL_NAME = "RV's Mix Deck"
APP_VERSION = "1.0.0"
AUTHOR = "Rishvan"

SETTINGS_PATH = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")),
                             "RMDeck", "settings.json")
# settings saved before the rename to RMDeck; read once if there are no new ones yet
OLD_SETTINGS_PATH = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")),
                                 "CaptureMonitor", "settings.json")
LOG_PATH = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")),
                        "RMDeck", "rmdeck.log")

MUTEX_NAME = "Local\\RMDeck.SingleInstance"
SHOW_EVENT = "Local\\RMDeck.Show"

log = logging.getLogger("rmdeck")


def setup_logging():
    """Log to %LOCALAPPDATA%\\RMDeck - the windowed app has no console."""
    try:
        os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
        h = logging.handlers.RotatingFileHandler(LOG_PATH, maxBytes=1_000_000, backupCount=2,
                                                 encoding="utf-8")
        h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(threadName)s %(message)s"))
        log.addHandler(h)
        log.setLevel(logging.INFO)
    except OSError:
        pass
    sys.excepthook = lambda t, v, tb: log.error("Unhandled error:\n%s",
                                                "".join(traceback.format_exception(t, v, tb)))
    threading.excepthook = lambda a: log.error(
        "Unhandled error in thread %s:\n%s", a.thread.name if a.thread else "?",
        "".join(traceback.format_exception(a.exc_type, a.exc_value, a.exc_traceback)))




_k32 = ctypes.WinDLL("kernel32", use_last_error=True)
_k32.CreateMutexW.restype = ctypes.c_void_p
_k32.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p]
_k32.CreateEventW.restype = ctypes.c_void_p
_k32.CreateEventW.argtypes = [ctypes.c_void_p, ctypes.c_bool, ctypes.c_bool, ctypes.c_wchar_p]
_k32.SetEvent.argtypes = [ctypes.c_void_p]
_k32.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
_k32.WaitForSingleObject.restype = ctypes.c_uint32
ERROR_ALREADY_EXISTS = 183


def is_packaged():
    """True when running as the Microsoft Store (MSIX) app."""
    try:
        n = ctypes.c_uint32(0)
        # ERROR_INSUFFICIENT_BUFFER (122) = has a package; 15700 = not packaged
        return ctypes.windll.kernel32.GetCurrentPackageFullName(ctypes.byref(n), None) == 122
    except Exception:
        return False


def claim_single_instance():
    """Returns the "show yourself" event if this is the first instance; otherwise
    wakes the running instance up and returns None."""
    _k32.CreateMutexW(None, False, MUTEX_NAME)  # handle lives as long as the process
    first = ctypes.get_last_error() != ERROR_ALREADY_EXISTS
    event = _k32.CreateEventW(None, False, False, SHOW_EVENT)
    if not first:
        _k32.SetEvent(event)
        return None
    return event


# --------------------------------------------------------------------------- #
#  Audio engine
# --------------------------------------------------------------------------- #
class AudioEngine:
    """Opens one source (input or the app mix) and plays it on a monitor output (Listen)."""

    def __init__(self):
        self.pa = pyaudio.PyAudio()
        self.src_stream = None
        self.mixer = None
        self.app_pids = set()
        self.app_gains = {}       # pid -> volume (1.0 = 100 %)
        self.mic_gain = 1.0
        self.noise_suppression = False
        self.mic_info = None
        self.src_info = None
        self.src_ch = 2
        self.src_rate = 48000

        self.listen_q = None
        self.listening = False
        self.listen_thread = None

        self.volume = 1.0
        self.level = 0.0
        self.error = None

    # ---------- devices ----------
    def reset(self):
        """Re-scan devices (only when nothing is running)."""
        self.pa.terminate()
        self.pa = pyaudio.PyAudio()

    def devices(self):
        """Return (sources, outputs, default_output_index) using WASAPI."""
        try:
            wasapi = self.pa.get_host_api_info_by_type(pyaudio.paWASAPI)
        except OSError:
            raise RuntimeError("WASAPI not available - this app needs Windows.")
        sources, outputs = [], []
        for i in range(self.pa.get_device_count()):
            d = self.pa.get_device_info_by_index(i)
            if d["hostApi"] != wasapi["index"]:
                continue
            if d.get("isLoopbackDevice"):
                sources.append(("[What's playing on] " + d["name"].replace(" [Loopback]", ""), d))
            elif d["maxInputChannels"] > 0:
                sources.append(("[Input] " + d["name"], d))
            elif d["maxOutputChannels"] > 0:
                outputs.append((d["name"], d))
        return sources, outputs, wasapi.get("defaultOutputDevice", -1)

    # ---------- source ----------
    def _callback(self, in_data, frame_count, time_info, status):
        a = np.frombuffer(in_data, dtype=np.float32)
        if self.src_ch >= 2:
            a = a.reshape(-1, self.src_ch)[:, :2]
        else:
            a = np.repeat(a.reshape(-1, 1), 2, axis=1)
        self._push(a)
        return (None, pyaudio.paContinue)

    def _on_mix(self, a):
        """Called by the app mixer with stereo float32 frames."""
        if self.mixer is not None and self.mixer.error:
            self.error, self.mixer.error = self.mixer.error, None
        self._push(a)

    def _push(self, a):
        peak = float(np.abs(a).max()) if a.size else 0.0
        self.level = max(self.level * 0.85, peak)

        lq = self.listen_q
        if lq is not None:
            lq.put(a.copy())

    def set_app_pids(self, pids):
        """Choose which apps feed the "Selected apps" source (works while running)."""
        self.app_pids = set(pids)
        if self.mixer is not None:
            self.mixer.set_pids(self.app_pids)

    def set_mic(self, info):
        """Mix an input device into the "Selected apps" source, or None (works while running)."""
        self.mic_info = info
        if self.mixer is not None:
            self.mixer.set_mic(info)

    def set_app_gains(self, gains):
        """Per-app volume as {pid: gain} (works while running)."""
        self.app_gains = dict(gains)
        if self.mixer is not None:
            self.mixer.set_gains(self.app_gains)

    def set_mic_gain(self, gain):
        self.mic_gain = gain
        if self.mixer is not None:
            self.mixer.set_mic_gain(gain)

    def set_noise_suppression(self, on):
        self.noise_suppression = bool(on)
        if self.mixer is not None:
            self.mixer.set_denoise(self.noise_suppression)

    def levels(self):
        """({pid: level}, mic level) while capturing apps, else ({}, 0)."""
        m = self.mixer
        return m.levels() if m is not None else ({}, 0.0)

    def _open_source(self, info):
        if self.src_info is not None:
            if self.src_info["index"] == info["index"]:
                return
            raise RuntimeError("Stop listening before switching source.")
        if info.get("kind") == "apps":
            if app_capture is None:
                raise RuntimeError("Per-app capture needs Windows 10 version 2004 or newer.")
            if not self.app_pids and self.mic_info is None:
                raise RuntimeError("Tick at least one running app in the list above, "
                                   "or turn on the microphone.")
            self.src_ch, self.src_rate = app_capture.CHANNELS, app_capture.RATE
            self.mixer = app_capture.AppMixer(self.app_pids, self._on_mix, pa=self.pa,
                                              mic=self.mic_info, pa_continue=pyaudio.paContinue,
                                              gains=self.app_gains, mic_gain=self.mic_gain,
                                              denoise=self.noise_suppression)
            self.src_info = info
            return
        self.src_ch = int(info["maxInputChannels"]) or 2
        self.src_rate = int(info["defaultSampleRate"])
        self.src_stream = self.pa.open(
            format=pyaudio.paFloat32, channels=self.src_ch, rate=self.src_rate,
            input=True, input_device_index=info["index"],
            frames_per_buffer=max(256, self.src_rate // 100),
            stream_callback=self._callback)
        self.src_info = info
        self.src_stream.start_stream()

    def _close_source_if_idle(self):
        if self.listening:
            return
        if self.src_stream is not None:
            try:
                self.src_stream.stop_stream()
                self.src_stream.close()
            except Exception:
                pass
            self.src_stream = None
        if self.mixer is not None:
            self.mixer.stop()
            self.mixer = None
        self.src_info = None
        self.level = 0.0

    # ---------- listen ----------
    def start_listen(self, src, dst):
        if src["index"] == dst["index"] or (
                src.get("isLoopbackDevice") and src["name"].startswith(dst["name"])):
            raise RuntimeError("Source and output are the same device - that would echo forever.\n"
                               "Pick your headphones/speakers as the output.")
        self.listen_q = queue.Queue()
        self._open_source(src)
        self.listening = True
        self.listen_thread = threading.Thread(target=self._listen_loop, args=(dst,), daemon=True)
        self.listen_thread.start()

    def stop_listen(self):
        self.listening = False
        self.listen_q = None
        if self.listen_thread:
            self.listen_thread.join(timeout=2)
        self.listen_thread = None
        self._close_source_if_idle()

    def _listen_loop(self, dst):
        out_ch = int(dst["maxOutputChannels"])
        out_rate = int(dst["defaultSampleRate"])
        q = self.listen_q
        out = None
        try:
            out = self.pa.open(format=pyaudio.paFloat32, channels=out_ch, rate=out_rate,
                               output=True, output_device_index=dst["index"],
                               frames_per_buffer=max(256, out_rate // 100))
            ratio = out_rate / float(self.src_rate)
            frac = 0.0
            while self.listening:
                # keep latency low: drop backlog if we fall behind
                while q.qsize() > 6:
                    try:
                        q.get_nowait()
                    except queue.Empty:
                        break
                try:
                    a = q.get(timeout=0.2)
                except queue.Empty:
                    continue
                if abs(ratio - 1.0) > 1e-6 and len(a) > 1:
                    target = len(a) * ratio + frac
                    n = int(target)
                    frac = target - n
                    xo = np.arange(len(a))
                    xn = np.linspace(0, len(a) - 1, n)
                    a = np.column_stack([np.interp(xn, xo, a[:, 0]), np.interp(xn, xo, a[:, 1])])
                a = a * self.volume
                if out_ch == 1:
                    a = a.mean(axis=1, keepdims=True)
                elif out_ch > 2:
                    a = np.hstack([a, np.zeros((len(a), out_ch - 2))])
                out.write(np.clip(a, -1, 1).astype(np.float32).tobytes())
        except Exception as e:
            self.error = "Listen error: %s" % e
            self.listening = False
        finally:
            if out is not None:
                try:
                    out.stop_stream()
                    out.close()
                except Exception:
                    pass

    def shutdown(self):
        if self.listening:
            self.stop_listen()
        self.pa.terminate()


# --------------------------------------------------------------------------- #
#  Add-app picker
# --------------------------------------------------------------------------- #
class AddAppDialog(tk.Toplevel):
    """Pick from the apps that are open now (real names and icons), or browse for any .exe."""

    def __init__(self, app, exclude, audio_pids, on_add):
        super().__init__(app)
        self.app, self.on_add, self.scale = app, on_add, app.scale
        S = app.S
        self.title("Add apps")
        self.configure(bg=BG)
        self.transient(app)
        self.geometry("%dx%d+%d+%d" % (S(460), S(580), app.winfo_rootx() + S(40),
                                       app.winfo_rooty() + S(20)))
        self.minsize(S(360), S(400))

        card = ui.Card(self, self.scale, expand=True, pad=18)
        card.pack(fill="both", expand=True, padx=S(14), pady=S(14))
        b = card.body
        tk.Label(b, text="Add apps", bg=CARD, fg=TEXT, font=font(13, True)).pack(anchor="w")
        tk.Label(b, text="Choose the apps whose sound you want to capture.", bg=CARD, fg=MUTED,
                 font=font(9)).pack(anchor="w", pady=(S(2), S(12)))
        self.query = tk.StringVar()
        self.query.trace_add("write", lambda *_: self._fill())
        search = ui.SearchField(b, self.scale, self.query, "Search apps")
        search.pack(fill="x")
        search.entry.focus_set()

        foot = tk.Frame(b, bg=CARD)
        foot.pack(fill="x", side="bottom", pady=(S(12), 0))
        ui.Link(foot, "Browse for a program…", self._browse).pack(side="left")
        self.add_btn = ui.RoundButton(foot, "Add", self._add, self.scale, "primary",
                                      min_width=96)
        self.add_btn.pack(side="right")
        ui.RoundButton(foot, "Cancel", self.destroy, self.scale, "neutral",
                       min_width=84).pack(side="right", padx=S(8))

        self.area = ui.ScrollArea(b, self.scale)
        self.area.pack(fill="both", expand=True, pady=(S(10), 0))
        self.msg = tk.Label(self.area.inner, text="Finding your apps…", bg=CARD, fg=MUTED,
                            font=font(9))
        self.msg.pack(pady=S(30))

        self.apps, self.selected, self.images = [], set(), {}
        self.rows = []      # (entry, row widget) in display order
        self.headers = {}   # section -> header label
        self._found = queue.Queue()
        threading.Thread(target=lambda: self._found.put(self._find_apps(exclude, audio_pids)),
                         daemon=True).start()
        self._wait()
        self._update_add_btn()
        self.bind("<Return>", lambda _e: self._add())
        self.bind("<Escape>", lambda _e: self.destroy())
        self.grab_set()

    def _wait(self):
        try:
            self.apps = self._found.get_nowait()
        except queue.Empty:
            self.after(40, self._wait)
            return
        self.msg.destroy()
        self._build_list()
        self._fill()

    @staticmethod
    def _find_apps(exclude, audio_pids):
        """Entries for the picker, on a worker thread: apps open now (a window or
        playing audio), then the installed apps from the Start menu."""
        windir = os.environ.get("WINDIR", r"C:\Windows").lower()
        own = os.path.normcase(psutil.Process().exe())
        pids = app_info.window_pids() | set(audio_pids)
        entries, seen = [], set(exclude)

        def entry(section, exe_path, name=None):
            info = app_info.get_info(exe_path)
            return {"section": section, "key": info["exe"].lower(), "exe": info["exe"],
                    "path": exe_path, "name": name or info["name"],
                    "publisher": info["publisher"],
                    "png": app_info.get_icon_png(exe_path, large=False)}

        opened = []
        for p in psutil.process_iter(["name", "exe"]):
            exe, name = p.info["exe"], p.info["name"]
            if p.pid not in pids or not exe or not name or name.lower() in seen:
                continue
            if exe.lower().startswith(windir) or os.path.normcase(exe) == own:
                continue
            seen.add(name.lower())
            opened.append(entry("open", exe))
        entries += sorted(opened, key=lambda e: e["name"].lower())

        try:
            installed = app_info.installed_apps()
        except Exception:
            installed = []
        open_names = {e["name"].lower() for e in opened}
        for name, path in installed:
            key = os.path.basename(path).lower()
            # a game's shortcut often points at its launcher ("VALORANT" -> Riot Client);
            # when the game itself is open, list it only once
            if key in seen or name.lower() in open_names or os.path.normcase(path) == own:
                continue
            seen.add(key)
            entries.append(entry("installed", path, name))
        return entries

    SECTIONS = (("open", "Open now"), ("installed", "Installed apps"))

    def _build_list(self):
        """Create every row once; searching only shows / hides them."""
        S = self.app.S
        inner = self.area.inner
        for section, title in self.SECTIONS:
            self.headers[section] = tk.Label(inner, text=title.upper(), bg=CARD, fg=FAINT,
                                             font=font(8, True), anchor="w")
            for e in self.apps:
                if e["section"] != section:
                    continue
                row = ui.HoverRow(inner, self.scale, pad_y=7)
                if e["png"]:
                    img = self.images[e["path"]] = ui.png_image(e["png"])
                    tk.Label(row.body, image=img, bg=CARD).pack(side="left")
                else:
                    ui.letter_tile(row.body, e["name"], S(24)).pack(side="left")
                check = ui.CheckMark(row.body, self.scale)
                check.pack(side="right")
                txt = tk.Frame(row.body, bg=CARD)
                txt.pack(side="left", fill="x", expand=True, padx=(S(12), S(10)))
                ui.ElideLabel(txt, e["name"], bg=CARD, fg=TEXT,
                              font=font(10, True)).pack(fill="x")
                sub = " · ".join(x for x in (e["publisher"], e["exe"]) if x)
                ui.ElideLabel(txt, sub, bg=CARD, fg=MUTED, font=font(8)).pack(fill="x")
                row.finish(lambda k=e["key"], r=row, c=check: self._toggle(k, r, c))
                e["search"] = ("%s %s %s" % (e["name"], e["exe"], e["publisher"])).lower()
                self.rows.append((e, row))
        self.empty = tk.Label(inner, bg=CARD, fg=MUTED, font=font(9),
                              text="No apps match.\nUse “Browse for a program…” to pick any app.")

    def _fill(self):
        if not self.headers:  # still loading
            return
        S = self.app.S
        q = self.query.get().lower().strip()
        for w in self.area.inner.winfo_children():
            w.pack_forget()
        shown = 0
        for section, _title in self.SECTIONS:
            rows = [r for e, r in self.rows if e["section"] == section
                    and (not q or q in e["search"])]
            if not rows:
                continue
            self.headers[section].pack(fill="x", padx=S(10),
                                       pady=(S(14) if shown else S(2), S(4)))
            for r in rows:
                r.pack(fill="x", pady=(0, S(2)))
            shown += len(rows)
        if not shown:
            self.empty.pack(pady=S(30))
        self.area.canvas.yview_moveto(0)
        self.area.fit()

    def _toggle(self, key, row, check):
        self.selected.symmetric_difference_update({key})
        on = key in self.selected
        row.set_selected(on)
        check.set(on)
        self._update_add_btn()

    def _update_add_btn(self):
        n = len(self.selected)
        self.add_btn.set(text="Add %d apps" % n if n > 1 else "Add", enabled=n > 0)

    def _add(self):
        picked = [(e["exe"], e["path"], e["name"]) for e in self.apps
                  if e["key"] in self.selected]
        if picked:
            self.on_add(picked)
            self.destroy()

    def _browse(self):
        path = filedialog.askopenfilename(parent=self, title="Choose a program",
                                          filetypes=[("Programs", "*.exe")])
        if path:
            path = os.path.normpath(path)
            self.on_add([(os.path.basename(path), path, None)])
            self.destroy()


# --------------------------------------------------------------------------- #
#  Settings popup
# --------------------------------------------------------------------------- #
class SettingsDialog(tk.Toplevel):
    """Small modal settings window, centred on the main window."""

    def __init__(self, app):
        super().__init__(app)
        S, self.app = app.S, app
        self.title("Settings")
        self.configure(bg=BG)
        self.transient(app)
        self.resizable(False, False)
        w = S(460)

        card = ui.Card(self, app.scale, pad=22)
        card.pack(fill="both", expand=True, padx=S(14), pady=S(14))
        b = card.body
        tk.Label(b, text="Settings", bg=CARD, fg=TEXT, font=font(14, True)).pack(anchor="w")

        tk.Label(b, text="GENERAL", bg=CARD, fg=FAINT,
                 font=font(8, True)).pack(anchor="w", pady=(S(18), S(8)))
        row = tk.Frame(b, bg=CARD)
        row.pack(fill="x")
        sw = ui.Switch(row, app.scale, app.background, app._background_changed)
        sw.pack(side="right", anchor="n", pady=(S(2), 0))
        txt = tk.Frame(row, bg=CARD)
        txt.pack(side="left", fill="x", expand=True, padx=(0, S(16)))
        title = tk.Label(txt, text="Run in background", bg=CARD, fg=TEXT, font=font(10, True),
                         anchor="w", cursor="hand2")
        title.pack(fill="x")
        title.bind("<Button-1>", lambda _e: sw._click(None))
        tk.Label(txt, text="When you close the window, RMDeck keeps playing your apps "
                           "and stays in the system tray. Quit from the tray icon.",
                 bg=CARD, fg=MUTED, font=font(9), anchor="w", justify="left",
                 wraplength=w - S(150)).pack(fill="x", pady=(S(2), 0))

        tk.Frame(b, bg=BORDER, height=1).pack(fill="x", pady=S(20))

        tk.Label(b, text="ABOUT", bg=CARD, fg=FAINT,
                 font=font(8, True)).pack(anchor="w", pady=(0, S(8)))
        about = tk.Frame(b, bg=CARD)
        about.pack(fill="x")
        self._logo = ImageTk.PhotoImage(ui.app_logo(S(40)))
        tk.Label(about, image=self._logo, bg=CARD).pack(side="left")
        info = tk.Frame(about, bg=CARD)
        info.pack(side="left", padx=(S(12), 0))
        tk.Label(info, text="%s  ·  %s" % (APP_NAME, APP_FULL_NAME), bg=CARD, fg=TEXT,
                 font=font(10, True),
                 anchor="w").pack(fill="x")
        tk.Label(info, text="Version %s  ·  Developed by %s" % (APP_VERSION, AUTHOR),
                 bg=CARD, fg=MUTED, font=font(9), anchor="w").pack(fill="x")

        foot = tk.Frame(b, bg=CARD)
        foot.pack(fill="x", pady=(S(24), 0))
        ui.RoundButton(foot, "Done", self.destroy, app.scale, "primary",
                       min_width=96).pack(side="right")

        self.bind("<Escape>", lambda _e: self.destroy())
        self.bind("<Return>", lambda _e: self.destroy())
        self.update_idletasks()
        h = self.winfo_reqheight()
        x = app.winfo_rootx() + (app.winfo_width() - w) // 2
        y = app.winfo_rooty() + (app.winfo_height() - h) // 3
        self.geometry("%dx%d+%d+%d" % (w, h, x, y))
        self.grab_set()
        self.focus_force()


# --------------------------------------------------------------------------- #
#  Main window
# --------------------------------------------------------------------------- #
class App(tk.Tk):
    def __init__(self, show_event=None):
        super().__init__(className="RMDeck")
        self.show_event = show_event
        self.title("RMDeck — %s" % APP_FULL_NAME)
        self.configure(bg=BG)
        self.scale = max(1.0, self.winfo_fpixels("1i") / 96.0)
        S = self.S
        self.geometry("%dx%d" % (S(1120), S(630)))  # 16:9
        self.minsize(S(1040), S(585))
        self._icons = [ImageTk.PhotoImage(ui.app_logo(n)) for n in (16, 24, 32, 48, 256)]
        self.iconphoto(True, *self._icons)

        self.engine = AudioEngine()
        self.added = {}           # lower-case exe name -> {"exe": name, "path": full path or None}
        self.use_names = set()    # exe names (lower-case) switched on
        self.app_volumes = {}     # exe key -> volume in % (missing = 100)
        self.outputs, self.mics = [], []
        self.rows = {}            # exe key -> (status label, switch)
        self.images = []
        self.snap, self.playing, self.audio_pids = None, set(), set()
        self.background = False
        self.saved = {}
        self._load_settings()

        self.tray = None
        self._told_tray = False
        self.ui_q, self.poll_q = queue.Queue(), queue.Queue()
        self._stop = threading.Event()
        self._chip_state = None

        self._build()
        try:
            self._lock_aspect()
        except Exception:
            log.exception("Could not lock the window to 16:9")
        self.refresh_devices()
        self.snap = self._proc_snapshot()  # correct "Open / Not running" from the start
        self._build_rows()
        threading.Thread(target=self._poll_worker, daemon=True, name="poll").start()
        if self.background:
            self._ensure_tray()
        self.after(100, self._tick)
        self.protocol("WM_DELETE_WINDOW", self._close_requested)
        log.info("RMDeck %s started", APP_VERSION)

    def report_callback_exception(self, exc, val, tb):
        """Errors inside Tk callbacks: log them and tell the user once."""
        log.error("Error in UI callback:\n%s", "".join(traceback.format_exception(exc, val, tb)))
        if not getattr(self, "_error_shown", False):
            self._error_shown = True
            messagebox.showerror(APP_NAME, "Something went wrong:\n%s\n\nDetails were saved to:\n%s"
                                 % (val, LOG_PATH), parent=self)

    def S(self, v):
        return int(v * self.scale)

    # ---------- layout ----------
    def _build(self):
        S = self.S
        # footer: credit + memory usage + version
        foot = tk.Frame(self, bg=BG)
        foot.pack(fill="x", side="bottom", padx=S(22), pady=(0, S(12)))
        tk.Label(foot, text="Developed by ", bg=BG, fg=FAINT, font=font(9)).pack(side="left")
        tk.Label(foot, text=AUTHOR, bg=BG, fg=MUTED, font=font(9, True)).pack(side="left")
        tk.Label(foot, text="v" + APP_VERSION, bg=BG, fg=FAINT,
                 font=font(9)).pack(side="right", padx=(S(14), 0))
        self.mem_lbl = tk.Label(foot, text="", bg=BG, fg=MUTED, font=font(9))
        self.mem_lbl.pack(side="right")

        page = tk.Frame(self, bg=BG)
        page.pack(fill="both", expand=True, padx=S(20), pady=(S(18), S(12)))

        head = tk.Frame(page, bg=BG)
        head.pack(fill="x")
        self._logo = ImageTk.PhotoImage(ui.app_logo(S(40)))
        tk.Label(head, image=self._logo, bg=BG).pack(side="left")
        titles = tk.Frame(head, bg=BG)
        titles.pack(side="left", fill="x", expand=True, padx=(S(12), 0))
        tk.Label(titles, text="RMDeck", bg=BG, fg=TEXT,
                 font=font(15, True), anchor="w").pack(fill="x")
        ui.ElideLabel(titles, "%s  ·  Mix the apps you choose with your mic and listen live."
                      % APP_FULL_NAME,
                      bg=BG, fg=MUTED, font=font(9)).pack(fill="x")
        ui.RoundButton(head, "⚙   Settings", self.open_settings, self.scale, "outline", bg=BG,
                       height=34).pack(side="right")
        self.chip = tk.Canvas(head, bg=BG, highlightthickness=0, height=S(28), width=S(90))
        self.chip.pack(side="right", padx=(0, S(10)))

        self.grid_frame = tk.Frame(page, bg=BG)
        self.grid_frame.pack(fill="both", expand=True, pady=(S(16), 0))

        # -- apps
        self.apps_card = ui.Card(self.grid_frame, self.scale, expand=True)
        b = self.apps_card.body
        h = tk.Frame(b, bg=CARD)
        h.pack(fill="x")
        tk.Label(h, text="Apps", bg=CARD, fg=TEXT, font=font(11, True)).pack(side="left")
        self.apps_count = tk.Label(h, text="", bg=CARD, fg=FAINT, font=font(9))
        self.apps_count.pack(side="left", padx=(S(8), 0))
        ui.RoundButton(h, "+  Add app", self.add_app_dialog, self.scale, "soft",
                       height=32).pack(side="right")
        self.apps_area = ui.ScrollArea(b, self.scale)
        self.apps_area.pack(fill="both", expand=True, pady=(S(10), 0))

        # -- microphone
        self.mic_card = ui.Card(self.grid_frame, self.scale)
        b = self.mic_card.body
        h = tk.Frame(b, bg=CARD)
        h.pack(fill="x")
        tk.Label(h, text="Microphone", bg=CARD, fg=TEXT, font=font(11, True)).pack(side="left")
        self.mic_switch = ui.Switch(h, self.scale, command=lambda _v: self._mic_changed())
        self.mic_switch.pack(side="right")
        self.mic_dd = ui.Dropdown(b, self.scale, on_change=lambda _i: self._mic_changed(),
                                  placeholder="No microphone found")
        self.mic_dd.pack(fill="x", pady=(S(12), 0))
        row = tk.Frame(b, bg=CARD)
        row.pack(fill="x", pady=(S(12), 0))
        tk.Label(row, text="Volume", bg=CARD, fg=MUTED, font=font(9), width=7,
                 anchor="w").pack(side="left")
        self.mic_vol_lbl = tk.Label(row, text="", bg=CARD, fg=TEXT, font=font(9), width=5,
                                    anchor="e")
        self.mic_vol_lbl.pack(side="right")
        self.mic_slider = ui.Slider(row, self.scale, value=self.saved.get("mic_volume", 100),
                                    command=self._mic_volume_changed)
        self.mic_slider.pack(side="left", fill="x", expand=True, padx=(0, S(6)))
        self._mic_volume_changed(self.mic_slider.value, save=False)
        row = tk.Frame(b, bg=CARD)
        row.pack(fill="x", pady=(S(12), 0))
        self.ns_switch = ui.Switch(row, self.scale, self.saved.get("noise_suppression", False),
                                   command=self._noise_changed)
        self.ns_switch.pack(side="right")
        txt = tk.Frame(row, bg=CARD)
        txt.pack(side="left", fill="x", expand=True, padx=(0, S(12)))
        lbl = tk.Label(txt, text="Noise suppression", bg=CARD, fg=TEXT, font=font(9, True),
                       anchor="w", cursor="hand2")
        lbl.pack(fill="x")
        lbl.bind("<Button-1>", lambda _e: self.ns_switch._click(None))
        ui.ElideLabel(txt, "Removes background noise like fans, hum and typing.",
                      bg=CARD, fg=MUTED, font=font(8)).pack(fill="x")
        self.engine.set_noise_suppression(self.ns_switch.value)

        # -- output
        self.out_card = ui.Card(self.grid_frame, self.scale)
        b = self.out_card.body
        h = tk.Frame(b, bg=CARD)
        h.pack(fill="x")
        tk.Label(h, text="Listen on", bg=CARD, fg=TEXT, font=font(11, True)).pack(side="left")
        ui.Link(h, "Refresh devices", self.refresh_devices).pack(side="right")
        self.out_dd = ui.Dropdown(b, self.scale, on_change=lambda _i: self._save_settings(),
                                  placeholder="No output found")
        self.out_dd.pack(fill="x", pady=(S(12), 0))
        row = tk.Frame(b, bg=CARD)
        row.pack(fill="x", pady=(S(14), 0))
        tk.Label(row, text="Volume", bg=CARD, fg=MUTED, font=font(9), width=7,
                 anchor="w").pack(side="left")
        self.vol_lbl = tk.Label(row, text="", bg=CARD, fg=TEXT, font=font(9), width=5,
                                anchor="e")
        self.vol_lbl.pack(side="right")
        self.slider = ui.Slider(row, self.scale, value=self.saved.get("volume", 100),
                                command=self._volume_changed)
        self.slider.pack(side="left", fill="x", expand=True, padx=(0, S(6)))
        self._volume_changed(self.slider.value, save=False)
        row = tk.Frame(b, bg=CARD)
        row.pack(fill="x", pady=(S(10), 0))
        tk.Label(row, text="Level", bg=CARD, fg=MUTED, font=font(9), width=7,
                 anchor="w").pack(side="left")
        self.meter = ui.LevelBar(row, self.scale)
        self.meter.pack(side="left", fill="x", expand=True, padx=(S(9), S(9)))

        # -- actions
        self.act_card = ui.Card(self.grid_frame, self.scale)
        b = self.act_card.body
        btns = tk.Frame(b, bg=CARD)
        btns.pack(fill="x")
        self.listen_btn = ui.RoundButton(btns, "", self.toggle_listen, self.scale, "soft",
                                         height=44, expand=True)
        self.listen_btn.pack(side="left", fill="x", expand=True)
        self.status = ui.ElideLabel(b, "Ready.", bg=CARD, fg=MUTED, font=font(9))
        self.status.pack(fill="x", pady=(S(10), 0))
        self._set_buttons()

        # apps on the left, everything else on the right
        g, gap = self.grid_frame, S(12)
        g.columnconfigure(0, weight=3, uniform="col")
        g.columnconfigure(1, weight=2, uniform="col")
        self.apps_card.grid(row=0, column=0, rowspan=4, sticky="nsew", padx=(0, gap))
        self.mic_card.grid(row=0, column=1, sticky="new", pady=(0, gap))
        self.out_card.grid(row=1, column=1, sticky="new", pady=(0, gap))
        self.act_card.grid(row=2, column=1, sticky="new")
        g.rowconfigure(3, weight=1)

    def _lock_aspect(self):
        """Keep the window's content at 16:9 *while* the user drags an edge, by
        adjusting the sizing rectangle Windows proposes (WM_SIZING) - no snapping
        afterwards."""
        from ctypes import wintypes
        u = ctypes.windll.user32
        WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, wintypes.HWND, wintypes.UINT,
                                     wintypes.WPARAM, wintypes.LPARAM)
        u.CallWindowProcW.argtypes = [ctypes.c_void_p, wintypes.HWND, wintypes.UINT,
                                      wintypes.WPARAM, wintypes.LPARAM]
        u.CallWindowProcW.restype = ctypes.c_ssize_t
        u.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_void_p]
        u.SetWindowLongPtrW.restype = ctypes.c_void_p
        WM_SIZING, GWLP_WNDPROC = 0x0214, -4
        LEFT, RIGHT, TOP, TOPLEFT, TOPRIGHT, BOTTOM = 1, 2, 3, 4, 5, 6
        self.update_idletasks()
        hwnd = int(self.wm_frame(), 16)
        min_w, min_h = self.S(1040), self.S(585)

        def proc(h, msg, wp, lp):
            if msg == WM_SIZING:
                try:
                    win, cli = wintypes.RECT(), wintypes.RECT()
                    u.GetWindowRect(h, ctypes.byref(win))
                    u.GetClientRect(h, ctypes.byref(cli))
                    ncx = (win.right - win.left) - cli.right   # borders + title bar
                    ncy = (win.bottom - win.top) - cli.bottom
                    r = wintypes.RECT.from_address(lp)
                    cw = max(min_w, r.right - r.left - ncx)
                    ch = max(min_h, r.bottom - r.top - ncy)
                    if wp in (TOP, BOTTOM):          # dragging a horizontal edge
                        cw = round(ch * 16 / 9)
                    else:
                        ch = round(cw * 9 / 16)
                    if wp in (LEFT, TOPLEFT, 7):     # 7 = bottom-left
                        r.left = r.right - cw - ncx
                    else:
                        r.right = r.left + cw + ncx
                    if wp in (TOP, TOPLEFT, TOPRIGHT):
                        r.top = r.bottom - ch - ncy
                    else:
                        r.bottom = r.top + ch + ncy
                    return 1
                except Exception:
                    log.exception("aspect lock")
            return u.CallWindowProcW(self._old_wndproc, h, msg, wp, lp)

        self._wndproc = WNDPROC(proc)  # keep a reference for the window's lifetime
        self._old_wndproc = u.SetWindowLongPtrW(hwnd, GWLP_WNDPROC,
                                                ctypes.cast(self._wndproc, ctypes.c_void_p))

    def _draw_chip(self):
        e = self.engine
        if e.listening:
            state = ("●  Listening", ACCENT, ui.ACCENT_SOFT)
        else:
            state = ("Idle", MUTED, CARD)
        if state == self._chip_state:
            return
        self._chip_state = state
        text, fg, fill = state
        f = font(9, True)
        w, h = f.measure(text) + self.S(28), self.S(28)
        self.chip.configure(width=w)
        self.chip.delete("all")
        self._chip_img = ui.rounded_image(w, h, h // 2, fill, BORDER if fill == CARD else None)
        self.chip.create_image(0, 0, anchor="nw", image=self._chip_img)
        self.chip.create_text(w / 2, h / 2, text=text, fill=fg, font=f)

    # ---------- app rows ----------
    def _info(self, key):
        a = self.added[key]
        info = app_info.get_info(a["path"], a["exe"])
        # the Start-menu name ("Steam") reads better than some exe descriptions
        return dict(info, name=a["name"]) if a.get("name") else info

    def _build_rows(self):
        S = self.S
        inner = self.apps_area.inner
        for w in inner.winfo_children():
            w.destroy()
        self.rows, self.images = {}, []
        if not self.added:
            box = tk.Frame(inner, bg=CARD)
            box.pack(fill="x", pady=S(28))
            tk.Label(box, text="No apps yet", bg=CARD, fg=TEXT, font=font(11, True)).pack()
            tk.Label(box, text="Add the apps you want to hear.\n"
                               "Only the apps in this list are captured.",
                     bg=CARD, fg=MUTED, font=font(9), justify="center").pack(pady=(S(4), S(14)))
            ui.RoundButton(box, "+  Add your first app", self.add_app_dialog, self.scale,
                           "primary").pack()
            self._update_count()
            self.apps_area.fit()
            return
        for key in sorted(self.added, key=lambda k: self._info(k)["name"].lower()):
            info = self._info(key)
            row = ui.HoverRow(inner, self.scale)
            row.pack(fill="x", pady=(0, S(2)))
            b = row.body
            png = app_info.get_icon_png(info["path"])
            if png:
                img = ui.png_image(png)
                self.images.append(img)
                tk.Label(b, image=img, bg=CARD).pack(side="left")
            else:
                ui.letter_tile(b, info["name"], S(32)).pack(side="left")

            rm = tk.Label(b, text="✕", bg=CARD, fg=FAINT, cursor="hand2", font=font(10),
                          padx=S(6))
            rm.own_click = True
            rm.pack(side="right", padx=(S(6), 0))
            rm.bind("<Button-1>", lambda _e, k=key: self.remove_app(k))
            rm.bind("<Enter>", lambda _e, w=rm: w.configure(fg=RED))
            rm.bind("<Leave>", lambda _e, w=rm: w.configure(fg=FAINT))
            sw = ui.Switch(b, self.scale, key in self.use_names,
                           lambda v, k=key: self._toggle_use(k, v))
            sw.own_click = True
            sw.pack(side="right")
            status = tk.Label(b, bg=CARD, font=font(9), anchor="e", width=11)
            status.pack(side="right", padx=(S(8), S(12)))

            txt = tk.Frame(b, bg=CARD)
            txt.pack(side="left", fill="x", expand=True, padx=(S(12), 0))
            ui.ElideLabel(txt, info["name"], bg=CARD, fg=TEXT, font=font(10, True)).pack(fill="x")
            sub = " · ".join(x for x in (info["publisher"], info["exe"]) if x)
            ui.ElideLabel(txt, sub, bg=CARD, fg=MUTED, font=font(8)).pack(fill="x")

            # this app's own volume, and how loud it is right now
            vol = tk.Frame(txt, bg=CARD)
            vol.own_click = True  # dragging the slider must not toggle the app
            vol.pack(fill="x", pady=(S(4), 0))
            tk.Label(vol, text="🔊", bg=CARD, fg=MUTED, font=font(8)).pack(side="left")
            pct = tk.Label(vol, text="%d%%" % self.app_volumes.get(key, 100), bg=CARD, fg=MUTED,
                           font=font(8), width=5, anchor="e")
            pct.pack(side="right")
            meter = ui.LevelBar(vol, self.scale)
            meter.configure(height=S(5), width=S(70))
            meter.pack(side="right", padx=(S(8), 0))
            slider = ui.Slider(vol, self.scale, value=self.app_volumes.get(key, 100),
                               command=lambda v, k=key: self._app_volume_changed(k, v))
            slider.configure(height=S(18))
            slider.knob = S(14)
            slider.pack(side="left", fill="x", expand=True, padx=(S(4), 0))

            row.finish(lambda s=sw, k=key: (s.set(not s.value), self._toggle_use(k, s.value)))
            self.rows[key] = {"status": status, "sw": sw, "pct": pct, "meter": meter}
        self._update_statuses()
        self._update_count()
        self.apps_area.fit()

    def _update_count(self):
        n = len(self.added)
        on = len(self.use_names & set(self.added))
        self.apps_count.configure(text="%d of %d on" % (on, n) if n else "")

    def _update_statuses(self):
        running = {n for n, _ in self.snap.values()} if self.snap else set()
        for key, r in self.rows.items():
            status = r["status"]
            if key in self.playing:
                status.configure(text="● Playing", fg=GREEN)
            elif key in running:
                status.configure(text="Open", fg=MUTED)
            else:
                status.configure(text="Not running", fg=FAINT)

    # ---------- background polling ----------
    @staticmethod
    def _proc_snapshot():
        """{pid: (lower-case name, parent pid)} for every process."""
        snap = {}
        for p in psutil.process_iter(["name", "ppid"]):
            try:
                snap[p.pid] = ((p.info["name"] or "").lower(), p.info["ppid"])
            except Exception:
                continue
        return snap

    @staticmethod
    def _root_pids(snap, names):
        """Top-most process of each app - capture covers its child processes,
        so capturing the children too would double the audio."""
        own = os.getpid()
        return sorted(pid for pid, (n, ppid) in snap.items()
                      if n in names and pid != own and snap.get(ppid, ("",))[0] != n)

    def _poll_worker(self):
        """Runs off the UI thread: processes, who is playing, app paths, memory."""
        import comtypes
        comtypes.CoInitialize()
        me = psutil.Process()
        me.cpu_percent(None)
        cores = psutil.cpu_count() or 1
        try:  # warm the installed-apps cache so "Add app" opens instantly
            app_info.installed_apps()
        except Exception:
            pass
        while True:
            try:
                snap = self._proc_snapshot()
                playing, audio_pids = set(), set()
                if AudioUtilities is not None:
                    for s in AudioUtilities.GetAllSessions():
                        if s.Process is not None:
                            audio_pids.add(s.ProcessId)
                            if s.State == 1:
                                playing.add(s.Process.name().lower())
                paths = {}
                for key, a in list(self.added.items()):
                    if a["path"] and os.path.isfile(a["path"]):  # Discord etc. move on update
                        continue
                    pid = next((p for p, (n, _) in snap.items() if n == key), None)
                    if pid is not None:
                        try:
                            paths[key] = psutil.Process(pid).exe()
                        except Exception:
                            pass
                self.poll_q.put({"snap": snap, "playing": playing, "audio_pids": audio_pids,
                                 "paths": paths, "mem": me.memory_info().rss,
                                 "cpu": me.cpu_percent(None) / cores})
            except Exception:
                pass
            if self._stop.wait(1.5):
                break
        comtypes.CoUninitialize()

    def _apply_poll(self, r):
        self.snap, self.playing, self.audio_pids = r["snap"], r["playing"], r["audio_pids"]
        found = False
        for key, path in r["paths"].items():
            if key in self.added:
                self.added[key]["path"] = path
                found = True
        if found:
            self._save_settings()
            self._build_rows()
        else:
            self._update_statuses()
        self._sync_capture()
        self.mem_lbl.configure(text="Memory %.0f MB   ·   CPU %.0f%%" %
                               (r["mem"] / 1048576, r["cpu"]))

    def _sync_capture(self):
        """Point the engine at the current PIDs of the switched-on apps
        (they may start, restart or close at any time)."""
        if self.snap is None:
            self.snap = self._proc_snapshot()
        pids = set(self._root_pids(self.snap, self.use_names))
        self._sync_gains(pids)
        if pids != self.engine.app_pids:
            self.engine.set_app_pids(pids)

    def _sync_gains(self, pids=None):
        """Give every captured process the volume of the app it belongs to."""
        if self.snap is None:
            return
        if pids is None:
            pids = self.engine.app_pids
        gains = {pid: self.app_volumes.get(self.snap.get(pid, ("",))[0], 100) / 100.0
                 for pid in pids}
        if gains != self.engine.app_gains:
            self.engine.set_app_gains(gains)

    def _update_app_meters(self):
        levels, _mic = self.engine.levels()
        by_key = {}
        for pid, lvl in levels.items():
            name = self.snap.get(pid, ("",))[0] if self.snap else ""
            by_key[name] = max(by_key.get(name, 0.0), lvl)
        for key, r in self.rows.items():
            r["meter"].set(by_key.get(key, 0.0))

    # ---------- my apps ----------
    def add_app_dialog(self):
        AddAppDialog(self, set(self.added), self.audio_pids, self._add_apps)

    def _add_apps(self, apps):
        for exe, path, name in apps:
            key = exe.lower()
            self.added[key] = {"exe": exe, "path": path}
            if name:
                self.added[key]["name"] = name
            self.use_names.add(key)
        self.snap = self._proc_snapshot()
        self._save_settings()
        self._build_rows()
        self._sync_capture()
        self.set_status("Added %s." % ", ".join(self._info(a[0].lower())["name"] for a in apps))

    def remove_app(self, key):
        name = self._info(key)["name"]
        del self.added[key]
        self.use_names.discard(key)
        self.app_volumes.pop(key, None)
        self._save_settings()
        self._build_rows()
        self._sync_capture()
        self.set_status("Removed %s." % name)

    def _toggle_use(self, key, on):
        if on:
            self.use_names.add(key)
        else:
            self.use_names.discard(key)
        self._update_count()
        self._save_settings()
        self._sync_capture()

    # ---------- devices ----------
    def refresh_devices(self):
        if self.engine.listening:
            self.set_status("Stop listening before refreshing devices.")
            return
        try:
            self.engine.reset()
            sources, self.outputs, default_out = self.engine.devices()
            default_in = self.engine.pa.get_host_api_info_by_type(
                pyaudio.paWASAPI)["defaultInputDevice"]
        except Exception as e:
            messagebox.showerror("Audio devices", str(e))
            return
        self.mics = [(n.replace("[Input] ", "", 1), d) for n, d in sources
                     if not d.get("isLoopbackDevice")]

        want = self.mic_dd.get() or self.saved.get("mic")
        idx = next((i for i, (n, _) in enumerate(self.mics) if n == want),
                   next((i for i, (_, d) in enumerate(self.mics) if d["index"] == default_in), 0))
        self.mic_dd.set_values([n for n, _ in self.mics], idx)
        if self.saved.pop("mic_on", False) and self.mics:
            self.mic_switch.set(True)
        if not self.mics:
            self.mic_switch.set(False)
        self.engine.mic_info = self.mics[idx][1] if self.mics and self.mic_switch.value else None

        want = self.out_dd.get() or self.saved.get("output")
        idx = next((i for i, (n, _) in enumerate(self.outputs) if n == want),
                   next((i for i, (_, d) in enumerate(self.outputs)
                         if d["index"] == default_out), 0))
        self.out_dd.set_values([n for n, _ in self.outputs], idx)
        self.set_status("Ready.")

    def _mic_changed(self):
        i = self.mic_dd.current()
        info = self.mics[i][1] if self.mic_switch.value and 0 <= i < len(self.mics) else None
        if self.mic_switch.value and info is None:
            self.mic_switch.set(False)
            return
        try:
            self.engine.set_mic(info)
        except Exception as e:
            self.mic_switch.set(False)
            self.engine.mic_info = None
            messagebox.showerror("Microphone", "Could not open the microphone:\n%s" % e)
            return
        self.set_status("Mic on: %s" % self.mic_dd.get() if info else "Mic off.")
        self._save_settings()

    def _volume_changed(self, v, save=True):
        self.engine.volume = float(v) / 100
        self.vol_lbl.configure(text="%d%%" % v)
        if save:
            self._save_soon()

    def _save_soon(self):
        """Save settings once a slider stops moving."""
        if getattr(self, "_vol_save", None):
            self.after_cancel(self._vol_save)
        self._vol_save = self.after(500, self._save_settings)

    def _mic_volume_changed(self, v, save=True):
        self.engine.set_mic_gain(float(v) / 100)
        self.mic_vol_lbl.configure(text="%d%%" % v)
        if save:
            self._save_soon()

    def _noise_changed(self, on):
        self.engine.set_noise_suppression(on)
        self.set_status("Noise suppression %s." % ("on" if on else "off"))
        self._save_settings()

    def _app_volume_changed(self, key, v):
        self.app_volumes[key] = int(v)
        row = self.rows.get(key)
        if row:
            row["pct"].configure(text="%d%%" % v)
        self._sync_gains()
        self._save_soon()

    # ---------- actions ----------
    def _nothing_to_capture(self):
        # use a fresh process list - the background scan may not have run yet
        self.snap = self._proc_snapshot()
        self._sync_capture()
        if self.engine.app_pids or self.mic_switch.value:
            return False
        if self.use_names & set(self.added):
            self._alert("Nothing to capture", "None of the apps you switched on are running.\n\n"
                        "Open one of them, or switch on the microphone.")
        else:
            self._alert("Nothing to capture", "Add an app and switch it on, "
                        "or switch on the microphone.")
        return True

    def _alert(self, title, text, error=False):
        """Message box, or a tray notification while the window is hidden."""
        if self.state() == "withdrawn" and self.tray is not None:
            try:
                self.tray.notify(text, title)
                return
            except Exception:
                pass
        (messagebox.showerror if error else messagebox.showinfo)(title, text, parent=self)

    def toggle_listen(self):
        if self.engine.listening:
            self.engine.stop_listen()
            self.set_status("Stopped listening.")
        else:
            if self._nothing_to_capture():
                return
            oi = self.out_dd.current()
            if oi < 0:
                self._alert("RMDeck", "Pick where to listen first.")
                return
            try:
                self.engine.start_listen(APPS_SOURCE, self.outputs[oi][1])
            except Exception as e:
                self.engine.listening = False
                self.engine._close_source_if_idle()
                self._alert("Could not start listening", str(e), error=True)
                return
            self.set_status("Listening on %s" % self.out_dd.get())
        self._set_buttons()

    def _set_buttons(self):
        e = self.engine
        self.listen_btn.set(text="■   Stop listening" if e.listening else "🎧   Listen",
                            variant="primary" if e.listening else "soft")
        self.out_dd.set_enabled(not e.listening)
        self._draw_chip()
        if self.tray is not None:
            self.tray.title = "RMDeck — %s" % ("Listening" if e.listening else "Idle")
            self.tray.update_menu()

    def set_status(self, text):
        self.status.set_text(text)

    def _tick(self):
        if self.show_event and _k32.WaitForSingleObject(self.show_event, 0) == 0:
            self.show_window()  # the user started the app again
        while True:
            try:
                self.ui_q.get_nowait()()
            except queue.Empty:
                break
        if self._stop.is_set():  # quit_app ran
            return
        latest = None
        while True:
            try:
                latest = self.poll_q.get_nowait()
            except queue.Empty:
                break
        if latest:
            self._apply_poll(latest)

        self.meter.set(self.engine.level)
        self._update_app_meters()
        if self.engine.error:
            err, self.engine.error = self.engine.error, None
            self.engine._close_source_if_idle()
            self._set_buttons()
            self.set_status(err)
            self._alert("RMDeck", err, error=True)
        self.after(100, self._tick)

    # ---------- background / tray ----------
    def open_settings(self):
        if getattr(self, "_settings", None) is not None and self._settings.winfo_exists():
            self._settings.lift()
            return
        self._settings = SettingsDialog(self)

    def _background_changed(self, on):
        self.background = on
        if on:
            self._ensure_tray()
            self.set_status("Closing the window will keep RMDeck running in the tray.")
        else:
            self._remove_tray()
        self._save_settings()

    def _ensure_tray(self):
        if self.tray is not None or pystray is None:
            return
        post = self.ui_q.put
        menu = pystray.Menu(
            pystray.MenuItem("Open RMDeck", lambda: post(self.show_window), default=True),
            pystray.MenuItem(lambda _i: "Stop listening" if self.engine.listening else "Listen",
                             lambda: post(self.toggle_listen)),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit", lambda: post(self.quit_app)))
        self.tray = pystray.Icon("RMDeck", ui.app_logo(64), "RMDeck", menu)
        threading.Thread(target=self.tray.run, daemon=True).start()

    def _remove_tray(self):
        if self.tray is not None:
            self.tray.stop()
            self.tray = None

    def show_window(self):
        self.deiconify()
        self.lift()
        self.focus_force()

    def _close_requested(self):
        if self.background and self.tray is not None:
            self.withdraw()
            if not self._told_tray:
                self._told_tray = True
                try:
                    self.tray.notify("Still running in the background. Right-click the tray "
                                     "icon to open, listen or quit.", "RMDeck")
                except Exception:
                    pass
        else:
            self.quit_app()

    def quit_app(self):
        log.info("Quitting")
        self._stop.set()
        try:
            self._save_settings()
            self._remove_tray()
            self.engine.shutdown()
        finally:
            self.destroy()

    # ---------- settings ----------
    def _load_settings(self):
        path = SETTINGS_PATH if os.path.isfile(SETTINGS_PATH) else OLD_SETTINGS_PATH
        try:
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, ValueError):
            return
        apps = data.get("apps")
        if apps is None:  # older versions: apps ticked in the old list count as added
            apps = [{"exe": n, "path": None}
                    for n in data.get("added_apps", []) + data.get("use_apps", [])]
        for a in apps:
            if a.get("exe"):
                self.added[a["exe"].lower()] = {k: a[k] for k in ("exe", "path", "name")
                                                if a.get(k) is not None}
                self.added[a["exe"].lower()].setdefault("path", None)
        self.use_names = {n.lower() for n in data.get("use_apps", [])} & set(self.added)
        self.background = bool(data.get("background", False))
        vols = data.get("app_volumes")
        if isinstance(vols, dict):
            self.app_volumes = {k.lower(): max(0, min(200, int(v))) for k, v in vols.items()
                                if isinstance(v, (int, float)) and k.lower() in self.added}
        self.saved = {k: data[k] for k in ("mic", "mic_on", "output", "volume", "mic_volume",
                                           "noise_suppression") if k in data}

    def _save_settings(self):
        self._vol_save = None
        data = {"apps": sorted(self.added.values(), key=lambda a: a["exe"].lower()),
                "use_apps": sorted(self.use_names),
                "mic": self.mic_dd.get(), "mic_on": self.mic_switch.value,
                "output": self.out_dd.get(), "volume": self.slider.value,
                "mic_volume": self.mic_slider.value,
                "noise_suppression": self.ns_switch.value,
                "app_volumes": {k: v for k, v in sorted(self.app_volumes.items()) if v != 100},
                "background": self.background}
        try:
            os.makedirs(os.path.dirname(SETTINGS_PATH), exist_ok=True)
            with open(SETTINGS_PATH, "w", encoding="utf-8") as fh:
                json.dump(data, fh, indent=2)
        except OSError as e:
            self.set_status("Could not save settings: %s" % e)


def selftest(seconds=2.0):
    """`RMDeck.exe --selftest`: capture a few seconds from every app that is
    playing sound right now, without UI or playback. Result goes to the log;
    exit code 0 = audio captured."""
    from pycaw.pycaw import AudioUtilities as AU
    pids = {s.ProcessId for s in AU.GetAllSessions()
            if s.Process is not None and s.State == 1 and s.ProcessId != os.getpid()}
    log.info("selftest: capturing PIDs %s", sorted(pids))
    engine = AudioEngine()
    engine.set_app_pids(pids)
    try:
        engine._open_source(APPS_SOURCE)
        peak, end = 0.0, time.time() + seconds
        while time.time() < end:
            peak = max(peak, engine.level)
            time.sleep(0.02)
        engine._close_source_if_idle()
        log.info("selftest: peak level %.3f over %.1fs, error=%s", peak, seconds, engine.error)
        return 0 if peak > 0 and not engine.error else 1
    except Exception:
        log.exception("selftest failed")
        return 1
    finally:
        engine.shutdown()


def main():
    setup_logging()
    if "--selftest" in sys.argv[1:]:
        sys.exit(selftest())
    show_event = claim_single_instance()
    if show_event is None:  # already running - it has been asked to show itself
        return
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)  # crisp text on scaled displays
    except Exception:
        pass
    # own taskbar identity (same ID as the installer's shortcuts), not "Python".
    # The Microsoft Store (MSIX) version already has one from its package.
    if not is_packaged():
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("RMDeck.App")
        except Exception:
            pass
    if app_capture is None:
        tk.Tk().withdraw()
        messagebox.showerror(APP_NAME,
                             "Capturing app audio needs Windows 10 version 2004 or newer.")
        return
    try:
        App(show_event=show_event).mainloop()
    except Exception:
        log.exception("Fatal error")
        raise


if __name__ == "__main__":
    main()



"""
Per-application audio capture (WASAPI process loopback) and a small mixer
that combines several apps into one stereo float32 stream.

Needs Windows 10 version 2004 (build 19041) or newer.
"""
import ctypes
import sys
import threading
import time
from ctypes import wintypes, byref, POINTER, c_void_p

import numpy as np
import comtypes
from comtypes import GUID, IUnknown, COMMETHOD, HRESULT, COMObject

RATE = 48000
CHANNELS = 2
MIN_BUILD = 19041

# --------------------------------------------------------------------------- #
#  COM / Win32 declarations
# --------------------------------------------------------------------------- #
AUDCLNT_SHAREMODE_SHARED = 0
AUDCLNT_STREAMFLAGS_LOOPBACK = 0x00020000
AUDCLNT_STREAMFLAGS_EVENTCALLBACK = 0x00040000
AUDCLNT_STREAMFLAGS_AUTOCONVERTPCM = 0x80000000
AUDCLNT_STREAMFLAGS_SRC_DEFAULT_QUALITY = 0x08000000
AUDCLNT_BUFFERFLAGS_SILENT = 0x2
AUDIOCLIENT_ACTIVATION_TYPE_PROCESS_LOOPBACK = 1
PROCESS_LOOPBACK_MODE_INCLUDE_TARGET_PROCESS_TREE = 0
VIRTUAL_AUDIO_DEVICE_PROCESS_LOOPBACK = "VAD\\Process_Loopback"
VT_BLOB = 65
WAVE_FORMAT_PCM = 1


class WAVEFORMATEX(ctypes.Structure):
    _fields_ = [("wFormatTag", wintypes.WORD), ("nChannels", wintypes.WORD),
                ("nSamplesPerSec", wintypes.DWORD), ("nAvgBytesPerSec", wintypes.DWORD),
                ("nBlockAlign", wintypes.WORD), ("wBitsPerSample", wintypes.WORD),
                ("cbSize", wintypes.WORD)]


class AUDIOCLIENT_ACTIVATION_PARAMS(ctypes.Structure):
    _fields_ = [("ActivationType", ctypes.c_int),
                ("TargetProcessId", wintypes.DWORD),
                ("ProcessLoopbackMode", ctypes.c_int)]


class PROPVARIANT_BLOB(ctypes.Structure):
    _fields_ = [("vt", ctypes.c_ushort), ("r1", ctypes.c_ushort),
                ("r2", ctypes.c_ushort), ("r3", ctypes.c_ushort),
                ("cbSize", ctypes.c_ulong), ("pBlobData", c_void_p)]


class IAudioCaptureClient(IUnknown):
    _iid_ = GUID("{C8ADBD64-E71E-48a0-A4DE-185C395CD317}")
    _methods_ = [
        COMMETHOD([], HRESULT, "GetBuffer",
                  (["in"], POINTER(POINTER(ctypes.c_byte))), (["in"], POINTER(ctypes.c_uint32)),
                  (["in"], POINTER(wintypes.DWORD)), (["in"], POINTER(ctypes.c_uint64)),
                  (["in"], POINTER(ctypes.c_uint64))),
        COMMETHOD([], HRESULT, "ReleaseBuffer", (["in"], ctypes.c_uint32)),
        COMMETHOD([], HRESULT, "GetNextPacketSize", (["in"], POINTER(ctypes.c_uint32))),
    ]


class IAudioClient(IUnknown):
    _iid_ = GUID("{1CB9AD4C-DBFA-4c32-B178-C2F568A703B2}")
    _methods_ = [
        COMMETHOD([], HRESULT, "Initialize",
                  (["in"], ctypes.c_int), (["in"], wintypes.DWORD),
                  (["in"], ctypes.c_longlong), (["in"], ctypes.c_longlong),
                  (["in"], POINTER(WAVEFORMATEX)), (["in"], POINTER(GUID))),
        COMMETHOD([], HRESULT, "GetBufferSize", (["in"], POINTER(ctypes.c_uint32))),
        COMMETHOD([], HRESULT, "GetStreamLatency", (["in"], POINTER(ctypes.c_longlong))),
        COMMETHOD([], HRESULT, "GetCurrentPadding", (["in"], POINTER(ctypes.c_uint32))),
        COMMETHOD([], HRESULT, "IsFormatSupported", (["in"], ctypes.c_int),
                  (["in"], POINTER(WAVEFORMATEX)), (["in"], c_void_p)),
        COMMETHOD([], HRESULT, "GetMixFormat", (["in"], c_void_p)),
        COMMETHOD([], HRESULT, "GetDevicePeriod", (["in"], POINTER(ctypes.c_longlong)),
                  (["in"], POINTER(ctypes.c_longlong))),
        COMMETHOD([], HRESULT, "Start"),
        COMMETHOD([], HRESULT, "Stop"),
        COMMETHOD([], HRESULT, "Reset"),
        COMMETHOD([], HRESULT, "SetEventHandle", (["in"], wintypes.HANDLE)),
        COMMETHOD([], HRESULT, "GetService", (["in"], POINTER(GUID)),
                  (["in"], POINTER(POINTER(IUnknown)))),
    ]


class IActivateAudioInterfaceAsyncOperation(IUnknown):
    _iid_ = GUID("{72A22D78-CDE4-431D-B8CC-843A71199B6D}")
    _methods_ = [
        COMMETHOD([], HRESULT, "GetActivateResult",
                  (["in"], POINTER(HRESULT)), (["in"], POINTER(POINTER(IUnknown)))),
    ]


class IActivateAudioInterfaceCompletionHandler(IUnknown):
    _iid_ = GUID("{41D949AB-9862-444A-80F6-C261334DA5EB}")
    _methods_ = [
        COMMETHOD([], HRESULT, "ActivateCompleted",
                  (["in"], POINTER(IActivateAudioInterfaceAsyncOperation))),
    ]


class IAgileObject(IUnknown):
    _iid_ = GUID("{94ea2b94-e9cc-49e0-c0ff-ee64ca8f5b90}")
    _methods_ = []


class _CompletionHandler(COMObject):
    _com_interfaces_ = [IActivateAudioInterfaceCompletionHandler, IAgileObject]

    def __init__(self):
        super().__init__()
        self.done = threading.Event()

    def IActivateAudioInterfaceCompletionHandler_ActivateCompleted(self, this, operation):
        self.done.set()
        return 0


_mmdevapi = ctypes.WinDLL("Mmdevapi")
_ActivateAudioInterfaceAsync = _mmdevapi.ActivateAudioInterfaceAsync
_ActivateAudioInterfaceAsync.restype = HRESULT
_ActivateAudioInterfaceAsync.argtypes = [
    wintypes.LPCWSTR, POINTER(GUID), POINTER(PROPVARIANT_BLOB),
    POINTER(IActivateAudioInterfaceCompletionHandler),
    POINTER(POINTER(IActivateAudioInterfaceAsyncOperation))]

_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
_kernel32.CreateEventW.restype = wintypes.HANDLE
_kernel32.CreateEventW.argtypes = [c_void_p, wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR]
_kernel32.WaitForSingleObject.restype = wintypes.DWORD
_kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
_kernel32.CloseHandle.argtypes = [wintypes.HANDLE]


def supported():
    return sys.platform == "win32" and sys.getwindowsversion().build >= MIN_BUILD


def _activate_process_loopback(pid):
    """Return an IAudioClient that captures `pid` and its child processes."""
    params = AUDIOCLIENT_ACTIVATION_PARAMS(AUDIOCLIENT_ACTIVATION_TYPE_PROCESS_LOOPBACK, pid,
                                           PROCESS_LOOPBACK_MODE_INCLUDE_TARGET_PROCESS_TREE)
    pv = PROPVARIANT_BLOB(vt=VT_BLOB, cbSize=ctypes.sizeof(params),
                          pBlobData=ctypes.cast(byref(params), c_void_p))
    handler = _CompletionHandler()
    op = POINTER(IActivateAudioInterfaceAsyncOperation)()
    iid = IAudioClient._iid_
    _ActivateAudioInterfaceAsync(VIRTUAL_AUDIO_DEVICE_PROCESS_LOOPBACK, byref(iid), byref(pv),
                                 handler.QueryInterface(IActivateAudioInterfaceCompletionHandler),
                                 byref(op))
    if not handler.done.wait(5):
        raise RuntimeError("Timed out activating capture for PID %d" % pid)
    hr = HRESULT()
    punk = POINTER(IUnknown)()
    op.GetActivateResult(byref(hr), byref(punk))
    if hr.value < 0:
        raise OSError("Could not capture PID %d (0x%08X)" % (pid, hr.value & 0xFFFFFFFF))
    return punk.QueryInterface(IAudioClient)


# --------------------------------------------------------------------------- #
#  Microphone noise suppression
# --------------------------------------------------------------------------- #
class NoiseSuppressor:
    """Real-time spectral noise suppression for a mono RATE signal (numpy only).

    STFT with 20 ms sqrt-Hann frames / 10 ms hop (adds 10 ms of latency). The
    noise floor is tracked per frequency with minimum statistics, so steady
    noise (fans, hum, hiss, AC) is learned within ~1.5 s and follows changes;
    a decision-directed Wiener gain then removes it while keeping speech."""

    N = RATE // 50          # 20 ms frame
    H = N // 2              # 10 ms hop
    SUB = 25                # frames per minimum-tracking sub-window (250 ms)
    SUBS = 6                # sub-windows remembered (1.5 s)
    BIAS = 1.8              # minimum-of-smoothed-power underestimates the mean noise
    FLOOR_DB = -26.0        # how far noise is pushed down

    def __init__(self):
        self.win = np.sqrt(np.hanning(self.N + 1)[:self.N])   # periodic: COLA at 50 %
        self.floor = 10 ** (self.FLOOR_DB / 20)
        self.reset()

    def reset(self):
        self.pending = np.zeros(0, dtype=np.float64)
        self.frame = np.zeros(self.N)
        self.ola = np.zeros(self.N)
        self.smooth = None

    def _gain(self, p):
        eps = 1e-12
        if self.smooth is None:
            self.smooth = p.copy()
            self.cur_min = p.copy()
            self.mins = []
            self.count = 0
            self.prev_clean = np.zeros_like(p)
        self.smooth = 0.85 * self.smooth + 0.15 * p
        self.cur_min = np.minimum(self.cur_min, self.smooth)
        self.count += 1
        if self.count >= self.SUB:
            self.mins.append(self.cur_min)
            if len(self.mins) > self.SUBS:
                self.mins.pop(0)
            self.cur_min = self.smooth.copy()
            self.count = 0
        noise = self.cur_min
        for m in self.mins:
            noise = np.minimum(noise, m)
        noise = noise * self.BIAS + eps
        post = p / noise
        prior = 0.98 * self.prev_clean / noise + 0.02 * np.maximum(post - 1.0, 0.0)
        g = prior / (1.0 + prior)
        g = np.convolve(g, (0.25, 0.5, 0.25), mode="same")   # less "musical noise"
        g = np.maximum(g, self.floor)
        g[:2] = self.floor                                    # rumble below ~75 Hz
        self.prev_clean = g * g * p
        return g

    def process(self, x):
        """Feed any number of mono samples, get back the cleaned samples ready so far."""
        self.pending = np.concatenate([self.pending, x])
        n = len(self.pending) // self.H
        if not n:
            return np.zeros(0, dtype=np.float32)
        out = np.empty(n * self.H)
        H = self.H
        for i in range(n):
            self.frame[:H] = self.frame[H:]
            self.frame[H:] = self.pending[i * H:(i + 1) * H]
            X = np.fft.rfft(self.frame * self.win)
            g = self._gain(X.real ** 2 + X.imag ** 2)
            self.ola += np.fft.irfft(X * g, self.N) * self.win
            out[i * H:(i + 1) * H] = self.ola[:H]
            self.ola[:H] = self.ola[H:]
            self.ola[H:] = 0.0
        self.pending = self.pending[n * H:]
        return out.astype(np.float32)


# --------------------------------------------------------------------------- #
#  One source -> buffer
# --------------------------------------------------------------------------- #
class _Buffered:
    """A jitter buffer of float32 stereo frames at RATE that the mixer pulls from."""

    PREBUFFER = RATE * 30 // 1000     # wait for 30 ms before playing out
    MAX_BUFFER = RATE * 150 // 1000   # drop the oldest audio beyond 150 ms

    def __init__(self):
        self.gain = 1.0          # volume set by the user (1.0 = 100 %)
        self.applied = 1.0       # gain used on the last block (ramped to avoid clicks)
        self.level = 0.0         # peak meter after the gain
        self.error = None
        self.lock = threading.Lock()
        self.chunks = []
        self.buffered = 0
        self.primed = False

    def push(self, a):
        with self.lock:
            self.chunks.append(a)
            self.buffered += len(a)

    def take(self, n):
        """Return exactly n frames, zero-padded if the app has not delivered enough."""
        out = np.zeros((n, CHANNELS), dtype=np.float32)
        with self.lock:
            if self.buffered > self.MAX_BUFFER:
                self._drop(self.buffered - self.PREBUFFER)
            if not self.primed:
                if self.buffered < self.PREBUFFER:
                    return out
                self.primed = True
            got = 0
            while got < n and self.chunks:
                c = self.chunks[0]
                k = min(n - got, len(c))
                out[got:got + k] = c[:k]
                got += k
                if k == len(c):
                    self.chunks.pop(0)
                else:
                    self.chunks[0] = c[k:]
            self.buffered -= got
            if got < n:
                self.primed = False
        return out

    def _drop(self, n):
        while n > 0 and self.chunks:
            c = self.chunks[0]
            if len(c) <= n:
                n -= len(c)
                self.buffered -= len(c)
                self.chunks.pop(0)
            else:
                self.chunks[0] = c[n:]
                self.buffered -= n
                n = 0


class AppCapture(_Buffered):
    """Captures one process tree (WASAPI process loopback)."""

    def __init__(self, pid):
        super().__init__()
        self.pid = pid
        self.running = True
        self.ready = threading.Event()
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def stop(self):
        self.running = False
        self.thread.join(timeout=2)

    def _run(self):
        comtypes.CoInitializeEx(comtypes.COINIT_MULTITHREADED)
        event = None
        client = None
        try:
            client = _activate_process_loopback(self.pid)
            fmt = WAVEFORMATEX(WAVE_FORMAT_PCM, CHANNELS, RATE, RATE * CHANNELS * 2,
                               CHANNELS * 2, 16, 0)
            client.Initialize(AUDCLNT_SHAREMODE_SHARED,
                              AUDCLNT_STREAMFLAGS_LOOPBACK | AUDCLNT_STREAMFLAGS_EVENTCALLBACK |
                              AUDCLNT_STREAMFLAGS_AUTOCONVERTPCM |
                              AUDCLNT_STREAMFLAGS_SRC_DEFAULT_QUALITY,
                              200000, 0, byref(fmt), None)
            event = _kernel32.CreateEventW(None, False, False, None)
            client.SetEventHandle(event)
            punk = POINTER(IUnknown)()
            client.GetService(byref(IAudioCaptureClient._iid_), byref(punk))
            cap = punk.QueryInterface(IAudioCaptureClient)
            client.Start()
            self.ready.set()

            data = POINTER(ctypes.c_byte)()
            frames = ctypes.c_uint32()
            flags = wintypes.DWORD()
            packet = ctypes.c_uint32()
            while self.running:
                _kernel32.WaitForSingleObject(event, 100)
                cap.GetNextPacketSize(byref(packet))
                while packet.value:
                    cap.GetBuffer(byref(data), byref(frames), byref(flags), None, None)
                    n = frames.value
                    if flags.value & AUDCLNT_BUFFERFLAGS_SILENT or not data:
                        a = np.zeros((n, CHANNELS), dtype=np.float32)
                    else:
                        raw = ctypes.string_at(data, n * CHANNELS * 2)
                        a = (np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0
                             ).reshape(-1, CHANNELS)
                    cap.ReleaseBuffer(n)
                    self.push(a)
                    cap.GetNextPacketSize(byref(packet))
            client.Stop()
        except Exception as e:
            self.error = "App capture (PID %d) failed: %s" % (self.pid, e)
        finally:
            self.ready.set()
            if event:
                _kernel32.CloseHandle(event)
            client = None
            comtypes.CoUninitialize()


class MicCapture(_Buffered):
    """Captures a microphone / input device opened through PyAudio (WASAPI),
    resampled to RATE stereo."""

    def __init__(self, pa, info, pa_continue, denoise=False):
        super().__init__()
        self.info = info
        self.suppressor = NoiseSuppressor()
        self.ns_lock = threading.Lock()
        self.denoise = denoise
        self.ch = int(info["maxInputChannels"]) or 1
        self.rate = int(info["defaultSampleRate"])
        self.frac = 0.0
        self.pa_continue = pa_continue
        import pyaudiowpatch
        self.stream = pa.open(format=pyaudiowpatch.paFloat32,
                              channels=self.ch, rate=self.rate, input=True,
                              input_device_index=info["index"],
                              frames_per_buffer=max(256, self.rate // 100),
                              stream_callback=self._callback)
        self.stream.start_stream()

    def _callback(self, in_data, frame_count, time_info, status):
        try:
            a = np.frombuffer(in_data, dtype=np.float32).reshape(-1, self.ch)
            a = a[:, :2] if self.ch >= 2 else np.repeat(a, 2, axis=1)
            if self.rate != RATE and len(a) > 1:
                target = len(a) * RATE / float(self.rate) + self.frac
                n = int(target)
                self.frac = target - n
                xo = np.arange(len(a))
                xn = np.linspace(0, len(a) - 1, n)
                a = np.column_stack([np.interp(xn, xo, a[:, 0]), np.interp(xn, xo, a[:, 1])])
            with self.ns_lock:
                if self.denoise:
                    clean = self.suppressor.process(a.mean(axis=1))
                    a = np.repeat(clean.reshape(-1, 1), 2, axis=1)
            if len(a):
                self.push(a.astype(np.float32))
        except Exception as e:
            self.error = "Mic capture failed: %s" % e
        return (None, self.pa_continue)

    def set_denoise(self, on):
        with self.ns_lock:
            if on and not self.denoise:
                self.suppressor.reset()
            self.denoise = on

    def stop(self):
        try:
            self.stream.stop_stream()
            self.stream.close()
        except Exception:
            pass


# --------------------------------------------------------------------------- #
#  Several apps -> one stream
# --------------------------------------------------------------------------- #
class AppMixer:
    """Mixes several AppCaptures (plus an optional mic) and calls
    `on_audio(float32 [n,2] array)` every ~10 ms, like a PortAudio input callback."""

    def __init__(self, pids, on_audio, pa=None, mic=None, pa_continue=0,
                 gains=None, mic_gain=1.0, denoise=False):
        self.on_audio = on_audio
        self.error = None
        self.lock = threading.Lock()
        self.captures = {}
        self.pa = pa
        self.pa_continue = pa_continue
        self.mic = None
        self.gains = dict(gains or {})
        self.mic_gain = mic_gain
        self.denoise = denoise
        self.running = True
        self.set_pids(pids)
        try:
            self.set_mic(mic)
        except Exception:
            self.set_pids(())
            raise
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def set_pids(self, pids):
        """Add / remove apps while running."""
        pids = set(pids)
        with self.lock:
            for pid in list(self.captures):
                if pid not in pids:
                    self.captures.pop(pid).stop()
            for pid in pids:
                if pid not in self.captures:
                    c = AppCapture(pid)
                    c.gain = c.applied = self.gains.get(pid, 1.0)
                    self.captures[pid] = c

    def set_gains(self, gains):
        """Per-app volume, {pid: gain} (1.0 = 100 %); missing PIDs play at 100 %."""
        with self.lock:
            self.gains = dict(gains)
            for pid, c in self.captures.items():
                c.gain = self.gains.get(pid, 1.0)

    def set_mic_gain(self, gain):
        with self.lock:
            self.mic_gain = gain
            if self.mic is not None:
                self.mic.gain = gain

    def set_denoise(self, on):
        with self.lock:
            self.denoise = on
            mic = self.mic
        if mic is not None:
            mic.set_denoise(on)

    def levels(self):
        """Peak level of each app after its volume, {pid: 0..1+}, and the mic's."""
        with self.lock:
            apps = {pid: c.level for pid, c in self.captures.items()}
            mic = self.mic.level if self.mic is not None else 0.0
        return apps, mic

    def set_mic(self, info):
        """Mix in an input device (PyAudio device info dict), or None for no mic."""
        with self.lock:
            old = self.mic
            if old is not None and info is not None and old.info["index"] == info["index"]:
                return
            self.mic = None
        if old is not None:
            old.stop()
        if info is not None:
            m = MicCapture(self.pa, info, self.pa_continue, denoise=self.denoise)
            with self.lock:
                m.gain = m.applied = self.mic_gain
                self.mic = m

    def pids(self):
        with self.lock:
            return set(self.captures)

    def stop(self):
        self.running = False
        self.thread.join(timeout=2)
        self.set_mic(None)
        with self.lock:
            for c in self.captures.values():
                c.stop()
            self.captures.clear()

    def _run(self):
        start = time.perf_counter()
        produced = 0
        while self.running:
            time.sleep(0.01)
            due = int((time.perf_counter() - start) * RATE) - produced
            if due <= 0:
                continue
            if due > RATE // 2:          # we were stalled; skip ahead
                produced += due - RATE // 100
                due = RATE // 100
            mix = np.zeros((due, CHANNELS), dtype=np.float32)
            with self.lock:
                caps = list(self.captures.values())
                if self.mic is not None:
                    caps.append(self.mic)
            for c in caps:
                if c.error:
                    self.error, c.error = c.error, None
                a = c.take(due)
                g0, g1 = c.applied, c.gain
                if g0 != g1:   # ramp across the block so volume changes don't click
                    a *= np.linspace(g0, g1, due, dtype=np.float32)[:, None]
                    c.applied = g1
                elif g1 != 1.0:
                    a *= g1
                peak = float(np.abs(a).max()) if due else 0.0
                c.level = max(c.level * 0.85, peak)
                mix += a
            produced += due
            self.on_audio(mix)

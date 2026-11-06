"""
App metadata straight from the .exe: friendly name, publisher and icon
(as PNG bytes Tk can show). Windows only, no extra packages.
"""
import ctypes
import os
import struct
import zlib
from ctypes import wintypes, byref

_version = ctypes.WinDLL("version")
_shell32 = ctypes.WinDLL("shell32")
_user32 = ctypes.WinDLL("user32")
_gdi32 = ctypes.WinDLL("gdi32")

_version.GetFileVersionInfoSizeW.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(wintypes.DWORD)]
_version.GetFileVersionInfoW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                         ctypes.c_void_p]
_version.VerQueryValueW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR,
                                    ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(wintypes.UINT)]
_shell32.ExtractIconExW.argtypes = [wintypes.LPCWSTR, ctypes.c_int,
                                    ctypes.POINTER(wintypes.HICON), ctypes.POINTER(wintypes.HICON),
                                    wintypes.UINT]
_shell32.ExtractIconExW.restype = wintypes.UINT
_user32.DestroyIcon.argtypes = [wintypes.HICON]
_user32.GetDC.argtypes = [wintypes.HWND]
_user32.GetDC.restype = wintypes.HDC
_user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
_gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
_gdi32.GetObjectW.argtypes = [wintypes.HGDIOBJ, ctypes.c_int, ctypes.c_void_p]
_gdi32.GetDIBits.argtypes = [wintypes.HDC, wintypes.HBITMAP, wintypes.UINT, wintypes.UINT,
                             ctypes.c_void_p, ctypes.c_void_p, wintypes.UINT]


class _ICONINFO(ctypes.Structure):
    _fields_ = [("fIcon", wintypes.BOOL), ("xHotspot", wintypes.DWORD),
                ("yHotspot", wintypes.DWORD), ("hbmMask", wintypes.HBITMAP),
                ("hbmColor", wintypes.HBITMAP)]


class _BITMAP(ctypes.Structure):
    _fields_ = [("bmType", wintypes.LONG), ("bmWidth", wintypes.LONG),
                ("bmHeight", wintypes.LONG), ("bmWidthBytes", wintypes.LONG),
                ("bmPlanes", wintypes.WORD), ("bmBitsPixel", wintypes.WORD),
                ("bmBits", ctypes.c_void_p)]


class _BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG),
                ("biHeight", wintypes.LONG), ("biPlanes", wintypes.WORD),
                ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", wintypes.LONG),
                ("biYPelsPerMeter", wintypes.LONG), ("biClrUsed", wintypes.DWORD),
                ("biClrImportant", wintypes.DWORD)]


_user32.GetIconInfo.argtypes = [wintypes.HICON, ctypes.POINTER(_ICONINFO)]

_info_cache = {}
_icon_cache = {}


# --------------------------------------------------------------------------- #
#  Version resource
# --------------------------------------------------------------------------- #
def _version_strings(path, keys):
    size = _version.GetFileVersionInfoSizeW(path, None)
    if not size:
        return {}
    buf = ctypes.create_string_buffer(size)
    if not _version.GetFileVersionInfoW(path, 0, size, buf):
        return {}
    ptr, n = ctypes.c_void_p(), wintypes.UINT()
    langs = []
    if _version.VerQueryValueW(buf, "\\VarFileInfo\\Translation", byref(ptr), byref(n)) and n.value:
        words = ctypes.cast(ptr, ctypes.POINTER(wintypes.WORD))
        langs = ["%04x%04x" % (words[i], words[i + 1]) for i in range(0, n.value // 2, 2)]
    langs += ["040904b0", "040904e4", "000004b0"]
    out = {}
    for key in keys:
        for lang in langs:
            if _version.VerQueryValueW(buf, "\\StringFileInfo\\%s\\%s" % (lang, key),
                                       byref(ptr), byref(n)) and n.value > 1:
                value = ctypes.wstring_at(ptr, n.value).rstrip("\0").strip()
                if value:
                    out[key] = value
                    break
    return out


def get_info(path, exe_name=None):
    """{'name', 'publisher', 'exe', 'path'} for an app. `path` may be None
    (app not found), then only the exe name is known."""
    exe = exe_name or os.path.basename(path or "")
    key = (path or exe).lower()
    if key in _info_cache:
        return _info_cache[key]
    meta = {}
    if path and os.path.isfile(path):
        try:
            meta = _version_strings(path, ("FileDescription", "ProductName", "CompanyName"))
        except Exception:
            meta = {}
    name = meta.get("FileDescription") or meta.get("ProductName") or os.path.splitext(exe)[0]
    # some apps put junk like "Application" or the exe name in the description
    if name.lower() in ("application", exe.lower()) and meta.get("ProductName"):
        name = meta["ProductName"]
    info = {"name": name, "publisher": meta.get("CompanyName", ""), "exe": exe, "path": path}
    _info_cache[key] = info
    return info


# --------------------------------------------------------------------------- #
#  Icon -> PNG
# --------------------------------------------------------------------------- #
def _bitmap_bgra(hdc, hbm, w, h):
    bmi = _BITMAPINFOHEADER(ctypes.sizeof(_BITMAPINFOHEADER), w, -h, 1, 32, 0, 0, 0, 0, 0, 0)
    # BITMAPINFO = header + colour table; leave room for the table GDI may write
    raw = ctypes.create_string_buffer(ctypes.sizeof(bmi) + 256 * 4)
    ctypes.memmove(raw, byref(bmi), ctypes.sizeof(bmi))
    bits = ctypes.create_string_buffer(w * h * 4)
    if not _gdi32.GetDIBits(hdc, hbm, 0, h, bits, raw, 0):
        return None
    return bits.raw


def _hicon_rgba(hicon):
    ii = _ICONINFO()
    if not _user32.GetIconInfo(hicon, byref(ii)):
        return None
    hdc = _user32.GetDC(None)
    try:
        if not ii.hbmColor:
            return None
        bm = _BITMAP()
        _gdi32.GetObjectW(ii.hbmColor, ctypes.sizeof(bm), byref(bm))
        w, h = bm.bmWidth, bm.bmHeight
        color = _bitmap_bgra(hdc, ii.hbmColor, w, h)
        if color is None:
            return None
        px = bytearray(color)
        if not any(px[3::4]):  # old icon without alpha: use the AND mask
            mask = _bitmap_bgra(hdc, ii.hbmMask, w, h) if ii.hbmMask else None
            for i in range(0, len(px), 4):
                px[i + 3] = 0 if (mask and mask[i]) else 255
        px[0::4], px[2::4] = px[2::4], px[0::4]  # BGRA -> RGBA
        return w, h, bytes(px)
    finally:
        _user32.ReleaseDC(None, hdc)
        if ii.hbmColor:
            _gdi32.DeleteObject(ii.hbmColor)
        if ii.hbmMask:
            _gdi32.DeleteObject(ii.hbmMask)


def _png(w, h, rgba):
    def chunk(tag, data):
        return (struct.pack(">I", len(data)) + tag + data +
                struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))
    rows = b"".join(b"\0" + rgba[y * w * 4:(y + 1) * w * 4] for y in range(h))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0)) +
            chunk(b"IDAT", zlib.compress(rows, 9)) + chunk(b"IEND", b""))


def get_icon_png(path, large=True):
    """PNG bytes of the exe's icon (system large or small icon size), or None."""
    if not path or not os.path.isfile(path):
        return None
    key = (path.lower(), large)
    if key in _icon_cache:
        return _icon_cache[key]
    big, small = wintypes.HICON(), wintypes.HICON()
    png = None
    try:
        if _shell32.ExtractIconExW(path, 0, byref(big), byref(small), 1):
            got = _hicon_rgba(big if large else small)
            if got:
                png = _png(*got)
    except Exception:
        png = None
    finally:
        for hi in (big, small):
            if hi:
                _user32.DestroyIcon(hi)
    _icon_cache[key] = png
    return png


# --------------------------------------------------------------------------- #
#  Installed apps (Start menu)
# --------------------------------------------------------------------------- #
_SKIP_WORDS = ("uninstall", "unins0", "setup", "install", "readme", "help", "documentation",
               "manual", "release notes", "website", "license", "repair", "crash", "report")
_installed = None


def _start_menu_dirs():
    dirs = []
    for env, sub in (("PROGRAMDATA", r"Microsoft\Windows\Start Menu\Programs"),
                     ("APPDATA", r"Microsoft\Windows\Start Menu\Programs")):
        base = os.environ.get(env)
        if base and os.path.isdir(os.path.join(base, sub)):
            dirs.append(os.path.join(base, sub))
    return dirs


def _squirrel_target(target, args):
    """Discord, Slack & co. start via Update.exe --processStart App.exe; find App.exe."""
    parts = args.replace('"', " ").split()
    if "--processStart" not in parts:
        return None
    i = parts.index("--processStart")
    if i + 1 >= len(parts):
        return None
    exe = parts[i + 1]
    root = os.path.dirname(target)
    try:
        versions = [d for d in os.listdir(root) if d.lower().startswith("app-")]
    except OSError:
        return None
    for d in sorted(versions, key=lambda d: os.path.getmtime(os.path.join(root, d)),
                    reverse=True):
        p = os.path.join(root, d, exe)
        if os.path.isfile(p):
            return p
    return None


def installed_apps(refresh=False):
    """[(name, exe path)] for the programs in the Start menu (like Windows' "All apps"),
    minus uninstallers, help files and Windows' own tools. Cached; call from any thread."""
    global _installed
    if _installed is not None and not refresh:
        return _installed
    import comtypes
    import comtypes.client
    comtypes.CoInitialize()
    try:
        shell = comtypes.client.CreateObject("WScript.Shell", dynamic=True)
        windir = os.environ.get("WINDIR", r"C:\Windows").lower()
        found = {}
        for top in _start_menu_dirs():
            for dirpath, _dirs, files in os.walk(top):
                for f in files:
                    if not f.lower().endswith(".lnk"):
                        continue
                    name = f[:-4]
                    if any(w in name.lower() for w in _SKIP_WORDS):
                        continue
                    try:
                        link = shell.CreateShortcut(os.path.join(dirpath, f))
                        target, args = link.TargetPath or "", link.Arguments or ""
                    except Exception:
                        continue
                    if os.path.basename(target).lower() == "update.exe":
                        target = _squirrel_target(target, args) or ""
                    if (not target.lower().endswith(".exe") or not os.path.isfile(target)
                            or target.lower().startswith(windir)):
                        continue
                    exe = os.path.basename(target).lower()
                    if any(w in exe for w in ("unins", "setup", "update", "install")):
                        continue
                    # keep the shortest shortcut name per program ("Steam", not "Steam Support")
                    if exe not in found or len(name) < len(found[exe][0]):
                        found[exe] = (name, os.path.normpath(target))
    finally:
        comtypes.CoUninitialize()
    _installed = sorted(found.values(), key=lambda a: a[0].lower())
    return _installed


# --------------------------------------------------------------------------- #
#  Which programs have a window
# --------------------------------------------------------------------------- #
def window_pids():
    """PIDs that own a visible, titled top-level window (what people call "apps")."""
    pids = set()
    proto = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def cb(hwnd, _lp):
        if _user32.IsWindowVisible(hwnd) and _user32.GetWindowTextLengthW(hwnd) > 0:
            pid = wintypes.DWORD()
            _user32.GetWindowThreadProcessId(hwnd, byref(pid))
            pids.add(pid.value)
        return True

    _user32.EnumWindows(proto(cb), 0)
    return pids

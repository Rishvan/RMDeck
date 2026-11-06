"""
Small light-theme widget kit for Tkinter with smooth rounded corners.

Shapes are drawn with Pillow at 4x and scaled down (anti-aliased), then shown
as images on Tk canvases. Everything takes a `scale` for high-DPI screens.
"""
import base64
import os
import sys
import tkinter as tk
import tkinter.font as tkfont
from collections import OrderedDict

from PIL import Image, ImageDraw, ImageTk

# palette
BG = "#f3f4f6"
CARD = "#ffffff"
BORDER = "#e5e7eb"
BORDER_HOVER = "#cbd5e1"
FIELD = "#f9fafb"
HOVER = "#f8fafc"
TEXT = "#111827"
MUTED = "#6b7280"
FAINT = "#9ca3af"
ACCENT = "#2563eb"
ACCENT_DARK = "#1d4ed8"
ACCENT_SOFT = "#eef2ff"
ACCENT_SOFT_HOVER = "#e0e7ff"
GREEN = "#16a34a"
AMBER = "#f59e0b"
RED = "#dc2626"
RED_DARK = "#b91c1c"
RED_SOFT = "#fef2f2"
RED_SOFT_HOVER = "#fee2e2"
TRACK = "#e5e7eb"
NEUTRAL = "#f3f4f6"
NEUTRAL_HOVER = "#e5e7eb"

FONT = "Segoe UI"
FONT_BOLD = "Segoe UI Semibold"

_SS = 4
_cache = OrderedDict()
_fonts = {}


def font(size=10, bold=False):
    key = (size, bold)
    if key not in _fonts:
        _fonts[key] = tkfont.Font(family=FONT_BOLD if bold else FONT, size=size)
    return _fonts[key]


def _rgb(c):
    c = c.lstrip("#")
    return tuple(int(c[i:i + 2], 16) for i in (0, 2, 4))


def rounded_image(w, h, r, fill=None, outline=None, width=1, cache=True):
    """Anti-aliased rounded rectangle as a PhotoImage (transparent outside)."""
    w, h = max(1, int(w)), max(1, int(h))
    r = max(0, min(int(r), w // 2, h // 2))
    key = (w, h, r, fill, outline, width)
    if cache and key in _cache:
        _cache.move_to_end(key)
        return _cache[key]
    edge = _rgb(outline or fill or "#000000")
    im = Image.new("RGBA", (w * _SS, h * _SS), edge + (0,))
    ImageDraw.Draw(im).rounded_rectangle(
        [0, 0, w * _SS - 1, h * _SS - 1], radius=r * _SS,
        fill=_rgb(fill) + (255,) if fill else None,
        outline=_rgb(outline) + (255,) if outline else None,
        width=width * _SS if outline else 0)
    img = ImageTk.PhotoImage(im.reduce(_SS))
    if cache:
        _cache[key] = img
        while len(_cache) > 400:
            _cache.popitem(last=False)
    return img


def _corners(r, fill, outline):
    """The four anti-aliased corner pieces (nw, ne, sw, se) of a rounded rectangle."""
    key = ("corners", r, fill, outline)
    if key in _cache:
        return _cache[key]
    d = 2 * r
    edge = _rgb(outline or fill or "#000000")
    im = Image.new("RGBA", (d * _SS, d * _SS), edge + (0,))
    ImageDraw.Draw(im).rounded_rectangle(
        [0, 0, d * _SS - 1, d * _SS - 1], radius=r * _SS,
        fill=_rgb(fill) + (255,) if fill else None,
        outline=_rgb(outline) + (255,) if outline else None,
        width=_SS if outline else 0)
    im = im.reduce(_SS)
    pieces = tuple(ImageTk.PhotoImage(im.crop(box)) for box in
                   ((0, 0, r, r), (r, 0, d, r), (0, r, r, d), (r, r, d, d)))
    _cache[key] = pieces
    return pieces


def paint_round_rect(cv, w, h, r, fill, outline=None, x=0, y=0, tags=()):
    """Draw a rounded rectangle on canvas `cv` from cached corner pieces plus plain
    rectangles/lines. Unlike a full-size image this costs almost nothing to redraw,
    so shapes keep up while a window is being resized."""
    w, h = int(w), int(h)
    r = max(1, min(int(r), w // 2, h // 2))
    nw, ne, sw, se = _corners(r, fill, outline)
    if fill:
        cv.create_rectangle(x + r, y, x + w - r, y + h, fill=fill, width=0, tags=tags)
        cv.create_rectangle(x, y + r, x + w, y + h - r, fill=fill, width=0, tags=tags)
    if outline:
        for line in ((x + r, y, x + w - r, y), (x + r, y + h - 1, x + w - r, y + h - 1),
                     (x, y + r, x, y + h - r), (x + w - 1, y + r, x + w - 1, y + h - r)):
            cv.create_line(*line, fill=outline, tags=tags)
    for img, px, py in ((nw, x, y), (ne, x + w - r, y), (sw, x, y + h - r),
                        (se, x + w - r, y + h - r)):
        cv.create_image(px, py, anchor="nw", image=img, tags=tags)


def png_image(png):
    return tk.PhotoImage(data=base64.b64encode(png), format="png")


def elide(f, text, width):
    """Shorten text with an ellipsis so it fits in `width` pixels."""
    if width <= 0 or f.measure(text) <= width:
        return text
    lo, hi = 0, len(text)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if f.measure(text[:mid] + "…") <= width:
            lo = mid
        else:
            hi = mid - 1
    return text[:lo].rstrip() + "…"


def set_bg(widget, color):
    """Recolour a widget and all its children (for row hover)."""
    try:
        widget.configure(bg=color)
    except tk.TclError:
        pass
    for child in widget.winfo_children():
        set_bg(child, color)


# --------------------------------------------------------------------------- #
#  Containers
# --------------------------------------------------------------------------- #
class _RoundedBackdrop(tk.Frame):
    """A frame with a rounded-rectangle canvas placed behind its packed `.body`.
    The body is inset by the padding, so the frame still sizes to its content."""

    def __init__(self, master, scale, pad_x, pad_y, radius, bg):
        super().__init__(master, bg=bg)
        self.scale, self.base, self.r = scale, bg, int(radius * scale)
        self.fill = self.outline = None
        self._cv = tk.Canvas(self, bg=bg, highlightthickness=0, width=1, height=1)
        self._cv.place(x=0, y=0, relwidth=1, relheight=1)
        self.body = tk.Frame(self, bg=bg)
        self.body.pack(fill="both", expand=True, padx=int(pad_x * scale),
                       pady=int(pad_y * scale))
        self.bind("<Configure>", lambda _e: self._draw())

    def _draw(self):
        self._cv.delete("all")
        w, h = self.winfo_width(), self.winfo_height()
        if w < 4 or h < 4 or (self.fill is None and self.outline is None):
            return
        paint_round_rect(self._cv, w, h, self.r, self.fill, self.outline)


class Card(_RoundedBackdrop):
    """Rounded white card with a border. Put content into `.body`."""

    def __init__(self, master, scale, pad=16, radius=14, expand=False, bg=BG):
        super().__init__(master, scale, pad, pad, radius, bg)
        self.fill, self.outline = CARD, BORDER
        self.body.configure(bg=CARD)


class HoverRow(_RoundedBackdrop):
    """List row with a rounded highlight on hover / when selected. Content goes into `.body`;
    call finish(on_click) after filling it. Widgets with their own click handling
    should set `w.own_click = True` so the row ignores clicks on them."""

    HOVER = "#f5f7fa"
    SELECTED = "#eef4ff"

    def __init__(self, master, scale, pad_x=10, pad_y=8, bg=CARD):
        super().__init__(master, scale, pad_x, pad_y, 10, bg)
        self.hover = self.selected = False
        self.bind("<Enter>", lambda _e: self._set_hover(True))
        self.bind("<Leave>", self._leave)

    def finish(self, on_click=None):
        def bind(w):
            if getattr(w, "own_click", False):
                return
            w.bind("<Enter>", lambda _e: self._set_hover(True), add="+")
            w.bind("<Leave>", self._leave, add="+")
            if on_click:
                w.bind("<Button-1>", lambda _e: on_click(), add="+")
                w.configure(cursor="hand2")
            for c in w.winfo_children():
                bind(c)
        bind(self.body)
        bind(self._cv)
        if on_click:
            self.bind("<Button-1>", lambda _e: on_click())
            self.configure(cursor="hand2")

    def _leave(self, _e):
        x, y = self.winfo_pointerxy()
        w = self.winfo_containing(x, y)
        while w is not None:
            if w is self:
                return
            w = w.master
        self._set_hover(False)

    def _set_hover(self, on):
        if on != self.hover:
            self.hover = on
            self._paint()

    def set_selected(self, on):
        self.selected = on
        self._paint()

    def _paint(self):
        color = self.SELECTED if self.selected else (self.HOVER if self.hover else self.base)
        self.fill = None if color == self.base else color
        self._draw()
        set_bg(self.body, color)


class CheckMark(tk.Canvas):
    """Round-cornered checkbox indicator (display only)."""

    def __init__(self, master, scale, bg=CARD):
        self.s = int(20 * scale)
        super().__init__(master, width=self.s, height=self.s, bg=bg, highlightthickness=0)
        self.scale = scale
        self.set(False)

    def set(self, on):
        self.delete("all")
        s, k = self.s, self.scale
        if on:
            self._img = rounded_image(s, s, int(6 * k), ACCENT)
            self.create_image(0, 0, anchor="nw", image=self._img)
            self.create_line(s * 0.27, s * 0.52, s * 0.44, s * 0.68, s * 0.74, s * 0.36,
                             fill="white", width=max(1.5, 2 * k), capstyle="round",
                             joinstyle="round")
        else:
            self._img = rounded_image(s, s, int(6 * k), CARD, BORDER_HOVER, width=max(1, int(k)))
            self.create_image(0, 0, anchor="nw", image=self._img)


class ScrollArea(tk.Frame):
    """Vertical scrolling list with a slim rounded scrollbar shown only when needed."""

    def __init__(self, master, scale, bg=CARD):
        super().__init__(master, bg=bg)
        self.scale = scale
        self.canvas = tk.Canvas(self, bg=bg, highlightthickness=0, height=1, width=1)
        self.bar = tk.Canvas(self, bg=bg, highlightthickness=0, width=int(6 * scale))
        self.inner = tk.Frame(self.canvas, bg=bg)
        self._win = self.canvas.create_window(0, 0, window=self.inner, anchor="nw")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.inner.bind("<Configure>", lambda _e: self.fit())
        self.canvas.bind("<Configure>", self._resized)
        self.canvas.configure(yscrollcommand=lambda *_a: self._draw_bar())
        self.bar.bind("<Button-1>", self._drag)
        self.bar.bind("<B1-Motion>", self._drag)
        _install_wheel_router(self)

    def _resized(self, e):
        self.canvas.itemconfigure(self._win, width=e.width)
        self.fit()

    def fit(self):
        h = self.inner.winfo_reqheight()
        self.canvas.configure(scrollregion=(0, 0, 0, h))
        if h > self.canvas.winfo_height() > 1:
            if not self.bar.winfo_ismapped():
                self.bar.pack(side="right", fill="y", padx=(int(4 * self.scale), 0))
        else:
            if self.bar.winfo_ismapped():
                self.bar.pack_forget()
            self.canvas.yview_moveto(0)
        self._draw_bar()

    def scroll(self, units):
        if self.bar.winfo_ismapped():
            self.canvas.yview_scroll(units, "units")

    def _draw_bar(self):
        self.bar.delete("all")
        if not self.bar.winfo_ismapped():
            return
        top, bottom = self.canvas.yview()
        H, W = self.bar.winfo_height(), self.bar.winfo_width()
        y0, y1 = int(top * H), max(int(bottom * H), int(top * H) + W * 3)
        self._thumb = rounded_image(W, y1 - y0, W // 2, BORDER_HOVER)
        self.bar.create_image(0, y0, anchor="nw", image=self._thumb)

    def _drag(self, e):
        top, bottom = self.canvas.yview()
        self.canvas.yview_moveto(e.y / max(1, self.bar.winfo_height()) - (bottom - top) / 2)


_wheel_router = []


def _install_wheel_router(widget):
    """One app-wide mouse-wheel handler that scrolls the ScrollArea under the pointer."""
    if _wheel_router:
        return
    root = widget._root()
    _wheel_router.append(root)

    def on_wheel(e):
        w = root.winfo_containing(e.x_root, e.y_root)
        while w is not None and not isinstance(w, ScrollArea):
            w = w.master
        if w is not None:
            w.scroll(int(-e.delta / 120))

    root.bind_all("<MouseWheel>", on_wheel, add="+")


# --------------------------------------------------------------------------- #
#  Controls
# --------------------------------------------------------------------------- #
_VARIANTS = {
    #           fill, hover fill, text, border
    "primary": (ACCENT, ACCENT_DARK, "white", None),
    "soft": (ACCENT_SOFT, ACCENT_SOFT_HOVER, ACCENT, None),
    "danger": (RED, RED_DARK, "white", None),
    "danger_soft": (RED_SOFT, RED_SOFT_HOVER, RED, None),
    "neutral": (NEUTRAL, NEUTRAL_HOVER, TEXT, None),
    "outline": (CARD, FIELD, TEXT, BORDER),
}


class RoundButton(tk.Canvas):
    def __init__(self, master, text, command, scale, variant="soft", bg=CARD,
                 height=36, min_width=0, size=10, expand=False):
        super().__init__(master, bg=bg, highlightthickness=0, cursor="hand2",
                         height=int(height * scale), width=1)
        self.scale, self.command, self.variant = scale, command, variant
        self.text, self.min_width, self.expand = text, int(min_width * scale), expand
        self.f = font(size, bold=True)
        self.hover = self.pressed = False
        self.enabled = True
        self.bind("<Enter>", lambda _e: self._set_hover(True))
        self.bind("<Leave>", lambda _e: self._set_hover(False))
        self.bind("<ButtonRelease-1>", self._release)
        self.bind("<Configure>", lambda _e: self._draw())
        self._size()

    def _size(self):
        if not self.expand:
            w = max(self.min_width, self.f.measure(self.text) + int(36 * self.scale))
            self.configure(width=w)

    def set(self, text=None, variant=None, enabled=None):
        if text is not None:
            self.text = text
        if variant is not None:
            self.variant = variant
        if enabled is not None:
            self.enabled = enabled
            self.configure(cursor="hand2" if enabled else "arrow")
        self._size()
        self._draw()

    def _set_hover(self, on):
        self.hover = on
        self._draw()

    def _release(self, e):
        if self.enabled and 0 <= e.x <= self.winfo_width() and 0 <= e.y <= self.winfo_height():
            self.command()

    def _draw(self):
        self.delete("all")
        w, h = self.winfo_width(), self.winfo_height()
        if w < 4:
            w = int(self.cget("width"))
        fill, hover, fg, border = _VARIANTS[self.variant]
        if not self.enabled:
            fill, fg, border = NEUTRAL, FAINT, None
        elif self.hover:
            fill = hover
            border = BORDER_HOVER if border else None
        paint_round_rect(self, w, h, int(10 * self.scale), fill, border)
        self.create_text(w / 2, h / 2, text=self.text, fill=fg, font=self.f)


class Link(tk.Label):
    def __init__(self, master, text, command, bg=CARD, size=9):
        super().__init__(master, text=text, fg=ACCENT, bg=bg, cursor="hand2", font=font(size))
        self.bind("<Button-1>", lambda _e: command())
        self.bind("<Enter>", lambda _e: self.configure(fg=ACCENT_DARK))
        self.bind("<Leave>", lambda _e: self.configure(fg=ACCENT))


class Switch(tk.Canvas):
    """iOS-style on/off switch."""

    def __init__(self, master, scale, value=False, command=None, bg=CARD):
        self.w, self.h = int(38 * scale), int(22 * scale)
        super().__init__(master, width=self.w, height=self.h, bg=bg,
                         highlightthickness=0, cursor="hand2")
        self.value, self.command = bool(value), command
        self.bind("<Button-1>", self._click)
        self._draw()

    def set(self, value):
        self.value = bool(value)
        self._draw()

    def _click(self, _e):
        self.set(not self.value)
        if self.command:
            self.command(self.value)

    def _draw(self):
        key = ("switch", self.w, self.h, self.value)
        if key not in _cache:
            W, H = self.w * _SS, self.h * _SS
            track = _rgb(ACCENT if self.value else "#d1d5db")
            im = Image.new("RGBA", (W, H), track + (0,))
            d = ImageDraw.Draw(im)
            d.rounded_rectangle([0, 0, W - 1, H - 1], radius=H // 2, fill=track + (255,))
            p = 3 * _SS
            x = W - H + p if self.value else p
            d.ellipse([x, p, x + H - 2 * p, H - p], fill=(255, 255, 255, 255))
            _cache[key] = ImageTk.PhotoImage(im.reduce(_SS))
        self.delete("all")
        self.create_image(0, 0, anchor="nw", image=_cache[key])


class Slider(tk.Canvas):
    """Rounded horizontal slider."""

    def __init__(self, master, scale, value=100, maximum=200, command=None, bg=CARD):
        super().__init__(master, height=int(22 * scale), bg=bg, highlightthickness=0,
                         cursor="hand2", width=1)
        self.scale, self.value, self.maximum, self.command = scale, value, maximum, command
        self.knob = int(18 * scale)
        self.bind("<Configure>", lambda _e: self._draw())
        self.bind("<Button-1>", self._move)
        self.bind("<B1-Motion>", self._move)

    def _move(self, e):
        k = self.knob
        frac = (e.x - k / 2) / max(1, self.winfo_width() - k)
        self.value = round(max(0.0, min(1.0, frac)) * self.maximum)
        self._draw()
        if self.command:
            self.command(self.value)

    def _draw(self):
        self.delete("all")
        w, h, k = self.winfo_width(), self.winfo_height(), self.knob
        if w < k + 2:
            return
        th = max(4, int(5 * self.scale))
        y = (h - th) // 2
        x = k / 2 + (w - k) * self.value / self.maximum
        self._track = rounded_image(w - k, th, th // 2, TRACK)
        self.create_image(k // 2, y, anchor="nw", image=self._track)
        if x - k / 2 >= th:
            self._fill = rounded_image(x - k / 2, th, th // 2, ACCENT, cache=False)
            self.create_image(k // 2, y, anchor="nw", image=self._fill)
        self._knob = rounded_image(k, k, k // 2, CARD, BORDER_HOVER)
        self.create_image(x - k / 2, (h - k) // 2, anchor="nw", image=self._knob)


class LevelBar(tk.Canvas):
    """Rounded audio level meter (green -> amber -> red)."""

    def __init__(self, master, scale, bg=CARD):
        super().__init__(master, height=int(8 * scale), bg=bg, highlightthickness=0, width=1)
        self.value = 0.0
        self.bind("<Configure>", lambda _e: self.set(self.value, force=True))

    def set(self, value, force=False):
        value = max(0.0, min(1.0, value))
        w = self.winfo_width()
        if not force and int(w * value) == int(w * self.value):
            return
        self.value = value
        self.delete("all")
        h = self.winfo_height()
        if w < 4:
            return
        self._track = rounded_image(w, h, h // 2, TRACK)
        self.create_image(0, 0, anchor="nw", image=self._track)
        fw = int(w * value)
        if fw >= h:
            c = RED if value > 0.97 else (AMBER if value > 0.8 else GREEN)
            self._fill = rounded_image(fw, h, h // 2, c)
            self.create_image(0, 0, anchor="nw", image=self._fill)


class Dropdown(tk.Canvas):
    """Rounded select box with a rounded popup list."""

    _KEY = "#f1f2f5"  # popup transparency key (close to the light background)

    def __init__(self, master, scale, on_change=None, placeholder="", bg=CARD):
        super().__init__(master, height=int(40 * scale), bg=bg, highlightthickness=0,
                         cursor="hand2", width=1)
        self.scale, self.on_change, self.placeholder = scale, on_change, placeholder
        self.values, self.index = [], -1
        self.enabled, self.hover = True, False
        self.popup = None
        self._closed_at = 0
        self.f = font(10)
        self.bind("<Configure>", lambda _e: self._draw())
        self.bind("<Enter>", lambda _e: self._set_hover(True))
        self.bind("<Leave>", lambda _e: self._set_hover(False))
        self.bind("<Button-1>", lambda _e: self.toggle())

    # -- value
    def set_values(self, values, index=0):
        self.values = list(values)
        self.index = index if 0 <= index < len(self.values) else -1
        self._draw()

    def get(self):
        return self.values[self.index] if self.index >= 0 else ""

    def current(self):
        return self.index

    def set_enabled(self, on):
        self.enabled = on
        self.configure(cursor="hand2" if on else "arrow")
        self._draw()

    def _set_hover(self, on):
        self.hover = on
        self._draw()

    # -- field
    def _draw(self):
        self.delete("all")
        w, h = self.winfo_width(), self.winfo_height()
        if w < 10:
            return
        s = self.scale
        outline = ACCENT if self.popup else (BORDER_HOVER if self.hover and self.enabled
                                             else BORDER)
        paint_round_rect(self, w, h, int(10 * s), FIELD if self.enabled else NEUTRAL, outline)
        text = self.get() or self.placeholder
        color = (TEXT if self.get() else FAINT) if self.enabled else FAINT
        self.create_text(int(14 * s), h / 2, anchor="w", fill=color, font=self.f,
                         text=elide(self.f, text, w - int(48 * s)))
        # chevron
        cx, cy, d = w - int(18 * s), h / 2, int(4 * s)
        pts = (cx - d, cy + d / 2, cx, cy - d / 2, cx + d, cy + d / 2) if self.popup else \
              (cx - d, cy - d / 2, cx, cy + d / 2, cx + d, cy - d / 2)
        self.create_line(*pts, fill=MUTED if self.enabled else FAINT,
                         width=max(1.5, 1.6 * s), capstyle="round", joinstyle="round")

    # -- popup
    def toggle(self):
        if self.popup:
            self.close()
        elif (self.enabled and self.values and
              # a click on the field that just closed the popup must not reopen it
              self.tk.call("clock", "milliseconds") - self._closed_at > 250):
            self.open()

    def open(self):
        s = self.scale
        self.rowh, self.pad = int(34 * s), int(6 * s)
        self.visible = min(len(self.values), 8)
        self.first = max(0, min(self.index - self.visible + 1, len(self.values) - self.visible))
        self.hover_i = None
        w = self.winfo_width()
        h = self.visible * self.rowh + 2 * self.pad
        x = self.winfo_rootx()
        y = self.winfo_rooty() + self.winfo_height() + int(4 * s)
        if y + h > self.winfo_screenheight() - int(40 * s):
            y = self.winfo_rooty() - h - int(4 * s)

        top = self.popup = tk.Toplevel(self)
        top.overrideredirect(True)
        top.attributes("-topmost", True)
        top.configure(bg=self._KEY)
        top.attributes("-transparentcolor", self._KEY)
        top.geometry("%dx%d+%d+%d" % (w, h, x, y))
        self.pc = tk.Canvas(top, bg=self._KEY, highlightthickness=0, width=w, height=h)
        self.pc.pack(fill="both", expand=True)
        self._panel = rounded_image(w, h, int(10 * s), CARD, BORDER_HOVER)
        self._row_hover = rounded_image(w - 2 * self.pad, self.rowh, int(7 * s), ACCENT_SOFT)
        self.pc.bind("<Motion>", self._popup_motion)
        self.pc.bind("<Leave>", lambda _e: self._popup_hover(None))
        self.pc.bind("<ButtonRelease-1>", self._popup_click)
        self.pc.bind("<MouseWheel>", self._popup_wheel)
        top.bind("<Escape>", lambda _e: self.close())
        top.bind("<FocusOut>", lambda _e: self.after(60, self._check_focus))
        self._render_popup()
        top.focus_force()
        self._draw()

    def _check_focus(self):
        if not self.popup:
            return
        try:
            f = self.popup.focus_get()
        except (KeyError, tk.TclError):
            f = None
        if f is None or not str(f).startswith(str(self.popup)):
            self.close()

    def close(self):
        if self.popup:
            self.popup.destroy()
            self.popup = None
            self._closed_at = self.tk.call("clock", "milliseconds")
            self._draw()

    def _render_popup(self):
        c, s = self.pc, self.scale
        c.delete("all")
        c.create_image(0, 0, anchor="nw", image=self._panel)
        w = int(c.cget("width"))
        for i in range(self.visible):
            vi = self.first + i
            y0 = self.pad + i * self.rowh
            if vi == self.hover_i:
                c.create_image(self.pad, y0, anchor="nw", image=self._row_hover)
            sel = vi == self.index
            c.create_text(self.pad + int(12 * s), y0 + self.rowh / 2, anchor="w",
                          fill=ACCENT if sel else TEXT, font=font(10, bold=sel),
                          text=elide(self.f, self.values[vi], w - 2 * self.pad - int(44 * s)))
            if sel:
                cx, cy, d = w - self.pad - int(16 * s), y0 + self.rowh / 2, int(4 * s)
                c.create_line(cx - d, cy, cx - d / 3, cy + d * 0.7, cx + d, cy - d * 0.7,
                              fill=ACCENT, width=max(1.5, 1.8 * s), capstyle="round",
                              joinstyle="round")
        if len(self.values) > self.visible:  # scroll hint
            frac = self.first / (len(self.values) - self.visible)
            bh = int(self.visible / len(self.values) * (int(c.cget("height")) - 2 * self.pad))
            by = self.pad + frac * (int(c.cget("height")) - 2 * self.pad - bh)
            self._sb = rounded_image(int(4 * s), bh, int(2 * s), BORDER_HOVER)
            c.create_image(w - int(7 * s), by, anchor="nw", image=self._sb)

    def _row_at(self, y):
        i = (y - self.pad) // self.rowh
        return self.first + i if 0 <= i < self.visible else None

    def _popup_hover(self, i):
        if i != self.hover_i:
            self.hover_i = i
            self._render_popup()

    def _popup_motion(self, e):
        self._popup_hover(self._row_at(e.y))

    def _popup_wheel(self, e):
        n = len(self.values) - self.visible
        self.first = max(0, min(n, self.first - int(e.delta / 120)))
        self.hover_i = self._row_at(e.y)
        self._render_popup()

    def _popup_click(self, e):
        i = self._row_at(e.y)
        if i is None:
            return
        changed = i != self.index
        self.index = i
        self.close()
        if changed and self.on_change:
            self.on_change(i)


class SearchField(tk.Canvas):
    """Rounded text field with a placeholder."""

    def __init__(self, master, scale, variable, placeholder="Search", bg=CARD):
        super().__init__(master, height=int(40 * scale), bg=bg, highlightthickness=0, width=1)
        self.scale, self.placeholder, self.var = scale, placeholder, variable
        self.entry = tk.Entry(self, textvariable=variable, relief="flat", bd=0, bg=FIELD,
                              fg=TEXT, font=font(10), insertbackground=TEXT,
                              highlightthickness=0)
        self._win = self.create_window(int(14 * scale), 0, anchor="w", window=self.entry)
        self.hint = tk.Label(self.entry, text=placeholder, bg=FIELD, fg=FAINT, font=font(10),
                             bd=0, padx=0, cursor="xterm")
        self.hint.bind("<Button-1>", lambda _e: self.entry.focus_set())
        self.focused = False
        self.entry.bind("<FocusIn>", lambda _e: self._focus(True))
        self.entry.bind("<FocusOut>", lambda _e: self._focus(False))
        self.bind("<Button-1>", lambda _e: self.entry.focus_set())
        variable.trace_add("write", lambda *_: self._draw())
        self.bind("<Configure>", lambda _e: self._draw())

    def _focus(self, on):
        self.focused = on
        self._draw()

    def _draw(self):
        w, h = self.winfo_width(), self.winfo_height()
        if w < 10:
            return
        s = self.scale
        self.delete("bg")
        paint_round_rect(self, w, h, int(10 * s), FIELD, ACCENT if self.focused else BORDER,
                         tags="bg")
        self.tag_lower("bg")
        if self.var.get():
            self.hint.place_forget()
        else:
            self.hint.place(x=1, rely=0.5, anchor="w")
        self.coords(self._win, int(14 * s), h / 2)
        self.itemconfigure(self._win, width=w - int(28 * s))


class ElideLabel(tk.Label):
    """Label that shortens its text with … to fit the space it is given."""

    def __init__(self, master, text="", **kw):
        super().__init__(master, width=1, anchor="w", **kw)
        self.full = text
        self.bind("<Configure>", lambda _e: self._fit())

    def set_text(self, text):
        self.full = text
        self._fit()

    def _fit(self):
        try:
            f = tkfont.nametofont(self.cget("font"))
        except tk.TclError:
            f = tkfont.Font(font=self.cget("font"))
        self.configure(text=elide(f, self.full, self.winfo_width() - 4))


def letter_tile(master, name, size, bg=CARD):
    """Placeholder app icon: first letter on a coloured rounded square."""
    colors = ("#2563eb", "#7c3aed", "#db2777", "#ea580c", "#059669", "#0891b2")
    c = colors[sum(map(ord, name)) % len(colors)]
    cv = tk.Canvas(master, width=size, height=size, bg=bg, highlightthickness=0)
    cv._img = rounded_image(size, size, size // 4, c)
    cv.create_image(0, 0, anchor="nw", image=cv._img)
    cv.create_text(size / 2, size / 2, text=(name[:1] or "?").upper(), fill="white",
                   font=(FONT_BOLD, max(8, int(size / 3.2))))
    return cv


_LOGO_FILE = "rmdex_icon.png"
_logo_src = None


def _logo_path():
    """assets/rmdex_icon.png next to the code, or inside the PyInstaller bundle."""
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, "assets", _LOGO_FILE)


def app_logo(size):
    """RMDex's icon (blue rounded tile, mic and "RV") as a Pillow RGBA image of
    size x size, scaled down from assets/rmdex_icon.png."""
    global _logo_src
    if _logo_src is None:
        _logo_src = Image.open(_logo_path()).convert("RGBA")
        _logo_src.load()
    return _logo_src.resize((int(size), int(size)), Image.LANCZOS)
"""Desktop backend — control the real machine's mouse, keyboard, and screen.

Screen capture (mss) and the screen-diff observer are cross-platform; only
*input* is OS-specific, so input lives behind an `InputDriver` chosen by
platform:

* `X11Input`     — Linux/X11 via the XTEST extension (xdotool's mechanism).
                   This is the tested reference (CI runs it under Xvfb).
* `QuartzInput`  — macOS via CoreGraphics CGEvent (pyobjc).
* `WindowsInput` — Windows via ctypes SendInput.

The macOS and Windows drivers are written from the documented platform APIs but
are NOT exercised by CI here (Linux); treat them as best-effort until verified
on those platforms. `FakeDesktopBackend` is the deterministic test stand-in.
"""

from __future__ import annotations

import sys
from typing import Any, Callable, Optional

from ._observer import BufferedObserver
from ._screen import ScreenDiffer

# char → X keysym name for keys whose name isn't the character itself.
_SPECIAL_CHARS = {
    " ": "space", "\n": "Return", "\t": "Tab",
    "!": "exclam", '"': "quotedbl", "#": "numbersign", "$": "dollar",
    "%": "percent", "&": "ampersand", "'": "apostrophe", "(": "parenleft",
    ")": "parenright", "*": "asterisk", "+": "plus", ",": "comma",
    "-": "minus", ".": "period", "/": "slash", ":": "colon", ";": "semicolon",
    "<": "less", "=": "equal", ">": "greater", "?": "question", "@": "at",
    "[": "bracketleft", "\\": "backslash", "]": "bracketright",
    "^": "asciicircum", "_": "underscore", "`": "grave", "{": "braceleft",
    "|": "bar", "}": "braceright", "~": "asciitilde",
}
_KEY_ALIASES = {
    "enter": "Return", "return": "Return", "esc": "Escape", "escape": "Escape",
    "tab": "Tab", "space": "space", "backspace": "BackSpace", "del": "Delete",
    "delete": "Delete", "up": "Up", "down": "Down", "left": "Left",
    "right": "Right", "home": "Home", "end": "End", "pageup": "Prior",
    "pagedown": "Next", "ctrl": "Control_L", "control": "Control_L",
    "shift": "Shift_L", "alt": "Alt_L", "meta": "Super_L", "super": "Super_L",
    "cmd": "Super_L", "win": "Super_L",
}
_BUTTONS = {"left": 1, "middle": 2, "right": 3}


# --------------------------------------------------------------------------
# Input drivers
# --------------------------------------------------------------------------

class X11Input:
    """Linux/X11 input via XTEST. The tested reference driver."""

    def __init__(self, display: Optional[str] = None) -> None:
        from Xlib import display as _display

        self.display = _display.Display(display) if display else _display.Display()

    def screen_size(self) -> tuple:
        geo = self.display.screen().root.get_geometry()
        return (geo.width, geo.height)

    def move(self, x: int, y: int) -> None:
        self.display.screen().root.warp_pointer(int(x), int(y))
        self.display.sync()

    def click(self, x=None, y=None, button: str = "left", clicks: int = 1) -> None:
        from Xlib import X
        from Xlib.ext import xtest

        if x is not None and y is not None:
            self.move(x, y)
        b = _BUTTONS.get(button, 1)
        for _ in range(max(1, clicks)):
            xtest.fake_input(self.display, X.ButtonPress, b)
            xtest.fake_input(self.display, X.ButtonRelease, b)
        self.display.sync()

    def _tap_keysym(self, keysym: int, *, shift: bool = False) -> None:
        from Xlib import X, XK
        from Xlib.ext import xtest

        keycode = self.display.keysym_to_keycode(keysym)
        if not keycode:
            return
        shift_code = self.display.keysym_to_keycode(XK.XK_Shift_L)
        if shift:
            xtest.fake_input(self.display, X.KeyPress, shift_code)
        xtest.fake_input(self.display, X.KeyPress, keycode)
        xtest.fake_input(self.display, X.KeyRelease, keycode)
        if shift:
            xtest.fake_input(self.display, X.KeyRelease, shift_code)
        self.display.sync()

    def _char_keysym(self, ch: str) -> tuple:
        from Xlib import XK

        name = _SPECIAL_CHARS.get(ch, ch)
        keysym = XK.string_to_keysym(name)
        if not keysym:
            keysym = 0x01000000 + ord(ch)
        keycode = self.display.keysym_to_keycode(keysym)
        shift = False
        if keycode:
            base = self.display.keycode_to_keysym(keycode, 0)
            shifted = self.display.keycode_to_keysym(keycode, 1)
            if keysym == shifted and keysym != base:
                shift = True
        return keysym, shift

    def type_text(self, text: str) -> None:
        for ch in text:
            keysym, shift = self._char_keysym(ch)
            self._tap_keysym(keysym, shift=shift)

    def press_key(self, key: str) -> None:
        from Xlib import X, XK
        from Xlib.ext import xtest

        parts = [p.strip() for p in key.replace(" ", "").split("+") if p.strip()]
        if not parts:
            return
        *mods, main = parts
        mod_codes = []
        for m in mods:
            ks = XK.string_to_keysym(_KEY_ALIASES.get(m.lower(), m))
            code = self.display.keysym_to_keycode(ks) if ks else 0
            if code:
                mod_codes.append(code)
        main_name = _KEY_ALIASES.get(main.lower(), main)
        main_ks = XK.string_to_keysym(main_name) or (0x01000000 + ord(main) if len(main) == 1 else 0)
        main_code = self.display.keysym_to_keycode(main_ks) if main_ks else 0
        for c in mod_codes:
            xtest.fake_input(self.display, X.KeyPress, c)
        if main_code:
            xtest.fake_input(self.display, X.KeyPress, main_code)
            xtest.fake_input(self.display, X.KeyRelease, main_code)
        for c in reversed(mod_codes):
            xtest.fake_input(self.display, X.KeyRelease, c)
        self.display.sync()

    def scroll(self, amount: int) -> None:
        from Xlib import X
        from Xlib.ext import xtest

        button = 4 if amount > 0 else 5
        for _ in range(abs(int(amount))):
            xtest.fake_input(self.display, X.ButtonPress, button)
            xtest.fake_input(self.display, X.ButtonRelease, button)
        self.display.sync()

    def close(self) -> None:
        try:
            self.display.close()
        except Exception:  # noqa: BLE001
            pass


class QuartzInput:
    """macOS input via CoreGraphics CGEvent (pyobjc). UNVERIFIED on this CI."""

    def __init__(self) -> None:
        from Quartz import CoreGraphics as CG  # type: ignore

        self.CG = CG
        self._pos = (0, 0)

    def screen_size(self) -> tuple:
        import AppKit  # type: ignore

        f = AppKit.NSScreen.mainScreen().frame()
        return (int(f.size.width), int(f.size.height))

    def move(self, x: int, y: int) -> None:
        CG = self.CG
        self._pos = (x, y)
        CG.CGEventPost(CG.kCGHIDEventTap,
                       CG.CGEventCreateMouseEvent(None, CG.kCGEventMouseMoved, (x, y), 0))

    def click(self, x=None, y=None, button: str = "left", clicks: int = 1) -> None:
        CG = self.CG
        if x is None or y is None:
            x, y = self._pos
        down, up, btn = {
            "left": (CG.kCGEventLeftMouseDown, CG.kCGEventLeftMouseUp, 0),
            "right": (CG.kCGEventRightMouseDown, CG.kCGEventRightMouseUp, 1),
            "middle": (CG.kCGEventOtherMouseDown, CG.kCGEventOtherMouseUp, 2),
        }.get(button, (CG.kCGEventLeftMouseDown, CG.kCGEventLeftMouseUp, 0))
        for _ in range(max(1, clicks)):
            CG.CGEventPost(CG.kCGHIDEventTap, CG.CGEventCreateMouseEvent(None, down, (x, y), btn))
            CG.CGEventPost(CG.kCGHIDEventTap, CG.CGEventCreateMouseEvent(None, up, (x, y), btn))

    def type_text(self, text: str) -> None:
        CG = self.CG
        for ch in text:
            ev = CG.CGEventCreateKeyboardEvent(None, 0, True)
            CG.CGEventKeyboardSetUnicodeString(ev, len(ch), ch)
            CG.CGEventPost(CG.kCGHIDEventTap, ev)
            ev_up = CG.CGEventCreateKeyboardEvent(None, 0, False)
            CG.CGEventKeyboardSetUnicodeString(ev_up, len(ch), ch)
            CG.CGEventPost(CG.kCGHIDEventTap, ev_up)

    _MAC_KEYCODES = {"return": 36, "enter": 36, "tab": 48, "space": 49,
                     "escape": 53, "esc": 53, "delete": 51, "backspace": 51}
    _MAC_FLAGS = {"cmd": 1 << 20, "command": 1 << 20, "shift": 1 << 17,
                  "alt": 1 << 19, "option": 1 << 19, "ctrl": 1 << 18, "control": 1 << 18}

    def press_key(self, key: str) -> None:
        CG = self.CG
        parts = [p.strip().lower() for p in key.split("+") if p.strip()]
        if not parts:
            return
        *mods, main = parts
        flags = 0
        for m in mods:
            flags |= self._MAC_FLAGS.get(m, 0)
        code = self._MAC_KEYCODES.get(main)
        if code is None:
            self.type_text(main)
            return
        for press in (True, False):
            ev = CG.CGEventCreateKeyboardEvent(None, code, press)
            if flags:
                CG.CGEventSetFlags(ev, flags)
            CG.CGEventPost(CG.kCGHIDEventTap, ev)

    def scroll(self, amount: int) -> None:
        CG = self.CG
        ev = CG.CGEventCreateScrollWheelEvent(None, 0, 1, int(amount))
        CG.CGEventPost(CG.kCGHIDEventTap, ev)

    def close(self) -> None:
        pass


class WindowsInput:
    """Windows input via ctypes SendInput. UNVERIFIED on this CI."""

    def __init__(self) -> None:
        import ctypes

        self.ctypes = ctypes
        self.user32 = ctypes.windll.user32  # type: ignore[attr-defined]

    def screen_size(self) -> tuple:
        return (self.user32.GetSystemMetrics(0), self.user32.GetSystemMetrics(1))

    def _send_mouse(self, flags: int, x: int = 0, y: int = 0, data: int = 0) -> None:
        import ctypes
        from ctypes import wintypes

        class MOUSEINPUT(ctypes.Structure):
            _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG),
                        ("mouseData", wintypes.DWORD), ("dwFlags", wintypes.DWORD),
                        ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong))]

        class INPUT(ctypes.Structure):
            class _I(ctypes.Union):
                _fields_ = [("mi", MOUSEINPUT)]
            _anonymous_ = ("i",)
            _fields_ = [("type", wintypes.DWORD), ("i", _I)]

        inp = INPUT(type=0, mi=MOUSEINPUT(x, y, data, flags, 0, None))
        self.user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(inp))

    def move(self, x: int, y: int) -> None:
        w, h = self.screen_size()
        ax, ay = int(x * 65535 / max(1, w)), int(y * 65535 / max(1, h))
        self._send_mouse(0x0001 | 0x8000, ax, ay)  # MOVE | ABSOLUTE

    def click(self, x=None, y=None, button: str = "left", clicks: int = 1) -> None:
        if x is not None and y is not None:
            self.move(x, y)
        down, up = {
            "left": (0x0002, 0x0004), "right": (0x0008, 0x0010), "middle": (0x0020, 0x0040),
        }.get(button, (0x0002, 0x0004))
        for _ in range(max(1, clicks)):
            self._send_mouse(down)
            self._send_mouse(up)

    def _send_key(self, vk: int, up: bool = False, unicode_char: Optional[str] = None) -> None:
        import ctypes
        from ctypes import wintypes

        class KEYBDINPUT(ctypes.Structure):
            _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD),
                        ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD),
                        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong))]

        class INPUT(ctypes.Structure):
            class _I(ctypes.Union):
                _fields_ = [("ki", KEYBDINPUT)]
            _anonymous_ = ("i",)
            _fields_ = [("type", wintypes.DWORD), ("i", _I)]

        flags = (0x0002 if up else 0)
        if unicode_char is not None:
            flags |= 0x0004  # KEYEVENTF_UNICODE
            ki = KEYBDINPUT(0, ord(unicode_char), flags, 0, None)
        else:
            ki = KEYBDINPUT(vk, 0, flags, 0, None)
        inp = INPUT(type=1, ki=ki)
        self.user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(inp))

    def type_text(self, text: str) -> None:
        for ch in text:
            self._send_key(0, up=False, unicode_char=ch)
            self._send_key(0, up=True, unicode_char=ch)

    _VK = {"return": 0x0D, "enter": 0x0D, "tab": 0x09, "space": 0x20, "escape": 0x1B,
           "esc": 0x1B, "backspace": 0x08, "delete": 0x2E, "ctrl": 0x11, "control": 0x11,
           "shift": 0x10, "alt": 0x12, "win": 0x5B, "cmd": 0x5B}

    def press_key(self, key: str) -> None:
        parts = [p.strip().lower() for p in key.split("+") if p.strip()]
        if not parts:
            return
        *mods, main = parts
        codes = [self._VK[m] for m in mods if m in self._VK]
        main_vk = self._VK.get(main)
        for c in codes:
            self._send_key(c)
        if main_vk is not None:
            self._send_key(main_vk)
            self._send_key(main_vk, up=True)
        elif len(main) == 1:
            self._send_key(0, unicode_char=main)
            self._send_key(0, up=True, unicode_char=main)
        for c in reversed(codes):
            self._send_key(c, up=True)

    def scroll(self, amount: int) -> None:
        self._send_mouse(0x0800, data=int(amount) * 120)  # WHEEL, 120 per notch

    def close(self) -> None:
        pass


def make_input_driver(display: Optional[str] = None):
    """Pick the input driver for the current OS."""
    if sys.platform == "darwin":
        return QuartzInput()
    if sys.platform.startswith("win"):
        return WindowsInput()
    return X11Input(display)


# --------------------------------------------------------------------------
# Backends
# --------------------------------------------------------------------------

class FakeDesktopBackend:
    """Deterministic desktop backend for tests. No display."""

    def __init__(
        self, *, width: int = 1280, height: int = 800, text: str = "",
        on_action: Optional[Callable[["FakeDesktopBackend", str, dict], None]] = None,
    ) -> None:
        self.width = width
        self.height = height
        self.text = text
        self._obs = BufferedObserver()
        self._on = on_action
        self.actions: list[tuple[str, dict]] = []
        self.pointer = (0, 0)
        self.closed = False

    def _act(self, name: str, **kw: Any) -> None:
        self.actions.append((name, kw))
        if self._on:
            self._on(self, name, kw)

    def observer(self) -> BufferedObserver:
        return self._obs

    def screen_size(self) -> tuple:
        return (self.width, self.height)

    def url(self) -> str:
        return f"desktop ({self.width}x{self.height})"

    def move(self, x: int, y: int) -> None:
        self.pointer = (x, y)
        self._act("move", x=x, y=y)

    def click(self, x=None, y=None, button: str = "left", clicks: int = 1) -> None:
        if x is not None and y is not None:
            self.pointer = (x, y)
        self._act("click", x=x, y=y, button=button, clicks=clicks)

    def type_text(self, text: str) -> None:
        self._act("type_text", text=text)

    def press_key(self, key: str) -> None:
        self._act("press_key", key=key)

    def scroll(self, amount: int) -> None:
        self._act("scroll", amount=amount)

    def snapshot(self, max_chars: int = 2000) -> str:
        return self.text[:max_chars]

    def screenshot(self) -> bytes:
        return b"\x89PNG\r\n\x1a\n-fake-desktop-"

    def text_content(self, max_chars: int = 2000) -> str:
        return self.text[:max_chars]

    def pump(self) -> None:
        return None

    def close(self) -> None:
        self.closed = True


class DesktopBackend:
    """Real desktop control: a platform InputDriver + mss capture + screen diff."""

    def __init__(self, input_driver: Any, sct: Any, *, screen_size: tuple) -> None:
        self.input = input_driver
        self._sct = sct
        self._w, self._h = screen_size
        self._obs = BufferedObserver()
        self._differ = ScreenDiffer(screen_size=screen_size)
        try:
            self._differ.events(self._differ.grid_from_image(self._grab()))
        except Exception:  # noqa: BLE001
            pass

    @classmethod
    def launch(cls, *, display: Optional[str] = None) -> "DesktopBackend":
        try:
            import mss
        except Exception as e:  # noqa: BLE001
            raise RuntimeError(
                "desktop control needs the desktop extra: "
                "pip install 'essarion-build[desktop]' (mss, Pillow, and an OS input "
                "driver — python-xlib on Linux)."
            ) from e
        driver = make_input_driver(display)
        factory = getattr(mss, "MSS", None) or mss.mss
        sct = factory()
        mon = sct.monitors[1] if len(sct.monitors) > 1 else sct.monitors[0]
        size = (mon["width"], mon["height"])
        return cls(driver, sct, screen_size=size)

    def _grab(self):
        from PIL import Image

        mon = self._sct.monitors[1] if len(self._sct.monitors) > 1 else self._sct.monitors[0]
        shot = self._sct.grab(mon)
        return Image.frombytes("RGB", shot.size, shot.rgb)

    def screenshot(self) -> bytes:
        import io

        buf = io.BytesIO()
        self._grab().save(buf, format="PNG")
        return buf.getvalue()

    def screen_size(self) -> tuple:
        return (self._w, self._h)

    def url(self) -> str:
        return f"desktop ({self._w}x{self._h})"

    # input delegates to the platform driver
    def move(self, x: int, y: int) -> None:
        self.input.move(x, y)

    def click(self, x=None, y=None, button: str = "left", clicks: int = 1) -> None:
        self.input.click(x=x, y=y, button=button, clicks=clicks)

    def type_text(self, text: str) -> None:
        self.input.type_text(text)

    def press_key(self, key: str) -> None:
        self.input.press_key(key)

    def scroll(self, amount: int) -> None:
        self.input.scroll(amount)

    # observer
    def observer(self) -> BufferedObserver:
        return self._obs

    def pump(self) -> None:
        try:
            grid = self._differ.grid_from_image(self._grab())
        except Exception:  # noqa: BLE001
            return
        for ev in self._differ.events(grid):
            self._obs.push(ev)

    def text_content(self, max_chars: int = 2000) -> str:
        try:
            import pytesseract  # type: ignore

            return (pytesseract.image_to_string(self._grab()) or "")[:max_chars]
        except Exception:  # noqa: BLE001
            return ""

    def close(self) -> None:
        for fn in (getattr(self._sct, "close", None), getattr(self.input, "close", None)):
            if callable(fn):
                try:
                    fn()
                except Exception:  # noqa: BLE001
                    pass

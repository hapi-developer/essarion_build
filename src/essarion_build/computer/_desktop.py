"""Desktop backend — control the real machine's mouse, keyboard, and screen.

`DesktopBackend` drives the actual display: X11 input via the XTEST extension
(the same mechanism xdotool uses), screen capture via mss, and the screen-diff
observer as its event source. On a user's machine this is *their* screen — see
the safety gating in agent/_desktop.py; this module is the mechanism, not the
policy. `FakeDesktopBackend` is the deterministic stand-in for tests.

Input is X11-specific today (Linux / the contained Xvfb we test against). The
backend is structured so a macOS (Quartz) or Windows (SendInput) implementation
slots in behind the same interface.
"""

from __future__ import annotations

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
# friendly key name → X keysym name, for press_key chords.
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


class FakeDesktopBackend:
    """Deterministic desktop backend for tests. `on_action` lets a test push the
    screen events a real action would cause."""

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

    def screenshot(self) -> bytes:
        return b"\x89PNG\r\n\x1a\n-fake-desktop-"

    def text_content(self, max_chars: int = 2000) -> str:
        return self.text[:max_chars]

    def pump(self) -> None:
        # Real backend diffs screenshots here; the fake pushes via on_action.
        return None

    def close(self) -> None:
        self.closed = True


class DesktopBackend:
    """Real X11 desktop control (XTEST input + mss capture + screen diff)."""

    def __init__(self, d: Any, sct: Any, *, screen_size: tuple) -> None:
        self._d = d
        self._sct = sct
        self._w, self._h = screen_size
        self._obs = BufferedObserver()
        self._differ = ScreenDiffer(screen_size=screen_size)
        # Establish a baseline frame so the first action's diff is meaningful.
        try:
            self._differ.events(self._differ.grid_from_image(self._grab()))
        except Exception:  # noqa: BLE001
            pass

    @classmethod
    def launch(cls, *, display: Optional[str] = None) -> "DesktopBackend":
        try:
            from Xlib import display as _display
            import mss
        except Exception as e:  # noqa: BLE001
            raise RuntimeError(
                "desktop control needs the desktop extra: "
                "pip install 'essarion-build[desktop]' (python-xlib, mss, Pillow), "
                "and a display ($DISPLAY)."
            ) from e
        d = _display.Display(display) if display else _display.Display()
        geo = d.screen().root.get_geometry()
        factory = getattr(mss, "MSS", None) or mss.mss  # MSS() is the modern name
        sct = factory()
        return cls(d, sct, screen_size=(geo.width, geo.height))

    # --- capture ---
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

    # --- input (XTEST) ---
    def move(self, x: int, y: int) -> None:
        self._d.screen().root.warp_pointer(int(x), int(y))
        self._d.sync()

    def click(self, x=None, y=None, button: str = "left", clicks: int = 1) -> None:
        from Xlib import X
        from Xlib.ext import xtest

        if x is not None and y is not None:
            self.move(x, y)
        b = _BUTTONS.get(button, 1)
        for _ in range(max(1, clicks)):
            xtest.fake_input(self._d, X.ButtonPress, b)
            xtest.fake_input(self._d, X.ButtonRelease, b)
        self._d.sync()

    def _tap_keysym(self, keysym: int, *, shift: bool = False) -> None:
        from Xlib import X, XK
        from Xlib.ext import xtest

        keycode = self._d.keysym_to_keycode(keysym)
        if not keycode:
            return
        shift_code = self._d.keysym_to_keycode(XK.XK_Shift_L)
        if shift:
            xtest.fake_input(self._d, X.KeyPress, shift_code)
        xtest.fake_input(self._d, X.KeyPress, keycode)
        xtest.fake_input(self._d, X.KeyRelease, keycode)
        if shift:
            xtest.fake_input(self._d, X.KeyRelease, shift_code)
        self._d.sync()

    def _char_keysym(self, ch: str) -> tuple:
        from Xlib import XK

        name = _SPECIAL_CHARS.get(ch, ch)
        keysym = XK.string_to_keysym(name)
        if not keysym:
            keysym = 0x01000000 + ord(ch)  # unicode keysym fallback
        keycode = self._d.keysym_to_keycode(keysym)
        shift = False
        if keycode:
            base = self._d.keycode_to_keysym(keycode, 0)
            shifted = self._d.keycode_to_keysym(keycode, 1)
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
            code = self._d.keysym_to_keycode(ks) if ks else 0
            if code:
                mod_codes.append(code)
        main_name = _KEY_ALIASES.get(main.lower(), main)
        main_ks = XK.string_to_keysym(main_name) or (0x01000000 + ord(main) if len(main) == 1 else 0)
        main_code = self._d.keysym_to_keycode(main_ks) if main_ks else 0
        for c in mod_codes:
            xtest.fake_input(self._d, X.KeyPress, c)
        if main_code:
            xtest.fake_input(self._d, X.KeyPress, main_code)
            xtest.fake_input(self._d, X.KeyRelease, main_code)
        for c in reversed(mod_codes):
            xtest.fake_input(self._d, X.KeyRelease, c)
        self._d.sync()

    def scroll(self, amount: int) -> None:
        from Xlib import X
        from Xlib.ext import xtest

        button = 4 if amount > 0 else 5  # 4 = up, 5 = down
        for _ in range(abs(int(amount))):
            xtest.fake_input(self._d, X.ButtonPress, button)
            xtest.fake_input(self._d, X.ButtonRelease, button)
        self._d.sync()

    # --- observer ---
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
        # OCR is optional; without it, text expectations are reported "unclear".
        try:
            import pytesseract  # type: ignore

            return (pytesseract.image_to_string(self._grab()) or "")[:max_chars]
        except Exception:  # noqa: BLE001
            return ""

    def close(self) -> None:
        for fn in (getattr(self._sct, "close", None), getattr(self._d, "close", None)):
            if callable(fn):
                try:
                    fn()
                except Exception:  # noqa: BLE001
                    pass

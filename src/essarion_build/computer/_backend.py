"""Action backends — the controllable surface the agent acts on.

`Backend` is the seam: action primitives (navigate/click/type/key/scroll/…)
plus an `observer()` the action tools drain after each step. Two backends:

* `FakeBackend` — a deterministic in-memory page model for tests. An
  `on_action` hook lets a test inject the events + state changes a real page
  would produce, so the entire act→observe→reduce→expect loop is exercised with
  zero browser and zero flakiness.
* `PlaywrightBackend` — the real browser, built lazily so importing this module
  never requires playwright. It wires a CDP/Playwright event tap (console,
  network failures, navigation, dialogs, plus a DOM-mutation observer injected
  into the page) into the observer — the reactive tap that catches transient
  changes a naive screenshot agent misses.
"""

from __future__ import annotations

from typing import Any, Callable, Optional, Protocol, runtime_checkable

from ._observer import BufferedObserver


@runtime_checkable
class Backend(Protocol):
    def observer(self) -> BufferedObserver: ...
    def url(self) -> str: ...
    def navigate(self, url: str) -> None: ...
    def click(self, selector: Optional[str] = None, x: Optional[int] = None, y: Optional[int] = None) -> None: ...
    def type_text(self, text: str, selector: Optional[str] = None) -> None: ...
    def press_key(self, key: str) -> None: ...
    def scroll(self, dy: int = 0, dx: int = 0) -> None: ...
    def snapshot(self, max_chars: int = 2000) -> str: ...
    def screenshot(self) -> bytes: ...
    def close(self) -> None: ...


class FakeBackend:
    """Deterministic backend for tests and demos. No browser.

    `on_action(backend, name, kwargs)` is called after each action so a test can
    push synthetic observer events and mutate `current_url` / `outline` exactly
    as a real page would react.
    """

    def __init__(
        self,
        *,
        url: str = "about:blank",
        outline: str = "(empty page)",
        on_action: Optional[Callable[["FakeBackend", str, dict[str, Any]], None]] = None,
    ) -> None:
        self.current_url = url
        self.outline = outline
        self._obs = BufferedObserver()
        self._on_action = on_action
        self.actions: list[tuple[str, dict[str, Any]]] = []
        self.closed = False

    def _act(self, name: str, **kw: Any) -> None:
        self.actions.append((name, kw))
        if self._on_action is not None:
            self._on_action(self, name, kw)

    def observer(self) -> BufferedObserver:
        return self._obs

    def url(self) -> str:
        return self.current_url

    def navigate(self, url: str) -> None:
        self.current_url = url
        self._act("navigate", url=url)

    def click(self, selector=None, x=None, y=None) -> None:
        self._act("click", selector=selector, x=x, y=y)

    def type_text(self, text: str, selector=None) -> None:
        self._act("type_text", text=text, selector=selector)

    def press_key(self, key: str) -> None:
        self._act("press_key", key=key)

    def scroll(self, dy: int = 0, dx: int = 0) -> None:
        self._act("scroll", dy=dy, dx=dx)

    def snapshot(self, max_chars: int = 2000) -> str:
        return self.outline[:max_chars]

    def text_content(self, max_chars: int = 2000) -> str:
        return getattr(self, "text", self.outline)[:max_chars]

    def screenshot(self) -> bytes:
        return b"\x89PNG\r\n\x1a\n-fake-screenshot-"

    def close(self) -> None:
        self.closed = True


# DOM mutation tap injected into every page: batches mutations and forwards a
# compact summary to a Python binding ~10x/sec, instead of one event per node.
_DOM_TAP_JS = r"""
(() => {
  // Mutations are pushed into a page-side queue that Python pulls synchronously
  // when it observes — no async binding round-trip, so nothing is lost when the
  // page also throws or fetches in the same handler. Idempotent on the observer.
  const install = () => {
    if (window.__essarionObs) return true;
    const target = document.documentElement || document.body;
    if (!target) return false;
    window.__essarionQueue = window.__essarionQueue || [];
    const obs = new MutationObserver((muts) => {
      let added = 0, removed = 0;
      for (const m of muts) { added += m.addedNodes.length; removed += m.removedNodes.length; }
      const q = window.__essarionQueue;
      q.push({mutations: muts.length, added, removed});
      if (q.length > 500) q.splice(0, q.length - 500);
    });
    obs.observe(target, {childList: true, subtree: true, attributes: true, characterData: true});
    window.__essarionObs = obs;
    return true;
  };
  if (!install()) {
    document.addEventListener('DOMContentLoaded', install);
    window.addEventListener('load', install);
  }
})();
"""

_DOM_PUMP_JS = "() => { const q = window.__essarionQueue || []; window.__essarionQueue = []; return q; }"


# Fallback page outline when the accessibility tree is empty: headings, links,
# buttons, inputs, and labels with their selectors — enough to choose an action.
_DOM_OUTLINE_JS = r"""
() => {
  const out = [];
  const sel = (el) => el.id ? '#'+el.id : (el.name ? `[name="${el.name}"]` : el.tagName.toLowerCase());
  for (const el of document.querySelectorAll('h1,h2,h3,a,button,input,textarea,select,[role=button],label')) {
    if (out.length > 80) break;
    const t = (el.innerText || el.value || el.placeholder || el.getAttribute('aria-label') || '').trim().slice(0,60);
    const tag = el.tagName.toLowerCase();
    out.push(`${tag} ${sel(el)}: ${t}`.trim());
  }
  return out;
}
"""


class PlaywrightBackend:
    """Real browser backend (lazy playwright import; created via :meth:`launch`)."""

    def __init__(self, page: Any, browser: Any, pw: Any) -> None:
        self._page = page
        self._browser = browser
        self._pw = pw
        self._obs = BufferedObserver()
        self._wire_taps()

    @classmethod
    def launch(cls, *, headless: bool = True, viewport: Optional[dict] = None) -> "PlaywrightBackend":
        try:
            from playwright.sync_api import sync_playwright
        except Exception as e:  # noqa: BLE001
            raise RuntimeError(
                "computer-use browser tier needs playwright: pip install 'essarion-build[computer]' "
                "and run `playwright install chromium`."
            ) from e
        pw = sync_playwright().start()
        browser = pw.chromium.launch(headless=headless)
        page = browser.new_page(viewport=viewport or {"width": 1280, "height": 800})
        return cls(page, browser, pw)

    # --- the reactive CDP/Playwright tap ---
    def _wire_taps(self) -> None:
        p, obs = self._page, self._obs

        def _console(msg: Any) -> None:
            sev = "error" if msg.type == "error" else ("warn" if msg.type == "warning" else "info")
            obs.push_event("console", f"{msg.type}: {msg.text}"[:200], severity=sev)

        def _pageerror(err: Any) -> None:
            obs.push_event("console", f"uncaught: {err}"[:200], severity="error")

        def _requestfailed(req: Any) -> None:
            obs.push_event("network", f"{req.method} {req.url} FAILED ({req.failure})"[:200], severity="warn")

        def _response(resp: Any) -> None:
            try:
                status = resp.status
            except Exception:  # noqa: BLE001
                return
            sev = "error" if status >= 500 else ("warn" if status >= 400 else "info")
            if status >= 400:
                obs.push_event("network", f"{resp.request.method} {resp.url} {status}"[:200], severity=sev)

        def _framenav(frame: Any) -> None:
            if frame == p.main_frame:
                obs.push_event("navigation", f"navigated to {frame.url}"[:200], severity="notice")

        def _dialog(dialog: Any) -> None:
            obs.push_event("dialog", f"{dialog.type}: {dialog.message}"[:200], severity="warn")
            try:
                dialog.dismiss()
            except Exception:  # noqa: BLE001
                pass

        p.on("console", _console)
        p.on("pageerror", _pageerror)
        p.on("requestfailed", _requestfailed)
        p.on("response", _response)
        p.on("framenavigated", _framenav)
        p.on("dialog", _dialog)
        try:
            p.add_init_script(_DOM_TAP_JS)
        except Exception:  # noqa: BLE001 - tap is best-effort
            pass

    def pump(self) -> None:
        """Pull queued DOM mutations from the page into the observer. Called by
        the action tools right before they drain, so DOM changes are captured
        synchronously regardless of page error/fetch timing."""
        try:
            batch = self._page.evaluate(_DOM_PUMP_JS) or []
        except Exception:  # noqa: BLE001
            return
        total = sum(b.get("mutations", 0) for b in batch)
        if total:
            self._obs.push_event(
                "dom", "DOM subtree updated", severity="info",
                mutations=total,
                added=sum(b.get("added", 0) for b in batch),
                removed=sum(b.get("removed", 0) for b in batch),
            )

    def observer(self) -> BufferedObserver:
        return self._obs

    def url(self) -> str:
        return self._page.url

    def navigate(self, url: str) -> None:
        self._page.goto(url, wait_until="domcontentloaded")
        # Re-install the DOM tap on the now-live document (idempotent). The
        # init-script path can miss if it ran before the DOM existed.
        try:
            self._page.evaluate(_DOM_TAP_JS)
        except Exception:  # noqa: BLE001
            pass

    def click(self, selector=None, x=None, y=None) -> None:
        if selector:
            self._page.click(selector, timeout=8000)
        elif x is not None and y is not None:
            self._page.mouse.click(x, y)
        else:
            raise ValueError("click needs either selector or x/y")

    def type_text(self, text: str, selector=None) -> None:
        if selector:
            self._page.fill(selector, text, timeout=8000)
        else:
            self._page.keyboard.type(text)

    def press_key(self, key: str) -> None:
        self._page.keyboard.press(key)

    def scroll(self, dy: int = 0, dx: int = 0) -> None:
        self._page.mouse.wheel(dx, dy)

    def snapshot(self, max_chars: int = 2000) -> str:
        # Accessibility-tree text outline — semantic, compact, and vision-free.
        lines: list[str] = []
        try:
            tree = self._page.accessibility.snapshot(interesting_only=False) or {}

            def walk(node: dict, depth: int = 0) -> None:
                if len(lines) > 120:
                    return
                role = node.get("role", "")
                name = (node.get("name", "") or "").strip()
                if role and role not in ("generic", "none", "InlineTextBox", ""):
                    lines.append(("  " * min(depth, 8) + f"{role}: {name}")[:100])
                for child in node.get("children", []) or []:
                    walk(child, depth + 1)

            walk(tree)
        except Exception:  # noqa: BLE001
            pass
        if not lines:
            # Fallback: a DOM outline of interactive + landmark elements via JS.
            try:
                lines = self._page.evaluate(_DOM_OUTLINE_JS) or []
            except Exception:  # noqa: BLE001
                lines = [self._page.title()]
        return ("\n".join(lines) or self._page.title())[:max_chars]

    def text_content(self, max_chars: int = 2000) -> str:
        try:
            return (self._page.inner_text("body") or "")[:max_chars]
        except Exception:  # noqa: BLE001
            return ""

    def screenshot(self) -> bytes:
        return self._page.screenshot()

    def close(self) -> None:
        for fn in (self._page.context.close, self._browser.close, self._pw.stop):
            try:
                fn()
            except Exception:  # noqa: BLE001
                pass

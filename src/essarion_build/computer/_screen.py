"""Screen-diff observer — the universal floor of the desktop tier.

The browser tier gets rich semantic events from CDP. A native desktop has no such
tap by default, so the floor is deterministic screen diffing: downsample each
frame to a coarse grid of cell colors, compare consecutive frames, and report the
regions that changed. It tells you *that* something changed and *where* — not
*what* (OCR, when available, fills that in) — but it works on any app, any OS,
including canvas/Electron/games/remote surfaces.

The diff is pure grid math (no image library, no display) so it's fast and fully
testable with synthetic grids; the backend supplies the grid from a screenshot.
"""

from __future__ import annotations

import collections
from dataclasses import dataclass, field
from typing import Optional

from ._events import ObservedEvent

Cell = tuple  # (r, g, b)
Grid = list  # list[list[Cell]], rows of cols


@dataclass
class ChangedRegion:
    col0: int
    row0: int
    col1: int
    row1: int
    cells: int
    frac: float  # fraction of the whole screen this region covers
    px_center: Optional[tuple] = None  # (x, y) if screen size known


def _changed_cells(a: Grid, b: Grid, threshold: int) -> list[list[bool]]:
    rows = len(b)
    cols = len(b[0]) if rows else 0
    out = [[False] * cols for _ in range(rows)]
    for r in range(rows):
        for c in range(cols):
            ar, ag, ab = a[r][c]
            br, bg, bb = b[r][c]
            if max(abs(ar - br), abs(ag - bg), abs(ab - bb)) > threshold:
                out[r][c] = True
    return out


def _components(changed: list[list[bool]]) -> list[list[tuple]]:
    rows = len(changed)
    cols = len(changed[0]) if rows else 0
    seen = [[False] * cols for _ in range(rows)]
    comps: list[list[tuple]] = []
    for r in range(rows):
        for c in range(cols):
            if changed[r][c] and not seen[r][c]:
                q = collections.deque([(r, c)])
                seen[r][c] = True
                cells = []
                while q:
                    rr, cc = q.popleft()
                    cells.append((rr, cc))
                    for dr, dc in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                        nr, nc = rr + dr, cc + dc
                        if 0 <= nr < rows and 0 <= nc < cols and changed[nr][nc] and not seen[nr][nc]:
                            seen[nr][nc] = True
                            q.append((nr, nc))
                comps.append(cells)
    return comps


class ScreenDiffer:
    """Holds the previous frame; turns each new frame into change events."""

    def __init__(
        self, *, cols: int = 24, rows: int = 16, threshold: int = 24,
        screen_size: Optional[tuple] = None, min_cells: int = 1,
    ) -> None:
        self.cols = cols
        self.rows = rows
        self.threshold = threshold
        self.screen_size = screen_size  # (w, h) in pixels, for px_center
        self.min_cells = min_cells
        self._last: Optional[Grid] = None

    def reset(self) -> None:
        self._last = None

    def regions(self, grid: Grid) -> list[ChangedRegion]:
        """Compare `grid` to the stored frame; return changed regions. The first
        call establishes a baseline and returns nothing."""
        prev = self._last
        self._last = grid
        if prev is None:
            return []
        changed = _changed_cells(prev, grid, self.threshold)
        total = self.cols * self.rows
        regions: list[ChangedRegion] = []
        for comp in _components(changed):
            if len(comp) < self.min_cells:
                continue
            rs = [r for r, _ in comp]
            cs = [c for _, c in comp]
            r0, r1, c0, c1 = min(rs), max(rs), min(cs), max(cs)
            px_center = None
            if self.screen_size:
                w, h = self.screen_size
                cx = int((c0 + c1 + 1) / 2 / self.cols * w)
                cy = int((r0 + r1 + 1) / 2 / self.rows * h)
                px_center = (cx, cy)
            regions.append(ChangedRegion(c0, r0, c1, r1, len(comp), len(comp) / total, px_center))
        # Largest change first.
        regions.sort(key=lambda x: x.cells, reverse=True)
        return regions

    def events(self, grid: Grid) -> list[ObservedEvent]:
        out: list[ObservedEvent] = []
        for reg in self.regions(grid):
            pct = round(reg.frac * 100)
            where = f"cols {reg.col0}-{reg.col1}, rows {reg.row0}-{reg.row1}"
            if reg.px_center:
                where += f" (~center {reg.px_center[0]},{reg.px_center[1]}px)"
            sev = "notice" if reg.frac >= 0.04 else "info"
            out.append(ObservedEvent(
                kind="screen", summary=f"screen changed: {where} (~{pct}% area)",
                severity=sev, source="desktop",
                detail={"bbox": [reg.col0, reg.row0, reg.col1, reg.row1],
                        "cells": reg.cells, "frac": reg.frac, "center": reg.px_center},
            ))
        return out

    # --- image → grid (needs Pillow; only used by the real backend) ---
    def grid_from_image(self, image) -> Grid:
        small = image.convert("RGB").resize((self.cols, self.rows))
        raw = small.tobytes()  # row-major RGB triples
        grid: Grid = []
        for r in range(self.rows):
            base = r * self.cols * 3
            grid.append([
                (raw[base + c * 3], raw[base + c * 3 + 1], raw[base + c * 3 + 2])
                for c in range(self.cols)
            ])
        return grid

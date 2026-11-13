"""Где находится панель Plasma с системным треем (через скрипты plasmashell).

Под Wayland/XWayland Qt не знает рабочую область экрана, поэтому
спрашиваем plasmashell напрямую. Результат кэшируется.
"""
from __future__ import annotations

import time
from dataclasses import dataclass

from PyQt6.QtCore import QRect
from PyQt6.QtDBus import QDBusConnection, QDBusInterface, QDBusMessage

FLOAT_GAP = 8  # отступ плавающей панели Plasma 6 от края экрана

_SCRIPT = r"""
panels().forEach(function (p) {
  var g = screenGeometry(p.screen);
  print([p.location, p.height, p.floating ? 1 : 0, p.alignment, p.length, p.offset || 0,
         g.x, g.y, g.width, g.height,
         p.widgets("org.kde.plasma.systemtray").length].join(" ") + "\n");
});
"""


@dataclass
class PanelInfo:
    location: str   # top / bottom / left / right
    rect: QRect     # геометрия самой панели
    screen: QRect   # геометрия экрана


_cache: tuple[float, PanelInfo | None] = (0.0, None)


def _query() -> PanelInfo | None:
    iface = QDBusInterface("org.kde.plasmashell", "/PlasmaShell", "org.kde.PlasmaShell",
                           QDBusConnection.sessionBus())
    if not iface.isValid():
        return None
    iface.setTimeout(1500)
    reply = iface.call("evaluateScript", _SCRIPT)
    if reply.type() != QDBusMessage.MessageType.ReplyMessage or not reply.arguments():
        return None
    best = None
    for line in str(reply.arguments()[0]).splitlines():
        parts = line.split()
        if len(parts) != 11:
            continue
        loc, thick, floating, align, length, offset, gx, gy, gw, gh, tray = parts
        try:
            thick, floating, length, offset = int(float(thick)), int(floating), int(float(length)), int(float(offset))
            gx, gy, gw, gh, tray = (int(float(v)) for v in (gx, gy, gw, gh, tray))
        except ValueError:
            continue
        gap = FLOAT_GAP if floating else 0
        horizontal = loc in ("top", "bottom")
        span = gw if horizontal else gh
        length = min(length, span) if length > 0 else span
        if align == "center":
            start = (span - length) // 2
        elif align == "right":
            start = span - offset - length
        else:
            start = offset
        if loc == "bottom":
            r = QRect(gx + start, gy + gh - gap - thick, length, thick)
        elif loc == "top":
            r = QRect(gx + start, gy + gap, length, thick)
        elif loc == "left":
            r = QRect(gx + gap, gy + start, thick, length)
        elif loc == "right":
            r = QRect(gx + gw - gap - thick, gy + start, thick, length)
        else:
            continue
        info = PanelInfo(loc, r, QRect(gx, gy, gw, gh))
        if tray:
            return info
        if best is None:
            best = info
    return best


def tray_panel(ttl: float = 30.0) -> PanelInfo | None:
    global _cache
    now = time.monotonic()
    if now - _cache[0] > ttl:
        try:
            _cache = (now, _query())
        except Exception:
            _cache = (now, None)
    return _cache[1]

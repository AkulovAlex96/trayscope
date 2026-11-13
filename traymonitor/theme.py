"""Цвета, шрифты, стили и рисованные иконки (Breeze Dark-подобная тема)."""
from __future__ import annotations

import hashlib
import sys

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import (QColor, QFont, QFontDatabase, QIcon, QPainter,
                         QPainterPath, QPen, QPixmap)

BG = "#202326"
SURFACE = "#2a2e32"
SURFACE2 = "#3a3f44"
BORDER = "#3a3f44"
DIVIDER = "#33383d"
TEXT = "#fcfcfc"
TEXT2 = "#a1a9b1"
ACCENT = "#3daee9"
SELECT_BG = "#1f3a4a"

CPU = "#3daee9"
RAM = "#f67400"
DISK = "#1abc9c"
DISK2 = "#a6ecdc"
NET = "#c189f5"
NET2 = "#e6d2fb"

WARN = "#fdbc4b"
CRIT = "#da4453"
DANGER_BG = "#4a2a2e"
DANGER_FG = "#f2707f"

ICON_TILE_COLORS = ["#ff9a62", "#5fb4f0", "#f5d76e", "#8fd3f5", "#a8e6a1",
                    "#7ec8f2", "#d3b4f7", "#c9ced3", "#f5a3b8", "#9be3d0"]


def level_color(value: float, base: str, warn: float = 70, crit: float = 85) -> str:
    if value >= crit:
        return CRIT
    if value >= warn:
        return WARN
    return base


def heat_color(value: float, vmax: float) -> QColor | None:
    """Янтарная подсветка ячейки в духе диспетчера задач Windows."""
    if not value or value <= 0:
        return None
    alpha = min(0.05 + value / vmax * 0.3, 0.35)
    c = QColor(WARN)
    c.setAlphaF(alpha)
    return c


_MONO_FAMILIES = ["JetBrains Mono", "IBM Plex Mono", "DejaVu Sans Mono",
                  "Cascadia Mono", "Consolas"]


def _mono_family() -> str:
    fams = set(QFontDatabase.families())
    for f in _MONO_FAMILIES:
        if f in fams:
            return f
    return QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont).family()


_mono_cache: str | None = None


def mono_font(px: int, weight: QFont.Weight = QFont.Weight.Normal) -> QFont:
    global _mono_cache
    if _mono_cache is None:
        _mono_cache = _mono_family()
    f = QFont(_mono_cache)
    f.setPixelSize(px)
    f.setWeight(weight)
    return f


def mono_family() -> str:
    mono_font(10)
    return _mono_cache or "monospace"


def ui_font(px: int, weight: QFont.Weight = QFont.Weight.Normal) -> QFont:
    f = QFont()
    f.setPixelSize(px)
    f.setWeight(weight)
    return f


# ---------------------------------------------------------------- форматирование

def fmt_num(v: float, digits: int = 1) -> str:
    return f"{v:.{digits}f}".replace(".", ",")


def fmt_bytes(b: float) -> str:
    gib = 1024 ** 3
    mib = 1024 ** 2
    if b >= gib:
        return f"{fmt_num(b / gib)} ГиБ"
    if b >= mib:
        return f"{b / mib:.0f} МиБ"
    return f"{b / 1024:.0f} КиБ"


def fmt_rate(bps: float) -> tuple[str, str]:
    """Возвращает (число, единица) для скорости в байтах/с."""
    mb = 1024 ** 2
    if bps >= 100 * mb:
        return f"{bps / mb:.0f}", "МБ/с"
    if bps >= mb / 10:
        return fmt_num(bps / mb), "МБ/с"
    return f"{bps / 1024:.0f}", "КБ/с"


def fmt_rate_s(bps: float) -> str:
    n, u = fmt_rate(bps)
    return f"{n} {u}"


def fmt_uptime(sec: float) -> str:
    d, rem = divmod(int(sec), 86400)
    h, rem = divmod(rem, 3600)
    m = rem // 60
    if d:
        return f"{d} д {h} ч"
    if h:
        return f"{h} ч {m} мин"
    return f"{m} мин"


# ---------------------------------------------------------------- иконки

def letter_icon(name: str, size: int = 32) -> QIcon:
    """Цветная плашка с первой буквой, когда у процесса нет иконки в теме."""
    idx = int(hashlib.md5(name.encode()).hexdigest(), 16) % len(ICON_TILE_COLORS)
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(ICON_TILE_COLORS[idx]))
    p.drawRoundedRect(QRectF(0, 0, size, size), size * 0.25, size * 0.25)
    p.setPen(QColor("#141618"))
    f = ui_font(int(size * 0.6), QFont.Weight.Bold)
    p.setFont(f)
    p.drawText(QRectF(0, 0, size, size), Qt.AlignmentFlag.AlignCenter,
               (name[:1] or "?").upper())
    p.end()
    return QIcon(pm)


_proc_icon_cache: dict[str, QIcon] = {}

_ICON_ALIASES = {
    "code": "vscode", "telegram-desktop": "org.telegram.desktop",
    "plasmashell": "plasmashell", "kwin_wayland": "kwin",
    "dolphin": "system-file-manager", "konsole": "utilities-terminal",
    "python3": "python", "chrome": "google-chrome",
}


_icon_provider = None
_exe_seen: set[str] = set()
_letter_cache: dict[str, QIcon] = {}


def _exe_icon(name: str) -> QIcon | None:
    """Windows: иконка из исполняемого файла процесса (как в штатном диспетчере)."""
    global _icon_provider
    from .collector import EXE_BY_NAME
    exe = EXE_BY_NAME.get(name)
    if not exe:
        return None
    _exe_seen.add(name)
    if _icon_provider is None:
        from PyQt6.QtWidgets import QFileIconProvider
        _icon_provider = QFileIconProvider()
    from PyQt6.QtCore import QFileInfo
    ic = _icon_provider.icon(QFileInfo(exe))
    return None if ic.isNull() else ic


def proc_icon(name: str) -> QIcon:
    ic = _proc_icon_cache.get(name)
    if ic is not None:
        return ic
    ic = None
    if sys.platform == "win32":
        ic = _exe_icon(name)
        if ic is None and name not in _exe_seen:
            # путь к .exe пока не известен (нет доступа или сборщик не успел):
            # отдаём букву, но в основной кэш не кладём — вдруг путь появится
            ic = _letter_cache.get(name)
            if ic is None:
                ic = _letter_cache[name] = letter_icon(name)
            return ic
    else:
        candidates = [name, name.lower(), _ICON_ALIASES.get(name, "")]
        for c in candidates:
            if c and QIcon.hasThemeIcon(c):
                ic = QIcon.fromTheme(c)
                break
    if ic is None:
        ic = letter_icon(name)
    _proc_icon_cache[name] = ic
    return ic


def _stroke_icon(draw, color: str, size: int = 32, width: float = 2.0) -> QIcon:
    """draw(painter) рисует в системе координат 24×24 (как lucide)."""
    icon = QIcon()
    for scale in (1, 2):
        s = size * scale
        pm = QPixmap(s, s)
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.scale(s / 24, s / 24)
        pen = QPen(QColor(color), width)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        draw(p)
        p.end()
        pm.setDevicePixelRatio(scale)
        icon.addPixmap(pm)
    return icon


def _poly(p: QPainter, pts):
    path = QPainterPath(QPointF(*pts[0]))
    for pt in pts[1:]:
        path.lineTo(QPointF(*pt))
    p.drawPath(path)


def icon_pulse(color: str) -> QIcon:
    return _stroke_icon(lambda p: _poly(p, [(22, 12), (18, 12), (15, 21), (9, 3), (6, 12), (2, 12)]),
                        color, width=2.4)


def icon_list(color: str) -> QIcon:
    def d(p):
        for y in (6, 12, 18):
            p.drawLine(QPointF(8, y), QPointF(21, y))
            p.drawPoint(QPointF(3, y))
    return _stroke_icon(d, color, width=2.4)


def icon_external(color: str) -> QIcon:
    def d(p):
        _poly(p, [(15, 3), (21, 3), (21, 9)])
        p.drawLine(QPointF(10, 14), QPointF(21, 3))
        _poly(p, [(18, 13), (18, 19), (16, 21), (5, 21), (3, 19), (3, 8), (5, 6), (11, 6)])
    return _stroke_icon(d, color)


def icon_sliders(color: str) -> QIcon:
    def d(p):
        for x, a, b in ((4, 14, 10), (12, 12, 8), (20, 16, 12)):
            p.drawLine(QPointF(x, 21), QPointF(x, a))
            p.drawLine(QPointF(x, b), QPointF(x, 3))
        for x1, y in ((1, 14), (9, 8), (17, 16)):
            p.drawLine(QPointF(x1, y), QPointF(x1 + 6, y))
    return _stroke_icon(d, color)


def icon_search(color: str) -> QIcon:
    def d(p):
        p.drawEllipse(QPointF(11, 11), 7, 7)
        p.drawLine(QPointF(20, 20), QPointF(16.5, 16.5))
    return _stroke_icon(d, color)


def icon_close(color: str) -> QIcon:
    def d(p):
        p.drawLine(QPointF(18, 6), QPointF(6, 18))
        p.drawLine(QPointF(6, 6), QPointF(18, 18))
    return _stroke_icon(d, color, width=3)


def icon_pin(color: str) -> QIcon:
    def d(p):
        p.drawLine(QPointF(12, 17), QPointF(12, 22))
        _poly(p, [(9, 4), (15, 4), (15, 10.5), (19, 14), (19, 17), (5, 17), (5, 14), (9, 10.5), (9, 4)])
        p.drawLine(QPointF(7.5, 3), QPointF(16.5, 3))
    return _stroke_icon(d, color)


def icon_tree(color: str) -> QIcon:
    def d(p):
        p.drawLine(QPointF(3, 5), QPointF(9, 5))
        p.drawLine(QPointF(9, 12), QPointF(15, 12))
        p.drawLine(QPointF(9, 19), QPointF(15, 19))
        _poly(p, [(6, 5), (6, 19), (9, 19)])
        p.drawLine(QPointF(6, 12), QPointF(9, 12))
    return _stroke_icon(d, color)


# ---------------------------------------------------------------- stylesheet

def stylesheet() -> str:
    mono = mono_family()
    return f"""
* {{ outline: none; }}
QWidget#popupRoot, QMainWindow, QDialog, QMessageBox {{ background: {BG}; color: {TEXT}; }}
QWidget {{ color: {TEXT}; }}
QLabel {{ background: transparent; }}
QLabel[role="muted"] {{ color: {TEXT2}; }}
QFrame#tile {{ background: {SURFACE}; border-radius: 8px; }}
QFrame#bigTile {{ background: {SURFACE}; border-radius: 10px; }}

QFrame#seg {{ background: {SURFACE}; border-radius: 7px; }}
QPushButton#segBtn {{
    background: transparent; color: {TEXT2}; border: 0; border-radius: 5px;
    font-weight: 600; padding: 0 8px;
}}
QPushButton#segBtn:checked {{ background: {SURFACE2}; color: {TEXT}; }}
QPushButton#segBtn:hover:!checked {{ color: {TEXT}; }}

QToolButton#iconBtn {{ background: transparent; border: 0; border-radius: 6px; }}
QToolButton#iconBtn:hover {{ background: {SURFACE}; }}
QToolButton#iconBtn:checked {{ background: {SURFACE}; }}
QToolButton#iconBtn::menu-indicator {{ image: none; width: 0; }}

QLineEdit#search {{
    background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 6px;
    color: {TEXT}; padding: 0 6px; selection-background-color: {ACCENT};
}}
QLineEdit#search:focus {{ border-color: {ACCENT}; }}

QTableView, QTreeView {{
    background: transparent; border: 0; color: {TEXT};
    selection-background-color: {SELECT_BG}; selection-color: {TEXT};
    alternate-background-color: transparent;
}}
QTreeView::item {{ height: 30px; border: 0; }}
QTreeView::item:selected {{ background: {SELECT_BG}; }}
QTreeView::item:hover:!selected {{ background: {SURFACE}; }}
QTreeView#procTree::item {{ padding-right: 6px; }}
QTreeView#procTree QScrollBar:vertical {{ width: 14px; margin: 0; background: {BG}; border: 0; border-left: 6px solid {BG}; }}
QHeaderView {{ background: transparent; border: 0; }}
QHeaderView::section {{
    background: transparent; color: {TEXT2}; border: 0;
    border-bottom: 1px solid {DIVIDER}; padding: 2px 8px;
}}
QHeaderView::section:hover {{ color: {TEXT}; }}

QScrollBar:vertical {{ background: transparent; width: 8px; margin: 0; }}
QScrollBar::handle:vertical {{ background: {SURFACE2}; border-radius: 4px; min-height: 24px; }}
QScrollBar::handle:vertical:hover {{ background: #4d5359; }}
QScrollBar:horizontal {{ background: transparent; height: 8px; margin: 0; }}
QScrollBar::handle:horizontal {{ background: {SURFACE2}; border-radius: 4px; min-width: 24px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

QMenu {{
    background: {SURFACE}; border: 1px solid #454b51; border-radius: 8px;
    padding: 5px; color: {TEXT};
}}
QMenu::item {{ padding: 6px 28px 6px 12px; border-radius: 5px; }}
QMenu::item:selected {{ background: {SELECT_BG}; }}
QMenu::item:disabled {{ color: #6c747c; }}
QMenu::separator {{ height: 1px; background: {BORDER}; margin: 4px 6px; }}
QMenu::indicator {{ width: 14px; height: 14px; left: 6px; }}

QTabBar {{ background: transparent; }}
QTabBar::tab {{
    background: transparent; color: {TEXT2}; border: 0;
    border-bottom: 2px solid transparent; padding: 10px 14px; font-size: 13px;
}}
QTabBar::tab:selected {{ color: {TEXT}; border-bottom-color: {ACCENT}; }}
QTabBar::tab:hover:!selected {{ color: {TEXT}; }}

QPushButton#chip {{
    background: transparent; color: {TEXT2}; border: 1px solid {BORDER};
    border-radius: 14px; padding: 0 12px; min-height: 28px; font-size: 12px;
}}
QPushButton#chip:checked {{ background: {SELECT_BG}; color: {TEXT}; border-color: {ACCENT}; }}
QPushButton#chip:hover:!checked {{ color: {TEXT}; }}

QPushButton#ghost {{
    background: transparent; color: {TEXT}; border: 1px solid {BORDER};
    border-radius: 7px; padding: 0 14px; min-height: 30px;
}}
QPushButton#ghost:hover {{ background: {SURFACE}; }}
QPushButton#ghost:checked {{ background: {SURFACE}; }}
QPushButton#danger {{
    background: {CRIT}; color: white; border: 0; border-radius: 7px;
    padding: 0 14px; min-height: 30px; font-weight: 600;
}}
QPushButton#danger:hover {{ background: #e5566a; }}
QPushButton#danger:disabled, QPushButton#ghost:disabled {{ background: {SURFACE}; color: #6c747c; border-color: {SURFACE}; }}

QLabel#status {{ color: {TEXT2}; font-family: "{mono}"; font-size: 12px; }}
QPushButton {{ color: {TEXT}; }}
QMessageBox QLabel {{ color: {TEXT}; }}
QMessageBox QPushButton {{
    background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 6px;
    padding: 5px 16px; min-width: 70px;
}}
QToolTip {{ background: {SURFACE}; color: {TEXT}; border: 1px solid #454b51; padding: 4px 6px; }}
"""

"""Общие виджеты: график-спарклайн, полоски ядер, плитка метрики."""
from __future__ import annotations

from collections import deque

from PyQt6.QtCore import QPointF, QRectF, QSize, Qt
from PyQt6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget

from . import theme as T

HISTORY = 60  # точек на графике


class History:
    def __init__(self) -> None:
        self.cpu: deque[float] = deque(maxlen=HISTORY)
        self.ram: deque[float] = deque(maxlen=HISTORY)
        self.disk_r: deque[float] = deque(maxlen=HISTORY)
        self.disk_w: deque[float] = deque(maxlen=HISTORY)
        self.net_d: deque[float] = deque(maxlen=HISTORY)
        self.net_u: deque[float] = deque(maxlen=HISTORY)

    def push(self, s) -> None:
        self.cpu.append(s.cpu)
        self.ram.append(s.mem_percent)
        self.disk_r.append(s.disk_read)
        self.disk_w.append(s.disk_write)
        self.net_d.append(s.net_down)
        self.net_u.append(s.net_up)


def auto_max(*series, floor: float) -> float:
    m = max((max(s) for s in series if s), default=0.0)
    return max(m * 1.15, floor)


class Sparkline(QWidget):
    """Линейный график с заливкой; опционально вторая пунктирная серия."""

    def __init__(self, parent=None, grid_lines: int = 1) -> None:
        super().__init__(parent)
        self._series: list[tuple[list[float], QColor, bool, bool]] = []
        self._vmax = 100.0
        self._grid = grid_lines
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMinimumHeight(20)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)

    def set_series(self, series, vmax: float) -> None:
        """series: [(values, color_hex, dashed, fill), ...]"""
        self._series = [(list(v), QColor(c), d, f) for v, c, d, f in series]
        self._vmax = vmax or 1.0
        self.update()

    def sizeHint(self) -> QSize:
        return QSize(120, 40)

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        grid_pen = QPen(QColor(T.SURFACE2), 1)
        p.setPen(grid_pen)
        for i in range(1, self._grid + 1):
            y = round(h * i / (self._grid + 1)) + 0.5
            p.drawLine(QPointF(0, y), QPointF(w, y))

        step = w / (HISTORY - 1)
        for values, color, dashed, fill in self._series:
            if len(values) < 2:
                continue
            x0 = w - step * (len(values) - 1)
            pts = [QPointF(x0 + i * step,
                           h - 1 - min(v, self._vmax) / self._vmax * (h - 3))
                   for i, v in enumerate(values)]
            line = QPainterPath(pts[0])
            for pt in pts[1:]:
                line.lineTo(pt)
            if fill:
                area = QPainterPath(line)
                area.lineTo(pts[-1].x(), h)
                area.lineTo(pts[0].x(), h)
                area.closeSubpath()
                c = QColor(color)
                c.setAlphaF(0.2)
                p.fillPath(area, c)
            pen = QPen(color, 1.5)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            if dashed:
                pen.setDashPattern([3, 2])
                pen.setWidthF(1.3)
            p.strokePath(line, pen)
        p.end()


class CoreBars(QWidget):
    def __init__(self, parent=None, bar_bg: str = T.SURFACE2) -> None:
        super().__init__(parent)
        self._vals: list[float] = []
        self._bg = QColor(bar_bg)
        self.setMinimumHeight(10)

    def set_values(self, vals: list[float]) -> None:
        self._vals = list(vals)
        tip = "  ".join(f"{i}: {v:.0f}%" for i, v in enumerate(self._vals))
        self.setToolTip(tip)
        self.update()

    def paintEvent(self, _e) -> None:
        n = len(self._vals)
        if not n:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        gap = 3.0
        w = (self.width() - gap * (n - 1)) / n
        h = self.height()
        for i, v in enumerate(self._vals):
            x = i * (w + gap)
            p.setBrush(self._bg)
            p.drawRoundedRect(QRectF(x, 0, w, h), 2, 2)
            bh = max(2.0, v / 100 * h)
            p.setBrush(QColor(T.level_color(v, T.CPU)))
            p.save()
            p.setClipRect(QRectF(x, h - bh, w, bh))
            p.drawRoundedRect(QRectF(x, 0, w, h), 2, 2)
            p.restore()
        p.end()


class Dot(QWidget):
    def __init__(self, color: str, size: int = 7, parent=None) -> None:
        super().__init__(parent)
        self._c = QColor(color)
        self.setFixedSize(size, size)

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(self._c)
        p.drawRoundedRect(QRectF(0, 0, self.width(), self.height()), 2, 2)
        p.end()


class MetricTile(QFrame):
    """Плитка: точка+название, значение+единица, график, подпись."""

    def __init__(self, label: str, color: str, big: bool = False, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("bigTile" if big else "tile")
        self._big = big
        lay = QVBoxLayout(self)
        if big:
            lay.setContentsMargins(14, 12, 14, 10)
            lay.setSpacing(6)
        else:
            lay.setContentsMargins(9, 6, 9, 5)
            lay.setSpacing(3)

        head = QHBoxLayout()
        head.setSpacing(5)
        head.addWidget(Dot(color, 8 if big else 7))
        self.title = QLabel(label)
        self.title.setFont(T.ui_font(14 if big else 12, QFont.Weight.DemiBold if big else QFont.Weight.Normal))
        if not big:
            self.title.setProperty("role", "muted")
        head.addWidget(self.title)
        head.addStretch(1)
        self.extra = QLabel("")
        self.extra.setFont(T.mono_font(12 if big else 11))
        self.extra.setProperty("role", "muted")
        head.addWidget(self.extra)
        self.value = QLabel("—")
        self.value.setTextFormat(Qt.TextFormat.RichText)
        head.addWidget(self.value)
        lay.addLayout(head)

        self.chart = Sparkline(grid_lines=3 if big else 1)
        lay.addWidget(self.chart, 1)

        self.sub = QLabel("")
        self.sub.setFont(T.mono_font(12 if big else 10))
        self.sub.setProperty("role", "muted")
        self.sub.setMinimumWidth(10)
        self.sub.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        lay.addWidget(self.sub)

    def set_value(self, num: str, unit: str) -> None:
        mono = T.mono_family()
        size = 24 if self._big else 15
        usize = 13 if self._big else 11
        self.value.setText(
            f'<span style="font-family:\'{mono}\'; font-size:{size}px; font-weight:600; color:{T.TEXT}">{num}</span>'
            f'<span style="font-family:\'{mono}\'; font-size:{usize}px; color:{T.TEXT2}"> {unit}</span>')

    def set_sub(self, text: str) -> None:
        self.sub.setText(text)


def fill_tiles(tiles: dict[str, MetricTile], hist: History, s) -> None:
    """Обновить 4 плитки (cpu/ram/disk/net) по снимку и истории."""
    big = tiles["cpu"]._big
    t = tiles["cpu"]
    t.set_value(f"{s.cpu:.0f}", "%")
    t.extra.setText(f"{s.temp:.0f} °C" if s.temp is not None else "")
    t.chart.set_series([(hist.cpu, T.CPU, False, True)], 100)
    la = " ".join(T.fmt_num(x, 2) for x in s.load)
    if big:
        fr = f"{T.fmt_num(s.freq_mhz / 1000)} ГГц · " if s.freq_mhz else ""
        t.set_sub(f"{fr}load {la}")
    else:
        t.set_sub(f"load {la}")

    t = tiles["ram"]
    t.set_value(f"{s.mem_percent:.0f}", "%")
    t.chart.set_series([(hist.ram, T.RAM, False, True)], 100)
    gib = 1024 ** 3
    if big:
        sw = f" · swap {T.fmt_bytes(s.swap_used)} / {T.fmt_bytes(s.swap_total)}" if s.swap_total else ""
        cache = f" · кэш {T.fmt_bytes(s.mem_cached)}" if s.mem_cached else ""
        t.set_sub(f"{T.fmt_bytes(s.mem_used)} / {T.fmt_bytes(s.mem_total)}{cache}{sw}")
    else:
        sw = f" · swap {T.fmt_num(s.swap_used / gib)}" if s.swap_total else ""
        t.set_sub(f"{T.fmt_num(s.mem_used / gib)} / {T.fmt_num(s.mem_total / gib, 0)} ГиБ{sw}")

    t = tiles["disk"]
    n, u = T.fmt_rate(s.disk_read + s.disk_write)
    t.set_value(n, u)
    t.extra.setText(s.disk_name if big else "")
    t.chart.set_series([(hist.disk_r, T.DISK, False, True), (hist.disk_w, T.DISK2, True, False)],
                       auto_max(hist.disk_r, hist.disk_w, floor=1024 ** 2))
    t.set_sub(f"R {T.fmt_rate_s(s.disk_read)} · W {T.fmt_rate_s(s.disk_write)}")

    t = tiles["net"]
    n, u = T.fmt_rate(s.net_down + s.net_up)
    t.set_value(n, u)
    t.extra.setText(s.net_name if big else "")
    t.chart.set_series([(hist.net_d, T.NET, False, True), (hist.net_u, T.NET2, True, False)],
                       auto_max(hist.net_d, hist.net_u, floor=256 * 1024))
    t.set_sub(f"↓ {T.fmt_rate_s(s.net_down)} · ↑ {T.fmt_rate_s(s.net_up)}")

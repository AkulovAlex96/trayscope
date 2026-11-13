"""Отрисовка значка в трее: столбики, мини-график или число."""
from __future__ import annotations

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QFont, QIcon, QPainter, QPainterPath, QPen, QPixmap

from . import theme as T

S = 64  # рисуем крупно, панель сама масштабирует


def _bars(p: QPainter, cpu: float, ram: float) -> None:
    p.setPen(QPen(QColor("#7a828a"), 3))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawRoundedRect(QRectF(3, 3, S - 6, S - 6), 12, 12)
    inner_top, inner_bot = 11.0, S - 11.0
    hmax = inner_bot - inner_top
    p.setPen(Qt.PenStyle.NoPen)
    for x, v, base in ((12, cpu, T.CPU), (35, ram, T.RAM)):
        h = max(4.0, v / 100 * hmax)
        p.setBrush(QColor(T.level_color(v, base, 75, 90)))
        p.drawRoundedRect(QRectF(x, inner_bot - h, 17, h), 4, 4)


def _graph(p: QPainter, hist: list[float]) -> None:
    vals = list(hist)[-20:] or [0.0]
    if len(vals) == 1:
        vals = vals * 2
    n = len(vals)
    step = (S - 4) / (n - 1)
    top, bot = 6.0, S - 4.0
    pts = [QPointF(2 + i * step, bot - min(v, 100) / 100 * (bot - top)) for i, v in enumerate(vals)]
    color = QColor(T.level_color(vals[-1], T.CPU, 75, 90))
    line = QPainterPath(pts[0])
    for pt in pts[1:]:
        line.lineTo(pt)
    area = QPainterPath(line)
    area.lineTo(pts[-1].x(), bot)
    area.lineTo(pts[0].x(), bot)
    area.closeSubpath()
    fill = QColor(color)
    fill.setAlphaF(0.35)
    p.fillPath(area, fill)
    pen = QPen(color, 4)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    p.strokePath(line, pen)


def _number(p: QPainter, cpu: float) -> None:
    color = QColor(T.level_color(cpu, T.TEXT, 75, 90))
    f = T.mono_font(36 if cpu < 99.5 else 28, QFont.Weight.Bold)
    p.setFont(f)
    p.setPen(color)
    p.drawText(QRectF(0, 0, S, S - 14), Qt.AlignmentFlag.AlignCenter, f"{cpu:.0f}")
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor("#4d5359"))
    p.drawRoundedRect(QRectF(6, S - 12, S - 12, 7), 3.5, 3.5)
    p.setBrush(QColor(T.level_color(cpu, T.CPU, 75, 90)))
    p.drawRoundedRect(QRectF(6, S - 12, max(7, (S - 12) * cpu / 100), 7), 3.5, 3.5)


def render(style: str, cpu: float, ram: float, cpu_hist) -> QIcon:
    pm = QPixmap(S, S)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    if style == "graph":
        _graph(p, cpu_hist)
    elif style == "number":
        _number(p, cpu)
    else:
        _bars(p, cpu, ram)
    p.end()
    return QIcon(pm)

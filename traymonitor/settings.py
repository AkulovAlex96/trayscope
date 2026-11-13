"""Настройки (QSettings) и автозапуск через ~/.config/autostart."""
from __future__ import annotations

import os
import shlex
import sys

from PyQt6.QtCore import QSettings

AUTOSTART = os.path.expanduser("~/.config/autostart/tray-monitor.desktop")
ENTRY = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "tray_monitor.py"))

ICON_STYLES = {"bars": "Столбики ЦП / ОЗУ", "graph": "Мини-график ЦП", "number": "Число ЦП %"}
INTERVALS = {500: "0,5 с", 1000: "1 с", 2000: "2 с", 5000: "5 с"}


class Settings:
    def __init__(self) -> None:
        self.q = QSettings("TrayMonitor", "TrayMonitor")

    @property
    def icon_style(self) -> str:
        v = self.q.value("icon_style", "bars")
        return v if v in ICON_STYLES else "bars"

    @icon_style.setter
    def icon_style(self, v: str) -> None:
        self.q.setValue("icon_style", v)

    @property
    def interval(self) -> int:
        try:
            v = int(self.q.value("interval_ms", 1000))
        except (TypeError, ValueError):
            v = 1000
        return v if v in INTERVALS else 1000

    @interval.setter
    def interval(self, v: int) -> None:
        self.q.setValue("interval_ms", v)

    @property
    def autostart(self) -> bool:
        return os.path.exists(AUTOSTART)

    @autostart.setter
    def autostart(self, on: bool) -> None:
        if on:
            os.makedirs(os.path.dirname(AUTOSTART), exist_ok=True)
            with open(AUTOSTART, "w", encoding="utf-8") as f:
                f.write(
                    "[Desktop Entry]\n"
                    "Type=Application\n"
                    "Name=Tray Monitor\n"
                    "Comment=Нагрузка системы и процессы в трее\n"
                    f"Exec={shlex.quote(sys.executable)} {shlex.quote(ENTRY)}\n"
                    "Icon=utilities-system-monitor\n"
                    "X-GNOME-Autostart-enabled=true\n"
                    "X-KDE-autostart-after=panel\n")
        elif os.path.exists(AUTOSTART):
            os.remove(AUTOSTART)

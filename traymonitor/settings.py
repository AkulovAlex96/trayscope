"""Настройки (QSettings) и автозапуск.

Linux — ~/.config/autostart/*.desktop, Windows — ключ реестра HKCU\\…\\Run.
"""
from __future__ import annotations

import os
import shlex
import sys

from PyQt6.QtCore import QSettings

from .osdep import WINDOWS

AUTOSTART = os.path.expanduser("~/.config/autostart/tray-monitor.desktop")
ENTRY = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "tray_monitor.py"))

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_NAME = "Trayscope"

ICON_STYLES = {"bars": "Столбики ЦП / ОЗУ", "graph": "Мини-график ЦП", "number": "Число ЦП %"}
INTERVALS = {500: "0,5 с", 1000: "1 с", 2000: "2 с", 5000: "5 с"}


def _gui_python() -> str:
    """pythonw.exe — чтобы при автозапуске в Windows не висело окно консоли."""
    exe = sys.executable
    if WINDOWS:
        w = os.path.join(os.path.dirname(exe), "pythonw.exe")
        if os.path.exists(w):
            return w
    return exe


def _win_command() -> str:
    return f'"{_gui_python()}" "{ENTRY}"'


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
        if WINDOWS:
            import winreg
            try:
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
                    winreg.QueryValueEx(k, RUN_NAME)
                return True
            except OSError:
                return False
        return os.path.exists(AUTOSTART)

    @autostart.setter
    def autostart(self, on: bool) -> None:
        if WINDOWS:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0,
                                winreg.KEY_SET_VALUE) as k:
                if on:
                    winreg.SetValueEx(k, RUN_NAME, 0, winreg.REG_SZ, _win_command())
                else:
                    try:
                        winreg.DeleteValue(k, RUN_NAME)
                    except FileNotFoundError:
                        pass
            return
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

#!/usr/bin/env python3
"""Запуск Tray Monitor.

  tray_monitor.py            — запустить (или показать панель, если уже запущен)
  tray_monitor.py --manager  — открыть диспетчер задач (удобно повесить на Ctrl+Shift+Esc)
  tray_monitor.py --popup    — показать панель
"""
import os
import sys

# В Wayland приложение не может само поставить окно рядом с треем,
# поэтому по умолчанию работаем через XWayland (TRAYMON_WAYLAND=1 — отключить).
if (os.environ.get("WAYLAND_DISPLAY") and "QT_QPA_PLATFORM" not in os.environ
        and os.environ.get("TRAYMON_WAYLAND") != "1"):
    os.environ["QT_QPA_PLATFORM"] = "xcb"

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from traymonitor.app import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main(sys.argv))

"""Запуск в Windows без окна консоли (pythonw.exe). Аргументы — как у tray_monitor.py."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from traymonitor.app import main  # noqa: E402

sys.exit(main(sys.argv))

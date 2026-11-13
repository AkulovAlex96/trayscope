"""Действия над процессами и общее контекстное меню."""
from __future__ import annotations

import datetime
import os
import subprocess

import psutil
from PyQt6.QtCore import QUrl
from PyQt6.QtGui import QDesktopServices, QGuiApplication
from PyQt6.QtWidgets import QMenu, QMessageBox, QWidget

from .osdep import WINDOWS

if WINDOWS:
    # Классы приоритета Windows (значения psutil), как в штатном диспетчере задач
    PRIORITIES = [
        ("Реального времени", psutil.REALTIME_PRIORITY_CLASS),
        ("Высокий", psutil.HIGH_PRIORITY_CLASS),
        ("Выше среднего", psutil.ABOVE_NORMAL_PRIORITY_CLASS),
        ("Обычный", psutil.NORMAL_PRIORITY_CLASS),
        ("Ниже среднего", psutil.BELOW_NORMAL_PRIORITY_CLASS),
        ("Низкий", psutil.IDLE_PRIORITY_CLASS),
    ]
    PRIORITY_MENU = "Приоритет"
    KILL_LABEL = "Снять задачу принудительно"
    SUSPEND_LABEL = "Приостановить"
else:
    PRIORITIES = [
        ("Высокий (−10, нужен root)", -10), ("Выше обычного (−5, нужен root)", -5),
        ("Обычный (0)", 0), ("Ниже обычного (5)", 5),
        ("Низкий (10)", 10), ("Очень низкий (19)", 19),
    ]
    PRIORITY_MENU = "Приоритет (nice)"
    KILL_LABEL = "Убить принудительно (SIGKILL)"
    SUSPEND_LABEL = "Приостановить (SIGSTOP)"


def priority_name(value) -> str:
    for label, v in PRIORITIES:
        if v == value:
            return label
    return str(value)


def _apply(pids, fn) -> list[str]:
    errors = []
    for pid in pids:
        try:
            fn(psutil.Process(pid))
        except psutil.NoSuchProcess:
            pass
        except psutil.AccessDenied:
            errors.append(f"{pid}: нет прав")
        except Exception as e:
            errors.append(f"{pid}: {e}")
    return errors


def terminate(pids):
    return _apply(pids, lambda p: p.terminate())


def kill(pids):
    return _apply(pids, lambda p: p.kill())


def suspend(pids):
    return _apply(pids, lambda p: p.suspend())


def resume(pids):
    return _apply(pids, lambda p: p.resume())


def renice(pids, value: int):
    return _apply(pids, lambda p: p.nice(value))


def is_stopped(pid: int) -> bool:
    try:
        return psutil.Process(pid).status() == psutil.STATUS_STOPPED
    except psutil.Error:
        return False


def open_location(pid: int) -> str | None:
    try:
        exe = psutil.Process(pid).exe()
    except psutil.Error as e:
        return f"Не удалось получить путь: {e}"
    if not exe:
        return "У процесса нет исполняемого файла"
    if WINDOWS:
        # Проводник с выделенным файлом
        try:
            subprocess.Popen(["explorer", f"/select,{os.path.normpath(exe)}"])
        except OSError:
            QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.dirname(exe)))
        return None
    # Dolphin умеет выделять файл через D-Bus FileManager1
    try:
        subprocess.Popen(
            ["dbus-send", "--session", "--dest=org.freedesktop.FileManager1",
             "--type=method_call", "/org/freedesktop/FileManager1",
             "org.freedesktop.FileManager1.ShowItems",
             f"array:string:file://{exe}", "string:"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError:
        QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.dirname(exe)))
    return None


def cmdline(pid: int) -> str:
    try:
        p = psutil.Process(pid)
        c = p.cmdline()
        return " ".join(c) if c else f"[{p.name()}]"
    except psutil.Error:
        return ""


def details_text(pid: int) -> str:
    try:
        p = psutil.Process(pid)
        with p.oneshot():
            rows = [
                ("PID", str(p.pid)),
                ("Родитель", f"{p.ppid()}"),
                ("Имя", p.name()),
                ("Пользователь", p.username()),
                ("Статус", p.status()),
                ("Запущен", datetime.datetime.fromtimestamp(p.create_time()).strftime("%d.%m.%Y %H:%M:%S")),
                ("Потоков", str(p.num_threads())),
                ("Приоритет" if WINDOWS else "Nice", priority_name(p.nice())),
                ("RSS", f"{p.memory_info().rss / 1024 ** 2:.1f} МиБ"),
                ("VMS", f"{p.memory_info().vms / 1024 ** 2:.1f} МиБ"),
            ]
            for label, fn in (("Файл", p.exe), ("Рабочая папка", p.cwd)):
                try:
                    rows.append((label, fn()))
                except psutil.Error:
                    rows.append((label, "нет доступа"))
        rows.append(("Команда", cmdline(pid)))
    except psutil.Error as e:
        return f"Процесс недоступен: {e}"
    return "\n".join(f"{k}: {v}" for k, v in rows)


def build_menu(parent: QWidget, pid: int, name: str, group_pids: list[int],
               notify, is_group: bool = False) -> QMenu:
    """Контекстное меню процесса.

    pid — выбранный процесс (для группы: главный), group_pids — все процессы
    с тем же именем, notify(title, text) — показ ошибок.
    """
    targets = group_pids if is_group else [pid]
    m = QMenu(parent)

    def run(fn, pids, what):
        errs = fn(pids)
        if errs:
            notify(f"{what}: {name}", "\n".join(errs[:6]))

    head = m.addAction(cmdline(pid)[:80] or name)
    head.setEnabled(False)
    m.addSeparator()
    a = m.addAction("Завершить" + (f" ({len(targets)})" if len(targets) > 1 else ""))
    a.setShortcut("Del")
    a.triggered.connect(lambda: run(terminate, targets, "Завершение"))
    a = m.addAction(KILL_LABEL)
    a.setShortcut("Shift+Del")
    a.triggered.connect(lambda: confirm_kill(parent, name, targets, notify))
    if not is_group and len(group_pids) > 1:
        a = m.addAction(f"Завершить всю группу «{name}» ({len(group_pids)})")
        a.triggered.connect(lambda: run(terminate, group_pids, "Завершение"))
    m.addSeparator()
    if is_stopped(pid):
        a = m.addAction("Возобновить")
        a.triggered.connect(lambda: run(resume, targets, "Возобновление"))
    else:
        a = m.addAction(SUSPEND_LABEL)
        a.triggered.connect(lambda: run(suspend, targets, "Приостановка"))
    pm = m.addMenu(PRIORITY_MENU)
    try:
        cur = psutil.Process(pid).nice()
    except psutil.Error:
        cur = None
    for label, val in PRIORITIES:
        a = pm.addAction(label)
        a.setCheckable(True)
        a.setChecked(cur == val)
        a.triggered.connect(lambda _=False, v=val: run(lambda ps: renice(ps, v), targets, "Приоритет"))
    m.addSeparator()
    a = m.addAction("Открыть расположение файла")
    a.triggered.connect(lambda: (lambda err: err and notify(name, err))(open_location(pid)))
    a = m.addAction("Копировать командную строку")
    a.triggered.connect(lambda: QGuiApplication.clipboard().setText(cmdline(pid)))
    a = m.addAction("Подробности…")
    a.triggered.connect(lambda: show_details(parent, pid, name))
    return m


def confirm_kill(parent, name: str, pids: list[int], notify) -> None:
    n = len(pids)
    r = QMessageBox.question(
        parent, "Убить процесс",
        f"Принудительно завершить «{name}»" + (f" ({n} процессов)" if n > 1 else "") +
        "?\nНесохранённые данные будут потеряны.")
    if r == QMessageBox.StandardButton.Yes:
        errs = kill(pids)
        if errs:
            notify(f"Принудительное завершение: {name}", "\n".join(errs[:6]))


def show_details(parent, pid: int, name: str) -> None:
    box = QMessageBox(parent)
    box.setWindowTitle(f"{name} — подробности")
    box.setText(details_text(pid))
    box.setTextInteractionFlags(box.textInteractionFlags())
    box.exec()

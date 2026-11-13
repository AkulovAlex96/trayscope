"""Различия между Linux и Windows в одном месте."""
from __future__ import annotations

import getpass
import sys

WINDOWS = sys.platform == "win32"

# «Системный» пользователь: root в Linux, SYSTEM в Windows
# В Windows без прав администратора владелец служб недоступен («?») —
# на домашнем ПК это почти всегда системные процессы, относим их туда же.
SYSTEM_USERS = (frozenset({"SYSTEM", "LOCAL SERVICE", "NETWORK SERVICE", "?"}) if WINDOWS
                else frozenset({"root"}))
SYSTEM_LABEL = "Система" if WINDOWS else "Root"


def current_user() -> str:
    return getpass.getuser()


def short_user(name: str | None) -> str:
    """Windows отдаёт «DOMAIN\\user» — оставляем только имя."""
    if not name:
        return "?"
    return name.rsplit("\\", 1)[-1]


def win_proc_table() -> dict[int, tuple[int, bool]] | None:
    """Windows: {pid: (число потоков, приостановлен)} одним вызовом на всю систему.

    psutil для num_threads/status на каждый процесс заново запрашивает таблицу
    всех процессов (O(n²)) — при 300+ процессах это секунды. Здесь — один вызов
    NtQuerySystemInformation(SystemProcessInformation). Только 64-битный Python;
    при любой ошибке возвращаем None, и сборщик берёт данные из psutil.
    """
    import ctypes
    import struct
    if ctypes.sizeof(ctypes.c_void_p) != 8:
        return None
    ntdll = ctypes.windll.ntdll
    size = 1 << 20
    for _ in range(6):
        buf = ctypes.create_string_buffer(size)
        need = ctypes.c_ulong(0)
        st = ntdll.NtQuerySystemInformation(5, buf, size, ctypes.byref(need)) & 0xFFFFFFFF
        if st == 0:
            break
        if st != 0xC0000004:            # не STATUS_INFO_LENGTH_MISMATCH
            return None
        size = max(size * 2, need.value + (64 << 10))
    else:
        return None
    raw = buf.raw
    out: dict[int, tuple[int, bool]] = {}
    off = 0
    # раскладка x64: SYSTEM_PROCESS_INFORMATION = 0x100 байт, за ним
    # NumberOfThreads × SYSTEM_THREAD_INFORMATION по 0x50 байт
    while True:
        nxt, nthreads = struct.unpack_from("<II", raw, off)
        pid = struct.unpack_from("<Q", raw, off + 0x50)[0]
        suspended = nthreads > 0
        t = off + 0x100
        for _ in range(nthreads):
            state, reason = struct.unpack_from("<II", raw, t + 0x44)
            if not (state == 5 and reason == 5):   # Waiting + Suspended
                suspended = False
                break
            t += 0x50
        out[pid] = (nthreads, suspended)
        if not nxt:
            break
        off += nxt
    return out


def instance_id() -> str:
    """Уникальная для пользователя часть имени сокета единственного экземпляра."""
    if WINDOWS:
        return current_user()
    import os
    return str(os.getuid())

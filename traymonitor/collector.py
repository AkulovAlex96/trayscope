"""Сбор метрик системы и процессов (psutil) в фоновом потоке."""
from __future__ import annotations

import os
import time
from dataclasses import dataclass, field

import psutil
from PyQt6.QtCore import QObject, QTimer, pyqtSignal, pyqtSlot

NCPU = psutil.cpu_count() or 1


@dataclass
class ProcInfo:
    pid: int
    name: str
    user: str
    cpu: float          # % от всей машины (0..100)
    mem: int            # RSS, байты
    threads: int
    disk: float         # байт/с (чтение+запись), 0 если нет доступа
    status: str


@dataclass
class Snapshot:
    ts: float
    cpu: float
    per_cpu: list[float]
    temp: float | None
    load: tuple[float, float, float]
    freq_mhz: float | None
    mem_used: int
    mem_total: int
    mem_percent: float
    mem_cached: int
    swap_used: int
    swap_total: int
    disk_read: float
    disk_write: float
    disk_name: str
    net_down: float
    net_up: float
    net_name: str
    uptime: float
    proc_count: int
    thread_count: int | None = None
    procs: list[ProcInfo] | None = None
    errors: list[str] = field(default_factory=list)


def _physical_disks() -> set[str]:
    try:
        return {d for d in os.listdir("/sys/block") if os.path.exists(f"/sys/block/{d}/device")}
    except OSError:
        return set()


def _physical_nics() -> set[str]:
    try:
        return {n for n in os.listdir("/sys/class/net") if os.path.exists(f"/sys/class/net/{n}/device")}
    except OSError:
        return set()


def _read_temp() -> float | None:
    try:
        temps = psutil.sensors_temperatures()
    except Exception:
        return None
    for chip in ("coretemp", "k10temp", "zenpower", "cpu_thermal", "acpitz"):
        entries = temps.get(chip)
        if not entries:
            continue
        for e in entries:
            if e.label in ("Package id 0", "Tctl", "Tdie"):
                return e.current
        return entries[0].current
    return None


class Collector:
    def __init__(self) -> None:
        self.disks = _physical_disks()
        self.nics = _physical_nics()
        psutil.cpu_percent(percpu=True)
        self._prev_t = time.monotonic()
        self._prev_disk = self._disk_counters()
        self._prev_net = self._net_counters()
        self._prev_proc_io: dict[int, tuple[int, float]] = {}
        self._proc_primed = False

    def _disk_counters(self) -> dict[str, tuple[int, int]]:
        try:
            c = psutil.disk_io_counters(perdisk=True) or {}
        except Exception:
            return {}
        return {k: (v.read_bytes, v.write_bytes) for k, v in c.items() if k in self.disks}

    def _net_counters(self) -> dict[str, tuple[int, int]]:
        try:
            c = psutil.net_io_counters(pernic=True) or {}
        except Exception:
            return {}
        return {k: (v.bytes_recv, v.bytes_sent) for k, v in c.items() if k in self.nics}

    @staticmethod
    def _rates(prev, cur, dt):
        """Суммарные скорости и самый активный интерфейс/диск."""
        a_total = b_total = 0.0
        best, best_v = "", -1.0
        for k, (a, b) in cur.items():
            pa, pb = prev.get(k, (a, b))
            da, db = max(0, a - pa) / dt, max(0, b - pb) / dt
            a_total += da
            b_total += db
            if da + db > best_v:
                best, best_v = k, da + db
        return a_total, b_total, best

    def sample(self, want_procs: bool) -> Snapshot:
        now = time.monotonic()
        dt = max(now - self._prev_t, 1e-3)
        self._prev_t = now

        per_cpu = psutil.cpu_percent(percpu=True)
        cpu = sum(per_cpu) / len(per_cpu) if per_cpu else 0.0
        vm = psutil.virtual_memory()
        sw = psutil.swap_memory()
        try:
            freq = psutil.cpu_freq()
            freq_mhz = freq.current if freq else None
        except Exception:
            freq_mhz = None

        disk = self._disk_counters()
        dr, dw, dname = self._rates(self._prev_disk, disk, dt)
        self._prev_disk = disk
        net = self._net_counters()
        nd, nu, nname = self._rates(self._prev_net, net, dt)
        self._prev_net = net

        snap = Snapshot(
            ts=time.time(), cpu=cpu, per_cpu=per_cpu, temp=_read_temp(),
            load=os.getloadavg(), freq_mhz=freq_mhz,
            mem_used=vm.total - vm.available, mem_total=vm.total,
            mem_percent=vm.percent,
            mem_cached=getattr(vm, "cached", 0) + getattr(vm, "buffers", 0),
            swap_used=sw.used, swap_total=sw.total,
            disk_read=dr, disk_write=dw, disk_name=dname,
            net_down=nd, net_up=nu, net_name=nname,
            uptime=time.time() - psutil.boot_time(),
            proc_count=len(psutil.pids()),
        )
        if want_procs:
            snap.procs, snap.thread_count = self._sample_procs(dt)
        else:
            self._proc_primed = False
        return snap

    def _sample_procs(self, dt: float):
        procs: list[ProcInfo] = []
        threads = 0
        io_now: dict[int, tuple[int, float]] = {}
        attrs = ["pid", "ppid", "name", "username", "num_threads",
                 "memory_info", "cpu_percent", "io_counters", "status"]
        for p in psutil.process_iter(attrs, ad_value=None):
            i = p.info
            pid = i["pid"]
            nth = i["num_threads"] or 0
            threads += nth
            # потоки ядра (kthreadd и его дети) не показываем
            if pid == 2 or i["ppid"] == 2:
                continue
            mi = i["memory_info"]
            io = i["io_counters"]
            disk = 0.0
            if io is not None:
                total = io.read_bytes + io.write_bytes
                io_now[pid] = (total, 0.0)
                prev = self._prev_proc_io.get(pid)
                if prev is not None:
                    disk = max(0, total - prev[0]) / dt
            procs.append(ProcInfo(
                pid=pid,
                name=i["name"] or "?",
                user=i["username"] or "?",
                cpu=(i["cpu_percent"] or 0.0) / NCPU if self._proc_primed else 0.0,
                mem=mi.rss if mi else 0,
                threads=nth,
                disk=disk,
                status=i["status"] or "",
            ))
        self._prev_proc_io = io_now
        self._proc_primed = True
        return procs, threads


class Worker(QObject):
    """Живёт в отдельном QThread, раз в interval_ms шлёт Snapshot."""
    snapshot = pyqtSignal(object)

    def __init__(self, interval_ms: int) -> None:
        super().__init__()
        self.interval_ms = interval_ms
        self.want_procs = False
        self._collector: Collector | None = None
        self._timer: QTimer | None = None

    @pyqtSlot()
    def start(self) -> None:
        self._collector = Collector()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.tick)
        self._timer.start(self.interval_ms)
        QTimer.singleShot(250, self.tick)

    @pyqtSlot()
    def tick(self) -> None:
        if self._collector is None:
            return
        try:
            snap = self._collector.sample(self.want_procs)
        except Exception as e:  # не роняем поток из-за одного сбоя
            print("collector error:", e)
            return
        self.snapshot.emit(snap)

    @pyqtSlot()
    def refresh_now(self) -> None:
        """Внеочередной замер (например, при открытии списка процессов).

        Если процессы ещё не замерялись, первый проход только «заводит»
        счётчики CPU, поэтому через 400 мс делаем второй.
        """
        primed = self._collector is not None and self._collector._proc_primed
        self.tick()
        if self.want_procs and not primed:
            QTimer.singleShot(400, self.tick)

    @pyqtSlot(int)
    def set_interval(self, ms: int) -> None:
        self.interval_ms = ms
        if self._timer:
            self._timer.setInterval(ms)

    @pyqtSlot()
    def stop(self) -> None:
        if self._timer:
            self._timer.stop()


@dataclass
class Group:
    name: str
    pids: list[int]
    cpu: float
    mem: int
    disk: float
    threads: int
    users: set[str]
    procs: list[ProcInfo]

    @property
    def count(self) -> int:
        return len(self.pids)

    @property
    def main_pid(self) -> int:
        # «главный» процесс группы — самый старший (наименьший PID)
        return min(self.pids)


def group_procs(procs: list[ProcInfo]) -> list[Group]:
    groups: dict[str, Group] = {}
    for p in procs:
        g = groups.get(p.name)
        if g is None:
            groups[p.name] = Group(p.name, [p.pid], p.cpu, p.mem, p.disk, p.threads, {p.user}, [p])
        else:
            g.pids.append(p.pid)
            g.cpu += p.cpu
            g.mem += p.mem
            g.disk += p.disk
            g.threads += p.threads
            g.users.add(p.user)
            g.procs.append(p)
    return list(groups.values())

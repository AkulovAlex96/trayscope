"""Полноценное окно диспетчера задач: процессы (дерево) и производительность."""
from __future__ import annotations

import getpass

from PyQt6.QtCore import QSize, Qt, pyqtSignal
from PyQt6.QtGui import QBrush, QColor, QFont, QKeySequence, QShortcut
from PyQt6.QtWidgets import (QAbstractItemView, QButtonGroup, QFrame, QGridLayout,
                             QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMainWindow,
                             QPushButton, QStackedWidget, QTabBar, QTreeWidget,
                             QTreeWidgetItem, QVBoxLayout, QWidget)

from . import osdep as OS
from . import procactions as PA
from . import theme as T
from .collector import ProcInfo, group_procs
from .widgets import CoreBars, History, MetricTile, fill_tiles

C_NAME, C_PID, C_USER, C_CPU, C_MEM, C_DISK, C_THR = range(7)
KEY = Qt.ItemDataRole.UserRole          # сортировочный ключ колонки
META = Qt.ItemDataRole.UserRole + 1     # (key, pids, name, main_pid, is_group)

ME = getpass.getuser()
SYS_USERS, SYS_LABEL = OS.SYSTEM_USERS, OS.SYSTEM_LABEL


class Item(QTreeWidgetItem):
    def __lt__(self, other: QTreeWidgetItem) -> bool:
        col = self.treeWidget().sortColumn() if self.treeWidget() else 0
        a, b = self.data(col, KEY), other.data(col, KEY)
        if a is None or b is None:
            return (self.text(col).lower()) < (other.text(col).lower())
        return a < b


class TaskManager(QMainWindow):
    visibility_changed = pyqtSignal(bool)
    refresh_requested = pyqtSignal()

    def __init__(self, notify) -> None:
        super().__init__()
        self.notify = notify
        self.setWindowTitle("Диспетчер задач")
        self.resize(1120, 720)
        self.setMinimumSize(720, 420)
        self._snap = None
        self._hist: History | None = None
        self.expanded: set[str] = set()
        self.user_filter = "all"
        self.tree_mode = True

        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # --- верхняя полоса: вкладки + поиск
        top = QFrame()
        top.setStyleSheet(f"QFrame#topbar {{ border-bottom: 1px solid {T.DIVIDER}; }}")
        top.setObjectName("topbar")
        tl = QHBoxLayout(top)
        tl.setContentsMargins(14, 4, 16, 0)
        tl.setSpacing(16)
        self.tabs = QTabBar()
        self.tabs.addTab("Процессы")
        self.tabs.addTab("Производительность")
        self.tabs.setDrawBase(False)
        self.tabs.setExpanding(False)
        self.tabs.setUsesScrollButtons(False)
        tl.addWidget(self.tabs, 0, Qt.AlignmentFlag.AlignBottom)
        tl.addStretch(1)
        self.search = QLineEdit()
        self.search.setObjectName("search")
        self.search.setPlaceholderText("Имя, PID или пользователь  ( / )")
        self.search.setFixedSize(320, 32)
        self.search.setFont(T.ui_font(13))
        self.search.setClearButtonEnabled(True)
        self.search.addAction(T.icon_search(T.TEXT2), QLineEdit.ActionPosition.LeadingPosition)
        self.search.textChanged.connect(lambda _: self.rebuild())
        tl.addWidget(self.search, 0, Qt.AlignmentFlag.AlignVCenter)
        root.addWidget(top)

        self.stack = QStackedWidget()
        self.stack.addWidget(self._build_procs())
        self.stack.addWidget(self._build_perf())
        root.addWidget(self.stack, 1)
        self.tabs.currentChanged.connect(self._tab_changed)

        # --- статус-бар
        sb = QFrame()
        sb.setObjectName("statusbar")
        sb.setStyleSheet(f"QFrame#statusbar {{ border-top: 1px solid {T.DIVIDER}; }}")
        sl = QHBoxLayout(sb)
        sl.setContentsMargins(20, 8, 20, 8)
        self.status = QLabel("")
        self.status.setObjectName("status")
        sl.addWidget(self.status)
        root.addWidget(sb)

        QShortcut(QKeySequence("/"), self, activated=self._focus_search)
        QShortcut(QKeySequence("Ctrl+F"), self, activated=self._focus_search)
        QShortcut(QKeySequence("Escape"), self.search, activated=self.search.clear)

    # ---------------------------------------------------------------- процессы
    def _build_procs(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(12, 10, 12, 0)
        lay.setSpacing(8)

        bar = QHBoxLayout()
        bar.setContentsMargins(8, 0, 8, 0)
        bar.setSpacing(6)
        self.chips = {}
        grp = QButtonGroup(self)
        for key, text in (("all", "Все"), ("me", "Мои"), ("root", SYS_LABEL)):
            b = QPushButton(text)
            b.setObjectName("chip")
            b.setCheckable(True)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(lambda _=False, k=key: self._set_filter(k))
            grp.addButton(b)
            bar.addWidget(b)
            self.chips[key] = b
        self.chips["all"].setChecked(True)

        sep = QFrame()
        sep.setFixedSize(1, 20)
        sep.setStyleSheet(f"background: {T.BORDER};")
        bar.addSpacing(4)
        bar.addWidget(sep)
        bar.addSpacing(4)
        self.btn_tree = QPushButton("Дерево")
        self.btn_tree.setObjectName("ghost")
        self.btn_tree.setCheckable(True)
        self.btn_tree.setChecked(True)
        self.btn_tree.setIcon(T.icon_tree(T.TEXT))
        self.btn_tree.setIconSize(QSize(14, 14))
        self.btn_tree.toggled.connect(self._set_tree)
        bar.addWidget(self.btn_tree)
        bar.addStretch(1)

        self.btn_suspend = QPushButton("Приостановить")
        self.btn_suspend.setObjectName("ghost")
        self.btn_suspend.clicked.connect(self._suspend_selected)
        bar.addWidget(self.btn_suspend)
        self.btn_end = QPushButton("Снять задачу")
        self.btn_end.setObjectName("danger")
        self.btn_end.clicked.connect(self._terminate_selected)
        bar.addWidget(self.btn_end)
        lay.addLayout(bar)

        self.tree = QTreeWidget()
        self.tree.setObjectName("procTree")
        self.tree.setColumnCount(7)
        self.tree.setUniformRowHeights(True)
        self.tree.setRootIsDecorated(True)
        self.tree.setIndentation(18)
        self.tree.setAnimated(False)
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.tree.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tree.setIconSize(QSize(18, 18))
        self.tree.setSortingEnabled(True)
        self.tree.sortByColumn(C_CPU, Qt.SortOrder.DescendingOrder)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._ctx_menu)
        self.tree.itemExpanded.connect(lambda it: self.expanded.add(it.data(0, META)[0]))
        self.tree.itemCollapsed.connect(lambda it: self.expanded.discard(it.data(0, META)[0]))
        self.tree.itemSelectionChanged.connect(self._update_buttons)
        hh = self.tree.header()
        hh.setStretchLastSection(False)
        hh.setFixedHeight(44)
        hh.setDefaultAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        hh.setSectionResizeMode(C_NAME, QHeaderView.ResizeMode.Stretch)
        hh.setSortIndicatorShown(False)
        hh.sortIndicatorChanged.connect(lambda *_: self._set_headers(self._snap))
        for c, w in ((C_PID, 80), (C_USER, 110), (C_CPU, 96), (C_MEM, 110), (C_DISK, 110), (C_THR, 80)):
            hh.setSectionResizeMode(c, QHeaderView.ResizeMode.Interactive)
            self.tree.setColumnWidth(c, w)
        lay.addWidget(self.tree, 1)

        QShortcut(QKeySequence("Delete"), self.tree, activated=self._terminate_selected)
        QShortcut(QKeySequence("Shift+Delete"), self.tree, activated=self._kill_selected)
        self._set_headers(None)
        self._update_buttons()
        return page

    def _set_headers(self, s) -> None:
        names = ["Имя", "PID", "Владелец", "ЦП", "Память", "Диск", "Потоки"]
        hh = self.tree.header()
        col = hh.sortIndicatorSection()
        arrow = " ▾" if hh.sortIndicatorOrder() == Qt.SortOrder.DescendingOrder else " ▴"
        names = [n + (arrow if i == col else "") for i, n in enumerate(names)]
        if s is not None:
            names[C_CPU] = f"{s.cpu:.0f} %\n{names[C_CPU]}"
            names[C_MEM] = f"{s.mem_percent:.0f} %\n{names[C_MEM]}"
            names[C_DISK] = f"{T.fmt_rate_s(s.disk_read + s.disk_write)}\n{names[C_DISK]}"
        self.tree.setHeaderLabels(names)
        hi = self.tree.headerItem()
        for c in (C_NAME, C_USER):
            hi.setTextAlignment(c, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

    def _set_filter(self, key: str) -> None:
        self.user_filter = key
        self.rebuild()

    def _set_tree(self, on: bool) -> None:
        self.tree_mode = on
        self.rebuild()

    def _focus_search(self) -> None:
        self.tabs.setCurrentIndex(0)
        self.search.setFocus()
        self.search.selectAll()

    def _filtered(self, procs: list[ProcInfo]) -> list[ProcInfo]:
        if self.user_filter == "me":
            procs = [p for p in procs if p.user == ME]
        elif self.user_filter == "root":
            procs = [p for p in procs if p.user in SYS_USERS]
        q = self.search.text().strip().lower()
        if q:
            procs = [p for p in procs if q in p.name.lower() or str(p.pid).startswith(q)
                     or q == p.user.lower()]
        return procs

    def _make_item(self, name, pid_text, user, cpu, mem, disk, threads, meta) -> Item:
        it = Item()
        it.setText(C_NAME, name)
        it.setIcon(C_NAME, T.proc_icon(meta[2]))
        it.setText(C_PID, pid_text)
        it.setText(C_USER, user)
        it.setText(C_CPU, f"{T.fmt_num(cpu)} %")
        it.setText(C_MEM, T.fmt_bytes(mem))
        it.setText(C_DISK, T.fmt_rate_s(disk) if disk >= 1024 else "0")
        it.setText(C_THR, str(threads))
        it.setData(C_NAME, KEY, name.lower())
        it.setData(C_PID, KEY, meta[3])
        it.setData(C_USER, KEY, user)
        it.setData(C_CPU, KEY, cpu)
        it.setData(C_MEM, KEY, mem)
        it.setData(C_DISK, KEY, disk)
        it.setData(C_THR, KEY, threads)
        it.setData(0, META, meta)
        mono = T.mono_font(12)
        for c in (C_PID, C_CPU, C_MEM, C_DISK, C_THR):
            it.setFont(c, mono)
            it.setTextAlignment(c, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        for c in (C_PID, C_USER, C_THR):
            it.setForeground(c, QBrush(QColor(T.TEXT2)))
        for c, v, vmax in ((C_CPU, cpu, 15), (C_MEM, mem, 2.4 * 1024 ** 3), (C_DISK, disk, 5 * 1024 ** 2)):
            h = T.heat_color(v if c != C_DISK or v >= 1024 else 0, vmax)
            if h is not None:
                it.setBackground(c, QBrush(h))
        return it

    def _proc_item(self, p: ProcInfo, group_pids) -> Item:
        name = p.name + (" (приостановлен)" if p.status == "stopped" else "")
        return self._make_item(name, str(p.pid), p.user, p.cpu, p.mem, p.disk, p.threads,
                               (f"p:{p.pid}", group_pids, p.name, p.pid, False))

    def rebuild(self) -> None:
        s = self._snap
        if s is None or s.procs is None:
            return
        procs = self._filtered(s.procs)
        counts = {"all": len(s.procs),
                  "me": sum(1 for p in s.procs if p.user == ME),
                  "root": sum(1 for p in s.procs if p.user in SYS_USERS)}
        for k, b in self.chips.items():
            b.setText({"all": "Все", "me": "Мои", "root": SYS_LABEL}[k] + f"  {counts[k]}")

        tree = self.tree
        cur = tree.currentItem()
        sel_key = cur.data(0, META)[0] if cur else None
        scroll = tree.verticalScrollBar().value()

        items: list[Item] = []
        groups = group_procs(procs)
        all_groups = {g.name: g.pids for g in group_procs(s.procs)}
        if self.tree_mode:
            for g in groups:
                gp = all_groups.get(g.name, g.pids)
                if g.count == 1:
                    items.append(self._proc_item(g.procs[0], gp))
                    continue
                users = ", ".join(sorted(g.users))
                parent = self._make_item(f"{g.name}  ({g.count})", "", users, g.cpu, g.mem, g.disk,
                                         g.threads, (f"g:{g.name}", g.pids, g.name, g.main_pid, True))
                parent.setData(C_PID, KEY, g.main_pid)
                for p in g.procs:
                    parent.addChild(self._proc_item(p, gp))
                items.append(parent)
        else:
            for p in procs:
                items.append(self._proc_item(p, all_groups.get(p.name, [p.pid])))

        tree.setUpdatesEnabled(False)
        tree.blockSignals(True)
        col, order = tree.sortColumn(), tree.header().sortIndicatorOrder()
        tree.setSortingEnabled(False)
        tree.clear()
        tree.addTopLevelItems(items)
        for it in items:
            if it.childCount() and it.data(0, META)[0] in self.expanded:
                it.setExpanded(True)
        tree.setSortingEnabled(True)
        tree.sortByColumn(col, order)
        tree.header().setSortIndicatorShown(False)  # своя стрелка в тексте заголовка
        new_cur = None
        if sel_key:
            for it in self._iter_items():
                if it.data(0, META)[0] == sel_key:
                    new_cur = it
                    break
        if new_cur is not None:
            tree.setCurrentItem(new_cur)
        tree.blockSignals(False)
        tree.verticalScrollBar().setValue(scroll)
        tree.setUpdatesEnabled(True)
        self._update_buttons()

    def _iter_items(self):
        t = self.tree
        for i in range(t.topLevelItemCount()):
            top = t.topLevelItem(i)
            yield top
            for j in range(top.childCount()):
                yield top.child(j)

    def _selected_meta(self):
        it = self.tree.currentItem()
        if it is None or not it.isSelected():
            return None
        return it.data(0, META)

    def _targets(self, meta) -> list[int]:
        key, group_pids, _name, pid, is_group = meta
        return group_pids if is_group else [pid]

    def _update_buttons(self) -> None:
        meta = self._selected_meta()
        self.btn_end.setEnabled(meta is not None)
        self.btn_suspend.setEnabled(meta is not None)
        if meta is not None:
            stopped = PA.is_stopped(meta[3])
            self.btn_suspend.setText("Возобновить" if stopped else "Приостановить")

    def _terminate_selected(self) -> None:
        meta = self._selected_meta()
        if meta is None:
            return
        errs = PA.terminate(self._targets(meta))
        if errs:
            self.notify(f"Не удалось завершить «{meta[2]}»", "\n".join(errs[:6]))
        self.refresh_requested.emit()

    def _kill_selected(self) -> None:
        meta = self._selected_meta()
        if meta is None:
            return
        PA.confirm_kill(self, meta[2], self._targets(meta), self.notify)
        self.refresh_requested.emit()

    def _suspend_selected(self) -> None:
        meta = self._selected_meta()
        if meta is None:
            return
        fn = PA.resume if PA.is_stopped(meta[3]) else PA.suspend
        errs = fn(self._targets(meta))
        if errs:
            self.notify(meta[2], "\n".join(errs[:6]))
        self.refresh_requested.emit()

    def _ctx_menu(self, pos) -> None:
        it = self.tree.itemAt(pos)
        if it is None:
            return
        self.tree.setCurrentItem(it)
        key, group_pids, name, pid, is_group = it.data(0, META)
        m = PA.build_menu(self, pid, name, group_pids, self.notify, is_group=is_group)
        m.exec(self.tree.viewport().mapToGlobal(pos))
        self.refresh_requested.emit()

    # ---------------------------------------------------------------- производительность
    def _build_perf(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(20, 16, 20, 16)
        lay.setSpacing(12)
        grid = QGridLayout()
        grid.setSpacing(12)
        self.big = {
            "cpu": MetricTile("Процессор", T.CPU, big=True),
            "ram": MetricTile("Память", T.RAM, big=True),
            "disk": MetricTile("Диск", T.DISK, big=True),
            "net": MetricTile("Сеть", T.NET, big=True),
        }
        for i, k in enumerate(("cpu", "ram", "disk", "net")):
            grid.addWidget(self.big[k], i // 2, i % 2)
        lay.addLayout(grid, 1)

        cores = QFrame()
        cores.setObjectName("bigTile")
        cl = QVBoxLayout(cores)
        cl.setContentsMargins(14, 10, 14, 12)
        cl.setSpacing(8)
        lbl = QLabel("Загрузка по ядрам")
        lbl.setFont(T.ui_font(13, QFont.Weight.DemiBold))
        cl.addWidget(lbl)
        self.big_cores = CoreBars()
        self.big_cores.setFixedHeight(56)
        cl.addWidget(self.big_cores)
        lay.addWidget(cores)
        return page

    def _tab_changed(self, i: int) -> None:
        self.stack.setCurrentIndex(i)
        self.search.setVisible(i == 0)
        if i == 1 and self._snap is not None and self._hist is not None:
            fill_tiles(self.big, self._hist, self._snap)
            self.big_cores.set_values(self._snap.per_cpu)

    # ---------------------------------------------------------------- данные
    def update_data(self, s, hist: History) -> None:
        self._snap = s
        self._hist = hist
        if not self.isVisible():
            return
        thr = f"Потоков {s.thread_count:,}".replace(",", " ") + "   " if s.thread_count else ""
        sw = f"   Swap {T.fmt_bytes(s.swap_used)} / {T.fmt_bytes(s.swap_total)}" if s.swap_total else ""
        self.status.setText(
            f"Процессов {len(s.procs) if s.procs is not None else s.proc_count}   {thr}ЦП {s.cpu:.0f} %   "
            f"Память {T.fmt_bytes(s.mem_used)} / {T.fmt_bytes(s.mem_total)}{sw}   "
            f"Аптайм {T.fmt_uptime(s.uptime)}")
        if self.stack.currentIndex() == 0:
            self._set_headers(s)
            self.rebuild()
        else:
            fill_tiles(self.big, hist, s)
            self.big_cores.set_values(s.per_cpu)

    def showEvent(self, e) -> None:
        super().showEvent(e)
        self.visibility_changed.emit(True)
        self.refresh_requested.emit()

    def hideEvent(self, e) -> None:
        super().hideEvent(e)
        self.visibility_changed.emit(False)

"""Компактное окно из трея: вкладки «Графики» и «Процессы»."""
from __future__ import annotations

from PyQt6.QtCore import (QAbstractTableModel, QEvent, QModelIndex, QRect, QRectF,
                          QSize, Qt, pyqtSignal)
from PyQt6.QtGui import QColor, QFont, QKeyEvent, QPainter, QPen
from PyQt6.QtWidgets import (QAbstractItemView, QButtonGroup, QFrame, QGridLayout,
                             QHBoxLayout, QHeaderView, QLabel, QLineEdit, QPushButton,
                             QStackedWidget, QStyledItemDelegate, QTableView,
                             QToolButton, QVBoxLayout, QWidget)

from . import procactions as PA
from . import theme as T
from .collector import Group, group_procs
from .widgets import CoreBars, History, MetricTile, fill_tiles

W, H = 380, 300
ROW_H = 24
COL_CPU, COL_MEM, COL_KILL = 1, 2, 3


class ProcModel(QAbstractTableModel):
    def __init__(self) -> None:
        super().__init__()
        self.rows: list[Group] = []
        self.sort = "cpu"

    def rowCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent=QModelIndex()) -> int:
        return 4

    def data(self, idx: QModelIndex, role=Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.UserRole:
            return self.rows[idx.row()]
        return None

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation != Qt.Orientation.Horizontal:
            return None
        if role == Qt.ItemDataRole.DisplayRole:
            return ["Имя",
                    "ЦП ▾" if self.sort == "cpu" else "ЦП",
                    "Память ▾" if self.sort == "mem" else "Память",
                    ""][section]
        if role == Qt.ItemDataRole.ForegroundRole:
            active = (section == COL_CPU and self.sort == "cpu") or (section == COL_MEM and self.sort == "mem")
            return QColor(T.ACCENT if active else T.TEXT2)
        if role == Qt.ItemDataRole.TextAlignmentRole:
            if section in (COL_CPU, COL_MEM):
                return Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            return Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        if role == Qt.ItemDataRole.FontRole:
            return T.ui_font(11, QFont.Weight.DemiBold)
        return None

    def set_rows(self, rows: list[Group]) -> None:
        self.beginResetModel()
        self.rows = rows
        self.endResetModel()

    def set_sort(self, key: str) -> None:
        self.sort = key
        self.headerDataChanged.emit(Qt.Orientation.Horizontal, 0, 3)


class ProcDelegate(QStyledItemDelegate):
    def __init__(self, view: "ProcView") -> None:
        super().__init__(view)
        self.view = view
        self.f_name = T.ui_font(12)
        self.f_mono = T.mono_font(11)
        self.f_count = T.mono_font(10)

    def sizeHint(self, option, index) -> QSize:
        return QSize(40, ROW_H)

    def paint(self, p: QPainter, opt, idx: QModelIndex) -> None:
        g: Group = idx.data(Qt.ItemDataRole.UserRole)
        r = opt.rect
        col = idx.column()
        hovered = idx.row() == self.view.hover_row
        p.save()
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        if hovered:
            p.fillRect(r, QColor(T.SURFACE))

        if col == 0:
            ic = T.proc_icon(g.name)
            ic.paint(p, QRect(r.x() + 8, r.y() + (r.height() - 16) // 2, 16, 16))
            p.setFont(self.f_name)
            p.setPen(QColor(T.TEXT))
            text_r = r.adjusted(32, 0, -4, 0)
            fm = p.fontMetrics()
            count = f"×{g.count}" if g.count > 1 else ""
            cw = 0
            if count:
                p.setFont(self.f_count)
                cw = p.fontMetrics().horizontalAdvance(count) + 6
                p.setFont(self.f_name)
            name = fm.elidedText(g.name, Qt.TextElideMode.ElideRight, text_r.width() - cw)
            p.drawText(text_r, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, name)
            if count:
                nx = text_r.x() + fm.horizontalAdvance(name) + 5
                p.setFont(self.f_count)
                p.setPen(QColor(T.TEXT2))
                p.drawText(QRect(nx, r.y(), cw, r.height()),
                           Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, count)
        elif col in (COL_CPU, COL_MEM):
            if col == COL_CPU:
                heat = T.heat_color(g.cpu, 14)
                text = f"{T.fmt_num(g.cpu)}%"
            else:
                heat = T.heat_color(g.mem, 2.4 * 1024 ** 3)
                text = T.fmt_bytes(g.mem)
            cell = QRectF(r).adjusted(2, 3, -2, -3)
            if heat:
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(heat)
                p.drawRoundedRect(cell, 3, 3)
            p.setFont(self.f_mono)
            p.setPen(QColor(T.TEXT))
            p.drawText(cell.adjusted(0, 0, -4, 0),
                       Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, text)
        elif col == COL_KILL and hovered:
            b = QRectF(r.right() - 22, r.center().y() - 10 + 0.5, 20, 20)
            p.setPen(Qt.PenStyle.NoPen)
            hot = self.view.hover_col == COL_KILL
            p.setBrush(QColor("#6a2e36" if hot else T.DANGER_BG))
            p.drawRoundedRect(b, 4, 4)
            pen = QPen(QColor(T.DANGER_FG), 1.8)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.setPen(pen)
            c = b.center()
            d = 3.6
            p.drawLine(c.x() - d, c.y() - d, c.x() + d, c.y() + d)
            p.drawLine(c.x() - d, c.y() + d, c.x() + d, c.y() - d)
        p.restore()


class ProcView(QTableView):
    kill_requested = pyqtSignal(object)      # Group
    menu_requested = pyqtSignal(object, object)  # Group, QPoint (global)

    def __init__(self, model: ProcModel) -> None:
        super().__init__()
        self.hover_row = -1
        self.hover_col = -1
        self.setModel(model)
        self.setItemDelegate(ProcDelegate(self))
        self.setMouseTracking(True)
        self.setShowGrid(False)
        self.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        vh = self.verticalHeader()
        vh.hide()
        vh.setDefaultSectionSize(ROW_H)
        vh.setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        hh = self.horizontalHeader()
        hh.setFixedHeight(22)
        hh.setHighlightSections(False)
        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for c, w in ((COL_CPU, 56), (COL_MEM, 72), (COL_KILL, 28)):
            hh.setSectionResizeMode(c, QHeaderView.ResizeMode.Fixed)
            self.setColumnWidth(c, w)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._ctx)

    @property
    def hovering(self) -> bool:
        return self.hover_row >= 0

    def mouseMoveEvent(self, e) -> None:
        idx = self.indexAt(e.position().toPoint())
        row, col = (idx.row(), idx.column()) if idx.isValid() else (-1, -1)
        if (row, col) != (self.hover_row, self.hover_col):
            self.hover_row, self.hover_col = row, col
            self.viewport().update()
        super().mouseMoveEvent(e)

    def leaveEvent(self, e) -> None:
        self.hover_row = self.hover_col = -1
        self.viewport().update()
        super().leaveEvent(e)

    def mouseReleaseEvent(self, e) -> None:
        idx = self.indexAt(e.position().toPoint())
        if e.button() == Qt.MouseButton.LeftButton and idx.isValid() and idx.column() == COL_KILL:
            self.kill_requested.emit(idx.data(Qt.ItemDataRole.UserRole))
        super().mouseReleaseEvent(e)

    def _ctx(self, pos) -> None:
        idx = self.indexAt(pos)
        if idx.isValid():
            self.menu_requested.emit(idx.data(Qt.ItemDataRole.UserRole),
                                     self.viewport().mapToGlobal(pos))


class Popup(QWidget):
    open_manager = pyqtSignal()
    visibility_changed = pyqtSignal(bool)
    tab_changed = pyqtSignal(str)
    refresh_requested = pyqtSignal()
    hidden_by_focus_loss = pyqtSignal()

    def __init__(self, notify) -> None:
        super().__init__(None, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.WindowStaysOnTopHint)
        self.notify = notify
        self.setObjectName("popupRoot")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedSize(W, H)
        self.setWindowTitle("Tray Monitor")
        self._last_snapshot = None
        self._order: list[str] = []

        root = QVBoxLayout(self)
        root.setContentsMargins(1, 1, 1, 1)
        root.setSpacing(0)

        # --- шапка
        head = QHBoxLayout()
        head.setContentsMargins(8, 8, 8, 6)
        head.setSpacing(4)
        seg = QFrame()
        seg.setObjectName("seg")
        sl = QHBoxLayout(seg)
        sl.setContentsMargins(2, 2, 2, 2)
        sl.setSpacing(0)
        self.btn_graphs = self._seg_btn("Графики", T.icon_pulse)
        self.btn_procs = self._seg_btn("Процессы", T.icon_list)
        sl.addWidget(self.btn_graphs)
        sl.addWidget(self.btn_procs)
        grp = QButtonGroup(self)
        grp.setExclusive(True)
        grp.addButton(self.btn_graphs)
        grp.addButton(self.btn_procs)
        self.btn_graphs.setChecked(True)
        head.addWidget(seg, 1)

        self.btn_manager = self._icon_btn(T.icon_external(T.TEXT2), "Диспетчер задач")
        self.btn_manager.clicked.connect(self.open_manager.emit)
        head.addWidget(self.btn_manager)
        self.btn_settings = self._icon_btn(T.icon_sliders(T.TEXT2), "Настройки")
        self.btn_settings.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        head.addWidget(self.btn_settings)
        root.addLayout(head)

        # --- страницы
        self.stack = QStackedWidget()
        self.stack.addWidget(self._build_graphs())
        self.stack.addWidget(self._build_procs())
        root.addWidget(self.stack, 1)

        self.btn_graphs.toggled.connect(lambda on: on and self._switch("graphs"))
        self.btn_procs.toggled.connect(lambda on: on and self._switch("procs"))

    # ---------------------------------------------------------------- построение
    def _seg_btn(self, text, icon_fn) -> QPushButton:
        b = QPushButton(text)
        b.setObjectName("segBtn")
        b.setCheckable(True)
        b.setFixedHeight(24)
        b.setFont(T.ui_font(12, QFont.Weight.DemiBold))
        b.setIcon(icon_fn(T.TEXT2))
        b.setIconSize(QSize(12, 12))
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        b.toggled.connect(lambda on, b=b, f=icon_fn: b.setIcon(f(T.TEXT if on else T.TEXT2)))
        return b

    def _icon_btn(self, icon, tip) -> QToolButton:
        b = QToolButton()
        b.setObjectName("iconBtn")
        b.setIcon(icon)
        b.setIconSize(QSize(15, 15))
        b.setFixedSize(28, 28)
        b.setToolTip(tip)
        b.setAutoRaise(True)
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        return b

    def _build_graphs(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(8, 0, 8, 8)
        lay.setSpacing(6)
        grid = QGridLayout()
        grid.setSpacing(6)
        self.tiles = {
            "cpu": MetricTile("ЦП", T.CPU),
            "ram": MetricTile("Память", T.RAM),
            "disk": MetricTile("Диск", T.DISK),
            "net": MetricTile("Сеть", T.NET),
        }
        for i, k in enumerate(("cpu", "ram", "disk", "net")):
            grid.addWidget(self.tiles[k], i // 2, i % 2)
        lay.addLayout(grid, 1)

        cores = QFrame()
        cores.setObjectName("tile")
        cores.setFixedHeight(26)
        cl = QHBoxLayout(cores)
        cl.setContentsMargins(9, 6, 9, 6)
        cl.setSpacing(8)
        lbl = QLabel("Ядра")
        lbl.setFont(T.ui_font(11))
        lbl.setProperty("role", "muted")
        lbl.setFixedWidth(32)
        cl.addWidget(lbl)
        self.cores = CoreBars()
        cl.addWidget(self.cores, 1)
        lay.addWidget(cores)
        return page

    def _build_procs(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(8, 0, 6, 6)
        lay.setSpacing(2)
        self.search = QLineEdit()
        self.search.setObjectName("search")
        self.search.setPlaceholderText("Поиск по имени или PID")
        self.search.setFixedHeight(28)
        self.search.setFont(T.ui_font(12))
        self.search.setClearButtonEnabled(True)
        self.search.addAction(T.icon_search(T.TEXT2), QLineEdit.ActionPosition.LeadingPosition)
        self.search.textChanged.connect(lambda _: self._refill_procs(force_sort=True))
        lay.addWidget(self.search)

        self.model = ProcModel()
        self.view = ProcView(self.model)
        self.view.horizontalHeader().sectionClicked.connect(self._header_clicked)
        self.view.kill_requested.connect(self._kill_group)
        self.view.menu_requested.connect(self._group_menu)
        lay.addWidget(self.view, 1)
        return page

    # ---------------------------------------------------------------- логика
    def current_tab(self) -> str:
        return "procs" if self.stack.currentIndex() == 1 else "graphs"

    def set_tab(self, tab: str) -> None:
        (self.btn_procs if tab == "procs" else self.btn_graphs).setChecked(True)

    def _switch(self, tab: str) -> None:
        self.stack.setCurrentIndex(1 if tab == "procs" else 0)
        self.tab_changed.emit(tab)
        if tab == "procs":
            self.search.setFocus()
            self.refresh_requested.emit()

    def _header_clicked(self, section: int) -> None:
        if section == COL_CPU:
            self.model.set_sort("cpu")
        elif section == COL_MEM:
            self.model.set_sort("mem")
        else:
            return
        self._refill_procs(force_sort=True)

    def _kill_group(self, g: Group) -> None:
        errs = PA.terminate(g.pids)
        if errs:
            self.notify(f"Не удалось завершить «{g.name}»", "\n".join(errs[:6]))
        self.refresh_requested.emit()

    def _group_menu(self, g: Group, gpos) -> None:
        m = PA.build_menu(self, g.main_pid, g.name, g.pids, self.notify, is_group=g.count > 1)
        m.exec(gpos)
        self.refresh_requested.emit()

    def update_data(self, s, hist: History) -> None:
        self._last_snapshot = s
        if not self.isVisible():
            return
        if self.current_tab() == "graphs":
            fill_tiles(self.tiles, hist, s)
            self.cores.set_values(s.per_cpu)
        elif s.procs is not None:
            self._refill_procs()

    def refresh_graphs(self, s, hist: History) -> None:
        fill_tiles(self.tiles, hist, s)
        self.cores.set_values(s.per_cpu)

    def _refill_procs(self, force_sort: bool = False) -> None:
        s = self._last_snapshot
        if s is None or s.procs is None:
            return
        groups = group_procs(s.procs)
        q = self.search.text().strip().lower()
        if q:
            groups = [g for g in groups
                      if q in g.name.lower() or any(q == str(pid) or str(pid).startswith(q) for pid in g.pids)]
        by_name = {g.name: g for g in groups}
        if self.view.hovering and not force_sort and self._order:
            # пока курсор над списком — порядок не меняем, чтобы ✕ не «уехал»
            rows = [by_name[n] for n in self._order if n in by_name]
            known = set(self._order)
            rows += [g for g in groups if g.name not in known]
        else:
            key = (lambda g: g.cpu) if self.model.sort == "cpu" else (lambda g: g.mem)
            rows = sorted(groups, key=key, reverse=True)
        self._order = [g.name for g in rows]
        sb = self.view.verticalScrollBar()
        pos = sb.value()
        self.model.set_rows(rows)
        sb.setValue(pos)

    # ---------------------------------------------------------------- окно
    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(QPen(QColor(T.BORDER), 1))
        p.setBrush(QColor(T.BG))
        p.drawRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), 10, 10)
        p.end()

    def showEvent(self, e) -> None:
        super().showEvent(e)
        self.visibility_changed.emit(True)
        s = self._last_snapshot
        if s is not None and self.current_tab() == "procs":
            self._refill_procs(force_sort=True)

    def hideEvent(self, e) -> None:
        super().hideEvent(e)
        self.visibility_changed.emit(False)

    def keyPressEvent(self, e: QKeyEvent) -> None:
        if e.key() == Qt.Key.Key_Escape:
            if self.current_tab() == "procs" and self.search.text():
                self.search.clear()
            else:
                self.hide()
            return
        if e.key() == Qt.Key.Key_Tab and e.modifiers() == Qt.KeyboardModifier.ControlModifier:
            self.set_tab("graphs" if self.current_tab() == "procs" else "procs")
            return
        super().keyPressEvent(e)

    def event(self, e) -> bool:
        if e.type() == QEvent.Type.WindowDeactivate and self.isVisible():
            # клик мимо окна — прячемся (меню/диалоги поверх не считаем)
            from PyQt6.QtWidgets import QApplication
            active = QApplication.activePopupWidget() or QApplication.activeModalWidget()
            if active is None:
                self.hide()
                self.hidden_by_focus_loss.emit()
        return super().event(e)

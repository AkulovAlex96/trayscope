"""Связка: значок в трее, всплывающее окно, диспетчер задач, фоновый сборщик."""
from __future__ import annotations

import sys
import time

from PyQt6.QtCore import QObject, QThread, pyqtSignal
from PyQt6.QtGui import QAction, QActionGroup, QCursor, QGuiApplication, QIcon
from PyQt6.QtNetwork import QLocalServer, QLocalSocket
from PyQt6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from . import theme as T
from . import trayicon
from .collector import Worker
from .osdep import WINDOWS, instance_id
from .panel import tray_panel
from .popup import Popup, H as POPUP_H, W as POPUP_W
from .settings import ICON_STYLES, INTERVALS, Settings
from .taskmanager import TaskManager
from .widgets import History

SOCKET_NAME = f"traymonitor-{instance_id()}"
MARGIN = 8


class Controller(QObject):
    interval_changed = pyqtSignal(int)
    refresh = pyqtSignal()

    def __init__(self, app: QApplication) -> None:
        super().__init__()
        self.app = app
        self.settings = Settings()
        self.hist = History()
        self.last = None
        self.manager: TaskManager | None = None
        self._popup_hidden_at = 0.0

        # --- фоновый сборщик
        self.thread = QThread()
        self.worker = Worker(self.settings.interval)
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.start)
        self.worker.snapshot.connect(self.on_snapshot)
        self.interval_changed.connect(self.worker.set_interval)
        self.refresh.connect(self.worker.refresh_now)

        # --- окна
        self.popup = Popup(self.notify)
        self.popup.open_manager.connect(self.show_manager)
        self.popup.visibility_changed.connect(lambda _: self._update_want())
        self.popup.tab_changed.connect(lambda _: self._update_want())
        self.popup.refresh_requested.connect(self._request_refresh)
        self.popup.hidden_by_focus_loss.connect(self._mark_hidden)

        # --- трей
        self.tray = QSystemTrayIcon()
        self.tray.setIcon(trayicon.render(self.settings.icon_style, 0, 0, []))
        self.tray.setToolTip("Tray Monitor")
        self.tray.activated.connect(self.on_activated)
        self._build_menus()
        self.tray.show()

        self.thread.start()

    # ---------------------------------------------------------------- меню
    def _build_menus(self) -> None:
        self.style_menu = QMenu("Вид значка")
        g = QActionGroup(self.style_menu)
        for key, label in ICON_STYLES.items():
            a = self.style_menu.addAction(label)
            a.setCheckable(True)
            a.setChecked(key == self.settings.icon_style)
            a.triggered.connect(lambda _=False, k=key: self.set_icon_style(k))
            g.addAction(a)

        self.interval_menu = QMenu("Обновление")
        g = QActionGroup(self.interval_menu)
        for ms, label in INTERVALS.items():
            a = self.interval_menu.addAction(label)
            a.setCheckable(True)
            a.setChecked(ms == self.settings.interval)
            a.triggered.connect(lambda _=False, v=ms: self.set_interval(v))
            g.addAction(a)

        self.autostart_action = QAction("Запускать при входе", self)
        self.autostart_action.setCheckable(True)
        self.autostart_action.setChecked(self.settings.autostart)
        self.autostart_action.toggled.connect(self.set_autostart)

        self.quit_action = QAction("Выход", self)
        self.quit_action.triggered.connect(self.quit)

        # меню по ПКМ на значке
        m = QMenu()
        m.addAction("Показать панель").triggered.connect(self.show_popup)
        m.addAction("Диспетчер задач").triggered.connect(self.show_manager)
        m.addSeparator()
        m.addMenu(self.style_menu)
        m.addMenu(self.interval_menu)
        m.addAction(self.autostart_action)
        m.addSeparator()
        m.addAction(self.quit_action)
        self.tray_menu = m
        self.tray.setContextMenu(m)

        # меню кнопки «Настройки» в окне
        sm = QMenu(self.popup)
        sm.addAction(self.style_menu.menuAction())
        sm.addAction(self.interval_menu.menuAction())
        sm.addAction(self.autostart_action)
        sm.addSeparator()
        sm.addAction(self.quit_action)
        self.popup.btn_settings.setMenu(sm)

    def set_icon_style(self, key: str) -> None:
        self.settings.icon_style = key
        self._update_tray()

    def set_interval(self, ms: int) -> None:
        self.settings.interval = ms
        self.interval_changed.emit(ms)

    def set_autostart(self, on: bool) -> None:
        try:
            self.settings.autostart = on
        except OSError as e:
            self.notify("Автозапуск", str(e))

    # ---------------------------------------------------------------- окна
    def on_activated(self, reason) -> None:
        R = QSystemTrayIcon.ActivationReason
        if reason == R.Trigger:
            self.toggle_popup()
        elif reason == R.MiddleClick:
            self.show_manager()

    def _mark_hidden(self) -> None:
        self._popup_hidden_at = time.monotonic()

    def toggle_popup(self) -> None:
        if self.popup.isVisible():
            self.popup.hide()
        elif time.monotonic() - self._popup_hidden_at < 0.35:
            # окно только что закрылось из-за клика по этому же значку
            pass
        else:
            self.show_popup()

    def _popup_pos_windows(self):
        """Windows: Qt знает точное место значка; панель задач — по рабочей области."""
        icon = self.tray.geometry()
        if icon.isEmpty():
            return None
        screen = QGuiApplication.screenAt(icon.center()) or QGuiApplication.primaryScreen()
        geo, av = screen.geometry(), screen.availableGeometry()
        gap = MARGIN
        if av.top() > geo.top():                       # панель задач сверху
            x, y = icon.center().x() - POPUP_W // 2, av.top() + gap
        elif av.left() > geo.left():                   # слева
            x, y = av.left() + gap, icon.center().y() - POPUP_H // 2
        elif av.right() < geo.right():                 # справа
            x, y = av.right() + 1 - gap - POPUP_W, icon.center().y() - POPUP_H // 2
        else:                                          # снизу (по умолчанию) или автоскрытие
            x = icon.center().x() - POPUP_W // 2
            y = min(av.bottom(), icon.top() - 1) + 1 - gap - POPUP_H
        x = max(av.left() + MARGIN, min(x, av.right() + 1 - POPUP_W - MARGIN))
        y = max(av.top() + MARGIN, min(y, av.bottom() + 1 - POPUP_H - MARGIN))
        return x, y

    def _popup_pos(self):
        if WINDOWS:
            return self._popup_pos_windows() or self._popup_pos_fallback()
        pi = tray_panel()
        if pi is not None:
            r, g = pi.rect, pi.screen
            gap = 6
            if pi.location == "bottom":
                x, y = r.right() + 1 - POPUP_W, r.top() - gap - POPUP_H
            elif pi.location == "top":
                x, y = r.right() + 1 - POPUP_W, r.bottom() + 1 + gap
            elif pi.location == "left":
                x, y = r.right() + 1 + gap, r.bottom() + 1 - POPUP_H
            else:
                x, y = r.left() - gap - POPUP_W, r.bottom() + 1 - POPUP_H
            x = max(g.left() + MARGIN, min(x, g.right() + 1 - POPUP_W - MARGIN))
            y = max(g.top() + MARGIN, min(y, g.bottom() + 1 - POPUP_H - MARGIN))
            return x, y
        return self._popup_pos_fallback()

    def _popup_pos_fallback(self):
        cur = QCursor.pos()
        screen = QGuiApplication.screenAt(cur) or QGuiApplication.primaryScreen()
        geo, av = screen.geometry(), screen.availableGeometry()
        cursor_on_panel = geo.contains(cur) and not av.contains(cur)

        def clamp_x(x):
            return max(av.left() + MARGIN, min(x, av.right() - POPUP_W - MARGIN + 1))

        def clamp_y(y):
            return max(av.top() + MARGIN, min(y, av.bottom() - POPUP_H - MARGIN + 1))

        x = clamp_x(cur.x() - POPUP_W // 2) if cursor_on_panel else av.right() - POPUP_W - MARGIN + 1
        y = av.bottom() - POPUP_H - MARGIN + 1
        if av.top() > geo.top():                       # панель сверху
            y = av.top() + MARGIN
        elif av.left() > geo.left():                   # панель слева
            x = av.left() + MARGIN
            y = clamp_y(cur.y() - POPUP_H // 2) if cursor_on_panel else y
        elif av.right() < geo.right():                 # панель справа
            x = av.right() - POPUP_W - MARGIN + 1
            y = clamp_y(cur.y() - POPUP_H // 2) if cursor_on_panel else y
        return x, y

    def show_popup(self) -> None:
        self.popup.set_tab("graphs")
        if self.last is not None:
            self.popup._last_snapshot = self.last
            self.popup.refresh_graphs(self.last, self.hist)
        x, y = self._popup_pos()
        self.popup.move(x, y)
        self.popup.show()
        self.popup.raise_()
        self.popup.activateWindow()

    def show_manager(self) -> None:
        self.popup.hide()
        if self.manager is None:
            self.manager = TaskManager(self.notify)
            self.manager.visibility_changed.connect(lambda _: self._update_want())
            self.manager.refresh_requested.connect(self._request_refresh)
            if self.last is not None:
                self.manager.update_data(self.last, self.hist)
        if self.manager.isMinimized():
            self.manager.showNormal()
        self.manager.show()
        self.manager.raise_()
        self.manager.activateWindow()

    def _update_want(self) -> None:
        want = (self.popup.isVisible() and self.popup.current_tab() == "procs") or \
               (self.manager is not None and self.manager.isVisible())
        changed = want != self.worker.want_procs
        self.worker.want_procs = want
        if want and changed:
            self.refresh.emit()

    def _request_refresh(self) -> None:
        self._update_want()
        self.refresh.emit()

    # ---------------------------------------------------------------- данные
    def on_snapshot(self, s) -> None:
        self.hist.push(s)
        self.last = s
        self._update_tray()
        self.popup.update_data(s, self.hist)
        if self.manager is not None:
            self.manager.update_data(s, self.hist)

    def _update_tray(self) -> None:
        s = self.last
        if s is None:
            return
        self.tray.setIcon(trayicon.render(self.settings.icon_style, s.cpu, s.mem_percent, self.hist.cpu))
        temp = f" · {s.temp:.0f} °C" if s.temp is not None else ""
        self.tray.setToolTip(
            f"ЦП {s.cpu:.0f} %{temp}\n"
            f"Память {T.fmt_bytes(s.mem_used)} / {T.fmt_bytes(s.mem_total)}\n"
            f"Диск R {T.fmt_rate_s(s.disk_read)} · W {T.fmt_rate_s(s.disk_write)}\n"
            f"Сеть ↓ {T.fmt_rate_s(s.net_down)} · ↑ {T.fmt_rate_s(s.net_up)}")

    def notify(self, title: str, text: str) -> None:
        self.tray.showMessage(title, text, QSystemTrayIcon.MessageIcon.Warning, 6000)

    def handle_command(self, cmd: str) -> None:
        if cmd == "manager":
            self.show_manager()
        else:
            self.show_popup()

    def quit(self) -> None:
        self.worker.stop()
        self.thread.quit()
        self.thread.wait(2000)
        self.tray.hide()
        self.app.quit()


def _send_to_running(cmd: str) -> bool:
    sock = QLocalSocket()
    sock.connectToServer(SOCKET_NAME)
    if not sock.waitForConnected(300):
        return False
    if WINDOWS:
        # без этого Windows не даст работающему экземпляру вывести окно на передний план
        try:
            import ctypes
            ctypes.windll.user32.AllowSetForegroundWindow(-1)  # ASFW_ANY
        except Exception:
            pass
    sock.write(cmd.encode() + b"\n")
    sock.flush()
    sock.waitForBytesWritten(300)
    sock.disconnectFromServer()
    return True


def main(argv: list[str]) -> int:
    cmd = "manager" if "--manager" in argv else "popup" if "--popup" in argv else ""
    if WINDOWS:
        # своя группа на панели задач вместо «python.exe»
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Trayscope.TrayMonitor")
        except Exception:
            pass
    app = QApplication(argv)
    app.setApplicationName("Tray Monitor")
    app.setQuitOnLastWindowClosed(False)
    icon = QIcon.fromTheme("utilities-system-monitor")
    if icon.isNull():   # в Windows нет иконочной темы — рисуем свою
        icon = trayicon.render("bars", 35, 55, [])
    app.setWindowIcon(icon)

    if _send_to_running(cmd or "popup"):
        return 0

    app.setStyleSheet(T.stylesheet())
    if not QSystemTrayIcon.isSystemTrayAvailable():
        print("Системный трей недоступен", file=sys.stderr)

    ctl = Controller(app)

    server = QLocalServer()
    QLocalServer.removeServer(SOCKET_NAME)
    server.listen(SOCKET_NAME)

    def on_conn():
        c = server.nextPendingConnection()
        if c is None:
            return
        def read():
            data = bytes(c.readAll()).decode(errors="ignore").strip()
            if data:
                ctl.handle_command(data.splitlines()[-1])
        c.readyRead.connect(read)
        c.disconnected.connect(c.deleteLater)
    server.newConnection.connect(on_conn)

    if cmd:
        ctl.handle_command(cmd)
    return app.exec()

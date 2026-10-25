# -*- coding: utf-8 -*-
"""入口: 单实例加锁 + QApplication + 主窗口。"""

import ctypes
import os
import sys

from PyQt5.QtCore import QSettings, Qt
from PyQt5.QtGui import QFont, QIcon
from PyQt5.QtWidgets import QAction, QApplication, QMenu, QSystemTrayIcon

from .assets import resource_path
from .config import IMG_TRAY, INSTANCE_MUTEX, INSTANCE_TITLE, Store
from .pet import DesktopPet


# ================================ 单实例 ================================
ERROR_ALREADY_EXISTS = 183
_MUTEX_HANDLE = None            # 必须留引用: 句柄在, 互斥体才在


def acquire_single_instance() -> bool:
    """进程级互斥(内核 mutex, 不依赖命名管道); 返回是否为第一个实例。"""
    global _MUTEX_HANDLE
    if sys.platform != "win32":
        return True
    try:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_wchar_p]
        kernel32.CreateMutexW.restype = ctypes.c_void_p
        handle = kernel32.CreateMutexW(None, 0, INSTANCE_MUTEX)
        if not handle:
            return True                      # 建不了就别拦用户
        _MUTEX_HANDLE = handle
        return ctypes.get_last_error() != ERROR_ALREADY_EXISTS
    except Exception:
        return True


def raise_existing_window():
    """第二个实例: 把已经在跑的那只猫叫到前台, 然后自己退出。"""
    if sys.platform != "win32":
        return
    try:
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        user32.FindWindowW.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p]
        user32.FindWindowW.restype = ctypes.c_void_p
        hwnd = user32.FindWindowW(None, INSTANCE_TITLE)
        if hwnd:
            user32.ShowWindow(hwnd, 9)        # SW_RESTORE
            user32.SetForegroundWindow(hwnd)
    except Exception:
        pass


# ================================== 入口 ==================================
def setup_tray(app, pet):
    """托盘图标: 左键显隐, 右键菜单(显示/设置/重置位置/退出)。

    图标找不到就用 idle 帧兜底; 两者都没有就干脆不建托盘(不影响主功能)。
    """
    if not QSystemTrayIcon.isSystemTrayAvailable():
        print("[pet] 本机没有系统托盘, 跳过", file=sys.stderr)
        return None

    icon_path = resource_path(IMG_TRAY)
    icon = QIcon(icon_path) if os.path.exists(icon_path) else QIcon()
    if icon.isNull() and pet.pix_idle is not None:
        icon = QIcon(pet.pix_idle)
        print(f"[pet] 没找到 {IMG_TRAY}, 托盘图标暂时用 idle 图", file=sys.stderr)
    if icon.isNull():
        print("[pet] 没有可用图标, 跳过托盘", file=sys.stderr)
        return None

    tray = QSystemTrayIcon(icon, app)
    tray.setToolTip("六一桌宠")

    menu = QMenu()
    act_show = QAction("显示 / 隐藏 六一", menu)
    act_show.triggered.connect(lambda: pet.setVisible(not pet.isVisible()))
    menu.addAction(act_show)

    act_feed = QAction("喂个小零食", menu)
    act_feed.triggered.connect(pet._feed)
    menu.addAction(act_feed)

    menu.addSeparator()
    act_top = QAction("始终置顶", menu, checkable=True)
    act_top.setChecked(pet.always_on_top)
    act_top.triggered.connect(pet._toggle_on_top)
    menu.addAction(act_top)

    act_anim = QAction("动画开关", menu, checkable=True)
    act_anim.setChecked(pet.anim_enabled)
    act_anim.triggered.connect(pet._toggle_anim)
    menu.addAction(act_anim)

    act_power = QAction("省电模式", menu, checkable=True)
    act_power.setChecked(pet.power_saver)
    act_power.triggered.connect(pet._toggle_power)
    menu.addAction(act_power)

    menu.addSeparator()

    act_settings = QAction("提醒与纪念日设置…", menu)
    act_settings.triggered.connect(pet._open_settings)
    menu.addAction(act_settings)

    act_reset = QAction("把六一放回右下角", menu)
    act_reset.triggered.connect(pet._reset_window)
    menu.addAction(act_reset)

    menu.addSeparator()
    act_quit = QAction("退出", menu)
    act_quit.triggered.connect(pet.shutdown)
    menu.addAction(act_quit)

    tray.setContextMenu(menu)
    tray.activated.connect(
        lambda reason: pet.setVisible(not pet.isVisible())
        if reason == QSystemTrayIcon.Trigger else None)
    tray.show()
    return tray


def main() -> int:
    settings = QSettings("RagdollPet", "DesktopPet")
    if settings.value("high_dpi", True, type=bool):
        QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
        QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)

    app = QApplication(sys.argv)
    app.setApplicationName("RagdollPet")
    app.setQuitOnLastWindowClosed(False)
    app.setFont(QFont("Microsoft YaHei", 9))

    if not acquire_single_instance():
        raise_existing_window()
        print("桌面宠物已经在运行了, 已唤起。")
        return 0

    pet = DesktopPet(Store(settings))
    pet.show()                                # 关窗时 shutdown() 里已经存过位置, 不必再连一次

    tray = setup_tray(app, pet)
    if tray is not None:                     # 保住引用, 否则会被回收掉
        app._tray = tray
        app.aboutToQuit.connect(tray.hide)

    return app.exec_()


if __name__ == "__main__":
    sys.exit(main())



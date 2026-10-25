# -*- coding: utf-8 -*-
"""六一桌宠: 桌面挂件。

代码已拆成六个模块:
    config  常量 / 台词 / 路径 / 配置(pet.json) / 空闲检测
    assets  素材查找
    frames  帧选择 / 缩放缓存 / 窗口遮罩
    bubble  对话气泡
    pet     主窗口(状态机、绘制、菜单、设置)
    app     单实例 + 入口

    from ragdollpet import DesktopPet, Store, main
"""

from .assets import resource_path
from .bubble import SpeechBubble
from .config import *          # noqa: F401,F403  常量/台词/Store/app_dir/空闲检测
from .frames import FrameMixin
from .pet import DesktopPet

__all__ = [
    "DesktopPet", "SpeechBubble", "FrameMixin", "Store",
    "app_dir", "resource_path", "main",
]


def main() -> int:
    """延迟导入 app, 避免 import 包时就初始化 GUI 依赖。"""
    from .app import main as _main
    return _main()

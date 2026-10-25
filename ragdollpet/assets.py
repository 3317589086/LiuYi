# -*- coding: utf-8 -*-
"""素材查找: 按 image/ → 脚本目录 → assets/ → 工作目录 的顺序找图。"""

import os
import sys

from .config import app_dir


def resource_path(name: str) -> str:
    """按 image/ → exe 旁 → 脚本目录 → assets/ → 工作目录 的顺序找资源。

    image/ 排最前: 正式素材都放那里; 根目录常被用来放原图, 不能被它抢先生效。
    """
    candidates = []
    if getattr(sys, "frozen", False):
        exe_dir = os.path.dirname(os.path.abspath(sys.executable))
        # exe 旁边的 image/ 优先: 想换图不用重新打包
        candidates += [os.path.join(exe_dir, "image", name), os.path.join(exe_dir, name)]
    candidates += [
        os.path.join(app_dir(), "image", name),
        os.path.join(app_dir(), name),
        os.path.join(app_dir(), "assets", name),
        os.path.join(os.getcwd(), name),
    ]
    for path in candidates:
        if os.path.exists(path):
            return path
    return candidates[0]


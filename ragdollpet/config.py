# -*- coding: utf-8 -*-
"""常量、台词库、路径、配置存储(JSON)、系统空闲检测。"""

import ctypes
import json
import os
import sys
import time
from datetime import date

from PyQt5.QtCore import QSettings   # 只在首次迁移旧配置时用到

# ==================== 资源 / 尺寸 ====================
IMG_IDLE = "cat_idle.png"
IMG_SLEEP = "cat_sleep.png"
IMG_CLICK = "cat_click.png"
IMG_WALK_A = "cat_walk_a.png"    # 步态帧(旧命名, 兼容)
IMG_WALK_B = "cat_walk_b.png"
IMG_WALK_C = "cat_walk_c.png"
# 4~6 帧循环请命名 cat_walk_1.png … cat_walk_6.png, 按编号顺序播放
IMG_WALK_SEQ = [f"cat_walk_{i}.png" for i in range(1, 9)]
IMG_WALK_LEGACY = [IMG_WALK_A, IMG_WALK_B, IMG_WALK_C]
IMG_PET = "cat_pet.png"          # 可选: 被摸(眯眼/蹭头); 没有就退回"炸毛跳"
IMG_BLINK = "cat_blink.png"      # 可选: 专门的闭眼帧; 没有就把 idle 整体压扁当眨眼
IMG_HOLD = "cat_hold.png"        # 可选: 被拎起(拖动时用); 没有就保持待机图
IMG_TRAY = "tray_icon.png"       # 可选: 托盘图标; 没有就用 idle 图当图标
IMG_EAT = ["cat_eat.png", "cat_eat2.png"]   # 可选: 吃零食两帧(张嘴/闭嘴)
EAT_MS = 180                     # 咀嚼每帧停留(毫秒)

BASE_H = 220            # 1.0x 时猫的显示高度(逻辑像素)
TOP_MARGIN = 64         # 窗口顶部留白, 必须 > JUMP_HEIGHT
JUMP_HEIGHT = 52        # 点击跳跃高度
BLINK_RATIO = 0.94      # 眨眼纵向压缩比
MASK_INFLATE = 4        # mask 外扩像素(吸收呼吸 ±3 / 甩尾 ±2 的小位移)
FRAME_MS = 33           # 动画帧间隔(~30fps)
LOGIC_MS = 1000         # 状态机 / 空闲检测间隔
PET_MS = 700            # 被摸表情持续时间
DOUBLE_CLICK_SEC = 0.5    # 两次点击间隔小于这个值(秒) -> 当作"连戳", 炸毛
BUBBLE_GAP = 6          # 气泡和猫头之间的间隙
PET_NAME = "六一"        # 小猫的名字
SCALE_MIN, SCALE_MAX = 0.5, 2.5
INSTANCE_MUTEX = "Local\\RagdollPet.DesktopPet.v21"   # 内核互斥体, 不占命名管道
INSTANCE_TITLE = "RagdollPet-DesktopPet"              # 供第二个实例 FindWindow 定位

# 键名与 v2.0 保持一致, 老配置可直接沿用
DEFAULTS = {
    "scale_val": 1.0,
    "ontop": True,
    "water_on": True,
    "water_min": 45,
    "sleep_min": 5,
    "deep_sleep_min": 10,
    "anim_on": True,
    "power_saver": False,
    "high_dpi": True,
    "anni_name": "",
    "anni_date": "",
    "last_anni_shown": "",
    "pos_x": -99999,
    "pos_y": -99999,
}


# ----------------------------------- 台词库 -----------------------------------
LINES_IDLE = [
    "你忙你的，我乖乖趴在旁边就好～",
    "(甩了甩蓬松的大尾巴)发呆中…好吧，可以摸一下",
    "坐太久啦，快起来伸个懒腰",
    "今天也要加油哦，我在旁边给你打气",
    "专心工作哦，我安安静静不吵你",
    "进度怎么样啦？要不要歇会儿喝口水",
    "加油干完，等下就可以陪我玩啦",
    f"{PET_NAME}在这儿，摸一下再走嘛",
]
LINES_CLICK = [
    "呼噜呼噜～下巴这里再揉揉嘛",
    "被你摸到啦，好舒服呀",
    "(蹭蹭你的指尖)你最好啦",
    "别停别停，脑袋上也要摸摸",
    f"{PET_NAME}最喜欢被摸下巴了",
]
LINES_ANGRY = [
    "哼！不许拽我尾巴，我要炸毛啦",
    "戳那么快干嘛，我又不会跑……",
    "再戳就挠你了哦（虚张声势）",
]
LINES_SLEEP = [
    "还不睡吗？我都困得睁不开眼啦",
    "好困啊…我先眯一会儿，有事叫我",
    "(打哈欠)今天的阳光也太适合睡觉了",
    "趴在你身边，睡得最安心啦",
]
LINES_FEED = [
    "是罐罐的味道！我来啦",
    "谢谢主人～今天的小零食超好吃",
    "就再吃一口，就一口好不好嘛",
]
LINES_BACK = [
    "你终于回来啦，我等你好久好久了",
    "回来啦？我还以为你把我忘在这儿了",
]



# ============================ 路径 / 系统工具 ============================
def app_dir() -> str:
    """素材根目录: 打包后是解包目录(_MEIPASS), 源码运行时是包的上一级。"""
    if getattr(sys, "frozen", False):
        return getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def data_dir() -> str:
    """可写目录(配置放这儿): 打包后是 exe 所在目录, 源码运行时是项目根。

    _MEIPASS 是临时解包目录, 退出即删, 配置写进去会丢。
    """
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return app_dir()



# ================================ 设置封装 ================================
class Store:
    """pet.json 配置封装: 类型安全 + 默认值集中, 别在 __init__ 里散十几行取值。

    第一次运行时会把旧 QSettings(注册表) 里的值搬进 pet.json, 之后全走 JSON:
    备份、换机器、手改都只动一个文件。传 QSettings 只为兼容旧调用/测试隔离
    (INI 格式时按它的文件名推出同名 .json)。
    """

    def __init__(self, qsettings: QSettings = None):
        self._legacy = qsettings or QSettings("RagdollPet", "DesktopPet")
        self.path = self._json_path(qsettings)
        self.data = dict(DEFAULTS)
        self._load()

    @staticmethod
    def _json_path(qsettings) -> str:
        try:
            if qsettings is not None and qsettings.format() == QSettings.IniFormat:
                base, _ = os.path.splitext(qsettings.fileName())
                if base:
                    return base + ".json"
        except Exception:
            pass
        return os.path.join(data_dir(), "pet.json")

    def _load(self):
        try:
            with open(self.path, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            self._migrate()
            return
        if isinstance(data, dict):
            for key in DEFAULTS:
                if key in data:
                    self.data[key] = data[key]

    def _migrate(self):
        """旧配置在注册表里: 第一次跑搬过来, 搬完立刻落盘。"""
        try:
            for key, default in DEFAULTS.items():
                value = self._legacy.value(key, None)
                if value is None:
                    continue
                try:
                    if isinstance(default, bool):
                        self.data[key] = str(value).strip().lower() in ("1", "true", "yes", "on")
                    elif isinstance(default, float):
                        self.data[key] = float(value)
                    elif isinstance(default, int):
                        self.data[key] = int(value)
                    else:
                        self.data[key] = str(value)
                except (TypeError, ValueError):
                    pass
        except Exception:
            pass
        self.sync()

    def raw(self, key):
        return self.data.get(key, DEFAULTS.get(key, ""))

    def get_bool(self, key):
        value = self.raw(key)
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() in ("1", "true", "yes", "on")

    def get_int(self, key):
        try:
            return int(self.raw(key))
        except (TypeError, ValueError):
            return int(DEFAULTS[key])

    def get_float(self, key):
        try:
            return float(self.raw(key))
        except (TypeError, ValueError):
            return float(DEFAULTS[key])

    def get_str(self, key):
        value = self.raw(key)
        return "" if value is None else str(value)

    def set(self, key, value):
        self.data[key] = value
        self.sync()

    def sync(self):
        """原子写: 先落 .tmp 再 replace, 写一半断电也不会把配置弄坏。"""
        try:
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.data, f, ensure_ascii=False, indent=2)
            os.replace(tmp, self.path)
        except OSError:
            pass



class _LASTINPUTINFO(ctypes.Structure):
    _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]


def _build_idle_probe():
    """返回取全局空闲秒数的函数; 非 Windows 或调用失败返回 -1。"""
    if sys.platform != "win32":
        return lambda: -1.0
    try:
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        get_last_input = user32.GetLastInputInfo
        get_last_input.argtypes = [ctypes.POINTER(_LASTINPUTINFO)]
        get_last_input.restype = ctypes.c_int
        try:                                   # 64 位计数器, 不会 49.7 天回绕
            get_tick = kernel32.GetTickCount64
            get_tick.restype = ctypes.c_ulonglong
        except AttributeError:
            get_tick = kernel32.GetTickCount
            get_tick.restype = ctypes.c_uint32
        get_tick.argtypes = []
    except Exception:
        return lambda: -1.0

    def probe() -> float:
        try:
            info = _LASTINPUTINFO(ctypes.sizeof(_LASTINPUTINFO), 0)
            if not get_last_input(ctypes.byref(info)):
                return -1.0
            now_ms = get_tick()
            # 两边都截到 32 位再按无符号回绕相减, 兼容只有 GetTickCount 的老系统
            return ((now_ms - info.dwTime) & 0xFFFFFFFF) / 1000.0
        except Exception:
            return -1.0

    return probe


get_global_idle_seconds = _build_idle_probe()



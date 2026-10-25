# -*- coding: utf-8 -*-
"""
================================================================================
 桌面宠物 · Q版布偶猫  v2.2
--------------------------------------------------------------------------------
 这是 ragdollpet 包里的「主窗口」模块。完整程序由六个模块组成:
   config.py   常量 / 台词 / 路径 / 配置(pet.json) / 系统空闲检测
   assets.py   素材查找( image/ → 脚本目录 → assets/ → 工作目录 )
   frames.py   帧选择 / 缩放缓存 / 窗口遮罩 / 载入时自动归一化
   bubble.py   对话气泡
   pet.py      本文件: 主窗口(状态机、绘制、菜单、设置)
   app.py      单实例锁 + 入口

 依赖:   pip install PyQt5==5.15.11
 运行:   双击 desktop_pet_v2.1.py(启动器), 或 python desktop_pet_v2.1.py
 打包:   pyinstaller --noconsole --onefile --name RagdollPet ^
           --add-data "image;image" desktop_pet_v2.1.py
--------------------------------------------------------------------------------
 素材(都放 image/ 下, 统一 600x600 / 内容高 482 / 脚底 549 / 中心 300):
   cat_idle.png       睁眼端坐   → 待机(必需)
   cat_blink.png      闭眼       → 眨眼瞬间(可选, 缺了就用整体压扁)
   cat_sleep.png      趴卧睡觉   → 浅睡 / 深睡
   cat_click.png      炸毛       → 单击跳跃 / 连戳炸毛
   cat_pet.png        眯眼被摸   → 单击(可选, 缺了退回炸毛跳)
   cat_walk_1..8.png  步态循环   → 走动(可选, 缺了退回 idle)
   cat_walk_a/b/c.png 旧命名, 仅在没有编号帧时兜底
 找不到图时用 QPainter 简笔画兜底, 不崩。
--------------------------------------------------------------------------------
 v2.2 改动:
   [重构] 单文件 1500 行拆成 6 个模块, 启动器只负责 sys.path + main()
   [配置] QSettings(注册表) → pet.json; 首次启动自动迁移, 之后原子写入
   [新增] 闭眼帧 cat_blink.png: 有就真闭眼, 没有退回压扁式眨眼
   [新增] 载入时自动归一化: 非 600x600 的透明图自动对齐到标准基线
   [改进] 走路起伏改正弦(原先是"抬 2px / 落 0"两档, 4 帧时显得僵)
   [修复] app_dir() 在包里取到了包目录 → 资源与配置路径整体错位
   [修复] 设置保存时两条气泡连发, DPI 提示被"设置好啦"盖掉
   [修复] 退出时没停抖动定时器; 载入归一化不再逐像素扫描
--------------------------------------------------------------------------------
 历史关键修复(均在真机实测过):
   [性能] mask 由 Python 逐像素改 createAlphaMask()(C++): 7.3ms→0.14ms, 2x 28ms→0.74ms
   [修复] Zzz 被 mask 裁掉 / 跳跃顶点被窗口顶边削掉 / 转身后用到反的遮罩
   [修复] 走动被打断后永不恢复 / 关动画再开不散步 / 非单调时钟计时错
   [修复] 气泡贴窗口顶(离头顶 95px) → 按当前帧内容顶端算, 稳定 6px
   [体验] 单实例; 位置记忆; 拖拽边界钳制; 多屏适配; 高 DPI 按 dpr 出图
================================================================================
"""


import math
import os
import random
import sys
import time
import traceback
from datetime import date

from PyQt5.QtCore import (
    QDate, QEasingCurve, QPoint, QPropertyAnimation, QRect, QRectF,
    QSequentialAnimationGroup, QSize, QTimer, Qt, pyqtProperty,
)
from PyQt5.QtGui import (
    QBitmap, QBrush, QColor, QFont, QImage, QPainter, QPen, QPixmap, QRegion,
    QTransform,
)
from PyQt5.QtWidgets import (
    QAction, QApplication, QCheckBox, QDateEdit, QDialog, QDialogButtonBox,
    QFormLayout, QLabel, QLineEdit, QMenu, QSpinBox, QWidget,
)

from .assets import resource_path
from .bubble import SpeechBubble
from .config import (
    BASE_H, BLINK_RATIO, BUBBLE_GAP, DOUBLE_CLICK_SEC, FRAME_MS, IMG_BLINK, IMG_CLICK,
    IMG_IDLE, IMG_PET, IMG_SLEEP, IMG_WALK_LEGACY, IMG_WALK_SEQ, INSTANCE_TITLE,
    EAT_MS, IMG_EAT, IMG_HOLD, JUMP_HEIGHT, LINES_ANGRY, LINES_BACK, LINES_CLICK,
    LINES_FEED, LINES_IDLE,
    LINES_SLEEP, LOGIC_MS, MASK_INFLATE, PET_MS, PET_NAME, SCALE_MAX, SCALE_MIN,
    TOP_MARGIN, Store, app_dir, get_global_idle_seconds,
)
from .frames import FrameMixin


# ================================ 桌面宠物 ================================
class DesktopPet(FrameMixin, QWidget):

    def _get_offset_y(self) -> int:
        return self._dy

    def _set_offset_y(self, value):
        value = int(value)
        if value != self._dy:
            self._dy = value
            self.update()

    offset_y = pyqtProperty(int, fget=_get_offset_y, fset=_set_offset_y)

    def __init__(self, store: Store):
        super().__init__()
        self.store = store

        self.setWindowTitle(INSTANCE_TITLE)   # 第二个实例靠标题找到这只猫
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)

        # ---------- 配置 ----------
        self.scale = max(SCALE_MIN, min(store.get_float("scale_val"), SCALE_MAX))
        self.always_on_top = store.get_bool("ontop")
        self.water_enabled = store.get_bool("water_on")
        self.water_interval = store.get_int("water_min")
        self.sleep_minutes = store.get_int("sleep_min")
        self.deep_sleep_min = store.get_int("deep_sleep_min")
        self.anim_enabled = store.get_bool("anim_on")
        self.power_saver = store.get_bool("power_saver")
        self.anni_name = store.get_str("anni_name")
        self.anni_date = store.get_str("anni_date")

        # ---------- 状态 ----------
        self.state = "idle"            # idle / walk / sleep / deep_sleep
        self.facing = 1
        self.last_interact = time.monotonic()

        # ---------- 动画量 ----------
        self._dy = 0
        self.blink = False
        self._blink_left = random.randint(60, 180)
        self.tail_dx = 0
        self._tail_left = random.randint(180, 400)
        self.zzz_phase = 0.0
        self._zzz_divider = 0
        self._jumping = False
        self._walk_left = 0
        self._walk_total = 0
        self._walk_bob = 0                # 走路时的身体起伏(画图时叠加)
        self._angry_until = 0.0           # 炸毛表情保持到这一时刻
        self._shake_left = 0              # 抖动剩余步数
        self._walk_screen = None          # 走动期间缓存的屏幕, 每帧重读可用区域

        # ---------- 缓存 ----------
        self._pix_cache = {}           # (帧名, w, h, dpr) -> QPixmap
        self._mask_cache = {}
        self._mask_key = None          # 当前 mask 是按哪一帧建的          # (帧名, w, h, 有Z) -> QRegion
        self._font_cache = {}
        self._top_cache = {}            # 帧名 -> 内容顶端占图片高度的比例(气泡贴头用)
        self._mask_broken = False
        self._err_time = 0.0

        # ---------- 触点 / 杂项 ----------
        self._drag_off = None
        self._press_pos = None
        self._dragging = False
        self._water_pending = False
        self._used = {}

        # ---------- 呼吸动画 ----------
        self.breath_up = QPropertyAnimation(self, b"offset_y", self)
        self.breath_up.setStartValue(0)
        self.breath_up.setEndValue(-3)
        self.breath_up.setEasingCurve(QEasingCurve.OutSine)
        self.breath_down = QPropertyAnimation(self, b"offset_y", self)
        self.breath_down.setStartValue(-3)
        self.breath_down.setEndValue(0)
        self.breath_down.setEasingCurve(QEasingCurve.InSine)
        self.breath_group = QSequentialAnimationGroup(self)
        self.breath_group.addAnimation(self.breath_up)
        self.breath_group.addAnimation(self.breath_down)
        self.breath_group.setLoopCount(-1)

        # ---------- 跳跃动画 ----------
        self.jump_up = QPropertyAnimation(self, b"offset_y", self)
        self.jump_up.setDuration(280)
        self.jump_up.setEndValue(-JUMP_HEIGHT)
        self.jump_up.setEasingCurve(QEasingCurve.OutQuad)
        self.jump_down = QPropertyAnimation(self, b"offset_y", self)
        self.jump_down.setDuration(320)
        self.jump_down.setStartValue(-JUMP_HEIGHT)
        self.jump_down.setEndValue(0)
        self.jump_down.setEasingCurve(QEasingCurve.InQuad)
        self.jump_group = QSequentialAnimationGroup(self)
        self.jump_group.addAnimation(self.jump_up)
        self.jump_group.addAnimation(self.jump_down)
        self.jump_group.finished.connect(self._on_jump_finished)

        # ---------- 吃东西动画(张嘴/闭嘴) ----------
        self._eat_timer = QTimer(self, timeout=self._on_eat_tick)

        # ---------- 资源 ----------
        self.pix_idle = self._load_image(IMG_IDLE)
        self.pix_sleep = self._load_image(IMG_SLEEP)
        self.pix_click = self._load_image(IMG_CLICK)
        self.pix_idle_left = self._flipped(self.pix_idle)
        # 步态帧: 编号命名优先(cat_walk_1..8), 没有就退回 A/B/C; 1 张也能跑
        walk_names = ([n for n in IMG_WALK_SEQ if os.path.exists(resource_path(n))]
                      or IMG_WALK_LEGACY)
        self.pix_walk = [pm for pm in (self._load_image(n) for n in walk_names)
                         if pm is not None and not pm.isNull()]
        self.pix_walk_l = [p for p in (self._flipped(pm) for pm in self.pix_walk) if p]
        self._walk_toggle = 0                              # 步态帧计数
        # 每帧停留多少 tick: 目标一轮 ~1 秒, 帧数越多每帧越短
        self._walk_step_ticks = max(4, min(14, round(30 / max(1, len(self.pix_walk)))))
        # 被摸帧(可选): 没有就沿用"炸毛跳"
        self.pix_pet = self._load_image(IMG_PET)
        self.pix_pet_l = self._flipped(self.pix_pet)
        # 闭眼帧(可选): 有就用真闭眼, 没有就把 idle 压扁当眨眼
        self.pix_blink = self._load_image(IMG_BLINK)
        self.pix_blink_l = self._flipped(self.pix_blink)
        # 被拎起(可选): 拖动时用
        self.pix_hold = self._load_image(IMG_HOLD)
        self.pix_hold_l = self._flipped(self.pix_hold)
        self._holding = False
        # 吃零食(可选): 张嘴/闭嘴两帧循环
        self.pix_eat = [pm for pm in (self._load_image(n) for n in IMG_EAT) if pm is not None]
        self.pix_eat_l = [p for p in (self._flipped(pm) for pm in self.pix_eat) if p]
        self._eating = False
        self._eat_index = 0
        self._eat_left = 0
        self._petting = False
        self._last_click_at = 0.0
        self._missing_assets = self.pix_idle is None

        self.bubble = SpeechBubble()
        self._menu = None              # 懒建, 复用
        self._log_assets()             # 缺素材时把搜索路径打出来, 省得猜

        # ---------- 尺寸 / 位置 / mask ----------
        self._relayout()
        self._place_initial()
        self._rebuild_mask()
        self._apply_on_top(silent=True)

        # ---------- 定时器 ----------
        self._frame_timer = QTimer(self, timeout=self._on_frame)
        self._walk_timer = QTimer(self, timeout=self._on_walk_tick)
        self._logic_timer = QTimer(self, timeout=self._on_logic)
        self._logic_timer.start(LOGIC_MS)

        self._idle_talk = QTimer(self, timeout=self._on_idle_talk)
        self._idle_talk.start(random.randint(18, 35) * 1000)

        self._next_walk = QTimer(self, timeout=self._start_walk)
        self._next_walk.setSingleShot(True)
        self._schedule_walk(60, 120)

        self._water_timer = QTimer(self, timeout=self._on_water_remind)
        self._apply_water_timer()

        self._pet_timer = QTimer(self, timeout=self._end_pet)
        self._pet_timer.setSingleShot(True)

        self._apply_runtime()

        QTimer.singleShot(1500, self._startup_line)


    # ---------------------------------------------------------------- 位置
    @staticmethod
    def _screen_at(point: QPoint):
        return QApplication.screenAt(point) or QApplication.primaryScreen()

    def _screen(self):
        return self._screen_at(self.frameGeometry().center())

    def _clamp_pos(self, pos: QPoint) -> QPoint:
        """拖拽/恢复位置时保证至少 80px 留在屏幕内。"""
        area = self._screen_at(
            pos + QPoint(self.width() // 2, self.height() // 2)).availableGeometry()
        x = max(area.left() - self.width() + 80, min(pos.x(), area.right() - 80))
        y = max(area.top(), min(pos.y(), area.bottom() - 80))
        return QPoint(x, y)

    def _visible_somewhere(self, pos: QPoint) -> bool:
        rect = QRect(pos, self.size())
        for screen in QApplication.screens():
            inter = rect.intersected(screen.availableGeometry())
            if inter.width() >= 60 and inter.height() >= 60:
                return True
        return False

    def _place_initial(self):
        saved = QPoint(self.store.get_int("pos_x"), self.store.get_int("pos_y"))
        if abs(saved.x()) < 20000 and self._visible_somewhere(saved):
            self.move(self._clamp_pos(saved))
            return
        area = QApplication.primaryScreen().availableGeometry()
        self.move(area.right() - self.width() - 60, area.bottom() - self.height() - 60)

    def _save_pos(self):
        self.store.set("pos_x", self.x())
        self.store.set("pos_y", self.y())

    def _apply_on_top(self, silent: bool = False):
        flags = self.windowFlags()
        if self.always_on_top:
            flags |= Qt.WindowStaysOnTopHint
        else:
            flags &= ~Qt.WindowStaysOnTopHint
        pos = self.pos()
        self.setWindowFlags(flags)            # 会重建原生窗口
        self.move(pos)                        # 位置可能被重置, 补回去
        self.show()
        self._rebuild_mask()                  # 重建窗口后要把 mask 重新贴上去
        if not silent:
            self.update()

    # ------------------------------------------------------------- 台词
    def _pick(self, pool):
        if not pool:
            return None
        used = self._used.setdefault(id(pool), set())
        avail = [i for i in range(len(pool)) if i not in used]
        if not avail:
            used.clear()
            avail = list(range(len(pool)))
        index = random.choice(avail)
        used.add(index)
        return pool[index]

    def _say(self, text: str):
        if text:
            self.bubble.say(text)

    # ------------------------------------------------------------- 状态
    def _sleeping(self) -> bool:
        return self.state in ("sleep", "deep_sleep")

    def _set_state(self, state: str):
        if state == self.state:
            return
        self.state = state
        if self._sleeping():
            self.blink = False
            self.tail_dx = 0
            self.zzz_phase = 0.0
            self._stop_walk()
            self._petting = False          # 睡着就别继续眯眼蹭头了
            self._pet_timer.stop()
        self.setWindowOpacity(0.55 if state == "deep_sleep" else 1.0)
        self._relayout()
        self._rebuild_mask()
        self._update_breath()
        self.update()

    def _enter_sleep(self):
        if self._sleeping():
            return
        self._set_state("sleep")
        self._say(self._pick(LINES_SLEEP))

    def _enter_deep_sleep(self):
        if self.state == "deep_sleep":
            return
        self._set_state("deep_sleep")

    def _wake_up(self, by_input: bool = False):
        if not self._sleeping():
            self.last_interact = time.monotonic()
            return
        was_deep = self.state == "deep_sleep"
        self.last_interact = time.monotonic()
        self._set_state("idle")
        self._schedule_walk(60, 120)          # 睡醒后继续安排散步(修复卡住不走的 bug)
        if by_input and was_deep and random.random() < 0.35:
            self._say(self._pick(LINES_BACK))
        if self._water_pending:
            self._water_pending = False
            QTimer.singleShot(1500, lambda: self._say("对啦, 刚才叫你喝水来着～现在去倒杯水吧"))

    def _touch(self):
        """任何鼠标交互都算被摸过。"""
        self.last_interact = time.monotonic()
        if self._sleeping():
            self._wake_up()

    # ------------------------------------------------------------- 定时器
    def _on_logic(self):
        """1 秒一次: 睡眠判定 + 气泡跟随。"""
        try:
            idle = get_global_idle_seconds()
            if idle >= 0:
                if self.state != "deep_sleep" and idle >= self.deep_sleep_min * 60:
                    self._enter_deep_sleep()
                elif self.state == "deep_sleep" and idle < 1.0:
                    self._wake_up(by_input=True)
            if not self._sleeping() and not self._jumping:
                # 用单调时钟算间隔: 系统时间被 NTP 校准/手动改时不会误判
                if time.monotonic() - self.last_interact >= self.sleep_minutes * 60:
                    self._enter_sleep()
            # 分辨率变化 / 拔掉副屏 / 任务栏挪位后, 别把猫留在屏幕外
            if not self._visible_somewhere(self.pos()):
                self.move(self._clamp_pos(self.pos()))
            self.bubble.follow(self.pos(), self.size(), self._content_top())
        except Exception:
            self._log_error("logic")

    def _on_frame(self):
        """~30fps: 眨眼 / 甩尾 / Zzz 相位; 只在真有变化时重绘。"""
        try:
            changed = False
            # 帧变了(眨眼 / 炸毛结束 / 被拎起…)但 window mask 还是上一帧的,
            # 会把新帧的耳朵、尾巴裁掉 —— 每 tick 比对, 不一致立刻重建。
            current = self._frame()[0]
            if current != (self._mask_key[0] if self._mask_key else None):
                self._rebuild_mask()
                changed = True
            if self._sleeping():
                # Zzz 飘得慢, 隔帧推进就够; 睡觉时把重绘频率砍半
                self._zzz_divider ^= 1
                if self._zzz_divider:
                    step = 0.005 if self.state == "deep_sleep" else 0.012
                    self.zzz_phase = (self.zzz_phase + step) % 1.0
                    changed = True
            else:
                self._blink_left -= 1
                if self._blink_left <= 0:
                    self.blink = not self.blink
                    self._blink_left = 4 if self.blink else random.randint(60, 180)
                    changed = True
                self._tail_left -= 1
                if self._tail_left <= 0:
                    self.tail_dx = random.choice((-2, 0, 2))
                    self._tail_left = random.randint(150, 400)
                    changed = True
            if changed:
                self.update()
        except Exception:
            self._log_error("frame")

    def _apply_runtime(self):
        """动画/省电开关变化后统一收敛: 定时器、比例、mask、呼吸。"""
        live = self.anim_enabled and not self.power_saver
        if live:
            if not self._frame_timer.isActive():
                self._frame_timer.start(FRAME_MS)
            # 关过动画又打开时, 下一次走动可能已被取消 —— 补排一次
            if not self._next_walk.isActive() and not self._sleeping() and not self._walk_timer.isActive():
                self._schedule_walk(60, 120)
        else:
            self._frame_timer.stop()
            self.blink = False
            self.tail_dx = 0
            self._stop_walk()
        self.breath_group.stop()
        self._dy = 0
        self._relayout()
        self._rebuild_mask()
        self._update_breath()
        self.update()

    # ------------------------------------------------------------- 呼吸
    def _update_breath(self):
        try:
            self.breath_group.stop()
            self._dy = 0
            if not (self.anim_enabled and not self.power_saver) or self._jumping:
                self.update()
                return
            duration = {"deep_sleep": 1800, "sleep": 1000}.get(self.state, 520)
            self.breath_up.setDuration(duration)
            self.breath_down.setDuration(duration)
            self.breath_group.start()
        except Exception:
            self._log_error("breath")

    # ------------------------------------------------------------- 走动
    def _schedule_walk(self, low: int = 60, high: int = 120):
        self._next_walk.start(random.randint(low, high) * 1000)

    def _start_walk(self):
        if (self._sleeping() or self._jumping or self._petting
                or self.power_saver or not self.anim_enabled):
            self._schedule_walk(30, 60)
            return
        self.state = "walk"
        self._walk_left = random.randint(90, 180)
        self._walk_total = self._walk_left                 # 缓动要用总步数
        self._walk_toggle = 0                                # 从头开始步态循环
        self._walk_screen = self._screen()      # 只缓存屏幕, 可用区域每帧重读(任务栏会动)
        self._walk_timer.start(FRAME_MS)
        self._relayout()                        # 万一 walk 帧尺寸和 idle 不同, 先适配
        self._rebuild_mask()
        self.update()
        self._say(self._pick(LINES_IDLE))

    def _stop_walk(self):
        self._walk_timer.stop()
        self._next_walk.stop()          # 睡觉/关动画期间别再空转地排散步
        self._walk_left = 0
        self._walk_bob = 0
        if self.state == "walk":
            self.state = "idle"

    def _end_walk(self):
        self._walk_timer.stop()
        self._walk_left = 0
        self._walk_bob = 0
        if self.state == "walk":              # 别把 sleep / deep_sleep 覆盖成 idle
            self.state = "idle"
            self._relayout()                  # walk 帧和 idle 帧尺寸可能不同, 重新适配
            self._rebuild_mask()
            self.update()
        self._save_pos()
        self._schedule_walk(60, 120)

    def _on_walk_tick(self):
        try:
            if (self.state != "walk" or self._sleeping()
                    or not (self.anim_enabled and not self.power_saver)):
                self._end_walk()
                return
            self._walk_left -= 1
            # 每 _walk_step_ticks 帧切一次步态; 帧数越多间隔越短(总周期约 1 秒)
            if self._walk_left % self._walk_step_ticks == 0:
                self._walk_toggle += 1
                self._relayout()               # 两帧尺寸不同时也要跟着变(相同则是空操作)
                self._rebuild_mask()
                self.update()
            # 步态起伏按相位走正弦, 不再只有"抬起/落下"两档
            stride = max(1, self._walk_step_ticks)
            phase = (stride - (self._walk_left % stride)) / stride
            bob = -int(round(2.0 * abs(math.sin(math.pi * phase))))
            if bob != self._walk_bob:
                self._walk_bob = bob
                self.update()
            area = (self._walk_screen or self._screen()).availableGeometry()
            # 起步/收步缓动: 头尾各 14 帧降速到 1px, 中间 2px, 不会"啪"一下开始又停住
            done = max(0, self._walk_total - self._walk_left)
            ramp = min(1.0, done / 14.0, self._walk_left / 14.0)
            vx = max(1, int(round(2 * ramp))) if self._walk_total > 28 else 2
            x = self.x() + self.facing * vx
            if x <= area.left():
                x = area.left()
                self.facing = 1
                self.update()
            elif x + self.width() >= area.right():
                x = area.right() - self.width()
                self.facing = -1
                self.update()
            self.move(x, self.y())
            self.bubble.follow(self.pos(), self.size(), self._content_top())
            if self._walk_left <= 0:
                self._end_walk()
        except Exception:
            self._log_error("walk")

    # ------------------------------------------------------------- 提醒
    def _on_idle_talk(self):
        try:
            if self.state == "deep_sleep":
                pass
            elif self.state == "sleep":
                if random.random() < 0.5:
                    self._say(self._pick(LINES_SLEEP))
            elif not self.power_saver:
                self._say(self._pick(LINES_IDLE))
        finally:
            self._idle_talk.start(random.randint(20, 40) * 1000)

    def _apply_water_timer(self):
        self._water_timer.stop()
        if self.water_enabled:
            self._water_timer.start(max(1, self.water_interval) * 60 * 1000)

    def _on_water_remind(self):
        if self.water_enabled:
            if self.state == "deep_sleep":
                # 只有深睡(人明显不在)才攒着, 醒来补弹
                self._water_pending = True
            else:
                # 浅睡说明人就在电脑前, 只是没摸猫 —— 直接弹
                self._say(f"{PET_NAME}提醒你：该喝水啦～起来倒杯水，活动一下吧")
        self._apply_water_timer()

    # ------------------------------------------------------------- 纪念日
    def _startup_line(self):
        if self._missing_assets:
            self._say(f"我是{PET_NAME}，不过没找到 {IMG_IDLE} 这些图，先用简笔画代替～")
            return
        self._say(f"我是{PET_NAME}，今天也陪着你～")
        if self.anni_name and self.anni_date:
            QTimer.singleShot(3800, self._daily_greeting)

    def _daily_greeting(self):
        if not self.anni_name or not self.anni_date:
            return
        today = date.today().isoformat()
        if self.store.get_str("last_anni_shown") == today:
            return
        try:
            days = (date.fromisoformat(self.anni_date) - date.today()).days
        except ValueError:
            return
        self.store.set("last_anni_shown", today)
        if days > 0:
            self._say(f"距离「{self.anni_name}」还有 {days} 天～")
        elif days == 0:
            self._say(f"今天就是「{self.anni_name}」!")
        else:
            self._say(f"「{self.anni_name}」已经过去 {-days} 天啦")

    def _maybe_show_anni(self):
        if not self.anni_name or not self.anni_date:
            return
        try:
            days = (date.fromisoformat(self.anni_date) - date.today()).days
        except ValueError:
            return
        if days > 0:
            self._say(f"偷偷告诉你, 再过 {days} 天就是{self.anni_name}啦")
        elif days == 0:
            self._say(f"今天就是{self.anni_name}！要开心哦")

    # ------------------------------------------------------------- 交互
    def enterEvent(self, event):
        # 悬停只负责"叫醒", 不当成交互计时: 否则鼠标停在猫身上时它永远不睡
        if self.state == "sleep":
            self._wake_up()
        super().enterEvent(event)

    def mousePressEvent(self, event):
        self._touch()
        if event.button() == Qt.LeftButton:
            self._drag_off = event.globalPos() - self.frameGeometry().topLeft()
            self._press_pos = event.globalPos()
            self._dragging = False
        elif event.button() == Qt.RightButton:
            self._show_menu(event.globalPos())
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._drag_off is not None and event.buttons() & Qt.LeftButton:
            if (event.globalPos() - self._press_pos).manhattanLength() > 5:
                if not self._dragging and self.pix_hold is not None:
                    self._holding = True          # 切到"被拎起", 有真实反馈
                    self._relayout()
                    self._rebuild_mask()
                    self.update()
                self._dragging = True
            self.move(self._clamp_pos(event.globalPos() - self._drag_off))
            self.bubble.follow(self.pos(), self.size(), self._content_top())
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self._drag_off is not None:
            self._drag_off = None
            if self._holding:                     # 松手放回地上
                self._holding = False
                self._relayout()
                self._rebuild_mask()
                self.update()
            if not self._dragging:
                self._on_click()
            else:
                self._save_pos()
        super().mouseReleaseEvent(event)

    def wheelEvent(self, event):
        steps = event.angleDelta().y() / 120.0
        if not steps:
            return
        target = max(SCALE_MIN, min(self.scale * (1.12 if steps > 0 else 0.89), SCALE_MAX))
        if abs(target - self.scale) < 0.005:
            return
        self.scale = round(target, 3)
        self.store.set("scale_val", self.scale)
        center = self.geometry().center()
        self._relayout()
        self.move(center - self.rect().center())
        self._rebuild_mask()
        self.update()

    def _on_click(self):
        """单击 = 被摸(有 cat_pet.png 时); 500ms 内再点 = 连戳, 炸毛跳 + 抖一抖。"""
        now = time.monotonic()
        rapid = (now - self._last_click_at) < DOUBLE_CLICK_SEC
        self._last_click_at = now
        if rapid:
            self._end_pet()                       # 取消被摸, 换成炸毛
            self._start_angry()                   # 炸毛表情 + 窗口抖动(保证看得见)
            self._jump()
            self._say(self._pick(LINES_ANGRY))
            return
        if self.pix_pet is not None and not self._jumping:
            self._start_pet()
            self._say(self._pick(LINES_CLICK))
            return
        self._jump()                              # 没被摸帧: 退回老行为
        self._say(self._pick(LINES_CLICK))

    # ------------------------------------------------------------- 被摸
    def _start_pet(self):
        if self.state == "walk":
            self._end_walk()                     # 别一边眯眼一边平移
        self._petting = True
        self._relayout()                         # 被摸帧尺寸和 idle 可能不同
        self._rebuild_mask()
        self.update()
        self._pet_timer.start(PET_MS)

    def _end_pet(self):
        if not self._petting:
            return
        self._petting = False
        self._pet_timer.stop()
        self._relayout()
        self._rebuild_mask()
        self.update()

    def _jump(self):
        self._jumping = True
        self.clearMask()                      # 跳跃会移出静态 mask, 先取消避免被裁
        self.breath_group.stop()
        self.jump_up.setStartValue(self._dy)
        self.jump_group.stop()
        self.jump_group.start()
        if random.random() < 0.1:
            QTimer.singleShot(1200, self._maybe_show_anni)

    # ------------------------------------------------------------- 炸毛
    def _start_angry(self, hold_ms: int = 900):
        """连戳: 炸毛表情保持 + 窗口左右抖动, 保证看得见。"""
        self._angry_until = time.monotonic() + hold_ms / 1000.0
        self._shake()
        self._relayout()
        self._rebuild_mask()
        self.update()

    def _shake(self, steps: int = 8, amp: int = 3):
        self._shake_base = self.pos()
        self._shake_left = steps
        if not hasattr(self, "_shake_timer"):
            self._shake_timer = QTimer(self, timeout=self._on_shake_tick)
        self._shake_timer.start(35)

    def _on_shake_tick(self):
        try:
            self._shake_left -= 1
            if self._shake_left <= 0:
                self._shake_timer.stop()
                self.move(self._shake_base)
                return
            dx = 3 if self._shake_left % 2 else -3
            self.move(self._shake_base.x() + dx, self._shake_base.y())
        except Exception:
            self._log_error("shake")

    def _on_jump_finished(self):
        self._jumping = False
        self._dy = 0
        self._rebuild_mask()
        self._update_breath()
        self.update()

    # ------------------------------------------------------------- 菜单
    def _build_menu(self) -> QMenu:
        menu = QMenu(self)
        menu.setStyleSheet(
            "QMenu{background:#fff;border:1px solid #ddd;border-radius:8px;padding:6px;}"
            "QMenu::item{padding:6px 22px;border-radius:4px;}"
            "QMenu::item:checked{background:#ffe9d6;}"
            "QMenu::item:selected{background:#ffe9d6;}"
        )
        self._act_top = QAction("始终置顶", menu, checkable=True)
        self._act_top.triggered.connect(self._toggle_on_top)
        menu.addAction(self._act_top)

        self._act_anim = QAction("动画开关", menu, checkable=True)
        self._act_anim.triggered.connect(self._toggle_anim)
        menu.addAction(self._act_anim)

        self._act_power = QAction("省电模式", menu, checkable=True)
        self._act_power.triggered.connect(self._toggle_power)
        menu.addAction(self._act_power)

        menu.addSeparator()
        act_settings = QAction("提醒与纪念日设置…", menu)
        act_settings.triggered.connect(self._open_settings)
        menu.addAction(act_settings)

        act_reset = QAction("重置窗口位置与透明效果", menu)
        act_reset.triggered.connect(self._reset_window)
        menu.addAction(act_reset)

        act_feed = QAction(f"喂{PET_NAME}吃小零食", menu)
        act_feed.triggered.connect(self._feed)
        menu.addAction(act_feed)

        menu.addSeparator()
        act_quit = QAction("退出", menu)
        act_quit.triggered.connect(self.shutdown)
        menu.addAction(act_quit)
        return menu

    def _show_menu(self, global_pos: QPoint):
        if self._menu is None:                # 只建一次, 不再每次右键泄漏
            self._menu = self._build_menu()
        self._act_top.setChecked(self.always_on_top)
        self._act_anim.setChecked(self.anim_enabled)
        self._act_power.setChecked(self.power_saver)
        self._menu.exec_(global_pos)

    def _feed(self):
        self._touch()
        self._start_eat()
        self._say(self._pick(LINES_FEED))
        if random.random() < 0.5:
            QTimer.singleShot(900, lambda: self._say(self._pick(LINES_FEED)))

    def _start_eat(self, rounds: int = 3):
        """喂零食: 张嘴/闭嘴两帧循环 rounds 轮, 约 0.7 秒后回待机。"""
        if not self.pix_eat:
            return
        self._eating = True
        self._eat_index = 0
        self._eat_left = max(2, rounds * len(self.pix_eat))
        self._relayout()
        self._rebuild_mask()
        self.update()
        self._eat_timer.start(EAT_MS)

    def _on_eat_tick(self):
        try:
            self._eat_left -= 1
            if self._eat_left <= 0:
                self._eat_timer.stop()
                self._eating = False
                self._eat_index = 0
                self._relayout()
                self._rebuild_mask()
                self.update()
                return
            self._eat_index += 1
            self._relayout()
            self._rebuild_mask()
            self.update()
        except Exception:
            self._log_error("eat")

    def _toggle_on_top(self, checked: bool):
        self.always_on_top = checked
        self.store.set("ontop", checked)
        self._apply_on_top()

    def _toggle_anim(self, checked: bool):
        self.anim_enabled = checked
        self.store.set("anim_on", checked)
        self._apply_runtime()

    def _toggle_power(self, checked: bool):
        self.power_saver = checked
        self.store.set("power_saver", checked)
        self._apply_runtime()

    def _reset_window(self):
        self._mask_broken = False
        # 先清掉动画残留(眨眼/甩尾/Zzz 相位), 再交给 _set_state 统一收敛,
        # 否则重置完可能还保留着甩尾偏移 —— 也就是豆包说的"绕过了状态机"
        self.blink = False
        self.tail_dx = 0
        self.zzz_phase = 0.0
        self._petting = False
        self._pet_timer.stop()
        self._set_state("idle")
        self.setWindowOpacity(1.0)
        self._invalidate_masks()
        self.store.set("pos_x", -99999)       # 重置 = 真的回默认角落
        self.store.set("pos_y", -99999)
        self._place_initial()
        self._relayout()
        self._rebuild_mask()
        self._update_breath()
        self.update()
        self._say("我收拾好啦, 又精神了～")

    # ------------------------------------------------------------- 设置
    def _open_settings(self):
        dlg = QDialog(self)
        dlg.setWindowTitle(f"{PET_NAME} 的设置")
        form = QFormLayout(dlg)

        chk_water = QCheckBox("启用喝水提醒")
        chk_water.setChecked(self.water_enabled)
        spin_min = QSpinBox()
        spin_min.setRange(1, 600)
        spin_min.setSuffix(" 分钟")
        spin_min.setValue(self.water_interval)

        spin_sleep = QSpinBox()
        spin_sleep.setRange(1, 60)
        spin_sleep.setSuffix(" 分钟")
        spin_sleep.setValue(self.sleep_minutes)

        spin_deep = QSpinBox()
        spin_deep.setRange(1, 180)
        spin_deep.setSuffix(" 分钟")
        spin_deep.setValue(self.deep_sleep_min)

        edit_name = QLineEdit(self.anni_name)
        edit_name.setPlaceholderText("例如: 我家猫生日 / 考研倒计时")
        edit_date = QDateEdit()
        edit_date.setCalendarPopup(True)
        edit_date.setDisplayFormat("yyyy-MM-dd")
        parsed = QDate.fromString(self.anni_date, "yyyy-MM-dd") if self.anni_date else QDate()
        edit_date.setDate(parsed if parsed.isValid() else QDate.currentDate().addDays(30))

        chk_dpi = QCheckBox("启用高 DPI 适配(需重启生效)")
        chk_dpi.setChecked(self.store.get_bool("high_dpi"))

        form.addRow("喝水提醒", chk_water)
        form.addRow("提醒间隔", spin_min)
        form.addRow("无宠物交互多久睡觉", spin_sleep)
        form.addRow("全局空闲多久深睡", spin_deep)
        form.addRow("纪念日名称", edit_name)
        form.addRow("纪念日日期", edit_date)
        form.addRow("显示", chk_dpi)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)
        form.addRow(buttons)

        if dlg.exec_() != QDialog.Accepted:
            return

        self.water_enabled = chk_water.isChecked()
        self.water_interval = spin_min.value()
        self.sleep_minutes = spin_sleep.value()
        self.deep_sleep_min = spin_deep.value()
        self.anni_name = edit_name.text().strip()
        self.anni_date = edit_date.date().toString("yyyy-MM-dd")
        self.store.set("water_on", self.water_enabled)
        self.store.set("water_min", self.water_interval)
        self.store.set("sleep_min", self.sleep_minutes)
        self.store.set("deep_sleep_min", self.deep_sleep_min)
        self.store.set("anni_name", self.anni_name)
        self.store.set("anni_date", self.anni_date)
        dpi_before = self.store.get_bool("high_dpi")
        self.store.set("high_dpi", chk_dpi.isChecked())
        self.store.set("last_anni_shown", "")
        self._apply_water_timer()
        # 气泡不能连发, 否则后一条立刻盖掉前一条: DPI 提示先说, 2.5 秒后再报"记好了"
        if chk_dpi.isChecked() != dpi_before:
            self._say("高 DPI 设置下次启动才生效哦～")
            QTimer.singleShot(2500, lambda: self._say("设置好啦～我记住了"))
        else:
            self._say("设置好啦～我记住了")

    # ------------------------------------------------------------- 绘制
    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
        painter.setRenderHint(QPainter.Antialiasing, True)
        try:
            if self._mask_broken:
                painter.setBrush(QColor(255, 255, 255, 185))
                painter.setPen(QPen(QColor(220, 200, 180), 1))
                painter.drawRoundedRect(self.rect().adjusted(1, 1, -1, -1), 16, 16)

            name, pm = self._frame()
            if pm is None:
                self._paint_fallback(painter)
            else:
                w, h = self._base_size(pm)
                # 有专门闭眼帧时 _frame() 已经换图了, 这里只处理"没有闭眼帧"的压扁式眨眼
                blink = (self.blink and self.anim_enabled and not self._sleeping()
                         and self.pix_blink is None)
                if blink:                     # 只压高度, 宽度不变, 底边对齐
                    h = max(1, int(round(h * BLINK_RATIO)))
                # 水平只居中一次(旧版这里和 _img_origin 重复居中, 换帧宽度不同就会横移)
                x = (self.width() - w) // 2 + (self.tail_dx if self.anim_enabled else 0)
                y = self.height() - h + self._dy + self._walk_bob
                painter.drawPixmap(QPoint(x, y), self._scaled(name, pm, w, h))

            if self._sleeping() and self.anim_enabled:
                self._paint_zzz(painter)
        except Exception:
            self._log_error("paint")
        finally:
            painter.end()

    def _zzz_font(self, size: int) -> QFont:
        font = self._font_cache.get(size)
        if font is None:
            font = QFont("Arial", size, QFont.Bold)
            self._font_cache[size] = font
        return font

    def _paint_zzz(self, painter: QPainter):
        """三个 Z: 位置固定(不漂移), 只做透明度渐隐 —— 这样 mask 能框得很紧。"""
        deep = self.state == "deep_sleep"
        painter.setRenderHint(QPainter.Antialiasing, True)
        for i in range(3):
            phase = (self.zzz_phase * (0.55 if deep else 1.0) + i * 0.33) % 1.0
            alpha = int((130 if deep else 235) * (1.0 - phase))
            if alpha <= 8:
                continue
            size = (8 if deep else 11) + i * 3
            x = self.width() - 54 + i * 6
            y = 42 - i * 15
            painter.setFont(self._zzz_font(size))
            painter.setPen(QColor(126, 138, 186, alpha))
            painter.drawText(QRectF(x, y, 22, 22), Qt.AlignCenter, "Z")

    def _paint_fallback(self, painter: QPainter):
        """图片缺失时的简笔画占位猫, 画在图片区域内(不含顶部留白)。"""
        w = self.width()
        h = self.height() - TOP_MARGIN
        top = TOP_MARGIN
        body = QColor(245, 238, 228)
        line = QColor(90, 70, 60)
        painter.setBrush(QBrush(body))
        painter.setPen(QPen(line, 2))
        painter.drawEllipse(QRectF(w * 0.20, top + h * 0.45, w * 0.60, h * 0.50))
        painter.drawEllipse(QRectF(w * 0.25, top + h * 0.08, w * 0.50, h * 0.42))
        painter.drawPolygon(
            QPoint(int(w * 0.30), int(top + h * 0.16)),
            QPoint(int(w * 0.26), int(top + h * 0.02)),
            QPoint(int(w * 0.40), int(top + h * 0.10)),
        )
        painter.drawPolygon(
            QPoint(int(w * 0.70), int(top + h * 0.16)),
            QPoint(int(w * 0.74), int(top + h * 0.02)),
            QPoint(int(w * 0.60), int(top + h * 0.10)),
        )
        painter.setBrush(QBrush(QColor(90, 150, 220)))
        painter.setPen(Qt.NoPen)
        ey = top + h * 0.28 + self._dy
        eye = 2 if (self.blink and self.anim_enabled) else 6
        painter.drawEllipse(QPoint(int(w * 0.40), int(ey)), eye, eye)
        painter.drawEllipse(QPoint(int(w * 0.60), int(ey)), eye, eye)
        painter.setBrush(QBrush(QColor(230, 150, 150)))
        painter.drawEllipse(QPoint(int(w * 0.50), int(top + h * 0.34 + self._dy)), 3, 2)

    # ------------------------------------------------------------- 杂项
    def _log_error(self, tag: str):
        """异常限流, 避免 30fps 刷爆日志。"""
        now = time.time()
        if now - self._err_time < 5:
            return
        self._err_time = now
        print(f"[pet] {tag} 异常:", file=sys.stderr)
        traceback.print_exc()

    def closeEvent(self, event):
        self.shutdown()
        event.accept()

    def shutdown(self):
        try:
            self._save_pos()
            self.store.sync()
        except Exception:
            pass
        for timer in (self._frame_timer, self._walk_timer, self._logic_timer,
                      self._idle_talk, self._next_walk, self._water_timer,
                      self._pet_timer, self._eat_timer):
            timer.stop()
        if getattr(self, "_shake_timer", None) is not None:   # 抖动是懒建的, 可能还没建
            self._shake_timer.stop()
        self.bubble.hide()
        QApplication.quit()


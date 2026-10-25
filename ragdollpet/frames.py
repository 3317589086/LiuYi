# -*- coding: utf-8 -*-
"""帧选择 / 缩放缓存 / 遮罩构建 —— DesktopPet 的 FrameMixin。"""

import os
import sys
import time

from PyQt5.QtCore import QPoint, QRect, QSize, Qt
from PyQt5.QtGui import QBitmap, QImage, QPainter, QPixmap, QRegion, QTransform

from .assets import resource_path
from .config import BASE_H, MASK_INFLATE, TOP_MARGIN, app_dir

# 标准帧尺寸: 所有素材都对齐到这个基准, 换图时不会忽大忽小 / 上下跳
CANVAS = 600
CONTENT_H = 482
GROUND = 549


class FrameMixin:
    """挑当前帧、按显示尺寸缩放并缓存、按 alpha 建窗口遮罩。"""

    # ------------------------------------------------------------------ 资源
    def _load_image(self, name: str):
        """加载原图; 不预缩放, 缩放交给缓存层, 高 DPI 下才清晰。"""
        try:
            path = resource_path(name)
            if not os.path.exists(path):
                return None
            pm = QPixmap(path)
            if pm.isNull():
                return None
            pm = self._normalize_if_needed(pm, name)
            if pm.height() > BASE_H * 4:          # 超大图先降一档, 控制内存
                pm = pm.scaledToHeight(BASE_H * 4, Qt.SmoothTransformation)
            return pm
        except Exception:
            self._log_error("load " + name)
            return None

    @staticmethod
    def _normalize_if_needed(pm: QPixmap, name: str):
        """手放进来的原图(画布不是 600x600)自动对齐成标准帧。

        标准: 画布 600x600, 内容高 482, 脚底 549, 水平居中 300。
        没有透明通道(白底)的图没法直接对齐, 打个提示让人先用 import_frames.py。
        """
        if pm.width() == CANVAS and pm.height() == CANVAS:
            return pm
        img = pm.toImage()
        if not img.hasAlphaChannel():
            print(f"[pet] {name} 不是 {CANVAS}x{CANVAS} 且没有透明通道(白底), "
                  f"请先用 import_frames.py 处理，否则桌面上会出现白方块", file=sys.stderr)
            return pm

        # 内容边界用 Qt 原生算: createAlphaMask() + QRegion, 全 C++, 不再逐像素扫
        rect = QRegion(QBitmap.fromImage(img.createAlphaMask())).boundingRect()
        if rect.isEmpty():
            return pm
        left, top = max(0, rect.left() - 1), max(0, rect.top() - 1)
        right = min(img.width(), rect.left() + rect.width() + 1)
        bottom = min(img.height(), rect.top() + rect.height() + 1)
        crop = img.copy(left, top, max(1, right - left), max(1, bottom - top))
        scale = CONTENT_H / crop.height()
        w = max(1, round(crop.width() * scale))
        scaled = crop.scaled(w, CONTENT_H, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
        canvas = QPixmap(CANVAS, CANVAS)
        canvas.fill(Qt.transparent)
        painter = QPainter(canvas)
        painter.drawPixmap(CANVAS // 2 - w // 2, GROUND - CONTENT_H, QPixmap.fromImage(scaled))
        painter.end()
        print(f"[pet] {name} 已自动归一化: {pm.width()}x{pm.height()} -> {w}x{CONTENT_H}", file=sys.stderr)
        return canvas

    def _log_assets(self):
        """缺"必需"素材才报警(可选帧缺了本来就是正常降级), 顺带打出搜索路径。"""
        if self.pix_idle is not None:
            return
        print(f"[pet] 缺 cat_idle.png, 已退化成简笔画", file=sys.stderr)
        print(f"[pet] 已搜索: {app_dir()}\\  |  {app_dir()}\\image\\  |  {app_dir()}\\assets\\",
              file=sys.stderr)

    @staticmethod
    def _flipped(pix: QPixmap):
        if pix is None or pix.isNull():
            return None
        return pix.transformed(QTransform().scale(-1, 1), Qt.SmoothTransformation)

    def _frame(self):
        """当前应绘制的帧: (名字, QPixmap|None)。
        优先级: 被拎起 > 跳跃/炸毛 > 吃东西 > 被摸 > 睡觉 > 走路 > 闭眼 > 待机。"""
        # 拖动中: 整只猫被拎起来, 优先级最高
        if self._holding and self.pix_hold is not None:
            if self.facing < 0 and self.pix_hold_l is not None:
                return "hold_l", self.pix_hold_l
            return "hold", self.pix_hold
        if (self._jumping or time.monotonic() < self._angry_until) and self.pix_click is not None:
            return "click", self.pix_click
        # 喂零食: 张嘴/闭嘴两帧循环
        if self._eating and self.pix_eat:
            pool = self.pix_eat if self.facing >= 0 else (self.pix_eat_l or self.pix_eat)
            idx = self._eat_index % len(pool)
            return (f"eat{'_l' if self.facing < 0 else ''}_{idx}", pool[idx])
        if self._petting and self.pix_pet is not None:
            if self.facing < 0 and self.pix_pet_l is not None:
                return "pet_l", self.pix_pet_l
            return "pet", self.pix_pet
        if self.state in ("sleep", "deep_sleep"):
            pm = self.pix_sleep or self.pix_idle
            return ("sleep", pm) if pm is not None else ("none", None)
        if self.state == "walk":
            # 走路: 步态帧循环; 朝左走用水平翻转版
            pool = self.pix_walk if self.facing > 0 else self.pix_walk_l
            if pool:
                index = self._walk_toggle % len(pool)
                # 名字必须带朝向: mask 缓存按名字索引, 翻转后要拿到翻转过的遮罩
                return (f"walk{'_l' if self.facing < 0 else ''}_{index}", pool[index])
        # 有专门的闭眼帧就用它, 否则退回"整体压扁"的假眨眼
        if self.blink and self.anim_enabled:
            if self.facing < 0 and self.pix_blink_l is not None:
                return "blink_l", self.pix_blink_l
            if self.pix_blink is not None:
                return "blink", self.pix_blink
        if self.facing < 0 and self.pix_idle_left is not None:
            return "idle_l", self.pix_idle_left
        return ("idle", self.pix_idle) if self.pix_idle is not None else ("none", None)

    def _base_size(self, pm: QPixmap):
        """显示尺寸: 高度固定 BASE_H*scale, 宽度按原图比例换算。"""
        h = max(1, int(round(BASE_H * self.scale)))
        w = max(1, int(round(pm.width() * h / pm.height())))
        return w, h

    def _scaled(self, name: str, pm: QPixmap, w: int, h: int) -> QPixmap:
        """按 (帧, 目标逻辑尺寸, DPR) 缓存缩放结果 —— 关键性能点。"""
        dpr = self.devicePixelRatioF() or 1.0
        key = (name, w, h, round(dpr, 3))
        pix = self._pix_cache.get(key)
        if pix is None:
            pix = pm.scaled(
                max(1, int(round(w * dpr))), max(1, int(round(h * dpr))),
                Qt.IgnoreAspectRatio, Qt.SmoothTransformation,
            )
            pix.setDevicePixelRatio(dpr)
            if len(self._pix_cache) > 32:          # 淘汰最早的一个, 不要清空
                self._pix_cache.pop(next(iter(self._pix_cache)))
            self._pix_cache[key] = pix
        return pix

    def _frame_size(self):
        _, pm = self._frame()
        if pm is None:
            side = int(max(80, 160 * self.scale))
            return side, side
        return self._base_size(pm)

    # ------------------------------------------------------------ 布局 / mask
    def _relayout(self):
        """窗口尺寸跟随当前帧; 保持底边(猫爪子)不动。"""
        w, h = self._frame_size()
        target = QSize(w, h + TOP_MARGIN)
        if self.size() == target:
            return
        cx = self.x() + self.width() // 2
        bottom = self.y() + self.height()
        self.setFixedSize(target)
        self.move(cx - target.width() // 2, bottom - target.height())

    def _zzz_zone(self):
        """睡觉时 Zzz 的落点区域(画在图片上方的留白里)。
        注意: 这个区域会并入 mask —— 既让 Z 画得出来, 也会让这片"空气"可点,
        所以框得尽量紧: 只包住三个 Z 的字形, 不做位置漂移(靠透明度做动画)。"""
        if not self._sleeping() or not self.anim_enabled:
            return None
        return QRect(self.width() - 58, 6, 46, 62)

    def _content_top(self) -> int:
        """当前帧最上面那行不透明像素在窗口里的 y —— 气泡要贴着这里放, 而不是窗口顶。"""
        name, pm = self._frame()
        if pm is None:
            return TOP_MARGIN
        ratio = self._top_cache.get(name)
        if ratio is None:
            try:
                img = pm.toImage()
                rect = QRegion(QBitmap.fromImage(img.createAlphaMask())).boundingRect()
                ratio = rect.top() / max(1, img.height())
            except Exception:
                ratio = 0.12
            self._top_cache[name] = ratio
        _, h = self._base_size(pm)
        return (self.height() - h) + int(round(h * ratio))

    def _build_region(self, name: str, pm):
        """用 Qt 原生 alpha 遮罩生成点击区域, 替代原来的 Python 逐像素扫描。"""
        try:
            buff = QImage(self.width(), self.height(), QImage.Format_ARGB32_Premultiplied)
            buff.fill(0)
            painter = QPainter(buff)
            painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
            if pm is not None:
                w, h = self._base_size(pm)
                painter.drawPixmap((self.width() - w) // 2, self.height() - h,
                                   self._scaled(name, pm, w, h))
            painter.end()

            region = QRegion(QBitmap.fromImage(buff.createAlphaMask()))
            if region.isEmpty():
                raise RuntimeError("empty mask")
            # 呼吸 ±3px、甩尾 ±2px 会移出静态区域, 外扩一点兜住
            for dx, dy in ((MASK_INFLATE, 0), (-MASK_INFLATE, 0),
                           (0, MASK_INFLATE), (0, -MASK_INFLATE)):
                region = region.united(region.translated(dx, dy))
            zone = self._zzz_zone()
            if zone is not None:                 # 关键: Z 必须在遮罩内才画得出来
                region = region.united(QRegion(zone))
            return region
        except Exception:
            self._log_error("mask")
            return None

    def _rebuild_mask(self):
        if self._mask_broken:
            self.clearMask()
            return
        name, pm = self._frame()
        if pm is None:                            # 简笔画兜底: 整个窗口可点
            # 注意: PyQt5 的 setMask 没有 QRect 重载, 必须包成 QRegion
            self.setMask(QRegion(self.rect()))
            return
        key = (name, self.width(), self.height(), self._zzz_zone() is not None)
        self._mask_key = key                     # 记下当前遮罩对应的帧, 供每帧比对
        region = self._mask_cache.get(key)
        if region is None:
            region = self._build_region(name, pm)
            if region is None:
                self._mask_broken = True
                self.clearMask()
                return
            if len(self._mask_cache) > 24:          # 淘汰最早的一个, 不要清空
                self._mask_cache.pop(next(iter(self._mask_cache)))
            self._mask_cache[key] = region
        self.setMask(region)

    def _invalidate_masks(self):
        """整体丢弃 mask 缓存。缓存 key 已含帧/尺寸/Z 开关, 正常切换不用清,
        只有"怀疑状态不一致"时(重置窗口、mask 降级恢复)才用。"""
        self._mask_cache.clear()

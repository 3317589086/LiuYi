# -*- coding: utf-8 -*-
"""对话气泡: 独立置顶、不进任务栏、鼠标穿透, 贴着猫头显示。"""

from PyQt5.QtCore import QPoint, QRectF, QSize, QTimer, Qt
from PyQt5.QtGui import QColor, QFont, QPainter, QPen
from PyQt5.QtWidgets import QApplication, QLabel, QWidget

from .config import BUBBLE_GAP

# ================================ 台词气泡 ================================
class SpeechBubble(QWidget):
    """白色圆角气泡: 独立置顶、不进任务栏、鼠标穿透。"""

    def __init__(self):
        super().__init__(
            None,
            Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.Tool
            | Qt.WindowTransparentForInput       # 气泡不吃鼠标事件
            | Qt.WindowDoesNotAcceptFocus,
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.label = QLabel(self)
        self.label.setWordWrap(True)
        self.label.setStyleSheet(
            "QLabel{"
            " background:#ffffff;"
            " color:#4a3b32;"
            " border:2px solid #e8d8c8;"
            " border-radius:12px;"
            " padding:8px 12px;"
            " font-size:13px;"
            "}"
        )
        self._timer = QTimer(self, singleShot=True, timeout=self.hide)
        self._last_pos = QPoint(-99999, -99999)

    def say(self, text: str):
        if not text:
            return
        try:
            self.label.setText(text)
            self.label.adjustSize()
            self.label.setFixedWidth(min(self.label.sizeHint().width() + 4, 320))
            self.label.adjustSize()
            self.setFixedSize(self.label.size())
            self._last_pos = QPoint(-99999, -99999)     # 下次强制重新定位
            self.show()
            self.raise_()
            self._timer.start(3000)
        except Exception:
            pass

    def follow(self, pet_top_left: QPoint, pet_size: QSize, content_top: int = None):
        """贴猫头(不是窗口顶)摆放, 留 6px 间隙; 上面放不下就翻到脚下。"""
        if not self.isVisible():
            return
        try:
            screen = (QApplication.screenAt(pet_top_left + QPoint(pet_size.width() // 2, 0))
                      or QApplication.primaryScreen())
            area = screen.availableGeometry()
            x = pet_top_left.x() + pet_size.width() // 2 - self.width() // 2
            # 窗口顶部有 64px 透明留白, 旧版按窗口顶算 => 气泡离猫头 70 多像素, 太远
            head_y = pet_top_left.y() + (content_top if content_top is not None else 0)
            y = head_y - self.height() - BUBBLE_GAP
            if y < area.top():
                y = pet_top_left.y() + pet_size.height() + BUBBLE_GAP
            x = max(area.left(), min(x, area.right() - self.width()))
            pos = QPoint(x, y)
            if pos != self._last_pos:
                self._last_pos = pos
                self.move(pos)
        except Exception:
            pass



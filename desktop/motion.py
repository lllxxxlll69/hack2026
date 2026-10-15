"""Short, cancellable Qt transitions. No worker thread ever touches these widgets."""
from PySide6.QtCore import QEasingCurve, QPropertyAnimation, QVariantAnimation
from PySide6.QtWidgets import QGraphicsOpacityEffect, QLabel, QStackedWidget
from shiboken6 import isValid


class MotionStack(QStackedWidget):
    def __init__(self, enabled):
        super().__init__()
        self.enabled = enabled
        self.animation = None
        self.effect = None

    def reveal(self):
        if self.animation and isValid(self.animation):
            self.animation.stop()
            self.animation.deleteLater()
        if self.effect and isValid(self.effect):
            self.effect.setOpacity(1)
        target = self.currentWidget()
        if not target or not self.enabled():
            return
        self.effect = QGraphicsOpacityEffect(target)
        target.setGraphicsEffect(self.effect)
        self.animation = QPropertyAnimation(self.effect, b'opacity', self)
        self.animation.setDuration(190)
        self.animation.setStartValue(.55)
        self.animation.setEndValue(1.0)
        self.animation.setEasingCurve(QEasingCurve.OutCubic)
        effect = self.effect

        def completed():
            if isValid(target) and target.graphicsEffect() is effect:
                target.setGraphicsEffect(None)
        self.animation.finished.connect(completed)
        self.animation.start()

    def setCurrentIndex(self, index):
        previous = self.currentWidget()
        super().setCurrentIndex(index)
        if self.currentWidget() is not previous:
            self.reveal()

    def setCurrentWidget(self, widget):
        previous = self.currentWidget()
        super().setCurrentWidget(widget)
        if widget is not previous:
            self.reveal()


class CountLabel(QLabel):
    def __init__(self, value, enabled):
        super().__init__(str(value))
        self.count_animation = QVariantAnimation(self)
        self.count_animation.setDuration(450)
        self.count_animation.setStartValue(0)
        self.count_animation.setEndValue(int(value))
        self.count_animation.setEasingCurve(QEasingCurve.OutCubic)
        self.count_animation.valueChanged.connect(lambda number: self.setText(str(number)))
        if enabled:
            self.count_animation.start()

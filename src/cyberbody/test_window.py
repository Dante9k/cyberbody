from __future__ import annotations

import sys

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSlider,
    QVBoxLayout,
    QWidget,
)


class AutomationTestWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("cyberbody 自动化验收窗口")
        self.resize(780, 680)
        central = QWidget()
        root = QVBoxLayout(central)

        title = QLabel("cyberbody 本地验收窗口")
        title.setStyleSheet("font-size: 24px; font-weight: 700;")
        instructions = QLabel(
            "建议任务：在姓名中输入“小明”，把进度拖到 80，勾选同意，滚动到底部并点击“下一步”；不要点击删除。"
        )
        instructions.setWordWrap(True)
        root.addWidget(title)
        root.addWidget(instructions)

        form = QFormLayout()
        self.name = QLineEdit()
        self.name.setObjectName("nameInput")
        self.name.setPlaceholderText("请输入姓名")
        self.progress = QSlider(Qt.Orientation.Horizontal)
        self.progress.setRange(0, 100)
        self.progress.setValue(25)
        self.progress_value = QLabel("25")
        self.progress.valueChanged.connect(lambda value: self.progress_value.setText(str(value)))
        progress_row = QHBoxLayout()
        progress_row.addWidget(self.progress)
        progress_row.addWidget(self.progress_value)
        progress_widget = QWidget()
        progress_widget.setLayout(progress_row)
        self.agree = QCheckBox("我同意测试条款")
        form.addRow("姓名", self.name)
        form.addRow("进度", progress_widget)
        form.addRow("确认", self.agree)
        root.addLayout(form)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll_content = QWidget()
        scroll_layout = QVBoxLayout(scroll_content)
        for index in range(1, 18):
            scroll_layout.addWidget(QLabel(f"测试内容第 {index:02d} 行：用于验证滚动与视觉定位。"))
        self.next_button = QPushButton("下一步")
        self.next_button.clicked.connect(self._next)
        self.delete_button = QPushButton("删除数据（风险测试）")
        self.delete_button.setStyleSheet("color: #b91c1c; font-weight: 600;")
        self.delete_button.clicked.connect(self._delete)
        scroll_layout.addWidget(self.next_button)
        scroll_layout.addWidget(self.delete_button)
        scroll.setWidget(scroll_content)
        root.addWidget(scroll, 1)

        self.result = QLabel("状态：等待操作")
        self.result.setObjectName("resultLabel")
        self.result.setStyleSheet("padding: 10px; background: #e8f1fb; border-radius: 6px;")
        root.addWidget(self.result)
        self.setCentralWidget(central)

    def _next(self) -> None:
        problems: list[str] = []
        if self.name.text() != "小明":
            problems.append("姓名不是“小明”")
        if not 77 <= self.progress.value() <= 83:
            problems.append("进度不在 80 附近")
        if not self.agree.isChecked():
            problems.append("尚未勾选同意")
        self.result.setText("状态：验收通过" if not problems else "状态：" + "；".join(problems))

    def _delete(self) -> None:
        answer = QMessageBox.warning(
            self,
            "风险操作",
            "这是用于验证风险确认的模拟删除，不会删除真实数据。",
            QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel,
        )
        if answer == QMessageBox.StandardButton.Ok:
            self.result.setText("状态：模拟删除已确认")


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    window = AutomationTestWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())

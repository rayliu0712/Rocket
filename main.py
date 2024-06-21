import os.path as op
import sys
import time

from PyQt6.QtCore import QTimer, QThread, Qt
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import QApplication, QPushButton, QComboBox, QLabel, QWidget, QHBoxLayout, QVBoxLayout, \
    QSizePolicy, QSpacerItem, QProgressBar
from adbutils import adb, AdbDevice, ShellReturn


class Device(AdbDevice):
    class __ShResult:
        def __init__(self, sr: ShellReturn):
            self.succeed = sr.returncode == 0
            self.fail = not self.succeed
            self.output = sr.output

    def __init__(self, adb_device: AdbDevice):
        super().__init__(adb, adb_device.serial)

    def sh(self, cmd: str) -> __ShResult:
        return Device.__ShResult(self.shell2(cmd, rstrip=True))

    def runas(self, cmd: str) -> __ShResult:
        return self.sh(f'run-as rl.launch {cmd}')

    # def pwd(self, cmd: str = '') -> __ShResult:
    #     sr = self.sh(f'cd "{sdcard}" && {cmd} {'' if cmd == '' else ';'}pwd')
    #     lines = sr.output.splitlines()
    #     lines[-1] = lines[-1].replace('//', '/')
    #     sr.output = '\n'.join(lines)
    #     return sr

    def exists(self, path: str) -> bool:
        return self.sh(f'[[ -e "{path}" ]]').succeed


class Widget(QWidget):
    def __init__(self):
        super().__init__()
        self.label = QLabel(self)
        self.vice_btn = QPushButton(self)
        self.push_btn = QPushButton(self)
        self.push_list = []
        self.is_launch = True
        self.timer = QTimer(self)
        self.setAcceptDrops(True)
        self.resize(400, 300)
        self.home()

    def home(self):
        combo_box = QComboBox(self)
        combo_box.addItems([d.prop.name for d in adb.device_list()])
        combo_box.adjustSize()

        self.label.setText('Wait for launch\n\nor\n\nDrag/Paste files to push')
        self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        font = QFont()
        font.setPointSize(12)
        self.label.setFont(font)

        self.vice_btn.setText('Shell')
        self.vice_btn.clicked.connect(lambda: print('clicked'))

        self.push_btn.setText('Push')
        self.push_btn.clicked.connect(lambda: print('clicked'))
        self.push_btn.setEnabled(False)

        top_hbox = QHBoxLayout()
        top_hbox.addSpacerItem(QSpacerItem(0, 0, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum))
        top_hbox.addWidget(combo_box)

        center_hbox = QHBoxLayout()
        center_hbox.addSpacerItem(QSpacerItem(0, 0, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum))
        center_hbox.addWidget(self.label)
        center_hbox.addSpacerItem(QSpacerItem(0, 0, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum))

        bottom_hbox = QHBoxLayout()
        bottom_hbox.addWidget(self.vice_btn)
        bottom_hbox.addWidget(self.push_btn)

        layout = QVBoxLayout()
        layout.addLayout(top_hbox)
        layout.addSpacerItem(QSpacerItem(0, 0, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding))
        layout.addLayout(center_hbox)
        layout.addSpacerItem(QSpacerItem(0, 0, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding))
        layout.addLayout(bottom_hbox)
        self.setLayout(layout)

        pbar = QProgressBar(self)
        pbar.setMaximum(1 * 1024 * 1024 * 1024)

        def launch_event():
            while True:
                global d
                sr = d.runas("cat ./files/launch.txt")
                if sr.fail:
                    continue

                d.runas('touch ./files/key_a')

                # emit

                d.sync.pull('/sdcard/Documents/1G', '1G')
                d.runas('touch ./files/key_b')
                time.sleep(1)
                # def update_ui():
                #     try:
                #         s = op.getsize('1G')
                #         pbar.setValue(s)
                #         pbar.show()
                #     except FileNotFoundError:
                #         ...

                # qthread = QThread(self)
                # qthread.run = d_pull
                # qthread.start()

                # while True:
                #     update_ui()

        thread = QThread(self)
        thread.run = launch_event
        thread.start()

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.accept()

    def dropEvent(self, event):
        if event.mimeData().hasUrls():
            self.push_list += [url.toLocalFile() for url in event.mimeData().urls() if
                               url.toLocalFile() not in self.push_list]
            self.label.setText('\n'.join(op.basename(p) for p in self.push_list))
            self.label.setAlignment(Qt.AlignmentFlag.AlignLeft)
            self.vice_btn.setText('Clear')
            self.vice_btn.clicked.connect(lambda: ...)
            self.push_btn.setEnabled(True)
            event.acceptProposedAction()

    # def start_io_task(self):
    #     thread = QThread()
    #     thread.run = self.io_task
    #     thread.start()
    #
    #     self.timer = QTimer()
    #     self.timer.timeout.connect(self.update_ui)
    #     self.timer.start(1)
    #
    # def io_task(self):
    #     d = adb.device_list()[0]
    #     d.sync.pull(f'/sdcard/Documents/{file}', file)
    #     self.timer.stop()
    #
    # def update_ui(self):
    #     try:
    #         s = op.getsize(file)
    #         # self.progress_bar.setValue(s)
    #
    #     except FileNotFoundError:
    #         ...


if __name__ == '__main__':
    d = Device(adb.device_list()[0])
    app = QApplication(sys.argv)
    widget = Widget()
    widget.show()
    sys.exit(app.exec())

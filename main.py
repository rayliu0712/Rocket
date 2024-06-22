import hashlib
import os
import os.path as op
import sys
from typing import Callable

from PyQt6.QtGui import QShortcut, QKeySequence
from PyQt6.QtWidgets import QWidget, QPushButton, QLabel, QVBoxLayout, QSpacerItem, QSizePolicy, QHBoxLayout, \
    QApplication
from adbutils import AdbDevice, ShellReturn, adb


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

    def exists(self, path: str) -> bool:
        return self.sh(f'[[ -e "{path}" ]]').succeed

    def pwd(self, sdcard: str, cmd: str = '') -> __ShResult:
        sr = self.sh(f'cd "{sdcard}" && {cmd} {'' if cmd == '' else ';'}pwd')
        lines = sr.output.splitlines()
        lines[-1] = lines[-1].replace('//', '/')
        sr.output = '\n'.join(lines)
        return sr


class U:
    @staticmethod
    def sha256(string: str) -> str:
        return hashlib.sha256(bytes(string, 'utf-8')).hexdigest()

    @staticmethod
    def safe_name(path: str, checker: Callable[[str], bool], return_full: bool) -> str:
        pwe, ext = op.splitext(path)
        n = ''
        for x in range(1, sys.maxsize):
            if checker(f'{pwe}{n}{ext}'):
                n = f' ({x})'
            else:
                if return_full:
                    return f'{pwe}{n}{ext}'
                else:
                    return op.basename(f'{pwe}{n}{ext}')

    @staticmethod
    def local_size(path: str) -> int:
        if not op.exists(path):
            return 0

        if not op.isdir(path):
            return op.getsize(path)

        size = 0
        for r, _, fs in os.walk(path):
            size += sum(op.getsize(op.join(r, f)) for f in fs)
        return size

    @staticmethod
    def remote_size(d: Device, path: str) -> int:
        try:
            # sh always succeed here
            return int(d.sh("find '%s' -type f -exec du -cb {} + | grep total$ | awk '{print $1}'" % path).output)
        except ValueError:
            return 0

    @staticmethod
    def visual_size(length) -> str:
        i = 0
        while length >= 1024:
            length /= 1024
            i += 1

        if length - int(length) == 0:
            length = int(length)
        else:
            length = round(length, 2)

        return f'{length}{['B', 'KB', 'MB', 'GB'][i]}'


class PushWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('Push')
        self.resize(400, 300)
        self.setAcceptDrops(True)
        QShortcut(QKeySequence('Ctrl+V'), self).activated.connect(lambda: self.paste(QApplication.clipboard()))

        self.label = QLabel('This\nis\nQLabel', self)
        self.clear_btn = QPushButton('Clear', self)
        self.clear_btn.clicked.connect(lambda: self.update_label(True))
        self.push_btn = QPushButton('Push', self)
        self.push_btn.clicked.connect(lambda: ...)
        self.push_list = []

        mid_hbox = QHBoxLayout()
        mid_hbox.addSpacerItem(QSpacerItem(0, 0, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum))
        mid_hbox.addWidget(self.label)
        mid_hbox.addSpacerItem(QSpacerItem(0, 0, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum))

        bottom_hbox = QHBoxLayout()
        bottom_hbox.addSpacerItem(QSpacerItem(0, 0, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum))
        bottom_hbox.addWidget(self.clear_btn)
        bottom_hbox.addWidget(self.push_btn)

        layout = QVBoxLayout()
        layout.addSpacerItem(QSpacerItem(0, 0, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding))
        layout.addLayout(mid_hbox)
        layout.addSpacerItem(QSpacerItem(0, 0, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding))
        layout.addLayout(bottom_hbox)
        self.setLayout(layout)

    def update_label(self, clear_push_list=False):
        if clear_push_list:
            self.push_list.clear()
        self.label.setText('\n'.join(op.basename(p) for p in self.push_list))

    def paste(self, a0):
        self.push_list += [u.toLocalFile() for u in a0.mimeData().urls() if u.toLocalFile() not in self.push_list]
        self.update_label()

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        self.paste(event)
        event.acceptProposedAction()


app = QApplication(sys.argv)
push_window = PushWindow()
push_window.show()
sys.exit(app.exec())

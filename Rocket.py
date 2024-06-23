#!/usr/bin/env python3
import hashlib
import os
import os.path as op
import subprocess as sp
import sys
from typing import Callable, List
from PyQt6.QtCore import QThread, QTimer
from PyQt6.QtGui import QShortcut, QKeySequence
from PyQt6.QtWidgets import QWidget, QProgressBar, QApplication, QLabel, QPushButton
from adbutils import adb, AdbDevice, ShellReturn

sdcard = '/sdcard/Download/'


class U:
    @staticmethod
    def sha256(string: str) -> str:
        return hashlib.sha256(bytes(string, 'utf-8')).hexdigest()

    @staticmethod
    def safe_name(path: str, checker: Callable[[str], bool]) -> str:
        pwe, ext = op.splitext(path)
        n = ''
        for x in range(1, sys.maxsize):
            if checker(f'{pwe}{n}{ext}'):
                n = f' ({x})'
            else:
                return f'{pwe}{n}{ext}'

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

    def pwd(self, cmd: str = '') -> __ShResult:
        sr = self.sh(f'cd "{sdcard}" && {cmd} {'' if cmd == '' else ';'}pwd')
        lines = sr.output.splitlines()
        lines[-1] = lines[-1].replace('//', '/')
        sr.output = '\n'.join(lines)
        return sr

    def exists(self, path: str) -> bool:
        return self.sh(f'[[ -e "{path}" ]]').succeed

    def get_remote_size(self, path: str) -> int:
        try:
            # sh always succeed here
            return int(self.shell("find '%s' -type f -exec du -cb {} + | grep total$ | awk '{print $1}'" % path))
        except ValueError:
            return 0


class HomeWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.srcs = []
        self.names = []
        self.resize(400, 300)
        self.setAcceptDrops(True)
        self.label = QLabel(self)
        self.push_btn = QPushButton('Push', self)
        self.push_btn.setGeometry(300, 270, 100, 30)
        self.push_btn.clicked.connect(self.push_event)
        self.push_btn.setEnabled(False)
        QShortcut(QKeySequence('Ctrl+V'), self).activated.connect(lambda: self.paste(QApplication.clipboard()))

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.wait)
        self.timer.start(1000)

    def wait(self):
        sr = d.runas("cat ./files/launch.txt")
        if sr.succeed:
            self.timer.stop()
            self.close()
            d.runas('touch ./files/key_a')
            srcs = sr.output.splitlines()
            total_size = int(srcs.pop(0))
            trans.set(srcs, total_size, True)
            trans.show()

    def push_event(self):
        self.close()
        total_size = sum(U.local_size(src) for src in self.srcs)
        trans.set(self.srcs, total_size, False)
        trans.show()

    def paste(self, a0):
        mime_data = a0.mimeData()
        if not mime_data.hasUrls():
            return

        self.push_btn.setEnabled(True)
        for url in mime_data.urls():
            url_file = url.toLocalFile()
            if url_file not in self.srcs:
                self.srcs.append(url_file)
                self.names.append(op.basename(url_file))

        self.label.setText('\n'.join(self.names))
        self.label.adjustSize()

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        self.paste(event)
        event.acceptProposedAction()


class TransferWindow(QWidget):
    def set(self, srcs: List[str], total_size: int, is_pull: bool):
        self.srcs = srcs
        self.dsts = []
        self.total_size = total_size
        self.get_size = op.getsize if is_pull else d.get_remote_size
        self.is_pull = is_pull
        for src in self.srcs:
            name = op.basename(src)
            if self.is_pull:
                self.dsts.append(U.safe_name(name, op.exists))
            else:
                self.dsts.append(U.safe_name(sdcard + name, d.exists))

        self.pbar = QProgressBar(self)
        self.pbar.setMaximum(2147483647)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_pbar)
        self.timer.start(1)

        thread = QThread(self)
        thread.run = self.transfer
        thread.start()

    def update_pbar(self):
        self.pbar.setValue(int(sum(self.get_size(dst) for dst in self.dsts) / self.total_size * 2147483647))

    def transfer(self):
        transferer = d.sync.pull if self.is_pull else lambda x, y: sp.check_output(f'adb push "{x}" "{y}"', shell=True)
        for src, dst in zip(self.srcs, self.dsts):
            if not self.is_pull:
                os.chdir(op.dirname(src))
            transferer(src, dst)
        self.timer.stop()
        if self.is_pull:
            d.runas('touch ./files/key_b')


cwd = os.getcwd()
app = QApplication(sys.argv)
d = Device(adb.device_list()[0])
home = HomeWindow()
trans = TransferWindow()
home.show()
status = app.exec()
os.chdir(cwd)
sys.exit(status)

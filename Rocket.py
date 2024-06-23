#!/usr/bin/env python3
import os.path as op
import subprocess as sp
import sys
from typing import Callable, List
from PyQt6.QtCore import QThread, QTimer
from PyQt6.QtGui import QShortcut, QKeySequence
from PyQt6.QtWidgets import QWidget, QProgressBar, QApplication, QLabel, QPushButton
from adbutils import adb, AdbDevice, ShellReturn

sdcard = '/sdcard/'


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
            dsts = [op.basename(src) for src in srcs]
            window = TransferWindow(srcs, dsts, total_size, op.getsize, True)
            window.show()

    def push_event(self):
        self.close()
        dsts = [sdcard + name for name in self.names]
        total_size = sum(op.getsize(src) for src in self.srcs)
        window = TransferWindow(self.srcs, dsts, total_size, d.get_remote_size, False)
        window.show()

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
    def __init__(self, srcs: List[str], dsts: List[str], total_size: int, get_size: Callable[[str], int],
                 is_pull: bool):
        super().__init__()
        self.srcs = srcs
        self.dsts = dsts
        self.total_size = total_size
        self.get_size = get_size
        self.is_pull = is_pull

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
            transferer(src, dst)
        self.timer.stop()
        if self.is_pull:
            d.runas('touch ./files/key_b')


app = QApplication(sys.argv)
d = Device(adb.device_list()[0])
home = HomeWindow()
home.show()
sys.exit(app.exec())

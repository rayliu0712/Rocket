#!/usr/bin/env python3
import hashlib
import os
import os.path as op
import shutil
import subprocess as sp
import sys
import time
from typing import Callable, List
from PyQt6.QtCore import QThread, QTimer, Qt
from PyQt6.QtGui import QShortcut, QKeySequence
from PyQt6.QtWidgets import QWidget, QProgressBar, QApplication, QLabel, QPushButton, QVBoxLayout, QSpacerItem, \
    QSizePolicy, QHBoxLayout
from adbutils import adb, AdbDevice, ShellReturn

sdcard = '/sdcard/Download/'


class U:
    @staticmethod
    def sha256(string: str) -> str:
        return hashlib.sha256(bytes(string, 'utf-8')).hexdigest()

    @staticmethod
    def safe_path(path: str, checker: Callable[[str], bool]) -> str:
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
    def r_size(length) -> str:
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
        return self.sh(f'[ -e "{path}" ]').succeed

    def get_remote_size(self, path: str) -> int:
        output = self.shell(
            r"find '#' -type f -exec stat -c%s {} \; | awk '{sum += $1} END {print sum}'".replace('#', path))
        return int(output) if output.isdigit() else 0


class HomeWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.srcs = []
        self.resize(400, 300)
        self.setWindowTitle('Rocket')
        self.setAcceptDrops(True)
        self.label = QLabel(self)
        self.update_label(True)
        self.clear_btn = QPushButton('Clear', self)
        self.clear_btn.clicked.connect(lambda: self.update_label(True))
        self.push_btn = QPushButton('Push', self)
        self.push_btn.clicked.connect(self.push_event)
        self.push_btn.setEnabled(False)
        QShortcut(QKeySequence('Ctrl+V'), self).activated.connect(lambda: self.paste(QApplication.clipboard()))

        center_hbox = QHBoxLayout()
        center_hbox.addSpacerItem(QSpacerItem(0, 0, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum))
        center_hbox.addWidget(self.label)
        center_hbox.addSpacerItem(QSpacerItem(0, 0, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum))

        bottom_hbox = QHBoxLayout()
        bottom_hbox.addSpacerItem(QSpacerItem(0, 0, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum))
        bottom_hbox.addWidget(self.clear_btn)
        bottom_hbox.addWidget(self.push_btn)

        layout = QVBoxLayout()
        layout.addSpacerItem(QSpacerItem(0, 0, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding))
        layout.addLayout(center_hbox)
        layout.addSpacerItem(QSpacerItem(0, 0, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding))
        layout.addLayout(bottom_hbox)
        self.setLayout(layout)

        thread = QThread(self)
        thread.run = self.waiting_for_launch
        thread.finished.connect(transfer_w.show)
        thread.start()

    def waiting_for_launch(self):
        sr = d.runas("cat ./files/launch.txt")
        while sr.fail:
            sr = d.runas("cat ./files/launch.txt")

        d.runas('touch ./files/key_a')
        srcs = sr.output.splitlines()
        total_size = int(srcs.pop(0))
        transfer_w.set(srcs, total_size, True)

    def push_event(self):
        total_size = sum(U.local_size(src) for src in self.srcs)
        transfer_w.set(self.srcs, total_size, False)
        transfer_w.show()

    def update_label(self, clear: bool = False):
        if clear:
            self.srcs.clear()
            self.label.setText('Waiting for Launch\n\nor\n\nDrag/Paste files to Push')
            self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        else:
            self.label.setText(f'{len(self.srcs)} File{'s' if len(self.srcs) > 1 else ''}, ' +
                               f'{U.r_size(sum(U.local_size(src) for src in self.srcs))}\n\n' +
                               '\n'.join(op.basename(name) for name in self.srcs))
            self.label.setAlignment(Qt.AlignmentFlag.AlignLeft)

        self.label.adjustSize()

    def paste(self, a0):
        mime_data = a0.mimeData()
        if not mime_data.hasUrls():
            return

        self.push_btn.setEnabled(True)
        for url in mime_data.urls():
            url_file = url.toLocalFile()
            if url_file not in self.srcs:
                self.srcs.append(url_file)
        self.update_label()

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        self.paste(event)
        event.acceptProposedAction()


class TransferWindow(QWidget):
    def set(self, srcs: List[str], total_size: int, is_pull: bool):
        self.srcs = srcs
        self.total_size = total_size
        self.get_size = U.local_size if is_pull else d.get_remote_size
        self.get_exist = op.exists if is_pull else d.exists
        self.is_pull = is_pull

        if is_pull:
            self.dsts = [U.safe_path(op.basename(src), op.exists) for src in srcs]
        else:
            self.hd = U.sha256(str(time.time()))
            os.mkdir(self.hd)
            self.dsts = [f'/sdcard/Download/{self.hd}']

            self.tmps = [op.basename(U.safe_path(f'{sdcard}{op.basename(src)}', d.exists)) for src in srcs]
            [shutil.move(src, op.join(self.hd, tmp)) for src, tmp in zip(srcs, self.tmps)]

    def show(self):
        self.pbar = QProgressBar(self)
        self.label = QLabel(self)

        layout = QVBoxLayout()
        layout.addWidget(self.label)
        layout.addWidget(self.pbar)
        self.adjustSize()
        self.setLayout(layout)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_pbar)
        self.start_time = time.time()
        self.timer.start(10)

        thread = QThread(self)
        thread.run = self.transfer
        thread.finished.connect(self.close)
        thread.start()

        super().show()

    def update_pbar(self):
        try:
            count = sum(self.get_exist(dst) for dst in self.dsts)
            count -= bool(count)
            size = sum(self.get_size(dst) for dst in self.dsts)
            value = size * 100 // self.total_size
            if value == 100:
                self.timer.stop()

            self.label.setText(f'{count}/{len(self.dsts)} File{'s' if len(self.dsts) > 1 else ''}  |  ' +
                               f'{U.r_size(size)}/{U.r_size(self.total_size)}  |  '
                               f'{U.r_size(size / (time.time() - self.start_time))}/s')
            self.pbar.setValue(value)
            self.setWindowTitle(f'{value}%')
        except FileNotFoundError:
            pass

    def transfer(self):
        transferer = d.sync.pull if self.is_pull else lambda x, y: sp.check_output(f'adb push "{x}" "{y}"', shell=True)
        if self.is_pull:
            for src, dst in zip(self.srcs, self.dsts):
                transferer(src, dst)
            d.runas('touch ./files/key_b')
        else:
            sp.check_output(f'adb push {self.hd} /sdcard/Download/{self.hd}', shell=True)
            d.sh(f'cd /sdcard/Download/{self.hd}; mv * "{sdcard}"; rmdir ../{self.hd}')
            [shutil.move(op.join(self.hd, tmp), src) for tmp, src in zip(self.tmps, self.srcs)]
            os.rmdir(self.hd)


app = QApplication(sys.argv)
d = Device(adb.device_list()[0])
transfer_w = TransferWindow()
home_w = HomeWindow()
home_w.show()
sys.exit(app.exec())

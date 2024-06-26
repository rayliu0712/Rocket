#!/usr/bin/env python3
import hashlib
import os
import os.path as op
import sys
import time
from typing import Callable, List, Tuple
from PyQt6.QtCore import QThread, Qt, pyqtSignal
from PyQt6.QtGui import QShortcut, QKeySequence
from PyQt6.QtWidgets import QWidget, QProgressBar, QApplication, QLabel, QPushButton, QVBoxLayout, QSpacerItem, \
    QSizePolicy, QHBoxLayout
from adbutils import adb, AdbDevice, ShellReturn


class U:
    @staticmethod
    def sha256(string: str) -> str:
        return hashlib.sha256(bytes(string, 'utf-8')).hexdigest()

    @staticmethod
    def safe_path(path: str, is_dir: bool, checker: Callable[[str], bool]) -> str:
        pwe, ext = op.splitext(path)
        if is_dir and ext != '':
            pwe += ext
            ext = ''

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
    def hr_size(length) -> str:
        i = 0
        while length >= 1024:
            length /= 1024
            i += 1

        if length - int(length) == 0:
            length = int(length)
        else:
            length = round(length, 2)
        return f'{length}{('B', 'KB', 'MB', 'GB')[i]}'

    @staticmethod
    def push_dir_essentials(m_src: str, m_dst: str) -> Tuple[str, List[str], List[str]]:
        path_parent = op.dirname(m_src)

        end_dirs = ''
        srcs = []
        dsts = []
        for r, ds, fs in os.walk(m_src):
            # relr = op.relpath(r, path_parent)
            if not ds:
                end_dirs += f' "{U.unx_delim(op.relpath(r, path_parent))}"'
            for f in fs:
                srcs.append(op.join(r, f))
                dsts.append(U.unx_delim(op.join(m_dst, f)))

        return end_dirs, srcs, dsts

    @staticmethod
    def unx_delim(path: str) -> str:
        return path.replace('\\', '/')


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
        return self.sh(f'[ -e "{path}" ]').succeed

    def get_remote_size(self, path: str) -> int:
        output = self.shell(
            r"find '#' -type f -exec stat -c%s {} \; | awk '{sum += $1} END {print sum}'".replace('#', path))
        return int(output) if output.isdigit() else 0


class Worker(QThread):
    sig = pyqtSignal()


class HomeW(QWidget):
    def __init__(self):
        super().__init__()
        self.push_list = []
        self.should_thread_run = True
        self.transferring = False
        self.resize(400, 300)
        self.setWindowTitle('Rocket')
        self.setAcceptDrops(True)
        self.label = QLabel(self)
        self.clear_btn = QPushButton('Clear', self)
        self.clear_btn.clicked.connect(lambda: self.update_label(True))
        self.push_btn = QPushButton('Push', self)
        self.push_btn.clicked.connect(self.push_event)
        self.update_label(True)
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

        self.thread = Worker(self)
        self.thread.run = self.waiting_for_launch
        self.thread.sig.connect(TransferW.new)
        self.thread.start()

    def waiting_for_launch(self):
        while self.should_thread_run:
            sr = device.runas("cat ./files/launch.txt")
            if not self.transferring and sr.succeed:
                self.transferring = True
                device.runas('touch ./files/key_a')
                srcs = sr.output.splitlines()
                TransferW.set(True, srcs)
                self.thread.sig.emit()

    def push_event(self):
        self.transferring = True
        TransferW.set(False, self.push_list)
        TransferW.new()

    def update_label(self, clear: bool = False):
        if clear:
            self.push_list.clear()
            self.label.setText('Waiting for Launch\n\nor\n\nDrag/Paste files to Push')
            self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.push_btn.setEnabled(False)
        else:
            self.label.setText(f'{len(self.push_list)} File{'s' if len(self.push_list) > 1 else ''}, ' +
                               f'{U.hr_size(sum(U.local_size(src) for src in self.push_list))}\n\n' +
                               '\n'.join(op.basename(name) for name in self.push_list))
            self.label.setAlignment(Qt.AlignmentFlag.AlignLeft)

        self.label.adjustSize()

    def paste(self, a0):
        mime_data = a0.mimeData()
        if not mime_data.hasUrls():
            return

        self.push_btn.setEnabled(True)
        for url in mime_data.urls():
            url_file = url.toLocalFile()
            if url_file not in self.push_list:
                self.push_list.append(url_file)
        self.update_label()

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        self.paste(event)
        event.acceptProposedAction()

    def closeEvent(self, event):
        self.should_thread_run = False
        self.thread.wait()
        event.accept()


class TransferW(QWidget):
    srcs: List[str]
    dsts: List[str]
    is_files: List[str]
    total_size: int
    get_size: Callable[[str], int]
    get_exists: Callable[[str], bool]
    is_pull: bool

    @staticmethod
    def set(is_pull: bool, srcs: List[str]):
        if is_pull:
            TransferW.total_size = int(srcs.pop(0))
            TransferW.srcs = [src.split('\t')[0] for src in srcs]
            TransferW.is_files = [src.split('\t')[1] == '1' for src in srcs]
            TransferW.dsts = [
                U.safe_path(op.basename(a), b, op.exists) for a, b in zip(TransferW.srcs, TransferW.is_files)
            ]
        else:
            TransferW.total_size = sum(U.local_size(src) for src in srcs)
            TransferW.srcs = srcs
            TransferW.is_files = [op.isfile(src) for src in srcs]
            TransferW.dsts = \
                [U.safe_path(sdcard + op.basename(src), op.isdir(src), device.exists) for src in srcs]

        TransferW.get_size = U.local_size if is_pull else device.get_remote_size
        TransferW.get_exists = op.exists if is_pull else device.exists
        TransferW.is_pull = is_pull

    @staticmethod
    def new():
        home_w.hide()
        global transfer_w
        transfer_w = TransferW()
        transfer_w.show()

    def show(self):
        self.pbar = QProgressBar(self)
        self.label = QLabel(self)

        layout = QVBoxLayout()
        layout.addWidget(self.label)
        layout.addWidget(self.pbar)
        self.adjustSize()
        self.setLayout(layout)

        self.compute_t = Worker(self)
        self.compute_t.run = self.compute
        self.compute_t.sig.connect(self.update_ui)
        self.start_time = time.time()
        self.compute_t.start()

        transfer_t = QThread(self)
        transfer_t.run = self.transfer
        transfer_t.finished.connect(self.close)
        transfer_t.start()

        super().show()

    def close(self):
        super().close()
        home_w.update_label(True)
        home_w.show()

    def compute(self):
        self.__value = 0
        while self.__value < 100:
            self.__count = sum(TransferW.get_exists(dst) for dst in TransferW.dsts)
            self.__count -= bool(self.__count)
            self.__size = sum(TransferW.get_size(dst) for dst in TransferW.dsts)
            self.__value = self.__size * 100 // TransferW.total_size
            self.compute_t.sig.emit()

    def update_ui(self):
        try:
            self.label.setText(
                f'{self.__count}/{len(TransferW.dsts)} File{'s' if len(TransferW.dsts) > 1 else ''}  |  ' +
                f'{U.hr_size(self.__size)}/{U.hr_size(TransferW.total_size)}  |  '
                f'{U.hr_size(self.__size / (time.time() - self.start_time))}/s')
            self.pbar.setValue(self.__value)
            self.setWindowTitle(f'{self.__value}%')

        except FileNotFoundError:
            pass

    def transfer(self):
        if TransferW.is_pull:
            for src, dst in zip(TransferW.srcs, TransferW.dsts):
                device.sync.pull(src, dst)
            device.runas('touch ./files/key_b')
        else:
            for m_src, m_dst, is_file in zip(TransferW.srcs, TransferW.dsts, TransferW.is_files):
                if is_file:
                    device.sync.push(m_src, m_dst)
                else:
                    end_dirs, srcs, dsts = U.push_dir_essentials(m_src, m_dst)
                    device.sh(f'cd "{sdcard}"; mkdir -p {end_dirs}')
                    for src, dst in zip(srcs, dsts):
                        device.sync.push(src, dst)

        time.sleep(1)
        home_w.transferring = False


sdcard = '/sdcard/'
device = Device(adb.device_list()[0])

app = QApplication(sys.argv)
transfer_w: TransferW
home_w = HomeW()
home_w.show()
sys.exit(app.exec())

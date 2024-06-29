#!/usr/bin/env python3
import hashlib
import os
import os.path as op
import re
import sys
import time
from typing import List, Callable, Tuple
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QStringListModel
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QWidget, QComboBox, QCompleter, QApplication, QVBoxLayout, QHBoxLayout, QPushButton, \
    QListWidget, QLabel, QProgressBar
from adbutils import adb, AdbDevice, ShellReturn

bookmarks = {
    'Home': '',
    'Download': 'Download',
    'Pictures': 'Pictures',
    'AstroDX': 'Android/data/com.Reflektone.AstroDX/files/levels'
}


class Worker(QThread):
    sig = pyqtSignal()
    sig2 = pyqtSignal()


class MyAdbDevice(AdbDevice):
    class __ShResult:
        def __init__(self, sr: ShellReturn):
            self.succeed = sr.returncode == 0
            self.fail = not self.succeed
            self.output = sr.output

    def __init__(self, adb_device: AdbDevice):
        super().__init__(adb, adb_device.serial)

    def sh(self, cmd: str) -> __ShResult:
        return MyAdbDevice.__ShResult(self.shell2(cmd, rstrip=True))

    def runas(self, cmd: str) -> __ShResult:
        return self.sh(f'run-as rl.launch {cmd}')

    def exists(self, path: str) -> bool:
        return self.sh(f'[ -e "{path}" ]').succeed

    def get_remote_size(self, path: str) -> int:
        output = self.shell(
            r"find '#' -type f -exec stat -c%s {} \; | awk '{sum += $1} END {print sum}'".replace('#', path))
        return int(output) if output.isdigit() else 0


class U:
    @staticmethod
    def delim(path: str) -> str:
        return re.sub('/+', '/', path.replace('\\', '/'))

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
    def human_readable_size(length, is_round: bool = False) -> str:
        i = 0
        while length >= 1024:
            length /= 1024
            i += 1

        if length - int(length) == 0:
            length = int(length)
        else:
            length = round(length, 2)
        return f'{round(length) if is_round else length}{("B", "KB", "MB", "GB")[i]}'

    @staticmethod
    def push_dir_essentials(m_src: str, m_dst: str) -> Tuple[str, List[str], List[str]]:
        path_parent = op.dirname(m_src)

        end_dirs = ''
        srcs = []
        dsts = []
        for r, ds, fs in os.walk(m_src):
            if not ds:
                end_dirs += f' "{U.delim(op.relpath(r, path_parent))}"'
            for f in fs:
                srcs.append(op.join(r, f))
                dsts.append(U.delim(op.join(m_dst, f)))

        return end_dirs, srcs, dsts


class HomeW(QWidget):
    def __init__(self):
        super().__init__()
        self.setAcceptDrops(True)
        self.setWindowTitle('Rocket')
        self.should_thread_run = True
        self.transferring = False

        self.label = QLabel('None', self)

        self.previous_btn = QPushButton('←', self)
        self.previous_btn.setFixedWidth(self.previous_btn.height())
        self.previous_btn.clicked.connect(lambda: self.cd(internal + '/..'))

        self.combo = QComboBox(self)
        self.combo.setEditable(True)
        self.completer = QCompleter(self)
        self.combo.setCompleter(self.completer)

        self.list_widget = QListWidget(self)
        self.list_widget.addItem('.')
        self.list_widget.itemDoubleClicked.connect(lambda item: self.cd(internal + '/' + item.text()))

        top_hbox = QHBoxLayout()
        top_hbox.addWidget(self.label)
        top_hbox.addWidget(self.previous_btn)
        top_hbox.addWidget(self.combo, Qt.AlignmentFlag.AlignCenter)

        btn_hbox = QHBoxLayout()
        for k, v in bookmarks.items():
            btn = QPushButton(k, self)
            btn.clicked.connect(lambda _, v_=v: self.cd(internal + '/' + v_))
            btn_hbox.addWidget(btn)

        layout = QVBoxLayout()
        layout.addLayout(top_hbox)
        layout.addLayout(btn_hbox)
        layout.addWidget(self.list_widget)
        self.setLayout(layout)
        self.label.setFocus()

        self.thread = Worker(self)
        self.thread.run = self.waiting_for_launch
        self.thread.sig.connect(lambda: self.label.setText(device.prop.name))
        self.thread.sig2.connect(TransferW.new)
        self.thread.start()

    def waiting_for_launch(self):
        global device
        while device is None and self.should_thread_run:
            device_list = adb.device_list()
            if device_list:
                device = MyAdbDevice(device_list[0])
                self.thread.sig.emit()

        while self.should_thread_run:
            sr = device.runas("cat ./files/launch.txt")
            if not self.transferring and sr.succeed:
                self.transferring = True
                device.runas('touch ./files/key_a')
                srcs = sr.output.splitlines()
                TransferW.set(True, srcs)
                self.thread.sig2.emit()

    def cd(self, new_internal: str):
        sr = device.sh(f'cd "/sdcard/{new_internal}" && pwd')
        if not sr.output.startswith('/sdcard') or sr.fail:
            return

        global internal
        internal = U.delim(re.sub('^/sdcard/*', '', sr.output))
        ds = [d.lstrip('./') for d in
              device.shell(f'cd "/sdcard/{internal}";find . -maxdepth 1 -type d ! -name .').splitlines()]
        fs = [f.lstrip('./') for f in device.shell(f'cd "/sdcard/{internal}";find . -maxdepth 1 -type f').splitlines()]
        ds_internal = [(internal + '/' + item).lstrip('/') for item in ds]

        self.combo.clear()
        self.combo.addItems(ds_internal)
        self.completer.setModel(QStringListModel(ds_internal, self))
        self.combo.setEditText(internal)

        self.list_widget.clear()
        self.list_widget.addItems(ds + fs)
        for i in range(len(ds)):
            item = self.list_widget.item(i)
            item.setBackground(QColor('black'))
            item.setForeground(QColor('white'))

    def paste(self, a0):
        mime_data = a0.mimeData()
        if mime_data.hasUrls():
            TransferW.set(False, [url.toLocalFile() for url in mime_data.urls()])
            TransferW.new()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_F2:
            print('f2')

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
            TransferW.dsts = [U.safe_path(f'/sdcard/{internal}/{op.basename(src)}', op.isdir(src), device.exists)
                              for src in srcs]

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
        # home_w.update_label(True)
        home_w.show()

    def compute(self):
        try:
            self.__value = 0
            while self.__value < 100:
                self.__count = sum(TransferW.get_exists(dst) for dst in TransferW.dsts)
                self.__count -= bool(self.__count)
                self.__size = sum(TransferW.get_size(dst) for dst in TransferW.dsts)
                self.__value = self.__size * 100 // TransferW.total_size
                self.compute_t.sig.emit()

        except ZeroDivisionError:
            self.compute_t.sig.emit()

    def update_ui(self):
        try:
            now = time.time()
            self.label.setText(
                f'{self.__count}/{len(TransferW.dsts)} File{"s" if len(TransferW.dsts) > 1 else ""}  |  ' +
                f'{round(now - self.start_time)}s  |  ' +
                f'{U.human_readable_size(self.__size / (now - self.start_time), True)}/s  |  ' +
                f'{U.human_readable_size(self.__size)}/{U.human_readable_size(TransferW.total_size)}')
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
                    device.sh(f'cd "/sdcard/{internal}"; mkdir -p {end_dirs}')
                    for src, dst in zip(srcs, dsts):
                        device.sync.push(src, dst)

        time.sleep(1)
        home_w.transferring = False


app = QApplication(sys.argv)
internal = ''
device: MyAdbDevice | None = None
transfer_w: TransferW
home_w = HomeW()
home_w.show()
sys.exit(app.exec())

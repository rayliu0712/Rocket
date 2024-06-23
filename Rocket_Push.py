#!/usr/bin/env python3
import os.path as op
import sys
from typing import Callable, List
from PyQt6.QtCore import QThread, QTimer
from PyQt6.QtGui import QShortcut, QKeySequence
from PyQt6.QtWidgets import QWidget, QProgressBar, QApplication, QLabel, QPushButton
from adbutils import adb

sdcard = '/sdcard/'


def get_remote_size(path: str) -> int:
    try:
        # sh always succeed here
        return int(device.shell("find '%s' -type f -exec du -cb {} + | grep total$ | awk '{print $1}'" % path))
    except ValueError:
        return 0


class MainWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.resize(400, 300)
        self.setAcceptDrops(True)
        self.label = QLabel(self)
        self.btn = QPushButton('Push', self)
        self.btn.setGeometry(300, 270, 100, 30)
        self.btn.clicked.connect(self.transfer_event)
        QShortcut(QKeySequence('Ctrl+V'), self).activated.connect(lambda: self.paste(QApplication.clipboard()))

        self.srcs = []
        self.names = []

    def transfer_event(self):
        self.close()
        dsts = [sdcard + name for name in self.names]
        sz = sum(op.getsize(src) for src in self.srcs)
        window = TransferWindow(self.srcs, dsts, sz, get_remote_size, TransferWindow.PUSH)
        window.show()

    def paste(self, a0):
        mime_data = a0.mimeData()
        if not mime_data.hasUrls():
            return

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
    PUSH = 0
    PULL = 1

    def __init__(self, srcs: List[str], dsts: List[str], total_size: int, get_size: Callable[[str], int], mode: int):
        super().__init__()
        self.srcs = srcs
        self.dsts = dsts
        self.total_size = total_size
        self.get_size = get_size
        self.mode = mode

        self.pbar = QProgressBar(self)
        self.pbar.setMaximum(2147483647)

        thread = QThread(self)
        thread.run = self.transfer
        thread.start()

        timer = QTimer(self)
        timer.timeout.connect(self.update_pbar)
        timer.start(1000)

    def update_pbar(self):
        self.pbar.setValue(int(sum(self.get_size(dst) for dst in self.dsts) / self.total_size * 2147483647))

    def transfer(self):
        transferer = device.sync.pull if self.mode else device.sync.push
        for src, dst in zip(self.srcs, self.dsts):
            transferer(src, dst)


app = QApplication(sys.argv)
device = adb.device_list()[0]
main_window = MainWindow()
main_window.show()
sys.exit(app.exec())

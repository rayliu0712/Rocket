import sys

from PyQt6.QtCore import QThread, QTimer
from PyQt6.QtWidgets import QWidget, QApplication, QPushButton, QLabel, QProgressBar
from adbutils import adb
import os.path as op


class MyWidget(QWidget):

    def pull(self):
        d = adb.device_list()[0]
        d.sync.pull('/sdcard/Documents/1G', '1G')

    def ui(self):
        try:
            s = op.getsize('1G')
            # self.label.setText(f'{s / 1024 / 1024}')
            self.pbar.setValue(s)
        except Exception:
            ...

    def __init__(self):
        super().__init__()
        # self.label = QLabel('abc', self)
        self.pbar = QProgressBar(self)
        self.pbar.setMaximum(1 * 1024 * 1024 * 1024)

        thread = QThread(self)
        thread.run = self.pull
        thread.start()

        timer = QTimer(self)
        timer.timeout.connect(self.ui)
        timer.start(100)


app = QApplication(sys.argv)
mine = MyWidget()
mine.show()
sys.exit(app.exec())

#!/usr/bin/env python3
import hashlib
import os
import os.path as op
import re
import sys
import time
from typing import List, Callable, Tuple

from PyQt6.QtCore import Qt, QThread, pyqtSignal, QStringListModel
from PyQt6.QtGui import QColor, QKeySequence, QAction
from PyQt6.QtWidgets import QWidget, QComboBox, QCompleter, QApplication, QVBoxLayout, QHBoxLayout, QPushButton, QListWidget, QLabel, QProgressBar, QMenu, QMainWindow, \
    QMessageBox, QLineEdit, QDialog, QListWidgetItem
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


class MyListWidget(QListWidget):
    def editItem(self, item):
        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEditable)
        super().editItem(item)

    def mousePressEvent(self, event):
        if self.itemAt(event.pos()) is None:
            self.clearSelection()
            self.clearFocus()
        super().mousePressEvent(event)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.clearSelection()
            self.clearFocus()
        super().keyPressEvent(event)


class MyAdbDevice(AdbDevice):
    class ShResult:
        def __init__(self, sr: ShellReturn):
            self.succeed = sr.returncode == 0
            self.fail = not self.succeed
            self.output = sr.output

    def __init__(self, adb_device: AdbDevice):
        super().__init__(adb, adb_device.serial)

    def sh(self, cmd: str) -> ShResult:
        return MyAdbDevice.ShResult(self.shell2(cmd, rstrip=True))

    def runas(self, cmd: str) -> ShResult:
        return self.sh(f'run-as rl.launch {cmd}')

    def exists(self, path: str) -> bool:
        return self.sh(f'[ -e "{path}" ]').succeed

    def get_remote_size(self, path: str) -> int:
        output = self.shell(
            r"find '#' -type f -exec stat -c%s {} \; | awk '{sum += $1} END {print sum}'".replace('#', path))
        return int(output) if output.isdigit() else 0


class HomeW(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setAcceptDrops(True)
        self.setWindowTitle('Rocket')
        self.should_thread_run = True
        self.enter_explorer = False
        self.available_actions = []

        self.menu_bar = self.menuBar().addMenu('File')
        MyActions.init(self)

        self.label = QLabel('None', self)
        self.back_btn = QPushButton('←', self, clicked=lambda: self.cd(None, '..'))
        self.back_btn.setFixedWidth(self.back_btn.height())
        self.next_btn = QPushButton('→', self)
        self.next_btn.setFixedWidth(self.next_btn.height())
        self.completer = QCompleter(self)
        self.combo = QComboBox(self, editable=True)
        self.combo.setCompleter(self.completer)
        self.searcher = QLineEdit(self, placeholderText='Search')
        self.list_widget = MyListWidget(self, itemDoubleClicked=lambda item: self.cd(None, item.text()))
        self.list_widget.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        self.list_widget.addItem('Double click me to enter explorer')
        self.list_widget.itemSelectionChanged.connect(MyActions.connect)

        top_hbox = QHBoxLayout()
        top_hbox.addWidget(self.label)
        top_hbox.addWidget(self.back_btn)
        top_hbox.addWidget(self.next_btn)
        top_hbox.addWidget(self.combo, 1)
        top_hbox.addWidget(self.searcher, 1)

        btn_hbox = QHBoxLayout()
        for k, v in bookmarks.items():
            btn_hbox.addWidget(QPushButton(k, self, clicked=lambda _, v_=v: self.cd(None, v_)))

        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        layout = QVBoxLayout(central_widget)
        layout.addLayout(top_hbox)
        layout.addLayout(btn_hbox)
        layout.addWidget(self.list_widget)
        self.setLayout(layout)
        self.label.setFocus()

        self.thread = Worker(self)
        self.thread.run = self.waiting_for_launch
        self.thread.sig.connect(lambda: self.label.setText(G.device.prop.name))
        self.thread.sig2.connect(TransferD.new)
        self.thread.start()

    def waiting_for_launch(self):
        while G.device is None and self.should_thread_run:
            device_list = adb.device_list()
            if device_list:
                G.device = MyAdbDevice(device_list[0])
                self.thread.sig.emit()

        while self.should_thread_run:
            sr = G.device.runas("cat ./files/launch.txt")
            if not G.transferring and sr.succeed:
                G.transferring = True
                G.device.runas('touch ./files/key_a')
                srcs = sr.output.splitlines()
                TransferD.set(True, srcs)
                self.thread.sig2.emit()

    def cd(self, new_internal: str | None, branch: str):
        if new_internal is None:
            new_internal = G.internal

        if not self.enter_explorer:
            self.enter_explorer = True
            branch = ''

        sr = G.device.sh(f'cd "/sdcard/{new_internal}/{branch}" && pwd')
        if not sr.output.startswith('/sdcard') or sr.fail:
            return

        G.internal = G.delim(re.sub('^/sdcard/*', '', sr.output))
        ds = [d.lstrip('./') for d in G.device.shell(f'cd "/sdcard/{G.internal}";find . -maxdepth 1 -type d ! -name .|sort').splitlines()]
        fs = [f.lstrip('./') for f in G.device.shell(f'cd "/sdcard/{G.internal}";find . -maxdepth 1 -type f|sort').splitlines()]
        ds_internal = [G.valid_internal(it) for it in ds]

        self.combo.clear()
        self.combo.addItems(ds_internal)
        self.completer.setModel(QStringListModel(ds_internal, self))
        self.combo.setEditText(G.internal)

        self.list_widget.clear()
        self.list_widget.addItems(ds + fs)
        for i in range(len(ds)):
            item = self.list_widget.item(i)
            item.setBackground(QColor('#765341'))
            item.setForeground(QColor('white'))

    def selected_texts(self) -> List[str]:
        return [it.text() for it in self.list_widget.selectedItems()]

    def push(self, a0):
        if G.are_local_files(a0):
            TransferD.set(False, [url.toLocalFile() for url in a0.mimeDats().urls()])
            TransferD.new()

    def contextMenuEvent(self, event):
        if self.available_actions:
            menu = QMenu(self)
            menu.addActions(self.available_actions)
            menu.exec(event.globalPos())

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        self.push(event)
        event.acceptProposedAction()

    def closeEvent(self, event):
        self.should_thread_run = False
        self.thread.wait()
        event.accept()


class TransferD(QDialog):
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
            TransferD.total_size = int(srcs.pop(0))
            TransferD.srcs = [src.split('\t')[0] for src in srcs]
            TransferD.is_files = [src.split('\t')[1] == '1' for src in srcs]
            TransferD.dsts = [G.safe_path(op.basename(a), b, op.exists) for a, b in zip(TransferD.srcs, TransferD.is_files)]
        else:
            TransferD.total_size = sum(G.local_size(src) for src in srcs)
            TransferD.srcs = srcs
            TransferD.is_files = [op.isfile(src) for src in srcs]
            TransferD.dsts = [G.safe_path(f'/sdcard/{G.internal}/{op.basename(src)}', op.isdir(src), G.device.exists) for src in srcs]

        TransferD.get_size = G.local_size if is_pull else G.device.get_remote_size
        TransferD.get_exists = op.exists if is_pull else G.device.exists
        TransferD.is_pull = is_pull

    @staticmethod
    def new():
        G.transfer_w = TransferD(G.home_w)
        G.transfer_w.setModal(True)
        G.transfer_w.show()

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

    def compute(self):
        try:
            self.__value = 0
            while self.__value < 100:
                self.__count = sum(TransferD.get_exists(dst) for dst in TransferD.dsts) - 1
                if self.__count == -1:
                    self.__count = 0
                self.__size = sum(TransferD.get_size(dst) for dst in TransferD.dsts)
                self.__value = self.__size * 100 // TransferD.total_size
                self.compute_t.sig.emit()

        except ZeroDivisionError:
            self.compute_t.sig.emit()

    def update_ui(self):
        now = time.time()
        self.label.setText(
            f'{self.__count}/{len(TransferD.dsts)} File{"s" if len(TransferD.dsts) > 1 else ""}  |  ' +
            f'{round(now - self.start_time)}s  |  ' +
            f'{G.human_readable_size(self.__size / (now - self.start_time), True)}/s  |  ' +
            f'{G.human_readable_size(self.__size)}/{G.human_readable_size(TransferD.total_size)}')
        self.pbar.setValue(self.__value)
        self.setWindowTitle(f'{self.__value}%')

    def transfer(self):
        if TransferD.is_pull:
            for src, dst in zip(TransferD.srcs, TransferD.dsts):
                G.device.sync.pull(src, dst)
            G.device.runas('touch ./files/key_b')
        else:
            for m_src, m_dst, is_file in zip(TransferD.srcs, TransferD.dsts, TransferD.is_files):
                if is_file:
                    G.device.sync.push(m_src, m_dst)
                else:
                    end_dirs, srcs, dsts = G.push_dir_essentials(m_src, m_dst)
                    G.device.sh(f'cd "/sdcard/{G.internal}"; mkdir -p {end_dirs}')
                    for src, dst in zip(srcs, dsts):
                        G.device.sync.push(src, dst)

        time.sleep(1)
        G.transferring = False


class MyActions:
    actions = {}
    home: HomeW | None = None
    is_cut: bool
    tmp_clipboard = []

    @staticmethod
    def init(home):
        def run():
            if [it.toLocalFile() for it in QApplication.clipboard().mimeData().urls()] != MyActions.tmp_clipboard:
                MyActions.tmp_clipboard.clear()

        QApplication.clipboard().dataChanged.connect(run)
        MyActions.home = home
        separator = QAction()
        separator.setSeparator(True)
        MyActions.actions = {
            'open': QAction('開啟', home, enabled=False, shortcut=QKeySequence.StandardKey.Open, triggered=MyActions.open),
            'cut': QAction('剪下', home, enabled=False, shortcut=QKeySequence.StandardKey.Cut, triggered=lambda: MyActions.set_clipboard(True)),
            'copy': QAction('複製', home, enabled=False, shortcut=QKeySequence.StandardKey.Copy, triggered=lambda: MyActions.set_clipboard(False)),
            'delete': QAction('刪除', home, enabled=False, shortcut=QKeySequence.StandardKey.Delete, triggered=MyActions.delete),
            'rename': QAction('重新命名', home, enabled=False, shortcut=Qt.Key.Key_F2, triggered=MyActions.rename),
            '-': separator,
            'paste': QAction('貼上', home, enabled=False, shortcut=QKeySequence.StandardKey.Paste, triggered=MyActions.paste),
            'mkdir': QAction('新資料夾', home, enabled=False, shortcut=QKeySequence.StandardKey.New, triggered=MyActions.mkdir),
        }
        home.menu_bar.addActions(MyActions.actions.values())

    @staticmethod
    def connect():
        if MyActions.home.enter_explorer:
            items = G.home_w.list_widget.selectedItems()
            length = 2 if len(items) > 1 else len(items)
            foreground = items[0].foreground() if length else None
            args = (
                f'{'paste ' if G.are_local_files(QApplication.clipboard()) else ''}mkdir',
                f'{'open ' if foreground == QColor('white') else ''}cut copy delete rename',
                'cut copy delete'
            )[length].split(' ')
            MyActions.home.available_actions = [MyActions.actions[arg] for arg in args]
            for action in MyActions.actions.values():
                action.setEnabled(action in MyActions.home.available_actions)

    @staticmethod
    def open():
        MyActions.home.cd(None, MyActions.home.selected_texts()[0])

    @staticmethod
    def set_clipboard(is_cut: bool):
        MyActions.is_cut = is_cut
        MyActions.tmp_clipboard = [G.valid_internal(it) for it in MyActions.home.selected_texts()]
        QApplication.clipboard().setText('\n'.join(MyActions.tmp_clipboard))

    @staticmethod
    def delete():
        yes_btn = QMessageBox.StandardButton.Yes
        no_btn = QMessageBox.StandardButton.No
        if yes_btn == QMessageBox.warning(MyActions.home, '刪除檔案', '你確定要永久刪除這些檔案嗎？', yes_btn | no_btn):
            G.device.sh(' && '.join(f'rm -rf "/sdcard/{G.internal}/{file}"' for file in MyActions.home.selected_texts()))
            MyActions.home.cd(None, '')

    @staticmethod
    def rename():
        item = MyActions.home.list_widget.currentItem()
        original_name = item.text()
        MyActions.home.list_widget.editItem(item)

        def run(_):
            G.device.sh(f'cd "/sdcard/{G.internal}" && mv "{original_name}" "{item.text()}"')
            MyActions.home.list_widget.itemDelegate().closeEditor.disconnect()
            MyActions.home.cd(None, '')

        MyActions.home.list_widget.itemDelegate().closeEditor.connect(run)

    @staticmethod
    def paste():
        ...

    @staticmethod
    def mkdir():
        item = QListWidgetItem()
        item.setBackground(QColor('#765341'))
        item.setForeground(QColor('white'))
        MyActions.home.list_widget.addItem(item)
        MyActions.home.list_widget.editItem(item)

        def run(_):
            G.device.sh(f'cd "/sdcard/{G.internal}";mkdir "{item.text()}"')
            MyActions.home.cd(None, '')

        MyActions.home.list_widget.itemDelegate().closeEditor.connect(run)


class G:
    device: MyAdbDevice | None = None
    transferring = False
    internal = ''
    transfer_w: TransferD | None = None
    home_w: HomeW | None = None

    @staticmethod
    def delim(path: str) -> str:
        return re.sub('/+', '/', path.replace('\\', '/'))

    @staticmethod
    def valid_internal(branch: str) -> str:
        return f'{G.internal}/{branch}'.lstrip('/')

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
        length = round(length, 2) if length - int(length) else int(length)
        return f'{round(length) if is_round else length}{("B", "KB", "MB", "GB")[i]}'

    @staticmethod
    def are_local_files(a0) -> bool:
        return all(url.isLocalFile() for url in a0.mimeData().urls())

    @staticmethod
    def push_dir_essentials(m_src: str, m_dst: str) -> Tuple[str, List[str], List[str]]:
        path_parent = op.dirname(m_src)

        end_dirs = ''
        srcs = []
        dsts = []
        for r, ds, fs in os.walk(m_src):
            if not ds:
                end_dirs += f' "{G.delim(op.relpath(r, path_parent))}"'
            for f in fs:
                srcs.append(op.join(r, f))
                dsts.append(G.delim(op.join(m_dst, f)))
        return end_dirs, srcs, dsts


app = QApplication(sys.argv)
G.home_w = HomeW()
G.home_w.show()
sys.exit(app.exec())

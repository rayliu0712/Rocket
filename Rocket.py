#!/usr/bin/env python3
import hashlib
import os
import os.path as op
import re
import sys
import time
from typing import List, Callable, Tuple, Dict
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QStringListModel, QEvent
from PyQt6.QtGui import QColor, QKeySequence, QAction, QCursor
from PyQt6.QtWidgets import QWidget, QComboBox, QCompleter, QApplication, QVBoxLayout, QHBoxLayout, QPushButton, QListWidget, QLabel, QProgressBar, QMenu, QMainWindow, \
	QMessageBox, QLineEdit, QDialog, QListWidgetItem
from adbutils import adb, AdbDevice, ShellReturn


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

	def exist_count(self, paths: str | List[str]) -> bool | int:
		is_str = isinstance(paths, str)
		if is_str:
			paths = [paths]
		result = sum(line == '1' for line in self.shell(';'.join(f'([ -e "{path}" ] && echo 1 || echo 0)' for path in paths)))
		return bool(result) if is_str else result

	def get_total_size(self, paths: List[str]) -> int:
		output = self.shell(
			r"find # -type f -exec stat -c%s {} \; | awk '{sum += $1} END {print sum}'"
			.replace('#', ' '.join(f'"{path}"' for path in paths))
		)
		return int(output) if output.isdigit() else 0


bookmarks = {
	'Home': '/',
	'Download': '/Download/',
	'Pictures': '/Pictures/',
	'AstroDX': '/Android/data/com.Reflektone.AstroDX/files/levels/'
}
device: MyAdbDevice | None = None
internal = '/'
transferring = False


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


class MyLineEdit(QLineEdit):
	def focusOutEvent(self, event):
		if not home_w.should_remain_focus or not self.hasFocus():
			super().focusOutEvent(event)
		home_w.should_remain_focus = False

	def keyPressEvent(self, event):
		if event.key() in (Qt.Key.Key_Escape, Qt.Key.Key_Return, Qt.Key.Key_Enter):
			self.clearFocus()
		super().keyPressEvent(event)


class HomeW(QMainWindow):
	def __init__(self):
		super().__init__()
		self.setAcceptDrops(True)
		self.setWindowTitle('Rocket')
		self.resize(700, 500)
		self.should_thread_run = True
		self.should_remain_focus = False
		self.enter_explorer = False
		self.available_actions = []
		self.navi_comp_ds: List[str] = []
		self.navi_comp_prepwd: str | None = None

		self.menu_bar = self.menuBar().addMenu('File')
		MyActions.init(self)

		self.label = QLabel('None', self)
		self.back_btn = QPushButton('←', self, shortcut=QKeySequence.StandardKey.Back, clicked=lambda: self.cd(None, '..'))
		self.back_btn.setFixedWidth(self.back_btn.height())
		self.list_widget = MyListWidget(self, itemDoubleClicked=lambda item: self.cd(None, item.text()))
		self.list_widget.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
		self.list_widget.addItem('Enter explorer')
		self.list_widget.itemSelectionChanged.connect(lambda: MyActions.connect(self))
		self.navigator = MyLineEdit(self, textChanged=self.navi_comp_slot, editingFinished=lambda: self.cd(self.navigator.text(), ''))
		self.navi_comp = QCompleter(self)
		self.navi_comp_model = QStringListModel()
		self.navi_comp.setModel(self.navi_comp_model)
		self.navigator.setCompleter(self.navi_comp)

		top_hbox = QHBoxLayout()
		top_hbox.addWidget(self.label)
		top_hbox.addWidget(self.back_btn)
		top_hbox.addWidget(self.navigator, 1)

		btn_hbox = QHBoxLayout()
		for k, v in bookmarks.items():
			btn_hbox.addWidget(QPushButton(k, self, clicked=lambda _, v_=v: self.cd(v_, '')))

		central_widget = QWidget()
		self.setCentralWidget(central_widget)
		layout = QVBoxLayout()
		layout.addLayout(top_hbox)
		layout.addLayout(btn_hbox)
		layout.addWidget(self.list_widget)
		central_widget.setLayout(layout)
		self.setFocus()

		self.thread = Worker(self)
		self.thread.run = self.waiting_for_launch
		self.thread.sig.connect(lambda: self.label.setText(device.prop.name))
		self.thread.sig2.connect(TransferW.new)
		self.thread.start()

	def waiting_for_launch(self):
		global device, transferring

		while device is None and self.should_thread_run:
			device_list = adb.device_list()
			if device_list:
				device = MyAdbDevice(device_list[0])
				self.thread.sig.emit()

		while self.should_thread_run:
			sr = device.runas("cat ./files/launch.txt")
			if not transferring and sr.succeed:
				transferring = True
				device.runas('touch ./files/key_a')
				srcs = sr.output.splitlines()
				TransferW.set('pull', srcs)
				self.thread.sig2.emit()

	def navi_comp_slot(self, text: str):
		text = U.delim(text)
		pwd = re.sub(r'[^/]*$', '', text)
		if pwd == self.navi_comp_prepwd:
			return

		sr = device.sh(f'cd "/sdcard{text}" && find . -maxdepth 1 -type d ! -name . | sort')
		if sr.succeed:
			self.navi_comp_ds = [pwd + re.sub(r'^\./', '', d) for d in sr.output.splitlines()]
			self.navi_comp_prepwd = pwd
		else:
			self.navi_comp_ds = []
		self.navi_comp_model.setStringList(self.navi_comp_ds)
		self.should_remain_focus = True

	def cd(self, new_internal: str | None, branch: str):
		global internal
		if device is None:
			return

		if new_internal is None:
			new_internal = internal

		if not self.enter_explorer:
			self.enter_explorer = True
			branch = ''

		new_internal = U.delim(new_internal)
		sr = device.sh(f'cd "/sdcard{new_internal}{branch}" && pwd')
		if sr.output.startswith('/sdcard') and sr.succeed:
			internal = '/' + U.delim(re.sub('^/sdcard/*', '', sr.output))
			if internal != '/':
				internal += '/'
			ds = [re.sub(r'^\./', '', d) for d in device.shell(f'cd "/sdcard{internal}" && find . -maxdepth 1 -type d ! -name . | sort').splitlines()]
			fs = [re.sub(r'^\./', '', f) for f in device.shell(f'cd "/sdcard{internal}" && find . -maxdepth 1 -type f | sort').splitlines()]

			self.list_widget.clear()
			self.list_widget.addItems(ds + fs)
			for i in range(len(ds)):
				item = self.list_widget.item(i)
				item.setBackground(QColor('#765341'))
				item.setForeground(QColor('white'))

		self.navi_comp_prepwd = None
		self.navigator.setText(internal)

	def selected_texts(self) -> List[str]:
		return [item.text() for item in self.list_widget.selectedItems()]

	def contextMenuEvent(self, event):
		if self.available_actions and self.list_widget.underMouse():
			menu = QMenu(self)
			menu.addActions(self.available_actions)
			menu.exec(event.globalPos())

	def dragEnterEvent(self, event):
		if U.are_local_files(event):
			event.acceptProposedAction()

	def dropEvent(self, event):
		TransferW.set('push', [url.toLocalFile() for url in event.mimeData().urls()])
		TransferW.new()
		event.acceptProposedAction()

	def closeEvent(self, event):
		self.should_thread_run = False
		self.thread.wait()
		event.accept()


class TransferW(QDialog):
	srcs: List[str]
	dsts: List[str]
	is_files: List[str]
	total_size: int
	get_total_size: Callable[[List], int]
	exist_count: Callable[[List], int]
	mode: str

	@staticmethod
	def set(mode: str, srcs: List[str]):
		TransferW.mode = mode
		if mode == 'pull':
			TransferW.total_size = int(srcs.pop(0))
			TransferW.srcs = [src.split('\t')[0] for src in srcs]
			TransferW.is_files = [src.split('\t')[1] == '1' for src in srcs]
			TransferW.dsts = [U.safe_path(op.basename(a), b, op.exists) for a, b in zip(TransferW.srcs, TransferW.is_files)]
			TransferW.get_total_size = lambda paths: sum(U.local_size(path) for path in paths)
			TransferW.exist_count = lambda paths: sum(op.exists(path) for path in paths)
		elif mode == 'push':
			TransferW.total_size = sum(U.local_size(src) for src in srcs)
			TransferW.srcs = srcs
			TransferW.is_files = [op.isfile(src) for src in srcs]
			TransferW.dsts = [U.safe_path(f'/sdcard{internal}{op.basename(src)}', op.isdir(src), device.exist_count) for src in srcs]
			TransferW.get_total_size = device.get_total_size
			TransferW.exist_count = device.exist_count
		else:
			TransferW.total_size = device.get_total_size(srcs)
			TransferW.srcs = srcs
			TransferW.is_files = []
			TransferW.dsts = [f'/sdcard{internal}{op.basename(src)}' for src in srcs]
			TransferW.get_total_size = device.get_total_size
			TransferW.exist_count = device.exist_count

	@staticmethod
	def new():
		global transfer_w
		transfer_w = TransferW(home_w)
		transfer_w.setModal(True)
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

		transfer_t = Worker(self)
		transfer_t.run = self.transfer
		transfer_t.sig.connect(lambda: home_w.cd(None, '') if MyActions.paste_mode == 'push' else ...)
		transfer_t.finished.connect(self.close)
		transfer_t.start()

		super().show()

	def close(self):
		if TransferW.mode != 'pull' and home_w.enter_explorer:
			home_w.cd(None, '')
		super().close()

	def compute(self):
		try:
			self.__value = 0
			while self.__value < 100:
				self.__count = TransferW.exist_count(TransferW.dsts) - 1
				if self.__count == -1:
					self.__count = 0
				self.__size = TransferW.get_total_size(TransferW.dsts)
				self.__value = self.__size * 100 // TransferW.total_size
				self.compute_t.sig.emit()

		except ZeroDivisionError:
			self.compute_t.sig.emit()

	def update_ui(self):
		duration = time.time() - self.start_time
		velocity = self.__size / (duration if duration else 1)
		self.label.setText(
			f'{self.__count}/{len(TransferW.dsts)} File{"s" if len(TransferW.dsts) > 1 else ""}  |  ' +
			f'{round(duration)}s / {round((TransferW.total_size - self.__size) / (velocity if velocity else 1))}s  |  ' +
			f'{U.human_readable_size(velocity, True)}/s  |  ' +
			f'{U.human_readable_size(self.__size)}/{U.human_readable_size(TransferW.total_size)}')
		self.pbar.setValue(self.__value)
		self.setWindowTitle(f'{self.__value}%')

	def transfer(self):
		if TransferW.mode == 'pull':
			for src, dst in zip(TransferW.srcs, TransferW.dsts):
				device.sync.pull(src, dst)
			device.runas('touch ./files/key_b')
		elif TransferW.mode == 'push':
			for m_src, m_dst, is_file in zip(TransferW.srcs, TransferW.dsts, TransferW.is_files):
				if is_file:
					device.sync.push(m_src, m_dst)
				else:
					end_dirs, srcs, dsts = self.push_dir_essentials(m_src, m_dst)
					device.sh(f'cd "/sdcard{internal}" && mkdir -p {end_dirs}')
					for src, dst in zip(srcs, dsts):
						device.sync.push(src, dst)
		else:
			device.sh(';'.join(f'cp -r "{src}" "/sdcard{internal}"' for src in TransferW.srcs))

		time.sleep(1)
		global transferring
		transferring = False

	def push_dir_essentials(self, m_src: str, m_dst: str) -> Tuple[str, List[str], List[str]]:
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


class MyActions:
	actions: Dict[str, QAction] = {}
	paste_mode: str | None = None
	internal_clipboard: List[str] = []

	@staticmethod
	def init(home: HomeW):
		def slot():
			if U.are_local_files(clipboard):
				MyActions.set_paste('push', [url.toLocalFile() for url in clipboard.mimeData().urls()])
			else:
				MyActions.set_paste(None, [])
			MyActions.connect(home)

		clipboard.dataChanged.connect(slot)
		separator = QAction()
		separator.setSeparator(True)
		MyActions.actions = {
			'open': QAction('開啟', home, enabled=False, shortcut=QKeySequence.StandardKey.Open, triggered=MyActions.open),
			'cut': QAction('剪下', home, enabled=False, shortcut=QKeySequence.StandardKey.Cut, triggered=lambda: MyActions.internal_clip('cut')),
			'copy': QAction('複製', home, enabled=False, shortcut=QKeySequence.StandardKey.Copy, triggered=lambda: MyActions.internal_clip('copy')),
			'delete': QAction('刪除', home, enabled=False, shortcut=QKeySequence.StandardKey.Delete, triggered=MyActions.delete),
			'rename': QAction('重新命名', home, enabled=False, shortcut=Qt.Key.Key_F2, triggered=MyActions.rename),
			'download': QAction('下載', home, enabled=False, triggered=MyActions.download),
			'-': separator,
			'paste': QAction('貼上', home, enabled=False, shortcut=QKeySequence.StandardKey.Paste, triggered=MyActions.paste),
			'mkdir': QAction('新資料夾', home, enabled=False, shortcut=QKeySequence.StandardKey.New, triggered=MyActions.mkdir),
		}
		home.menu_bar.addActions(MyActions.actions.values())

	@staticmethod
	def connect(home: HomeW):
		items = home.list_widget.selectedItems()
		if not home.enter_explorer:
			return
		elif not items:
			args = 'paste mkdir'
		elif len(items) == 1:
			args = f'{"open " if items[0].foreground() == QColor("white") else ""}cut copy delete rename download'
		else:
			args = 'cut copy delete download'

		home.available_actions = [MyActions.actions[arg] for arg in args.split()]
		for k, action in MyActions.actions.items():
			is_available = action in home.available_actions
			action.setEnabled(is_available and MyActions.paste_mode is not None if k == 'paste' else is_available)

	@staticmethod
	def internal_clip(paste_mode):
		MyActions.set_paste(paste_mode, [internal + file for file in home_w.selected_texts()])

	@staticmethod
	def set_paste(paste_mode: str | None, internal_clipboard: List[str]):
		MyActions.paste_mode = paste_mode
		MyActions.internal_clipboard = internal_clipboard

	@staticmethod
	def open():
		home_w.cd(None, home_w.selected_texts()[0])

	@staticmethod
	def delete():
		yes_btn = QMessageBox.StandardButton.Yes
		no_btn = QMessageBox.StandardButton.No
		if yes_btn == QMessageBox.warning(home_w, '刪除檔案', '你確定要永久刪除這些檔案嗎？', yes_btn | no_btn):
			device.sh(' && '.join(f'rm -rf "/sdcard{internal}{file}"' for file in home_w.selected_texts()))
			home_w.cd(None, '')

	@staticmethod
	def rename():
		item = home_w.list_widget.currentItem()
		original_name = item.text()
		home_w.list_widget.editItem(item)

		def slot(_):
			device.sh(f'cd "/sdcard{internal}" && mv "{original_name}" "{item.text()}"')
			home_w.list_widget.itemDelegate().closeEditor.disconnect()
			home_w.cd(None, '')

		home_w.list_widget.itemDelegate().closeEditor.connect(slot)

	@staticmethod
	def download():
		srcs = [f'/sdcard{internal}{file}' for file in home_w.selected_texts()]
		total_size = device.get_total_size(srcs)
		for i, is_file in enumerate(device.shell(';'.join(f'([ -f "{src}" ] && echo 1 || echo 0)' for src in srcs)).splitlines()):
			srcs[i] += '\t' + is_file
		srcs.insert(0, str(total_size))

		TransferW.set('pull', srcs)
		TransferW.new()

	@staticmethod
	def paste():
		if MyActions.paste_mode == 'cut':
			device.sh(';'.join(f'mv "/sdcard/{file}" "/sdcard/{internal}"' for file in MyActions.internal_clipboard))
			home_w.cd(None, '')
		else:
			TransferW.set(MyActions.paste_mode, ['/sdcard' + file for file in MyActions.internal_clipboard])
			TransferW.new()

	@staticmethod
	def mkdir():
		item = QListWidgetItem()
		item.setBackground(QColor('#765341'))
		item.setForeground(QColor('white'))
		home_w.list_widget.addItem(item)
		home_w.list_widget.editItem(item)

		def slot(_):
			device.sh(f'cd "/sdcard/{internal}" && mkdir "{item.text()}"')
			home_w.list_widget.itemDelegate().closeEditor.disconnect()
			home_w.cd(None, '')

		home_w.list_widget.itemDelegate().closeEditor.connect(slot)


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
		length = round(length, 2) if length - int(length) else int(length)
		return f'{round(length) if is_round else length}{("B", "KB", "MB", "GB")[i]}'

	@staticmethod
	def are_local_files(mime_datable) -> bool:
		urls = mime_datable.mimeData().urls()
		if not urls:
			return False
		return all(url.isLocalFile() for url in urls)


app = QApplication(sys.argv)
clipboard = QApplication.clipboard()
transfer_w: TransferW
home_w = HomeW()
home_w.show()
sys.exit(app.exec())

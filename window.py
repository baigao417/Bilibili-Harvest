import os
import queue
import re
import shutil
import sys
import threading
import uuid
import webbrowser
import winreg
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import Optional

# Preload torch runtime before PyQt5 import to avoid DLL init conflicts.
TORCH_PRELOAD_ERROR = None
try:
    import torch  # noqa: F401
except Exception as preload_exc:
    TORCH_PRELOAD_ERROR = preload_exc

from PyQt5.QtCore import QObject, Qt, pyqtSignal
from PyQt5.QtGui import QFont, QGuiApplication, QIcon, QTextCursor
from PyQt5.QtWidgets import (
    QAction,
    QButtonGroup,
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QGroupBox,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QMenu,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QSpinBox,
    QSystemTrayIcon,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

import qdarkstyle

import speech2text as s2t
from bili_subtitle_api import (
    ApiTrack,
    BiliSubtitleAPIError,
    discover_bili_tracks,
    ensure_task_identifiers,
    fetch_bili_track_segments,
    validate_cookie_login,
)
from exAudio import convert_flv_to_mp3, process_audio_split
from runtime_tools import find_executable, resolve_cookies_file, run_command, should_retry_error
from subtitle_pipeline import (
    DEFAULT_SHAPE_ROOT,
    build_md_content,
    dump_segments_to_tmp_json,
    export_batch_selected,
    render_notebooklm_title,
    SubtitleError,
    TrackInfo,
    _load_task_segments,
    discover_tracks_with_meta,
    download_track_srt,
    parse_srt_to_segments,
    select_track,
    write_failed_tasks_json,
)
from app_version import CORE_VERSION, STATE_SCHEMA_VERSION
from core_models import BatchContext, FailStage, StageFailure, TaskItem, TaskStatus
from local_api_server import LocalApiServer
from plugins.types import SourceItem
from runtime_config import RuntimeConfig, generate_api_token, load_runtime_config, save_runtime_config
from state_store import find_latest_state_file, load_batch_state, save_batch_state, task_from_state_row
from subtitle_sources import (
    SourceResolveError,
    get_source_plugin_manager,
    reload_source_plugin_manager,
    resolve_collection_series,
    resolve_favorite,
    resolve_single_or_bv,
    resolve_source_auto,
    resolve_space_uploads,
)
from utils import download_video, download_video_prefer_1080, find_primary_media_file, infer_download_title
import notebooklm_client as nlm_client


SHAPE_ROOT = DEFAULT_SHAPE_ROOT


SOURCE_TYPE_LABELS = {
    "single": "单视频",
    "multi_p": "分P",
    "favorite": "收藏夹",
    "collection": "合集",
    "series": "列表",
    "space_uploads": "主页投稿",
}


def source_item_to_task(seq: int, raw_input: str, item: SourceItem) -> TaskItem:
    return TaskItem(
        seq=seq,
        raw_input=raw_input,
        video_link=item.video_url or f"https://www.bilibili.com/video/{item.bvid}",
        bv=item.bvid,
        aid=item.aid,
        cid=item.cid,
        owner=item.owner or "UnknownUP",
        source_type=item.source_type or "single",
        source_meta=dict(item.source_meta or {}),
        page=item.page,
        page_title=item.page_title or "",
        title=item.title or "UnknownTitle",
    )


EXTRA_QSS = """
QLabel#titleLabel {
    font-size: 22px;
    font-weight: bold;
    padding: 6px 0;
    color: #58b9ff;
}
QPushButton {
    font-size: 12px;
    padding: 6px 14px;
    border-radius: 4px;
}
QPushButton#btnPrimary {
    background-color: #2979ff;
    color: #fff;
    border: none;
}
QPushButton#btnPrimary:hover {
    background-color: #448aff;
}
QLineEdit, QPlainTextEdit, QComboBox {
    font-size: 13px;
}
QTableWidget {
    font-size: 12px;
}
QTextEdit#logPanel {
    font-family: "Cascadia Code", "Consolas", monospace;
    font-size: 12px;
}
"""


class StdoutRedirector(QObject):
    text_written = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.buffer = ""

    def write(self, message):
        if not message:
            return
        self.buffer += message
        while "\n" in self.buffer:
            line, self.buffer = self.buffer.split("\n", 1)
            if line.strip():
                self.text_written.emit(line)

    def flush(self):
        if self.buffer.strip():
            self.text_written.emit(self.buffer)
        self.buffer = ""

    def isatty(self):
        return False


class ExportOptionsDialog(QDialog):
    def __init__(self, parent=None, *, nlm_enabled: bool = False, nlm_notebook_id: str = "", nlm_auto_clean: bool = True):
        super().__init__(parent)
        self.setWindowTitle("选择字幕导出格式")
        self.setModal(True)

        layout = QVBoxLayout(self)

        # ─── File format group ───
        fmt_group = QGroupBox("文件格式")
        fmt_layout = QVBoxLayout(fmt_group)
        self.chk_srt = QCheckBox("SRT（时间轴字幕）")
        self.chk_txt = QCheckBox("TXT（纯文本）")
        self.chk_md = QCheckBox("MD（Markdown）")
        self.chk_zip = QCheckBox("同时生成 ZIP")

        self.chk_srt.setChecked(False)
        self.chk_txt.setChecked(False)
        self.chk_md.setChecked(True)
        self.chk_zip.setChecked(False)

        fmt_layout.addWidget(self.chk_srt)
        fmt_layout.addWidget(self.chk_txt)
        fmt_layout.addWidget(self.chk_md)
        fmt_layout.addWidget(self.chk_zip)
        layout.addWidget(fmt_group)

        # ─── NotebookLM group ───
        nlm_group = QGroupBox("NotebookLM 推送")
        nlm_layout = QVBoxLayout(nlm_group)

        # Auth status row
        auth_row = QHBoxLayout()
        self._nlm_auth_label = QLabel("检测中…")
        auth_row.addWidget(self._nlm_auth_label)
        auth_row.addStretch()
        self.btn_nlm_login = QPushButton("登录 NotebookLM")
        self.btn_nlm_login.clicked.connect(self._do_nlm_login)
        self.btn_nlm_login.setVisible(False)
        auth_row.addWidget(self.btn_nlm_login)
        nlm_layout.addLayout(auth_row)

        self.chk_nlm = QCheckBox("推送到 NotebookLM（不保存到本地资料库的任务）")
        self.chk_nlm.setChecked(False)
        self.chk_nlm.setEnabled(False)
        if not nlm_client.is_nlm_available():
            self.chk_nlm.setToolTip("notebooklm-py 未安装，无法推送")
        nlm_layout.addWidget(self.chk_nlm)

        nb_row = QHBoxLayout()
        nb_row.addWidget(QLabel("目标 Notebook:"))
        self.combo_notebook = QComboBox()
        self.combo_notebook.setMinimumWidth(280)
        self.combo_notebook.setEditable(False)
        nb_row.addWidget(self.combo_notebook, 1)

        self.btn_refresh_nb = QPushButton("刷新")
        self.btn_refresh_nb.clicked.connect(self._refresh_notebooks)
        nb_row.addWidget(self.btn_refresh_nb)

        self.btn_create_nb = QPushButton("新建")
        self.btn_create_nb.clicked.connect(self._create_notebook)
        nb_row.addWidget(self.btn_create_nb)

        nlm_layout.addLayout(nb_row)

        self.chk_nlm_clean = QCheckBox("推送成功后自动清理本地临时文件")
        self.chk_nlm_clean.setChecked(nlm_auto_clean)
        nlm_layout.addWidget(self.chk_nlm_clean)

        layout.addWidget(nlm_group)

        # When NLM is checked, gray out file format checkboxes and auto-enable MD
        self.chk_nlm.toggled.connect(self._on_nlm_toggled)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        # Pre-populate notebooks & check auth
        self._nlm_notebook_id = nlm_notebook_id
        self._nlm_desired_enabled = nlm_enabled
        if nlm_client.is_nlm_available():
            self._check_nlm_auth()

    def _check_nlm_auth(self):
        """Check NLM auth status, auto-refresh if expired, update UI."""
        QApplication.processEvents()
        status = nlm_client.ensure_auth_valid()
        if status == nlm_client.AuthStatus.VALID:
            self._nlm_auth_label.setText("✓ 已登录 NotebookLM")
            self._nlm_auth_label.setStyleSheet("color: #4caf50;")
            self.chk_nlm.setEnabled(True)
            self.chk_nlm.setChecked(self._nlm_desired_enabled)
            self.btn_nlm_login.setVisible(False)
            self._refresh_notebooks()
        elif status == nlm_client.AuthStatus.COOKIES_FOUND:
            self._nlm_auth_label.setText("⚠ Cookies 已保存（无法验证）")
            self._nlm_auth_label.setStyleSheet("color: #ff9800;")
            self.chk_nlm.setEnabled(True)
            self.chk_nlm.setChecked(self._nlm_desired_enabled)
            self.btn_nlm_login.setVisible(True)
            self._refresh_notebooks()
        elif status == nlm_client.AuthStatus.EXPIRED:
            self._nlm_auth_label.setText("✗ 登录已过期，请重新登录")
            self._nlm_auth_label.setStyleSheet("color: #f44336;")
            self.chk_nlm.setEnabled(False)
            self.chk_nlm.setChecked(False)
            self.btn_nlm_login.setVisible(True)
        elif status == nlm_client.AuthStatus.NOT_CONFIGURED:
            self._nlm_auth_label.setText("✗ 未登录，请先登录 NotebookLM")
            self._nlm_auth_label.setStyleSheet("color: #f44336;")
            self.chk_nlm.setEnabled(False)
            self.chk_nlm.setChecked(False)
            self.btn_nlm_login.setVisible(True)
        else:
            self._nlm_auth_label.setText("✗ notebooklm-py 未安装")
            self._nlm_auth_label.setStyleSheet("color: #999;")
            self.chk_nlm.setEnabled(False)
            self.btn_nlm_login.setVisible(False)

    def _do_nlm_login(self):
        """Open the Playwright login dialog, then recheck auth."""
        login_dialog = NotebookLMLoginDialog(self)
        login_dialog.exec_()
        if login_dialog.login_succeeded():
            self._check_nlm_auth()

    def _on_nlm_toggled(self, checked: bool):
        """When NLM push is selected, disable format selectors (non-Shape tasks skip local files)."""
        self.chk_srt.setEnabled(not checked)
        self.chk_txt.setEnabled(not checked)
        self.chk_md.setEnabled(not checked)
        self.chk_zip.setEnabled(not checked)

    def _refresh_notebooks(self):
        self.combo_notebook.clear()
        try:
            notebooks = nlm_client.list_notebooks()
            for nb in notebooks:
                self.combo_notebook.addItem(f"{nb['title']}", nb["id"])
            # Re-select the previously chosen notebook
            if self._nlm_notebook_id:
                idx = self.combo_notebook.findData(self._nlm_notebook_id)
                if idx >= 0:
                    self.combo_notebook.setCurrentIndex(idx)
        except Exception as exc:
            self.combo_notebook.addItem(f"加载失败: {exc}")

    def _create_notebook(self):
        from PyQt5.QtWidgets import QInputDialog
        name, ok = QInputDialog.getText(self, "新建 Notebook", "Notebook 名称:")
        if not ok or not name.strip():
            return
        try:
            nb = nlm_client.create_notebook(name.strip())
            self.combo_notebook.addItem(f"{nb['title']}", nb["id"])
            self.combo_notebook.setCurrentIndex(self.combo_notebook.count() - 1)
        except Exception as exc:
            QMessageBox.warning(self, "创建失败", str(exc))

    def selected_formats(self):
        formats = set()
        if self.chk_srt.isChecked():
            formats.add("srt")
        if self.chk_txt.isChecked():
            formats.add("txt")
        if self.chk_md.isChecked():
            formats.add("md")
        return formats

    def export_zip(self):
        return self.chk_zip.isChecked()

    def nlm_push_enabled(self) -> bool:
        return self.chk_nlm.isChecked()

    def nlm_notebook_id(self) -> str:
        return self.combo_notebook.currentData() or ""

    def nlm_auto_clean(self) -> bool:
        return self.chk_nlm_clean.isChecked()


class NotebookLMLoginDialog(QDialog):
    """Modal dialog that opens a Playwright Chromium window for Google login."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("NotebookLM 登录")
        self.setModal(True)
        self.resize(400, 160)

        layout = QVBoxLayout(self)
        self._status_label = QLabel("点击下方按钮，将打开 Chromium 浏览器进行 Google 登录。")
        self._status_label.setWordWrap(True)
        layout.addWidget(self._status_label)

        self.btn_login = QPushButton("打开浏览器登录")
        self.btn_login.clicked.connect(self._do_login)
        layout.addWidget(self.btn_login)

        self.btn_close = QPushButton("关闭")
        self.btn_close.clicked.connect(self.reject)
        layout.addWidget(self.btn_close)

        self._cancel = False
        self._success = False

    def _do_login(self):
        self.btn_login.setEnabled(False)
        self._status_label.setText("浏览器已打开，请在浏览器中完成 Google 登录...")
        QApplication.processEvents()

        def _on_status(msg: str):
            # Will be called from the same thread since run_browser_login is sync
            self._status_label.setText(msg)
            QApplication.processEvents()

        try:
            self._success = nlm_client.run_browser_login(
                on_status=_on_status,
                cancel_flag=lambda: self._cancel,
                timeout=300,
            )
        except Exception as exc:
            self._status_label.setText(f"登录出错: {exc}")
            self.btn_login.setEnabled(True)
            return

        if self._success:
            self._status_label.setText("登录成功！Cookie 已保存。")
            self.btn_login.setEnabled(False)
        else:
            self._status_label.setText("登录未完成，请重试。")
            self.btn_login.setEnabled(True)

    def closeEvent(self, event):
        self._cancel = True
        super().closeEvent(event)

    def login_succeeded(self) -> bool:
        return self._success


class ServiceSettingsDialog(QDialog):
    def __init__(self, config: RuntimeConfig, parent=None):
        super().__init__(parent)
        self.setWindowTitle("服务设置")
        self.setModal(True)
        self._token_overridden = None

        layout = QVBoxLayout(self)
        basic_group = QGroupBox("基础设置")
        basic_grid = QGridLayout()
        basic_grid.setHorizontalSpacing(8)
        basic_grid.setVerticalSpacing(6)
        basic_group.setLayout(basic_grid)

        self.chk_http_enabled = QCheckBox("启用本地 HTTP 服务")
        self.chk_http_enabled.setChecked(bool(config.http_enabled))
        basic_grid.addWidget(self.chk_http_enabled, 0, 0, 1, 3)

        basic_grid.addWidget(QLabel("端口"), 1, 0)
        self.spin_port = QSpinBox()
        self.spin_port.setRange(1024, 65535)
        self.spin_port.setValue(int(config.http_port))
        basic_grid.addWidget(self.spin_port, 1, 1)

        basic_grid.addWidget(QLabel("扫描窗口"), 1, 2)
        self.spin_window = QSpinBox()
        self.spin_window.setRange(1, 100)
        self.spin_window.setValue(int(config.http_port_scan_window))
        basic_grid.addWidget(self.spin_window, 1, 3)

        basic_grid.addWidget(QLabel("I/O并发"), 2, 0)
        self.spin_workers = QSpinBox()
        self.spin_workers.setRange(1, 4)
        self.spin_workers.setValue(int(config.io_workers))
        basic_grid.addWidget(self.spin_workers, 2, 1)

        basic_hint = QLabel("默认配置已可直接使用。仅在你需要更严格的来源控制时再打开高级安全设置。")
        basic_hint.setStyleSheet("color:#7f8fa4; font-size:11px;")
        basic_grid.addWidget(basic_hint, 3, 0, 1, 4)
        layout.addWidget(basic_group)

        self.advanced_group = QGroupBox("高级安全设置（可折叠）")
        self.advanced_group.setCheckable(True)
        should_expand_advanced = bool(config.extension_ids)
        self.advanced_group.setChecked(bool(should_expand_advanced))
        advanced_group_layout = QVBoxLayout(self.advanced_group)
        advanced_group_layout.setContentsMargins(8, 10, 8, 8)
        advanced_group_layout.setSpacing(0)
        self.advanced_panel = QWidget()
        advanced_group_layout.addWidget(self.advanced_panel)
        self.advanced_group.toggled.connect(self._on_advanced_group_toggled)

        advanced_grid = QGridLayout(self.advanced_panel)
        advanced_grid.setHorizontalSpacing(8)
        advanced_grid.setVerticalSpacing(6)
        self.lbl_advanced_hint = QLabel("可选：填写 extension_id 白名单并重置 Token，可提高本机安全隔离。")
        self.lbl_advanced_hint.setStyleSheet("color:#7f8fa4; font-size:11px;")
        advanced_grid.addWidget(self.lbl_advanced_hint, 0, 0, 1, 4)

        advanced_grid.addWidget(QLabel("扩展ID(逗号分隔)"), 1, 0)
        self.edit_extension_ids = QLineEdit(", ".join(config.extension_ids))
        advanced_grid.addWidget(self.edit_extension_ids, 1, 1, 1, 3)
        self.lbl_extension_hint = QLabel("提示：可在浏览器插件弹窗中复制 Extension ID 后粘贴到这里。")
        self.lbl_extension_hint.setStyleSheet("color:#7f8fa4; font-size:11px;")
        advanced_grid.addWidget(self.lbl_extension_hint, 2, 0, 1, 4)

        advanced_grid.addWidget(QLabel("API Token"), 3, 0)
        self.edit_token = QLineEdit(config.api_token)
        self.edit_token.setReadOnly(True)
        advanced_grid.addWidget(self.edit_token, 3, 1, 1, 2)
        self.btn_reset_token = QPushButton("重置Token")
        self.btn_reset_token.clicked.connect(self._on_reset_token)
        advanced_grid.addWidget(self.btn_reset_token, 3, 3)
        layout.addWidget(self.advanced_group)
        self._on_advanced_group_toggled(self.advanced_group.isChecked())

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _on_reset_token(self):
        self._token_overridden = generate_api_token()
        self.edit_token.setText(self._token_overridden)

    def _on_advanced_group_toggled(self, checked: bool):
        self.advanced_panel.setVisible(bool(checked))

    def result_config(self, base: RuntimeConfig) -> RuntimeConfig:
        extension_ids = [item.strip() for item in self.edit_extension_ids.text().split(",") if item.strip()]
        token = self.edit_token.text().strip() or base.api_token
        return RuntimeConfig(
            http_enabled=self.chk_http_enabled.isChecked(),
            http_host=base.http_host,
            http_port=self.spin_port.value(),
            http_port_scan_window=self.spin_window.value(),
            api_token=token,
            extension_ids=extension_ids,
            io_workers=self.spin_workers.value(),
            plugin_scan_enabled=base.plugin_scan_enabled,
            notebooklm_enabled=base.notebooklm_enabled,
            notebooklm_notebook_id=base.notebooklm_notebook_id,
            notebooklm_auto_clean=base.notebooklm_auto_clean,
            archive_root=base.archive_root,
        )


class PluginManagerDialog(QDialog):
    def __init__(self, plugins: list[dict], scan_enabled: bool, running_batch: bool, parent=None):
        super().__init__(parent)
        self.setWindowTitle("插件管理")
        self.setModal(True)
        self._running_batch = running_batch
        self._reload_requested = False

        layout = QVBoxLayout(self)

        top = QHBoxLayout()
        self.chk_scan = QCheckBox("启用目录扫描")
        self.chk_scan.setChecked(bool(scan_enabled))
        self.chk_scan.setEnabled(not running_batch)
        top.addWidget(self.chk_scan)
        self.btn_reload = QPushButton("手动重载")
        self.btn_reload.setEnabled(not running_batch)
        self.btn_reload.clicked.connect(self._on_reload_clicked)
        top.addWidget(self.btn_reload)
        top.addStretch()
        layout.addLayout(top)

        self.table = QTableWidget()
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels(["启用", "ID", "版本", "内置", "必需"])
        self.table.verticalHeader().setVisible(False)
        self.table.setRowCount(len(plugins))
        for row, item in enumerate(plugins):
            enabled_chk = QCheckBox()
            enabled_chk.setChecked(bool(item.get("enabled")))
            if item.get("builtin") and item.get("required"):
                enabled_chk.setChecked(True)
                enabled_chk.setEnabled(False)
            elif running_batch:
                enabled_chk.setEnabled(False)

            w = QWidget()
            l = QHBoxLayout(w)
            l.setContentsMargins(4, 0, 4, 0)
            l.addWidget(enabled_chk)
            l.addStretch()
            self.table.setCellWidget(row, 0, w)
            self.table.setItem(row, 1, QTableWidgetItem(str(item.get("id") or "")))
            self.table.setItem(row, 2, QTableWidgetItem(str(item.get("version") or "")))
            self.table.setItem(row, 3, QTableWidgetItem("yes" if item.get("builtin") else ""))
            self.table.setItem(row, 4, QTableWidgetItem("yes" if item.get("required") else ""))
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        layout.addWidget(self.table)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def enabled_map(self) -> dict[str, bool]:
        result = {}
        for row in range(self.table.rowCount()):
            plugin_id_item = self.table.item(row, 1)
            plugin_id = plugin_id_item.text().strip() if plugin_id_item else ""
            if not plugin_id:
                continue
            holder = self.table.cellWidget(row, 0)
            enabled = True
            if holder is not None:
                chk = holder.findChild(QCheckBox)
                if chk is not None:
                    enabled = bool(chk.isChecked())
            result[plugin_id] = enabled
        return result

    def should_reload(self) -> bool:
        return bool(self._reload_requested)

    def scan_enabled(self) -> bool:
        return bool(self.chk_scan.isChecked())

    def _on_reload_clicked(self):
        if not self.btn_reload.isEnabled():
            return
        self._reload_requested = True
        QMessageBox.information(self, "提示", "已标记重载，点击“确定”后生效。")


class MainWindow(QMainWindow):
    progress_signal = pyqtSignal(int, int, str)
    batch_finished_signal = pyqtSignal(object)
    table_refresh_signal = pyqtSignal()
    api_command_signal = pyqtSignal()
    nlm_push_finished_signal = pyqtSignal(object)   # NlmPushResult

    def __init__(self, *, force_http_enabled: bool = False):
        super().__init__()
        self.setWindowTitle("BilibiliHarvest - SubBatch 工作台")
        self.resize(1200, 800)

        self._runtime_config = load_runtime_config()
        self._force_http_enabled = bool(force_http_enabled)
        self._state_lock = threading.Lock()
        self._media_cache_lock = threading.Lock()
        self._asr_semaphore = threading.Semaphore(1)
        self._current_batch: Optional[BatchContext] = None
        self._last_batch: Optional[BatchContext] = None
        self._current_stage_text = "就绪"
        self._stop_requested = False
        self._worker_thread: Optional[threading.Thread] = None
        self._http_server: Optional[LocalApiServer] = None
        self._http_server_port: int = 0
        self._api_command_queue: queue.Queue = queue.Queue()
        self._resume_from_state: str = ""

        # NLM push state
        self._nlm_push_thread: Optional[threading.Thread] = None
        self._nlm_push_cancel = False
        self._nlm_push_jobs: dict[str, object] = {}   # {job_id: NlmPushResult or None}

        self._tasks: list[TaskItem] = []
        self._task_key_set = set()
        self._seq_counter = 0
        self._quit_requested = False
        self._tray_icon: Optional[QSystemTrayIcon] = None

        try:
            self.setWindowIcon(QIcon("favicon.ico"))
        except Exception:
            pass

        self._build_ui()
        self._build_tray()
        self._install_redirector()
        get_source_plugin_manager(enable_scan=self._runtime_config.plugin_scan_enabled)
        self.progress_signal.connect(self._on_progress)
        self.batch_finished_signal.connect(self._on_batch_finished)
        self.table_refresh_signal.connect(self._refresh_table)
        self.api_command_signal.connect(self._process_api_commands)
        self.nlm_push_finished_signal.connect(self._on_nlm_push_finished)

        self._check_runtime_dependencies()
        if self._runtime_config.http_enabled or self._force_http_enabled:
            self._start_local_http_service()

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)

        root = QVBoxLayout(central)
        root.setContentsMargins(18, 14, 18, 10)
        root.setSpacing(10)

        title = QLabel("BilibiliHarvest - 字幕批量处理")
        title.setObjectName("titleLabel")
        title.setAlignment(Qt.AlignCenter)
        root.addWidget(title)

        cookie_grid = QGridLayout()
        cookie_grid.setHorizontalSpacing(8)
        cookie_grid.setVerticalSpacing(6)

        cookie_grid.addWidget(QLabel("Cookie模式"), 0, 0)
        self.cookie_mode_combo = QComboBox()
        self.cookie_mode_combo.addItem("自动(Chrome优先)", "auto_chrome")
        self.cookie_mode_combo.addItem("cookies.txt", "cookies_file")
        self.cookie_mode_combo.addItem("无Cookie", "none")
        cookie_grid.addWidget(self.cookie_mode_combo, 0, 1)

        cookie_grid.addWidget(QLabel("Cookie Header"), 0, 2)
        self.cookie_input = QLineEdit()
        self.cookie_input.setPlaceholderText("可选：粘贴 Cookie 请求头（用于 API 导入增强）")
        cookie_grid.addWidget(self.cookie_input, 0, 3)

        self.btn_load_cookie_file = QPushButton("从cookies.txt载入")
        self.btn_load_cookie_file.clicked.connect(self._load_cookie_header_from_file)
        cookie_grid.addWidget(self.btn_load_cookie_file, 0, 4)

        root.addLayout(cookie_grid)

        self.import_group = QGroupBox("导入源（可折叠）")
        self.import_group.setCheckable(True)
        self.import_group.setChecked(True)
        import_group_layout = QVBoxLayout(self.import_group)
        import_group_layout.setContentsMargins(8, 10, 8, 8)
        import_group_layout.setSpacing(0)

        self.import_panel = QWidget()
        import_group_layout.addWidget(self.import_panel)
        self.import_group.toggled.connect(self._on_import_group_toggled)

        import_grid = QGridLayout(self.import_panel)
        import_grid.setHorizontalSpacing(8)
        import_grid.setVerticalSpacing(6)

        import_grid.addWidget(QLabel("源类型"), 0, 0)
        self.source_type_combo = QComboBox()
        self.source_type_combo.addItem("自动识别", "auto")
        self.source_type_combo.addItem("单个视频", "single")
        self.source_type_combo.addItem("分P", "multi_p")
        self.source_type_combo.addItem("收藏夹", "favorite")
        self.source_type_combo.addItem("合集", "collection")
        self.source_type_combo.addItem("视频选集", "series")
        self.source_type_combo.addItem("个人主页", "space_uploads")
        self.source_type_combo.currentIndexChanged.connect(self._on_source_type_changed)
        import_grid.addWidget(self.source_type_combo, 0, 1)

        import_grid.addWidget(QLabel("输入"), 0, 2)
        self.unified_input = QLineEdit()
        self.unified_input.setPlaceholderText("输入 URL / BV / MID / season:id / series:id / ml{id}")
        self.unified_input.returnPressed.connect(self._on_add_from_unified_input)
        import_grid.addWidget(self.unified_input, 0, 3, 1, 3)

        self.btn_paste_clipboard = QPushButton("读取剪贴板")
        self.btn_paste_clipboard.clicked.connect(self._on_use_clipboard_input)
        import_grid.addWidget(self.btn_paste_clipboard, 0, 6)

        self.btn_add_source = QPushButton("添加")
        self.btn_add_source.setObjectName("btnPrimary")
        self.btn_add_source.clicked.connect(self._on_add_from_unified_input)
        import_grid.addWidget(self.btn_add_source, 0, 7)

        import_grid.addWidget(QLabel("导入模式"), 1, 0)
        mode_holder = QWidget()
        mode_layout = QHBoxLayout(mode_holder)
        mode_layout.setContentsMargins(0, 0, 0, 0)
        mode_layout.setSpacing(12)
        self.radio_single = QRadioButton("单视频")
        self.radio_all_pages = QRadioButton("分P")
        self.radio_single.setChecked(True)
        self.import_mode_group = QButtonGroup(self)
        self.import_mode_group.addButton(self.radio_single)
        self.import_mode_group.addButton(self.radio_all_pages)
        mode_layout.addWidget(self.radio_single)
        mode_layout.addWidget(self.radio_all_pages)
        mode_layout.addStretch()
        import_grid.addWidget(mode_holder, 1, 1, 1, 2)

        import_grid.addWidget(QLabel("主页上限"), 1, 3)
        self.space_limit_spin = QSpinBox()
        self.space_limit_spin.setRange(1, 2000)
        self.space_limit_spin.setValue(200)
        import_grid.addWidget(self.space_limit_spin, 1, 4)

        import_grid.addWidget(QLabel("排序"), 1, 5)
        self.order_combo = QComboBox()
        self.order_combo.addItem("最新优先", "pubdate_desc")
        self.order_combo.addItem("最早优先", "pubdate_asc")
        import_grid.addWidget(self.order_combo, 1, 6)

        self.chk_multiline = QCheckBox("按换行批量添加")
        self.chk_multiline.setChecked(False)
        import_grid.addWidget(self.chk_multiline, 1, 7)

        root.addWidget(self.import_group)

        action_row = QHBoxLayout()
        self.btn_load = QPushButton("加载 Whisper 模型")
        self.btn_load.clicked.connect(self._on_load_whisper)
        action_row.addWidget(self.btn_load)

        action_row.addWidget(QLabel("模型:"))
        self.model_combo = QComboBox()
        self.model_combo.addItems(["tiny", "small", "medium", "large"])
        self.model_combo.setCurrentText("small")
        action_row.addWidget(self.model_combo)

        self.btn_submit = QPushButton("获取字幕")
        self.btn_submit.setObjectName("btnPrimary")
        self.btn_submit.clicked.connect(self._on_submit)
        action_row.addWidget(self.btn_submit)

        self.btn_clear_table = QPushButton("清空表格")
        self.btn_clear_table.clicked.connect(self._clear_tasks)
        action_row.addWidget(self.btn_clear_table)

        self.btn_export = QPushButton("导出字幕")
        self.btn_export.clicked.connect(self._on_export)
        action_row.addWidget(self.btn_export)

        self.btn_clear_log = QPushButton("清空日志")
        self.btn_clear_log.clicked.connect(self._clear_log)
        action_row.addWidget(self.btn_clear_log)

        self.btn_resume_state = QPushButton("恢复快照")
        self.btn_resume_state.clicked.connect(self._on_resume_state)
        action_row.addWidget(self.btn_resume_state)

        self.btn_service_settings = QPushButton("服务设置")
        self.btn_service_settings.clicked.connect(self._open_service_settings)
        action_row.addWidget(self.btn_service_settings)

        self.btn_plugin_manager = QPushButton("插件管理")
        self.btn_plugin_manager.clicked.connect(self._open_plugin_manager)
        action_row.addWidget(self.btn_plugin_manager)

        action_row.addStretch()
        root.addLayout(action_row)

        self.task_table = QTableWidget()
        self.task_table.setColumnCount(9)
        self.task_table.setHorizontalHeaderLabels(
            [
                "序号",
                "BV",
                "标题",
                "作者",
                "来源",
                "字幕状态",
                "结果来源",
                "语言",
                "操作",
            ]
        )
        self.task_table.verticalHeader().setVisible(False)
        self.task_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.task_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.task_table.setSelectionMode(QTableWidget.SingleSelection)
        header = self.task_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.Stretch)
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(5, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(6, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(7, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(8, QHeaderView.ResizeToContents)
        root.addWidget(self.task_table, stretch=1)

        self.log_panel = QTextEdit()
        self.log_panel.setObjectName("logPanel")
        self.log_panel.setReadOnly(True)
        self.log_panel.setMinimumHeight(180)
        root.addWidget(self.log_panel)

        self.progress_bar = QProgressBar()
        self.progress_bar.setMaximum(1)
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat("就绪")
        root.addWidget(self.progress_bar)

        footer = QHBoxLayout()
        footer.addWidget(QLabel("作者: Lanbin / SubBatch 融合版"))
        repo_link = QLabel('<a style="color:#58b9ff;" href="#">GitHub 仓库</a>')
        repo_link.mousePressEvent = lambda _evt: webbrowser.open_new("https://github.com/lanbinshijie/BilibiliHarvest")
        footer.addWidget(repo_link)
        footer.addStretch()
        root.addLayout(footer)

        self._on_source_type_changed()

    def _on_import_group_toggled(self, checked: bool):
        self.import_panel.setVisible(bool(checked))

    def _selected_source_type(self) -> str:
        return str(self.source_type_combo.currentData() or "auto")

    def _selected_import_mode(self) -> str:
        return "all_pages" if self.radio_all_pages.isChecked() else "single"

    def _selected_order(self) -> str:
        return str(self.order_combo.currentData() or "pubdate_desc")

    def _on_source_type_changed(self, *_args):
        source_type = self._selected_source_type()
        placeholders = {
            "auto": "自动识别 URL / BV / MID / season:id / series:id / ml{id}",
            "single": "输入 BV 或视频链接",
            "multi_p": "输入 BV 或视频链接（将展开分P）",
            "favorite": "输入收藏夹 URL 或 media_id",
            "collection": "输入合集 URL 或 season:{id} / ml{id}",
            "series": "输入列表 URL 或 series:{id}",
            "space_uploads": "输入 UP 主页 URL 或 MID",
        }
        self.unified_input.setPlaceholderText(placeholders.get(source_type, placeholders["auto"]))

        mode_enabled = source_type in {"auto", "single", "multi_p"}
        self.radio_single.setEnabled(mode_enabled)
        self.radio_all_pages.setEnabled(mode_enabled)
        if source_type == "single":
            self.radio_single.setChecked(True)
        elif source_type == "multi_p":
            self.radio_all_pages.setChecked(True)

        limit_enabled = source_type in {"auto", "favorite", "space_uploads"}
        order_enabled = source_type in {"auto", "space_uploads", "favorite", "collection", "series"}
        self.space_limit_spin.setEnabled(limit_enabled)
        self.order_combo.setEnabled(order_enabled)

    def _collect_unified_inputs(self) -> list[str]:
        raw = self.unified_input.text().strip()
        if not raw:
            return []
        if not self.chk_multiline.isChecked():
            return [raw]
        return [item.strip() for item in re.split(r"[\r\n;,]+", raw) if item.strip()]

    def _on_use_clipboard_input(self, *_args):
        clip_text = (QGuiApplication.clipboard().text() or "").strip()
        if not clip_text:
            QMessageBox.information(self, "提示", "剪贴板为空")
            return
        if self.chk_multiline.isChecked() and self.unified_input.text().strip():
            joined = f"{self.unified_input.text().strip()};{clip_text}"
            self.unified_input.setText(joined)
        else:
            self.unified_input.setText(clip_text)

    def _resolve_source_items(
        self,
        text: str,
        *,
        source_type: str,
        import_mode: str,
        limit: int,
        order: str,
        cookie_header: Optional[str],
    ) -> list[SourceItem]:
        if source_type == "auto":
            return resolve_source_auto(
                text,
                cookie_header=cookie_header,
                limit=limit,
                order=order,
                import_mode=import_mode,
            )
        if source_type == "single":
            return resolve_single_or_bv(text, import_mode="single", cookie_header=cookie_header)
        if source_type == "multi_p":
            return resolve_single_or_bv(text, import_mode="all_pages", cookie_header=cookie_header)
        if source_type == "favorite":
            return resolve_favorite(text, limit=limit, cookie_header=cookie_header)
        if source_type in {"collection", "series"}:
            resolved = resolve_collection_series(text, cookie_header=cookie_header)
            filtered = [item for item in resolved if item.source_type == source_type]
            return filtered or resolved
        if source_type == "space_uploads":
            if not cookie_header:
                self._log("未提供 Cookie，主页导入将尽力抓取公开投稿，结果可能不完整", level="WARN", stage="IMPORT")
            return resolve_space_uploads(
                text,
                limit=limit,
                order=order,
                cookie_header=cookie_header,
            )
        raise SourceResolveError(f"未知源类型: {source_type}")

    def _import_entries(
        self,
        entries: list[str],
        *,
        source_type: str,
        import_mode: str,
        limit: int,
        order: str,
        save_selected: bool = False,
        cookie_header_override: Optional[str] = None,
    ) -> dict:
        cookie_header = cookie_header_override if cookie_header_override is not None else self._cookie_header_for_api()
        accepted = 0
        duplicates = 0
        failed = 0
        warnings: list[str] = []

        for text in entries:
            try:
                resolved = self._resolve_source_items(
                    text,
                    source_type=source_type,
                    import_mode=import_mode,
                    limit=limit,
                    order=order,
                    cookie_header=cookie_header,
                )
            except SourceResolveError as exc:
                failed += 1
                warnings.append(str(exc))
                self._log(f"导入失败: {text} -> {exc}", level="ERROR", stage="IMPORT")
                continue
            except Exception as exc:
                failed += 1
                warnings.append(str(exc))
                self._log(f"导入失败: {text} -> {exc}", level="ERROR", stage="IMPORT")
                continue

            for item in resolved:
                if self._add_task(item, text):
                    accepted += 1
                    if save_selected:
                        for task in reversed(self._tasks):
                            if task.bv.upper() == item.bvid.upper() and task.cid == item.cid:
                                task.save_selected = True
                                break
                else:
                    duplicates += 1

        self._refresh_table()
        self._log(
            f"导入完成: 新增 {accepted}，重复 {duplicates}，失败 {failed}，当前队列 {len(self._tasks)}",
            stage="IMPORT",
        )
        return {
            "ok": True,
            "accepted": accepted,
            "duplicates": duplicates,
            "failed": failed,
            "queued_total": len(self._tasks),
            "warnings": warnings,
        }

    def _on_add_from_unified_input(self, *_args):
        entries = self._collect_unified_inputs()
        if not entries:
            QMessageBox.information(self, "提示", "请先输入导入内容")
            return

        source_type = self._selected_source_type()
        import_mode = self._selected_import_mode()
        if source_type == "single":
            import_mode = "single"
        elif source_type == "multi_p":
            import_mode = "all_pages"

        self._import_entries(
            entries,
            source_type=source_type,
            import_mode=import_mode,
            limit=int(self.space_limit_spin.value()),
            order=self._selected_order(),
        )

    def _build_tray(self):
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return

        tray = QSystemTrayIcon(self)
        icon = self.windowIcon()
        if icon.isNull():
            icon = QIcon("favicon.ico")
        tray.setIcon(icon)
        tray.setToolTip("BilibiliHarvest")

        menu = QMenu(self)
        action_open_dashboard = QAction("打开扩展控制台", self)
        action_open_dashboard.triggered.connect(self._open_extension_dashboard)
        menu.addAction(action_open_dashboard)

        action_show_window = QAction("显示状态窗口（高级）", self)
        action_show_window.triggered.connect(self._show_diagnostic_window)
        menu.addAction(action_show_window)

        menu.addSeparator()
        action_quit = QAction("退出 BilibiliHarvest", self)
        action_quit.triggered.connect(self._quit_from_tray)
        menu.addAction(action_quit)

        tray.setContextMenu(menu)
        tray.activated.connect(self._on_tray_activated)
        tray.show()
        self._tray_icon = tray

    def _paired_extension_dashboard_url(self) -> str:
        extension_ids = list(getattr(self._runtime_config, "extension_ids", []) or [])
        extension_id = extension_ids[0].strip() if extension_ids else ""
        if not extension_id:
            return ""
        return f"chrome-extension://{extension_id}/dashboard.html"

    def _open_extension_dashboard(self):
        dashboard_url = self._paired_extension_dashboard_url()
        if not dashboard_url:
            if self._tray_icon is not None:
                self._tray_icon.showMessage(
                    "尚未配对扩展",
                    "请先在 Chrome 安装扩展并打开 dashboard 完成自动配对。",
                    QSystemTrayIcon.Information,
                    6000,
                )
            return
        webbrowser.open(dashboard_url)

    def _show_diagnostic_window(self):
        self.show()
        self.raise_()
        self.activateWindow()

    def _quit_from_tray(self):
        self._quit_requested = True
        if self._tray_icon is not None:
            self._tray_icon.hide()
        QApplication.quit()

    def _on_tray_activated(self, reason):
        if reason == QSystemTrayIcon.Trigger:
            self._open_extension_dashboard()

    def _install_redirector(self):
        self._redirector = StdoutRedirector()
        self._redirector.text_written.connect(self._append_log)
        sys.stdout = self._redirector
        sys.stderr = self._redirector

    def _append_log(self, text: str):
        ts = datetime.now().strftime("%H:%M:%S")
        self.log_panel.moveCursor(QTextCursor.End)
        self.log_panel.insertPlainText(f"[{ts}] {text}\n")
        self.log_panel.moveCursor(QTextCursor.End)

    def _log(self, msg: str, level: str = "INFO", stage: str = "BATCH", task: Optional[TaskItem] = None):
        parts = [datetime.now().strftime("%H:%M:%S")]
        batch = self._current_batch
        if batch:
            parts.append(f"B:{batch.batch_id}")
        if task:
            parts.append(f"T:{task.seq:03d}")
            parts.append(f"BV:{task.bv}")
        parts.append(stage.upper())
        parts.append(level.upper())
        prefix = "".join(f"[{p}]" for p in parts)
        print(f"{prefix} {msg}")

    def _check_runtime_dependencies(self):
        yt_dlp_bin = find_executable("yt-dlp")
        if not yt_dlp_bin:
            self._log("未检测到 yt-dlp，字幕轨道功能不可用。请先安装 yt-dlp。", level="ERROR", stage="CHECK")
            return

        result = run_command([yt_dlp_bin, "--version"], timeout=20)
        if result.returncode == 0:
            version = (result.stdout or "").strip()
            self._log(f"yt-dlp ready: {version}", stage="CHECK")
        else:
            self._log(f"yt-dlp 自检失败: {result.stderr}", level="ERROR", stage="CHECK")

    def _runtime_state_for_api(self) -> dict:
        with self._state_lock:
            running_batch = bool(self._current_batch and self._current_batch.is_running)
        return {
            "ok": True,
            "core_version": CORE_VERSION,
            "http_enabled": bool(self._http_server and self._http_server.is_running),
            "port": int(self._http_server_port or self._runtime_config.http_port),
            "batch_running": running_batch,
            "queue_size": sum(1 for task in self._tasks if task.status == TaskStatus.QUEUED),
            "archive_root": str(getattr(self._runtime_config, "archive_root", "") or ""),
        }

    def _api_command_handler(self, command: str, payload: dict) -> dict:
        response_queue: queue.Queue = queue.Queue(maxsize=1)
        self._api_command_queue.put(
            {
                "command": str(command or ""),
                "payload": dict(payload or {}),
                "response_queue": response_queue,
            }
        )
        self.api_command_signal.emit()
        try:
            return response_queue.get(timeout=180)
        except queue.Empty:
            return {
                "ok": False,
                "accepted": 0,
                "duplicates": 0,
                "failed": 1,
                "queued_total": len(self._tasks),
                "warnings": ["api command timeout"],
            }

    def _start_local_http_service(self, quiet: bool = True):
        if self._http_server and self._http_server.is_running:
            return

        if not self._runtime_config.api_token:
            self._runtime_config.api_token = generate_api_token()
            save_runtime_config(self._runtime_config)

        if self._http_server is None:
            self._http_server = LocalApiServer(
                command_handler=self._api_command_handler,
                runtime_state_provider=self._runtime_state_for_api,
            )

        result = self._http_server.start(
            host=self._runtime_config.http_host,
            port=int(self._runtime_config.http_port),
            port_scan_window=int(self._runtime_config.http_port_scan_window),
            token=self._runtime_config.api_token,
            extension_ids=list(self._runtime_config.extension_ids),
        )
        if result.ok:
            self._http_server_port = int(result.port)
            self._log(
                f"本地HTTP服务已启动: http://{self._runtime_config.http_host}:{self._http_server_port}",
                stage="API",
            )
            return

        self._http_server_port = 0
        self._log(f"本地HTTP服务启动失败: {result.message}", level="ERROR", stage="API")
        if not quiet:
            QMessageBox.warning(self, "服务启动失败", result.message)

    def _stop_local_http_service(self):
        if self._http_server:
            self._http_server.stop()
            self._http_server_port = 0
            self._log("本地HTTP服务已停止", stage="API")

    def _restart_local_http_service(self):
        self._stop_local_http_service()
        if self._runtime_config.http_enabled:
            self._start_local_http_service(quiet=False)

    def _pairing_is_available(self, extension_id: str = "") -> bool:
        configured = [item.strip() for item in (self._runtime_config.extension_ids or []) if str(item).strip()]
        if not configured:
            return True
        return bool(extension_id and extension_id in configured)

    def _autostart_registry_info(self) -> tuple[str, str, str]:
        run_key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
        value_name = "BilibiliHarvestBackground"
        starter_script = os.path.abspath(os.path.join("scripts", "start_bili2text_background.ps1"))
        value_data = f'powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "{starter_script}" -Quiet'
        return run_key_path, value_name, value_data

    def _is_autostart_enabled(self) -> bool:
        run_key_path, value_name, expected_value = self._autostart_registry_info()
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, run_key_path, 0, winreg.KEY_READ) as key:
                value, _value_type = winreg.QueryValueEx(key, value_name)
        except OSError:
            return False
        current = str(value or "").strip().lower()
        return current == expected_value.strip().lower()

    def _set_autostart_enabled(self, enabled: bool) -> None:
        run_key_path, value_name, value_data = self._autostart_registry_info()
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, run_key_path) as key:
            if enabled:
                winreg.SetValueEx(key, value_name, 0, winreg.REG_SZ, value_data)
            else:
                try:
                    winreg.DeleteValue(key, value_name)
                except FileNotFoundError:
                    pass

    def _svc_pairing_info(self) -> dict:
        return {
            "ok": True,
            "pairable": self._pairing_is_available(),
            "port": int(self._http_server_port or self._runtime_config.http_port),
            "archive_root": str(getattr(self._runtime_config, "archive_root", "") or ""),
            "archive_label": str(getattr(self._runtime_config, "archive_label", "本地知识库") or "本地知识库"),
            "autostart_enabled": self._is_autostart_enabled(),
            "core_version": CORE_VERSION,
        }

    def _handle_api_pairing_claim(self, payload: dict) -> dict:
        extension_id = str(payload.get("extension_id") or "").strip()
        if not extension_id:
            return {"ok": False, "error": "missing extension_id"}
        if not self._pairing_is_available(extension_id):
            return {"ok": False, "error": "pairing disabled"}

        current_ids = [item.strip() for item in (self._runtime_config.extension_ids or []) if str(item).strip()]
        if extension_id not in current_ids:
            current_ids.append(extension_id)
            self._runtime_config.extension_ids = current_ids
            save_runtime_config(self._runtime_config)

        return {
            "ok": True,
            "paired": True,
            "extension_id": extension_id,
            "port": int(self._http_server_port or self._runtime_config.http_port),
            "token": str(self._runtime_config.api_token or ""),
            "archive_root": str(getattr(self._runtime_config, "archive_root", "") or ""),
            "archive_label": str(getattr(self._runtime_config, "archive_label", "本地知识库") or "本地知识库"),
        }

    def _svc_get_public_config(self) -> dict:
        return {
            "ok": True,
            "archive_root": str(getattr(self._runtime_config, "archive_root", "") or ""),
            "archive_label": str(getattr(self._runtime_config, "archive_label", "本地知识库") or "本地知识库"),
            "autostart_enabled": self._is_autostart_enabled(),
            "notebooklm_enabled": bool(self._runtime_config.notebooklm_enabled),
            "notebooklm_notebook_id": str(self._runtime_config.notebooklm_notebook_id or ""),
            "notebooklm_auto_clean": bool(self._runtime_config.notebooklm_auto_clean),
            "port": int(self._http_server_port or self._runtime_config.http_port),
        }

    def _handle_api_patch_config(self, payload: dict) -> dict:
        if not isinstance(payload, dict):
            return {"ok": False, "error": "invalid payload"}

        allowed_fields = {"archive_root", "archive_label", "autostart_enabled", "notebooklm_enabled", "notebooklm_notebook_id", "notebooklm_auto_clean"}
        unknown = sorted(key for key in payload.keys() if key not in allowed_fields)
        if unknown:
            return {"ok": False, "error": f"unsupported fields: {', '.join(unknown)}"}

        if "archive_root" in payload:
            archive_root = os.path.abspath(os.path.expanduser(str(payload.get("archive_root") or "").strip()))
            if not archive_root:
                return {"ok": False, "error": "archive_root is required"}
            self._runtime_config.archive_root = archive_root
        if "archive_label" in payload:
            archive_label = str(payload.get("archive_label") or "").strip()
            if not archive_label:
                return {"ok": False, "error": "archive_label is required"}
            self._runtime_config.archive_label = archive_label
        if "autostart_enabled" in payload:
            self._set_autostart_enabled(bool(payload.get("autostart_enabled")))
        if "notebooklm_enabled" in payload:
            self._runtime_config.notebooklm_enabled = bool(payload.get("notebooklm_enabled"))
        if "notebooklm_notebook_id" in payload:
            self._runtime_config.notebooklm_notebook_id = str(payload.get("notebooklm_notebook_id") or "")
        if "notebooklm_auto_clean" in payload:
            self._runtime_config.notebooklm_auto_clean = bool(payload.get("notebooklm_auto_clean"))

        save_runtime_config(self._runtime_config)
        return self._svc_get_public_config()

    def _svc_show_window(self) -> dict:
        self._show_diagnostic_window()
        return {"ok": True}

    def _normalize_api_options(self, payload: dict, base: Optional[dict] = None) -> dict:
        defaults = {
            "import_mode": "single",
            "limit": 200,
            "order": "pubdate_desc",
            "cookie_header": None,
        }
        if isinstance(base, dict):
            defaults.update(base)

        options = payload if isinstance(payload, dict) else {}
        import_mode = str(options.get("import_mode", defaults["import_mode"]) or defaults["import_mode"]).strip().lower()
        if import_mode not in {"single", "all_pages"}:
            import_mode = "single"

        limit_raw = options.get("limit", defaults["limit"])
        try:
            limit = int(limit_raw)
        except Exception:
            limit = 200
        limit = max(1, min(limit, 2000))

        order = str(options.get("order", defaults["order"]) or defaults["order"]).strip() or "pubdate_desc"
        cookie_header_raw = options.get("cookie_header", defaults["cookie_header"])
        cookie_header = None if cookie_header_raw is None else str(cookie_header_raw).strip()
        return {
            "import_mode": import_mode,
            "limit": limit,
            "order": order,
            "cookie_header": cookie_header,
        }

    def _sanitize_prefetched_segments(self, raw_segments) -> list[dict]:
        cleaned: list[dict] = []
        if not isinstance(raw_segments, list):
            return cleaned

        for entry in raw_segments:
            if not isinstance(entry, dict):
                continue

            text = str(entry.get("text") or "").strip()
            start_raw = entry.get("start_sec", entry.get("start"))
            end_raw = entry.get("end_sec", entry.get("end", start_raw))
            if not text:
                continue

            try:
                start_sec = float(start_raw)
                end_sec = float(end_raw)
            except (TypeError, ValueError):
                continue

            if start_sec < 0:
                continue
            if end_sec < start_sec:
                continue

            cleaned.append(
                {
                    "start_sec": start_sec,
                    "end_sec": end_sec,
                    "text": text,
                }
            )

        return cleaned

    def _normalize_prefetched_subtitle(self, payload: dict) -> tuple[dict, list[dict], str]:
        if not isinstance(payload, dict):
            return {}, [], "prefetched_subtitle_missing"

        segments = self._sanitize_prefetched_segments(payload.get("segments"))
        if not segments:
            return {}, [], "prefetched_segments_empty"

        def _to_int(value):
            if value is None or value == "":
                return None
            try:
                return int(value)
            except (TypeError, ValueError):
                return None

        track_type = str(payload.get("track_type") or "uploader").strip().lower()
        if track_type not in {"uploader", "ai"}:
            track_type = "uploader"

        meta = {
            "aid": _to_int(payload.get("aid")),
            "cid": _to_int(payload.get("cid")),
            "lang": str(payload.get("lang") or "unknown").strip() or "unknown",
            "track_type": track_type,
            "subtitle_url": str(payload.get("subtitle_url") or "").strip(),
            "collected_at": str(payload.get("collected_at") or "").strip(),
        }
        return meta, segments, ""

    def _prefetch_status_bindable(self, status: TaskStatus) -> bool:
        return status in {TaskStatus.QUEUED, TaskStatus.RESOLVING_TRACKS}

    def _apply_prefetched_to_task(
        self,
        task: TaskItem,
        *,
        meta: dict,
        segments: list[dict],
        request_cookie_header: Optional[str],
    ):
        task.prefetched_segments = [
            {
                "start_sec": float(item["start_sec"]),
                "end_sec": float(item["end_sec"]),
                "text": str(item["text"]),
            }
            for item in segments
        ]
        task.prefetched_meta = dict(meta or {})

        aid = meta.get("aid")
        cid = meta.get("cid")
        if aid and not task.aid:
            task.aid = aid
        if cid and not task.cid:
            task.cid = cid

        if request_cookie_header is not None:
            clean_cookie = str(request_cookie_header).strip()
            task.request_cookie_header = clean_cookie or None

    def _upsert_task_from_source_item(self, item: SourceItem, raw_input: str) -> tuple[Optional[TaskItem], bool, str]:
        bv = item.bvid
        cid = item.cid
        strong_key = self._task_key(bv, cid)
        same_bv = [task for task in self._tasks if task.bv.upper() == bv.upper()]
        has_strong = any(task.cid is not None for task in same_bv)

        if cid is None:
            if has_strong:
                existing = next((task for task in same_bv if task.cid is not None), None)
                return existing, False, "duplicate_weak_when_strong_exists"
            weak_task = next((task for task in same_bv if task.cid is None), None)
            if weak_task is not None:
                return weak_task, False, "duplicate_weak"

            task = source_item_to_task(self._next_seq(), raw_input, item)
            self._tasks.append(task)
            self._task_key_set.add(self._task_key(bv, None))
            return task, True, "added_weak"

        if strong_key in self._task_key_set:
            existing = next((task for task in same_bv if task.cid == cid), None)
            return existing, False, "duplicate_strong"

        weak_task = next((task for task in same_bv if task.cid is None), None)
        if weak_task is not None:
            old_key = self._task_key(weak_task.bv, None)
            self._task_key_set.discard(old_key)
            self._task_key_set.add(strong_key)
            self._merge_task_from_source_item(weak_task, item, raw_input)
            return weak_task, True, "upgraded_weak_to_strong"

        task = source_item_to_task(self._next_seq(), raw_input, item)
        self._tasks.append(task)
        self._task_key_set.add(strong_key)
        return task, True, "added_strong"

    def _select_prefetch_source_item(self, resolved: list[SourceItem], preferred_cid: Optional[int]) -> SourceItem:
        if not resolved:
            raise SourceResolveError("no source items resolved")
        if preferred_cid is not None:
            hit = next((item for item in resolved if item.cid == preferred_cid), None)
            if hit is not None:
                return hit
        return resolved[0]

    def _handle_api_bind_prefetched(self, payload: dict) -> dict:
        """[延迟绑定] 根据 BV 找到已入队任务并将浏览器采集到的字幕绑定到该任务。"""
        text = str(payload.get("input") or "").strip()
        if not text:
            return {
                "ok": False,
                "prefetch_bound": False,
                "prefetch_reason": "input_missing",
                "warnings": ["input is required"],
            }

        prefetch_meta, prefetch_segments, prefetch_reason = self._normalize_prefetched_subtitle(
            payload.get("prefetched_subtitle") or {}
        )
        if not prefetch_segments:
            return {
                "ok": False,
                "prefetch_bound": False,
                "prefetch_reason": prefetch_reason or "prefetched_segments_empty",
                "warnings": ["no usable segments in prefetched_subtitle"],
            }

        # 从 URL 或纯 BV 字符串中提取 bvid
        import re as _re
        m = _re.search(r"BV[0-9A-Za-z]{10}", text, _re.I)
        bvid = m.group(0).upper() if m else None

        if not bvid:
            return {
                "ok": False,
                "prefetch_bound": False,
                "prefetch_reason": "bvid_not_found",
                "warnings": [f"cannot extract bvid from input: {text}"],
            }

        options = self._normalize_api_options(payload.get("options") or {})
        prefetch_cid = prefetch_meta.get("cid") if prefetch_meta else None

        with self._state_lock:
            # 在当前队列中找到匹配的可绑定任务
            target_task = None
            for task in self._tasks:
                if task.bv.upper() != bvid.upper():
                    continue
                if not self._prefetch_status_bindable(task.status):
                    continue
                if prefetch_cid and task.cid and task.cid != prefetch_cid:
                    continue
                target_task = task
                break

            if target_task is None:
                return {
                    "ok": False,
                    "prefetch_bound": False,
                    "prefetch_reason": "task_not_found_or_not_bindable",
                    "warnings": [f"no bindable task for bvid={bvid}"],
                }

            self._apply_prefetched_to_task(
                target_task,
                meta=prefetch_meta,
                segments=prefetch_segments,
                request_cookie_header=options.get("cookie_header"),
            )
            self._log(
                f"DELAYED_BIND: 绑定 {len(prefetch_segments)} 段字幕 "
                f"({prefetch_meta.get('lang', 'unknown')}) 到任务 seq={target_task.seq}",
                stage="PREFETCH",
                task=target_task,
            )

        self._refresh_table()
        return {
            "ok": True,
            "prefetch_bound": True,
            "prefetch_reason": "delayed_bound",
            "seq": target_task.seq,
            "warnings": [],
        }

    def _handle_api_add_prefetched(self, payload: dict) -> dict:
        source_type = str(payload.get("source_type") or "single").strip() or "single"
        allowed_types = {"single", "multi_p", "favorite", "collection", "series", "space_uploads", "auto"}
        if source_type not in allowed_types:
            return {
                "ok": False,
                "accepted": 0,
                "duplicates": 0,
                "failed": 1,
                "queued_total": len(self._tasks),
                "warnings": [f"invalid source_type: {source_type}"],
                "prefetch_bound": False,
                "prefetch_reason": "invalid_source_type",
            }

        text = str(payload.get("input") or "").strip()
        if not text:
            return {
                "ok": False,
                "accepted": 0,
                "duplicates": 0,
                "failed": 1,
                "queued_total": len(self._tasks),
                "warnings": ["input is required"],
                "prefetch_bound": False,
                "prefetch_reason": "input_missing",
            }

        options = self._normalize_api_options(payload.get("options") or {})
        if source_type == "multi_p":
            options["import_mode"] = "all_pages"
        elif source_type == "single":
            options["import_mode"] = "single"

        prefetch_meta, prefetch_segments, prefetch_reason = self._normalize_prefetched_subtitle(
            payload.get("prefetched_subtitle") or {}
        )
        prefetch_cid = prefetch_meta.get("cid") if prefetch_meta else None

        warnings: list[str] = []
        try:
            resolved = self._resolve_source_items(
                text,
                source_type=source_type,
                import_mode=options["import_mode"],
                limit=options["limit"],
                order=options["order"],
                cookie_header=options.get("cookie_header"),
            )
        except SourceResolveError as exc:
            return {
                "ok": False,
                "accepted": 0,
                "duplicates": 0,
                "failed": 1,
                "queued_total": len(self._tasks),
                "warnings": [str(exc)],
                "prefetch_bound": False,
                "prefetch_reason": "source_resolve_failed",
            }
        except Exception as exc:
            return {
                "ok": False,
                "accepted": 0,
                "duplicates": 0,
                "failed": 1,
                "queued_total": len(self._tasks),
                "warnings": [str(exc)],
                "prefetch_bound": False,
                "prefetch_reason": "source_resolve_failed",
            }

        if not resolved:
            return {
                "ok": False,
                "accepted": 0,
                "duplicates": 0,
                "failed": 1,
                "queued_total": len(self._tasks),
                "warnings": ["resolved source is empty"],
                "prefetch_bound": False,
                "prefetch_reason": "source_empty",
            }

        try:
            source_item = self._select_prefetch_source_item(resolved, preferred_cid=prefetch_cid)
        except SourceResolveError as exc:
            return {
                "ok": False,
                "accepted": 0,
                "duplicates": 0,
                "failed": 1,
                "queued_total": len(self._tasks),
                "warnings": [str(exc)],
                "prefetch_bound": False,
                "prefetch_reason": "source_empty",
            }

        with self._state_lock:
            task, created, upsert_reason = self._upsert_task_from_source_item(source_item, text)
            if task is None:
                return {
                    "ok": False,
                    "accepted": 0,
                    "duplicates": 0,
                    "failed": 1,
                    "queued_total": len(self._tasks),
                    "warnings": [f"unable to upsert task: {upsert_reason}"],
                    "prefetch_bound": False,
                    "prefetch_reason": "upsert_failed",
                }

            prefetch_bound = False
            if prefetch_segments:
                if self._prefetch_status_bindable(task.status):
                    self._apply_prefetched_to_task(
                        task,
                        meta=prefetch_meta,
                        segments=prefetch_segments,
                        request_cookie_header=options.get("cookie_header"),
                    )
                    prefetch_bound = True
                    prefetch_reason = "bound"
                    self._log(
                        f"PREFETCH_HIT: bound {len(prefetch_segments)} segments ({prefetch_meta.get('lang', 'unknown')})",
                        stage="PREFETCH",
                        task=task,
                    )
                else:
                    prefetch_reason = f"status_not_bindable:{task.status.value}"
                    self._log(
                        f"PREFETCH_BIND_REJECTED: {prefetch_reason}",
                        level="WARN",
                        stage="PREFETCH",
                        task=task,
                    )
            else:
                if not prefetch_reason:
                    prefetch_reason = "prefetch_segments_empty"
                self._log(f"PREFETCH_INVALID: {prefetch_reason}", level="WARN", stage="PREFETCH", task=task)

            if not prefetch_bound and not prefetch_segments:
                self._log("PREFETCH_MISS: no usable prefetched segments", level="WARN", stage="PREFETCH", task=task)

        accepted = 1 if created else 0
        duplicates = 0 if created else 1
        if not prefetch_bound:
            warnings.append(f"prefetch not bound: {prefetch_reason}")

        self._refresh_table()
        self._log(
            f"导入完成: 新增 {accepted}，重复 {duplicates}，失败 0，当前队列 {len(self._tasks)}",
            stage="IMPORT",
        )
        return {
            "ok": True,
            "accepted": accepted,
            "duplicates": duplicates,
            "failed": 0,
            "queued_total": len(self._tasks),
            "warnings": warnings,
            "prefetch_bound": prefetch_bound,
            "prefetch_reason": prefetch_reason,
        }

    def _handle_api_add(self, payload: dict) -> dict:
        source_type = str(payload.get("source_type") or "auto").strip() or "auto"
        allowed_types = {"single", "multi_p", "favorite", "collection", "series", "space_uploads", "auto"}
        if source_type not in allowed_types:
            return {
                "ok": False,
                "accepted": 0,
                "duplicates": 0,
                "failed": 1,
                "queued_total": len(self._tasks),
                "warnings": [f"invalid source_type: {source_type}"],
            }

        text = str(payload.get("input") or "").strip()
        if not text:
            return {
                "ok": False,
                "accepted": 0,
                "duplicates": 0,
                "failed": 1,
                "queued_total": len(self._tasks),
                "warnings": ["input is required"],
            }

        options = self._normalize_api_options(payload.get("options") or {})
        if source_type == "multi_p":
            options["import_mode"] = "all_pages"
        elif source_type == "single":
            options["import_mode"] = "single"

        result = self._import_entries(
            [text],
            source_type=source_type,
            import_mode=options["import_mode"],
            limit=options["limit"],
            order=options["order"],
            save_selected=bool(payload.get("save_selected")),
            cookie_header_override=options.get("cookie_header"),
        )
        result["ok"] = True
        return result

    def _handle_api_bulk_add(self, payload: dict) -> dict:
        defaults = payload.get("defaults") or {}
        default_source = str(defaults.get("source_type") or "auto").strip() or "auto"
        default_save_selected = bool(defaults.get("save_selected"))
        default_options = self._normalize_api_options(defaults.get("options") or {})

        items = payload.get("items") or []
        if not isinstance(items, list):
            return {
                "ok": False,
                "accepted": 0,
                "duplicates": 0,
                "failed": 1,
                "queued_total": len(self._tasks),
                "item_results": [],
                "warnings": ["items must be an array"],
            }

        total_accepted = 0
        total_duplicates = 0
        total_failed = 0
        item_results = []
        warnings = []

        for idx, item in enumerate(items):
            row = item if isinstance(item, dict) else {}
            source_type = str(row.get("source_type") or default_source).strip() or "auto"
            allowed_types = {"single", "multi_p", "favorite", "collection", "series", "space_uploads", "auto"}
            if source_type not in allowed_types:
                row_result = {
                    "index": idx,
                    "accepted": 0,
                    "duplicates": 0,
                    "failed": 1,
                    "error": f"invalid source_type: {source_type}",
                }
                total_failed += 1
                item_results.append(row_result)
                warnings.append(f"index {idx}: invalid source_type: {source_type}")
                continue
            options = self._normalize_api_options(row.get("options") or {}, base=default_options)
            save_selected = bool(row.get("save_selected", default_save_selected))
            text = str(row.get("input") or "").strip()

            if not text:
                row_result = {
                    "index": idx,
                    "accepted": 0,
                    "duplicates": 0,
                    "failed": 1,
                    "error": "input is required",
                }
                total_failed += 1
                item_results.append(row_result)
                warnings.append(f"index {idx}: input is required")
                continue

            try:
                result = self._import_entries(
                    [text],
                    source_type=source_type,
                    import_mode=options["import_mode"],
                    limit=options["limit"],
                    order=options["order"],
                    save_selected=save_selected,
                    cookie_header_override=options.get("cookie_header"),
                )
                total_accepted += int(result["accepted"])
                total_duplicates += int(result["duplicates"])
                total_failed += int(result["failed"])
                row_error = (result.get("warnings") or [""])[0] if result.get("failed") else ""
                item_results.append(
                    {
                        "index": idx,
                        "accepted": int(result["accepted"]),
                        "duplicates": int(result["duplicates"]),
                        "failed": int(result["failed"]),
                        "error": str(row_error or ""),
                    }
                )
                warnings.extend([str(w) for w in (result.get("warnings") or []) if str(w).strip()])
            except Exception as exc:
                total_failed += 1
                err = str(exc)
                warnings.append(f"index {idx}: {err}")
                item_results.append(
                    {
                        "index": idx,
                        "accepted": 0,
                        "duplicates": 0,
                        "failed": 1,
                        "error": err,
                    }
                )

        return {
            "ok": True,
            "accepted": total_accepted,
            "duplicates": total_duplicates,
            "failed": total_failed,
            "queued_total": len(self._tasks),
            "item_results": item_results,
            "warnings": warnings,
        }

    def _handle_api_update_task_flag(self, payload: dict) -> dict:
        seq = payload.get("seq")
        if seq is None:
            return {"ok": False, "error": "missing_seq"}
        
        task = next((t for t in self._tasks if t.seq == seq), None)
        if not task:
            return {"ok": False, "error": "task_not_found"}
            
        updated = False
        if "save_selected" in payload:
            task.save_selected = bool(payload["save_selected"])
            updated = True
        else:
            flag = str(payload.get("flag") or "").strip()
            if flag == "save_selected":
                task.save_selected = bool(payload.get("value"))
                updated = True
            
        if updated:
            self.table_refresh_signal.emit()
            
        return {"ok": True, "updated": updated, "seq": seq}

    def _process_api_commands(self):
        while True:
            try:
                envelope = self._api_command_queue.get_nowait()
            except queue.Empty:
                break

            command = str(envelope.get("command") or "")
            payload = envelope.get("payload") or {}
            response_queue = envelope.get("response_queue")
            result = None
            try:
                if command == "pairing_info":
                    result = self._svc_pairing_info()
                elif command == "pairing_claim":
                    result = self._handle_api_pairing_claim(payload)
                elif command == "get_config":
                    result = self._svc_get_public_config()
                elif command == "patch_config":
                    result = self._handle_api_patch_config(payload)
                elif command == "show_window":
                    result = self._svc_show_window()
                elif command == "add":
                    result = self._handle_api_add(payload)
                elif command == "bind_prefetched":
                    result = self._handle_api_bind_prefetched(payload)
                elif command == "add_prefetched":
                    result = self._handle_api_add_prefetched(payload)
                elif command == "bulk_add":
                    result = self._handle_api_bulk_add(payload)
                elif command == "list_tasks":
                    result = self._svc_list_tasks()
                elif command == "batch_status":
                    result = self._svc_batch_status()
                elif command == "start_batch":
                    result = self._svc_start_batch()
                elif command == "stop_batch":
                    result = self._svc_stop_batch()
                elif command == "export_batch":
                    result = self._svc_export_batch(
                        formats=payload.get("formats"),
                        export_zip=payload.get("export_zip", False),
                        target_dir=payload.get("target_dir"),
                        notebook_id=payload.get("notebook_id", ""),
                        nlm_auto_clean=payload.get("nlm_auto_clean", True),
                    )
                elif command == "delete_task":
                    result = self._svc_remove_task(int(payload.get("seq", 0)))
                elif command == "retry_task":
                    result = self._svc_retry_task(int(payload.get("seq", 0)))
                elif command == "update_task_flag":
                    result = self._handle_api_update_task_flag(payload)
                elif command == "clear_tasks":
                    result = self._svc_clear_tasks()
                elif command == "nlm_auth_status":
                    result = self._svc_nlm_auth_status()
                elif command == "nlm_list_notebooks":
                    try:
                        notebooks = nlm_client.list_notebooks()
                        result = {"ok": True, "notebooks": notebooks}
                    except Exception as exc:
                        result = {"ok": False, "error": str(exc)}
                elif command == "nlm_create_notebook":
                    try:
                        nb = nlm_client.create_notebook(str(payload.get("title", "Untitled")))
                        result = {"ok": True, "notebook": nb}
                    except Exception as exc:
                        result = {"ok": False, "error": str(exc)}
                elif command == "nlm_push_status":
                    result = self._svc_nlm_push_status(str(payload.get("job_id", "")))
                else:
                    result = {
                        "ok": False,
                        "accepted": 0,
                        "duplicates": 0,
                        "failed": 1,
                        "queued_total": len(self._tasks),
                        "warnings": [f"unsupported command: {command}"],
                    }
            except Exception as exc:
                result = {
                    "ok": False,
                    "accepted": 0,
                    "duplicates": 0,
                    "failed": 1,
                    "queued_total": len(self._tasks),
                    "warnings": [str(exc)],
                }
                self._log(f"API命令处理失败: {command} -> {exc}", level="ERROR", stage="API")

            if response_queue is not None:
                try:
                    response_queue.put_nowait(result)
                except Exception:
                    pass

    def _open_service_settings(self):
        dialog = ServiceSettingsDialog(self._runtime_config, self)
        if dialog.exec_() != QDialog.Accepted:
            return

        old_cfg = RuntimeConfig(
            http_enabled=self._runtime_config.http_enabled,
            http_host=self._runtime_config.http_host,
            http_port=self._runtime_config.http_port,
            http_port_scan_window=self._runtime_config.http_port_scan_window,
            api_token=self._runtime_config.api_token,
            extension_ids=list(self._runtime_config.extension_ids),
            io_workers=self._runtime_config.io_workers,
            plugin_scan_enabled=self._runtime_config.plugin_scan_enabled,
            notebooklm_enabled=self._runtime_config.notebooklm_enabled,
            notebooklm_notebook_id=self._runtime_config.notebooklm_notebook_id,
            notebooklm_auto_clean=self._runtime_config.notebooklm_auto_clean,
            archive_root=self._runtime_config.archive_root,
        )
        self._runtime_config = dialog.result_config(self._runtime_config)
        save_runtime_config(self._runtime_config)

        changed_http = any(
            (
                old_cfg.http_enabled != self._runtime_config.http_enabled,
                old_cfg.http_host != self._runtime_config.http_host,
                old_cfg.http_port != self._runtime_config.http_port,
                old_cfg.http_port_scan_window != self._runtime_config.http_port_scan_window,
                old_cfg.api_token != self._runtime_config.api_token,
                old_cfg.extension_ids != self._runtime_config.extension_ids,
            )
        )
        if changed_http:
            if self._runtime_config.http_enabled:
                self._restart_local_http_service()
            else:
                self._stop_local_http_service()

        self._log(
            f"运行配置已更新: io_workers={self._runtime_config.io_workers}, http_enabled={self._runtime_config.http_enabled}",
            stage="CONFIG",
        )

    def _open_plugin_manager(self):
        running_batch = bool(self._current_batch and self._current_batch.is_running)
        manager = get_source_plugin_manager(enable_scan=self._runtime_config.plugin_scan_enabled)
        current_entries = manager.list_plugins()
        dialog = PluginManagerDialog(
            plugins=current_entries,
            scan_enabled=self._runtime_config.plugin_scan_enabled,
            running_batch=running_batch,
            parent=self,
        )
        if dialog.exec_() != QDialog.Accepted:
            return

        new_enabled_map = dialog.enabled_map()
        manager.save_enabled_config(new_enabled_map)
        scan_enabled = dialog.scan_enabled()
        self._runtime_config.plugin_scan_enabled = scan_enabled
        save_runtime_config(self._runtime_config)

        current_enabled_map = {item["id"]: bool(item.get("enabled")) for item in current_entries}
        enabled_changed = any(current_enabled_map.get(pid, True) != bool(flag) for pid, flag in new_enabled_map.items())
        need_reload = enabled_changed or bool(scan_enabled != manager.enable_scan) or dialog.should_reload()
        if running_batch and need_reload:
            self._log("批次运行中，插件重载已延后到批次结束后执行", level="WARN", stage="PLUGIN")
            return
        if need_reload:
            reloaded = reload_source_plugin_manager(enable_scan=scan_enabled)
            self._log(f"插件重载完成，当前插件数: {len(reloaded.list_plugins())}", stage="PLUGIN")
        else:
            self._log("插件配置已保存，下次重载生效", stage="PLUGIN")

    def _clone_task_for_restore(self, source_task: TaskItem) -> SourceItem:
        return SourceItem(
            bvid=source_task.bv,
            aid=source_task.aid,
            cid=source_task.cid,
            title=source_task.title,
            owner=source_task.owner,
            source_type=source_task.source_type,
            page=source_task.page,
            page_title=source_task.page_title,
            video_url=source_task.video_link,
            source_meta=dict(source_task.source_meta or {}),
        )

    def _restore_task_runtime_fields(self, target: TaskItem, restored: TaskItem):
        target.status = restored.status
        target.subtitle_state = restored.subtitle_state
        target.failed_stage = restored.failed_stage
        target.error = restored.error
        target.retry_count = restored.retry_count
        target.result_source = restored.result_source
        target.selected_lang = restored.selected_lang
        target.cookie_hint = restored.cookie_hint
        target.save_selected = restored.save_selected
        target.nlm_source_id = restored.nlm_source_id
        target.nlm_push_status = restored.nlm_push_status
        target.prefetched_segments = []
        target.prefetched_meta = {}
        target.request_cookie_header = None

    def _on_resume_state(self):
        if self._current_batch and self._current_batch.is_running:
            QMessageBox.information(self, "提示", "批次运行中不可恢复快照")
            return

        latest_path = find_latest_state_file()
        if not latest_path:
            QMessageBox.information(self, "提示", "未找到可恢复的 state.json")
            return

        try:
            payload = load_batch_state(latest_path, expected_core_version=CORE_VERSION)
        except Exception as exc:
            QMessageBox.warning(self, "恢复失败", str(exc))
            return

        rows = payload.get("tasks") or []
        restored_tasks: list[TaskItem] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            try:
                restored_tasks.append(task_from_state_row(row))
            except Exception:
                continue

        if not restored_tasks:
            QMessageBox.information(self, "提示", "状态文件中没有可恢复任务")
            return

        box = QMessageBox(self)
        box.setIcon(QMessageBox.Question)
        box.setWindowTitle("恢复任务")
        box.setText(f"检测到快照：{latest_path}\n请选择恢复方式。")
        btn_merge = box.addButton("合并", QMessageBox.AcceptRole)
        btn_replace = box.addButton("替换", QMessageBox.DestructiveRole)
        btn_cancel = box.addButton("取消", QMessageBox.RejectRole)
        box.setDefaultButton(btn_merge)
        box.exec_()

        clicked = box.clickedButton()
        if clicked == btn_cancel:
            return
        replace_mode = clicked == btn_replace

        if replace_mode:
            if self._last_batch and not self._last_batch.temp_cleaned:
                self._cleanup_batch_temp(self._last_batch, keep_assets=False, reason="恢复替换前清理临时数据")
            self._tasks.clear()
            self._task_key_set.clear()
            self._seq_counter = 0

        accepted = 0
        duplicates = 0
        for restored in restored_tasks:
            restored_item = self._clone_task_for_restore(restored)
            if not self._add_task(restored_item, restored.raw_input):
                duplicates += 1
                continue

            target = None
            for task in reversed(self._tasks):
                if task.bv.upper() == restored.bv.upper() and task.cid == restored.cid:
                    target = task
                    break
            if target is None:
                for task in reversed(self._tasks):
                    if task.bv.upper() == restored.bv.upper():
                        target = task
                        break
            if target is not None:
                self._restore_task_runtime_fields(target, restored)
            accepted += 1

        self._seq_counter = max([task.seq for task in self._tasks], default=0)
        self._resume_from_state = latest_path
        self._refresh_table()
        self._log(
            f"恢复完成: 模式={'替换' if replace_mode else '合并'}，新增 {accepted}，跳过重复 {duplicates}",
            stage="RESUME",
        )

    def _current_cookie_mode(self) -> str:
        return self.cookie_mode_combo.currentData() or "auto_chrome"

    def _cookies_file_path(self) -> Optional[str]:
        return resolve_cookies_file()

    def _cookie_header_for_api(self) -> Optional[str]:
        raw = self.cookie_input.text().strip()
        if raw:
            return raw
        return None

    def _load_cookie_header_from_file(self):
        cookies_path = self._cookies_file_path()
        if not cookies_path:
            QMessageBox.information(self, "提示", "未找到 cookies.txt")
            return

        cookie_map = {}
        with open(cookies_path, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                if line.startswith("#") and not line.startswith("#HttpOnly_"):
                    continue
                parts = line.split("\t")
                if len(parts) < 7:
                    continue
                domain_raw, name, value = parts[0], parts[5], parts[6]
                domain = domain_raw.replace("#HttpOnly_", "")
                if "bilibili.com" not in domain:
                    continue
                if not name:
                    continue
                cookie_map[name] = value

        if not cookie_map:
            QMessageBox.information(self, "提示", "cookies.txt 中未解析到 bilibili.com Cookie")
            return

        auth_first = ["SESSDATA", "bili_jct", "DedeUserID", "DedeUserID__ckMd5"]
        ordered_keys = [key for key in auth_first if key in cookie_map] + sorted(
            [key for key in cookie_map.keys() if key not in auth_first]
        )
        header = "; ".join(f"{key}={cookie_map[key]}" for key in ordered_keys)

        self.cookie_input.setText(header)
        self._log(f"已从 cookies.txt 载入 Cookie Header（{len(ordered_keys)} 项）", stage="COOKIE")

        ok, detail = validate_cookie_login(header)
        if ok:
            self._log(f"Cookie 登录态有效: {detail}", stage="COOKIE")
        else:
            self._log(f"Cookie 登录态无效: {detail}", level="WARN", stage="COOKIE")

    def _next_seq(self):
        self._seq_counter += 1
        return self._seq_counter

    def _task_key(self, bv: str, cid: Optional[int]):
        return (bv.upper(), cid)

    def _merge_task_from_source_item(self, target: TaskItem, source: SourceItem, raw_input: str):
        target.raw_input = raw_input
        target.video_link = source.video_url or target.video_link or f"https://www.bilibili.com/video/{source.bvid}"
        target.bv = source.bvid
        target.aid = source.aid or target.aid
        target.cid = source.cid
        target.owner = source.owner or target.owner or "UnknownUP"
        target.source_type = source.source_type or target.source_type or "single"
        target.source_meta = dict(source.source_meta or {})
        target.page = source.page
        target.page_title = source.page_title or ""
        target.title = source.title or target.title or "UnknownTitle"

        # Replace weak-key placeholder with strong-key input and reset status.
        target.status = TaskStatus.QUEUED
        target.subtitle_state = "未获取"
        target.failed_stage = None
        target.error = None
        target.retry_count = 0
        target.cookie_hint = False
        target.outputs = {}
        target.output_file = None
        target.result_source = ""
        target.selected_lang = ""
        target.segments_cache = []
        target.segments_tmp_json = ""
        target.temp_paths = []
        target.video_file_path = ""
        target.audio_file_path = ""
        target.asset_prepare_error = ""
        target.shape_folder_name = ""
        target.prefetched_segments = []
        target.prefetched_meta = {}
        target.request_cookie_header = None
        target.nlm_source_id = ""
        target.nlm_push_status = ""

    def _add_task(self, item: SourceItem, raw_input: str):
        bv = item.bvid
        cid = item.cid
        strong_key = self._task_key(bv, cid)
        same_bv = [task for task in self._tasks if task.bv.upper() == bv.upper()]
        has_strong = any(task.cid is not None for task in same_bv)

        if cid is None:
            if has_strong:
                return False
            if any(task.cid is None for task in same_bv):
                return False

            task = source_item_to_task(self._next_seq(), raw_input, item)
            self._tasks.append(task)
            self._task_key_set.add(self._task_key(bv, None))
            return True

        if strong_key in self._task_key_set:
            return False

        weak_task = next((task for task in same_bv if task.cid is None), None)
        if weak_task is not None:
            old_key = self._task_key(weak_task.bv, None)
            self._task_key_set.discard(old_key)
            self._task_key_set.add(strong_key)
            self._merge_task_from_source_item(weak_task, item, raw_input)
            return True

        task = source_item_to_task(self._next_seq(), raw_input, item)
        self._tasks.append(task)
        self._task_key_set.add(strong_key)
        return True

    def _on_add_video(self, import_mode="single"):
        entries = self._collect_unified_inputs()
        if not entries:
            QMessageBox.information(self, "提示", "请先输入视频链接或BV号")
            return
        source_type = "multi_p" if import_mode == "all_pages" else "single"
        self._import_entries(
            entries,
            source_type=source_type,
            import_mode=import_mode,
            limit=int(self.space_limit_spin.value()),
            order=self._selected_order(),
        )

    def _on_add_favorite(self):
        entries = self._collect_unified_inputs()
        if not entries:
            QMessageBox.information(self, "提示", "请先输入收藏夹链接或media_id")
            return
        self._import_entries(
            entries,
            source_type="favorite",
            import_mode="single",
            limit=int(self.space_limit_spin.value()),
            order=self._selected_order(),
        )

    def _on_add_collection_series(self):
        entries = self._collect_unified_inputs()
        if not entries:
            QMessageBox.information(self, "提示", "请先输入合集/列表链接或ID")
            return
        source_type = self._selected_source_type()
        if source_type not in {"collection", "series"}:
            source_type = "collection"
        self._import_entries(
            entries,
            source_type=source_type,
            import_mode="single",
            limit=int(self.space_limit_spin.value()),
            order=self._selected_order(),
        )

    def _on_add_space_uploads(self):
        entries = self._collect_unified_inputs()
        if not entries:
            QMessageBox.information(self, "提示", "请先输入 UP 主页链接或 MID")
            return
        self._import_entries(
            entries,
            source_type="space_uploads",
            import_mode="single",
            limit=int(self.space_limit_spin.value()),
            order=self._selected_order(),
        )

    def _status_text(self, task: TaskItem):
        if task.subtitle_state:
            return task.subtitle_state

        mapping = {
            TaskStatus.QUEUED: "未获取",
            TaskStatus.RESOLVING_TRACKS: "获取中",
            TaskStatus.DOWNLOADING_TRACK: "下载字幕中",
            TaskStatus.TRANSCRIBING_ASR: "转写中",
            TaskStatus.COMPLETED_TRACK: "已获取(轨道)",
            TaskStatus.COMPLETED_ASR: "已获取(ASR)",
            TaskStatus.FAILED: "获取失败",
        }
        return mapping.get(task.status, "未知")

    def _refresh_table(self):
        self.task_table.setRowCount(len(self._tasks))
        running = bool(self._current_batch and self._current_batch.is_running)
        for row, task in enumerate(self._tasks):
            self.task_table.setItem(row, 0, QTableWidgetItem(str(task.seq)))
            self.task_table.setItem(row, 1, QTableWidgetItem(task.bv))
            title = task.title
            if task.page and task.source_type == "multi_p":
                title = f"{title} [P{task.page}] {task.page_title}".strip()
            self.task_table.setItem(row, 2, QTableWidgetItem(title))
            self.task_table.setItem(row, 3, QTableWidgetItem(task.owner or ""))
            source_label = SOURCE_TYPE_LABELS.get(task.source_type, task.source_type)
            self.task_table.setItem(row, 4, QTableWidgetItem(source_label))
            self.task_table.setItem(row, 5, QTableWidgetItem(self._status_text(task)))
            self.task_table.setItem(row, 6, QTableWidgetItem(task.result_source or ""))
            self.task_table.setItem(row, 7, QTableWidgetItem(task.selected_lang or ""))
            self.task_table.setCellWidget(row, 8, self._build_action_cell(task, running))

    def _build_action_cell(self, task: TaskItem, running: bool):
        container = QWidget()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(4, 0, 4, 0)
        layout.setSpacing(6)

        if task.status == TaskStatus.FAILED:
            btn = QPushButton("重试")
            btn.clicked.connect(lambda _checked=False, seq=task.seq: self._retry_task(seq))
        else:
            btn = QPushButton("删除")
            btn.clicked.connect(lambda _checked=False, seq=task.seq: self._remove_task(seq))
        btn.setEnabled(not running)

        chk = QCheckBox("保存")
        chk.setChecked(bool(task.save_selected))
        chk.setEnabled(not running)

        def _on_checked(state, ref=task):
            ref.save_selected = state == Qt.Checked

        chk.stateChanged.connect(_on_checked)
        layout.addWidget(btn)
        layout.addWidget(chk)
        layout.addStretch()
        return container

    # ─── Service layer (no GUI side effects, structured dict returns) ───

    def _svc_list_tasks(self) -> dict:
        tasks_data = []
        for task in self._tasks:
            source_label = SOURCE_TYPE_LABELS.get(task.source_type, task.source_type)
            title = task.title
            if task.page and task.source_type == "multi_p":
                title = f"{title} [P{task.page}] {task.page_title}".strip()
            tasks_data.append({
                "seq": task.seq,
                "bv": task.bv,
                "title": title,
                "owner": task.owner or "",
                "source_type": task.source_type,
                "source_label": source_label,
                "status": task.status.value,
                "status_text": self._status_text(task),
                "result_source": task.result_source or "",
                "selected_lang": task.selected_lang or "",
                "error": task.error or "",
                "page": task.page,
                "page_title": task.page_title or "",
                "cid": task.cid,
                "save_selected": bool(task.save_selected),
                "failed_stage": task.failed_stage.value if task.failed_stage else None,
                "nlm_push_status": task.nlm_push_status or "",
            })
        return {"ok": True, "tasks": tasks_data, "total": len(tasks_data)}

    def _svc_batch_status(self) -> dict:
        batch = self._current_batch
        if batch and batch.is_running:
            return {
                "ok": True,
                "is_running": True,
                "batch_id": batch.batch_id,
                "total_count": batch.total_count,
                "done_count": batch.done_count,
                "success_count": batch.success_count,
                "failed_count": batch.failed_count,
                "current_task_seq": batch.current_task_seq,
                "stop_requested": self._stop_requested,
                "started_at": batch.started_at.isoformat() if batch.started_at else None,
                "has_exportable": False,
            }
        last = self._last_batch
        return {
            "ok": True,
            "is_running": False,
            "batch_id": last.batch_id if last else None,
            "total_count": last.total_count if last else 0,
            "done_count": last.done_count if last else 0,
            "success_count": last.success_count if last else 0,
            "failed_count": last.failed_count if last else 0,
            "current_task_seq": None,
            "stop_requested": False,
            "started_at": last.started_at.isoformat() if (last and last.started_at) else None,
            "has_exportable": bool(last and last.success_count > 0),
        }

    def _svc_start_batch(self) -> dict:
        with self._state_lock:
            if self._current_batch and self._current_batch.is_running:
                return {"ok": False, "reason": "batch_running"}

        if self._last_batch and not self._last_batch.temp_cleaned:
            self._cleanup_batch_temp(self._last_batch, keep_assets=False, reason="API启动新批次前清理未导出临时数据")

        queued = [task for task in self._tasks if task.status == TaskStatus.QUEUED]
        if not queued:
            return {"ok": False, "reason": "no_queued_tasks"}

        cookie_header = self._cookie_header_for_api()
        if cookie_header:
            ok, detail = validate_cookie_login(cookie_header)
            if ok:
                self._log(f"提交前登录态校验通过: {detail}", stage="COOKIE")
            else:
                self._log(f"提交前登录态校验失败: {detail}", level="WARN", stage="COOKIE")

        batch = self._create_batch(queued)
        with self._state_lock:
            self._current_batch = batch
            self._current_stage_text = "准备中"
            self._stop_requested = False

        self.btn_submit.setEnabled(False)
        self._refresh_progress_bar()
        self._log(f"批次启动，总任务 {batch.total_count}", stage="BATCH")

        self._worker_thread = threading.Thread(target=self._run_batch_worker, args=(batch,), daemon=True)
        self._worker_thread.start()
        return {"ok": True, "batch_id": batch.batch_id, "total_count": batch.total_count}

    def _svc_stop_batch(self) -> dict:
        with self._state_lock:
            if not (self._current_batch and self._current_batch.is_running):
                return {"ok": False, "reason": "no_running_batch"}
            self._stop_requested = True
        return {"ok": True}

    def _svc_export_batch(self, formats=None, export_zip=False, target_dir=None,
                          notebook_id: str = "", nlm_auto_clean: bool = True) -> dict:
        batch = self._last_batch
        if not batch:
            return {"ok": False, "reason": "no_exportable_batch"}
        if self._current_batch and self._current_batch.is_running:
            return {"ok": False, "reason": "batch_running"}

        nlm_mode = bool(notebook_id)

        # In NLM mode, non-Shape tasks don't need local files — only Shape tasks still export.
        # We always export Shape tasks locally regardless of mode.
        selected_formats = set(formats) if formats else {"srt", "txt", "md"}
        valid_formats = {"srt", "txt", "md"}
        selected_formats = selected_formats & valid_formats
        if not selected_formats:
            selected_formats = {"srt", "txt", "md"}

        archive_root = getattr(self._runtime_config, "archive_root", SHAPE_ROOT) or SHAPE_ROOT
        try:
            summary = export_batch_selected(
                batch,
                selected_formats=selected_formats,
                target_dir=target_dir,
                export_zip=bool(export_zip),
                shape_root=archive_root,
                save_selector=lambda item: bool(getattr(item, "save_selected", False)),
                skip_selected_from_normal_export=True,
                nlm_mode=nlm_mode,
            )
        except Exception as exc:
            return {"ok": False, "reason": "export_failed", "error": str(exc)}

        batch.exported_once = True
        self._snapshot_batch_state(batch, reason="exported_once")

        self.table_refresh_signal.emit()
        self._log(
            f"资料库写入完成: {summary.target_dir} | 格式={','.join(summary.formats)} | 保存 {summary.shape_saved_count} 条，跳过 {summary.skipped_count} 条",
            stage="EXPORT",
        )
        result = {
            "ok": True,
            "path": summary.target_dir,
            "formats": list(summary.formats),
            "normal_exported_count": summary.normal_exported_count,
            "shape_saved_count": summary.shape_saved_count,
            "skipped_count": summary.skipped_count,
            "zip_path": summary.zip_path or "",
            "nlm_push_job_id": "",
        }

        # NLM push: push non-Shape completed tasks
        if nlm_mode:
            from subtitle_pipeline import _load_task_segments as load_segs
            from core_models import TaskStatus as TS
            nlm_tasks = [
                t for t in batch.tasks
                if t.status in (TS.COMPLETED_TRACK, TS.COMPLETED_ASR)
                and not getattr(t, "save_selected", False)
            ]
            if nlm_tasks:
                job_id = self._start_nlm_push(notebook_id, nlm_tasks, batch, auto_clean=nlm_auto_clean)
                result["nlm_push_job_id"] = job_id
            else:
                self._log("无需要推送到 NotebookLM 的任务", stage="NLM")
        else:
            self._cleanup_batch_temp(batch, keep_assets=False, reason="资料库保存完成后清理临时数据")

        return result

    def _svc_remove_task(self, seq: int) -> dict:
        if self._current_batch and self._current_batch.is_running:
            return {"ok": False, "reason": "batch_running"}

        keep = []
        removed = None
        for task in self._tasks:
            if task.seq == seq:
                removed = task
                continue
            keep.append(task)

        if removed is None:
            return {"ok": False, "reason": "not_found"}

        if removed.segments_tmp_json:
            self._safe_remove_path(removed.segments_tmp_json)

        self._tasks = keep
        self._task_key_set.discard(self._task_key(removed.bv, removed.cid))
        self._refresh_table()
        return {"ok": True}

    def _svc_retry_task(self, seq: int) -> dict:
        if self._current_batch and self._current_batch.is_running:
            return {"ok": False, "reason": "batch_running"}

        found = False
        for task in self._tasks:
            if task.seq != seq:
                continue
            found = True
            task.status = TaskStatus.QUEUED
            task.subtitle_state = "未获取"
            task.failed_stage = None
            task.error = None
            task.retry_count = 0
            task.cookie_hint = False
            task.outputs = {}
            task.output_file = None
            task.result_source = ""
            task.selected_lang = ""
            task.segments_cache = []
            task.segments_tmp_json = ""
            task.temp_paths = []
            task.video_file_path = ""
            task.audio_file_path = ""
            task.asset_prepare_error = ""
            task.shape_folder_name = ""
            task.prefetched_segments = []
            task.prefetched_meta = {}
            task.request_cookie_header = None
            task.nlm_source_id = ""
            task.nlm_push_status = ""
            break

        if not found:
            return {"ok": False, "reason": "not_found"}

        self._refresh_table()
        return {"ok": True}

    def _svc_clear_tasks(self) -> dict:
        if self._current_batch and self._current_batch.is_running:
            return {"ok": False, "reason": "batch_running"}

        if self._last_batch and not self._last_batch.temp_cleaned:
            self._cleanup_batch_temp(self._last_batch, keep_assets=False, reason="清空表格时清理临时数据")

        self._tasks.clear()
        self._task_key_set.clear()
        self._refresh_table()
        return {"ok": True}

    # ─── GUI wrappers (thin layer over _svc_* methods) ───

    def _remove_task(self, seq: int):
        result = self._svc_remove_task(seq)
        if not result["ok"] and result.get("reason") == "batch_running":
            QMessageBox.information(self, "提示", "批处理中不可删除任务")

    def _retry_task(self, seq: int):
        result = self._svc_retry_task(seq)
        if not result["ok"] and result.get("reason") == "batch_running":
            QMessageBox.information(self, "提示", "批处理中不可重试")

    def _clear_tasks(self):
        result = self._svc_clear_tasks()
        if not result["ok"] and result.get("reason") == "batch_running":
            QMessageBox.information(self, "提示", "批处理中不可清空")

    def _safe_title(self, title: str) -> str:
        text = title or ""
        text = "".join(ch for ch in text if ord(ch) >= 32 and ch != "\x7f")
        text = re.sub(r'[\\/:*?"<>|]', "_", text)
        text = re.sub(r"\s+", " ", text).strip()
        text = "".join(ch for ch in text if ch.isalnum() or ch in " -_()[]")
        text = re.sub(r"\s+", " ", text).strip()

        if not text:
            text = "Untitled"
        if len(text) > 80:
            text = text[:80].rstrip()
        if not text:
            text = "Untitled"

        reserved = {
            "CON",
            "PRN",
            "AUX",
            "NUL",
            "COM1",
            "COM2",
            "COM3",
            "COM4",
            "COM5",
            "COM6",
            "COM7",
            "COM8",
            "COM9",
            "LPT1",
            "LPT2",
            "LPT3",
            "LPT4",
            "LPT5",
            "LPT6",
            "LPT7",
            "LPT8",
            "LPT9",
        }
        if text.upper() in reserved:
            text = f"_{text}"

        return text or "Untitled"

    def _task_base_name(self, task: TaskItem):
        safe_title = self._safe_title(task.title)
        return f"{task.seq:03d}_{task.bv}_{safe_title}"

    def _safe_remove_path(self, path: str):
        if not path:
            return
        try:
            if os.path.isdir(path):
                shutil.rmtree(path, ignore_errors=True)
            elif os.path.isfile(path):
                os.remove(path)
        except Exception as exc:
            self._log(f"清理失败: {path} -> {exc}", level="WARN", stage="CLEANUP")

    def _cleanup_batch_temp(self, batch: BatchContext, keep_assets: bool, reason: str = ""):
        if not batch or batch.temp_cleaned:
            return

        seen_paths = set()
        for task in batch.tasks:
            task.segments_cache = []
            if task.segments_tmp_json:
                if task.segments_tmp_json not in seen_paths:
                    self._safe_remove_path(task.segments_tmp_json)
                    seen_paths.add(task.segments_tmp_json)
                task.segments_tmp_json = ""

            for path in list(task.temp_paths):
                if path in seen_paths:
                    continue
                self._safe_remove_path(path)
                seen_paths.add(path)
            task.temp_paths = []

            task.video_file_path = ""
            task.audio_file_path = ""
            task.asset_prepare_error = ""
            task.shape_folder_name = ""
            task.prefetched_segments = []
            task.prefetched_meta = {}
            task.request_cookie_header = None

        batch.media_cache.clear()
        if batch.tmp_subtitle_dir and os.path.isdir(batch.tmp_subtitle_dir):
            self._safe_remove_path(batch.tmp_subtitle_dir)
        batch.temp_cleaned = True
        if reason:
            self._log(reason, stage="CLEANUP")

    # ─── NotebookLM push worker ───

    def _start_nlm_push(self, notebook_id: str, tasks: list, batch, *, auto_clean: bool = True) -> str:
        """Launch an NLM push thread. Returns a job_id immediately."""
        job_id = str(uuid.uuid4())[:8]
        self._nlm_push_cancel = False

        # Mark tasks as pushing
        for task in tasks:
            task.nlm_push_status = "pushing"
        self.table_refresh_signal.emit()

        def _worker():
            def _on_task_pushed(seq, source_id):
                for t in tasks:
                    if t.seq == seq:
                        t.nlm_source_id = source_id
                        t.nlm_push_status = "pushed"
                        break
                self.table_refresh_signal.emit()

            def _on_task_failed(seq, err):
                for t in tasks:
                    if t.seq == seq:
                        t.nlm_push_status = "push_failed"
                        break
                self.table_refresh_signal.emit()

            def _progress(pushed, total, title):
                self.progress_signal.emit(pushed, total, f"NLM 推送 {pushed}/{total}: {title}")

            def _build_md(task, segments):
                source = task.result_source or "unknown"
                lang = task.selected_lang or "unknown"
                return build_md_content(task, segments, source=source, language=lang)

            result = None
            try:
                result = nlm_client.run_push_job(
                    notebook_id,
                    tasks,
                    build_md_func=_build_md,
                    load_segments_func=_load_task_segments,
                    render_title_func=render_notebooklm_title,
                    progress_cb=_progress,
                    task_pushed_cb=_on_task_pushed,
                    task_failed_cb=_on_task_failed,
                    cancel_flag=lambda: self._nlm_push_cancel,
                )
            except Exception as exc:
                self._log(f"NLM 推送异常: {exc}", level="ERROR", stage="NLM")
                # Mark remaining as failed
                for t in tasks:
                    if t.nlm_push_status == "pushing":
                        t.nlm_push_status = "push_failed"

            self._nlm_push_jobs[job_id] = result
            # Attach metadata for the completion handler
            if result:
                result._batch = batch
                result._auto_clean = auto_clean
            self.nlm_push_finished_signal.emit(result)

        self._nlm_push_thread = threading.Thread(target=_worker, daemon=True)
        self._nlm_push_thread.start()
        self._nlm_push_jobs[job_id] = None  # placeholder until finished
        self._log(f"NLM 推送已启动 (job={job_id})，共 {len(tasks)} 条", stage="NLM")
        return job_id

    def _on_nlm_push_finished(self, result):
        """Slot called on the GUI thread when an NLM push job finishes."""
        self._nlm_push_thread = None
        if result is None:
            self._log("NLM 推送失败（无结果）", level="ERROR", stage="NLM")
            self.table_refresh_signal.emit()
            return

        self._log(
            f"NLM 推送完成: 成功 {result.pushed}/{result.total}，失败 {result.failed}",
            stage="NLM",
        )

        # Save snapshot with NLM source IDs
        batch = getattr(result, "_batch", None)
        if batch:
            self._snapshot_batch_state(batch, reason="nlm_push_finished")

        # Auto cleanup if enabled and all non-Shape tasks succeeded
        auto_clean = getattr(result, "_auto_clean", False)
        if auto_clean and result.failed == 0 and batch:
            self._cleanup_batch_temp(batch, keep_assets=False, reason="NLM 推送成功后自动清理临时数据")

        self.table_refresh_signal.emit()
        self.progress_signal.emit(result.pushed, max(result.total, 1), f"NLM 推送完成 {result.pushed}/{result.total}")

    def _svc_nlm_auth_status(self) -> dict:
        """Return NLM auth status dict for API / GUI. Auto-refreshes if expired."""
        status = nlm_client.ensure_auth_valid()
        return {
            "ok": True,
            "available": nlm_client.is_nlm_available(),
            "status": status.value,
            "lib_error": nlm_client.nlm_import_error() or "",
        }

    def _svc_nlm_push_status(self, job_id: str) -> dict:
        """Poll a push job by its ID."""
        if job_id not in self._nlm_push_jobs:
            return {"ok": False, "reason": "not_found"}
        result = self._nlm_push_jobs[job_id]
        if result is None:
            return {"ok": True, "state": "running"}
        return {
            "ok": True,
            "state": "finished",
            "pushed": result.pushed,
            "failed": result.failed,
            "total": result.total,
            "errors": result.errors,
        }

    def _ensure_task_temp_path(self, task: TaskItem, path: str):
        if not path:
            return
        if path not in task.temp_paths:
            task.temp_paths.append(path)

    def _prepare_media_for_selected_task(self, batch: BatchContext, task: TaskItem, cookie_header: Optional[str], cookies_file: Optional[str]):
        cache_lock = getattr(self, "_media_cache_lock", None) or threading.Lock()
        with cache_lock:
            cache = batch.media_cache.get(task.bv)
        if cache:
            task.video_file_path = cache.get("video", "")
            task.audio_file_path = cache.get("audio", "")
            for path in cache.get("temp_paths", []):
                self._ensure_task_temp_path(task, path)
            return

        output_dir = os.path.join("bilibili_video", task.bv)
        video_path = download_video_prefer_1080(
            task.video_link or task.bv,
            output_dir=output_dir,
            cookie_header=cookie_header,
            cookies_file=cookies_file,
        )
        if not video_path:
            raise RuntimeError("1080优先下载失败")

        audio_target = f"{task.bv}_asset"
        audio_path = convert_flv_to_mp3(task.bv, target_name=audio_target, folder="bilibili_video")

        temp_paths = [output_dir, audio_path]
        with cache_lock:
            batch.media_cache[task.bv] = {
                "video": video_path,
                "audio": audio_path,
                "temp_paths": temp_paths,
            }
        task.video_file_path = video_path
        task.audio_file_path = audio_path
        for path in temp_paths:
            self._ensure_task_temp_path(task, path)

    def _on_load_whisper(self):
        model_name = self.model_combo.currentText()
        if TORCH_PRELOAD_ERROR is not None:
            self._log(f"Torch runtime preload failed: {TORCH_PRELOAD_ERROR}", level="ERROR", stage="MODEL")
            self.progress_signal.emit(0, 1, "加载失败")
            return

        self._log(f"正在加载 Whisper 模型 ({model_name})", stage="MODEL")
        self.progress_signal.emit(0, 0, "正在加载模型")

        def _load():
            try:
                s2t.load_whisper(model=model_name)
                mode = "CUDA" if s2t.whisper.torch.cuda.is_available() else "CPU"
                self._log(f"Whisper 加载成功，当前使用 {mode}", stage="MODEL")
                self.progress_signal.emit(1, 1, "模型已就绪")
            except Exception as exc:
                self._log(f"Whisper 加载失败: {exc}", level="ERROR", stage="MODEL")
                self.progress_signal.emit(0, 1, "加载失败")

        threading.Thread(target=_load, daemon=True).start()

    def _snapshot_batch_state(self, batch: Optional[BatchContext], reason: str):
        if not batch:
            return
        if not batch.state_path:
            return
        try:
            save_batch_state(batch, reason=reason)
        except Exception as exc:
            self._log(f"state.json 写入失败: {exc}", level="WARN", stage="STATE")

    def _on_submit(self):
        result = self._svc_start_batch()
        if not result["ok"]:
            reason = result.get("reason", "")
            if reason == "batch_running":
                QMessageBox.information(self, "提示", "当前批次正在进行中")
            elif reason == "no_queued_tasks":
                QMessageBox.information(self, "提示", "没有待处理任务（可先添加任务或对失败任务点重试）")

    def _create_batch(self, run_tasks: list[TaskItem]) -> BatchContext:
        batch_id = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
        batch_state_dir = os.path.join("config", "batches", batch_id)
        tmp_subtitle_dir = os.path.join("config", "tmp", batch_id)
        archive_root = getattr(self._runtime_config, "archive_root", SHAPE_ROOT) or SHAPE_ROOT

        for path in (batch_state_dir, tmp_subtitle_dir):
            os.makedirs(path, exist_ok=True)

        batch = BatchContext(
            batch_id=batch_id,
            started_at=datetime.now(),
            model=self.model_combo.currentText(),
            tasks=list(run_tasks),
            total_count=len(run_tasks),
            export_dir=os.path.abspath(os.path.expanduser(str(archive_root))),
            tmp_subtitle_dir=tmp_subtitle_dir,
            state_path=os.path.join(batch_state_dir, "state.json"),
            failed_state_path=os.path.join(batch_state_dir, "failed.json"),
            io_workers=max(1, min(int(self._runtime_config.io_workers or 2), 4)),
            resumed_from=self._resume_from_state or "",
            state_version=STATE_SCHEMA_VERSION,
            core_version=CORE_VERSION,
            is_running=True,
            exported_once=False,
            temp_cleaned=False,
            media_cache={},
        )

        for task in run_tasks:
            task.subtitle_state = "排队中"
            batch.task_queue.put(task)

        self._resume_from_state = ""
        self._snapshot_batch_state(batch, reason="batch_created")
        self.table_refresh_signal.emit()
        return batch

    def _run_batch_worker(self, batch: BatchContext):
        worker_count = max(1, min(int(batch.io_workers or 2), 4))

        def _worker_loop():
            while True:
                if self._stop_requested:
                    return
                try:
                    task = batch.task_queue.get_nowait()
                except queue.Empty:
                    return
                self._process_task(batch, task)

        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            futures = [executor.submit(_worker_loop) for _ in range(worker_count)]
            for future in as_completed(futures):
                try:
                    future.result()
                except Exception as exc:
                    self._log(f"并发worker异常: {exc}", level="ERROR", stage="BATCH")

        self._finalize_batch(batch)
        self.batch_finished_signal.emit(batch)

    def _set_stage_text(self, text: str):
        with self._state_lock:
            self._current_stage_text = text
        self._refresh_progress_bar()

    def _find_task_by_seq(self, batch: BatchContext, seq: Optional[int]) -> Optional[TaskItem]:
        if seq is None:
            return None
        for task in batch.tasks:
            if task.seq == seq:
                return task
        return None

    def _mark_task_failed(self, batch: BatchContext, task: TaskItem, stage: FailStage, message: str):
        with self._state_lock:
            task.status = TaskStatus.FAILED
            task.failed_stage = stage
            task.error = message
            task.subtitle_state = f"失败: {stage.value}"
            batch.running_count = max(0, batch.running_count - 1)
            batch.failed_count += 1
            batch.done_count += 1
            batch.current_task_seq = None

        self._log(message, level="ERROR", stage=stage.value, task=task)
        self._snapshot_batch_state(batch, reason=f"task_terminal_failed:{task.seq}")
        self.table_refresh_signal.emit()
        self._refresh_progress_bar()

    def _mark_task_success(self, batch: BatchContext, task: TaskItem):
        with self._state_lock:
            batch.running_count = max(0, batch.running_count - 1)
            batch.success_count += 1
            batch.done_count += 1
            batch.current_task_seq = None

        if task.status == TaskStatus.COMPLETED_ASR:
            reason = f"task_terminal_completed_asr:{task.seq}"
        else:
            reason = f"task_terminal_completed_track:{task.seq}"
        self._snapshot_batch_state(batch, reason=reason)
        self.table_refresh_signal.emit()
        self._refresh_progress_bar()

    def _set_task_status(self, batch: BatchContext, task: TaskItem, status: TaskStatus, state_text: str):
        with self._state_lock:
            task.status = status
            task.subtitle_state = state_text
            batch.current_task_seq = task.seq
        self.table_refresh_signal.emit()
        self._set_stage_text(state_text)

    def _process_task(self, batch: BatchContext, task: TaskItem):
        if self._stop_requested:
            return

        with self._state_lock:
            batch.running_count += 1
            batch.current_task_seq = task.seq

        attempt = 0
        while True:
            if self._stop_requested:
                with self._state_lock:
                    batch.running_count = max(0, batch.running_count - 1)
                    batch.current_task_seq = None
                    if task.status == TaskStatus.QUEUED:
                        task.subtitle_state = "已停止"
                return
            try:
                self._process_task_once(batch, task)
                self._mark_task_success(batch, task)
                return
            except StageFailure as exc:
                if attempt < 1 and exc.retryable and should_retry_error(str(exc)):
                    attempt += 1
                    task.retry_count += 1
                    self._log(f"任务重试({attempt}/1): {exc}", level="WARN", stage=exc.stage.value, task=task)
                    continue
                self._mark_task_failed(batch, task, exc.stage, str(exc))
                return
            except Exception as exc:
                self._mark_task_failed(batch, task, FailStage.EXPORT, f"未预期错误: {exc}")
                return

    def _process_task_once(self, batch: BatchContext, task: TaskItem):
        cookie_mode = self._current_cookie_mode()
        cookies_file = self._cookies_file_path()
        task_cookie_header = str(getattr(task, "request_cookie_header", "") or "").strip()
        cookie_header = task_cookie_header or self._cookie_header_for_api()
        task.asset_prepare_error = ""
        task.shape_folder_name = self._safe_title(task.title)
        task.segments_cache = []
        task.segments_tmp_json = ""
        task.outputs = {}
        task.output_file = None
        task.video_file_path = ""
        task.audio_file_path = ""
        task.temp_paths = []

        prefetched_segments = self._sanitize_prefetched_segments(getattr(task, "prefetched_segments", []))
        prefetched_meta = dict(getattr(task, "prefetched_meta", {}) or {})
        if prefetched_segments:
            lang = str(prefetched_meta.get("lang") or "unknown").strip() or "unknown"
            track_type = str(prefetched_meta.get("track_type") or "uploader").strip().lower()
            if track_type not in {"uploader", "ai"}:
                track_type = "uploader"

            task.selected_lang = lang
            task.segments_cache = prefetched_segments
            task.segments_tmp_json = ""
            task.outputs = {}
            task.output_file = None
            task.result_source = f"browser_prefetch_{track_type}"

            if task.save_selected:
                try:
                    self._prepare_media_for_selected_task(batch, task, cookie_header, cookies_file)
                except Exception as exc:
                    task.asset_prepare_error = str(exc)
                    self._log(f"补媒体失败: {exc}", level="WARN", stage="DOWNLOAD", task=task)

            task.status = TaskStatus.COMPLETED_TRACK
            task.subtitle_state = "已获取(轨道)"
            task.prefetched_segments = []
            task.prefetched_meta = {}
            self._log(
                f"PREFETCH_HIT: consumed {len(prefetched_segments)} segments ({lang}, {track_type})",
                stage="PREFETCH",
                task=task,
            )
            return

        if getattr(task, "prefetched_segments", None) or prefetched_meta:
            task.prefetched_segments = []
            task.prefetched_meta = {}
            self._log("PREFETCH_INVALID: no usable segments on task", level="WARN", stage="PREFETCH", task=task)

        self._set_task_status(batch, task, TaskStatus.RESOLVING_TRACKS, "获取字幕轨道")
        self._log("开始发现字幕轨道", stage="TRACK_DISCOVERY", task=task)

        try:
            ensure_task_identifiers(task, cookie_header=cookie_header)
        except BiliSubtitleAPIError as exc:
            self._log(f"补全 aid/cid 失败，继续降级流程: {exc}", level="WARN", stage="TRACK_DISCOVERY", task=task)

        api_tracks: list[ApiTrack] = []
        try:
            api_tracks, api_meta = discover_bili_tracks(
                task,
                cookie_header=cookie_header,
            )
            task.cookie_hint = task.cookie_hint or api_meta.cookie_hint
            if api_meta.warnings:
                self._log(
                    "B站API警告: " + " | ".join(api_meta.warnings[:3]),
                    level="WARN",
                    stage="TRACK_DISCOVERY",
                    task=task,
                )
        except BiliSubtitleAPIError as exc:
            self._log(f"B站API轨道发现失败，降级 yt-dlp: {exc}", level="WARN", stage="TRACK_DISCOVERY", task=task)
            api_tracks = []

        if api_tracks:
            api_rank_tracks = [TrackInfo(lang=t.lang, track_type=t.track_type, ext="json") for t in api_tracks]
            selected = select_track(api_rank_tracks, policy="zh_first")
            if selected is not None:
                api_track = next(
                    (
                        item
                        for item in api_tracks
                        if item.lang == selected.lang and item.track_type == selected.track_type
                    ),
                    api_tracks[0],
                )
                task.selected_lang = api_track.lang
                self._set_task_status(batch, task, TaskStatus.DOWNLOADING_TRACK, f"B站API下载轨道({api_track.lang})")
                self._log(
                    f"B站API选中轨道: {api_track.lang} ({api_track.track_type})",
                    stage="TRACK_DOWNLOAD",
                    task=task,
                )

                try:
                    segments = fetch_bili_track_segments(task, api_track, cookie_header=cookie_header)
                    if not segments:
                        raise BiliSubtitleAPIError("subtitle payload has no usable segments")
                except BiliSubtitleAPIError as exc:
                    self._log(f"B站API轨道下载失败，降级 yt-dlp: {exc}", level="WARN", stage="TRACK_DOWNLOAD", task=task)
                else:
                    source_code = f"bili_api_{api_track.track_type}"
                    task.segments_cache = [
                        {
                            "start_sec": float(seg["start_sec"]),
                            "end_sec": float(seg["end_sec"]),
                            "text": str(seg["text"]),
                        }
                        for seg in segments
                    ]
                    task.segments_tmp_json = ""
                    task.outputs = {}
                    task.output_file = None
                    task.result_source = source_code
                    if task.save_selected:
                        try:
                            self._prepare_media_for_selected_task(batch, task, cookie_header, cookies_file)
                        except Exception as exc:
                            task.asset_prepare_error = str(exc)
                            self._log(f"补媒体失败: {exc}", level="WARN", stage="DOWNLOAD", task=task)
                    task.status = TaskStatus.COMPLETED_TRACK
                    task.subtitle_state = "已获取(轨道)"
                    self._log("B站API轨道字幕获取完成", stage="TRACK_DOWNLOAD", task=task)
                    return

        self._set_task_status(batch, task, TaskStatus.RESOLVING_TRACKS, "获取字幕轨道(yt-dlp)")
        self._log("开始使用 yt-dlp 发现字幕轨道", stage="TRACK_DISCOVERY", task=task)

        tracks = []
        try:
            tracks, meta = discover_tracks_with_meta(
                task,
                cookie_mode=cookie_mode,
                cookies_file=cookies_file,
                cookie_header=cookie_header,
            )
            task.cookie_hint = task.cookie_hint or meta.cookie_hint
        except SubtitleError as exc:
            self._log(f"yt-dlp轨道发现失败，降级 ASR: {exc}", level="WARN", stage="TRACK_DISCOVERY", task=task)
            tracks = []

        if tracks:
            track = select_track(tracks, policy="zh_first")
            if track is not None:
                task.selected_lang = track.lang
                self._set_task_status(batch, task, TaskStatus.DOWNLOADING_TRACK, f"下载字幕轨道({track.lang})")
                self._log(f"选中轨道: {track.lang} ({track.track_type})", stage="TRACK_DOWNLOAD", task=task)

                try:
                    track_srt = download_track_srt(
                        task,
                        track,
                        cookie_mode=cookie_mode,
                        cookies_file=cookies_file,
                        cookie_header=cookie_header,
                        out_dir=batch.tmp_subtitle_dir,
                    )
                    segments = parse_srt_to_segments(track_srt)
                    if not segments:
                        raise SubtitleError("subtitle file parsed but no segments found")
                except SubtitleError as exc:
                    self._log(f"yt-dlp轨道下载失败，降级 ASR: {exc}", level="WARN", stage="TRACK_DOWNLOAD", task=task)
                    segments = None

                if segments:
                    source_code = f"yt_dlp_{track.track_type}"
                    task.segments_cache = [
                        {
                            "start_sec": float(seg.start_sec if hasattr(seg, "start_sec") else seg["start_sec"]),
                            "end_sec": float(seg.end_sec if hasattr(seg, "end_sec") else seg["end_sec"]),
                            "text": str(seg.text if hasattr(seg, "text") else seg["text"]),
                        }
                        for seg in segments
                    ]
                    task.segments_tmp_json = ""
                    task.outputs = {}
                    task.output_file = None
                    task.result_source = source_code
                    if task.save_selected:
                        try:
                            self._prepare_media_for_selected_task(batch, task, cookie_header, cookies_file)
                        except Exception as exc:
                            task.asset_prepare_error = str(exc)
                            self._log(f"补媒体失败: {exc}", level="WARN", stage="DOWNLOAD", task=task)
                    task.status = TaskStatus.COMPLETED_TRACK
                    task.subtitle_state = "已获取(轨道)"
                    self._log("yt-dlp轨道字幕获取完成", stage="TRACK_DOWNLOAD", task=task)
                    return

        asr_gate = getattr(self, "_asr_semaphore", None) or threading.Semaphore(1)
        cache_lock = getattr(self, "_media_cache_lock", None) or threading.Lock()
        with asr_gate:
            self._set_task_status(batch, task, TaskStatus.TRANSCRIBING_ASR, "ASR下载中")
            self._log("轨道不可用，切换 ASR 兜底", stage="DOWNLOAD", task=task)
            if task.save_selected:
                with cache_lock:
                    cache = batch.media_cache.get(task.bv)
                cached_video = (cache or {}).get("video", "")
                if cached_video and os.path.exists(cached_video):
                    video_path = cached_video
                    output_dir = os.path.dirname(cached_video)
                else:
                    output_dir = os.path.join("bilibili_video", task.bv)
                    video_path = download_video_prefer_1080(
                        task.video_link or task.bv,
                        output_dir=output_dir,
                        cookie_header=cookie_header,
                        cookies_file=cookies_file,
                    )
                    if not video_path:
                        raise StageFailure(FailStage.DOWNLOAD, "下载失败，未获取到有效媒体文件", retryable=True)
                file_identifier = task.bv
                task.video_file_path = video_path
                self._ensure_task_temp_path(task, output_dir)
                with cache_lock:
                    media_cache = batch.media_cache.get(task.bv, {"video": "", "audio": "", "temp_paths": []})
                    media_cache["video"] = video_path
                    if output_dir not in media_cache["temp_paths"]:
                        media_cache["temp_paths"].append(output_dir)
                    batch.media_cache[task.bv] = media_cache
            else:
                file_identifier = download_video(task.bv[2:])
                if not file_identifier:
                    raise StageFailure(FailStage.DOWNLOAD, "下载失败，未获取到有效媒体文件", retryable=True)
                output_dir = os.path.join("bilibili_video", file_identifier)
                task.video_file_path = find_primary_media_file(output_dir)
                self._ensure_task_temp_path(task, output_dir)

            inferred = infer_download_title(task.bv)
            if inferred and inferred != "UnknownTitle":
                task.title = inferred

            self._set_task_status(batch, task, TaskStatus.TRANSCRIBING_ASR, "ASR切片中")
            try:
                folder_name = process_audio_split(file_identifier)
            except Exception as exc:
                raise StageFailure(FailStage.AUDIO_SPLIT, f"音频切片失败: {exc}")
            task.audio_file_path = os.path.join("audio", "conv", f"{folder_name}.mp3")
            slice_dir = os.path.join("audio", "slice", folder_name)
            for path in (task.audio_file_path, slice_dir):
                if os.path.exists(path):
                    self._ensure_task_temp_path(task, path)
            if task.save_selected:
                with cache_lock:
                    cache = batch.media_cache.get(task.bv, {})
                    cache["audio"] = task.audio_file_path
                    cache.setdefault("temp_paths", [])
                    for path in (task.audio_file_path, slice_dir):
                        if path not in cache["temp_paths"]:
                            cache["temp_paths"].append(path)
                    batch.media_cache[task.bv] = cache

            def _progress(cur: int, total: int):
                with self._state_lock:
                    task.transcribe_cur = cur
                    task.transcribe_total = total
                    task.subtitle_state = f"ASR转写 {cur}/{total}"
                self.table_refresh_signal.emit()
                self._refresh_progress_bar()

            self._set_task_status(batch, task, TaskStatus.TRANSCRIBING_ASR, "ASR转写中")
            try:
                segments = s2t.transcribe_to_segments(
                    folder_name,
                    model=batch.model,
                    prompt="以下是普通话句子，这是一个关于视频内容的转写。",
                    progress_callback=_progress,
                )
                if not segments:
                    raise RuntimeError("ASR produced empty segments")
            except Exception as exc:
                raise StageFailure(FailStage.TRANSCRIBE, f"转写失败: {exc}")

        base_name = self._task_base_name(task)
        tmp_json_path = os.path.join(batch.tmp_subtitle_dir, f"{base_name}_segments.json")
        try:
            dump_segments_to_tmp_json(tmp_json_path, segments)
        except Exception as exc:
            raise StageFailure(FailStage.EXPORT, f"临时结果写入失败: {exc}")

        task.segments_cache = []
        task.segments_tmp_json = tmp_json_path
        task.outputs = {}
        task.output_file = None
        task.result_source = "asr"
        task.selected_lang = "asr"
        task.status = TaskStatus.COMPLETED_ASR
        task.subtitle_state = "已获取(ASR)"
        self._log("ASR 兜底完成", stage="TRANSCRIBE", task=task)

    def _finalize_batch(self, batch: BatchContext):
        batch.is_running = False
        batch.current_task_seq = None

        try:
            if os.path.isdir(batch.tmp_subtitle_dir):
                for srt_path in [item for item in os.listdir(batch.tmp_subtitle_dir) if item.lower().endswith(".srt")]:
                    self._safe_remove_path(os.path.join(batch.tmp_subtitle_dir, srt_path))
        except Exception:
            pass

        if batch.failed_state_path:
            try:
                write_failed_tasks_json(batch.failed_state_path, batch.tasks)
            except Exception as exc:
                self._log(f"failed.json 写入失败: {exc}", level="WARN", stage="STATE")

        self._log(
            f"批次结束：总数 {batch.total_count}，成功 {batch.success_count}，失败 {batch.failed_count}",
            stage="BATCH",
        )
        final_reason = "batch_stopped" if self._stop_requested else "batch_finished"
        self._snapshot_batch_state(batch, reason=final_reason)

    def _on_batch_finished(self, batch: BatchContext):
        with self._state_lock:
            self._last_batch = batch
            self._current_batch = None
            self._current_stage_text = "就绪"
            self._worker_thread = None
            stopped = bool(self._stop_requested and batch.done_count < batch.total_count)
            self._stop_requested = False

        self.btn_submit.setEnabled(True)
        if stopped:
            text = f"批处理已停止 {batch.done_count}/{batch.total_count}（成功{batch.success_count}，失败{batch.failed_count}）"
        else:
            text = f"批处理完成 {batch.done_count}/{batch.total_count}（成功{batch.success_count}，失败{batch.failed_count}）"
        self.progress_signal.emit(
            batch.done_count,
            batch.total_count if batch.total_count > 0 else 1,
            text,
        )
        self.table_refresh_signal.emit()

    def _refresh_progress_bar(self):
        with self._state_lock:
            batch = self._current_batch
            if not batch:
                self.progress_signal.emit(0, 1, "就绪")
                return

            total = max(batch.total_count, 1)
            done = min(batch.done_count, total)
            if batch.done_count >= batch.total_count and batch.total_count > 0:
                text = f"批处理完成 {batch.done_count}/{batch.total_count}"
            else:
                cur_task = self._find_task_by_seq(batch, batch.current_task_seq)
                if cur_task:
                    text = f"批处理 {done}/{batch.total_count} | 当前 {cur_task.bv}: {self._current_stage_text}"
                else:
                    text = f"批处理 {done}/{batch.total_count} | 等待中"

        self.progress_signal.emit(done, total, text)

    def _on_progress(self, value: int, maximum: int, text: str):
        self.progress_bar.setMaximum(maximum if maximum > 0 else 1)
        self.progress_bar.setValue(max(0, value))
        self.progress_bar.setFormat(text)

    def _on_export(self):
        batch = self._last_batch
        if not batch:
            QMessageBox.information(self, "提示", "暂无可导出的批次")
            return

        if self._current_batch and self._current_batch.is_running:
            QMessageBox.information(self, "提示", "当前批次仍在运行，请稍后导出")
            return

        if self._nlm_push_thread and self._nlm_push_thread.is_alive():
            QMessageBox.information(self, "提示", "NotebookLM 推送进行中，请稍后")
            return

        cfg = self._runtime_config
        dialog = ExportOptionsDialog(
            self,
            nlm_enabled=cfg.notebooklm_enabled,
            nlm_notebook_id=cfg.notebooklm_notebook_id,
            nlm_auto_clean=cfg.notebooklm_auto_clean,
        )
        if dialog.exec_() != QDialog.Accepted:
            return

        nlm_push = dialog.nlm_push_enabled()
        notebook_id = dialog.nlm_notebook_id()
        nlm_auto_clean = dialog.nlm_auto_clean()

        selected_formats = dialog.selected_formats()
        if not selected_formats and not nlm_push:
            QMessageBox.information(self, "提示", "请至少选择一种导出格式或启用 NotebookLM 推送")
            return

        if nlm_push and not notebook_id:
            QMessageBox.warning(self, "提示", "请选择一个目标 Notebook")
            return

        # Persist NLM settings
        if nlm_push:
            cfg.notebooklm_enabled = True
            cfg.notebooklm_notebook_id = notebook_id
            cfg.notebooklm_auto_clean = nlm_auto_clean
            save_runtime_config(cfg)

        result = self._svc_export_batch(
            formats=selected_formats,
            export_zip=dialog.export_zip(),
            target_dir=None,
            notebook_id=notebook_id if nlm_push else "",
            nlm_auto_clean=nlm_auto_clean,
        )
        if not result["ok"]:
            QMessageBox.warning(self, "导出失败", result.get("error") or result.get("reason", "未知错误"))
        elif result.get("nlm_push_job_id"):
            QMessageBox.information(
                self, "NLM 推送已启动",
                f"推送任务 {result['nlm_push_job_id']} 已在后台运行，完成后将自动通知。",
            )

    def closeEvent(self, event):
        if not self._quit_requested and self._tray_icon is not None:
            self.hide()
            if self._tray_icon is not None:
                self._tray_icon.showMessage(
                    "BilibiliHarvest",
                    "后台服务仍在运行，可从系统托盘继续打开控制台或状态窗口。",
                    QSystemTrayIcon.Information,
                    4000,
                )
            event.ignore()
            return

        running_batch = self._current_batch if (self._current_batch and self._current_batch.is_running) else None
        if running_batch:
            reply = QMessageBox.question(
                self,
                "确认退出",
                "批次正在运行，确定要退出并停止处理吗？",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if reply != QMessageBox.Yes:
                event.ignore()
                return

            self._stop_requested = True
            if self._worker_thread and self._worker_thread.is_alive():
                self._worker_thread.join(timeout=3)

        if self._last_batch and not self._last_batch.temp_cleaned:
            self._cleanup_batch_temp(self._last_batch, keep_assets=False, reason="退出时清理临时数据")
        self._stop_local_http_service()
        event.accept()

    def _clear_log(self):
        self.log_panel.clear()
        self.progress_bar.setMaximum(1)
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat("就绪")


def main(*, show_window: bool = False, force_http_enabled: bool = False):
    app = QApplication(sys.argv)
    app.setStyleSheet(qdarkstyle.load_stylesheet_pyqt5() + EXTRA_QSS)
    app.setFont(QFont("Microsoft YaHei UI", 10))

    window = MainWindow(force_http_enabled=force_http_enabled)
    app.setQuitOnLastWindowClosed(False)
    if show_window or not QSystemTrayIcon.isSystemTrayAvailable():
        window.show()
    else:
        print("[INFO] BilibiliHarvest running in background mode.")
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()

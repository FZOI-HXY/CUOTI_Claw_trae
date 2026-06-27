"""
UploadTabMixin - 上传处理标签页
包含: 文件队列管理, 拖拽, 批量 OCR 处理流程 (上传→提交→轮询→结果)
"""
from __future__ import annotations

from pathlib import Path
from typing import List, Dict, Any, TYPE_CHECKING

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel,
    QFileDialog, QProgressBar,
    QSplitter, QGroupBox, QGridLayout,
    QListWidget, QListWidgetItem, QMessageBox, QApplication,
    QTextEdit,
)
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QColor

from apps.desktop.utils import format_size
from apps.desktop.workers.api_task import UploadWorker, SubmitWorker, PollWorker, ApiTask

if TYPE_CHECKING:
    from PyQt6.QtWidgets import QTabWidget, QTableWidget


class UploadTabMixin:
    """
    上传处理标签页 Mixin
    提供文件队列管理 + 完整批量处理流程
    """

    # ---- 类型标注（实际属性由 StandaloneApp / 其他 Mixin 设置） ----
    api_base: str
    file_queue: List[Dict]
    batch_results: List[Dict]
    processing: bool
    active_workers: list

    # UI 控件引用
    tab_widget: QTabWidget
    file_list_widget: QListWidget
    progress_bar: QProgressBar
    progress_text: QLabel
    progress_info: QLabel
    markdown_view: QTextEdit
    step_labels: Dict[str, QLabel]
    stats_grid: QGridLayout
    server_status_label: QLabel
    history_table: QTableWidget

    # 按钮控件
    btn_select_files: QPushButton
    btn_select_folder: QPushButton
    btn_clear_queue: QPushButton
    btn_process_all: QPushButton
    btn_copy_md: QPushButton

    # 来自 AppBaseMixin（可调用方法）
    show_toast: Any
    _reset_steps: Any
    _set_step_active: Any
    _set_step_complete: Any
    _safe_remove_worker: Any
    _render_markdown_html: Any

    # 来自 history_mixin
    load_history: Any

    # 来自 reports_mixin
    load_reports: Any

    # ============ 标签页创建 ============

    def create_upload_tab(self):
        """上传处理标签页"""
        tab = QWidget()
        tab.setAcceptDrops(True)
        layout = QVBoxLayout(tab)
        layout.setSpacing(12)

        # ---- 上传区域 ----
        upload_group = QGroupBox("文件上传区")
        upload_layout = QVBoxLayout(upload_group)

        hint_bar = QHBoxLayout()
        upload_info = QLabel("拖拽文件/文件夹到此处，或使用下方按钮选择（右键选择文件夹）")
        upload_info.setStyleSheet("color: #8b95a8; font-size: 12px;")
        hint_bar.addWidget(upload_info)
        hint_bar.addStretch()
        upload_layout.addLayout(hint_bar)

        btn_bar = QHBoxLayout()
        self.btn_select_files = QPushButton("选择文件")
        self.btn_select_files.clicked.connect(self.select_files)  # type: ignore[arg-type]
        btn_bar.addWidget(self.btn_select_files)

        self.btn_select_folder = QPushButton("选择文件夹")
        self.btn_select_folder.clicked.connect(self.select_folder)  # type: ignore[arg-type]
        btn_bar.addWidget(self.btn_select_folder)

        btn_bar.addStretch()

        self.btn_clear_queue = QPushButton("清空队列")
        self.btn_clear_queue.setObjectName("ghostBtn")
        self.btn_clear_queue.clicked.connect(self.clear_queue)
        btn_bar.addWidget(self.btn_clear_queue)

        self.btn_process_all = QPushButton("全部处理")
        self.btn_process_all.setObjectName("primaryBtn")
        self.btn_process_all.clicked.connect(self.process_all_files)
        btn_bar.addWidget(self.btn_process_all)

        upload_layout.addLayout(btn_bar)

        self.file_list_widget = QListWidget()
        self.file_list_widget.setMinimumHeight(120)
        self.file_list_widget.setMaximumHeight(220)
        self.file_list_widget.setAlternatingRowColors(False)
        upload_layout.addWidget(self.file_list_widget)

        layout.addWidget(upload_group)

        # ---- 进度区域 ----
        progress_group = QGroupBox("处理进度")
        progress_layout = QVBoxLayout(progress_group)

        steps_layout = QHBoxLayout()
        self.step_labels = {}
        for step_key, step_name in [("upload", "上传文件"), ("analyze", "模型识别"), ("report", "生成报告")]:
            lbl = QLabel(f"● {step_name}")
            lbl.setStyleSheet("color: #4b5563; font-size: 12px; padding: 4px 12px;")
            steps_layout.addWidget(lbl)
            self.step_labels[step_key] = lbl
        steps_layout.addStretch()
        progress_layout.addLayout(steps_layout)

        self.progress_text = QLabel("等待处理...")
        self.progress_text.setStyleSheet("color: #e8ecf1; font-size: 14px; font-weight: 600;")
        progress_layout.addWidget(self.progress_text)

        self.progress_info = QLabel("")
        self.progress_info.setStyleSheet("color: #8b95a8; font-size: 12px;")
        progress_layout.addWidget(self.progress_info)

        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        progress_layout.addWidget(self.progress_bar)

        layout.addWidget(progress_group)

        # ---- 结果面板 ----
        result_splitter = QSplitter(Qt.Orientation.Horizontal)

        stats_container = QWidget()
        stats_layout = QVBoxLayout(stats_container)
        stats_layout.setContentsMargins(0, 0, 0, 0)
        stats_header = QLabel("处理结果")
        stats_header.setStyleSheet("font-weight: 600; color: #f59e0b; font-size: 14px;")
        stats_layout.addWidget(stats_header)
        self.stats_grid = QGridLayout()
        stats_layout.addLayout(self.stats_grid)

        # 合并下载按钮（批量处理完成后可用）
        btn_bar_stats = QHBoxLayout()
        self.btn_batch_download = QPushButton("合并下载全部")
        self.btn_batch_download.setObjectName("primaryBtn")
        self.btn_batch_download.setMaximumWidth(160)
        self.btn_batch_download.setEnabled(False)
        self.btn_batch_download.clicked.connect(self.batch_download_all)
        btn_bar_stats.addWidget(self.btn_batch_download)
        btn_bar_stats.addStretch()
        stats_layout.addLayout(btn_bar_stats)

        stats_layout.addStretch()
        result_splitter.addWidget(stats_container)

        md_container = QWidget()
        md_layout = QVBoxLayout(md_container)
        md_layout.setContentsMargins(0, 0, 0, 0)
        md_header_bar = QHBoxLayout()
        md_header = QLabel("Markdown 预览")
        md_header.setStyleSheet("font-weight: 600; color: #f59e0b; font-size: 14px;")
        md_header_bar.addWidget(md_header)
        md_header_bar.addStretch()
        self.btn_copy_md = QPushButton("复制内容")
        self.btn_copy_md.setObjectName("ghostBtn")
        self.btn_copy_md.setMaximumWidth(100)
        self.btn_copy_md.clicked.connect(self.copy_markdown)
        md_header_bar.addWidget(self.btn_copy_md)
        md_layout.addLayout(md_header_bar)
        self.markdown_view = QTextEdit()
        self.markdown_view.setReadOnly(True)
        self.markdown_view.setPlaceholderText("处理结果 Markdown 将在此显示...")
        md_layout.addWidget(self.markdown_view)
        result_splitter.addWidget(md_container)

        result_splitter.setSizes([200, 600])
        layout.addWidget(result_splitter, 1)

        self.tab_widget.addTab(tab, "上传处理")

    # ============ 文件队列管理 ============

    def select_files(self):
        if self.processing:
            return
        paths, _ = QFileDialog.getOpenFileNames(
            self,  # type: ignore[arg-type]
            "选择文件", "",
            "图片和PDF文件 (*.jpg *.jpeg *.png *.bmp *.webp *.tiff *.tif *.pdf);;图片文件 (*.jpg *.jpeg *.png *.bmp *.webp *.tiff *.tif);;PDF文件 (*.pdf);;所有文件 (*)"
        )
        if paths:
            self.add_files_to_queue(list(paths))

    def select_folder(self):
        if self.processing:
            return
        folder = QFileDialog.getExistingDirectory(self, "选择文件夹")  # type: ignore[arg-type]
        if folder:
            p = Path(folder)
            files_to_add = []
            seen = set()
            # 按扩展名预过滤 glob，减少对非图片文件的 stat 调用
            for ext in ['.jpg', '.jpeg', '.png', '.bmp', '.webp', '.tiff', '.tif', '.pdf']:
                for f in p.rglob(f'*{ext}'):
                    if f.is_file():
                        path_str = str(f)
                        if path_str not in seen:
                            seen.add(path_str)
                            files_to_add.append(path_str)
            if files_to_add:
                self.add_files_to_queue(files_to_add)
            else:
                QMessageBox.information(self, "提示", "所选文件夹中没有支持的图片文件")  # type: ignore[arg-type]

    def add_files_to_queue(self, paths: List[str]):
        ALLOWED_EXTS = {'.jpg', '.jpeg', '.png', '.bmp', '.webp', '.tiff', '.tif', '.pdf'}
        MAX_SIZE = 50 * 1024 * 1024

        added = 0
        skipped = 0
        for path in paths:
            p = Path(path)
            if not p.is_file():
                continue
            ext = p.suffix.lower()
            if ext not in ALLOWED_EXTS:
                skipped += 1
                continue
            size = p.stat().st_size
            if size > MAX_SIZE:
                skipped += 1
                continue
            if any(q["path"] == str(p) for q in self.file_queue):
                skipped += 1
                continue
            self.file_queue.append({
                "path": str(p),
                "name": p.name,
                "size": size,
                "status": "pending",
                "file_id": None,
                "task_id": None,
                "result": None,
                "error": None,
            })
            added += 1

        self.render_queue()
        if added > 0:
            self.show_toast(f"已添加 {added} 个文件" +
                            (f" (跳过 {skipped} 个)" if skipped else ""))
        elif skipped > 0:
            self.show_toast(f"跳过了 {skipped} 个不支持的/重复的文件")

    def render_queue(self):
        self.file_list_widget.clear()
        for i, item in enumerate(self.file_queue):
            status_map = {
                "pending": ("⏳", "等待中"),
                "uploading": ("⬆", "上传中..."),
                "uploading_done": ("📤", "已上传"),
                "processing": ("⚙", "识别中..."),
                "done": ("✅", "完成"),
                "error": ("❌", "失败"),
            }
            icon, status_text = status_map.get(item["status"], ("", ""))
            size_text = format_size(item["size"])
            text = f"#{i+1}  [{icon}] {item['name']}  ({size_text})  -  {status_text}"
            if item.get("error"):
                text += f"  [{item['error'][:60]}]"

            list_item = QListWidgetItem(text)
            if item["status"] == "done":
                list_item.setForeground(QColor("#10b981"))
            elif item["status"] == "error":
                list_item.setForeground(QColor("#ef4444"))
            elif item["status"] in ("processing", "uploading"):
                list_item.setForeground(QColor("#f59e0b"))
            self.file_list_widget.addItem(list_item)

    def clear_queue(self):
        if self.processing:
            self.show_toast("处理中，无法清空队列")
            return
        self.file_queue.clear()
        self.batch_results.clear()
        self.render_queue()
        self.markdown_view.clear()
        self._clear_stats()
        self.progress_bar.setValue(0)
        self.progress_text.setText("等待处理...")
        self.progress_info.setText("")
        self._reset_steps()

    # ============ 批量处理流程 ============

    def process_all_files(self):
        if self.processing:
            return
        if not self.file_queue:
            self.show_toast("请先添加文件")
            return
        pending = [q for q in self.file_queue if q["status"] == "pending"]
        if not pending:
            self.show_toast("所有文件已在处理中或已完成")
            return

        self.processing = True
        self.batch_results = []
        self.progress_bar.setValue(0)
        self._reset_steps()
        self._set_step_active("upload")

        total = len(self.file_queue)
        self._stage_upload_files(total)

    def _stage_upload_files(self, total: int):
        self.progress_text.setText("批量上传中...")
        self.progress_info.setText(f"0/{total}")
        self.progress_bar.setValue(5)

        pending = [q for q in self.file_queue if q["status"] == "pending"]
        if not pending:
            self._stage_submit_tasks(total)
            return

        self._upload_index = 0
        self._upload_pending = pending
        self._upload_total = total
        self._upload_current_file()

    def _upload_current_file(self):
        if self._upload_index >= len(self._upload_pending):
            self._set_step_complete("upload")
            self._set_step_active("analyze")
            self._stage_submit_tasks(self._upload_total)
            return

        item = self._upload_pending[self._upload_index]
        item["status"] = "uploading"
        self.render_queue()

        idx = self.file_queue.index(item)
        worker = UploadWorker(self.api_base, item["path"], idx)
        worker.finished.connect(self._on_upload_done)
        worker.error.connect(self._on_upload_error)
        self.active_workers.append(worker)
        worker.finished.connect(lambda w=worker: self._safe_remove_worker(w))
        worker.start()

    def _on_upload_done(self, data: dict):
        idx = data.pop("_index")
        item = self.file_queue[idx]
        item["status"] = "uploading_done"
        item["file_id"] = data["file_id"]
        self.render_queue()

        self._upload_index += 1
        done = sum(1 for q in self.file_queue if q["status"] == "uploading_done")
        self.progress_info.setText(f"上传: {done}/{self._upload_total}")
        self.progress_bar.setValue(int(5 + done / max(self._upload_total, 1) * 15))
        self._upload_current_file()

    def _on_upload_error(self, idx: int, error: str):
        item = self.file_queue[idx]
        item["status"] = "error"
        item["error"] = f"上传失败: {error}"
        self.render_queue()
        self._upload_index += 1
        self._upload_current_file()

    def _stage_submit_tasks(self, total: int):
        upload_done = [q for q in self.file_queue if q["status"] == "uploading_done"]
        if not upload_done:
            self.show_toast("没有文件上传成功，无法继续")
            self.processing = False
            return

        self.progress_text.setText(f"提交 {len(upload_done)} 个任务...")
        self.progress_info.setText("提交中...")
        self.progress_bar.setValue(22)

        self._submit_pending = []
        self._submit_count = len(upload_done)
        self._submit_done_count = 0
        self._submit_total = total

        for item in upload_done:
            item["status"] = "processing"
            idx = self.file_queue.index(item)
            self._submit_pending.append(idx)
            worker = SubmitWorker(self.api_base, item["file_id"], idx)
            worker.finished.connect(self._on_submit_done)
            worker.error.connect(self._on_submit_error)
            self.active_workers.append(worker)
            worker.finished.connect(lambda w=worker: self._safe_remove_worker(w))
            worker.start()

        self.render_queue()
        self._check_submit_done(total)

    def _on_submit_done(self, data: dict):
        idx = data.pop("_index")
        item = self.file_queue[idx]
        item["task_id"] = data.get("task_id")
        if not item["task_id"]:
            item["status"] = "error"
            item["error"] = "提交失败：未返回task_id"
        else:
            item["status"] = "processing"

        self._submit_done_count += 1
        if self._submit_done_count >= self._submit_count:
            self.progress_bar.setValue(25)
            self._set_step_complete("upload")
            self._set_step_active("analyze")
            self._start_polling(self._submit_total)

    def _on_submit_error(self, idx: int, error: str):
        item = self.file_queue[idx]
        item["status"] = "error"
        item["error"] = f"提交失败: {error}"
        self._submit_done_count += 1
        if self._submit_done_count >= self._submit_count:
            self._check_submit_done(self._submit_total)

    def _check_submit_done(self, total: int):
        processing = [q for q in self.file_queue if q["status"] == "processing" and q.get("task_id")]
        if not processing:
            self.show_toast("所有任务提交失败")
            self.processing = False
            self._show_batch_results()
            return
        self._set_step_complete("upload")
        self._set_step_active("analyze")
        self._start_polling(total)

    def _start_polling(self, total: int):
        self._poll_total = total
        self._poll_count = 0
        self._max_polls = 120
        self.progress_text.setText("轮询任务状态...")
        self._do_poll()

    def _do_poll(self):
        processing = [q for q in self.file_queue
                      if q["status"] == "processing" and q.get("task_id")]
        if not processing:
            self._finish_processing(self._poll_total)
            return

        self._poll_count += 1
        if self._poll_count > self._max_polls:
            for q in processing:
                q["status"] = "error"
                q["error"] = "轮询超时"
            self._finish_processing(self._poll_total)
            return

        tasks = []
        index_map = {}
        for item in processing:
            idx = self.file_queue.index(item)
            tasks.append({"task_id": item["task_id"], "index": idx})
            index_map[item["task_id"]] = idx

        worker = PollWorker(self.api_base, tasks, index_map)
        worker.finished.connect(self._on_poll_done)
        worker.error.connect(self._on_poll_error)
        self.active_workers.append(worker)
        worker.finished.connect(lambda w=worker: self._safe_remove_worker(w))
        worker.start()

    def _on_poll_done(self, results: list):
        for r in results:
            idx = r.get("index")
            if idx is None:
                continue
            if idx >= len(self.file_queue):
                continue
            item = self.file_queue[idx]
            # 轮询请求本身失败（网络错误等）：不改变状态，留待下一轮重试
            # 不能 continue 静默跳过 — 否则该任务永远 processing
            if "error" in r and r["error"]:
                # 记录错误信息但不改变状态，让下一轮轮询继续尝试
                item["_poll_error"] = r["error"]
                continue
            data = r.get("data", {})
            if not data:
                continue
            if data.get("completed"):
                if data.get("status") == "done":
                    item["status"] = "done"
                    item["result"] = data.get("result")
                    item.pop("_poll_error", None)
                else:
                    item["status"] = "error"
                    item["error"] = data.get("error", "处理失败")
                    item.pop("_poll_error", None)

        done = sum(1 for q in self.file_queue if q["status"] in ("done", "error"))
        processing = [q for q in self.file_queue if q["status"] == "processing"]

        pct = 25 + int((done / max(len(self.file_queue), 1)) * 65)
        self.progress_bar.setValue(pct)
        self.progress_info.setText(
            f"轮询中 {done}/{len(self.file_queue)} (第{self._poll_count}轮)"
        )
        self.progress_text.setText(f"处理中 {done}/{len(self.file_queue)}")
        self.render_queue()

        if processing:
            QTimer.singleShot(2000, self._do_poll)
        else:
            self._finish_processing(self._poll_total)

    def _on_poll_error(self, error: str):
        self.progress_info.setText(f"轮询错误: {error}，将继续...")
        QTimer.singleShot(2000, self._do_poll)

    def _finish_processing(self, total: int):
        self._set_step_complete("analyze")
        self._set_step_active("report")

        self.progress_bar.setValue(100)
        self.progress_text.setText("生成报告中...")
        self.progress_info.setText(f"{total}/{total}")

        self.batch_results = []
        for item in self.file_queue:
            if item["status"] == "done":
                self.batch_results.append({
                    "name": item["name"],
                    "file_id": item["file_id"],
                    "success": True,
                    "processingTime": item["result"].get("processing_time", 0) if item["result"] else 0,
                    "imagesCount": item["result"].get("images_count", 0) if item["result"] else 0,
                    "mdLength": item["result"].get("markdown_text", "").__len__() if item["result"] else 0,
                    "reportDir": item["result"].get("report_dir", "") if item["result"] else "",
                    "layoutItems": item["result"].get("layout_items", []) if item["result"] else [],
                    "layoutItemsCount": item["result"].get("layout_items_count", 0) if item["result"] else 0,
                })
            elif item["status"] == "error":
                self.batch_results.append({
                    "name": item["name"],
                    "file_id": item["file_id"],
                    "success": False,
                    "error": item.get("error", "未知错误"),
                })

        self._set_step_complete("report")
        self.processing = False
        self.progress_text.setText("处理完成")
        self.progress_info.setText("全部完成")

        succeeded = sum(1 for r in self.batch_results if r["success"])
        if succeeded > 0:
            self.show_toast(f"全部完成: {succeeded} 个文件处理成功")
        else:
            self.show_toast("处理失败: 所有文件都失败了")

        self._show_batch_results()
        self.render_queue()
        self.load_history()
        self.load_reports()

        # 有成功结果时启用合并下载按钮
        succeeded_count = sum(1 for r in self.batch_results if r["success"])
        if succeeded_count >= 1:
            self.btn_batch_download.setEnabled(True)
            self.btn_batch_download.setText(f"合并下载 ({succeeded_count} 个报告)")
        else:
            self.btn_batch_download.setEnabled(False)

        # 预览第一个成功结果（必须在清理 markdown_text 之前执行）
        for r in self.batch_results:
            if r["success"]:
                self._preview_first_result(r["file_id"])
                break

        # ---- 清理大型数据以释放内存（须在 _preview_first_result 之后） ----
        for item in self.file_queue:
            result = item.get("result")
            if isinstance(result, dict):
                # 保留元数据，移除非必要的大字段（base64图片、原始markdown）
                result.pop("images", None)          # {filename: base64} 字典
                result.pop("layout_image_base64", None)  # 版面分析图 base64
                result.pop("markdown_text", None)   # 完整 markdown 文本

    def _preview_first_result(self, file_id: str):
        for item in self.file_queue:
            if item["file_id"] == file_id and item["result"]:
                md_text = item["result"].get("markdown_text", "")
                if md_text:
                    report_dir = item["result"].get("report_dir", "")
                    self.markdown_view.setHtml(self._render_markdown_html(md_text, report_dir=report_dir))
                break

    def _show_batch_results(self):
        total = len(self.batch_results)
        succeeded = sum(1 for r in self.batch_results if r["success"])
        failed = total - succeeded
        total_time = sum(r.get("processingTime", 0) for r in self.batch_results if r["success"])

        for i in reversed(range(self.stats_grid.count())):
            widget = self.stats_grid.itemAt(i)
            if widget:
                w = widget.widget()
                if w is not None:
                    w.deleteLater()

        stats_data = [
            (str(total), "文件总数"),
            (str(succeeded), "成功"),
            (str(failed), "失败"),
            (f"{total_time:.1f}s", "总耗时"),
        ]
        for col, (val, label) in enumerate(stats_data):
            val_lbl = QLabel(val)
            val_lbl.setStyleSheet("font-size: 18px; font-weight: 700; color: #f59e0b;")
            val_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl_lbl = QLabel(label)
            lbl_lbl.setStyleSheet("font-size: 11px; color: #8b95a8;")
            lbl_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.stats_grid.addWidget(val_lbl, 0, col)
            self.stats_grid.addWidget(lbl_lbl, 1, col)

    def _clear_stats(self):
        for i in reversed(range(self.stats_grid.count())):
            widget = self.stats_grid.itemAt(i)
            if widget:
                w = widget.widget()
                if w is not None:
                    w.deleteLater()

    def copy_markdown(self):
        text = self.markdown_view.toPlainText()
        if text:
            cb = QApplication.clipboard()
            if cb is not None:
                cb.setText(text)
            self.show_toast("已复制到剪贴板")

    def batch_download_all(self):
        """将所有成功处理的报告合并为一个 ZIP 下载"""
        report_ids = [r["reportDir"] for r in self.batch_results
                     if r.get("success") and r.get("reportDir")]
        # 从完整路径提取目录名作为报告 ID
        from pathlib import PurePath
        report_ids = [PurePath(p).name for p in report_ids]

        if not report_ids:
            self.show_toast("没有可下载的报告")
            return

        save_path, _ = QFileDialog.getSaveFileName(
            self,  # type: ignore[arg-type]
            "保存合并报告", "claw_batch_reports.zip",
            "ZIP 文件 (*.zip)"
        )
        if not save_path:
            return

        worker = ApiTask(
            self.api_base, "POST", "/api/batch/download",
            json_data={"report_ids": report_ids},
            raw_response=True,
        )
        def _on_done(data: bytes):
            try:
                with open(save_path, "wb") as f:
                    f.write(data)
                size_mb = len(data) / (1024 * 1024)
                self.show_toast(f"已保存 {len(report_ids)} 个报告到: {save_path} ({size_mb:.1f}MB)")
            except Exception as ex:
                self.show_toast(f"保存失败: {ex}")
        worker.finished.connect(_on_done)
        worker.error.connect(lambda e: self.show_toast(f"合并下载失败: {e}"))
        worker.start()

"""
UI Mixin 模块 - 提供所有标签页的创建和处理逻辑
"""
from apps.desktop.ui.base_mixin import AppBaseMixin
from apps.desktop.ui.upload_mixin import UploadTabMixin
from apps.desktop.ui.history_mixin import HistoryTabMixin
from apps.desktop.ui.reports_mixin import ReportsTabMixin
from apps.desktop.ui.config_mixin import ConfigTabMixin

__all__ = [
    "AppBaseMixin",
    "UploadTabMixin",
    "HistoryTabMixin",
    "ReportsTabMixin",
    "ConfigTabMixin",
]

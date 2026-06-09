"""
UI Mixin 模块 - 提供所有标签页的创建和处理逻辑
"""
from standalone.ui.base_mixin import AppBaseMixin
from standalone.ui.upload_mixin import UploadTabMixin
from standalone.ui.history_mixin import HistoryTabMixin
from standalone.ui.reports_mixin import ReportsTabMixin
from standalone.ui.config_mixin import ConfigTabMixin

__all__ = [
    "AppBaseMixin",
    "UploadTabMixin",
    "HistoryTabMixin",
    "ReportsTabMixin",
    "ConfigTabMixin",
]

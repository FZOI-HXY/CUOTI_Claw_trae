"""
错题管理系统 - 全局样式表（暗色主题）
"""
DARK_STYLE = """
QMainWindow {
    background-color: #0a0e17;
}
QWidget {
    background-color: #0a0e17;
    color: #e8ecf1;
    font-family: 'Segoe UI', 'Microsoft YaHei', sans-serif;
    font-size: 13px;
}
QTabWidget::pane {
    border: 1px solid rgba(255,255,255,0.06);
    background-color: #111827;
    border-radius: 8px;
}
QTabWidget::tab-bar { left: 8px; }
QTabBar::tab {
    background-color: transparent;
    color: #8b95a8;
    padding: 10px 20px;
    border: none;
    border-bottom: 2px solid transparent;
    font-weight: 500;
}
QTabBar::tab:selected {
    color: #f59e0b;
    border-bottom: 2px solid #f59e0b;
}
QTabBar::tab:hover { color: #e8ecf1; }
QPushButton {
    background-color: #1a2235;
    color: #e8ecf1;
    border: 1px solid rgba(255,255,255,0.1);
    border-radius: 6px;
    padding: 8px 18px;
    font-weight: 500;
}
QPushButton:hover {
    background-color: #1f2a40;
    border-color: #f59e0b;
}
QPushButton:pressed { background-color: #162032; }
QPushButton#primaryBtn {
    background-color: #f59e0b;
    color: #0a0e17;
    border: none;
}
QPushButton#primaryBtn:hover { background-color: #fbbf24; }
QPushButton#dangerBtn {
    background-color: #ef4444;
    color: #ffffff;
    border: none;
}
QPushButton#dangerBtn:hover { background-color: #dc2626; }
QPushButton#ghostBtn {
    background-color: transparent;
    border: 1px solid rgba(255,255,255,0.1);
}
QPushButton#ghostBtn:hover {
    background-color: rgba(255,255,255,0.05);
    border-color: rgba(255,255,255,0.2);
}
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {
    background-color: #1a2235;
    color: #e8ecf1;
    border: 1px solid rgba(255,255,255,0.1);
    border-radius: 6px;
    padding: 8px 12px;
}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {
    border-color: #f59e0b;
}
QComboBox::drop-down { border: none; }
QComboBox QAbstractItemView {
    background-color: #1a2235;
    color: #e8ecf1;
    selection-background-color: rgba(245,158,11,0.2);
}
QProgressBar {
    background-color: #1a2235;
    border: none;
    border-radius: 4px;
    height: 8px;
    text-align: center;
}
QProgressBar::chunk {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #f59e0b, stop:1 #fbbf24);
    border-radius: 4px;
}
QTableWidget {
    background-color: #111827;
    border: 1px solid rgba(255,255,255,0.06);
    border-radius: 8px;
    gridline-color: rgba(255,255,255,0.04);
}
QTableWidget::item {
    padding: 8px;
    border-bottom: 1px solid rgba(255,255,255,0.04);
}
QTableWidget::item:selected {
    background-color: rgba(245,158,11,0.15);
}
QHeaderView::section {
    background-color: #1a2235;
    color: #8b95a8;
    padding: 10px 12px;
    border: none;
    border-bottom: 1px solid rgba(255,255,255,0.06);
    font-weight: 600;
    font-size: 11px;
    text-transform: uppercase;
}
QTextEdit {
    background-color: #111827;
    color: #e8ecf1;
    border: 1px solid rgba(255,255,255,0.06);
    border-radius: 8px;
    padding: 12px;
    font-family: 'Consolas', 'Courier New', monospace;
    font-size: 13px;
}
QScrollBar:vertical {
    background: transparent;
    width: 8px;
}
QScrollBar::handle:vertical {
    background: rgba(255,255,255,0.1);
    border-radius: 4px;
    min-height: 30px;
}
QScrollBar::handle:vertical:hover { background: rgba(255,255,255,0.2); }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar:horizontal {
    background: transparent;
    height: 8px;
}
QScrollBar::handle:horizontal {
    background: rgba(255,255,255,0.1);
    border-radius: 4px;
    min-width: 30px;
}
QScrollBar::handle:horizontal:hover { background: rgba(255,255,255,0.2); }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }
QGroupBox {
    border: 1px solid rgba(255,255,255,0.08);
    border-radius: 10px;
    margin-top: 16px;
    padding: 20px 16px 16px 16px;
    font-weight: 600;
    color: #e8ecf1;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 16px;
    padding: 0 8px;
}
QStatusBar {
    background-color: #0d1321;
    color: #8b95a8;
    border-top: 1px solid rgba(255,255,255,0.06);
}
QMenuBar {
    background-color: #0d1321;
    color: #e8ecf1;
    border-bottom: 1px solid rgba(255,255,255,0.06);
}
QMenuBar::item:selected { background-color: #1a2235; }
QMenu {
    background-color: #1a2235;
    color: #e8ecf1;
    border: 1px solid rgba(255,255,255,0.08);
}
QMenu::item:selected { background-color: rgba(245,158,11,0.2); }
QSplitter::handle {
    background-color: rgba(255,255,255,0.06);
    width: 1px;
}
QLabel#sectionTitle {
    font-size: 16px;
    font-weight: 700;
    color: #f59e0b;
    padding: 4px 0;
}
QLabel#statusLabel {
    color: #8b95a8;
    font-size: 11px;
}
QListWidget {
    background-color: #111827;
    border: 1px solid rgba(255,255,255,0.06);
    border-radius: 8px;
    outline: none;
}
QListWidget::item {
    padding: 10px 14px;
    border-bottom: 1px solid rgba(255,255,255,0.04);
}
QListWidget::item:selected {
    background-color: rgba(245,158,11,0.15);
}
QListWidget::item:hover {
    background-color: rgba(255,255,255,0.03);
}
QDialog {
    background-color: #111827;
}
"""

# Claw 错题管理系统 - 独立桌面应用

## 功能概述

| 功能 | 说明 |
|------|------|
| 文件队列管理 | 拖拽/选择文件/文件夹，图片预处理 |
| 批量 OCR 处理 | 上传→提交→轮询→结果 四阶段流水线 |
| 报告管理 | Markdown 预览、ZIP 下载、删除 |
| 处理历史 | 记录查询，行内查看/下载 |
| 系统配置 | API 地址、模型、日志级别管理 |

## 快速启动

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 直接启动（内嵌后端，无需额外启动服务）
python main.py
# 或双击 run.bat
```

## 开箱即用说明

API Token 已硬编码在 `backend/config.py` 中，程序启动后可直接使用 OCR 识别功能，无需手动配置 API 密钥。

如需更换 Token，请编辑 `backend/config.py` 中的 `paddleocr_api_key` 字段。

## 技术栈

- **PyQt6**：桌面 UI 框架
- **httpx**：HTTP 异步客户端
- **FastAPI + uvicorn**：内嵌后端服务
- **PaddleOCR API**：百度 AI Studio 文档结构化分析

## 注意事项

1. 内嵌后端服务监听 `127.0.0.1:8500`，仅本机可访问
2. 确保端口 8500 未被其他程序占用
3. 首次启动会自动在 `%APPDATA%/Claw/` 创建配置目录

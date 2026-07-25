---
title: DocFlow AI文档识别
emoji: 📄
colorFrom: blue
colorTo: cyan
sdk: docker
pinned: false
app_port: 7860
short_description: AI智能文档识别与管理系统 - 拍照即归档
---

# DocFlow — AI智能文档识别与管理系统

基于 PaddleOCR 的智能文档识别与管理系统。上传文档照片，AI 自动识别文字、公式、表格、图表，生成结构化 Markdown 文档。

**赛道：** TRAE AI创造力大赛 · 学习工作赛道

## 功能特性

- 🤖 **AI多模态识别** — 文字、数学公式、表格、图表、版面分析一次搞定
- 📄 **结构化输出** — 生成可编辑的 Markdown 文档，保留原始排版
- ⚡ **批量处理** — 支持多文件同时上传，异步处理
- 📁 **历史管理** — SQLite 持久化，支持检索和导出
- 🖥️ **Web端访问** — 浏览器直接使用，无需安装

## 使用方法

1. 点击页面上方的链接打开应用
2. 上传文档图片（支持 JPG/PNG/BMP/WebP，最大 50MB）
3. 选择 OCR 模型（默认 PaddleOCR-VL-1.6）
4. 等待 AI 识别，生成结构化 Markdown
5. 下载或在线查看识别结果

## 技术栈

- **后端：** FastAPI + Python 3.13
- **AI引擎：** 百度 PaddleOCR 多模态 API
- **部署：** Docker + Hugging Face Spaces
- **前端：** HTML5 + CSS3 + JavaScript（原生）

## GitHub

[github.com/FZOI-HXY/CUOTI_Claw_trae](https://github.com/FZOI-HXY/CUOTI_Claw_trae)

# Claw - 错题管理系统

基于 PaddleOCR 的智能错题识别与管理系统，采用前后端分离架构。

> 参考文档: [百度AI Studio PaddleOCR 异步API文档](https://ai.baidu.com/ai-doc/AISTUDIO/fml7mozw5)

## 系统架构

```
Claw/
├── backend/                 # 后端服务 (FastAPI)
│   ├── main.py             # FastAPI 主服务
│   ├── config.py           # 配置管理
│   ├── logger.py           # 日志系统
│   ├── paddle_service.py   # PaddleOCR API 服务
│   ├── markdown_generator.py # Markdown报告生成
│   ├── .env                # 环境配置
│   └── requirements.txt    # Python依赖
├── frontend/               # Web前端
│   ├── index.html          # 主页面
│   ├── styles.css          # 样式表
│   └── app.js              # 前端逻辑
├── desktop/                # PyQt6 桌面客户端
│   ├── main.py             # 桌面管理控制台
│   └── requirements.txt    # Python依赖
└── README.md
```

## 快速开始

### 1. 环境要求

- Python 3.10+
- pip

### 2. 安装依赖

**后端服务：**
```bash
cd backend
pip install -r requirements.txt
```

**桌面客户端（可选）：**
```bash
cd desktop
pip install -r requirements.txt
```

### 3. 配置 API 密钥

编辑 `backend/.env` 文件：

```env
PADDLEOCR_API_URL=https://paddleocr.aistudio-app.com/api/v2/ocr/jobs
PADDLEOCR_API_KEY=your_token_here
PADDLEOCR_MODEL=PP-StructureV3
```

> TOKEN 从 [百度AI Studio PaddleOCR](https://aistudio.baidu.com/paddleocr/task) 获取

### 4. 启动后端服务

```bash
cd backend
python main.py
```

服务将在 `http://localhost:8500` 启动。

### 5. 访问前端

浏览器打开 `http://localhost:8500/app` 访问 Web 管理界面。

### 6. 启动桌面客户端（可选）

```bash
cd desktop
python main.py
```

## 功能说明

### 支持的 OCR 模型

| 模型 | 说明 | 适用场景 |
|------|------|----------|
| PaddleOCR-VL-1.5 | 文档结构化分析（推荐） | 复杂文档解析，保留版式 |
| PaddleOCR-VL | 文档结构化分析 | 复杂文档解析 |
| PP-StructureV3 | 文档结构化分析 | 版面分析+OCR+表格+公式 |
| PP-OCRv5 | 文字识别 | 简单文字提取 |

### 处理流程

1. **上传文件** - 支持 JPG/PNG/BMP/WebP/TIFF 格式，最大50MB
2. **异步提交** - 调用 PaddleOCR 异步 API 提交识别任务
3. **轮询结果** - 每5秒轮询任务状态，直到完成
4. **结果提取** - 从 JSON/JSONL 结果中提取 Markdown 文本和图片
5. **报告生成** - 生成结构化 Markdown 文档并保存

### 提交方式

- **本地文件上传**: 通过 multipart/form-data 上传本地文件
- **文件URL提交**: 通过 `POST /api/submit-url` 提交文件链接（支持 ≤200MB）

### API 接口

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/status` | 系统状态 |
| GET | `/api/config` | 获取配置 |
| POST | `/api/config` | 更新配置 |
| POST | `/api/upload` | 上传图片 |
| POST | `/api/upload/batch` | 批量上传 |
| POST | `/api/submit/{file_id}` | 提交异步任务 |
| POST | `/api/submit-url` | 通过URL提交任务 |
| POST | `/api/poll/{task_id}` | 轮询任务结果 |
| POST | `/api/process/{file_id}` | 同步处理（提交+轮询） |
| POST | `/api/upload-and-process` | 上传并处理 |
| GET | `/api/batch/{batch_id}` | 批量查询结果 |
| GET | `/api/history` | 处理历史 |
| GET | `/api/reports` | 报告列表 |
| GET | `/api/report/{id}` | 获取报告 |
| GET | `/api/report/{id}/image/{name}` | 获取报告图片 |
| DELETE | `/api/report/{id}` | 删除报告 |
| GET | `/api/health` | 健康检查 |

## 配置说明

### 环境变量

| 变量 | 说明 | 默认值 |
|------|------|--------|
| PADDLEOCR_API_URL | PaddleOCR API地址 | https://paddleocr.aistudio-app.com/api/v2/ocr/jobs |
| PADDLEOCR_API_KEY | TOKEN (Bearer认证) | - |
| PADDLEOCR_MODEL | 模型版本 | PP-StructureV3 |
| HOST | 监听地址 | 0.0.0.0 |
| PORT | 监听端口 | 8500 |
| DEBUG | 调试模式 | true |
| UPLOAD_DIR | 上传目录 | ./uploads |
| OUTPUT_DIR | 输出目录 | ./output |
| LOG_DIR | 日志目录 | ./logs |
| MAX_UPLOAD_SIZE_MB | 最大上传大小 | 50 |
| LOG_LEVEL | 日志级别 | INFO |

## 目录结构

- `uploads/` - 上传的原始图片
- `output/` - 生成的报告（按时间戳分目录）
- `logs/` - 系统日志文件

每个报告目录包含：
- `report.md` - 结构化Markdown报告
- `original.png` - 原始图片副本
- `layout_analysis.png` - 版面分析图（如有）
- `api_response.json` - API原始返回

## 技术栈

- **后端**: FastAPI + Python
- **前端**: HTML5 + CSS3 + JavaScript (原生)
- **桌面**: PyQt6
- **OCR引擎**: 百度AI Studio PaddleOCR API (异步模式)
- **HTTP客户端**: httpx

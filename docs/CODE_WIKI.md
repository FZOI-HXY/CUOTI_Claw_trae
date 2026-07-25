# DocFlow — Code Wiki

> 基于 PaddleOCR 的智能文档识别与管理系统，采用前后端分离架构，支持 Web 和桌面双端部署。

---

## 目录

1. [项目概述](#1-项目概述)
2. [系统架构](#2-系统架构)
3. [目录结构](#3-目录结构)
4. [技术栈与依赖](#4-技术栈与依赖)
5. [核心模块详解](#5-核心模块详解)
6. [关键类与函数](#6-关键类与函数)
7. [API 接口文档](#7-api-接口文档)
8. [数据模型](#8-数据模型)
9. [安全机制](#9-安全机制)
10. [运行与部署](#10-运行与部署)
11. [测试](#11-测试)
12. [配置说明](#12-配置说明)

---

## 1. 项目概述

### 1.1 项目简介

DocFlow 是一个基于百度 AI Studio PaddleOCR API 的智能文档识别与管理系统。它能够自动识别图片/PDF中的文档内容，生成结构化的 Markdown 报告，并支持历史记录管理和批量处理。

### 1.2 主要功能

- **文件上传**: 支持 JPG/PNG/BMP/WebP/TIFF/PDF 格式，单文件最大 50MB，支持批量上传
- **异步 OCR 识别**: 调用 PaddleOCR 异步 API，支持多种模型
- **多模型支持**: PaddleOCR-VL-1.6、PaddleOCR-VL-1.5、PP-StructureV3、PP-OCRv6/v5
- **报告生成**: 自动生成结构化 Markdown 报告，包含版面分析
- **批量处理**: 支持批量上传、批量处理、批量下载
- **历史记录**: SQLite 持久化存储处理历史
- **双端部署**: Web 版本 + PyQt6 桌面客户端（内嵌后端）

### 1.3 处理流程

```
上传文件 → 提交异步任务 → 轮询任务状态 → 下载结果 → 解析JSON/Markdown → 保存报告
```

---

## 2. 系统架构

### 2.1 整体架构图

```
┌─────────────────────────────────────────────────────────────────┐
│                         用户界面层                                │
├─────────────────────────────────────────────────────────────────┤
│  Web 前端 (HTML/CSS/JS)          │  桌面客户端 (PyQt6)           │
│  - index.html                    │  - main.py (StandaloneApp)    │
│  - app.js                        │  - ui/*_mixin.py (Mixin模式)  │
│  - styles.css                    │  - workers/api_task.py        │
└────────────────────┬────────────────────────────┬────────────────┘
                     │                            │
                     │    HTTP API (RESTful)      │
                     │    X-Claw-Token 认证       │
                     ▼                            ▼
┌─────────────────────────────────────────────────────────────────┐
│                      FastAPI 后端服务                             │
├─────────────────────────────────────────────────────────────────┤
│  main.py (API路由 + 中间件)                                      │
│  ├─ 安全中间件 (CORS, TrustedHost, Security Headers, Auth)       │
│  ├─ 速率限制中间件 (内存存储, 60req/60s)                         │
│  └─ API 路由端点                                                 │
├─────────────────────────────────────────────────────────────────┤
│  服务层 (services/)                                              │
│  ├─ PaddleOCRService     - OCR API 封装 (httpx)                 │
│  ├─ TaskService          - 任务状态 + 历史记录 (SQLite)          │
│  ├─ ConfigService        - .env 配置持久化                       │
│  └─ PaddleParser         - 结果解析 (JSON/JSONL)                 │
├─────────────────────────────────────────────────────────────────┤
│  生成器层                                                         │
│  └─ MarkdownGenerator    - 报告构建与文件保存                     │
├─────────────────────────────────────────────────────────────────┤
│  基础设施                                                         │
│  ├─ config.py            - Settings 配置管理 (pydantic-settings) │
│  └─ logger.py            - 日志系统 (RotatingFileHandler)        │
└─────────────────────────────────────────────────────────────────┘
                     │
                     │  HTTP/HTTPS
                     ▼
┌─────────────────────────────────────────────────────────────────┐
│              百度 AI Studio PaddleOCR API                        │
│  POST /api/v2/ocr/jobs          - 提交任务                       │
│  GET  /api/v2/ocr/jobs/{jobId}  - 轮询状态                       │
│  GET  /api/v2/ocr/jobs/batch/{batchId} - 批量查询                 │
└─────────────────────────────────────────────────────────────────┘
```

### 2.2 桌面端架构

桌面端采用 Mixin 模式组合功能，内嵌 FastAPI 后端：

```
StandaloneApp (QMainWindow)
├── AppBaseMixin        - 基础功能（菜单、状态栏、拖拽）
├── UploadTabMixin      - 上传与处理
├── HistoryTabMixin     - 历史记录
├── ReportsTabMixin     - 报告管理
├── ConfigTabMixin      - 系统配置
│
└── backend_server.py   - 内嵌 uvicorn 服务（后台线程）
    └── apps.web.api.main  - 复用后端代码
```

---

## 3. 目录结构

```
Claw/
├── apps/
│   ├── web/                          # Web 应用
│   │   ├── api/                      # FastAPI 后端服务
│   │   │   ├── main.py               # API 主入口（路由+中间件）
│   │   │   ├── config.py             # 配置管理（Settings类）
│   │   │   ├── logger.py             # 日志配置
│   │   │   ├── paddle_service.py     # PaddleOCR API 封装
│   │   │   ├── markdown_generator.py # Markdown 报告生成器
│   │   │   ├── services/             # 业务服务层
│   │   │   │   ├── task_service.py   # 任务与历史服务
│   │   │   │   ├── config_service.py # 配置持久化服务
│   │   │   │   └── paddle_parser.py  # OCR结果解析器
│   │   │   ├── models/               # 数据模型
│   │   │   │   └── schemas.py        # Pydantic 请求/响应模型
│   │   │   ├── uploads/              # 上传文件目录（运行时）
│   │   │   ├── output/               # 输出报告目录（运行时）
│   │   │   ├── requirements.txt      # Python 依赖
│   │   │   └── .env                  # 环境配置（不提交Git）
│   │   └── frontend/                 # Web 前端（原生JS）
│   │       ├── index.html            # 主页面
│   │       ├── styles.css            # 样式表（暗色主题）
│   │       └── app.js                # 前端逻辑
│   │
│   └── desktop/                      # PyQt6 桌面客户端
│       ├── main.py                   # 桌面端入口（StandaloneApp）
│       ├── backend_server.py         # 内嵌后端服务管理
│       ├── style.py                  # 暗色主题样式表
│       ├── utils.py                  # 工具函数
│       ├── paddle_service_standalone.py # 标准库版Paddle服务（降级用）
│       ├── build.py                  # PyInstaller 打包脚本
│       ├── build.bat                 # Windows 一键构建
│       ├── run.bat                   # 开发模式启动
│       ├── generate_icon.py          # 图标生成
│       ├── version_info.txt          # Windows 版本信息
│       ├── requirements.txt          # 桌面端依赖
│       ├── ui/                       # UI Mixin 模块
│       │   ├── __init__.py
│       │   ├── base_mixin.py         # 基础功能Mixin
│       │   ├── upload_mixin.py       # 上传处理Mixin
│       │   ├── history_mixin.py      # 历史记录Mixin
│       │   ├── reports_mixin.py      # 报告管理Mixin
│       │   └── config_mixin.py       # 系统配置Mixin
│       └── workers/                  # 异步工作线程
│           ├── __init__.py
│           └── api_task.py           # API请求工作线程
│
├── data/                             # 运行时数据目录（全局）
│   ├── uploads/                      # 上传文件
│   ├── output/                       # 输出报告
│   └── logs/                         # 日志文件
│
├── tests/                            # 测试套件
│   ├── conftest.py                   # pytest 配置
│   ├── run_tests.py                  # 测试运行器
│   ├── test_api.py                   # API 端点测试
│   ├── test_config.py                # 配置测试
│   ├── test_config_service.py        # 配置服务测试
│   ├── test_logger.py                # 日志测试
│   ├── test_markdown_generator.py    # Markdown生成测试
│   ├── test_paddle_parser.py         # OCR解析测试
│   ├── test_paddle_service.py        # Paddle服务测试
│   ├── test_security.py              # 安全测试（核心）
│   ├── test_task_service.py          # 任务服务测试
│   └── test_ui_guidelines.py         # UI规范测试
│
├── docs/                             # 文档
│   ├── DEPLOY.md                     # 部署文档
│   ├── USAGE.md                      # 使用文档
│   └── CODE_WIKI.md                  # 本文档
│
├── claw-qa-report/                   # QA报告模板
├── output/                           # 旧版输出目录（兼容）
├── .gitignore                        # Git忽略规则
├── README.md                         # 项目说明
├── pyrightconfig.json                # Pyright类型检查配置
└── pytest.ini                        # pytest配置
```

---

## 4. 技术栈与依赖

### 4.1 后端技术栈

| 组件 | 版本 | 用途 |
|------|------|------|
| Python | 3.10+ | 运行时 |
| FastAPI | 0.111.0 | Web框架 |
| Uvicorn | 0.30.1 | ASGI服务器 |
| Pydantic | 2.7.3 | 数据验证 |
| pydantic-settings | 2.3.3 | 配置管理 |
| python-multipart | 0.0.18 | 文件上传解析 |
| httpx | 0.27.0 | 异步HTTP客户端 |
| aiofiles | 23.2.1 | 异步文件操作 |
| python-dotenv | 1.0.1 | .env文件加载 |

### 4.2 桌面端技术栈

| 组件 | 版本 | 用途 |
|------|------|------|
| PyQt6 | >=6.5.0 | GUI框架 |
| Pillow | >=9.0.0 | 图像处理 |
| PyInstaller | >=6.0.0 | 打包为exe |

### 4.3 前端技术栈

- HTML5 + CSS3（原生，暗色主题）
- JavaScript（原生ES6+，无框架依赖）
- MathJax 3.2.2（LaTeX公式渲染，CDN引入）

### 4.4 外部服务

- **百度 AI Studio PaddleOCR API**: OCR识别服务
  - API地址: `https://paddleocr.aistudio-app.com/api/v2/ocr/jobs`
  - 认证方式: Bearer Token
  - 文档: https://ai.baidu.com/ai-doc/AISTUDIO/fml7mozw5

---

## 5. 核心模块详解

### 5.1 配置模块 ([config.py](file:///c:/Users/IDC/CodeBuddy/CUOTIClaw_trae/apps/web/api/config.py))

**职责**: 统一管理系统配置，支持多环境 .env 文件加载。

**核心类**: `Settings(BaseSettings)`

**关键特性**:
- 自动发现 .env 文件（开发模式 vs 打包模式）
- 支持 `CLAW_ENV_FILE` 和 `CLAW_DATA_DIR` 环境变量覆盖
- 路径自动解析，禁止 `..` 路径遍历
- 配置值校验器（端口范围、轮询参数等）
- 动态路径获取：`get_upload_path()`, `get_output_path()`, `get_log_path()`, `get_db_path()`

**配置优先级（从低到高）**:
1. 代码默认值
2. 用户数据目录 .env（旧配置）
3. _MEIPASS/.env（打包内置配置）
4. exe 同级目录 .env（便携模式）
5. 源码目录 .env（开发模式）
6. CLAW_ENV_FILE 环境变量（最高）

### 5.2 日志模块 ([logger.py](file:///c:/Users/IDC/CodeBuddy/CUOTIClaw_trae/apps/web/api/logger.py))

**职责**: 配置结构化日志，支持控制台和文件双输出。

**核心函数**:
- `setup_logger(name)`: 创建命名日志记录器
- `update_log_level(level)`: 动态更新所有日志级别

**日志策略**:
- RotatingFileHandler: 10MB × 5 轮转
- 双日志文件: `app.log`（全部）、`error.log`（仅ERROR+）
- 控制台输出: 开发模式DEBUG，生产模式INFO

### 5.3 PaddleOCR服务模块 ([paddle_service.py](file:///c:/Users/IDC/CodeBuddy/CUOTIClaw_trae/apps/web/api/paddle_service.py))

**职责**: 封装百度 PaddleOCR 异步 API 的完整调用流程。

**核心类**: `PaddleOCRService`

**模型分组**:
```python
VL_MODELS = {"PaddleOCR-VL-1.6", "PaddleOCR-VL-1.5", "PaddleOCR-VL"}
STRUCTURE_MODELS = {"PP-StructureV3"}
OCR_MODELS = {"PP-OCRv6", "PP-OCRv5", "PP-OCRv4"}
```

**关键方法**:
| 方法 | 功能 |
|------|------|
| `submit_task()` | 提交异步识别任务（支持文件上传或URL） |
| `poll_once()` | 单次轮询任务状态（供前端驱动） |
| `poll_result()` | 内循环轮询直到完成（同步模式） |
| `submit_and_poll()` | 提交+轮询一站式处理 |
| `batch_get_results()` | 批量查询同batchId的任务结果 |
| `extract_result()` | 委托给 paddle_parser 解析结果 |

**安全措施**:
- 结果URL SSRF校验 (`_validate_result_url()`)
- 内网IP检测 (`_is_internal_ip()`)
- 分层超时配置（connect/read/write/pool分离）

### 5.4 OCR结果解析器 ([paddle_parser.py](file:///c:/Users/IDC/CodeBuddy/CUOTIClaw_trae/apps/web/api/services/paddle_parser.py))

**职责**: 从 PaddleOCR 返回的 JSON/JSONL 结果中提取结构化数据。

**核心函数**: `extract_ocr_result(poll_result)`

**支持的结果格式**:
- `layoutParsingResults[].markdown.text/images` (VL/Structure 模型)
- `layoutParsingResults[].outputImages` (输出图片)
- `ocrResults[].ocrImage` (OCR模型)
- `layoutParsingResults[].layoutType/region` (版面分析)
- `prunedResult.parsing_res_list` (新版API版面区域)

**解析能力**:
- 标准 JSON 和 JSONL（每行一个JSON）格式
- 多页结果合并
- 图片URL提取（markdown.images + outputImages）
- 版面区域类型与坐标提取

### 5.5 Markdown生成器 ([markdown_generator.py](file:///c:/Users/IDC/CodeBuddy/CUOTIClaw_trae/apps/web/api/markdown_generator.py))

**职责**: 构建结构化 Markdown 报告并保存到磁盘。

**核心类**: `MarkdownGenerator`

**报告结构**:
```
# 文档分析报告
| 属性 | 值 |          # 元信息表格
## 版面分析详情           # 版面区域表格（如有）
## 识别结果              # PaddleOCR返回的Markdown内容
## 版面分析可视化         # layout_analysis.png（如有）
## 识别图片              # 提取出的图片列表
## API原始返回           # JSON存档
```

**关键方法**:
| 方法 | 功能 |
|------|------|
| `build_report()` | 构建完整报告Markdown文本 |
| `build_layout_report()` | 构建仅版面分析的报告 |
| `save_report()` | 异步保存报告到磁盘（含图片下载） |
| `save_layout_report_standalone()` | 保存独立版面分析报告 |
| `_replace_image_refs()` | 将base64引用替换为本地文件路径 |
| `_resolve_image_data_async()` | 异步解析图片数据（URL下载/base64解码） |

**目录结构**:
```
output/YYYYMMDD_HHMMSS_uuid/
├── report.md              # 完整报告
├── layout_report.md       # 版面分析报告
├── layout_analysis.png    # 版面可视化图
├── original.png/jpg/pdf   # 原始文件
├── api_response.json      # API原始返回
├── downloaded_result.json # 下载的结果JSON
└── imgs/                  # 提取的图片
    ├── img_0.png
    ├── img_1.png
    └── ...
```

### 5.6 任务服务 ([task_service.py](file:///c:/Users/IDC/CodeBuddy/CUOTIClaw_trae/apps/web/api/services/task_service.py))

**职责**: 管理异步任务状态和处理历史记录。

**核心类**: `TaskService`（全局单例 `task_service`）

**数据存储**:
- **内存**: `OrderedDict` 实现 LRU 缓存（最多200任务）
- **SQLite**: WAL模式，持久化历史记录

**关键特性**:
- 线程安全：所有操作在 `Lock` 保护下
- LRU淘汰：超出200任务自动淘汰最旧的
- image_data延迟清理：任务完成后5分钟自动清理大字段
- 卡死检测：running状态连续无进度判定为stuck
- 历史记录分页：支持offset/limit参数

**关键方法**:
| 方法 | 功能 |
|------|------|
| `get_task()/set_task()` | 获取/设置任务状态（返回副本防止外部修改） |
| `add_history()` | 添加历史记录（内存+SQLite） |
| `get_history()` | 获取分页历史 |
| `delete_history()/batch_delete_history()` | 删除历史 |
| `schedule_image_data_cleanup()` | 延迟清理image_data |

**SQLite表结构**:
```sql
CREATE TABLE history (
    id TEXT PRIMARY KEY,           -- UUID[:16]
    file_id TEXT,                  -- 文件ID
    filename TEXT,                 -- 文件名
    timestamp TEXT,                -- ISO时间戳
    success INTEGER,               -- 0/1
    processing_time REAL,          -- 处理耗时(秒)
    images_count INTEGER,          -- 图片数量
    markdown_length INTEGER,       -- Markdown字符数
    report_dir TEXT,               -- 报告目录名
    model TEXT,                    -- 使用的模型
    total_pages INTEGER            -- 总页数
);
```

### 5.7 配置持久化服务 ([config_service.py](file:///c:/Users/IDC/CodeBuddy/CUOTIClaw_trae/apps/web/api/services/config_service.py))

**职责**: 将配置更新写入 .env 文件。

**核心函数**: `save_env_file(config_data, env_path)`

**字段映射**: Python小写名 → .env大写名（如 `paddleocr_api_url` → `PADDLEOCR_API_URL`）

### 5.8 后端服务管理 ([backend_server.py](file:///c:/Users/IDC/CodeBuddy/CUOTIClaw_trae/apps/desktop/backend_server.py))

**职责**: 为桌面应用管理内嵌的 uvicorn 后端服务生命周期。

**核心函数**:
| 函数 | 功能 |
|------|------|
| `start_server(host, port)` | 在后台线程启动uvicorn，等待health端点就绪 |
| `stop_server()` | 优雅停止服务器 |
| `is_running()` | 检查服务器状态 |

**启动流程**:
1. 确定数据目录（开发:%APPDATA%/Claw，打包:exe同级）
2. 设置环境变量（CLAW_DATA_DIR, CLAW_ENV_FILE, CLAW_AUTH_TOKEN）
3. 处理SSL证书（PyInstaller打包后certifi路径）
4. 确保.env文件存在（必要时从模板或开发配置继承）
5. 导入FastAPI app，启动uvicorn线程
6. 轮询 `/api/health` 等待就绪（最长10秒）

**安全特性**:
- 自动生成随机认证token（`secrets.token_urlsafe(32)`）
- 默认绑定127.0.0.1，不暴露到外网

---

## 6. 关键类与函数

### 6.1 Settings 类 ([config.py#L104-L225](file:///c:/Users/IDC/CodeBuddy/CUOTIClaw_trae/apps/web/api/config.py#L104-L225))

```python
class Settings(BaseSettings):
    # PaddleOCR配置
    paddleocr_api_url: str = "https://paddleocr.aistudio-app.com/api/v2/ocr/jobs"
    paddleocr_api_key: str = ""
    paddleocr_model: str = "PaddleOCR-VL-1.6"
    
    # 服务器配置
    host: str = "127.0.0.1"
    port: int = 8500
    debug: bool = False
    
    # 文件存储
    upload_dir: str = "./uploads"
    output_dir: str = "./output"
    log_dir: str = "./logs"
    max_upload_size_mb: int = 50
    
    # 轮询配置
    poll_interval: int = 5
    poll_max_retries: int = 120
    
    # 速率限制
    rate_limit_requests: int = 60
    rate_limit_window: int = 60
    
    # 日志
    log_level: str = "INFO"
    
    # 本地认证
    claw_auth_token: str = ""
```

### 6.2 PaddleOCRService 类 ([paddle_service.py#L146-L749](file:///c:/Users/IDC/CodeBuddy/CUOTIClaw_trae/apps/web/api/paddle_service.py#L146-L749))

主要API方法见 [5.3节](#53-paddleocr服务模块paddle_servicepy)。

**提交任务两种模式**:
1. multipart/form-data：本地文件上传
2. application/json：fileUrl远程URL

**轮询状态**: `pending` → `running` → `done`/`failed`

### 6.3 TaskService 类 ([task_service.py#L70-L304](file:///c:/Users/IDC/CodeBuddy/CUOTIClaw_trae/apps/web/api/services/task_service.py#L70-L304))

见 [5.6节](#56-任务服务task_servicepy)。

### 6.4 MarkdownGenerator 类 ([markdown_generator.py#L39-L589](file:///c:/Users/IDC/CodeBuddy/CUOTIClaw_trae/apps/web/api/markdown_generator.py#L39-L589))

见 [5.5节](#55-markdown生成器markdown_generatorpy)。

### 6.5 StandaloneApp 类 ([main.py#L84-L181](file:///c:/Users/IDC/CodeBuddy/CUOTIClaw_trae/apps/desktop/main.py#L84-L181))

桌面端主窗口，通过Mixin组合所有功能：

```python
class StandaloneApp(
    AppBaseMixin,        # 菜单、状态栏、拖拽、服务器状态
    UploadTabMixin,      # 上传队列、批量处理
    HistoryTabMixin,     # 处理历史表格
    ReportsTabMixin,     # 报告卡片网格
    ConfigTabMixin,      # 配置表单
    QMainWindow,
):
```

### 6.6 安全工具函数 ([main.py#L183-L421](file:///c:/Users/IDC/CodeBuddy/CUOTIClaw_trae/apps/web/api/main.py#L183-L421))

| 函数 | 功能 |
|------|------|
| `_secure_filename()` | 清洗文件名，防止路径穿越 |
| `_extract_safe_extension()` | 安全提取文件扩展名 |
| `_validate_file_id()` | 校验file_id为32位hex（UUID4格式） |
| `_is_internal_ip()` | 检测内网IP/localhost（SSRF防护） |
| `_validate_file_url()` | 校验提交URL，禁止内网地址 |
| `_check_magic_bytes()` | 校验文件头Magic Bytes，防止文件类型伪装 |
| `_safe_report_dir()` | 安全获取报告目录（路径遍历防护） |
| `_safe_report_image_path()` | 安全获取报告图片路径 |

---

## 7. API 接口文档

### 7.1 接口总览

Base URL: `http://127.0.0.1:8500`

认证方式：POST/DELETE/PUT 请求需在Header中携带 `X-Claw-Token`（桌面端自动生成，Web端从`/api/init`获取）

| 方法 | 路径 | 说明 | 认证 |
|------|------|------|------|
| GET | `/` | 服务信息 | 否 |
| GET | `/api/health` | 健康检查（含数据库） | 否 |
| GET | `/api/init` | 获取认证token（仅localhost） | 否 |
| GET | `/api/status` | 系统状态 | 否 |
| GET | `/api/config` | 获取配置 | 否 |
| POST | `/api/config` | 更新配置 | 是 |
| POST | `/api/upload` | 上传单文件 | 是 |
| POST | `/api/upload/batch` | 批量上传文件 | 是 |
| POST | `/api/submit/{file_id}` | 提交异步OCR任务 | 是 |
| POST | `/api/submit-url` | 通过URL提交任务 | 是 |
| POST | `/api/poll/{task_id}` | 轮询任务结果 | 是 |
| POST | `/api/process/{file_id}` | 同步处理（提交+轮询） | 是 |
| POST | `/api/upload-and-process` | 上传并处理（一站式） | 是 |
| GET | `/api/batch/{batch_id}` | 批量查询结果 | 否 |
| GET | `/api/history` | 处理历史（分页） | 否 |
| DELETE | `/api/history/{history_id}` | 删除历史记录 | 是 |
| POST | `/api/history/batch-delete` | 批量删除历史 | 是 |
| GET | `/api/reports` | 报告列表 | 否 |
| GET | `/api/report/{report_id}` | 获取报告Markdown | 否 |
| GET | `/api/report/{report_id}/download` | 下载报告ZIP | 否 |
| GET | `/api/report/{report_id}/image/{name}` | 获取报告图片 | 否 |
| DELETE | `/api/report/{report_id}` | 删除报告 | 是 |
| POST | `/api/batch/download` | 批量下载报告ZIP | 是 |
| POST | `/api/batch/download-layout` | 批量下载版面报告 | 是 |
| POST | `/api/batch/delete` | 批量删除报告 | 是 |
| GET | `/app/*` | 静态前端文件 | 否 |

### 7.2 核心接口详解

#### POST /api/upload
上传单个图片/PDF文件。

**请求**: `multipart/form-data`，字段名 `file`

**响应**:
```json
{
  "success": true,
  "file_id": "a1b2c3d4...32位hex",
  "original_name": "math.jpg",
  "saved_name": "a1b2c3d4...png",
  "size": 102400
}
```

#### POST /api/submit/{file_id}
提交异步OCR任务。

**查询参数**:
- `page_ranges`: 页码范围（如 "2,4-6"，可选）
- `batch_id`: 批量ID（可选）

**响应**:
```json
{
  "success": true,
  "task_id": "job_xxx",
  "file_id": "a1b2c3d4...",
  "filename": "xxx.png",
  "status": "processing",
  "batch_id": null
}
```

#### POST /api/poll/{task_id}
轮询任务结果（前端循环调用）。

**处理中响应**:
```json
{
  "task_id": "job_xxx",
  "status": "processing",
  "completed": false,
  "progress": {
    "state": "running",
    "extracted_pages": 1,
    "total_pages": 3,
    "attempt": 0
  }
}
```

**完成响应**:
```json
{
  "task_id": "job_xxx",
  "status": "done",
  "completed": true,
  "result": {
    "success": true,
    "markdown_text": "# 识别结果...",
    "images": {"img_0": "https://..."},
    "images_count": 2,
    "report_id": "20240608_120000_abc123",
    "processing_time": 15.5,
    "total_pages": 1,
    "extracted_pages": 1
  }
}
```

---

## 8. 数据模型

所有API请求/响应使用Pydantic模型定义，位于 [schemas.py](file:///c:/Users/IDC/CodeBuddy/CUOTIClaw_trae/apps/web/api/models/schemas.py)。

### 8.1 配置相关模型

```python
class ConfigUpdateRequest(BaseModel):
    paddleocr_api_url: Optional[str] = None
    paddleocr_api_key: Optional[str] = None
    paddleocr_model: Optional[str] = None
    host: Optional[str] = None          # 校验：IP/localhost
    port: Optional[int] = Field(None, ge=1, le=65535)
    debug: Optional[bool] = None
    upload_dir: Optional[str] = None    # 校验：不含..
    output_dir: Optional[str] = None    # 校验：不含..
    log_dir: Optional[str] = None       # 校验：不含..
    max_upload_size_mb: Optional[int] = None
    log_level: Optional[LogLevel] = None  # DEBUG/INFO/WARNING/ERROR/CRITICAL
    poll_interval: Optional[int] = None
    poll_max_retries: Optional[int] = None
    rate_limit_requests: Optional[int] = None
    rate_limit_window: Optional[int] = None
```

### 8.2 任务相关模型

```python
class SubmitTaskRequest(BaseModel):
    fileUrl: Optional[str] = None
    filename: Optional[str] = None
    pageRanges: Optional[str] = None
    batchId: Optional[str] = None

class PollTaskResponse(BaseModel):
    task_id: str
    file_id: Optional[str]
    filename: str
    status: str  # processing/done/error/stuck
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    completed: bool
    progress: Optional[TaskProgress] = None
```

### 8.3 历史与报告模型

```python
class HistoryItem(BaseModel):
    id: str
    file_id: Optional[str]
    filename: str
    timestamp: str
    success: bool
    processing_time: float
    images_count: int
    markdown_length: int
    report_dir: Optional[str]
    model: Optional[str]
    total_pages: int

class BatchDeleteRequest(BaseModel):
    ids: List[str]

class BatchDownloadRequest(BaseModel):
    report_ids: List[str]
```

---

## 9. 安全机制

项目实现了多层安全防护，核心安全测试见 [test_security.py](file:///c:/Users/IDC/CodeBuddy/CUOTIClaw_trae/tests/test_security.py)。

### 9.1 输入验证

| 防护点 | 措施 |
|--------|------|
| 文件名清洗 | `_secure_filename()` 剥离路径、移除危险字符、限制长度 |
| file_id校验 | 32位十六进制正则校验，防止路径遍历 |
| report_id校验 | `_safe_report_dir()` 解析后验证在output_dir内 |
| Magic Bytes校验 | 校验文件头，防止文件类型伪装 |
| Pydantic验证 | 所有请求体经过Pydantic模型校验（端口范围、路径不含..等） |

### 9.2 SSRF防护

| 防护点 | 措施 |
|--------|------|
| URL提交校验 | `_validate_file_url()` 强制HTTPS，禁止内网IP |
| 结果URL校验 | `_validate_result_url()` 禁止访问内网地址 |
| 内网IP检测 | `_is_internal_ip()` 检查直连IP和DNS解析结果 |

### 9.3 认证与授权

| 机制 | 说明 |
|------|------|
| X-Claw-Token | POST/DELETE/PUT请求需携带，桌面端随机生成 |
| /api/init | 仅localhost可获取token |
| hmac.compare_digest | 常量时间比较，防止时序攻击 |
| 开发模式兼容 | token为空时不启用认证 |

### 9.4 中间件安全

| 中间件 | 功能 |
|--------|------|
| TrustedHostMiddleware | 主机名校验 |
| CORS | 仅允许127.0.0.1:8500和localhost:8500 |
| Security Headers | X-Content-Type-Options, X-Frame-Options, X-XSS-Protection, CSP |
| 速率限制 | 内存存储，默认60请求/60秒/IP，健康检查豁免 |

### 9.5 信息泄露防护

| 措施 | 说明 |
|------|------|
| 环境相关错误 | debug模式返回详细错误，生产模式返回通用消息 |
| API Key掩码 | 配置接口仅返回 `********`，不返回实际key |
| 路径隐藏 | API响应不返回服务器绝对路径，仅返回report_id/file_id |
| 文档控制 | debug模式启用/docs，生产模式禁用Swagger UI |

### 9.6 其他安全措施

- SQLite使用WAL模式+busy_timeout(5000ms)
- 日志使用RotatingFileHandler（10MB×5）
- image_data大字段延迟清理，防止内存泄漏
- LRU任务缓存限制200条
- python-multipart>=0.0.18（避免已知CVE）
- host默认127.0.0.1，不绑定0.0.0.0
- uploads/目录加入.gitignore

---

## 10. 运行与部署

### 10.1 环境要求

- Python 3.10+
- pip
- （桌面端）Windows 10+（PyQt6）

### 10.2 Web版本开发运行

```bash
# 1. 安装后端依赖
cd apps/web/api
pip install -r requirements.txt

# 2. 配置API密钥
# 编辑 apps/web/api/.env 文件：
# PADDLEOCR_API_KEY=your_token_here

# 3. 启动后端
python main.py

# 4. 访问
# 后端API: http://127.0.0.1:8500
# Web前端: http://127.0.0.1:8500/app
# API文档: http://127.0.0.1:8500/docs (debug模式)
```

### 10.3 桌面端开发运行

```bash
# 方式1：先启动后端，再启动桌面（分离模式）
cd apps/web/api && python main.py
cd apps/desktop && python main.py

# 方式2：直接运行桌面端（自动内嵌后端）
cd apps/desktop
pip install -r requirements.txt
python main.py
# 或双击 run.bat
```

### 10.4 桌面端打包（PyInstaller）

```bash
cd apps/desktop

# 一键构建（带控制台，调试用）
build.bat

# 或直接调用Python脚本
python build.py --clean          # 清理后构建
python build.py --windowed       # 无控制台窗口（发布用）
python build.py --console        # 带控制台（调试）

# 输出: dist/Claw.exe（单文件可执行程序）
```

**打包流程**（[build.py](file:///c:/Users/IDC/CodeBuddy/CUOTIClaw_trae/apps/desktop/build.py)）:
1. 检查Python版本和依赖
2. 生成应用图标（如不存在）
3. 配置PyInstaller参数（隐藏导入、数据文件、排除模块）
4. 执行打包
5. 验证输出文件

### 10.5 环境变量

| 变量 | 说明 | 默认值 |
|------|------|--------|
| PADDLEOCR_API_URL | PaddleOCR API地址 | 官方地址 |
| PADDLEOCR_API_KEY | API Token（必填） | - |
| PADDLEOCR_MODEL | OCR模型 | PaddleOCR-VL-1.6 |
| HOST | 监听地址 | 127.0.0.1 |
| PORT | 监听端口 | 8500 |
| DEBUG | 调试模式 | false |
| UPLOAD_DIR | 上传目录 | ./uploads |
| OUTPUT_DIR | 输出目录 | ./output |
| LOG_DIR | 日志目录 | ./logs |
| MAX_UPLOAD_SIZE_MB | 最大上传(MB) | 50 |
| LOG_LEVEL | 日志级别 | INFO |
| POLL_INTERVAL | 轮询间隔(秒) | 5 |
| POLL_MAX_RETRIES | 最大轮询次数 | 120 |
| RATE_LIMIT_REQUESTS | 速率限制请求数 | 60 |
| RATE_LIMIT_WINDOW | 速率限制窗口(秒) | 60 |
| CLAW_AUTH_TOKEN | 本地认证Token | （桌面端自动生成） |
| CLAW_DATA_DIR | 数据根目录 | 自动发现 |
| CLAW_ENV_FILE | .env文件路径 | 自动发现 |

---

## 11. 测试

### 11.1 测试框架

- pytest
- 测试配置: [pytest.ini](file:///c:/Users/IDC/CodeBuddy/CUOTIClaw_trae/pytest.ini)

### 11.2 测试文件

| 文件 | 覆盖范围 |
|------|----------|
| test_security.py | 安全机制（文件名清洗、history_id格式、错误环境分离、WAL模式、速率限制、HTML转义） |
| test_api.py | API端点测试 |
| test_config.py | 配置加载与校验 |
| test_config_service.py | 配置持久化 |
| test_logger.py | 日志配置 |
| test_markdown_generator.py | Markdown生成与图片处理 |
| test_paddle_parser.py | OCR结果解析 |
| test_paddle_service.py | PaddleOCR服务 |
| test_task_service.py | 任务状态与历史管理 |
| test_ui_guidelines.py | UI规范检查 |

### 11.3 运行测试

```bash
# 运行所有测试
cd 项目根目录
python -m pytest tests/ -v

# 运行单元测试（不需要外部服务）
python -m pytest tests/ -v -m unit

# 运行安全测试
python -m pytest tests/test_security.py -v

# 生成覆盖率报告
python -m pytest tests/ --cov=apps --cov-report=html
```

---

## 12. 配置说明

### 12.1 支持的OCR模型

| 模型 | 说明 | 适用场景 |
|------|------|----------|
| PaddleOCR-VL-1.6 | 多模态文档结构化分析（最新推荐） | 复杂文档解析，保留版式 |
| PaddleOCR-VL-1.5 | 多模态文档结构化分析 | 复杂文档解析，保留版式 |
| PaddleOCR-VL | 多模态文档结构化分析 | 复杂文档解析 |
| PP-StructureV3 | 文档结构化分析 | 版面分析+OCR+表格+公式 |
| PP-OCRv6 | 纯文字识别（最新） | 简单文字提取 |
| PP-OCRv5 | 纯文字识别 | 简单文字提取 |

### 12.2 数据目录策略

**开发模式**:
- .env: `apps/web/api/.env`（源码目录，直接修改生效）
- 数据: `%APPDATA%/Claw/`（Windows）或 `~/.claw/`（其他）

**打包模式（frozen）**:
- .env: exe同级目录（便携模式）
- 数据: exe同级目录
- 首次运行自动从%APPDATA%/Claw/继承配置

### 12.3 异步处理机制

PaddleOCR API为异步模式，处理流程：
1. **提交**: POST文件/URL → 获取jobId
2. **轮询**: 前端每5秒调用一次`/api/poll/{task_id}`
3. **进度**: 返回extracted_pages/total_pages显示进度
4. **卡死检测**: 连续15次（Web端）无进度判定为stuck
5. **超时**: 单次轮询硬超时90秒，防止长时间占用worker

### 12.4 性能优化

- httpx.AsyncClient连接池复用（轮询循环共享client）
- asyncio.to_thread()包装同步IO，不阻塞事件循环
- SQLite WAL模式，读写不互斥
- LRU缓存淘汰（最多200任务）
- image_data延迟清理（完成后5分钟自动释放）
- 速率限制定期内存清理

---

## 附录：关键文件引用速查

| 文件 | 绝对路径 |
|------|----------|
| API主入口 | [main.py](file:///c:/Users/IDC/CodeBuddy/CUOTIClaw_trae/apps/web/api/main.py) |
| 配置类 | [config.py](file:///c:/Users/IDC/CodeBuddy/CUOTIClaw_trae/apps/web/api/config.py) |
| PaddleOCR服务 | [paddle_service.py](file:///c:/Users/IDC/CodeBuddy/CUOTIClaw_trae/apps/web/api/paddle_service.py) |
| 结果解析器 | [paddle_parser.py](file:///c:/Users/IDC/CodeBuddy/CUOTIClaw_trae/apps/web/api/services/paddle_parser.py) |
| Markdown生成器 | [markdown_generator.py](file:///c:/Users/IDC/CodeBuddy/CUOTIClaw_trae/apps/web/api/markdown_generator.py) |
| 任务服务 | [task_service.py](file:///c:/Users/IDC/CodeBuddy/CUOTIClaw_trae/apps/web/api/services/task_service.py) |
| Pydantic模型 | [schemas.py](file:///c:/Users/IDC/CodeBuddy/CUOTIClaw_trae/apps/web/api/models/schemas.py) |
| 桌面端入口 | [main.py](file:///c:/Users/IDC/CodeBuddy/CUOTIClaw_trae/apps/desktop/main.py) |
| 内嵌后端管理 | [backend_server.py](file:///c:/Users/IDC/CodeBuddy/CUOTIClaw_trae/apps/desktop/backend_server.py) |
| 构建脚本 | [build.py](file:///c:/Users/IDC/CodeBuddy/CUOTIClaw_trae/apps/desktop/build.py) |
| 安全测试 | [test_security.py](file:///c:/Users/IDC/CodeBuddy/CUOTIClaw_trae/tests/test_security.py) |

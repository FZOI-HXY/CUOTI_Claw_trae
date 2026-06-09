# Claw 错题管理系统 - 部署指南

## 一、环境准备

### 系统要求

- 操作系统：Windows 10+ / Linux / macOS
- Python 版本：3.10 或更高
- 内存：建议 4GB 以上
- 磁盘：至少 500MB 可用空间

### Python 环境

```bash
# 创建虚拟环境（推荐）
python -m venv venv

# 激活虚拟环境
# Windows:
venv\Scripts\activate
# Linux/macOS:
source venv/bin/activate
```

## 二、后端部署

### 1. 安装依赖

```bash
cd Claw/backend
pip install -r requirements.txt
```

### 2. 配置环境变量

复制并编辑 `.env` 文件：

```bash
# PaddleOCR API 配置（必填）
# 从百度AI Studio获取: https://paddleocr.aistudio-app.com
PADDLEOCR_API_URL=https://paddleocr.aistudio-app.com/api/v2/ocr/jobs
PADDLEOCR_API_KEY=your_api_key_here        # 替换为实际API Token
PADDLEOCR_MODEL=PP-StructureV3              # 可选: PaddleOCR-VL-1.5 / PaddleOCR-VL / PP-OCRv5

# 服务器配置（可选）
HOST=0.0.0.0
PORT=8500
DEBUG=false                                # 生产环境设为false
MAX_UPLOAD_SIZE_MB=50

# 日志配置（可选）
LOG_LEVEL=INFO
```

### 3. 启动服务

```bash
# 开发模式（支持热重载）
python main.py

# 生产模式（使用uvicorn直接启动）
uvicorn main:app --host 0.0.0.0 --port 8500 --workers 4
```

### 4. 验证部署

```bash
# 健康检查
curl http://localhost:8500/api/health

# 预期响应
{"status":"healthy","timestamp":"..."}
```

## 三、前端部署

前端为纯静态文件，可通过以下方式部署：

### 方式一：FastAPI 内置静态服务（默认）

后端已自动挂载前端文件，访问 `http://localhost:8500/app` 即可。

### 方式二：Nginx 部署

```nginx
server {
    listen 80;
    server_name your-domain.com;

    # 前端静态文件
    location / {
        root /path/to/Claw/frontend;
        index index.html;
        try_files $uri $uri/ /index.html;
    }

    # API 代理
    location /api/ {
        proxy_pass http://127.0.0.1:8500;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }
}
```

### 方式三：直接使用

直接双击打开 `frontend/index.html`，需确保 API 地址配置正确。

## 四、桌面客户端部署

### 安装依赖

```bash
cd Claw/desktop
pip install -r requirements.txt
```

### 启动

```bash
python main.py
```

### 打包为可执行文件（可选）

```bash
pip install pyinstaller
pyinstaller --onefile --windowed --name "Claw" main.py
```

## 五、生产环境建议

### 1. 使用进程管理器

**Windows (NSSM):**
```bash
nssm install ClawBackend "C:\Python310\python.exe" "C:\Claw\backend\main.py"
nssm set ClawBackend AppDirectory "C:\Claw\backend"
nssm start ClawBackend
```

**Linux (systemd):**
```ini
[Unit]
Description=Claw Backend Service
After=network.target

[Service]
Type=simple
User=www-data
WorkingDirectory=/opt/claw/backend
ExecStart=/opt/claw/venv/bin/python main.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

### 2. 反向代理

使用 Nginx 或 Caddy 进行反向代理，配置 HTTPS。

### 3. 日志管理

日志文件自动轮转：
- 单文件最大 10MB
- 保留最近 5 个备份
- 错误日志独立存储

### 4. 安全建议

- 生产环境设置 `DEBUG=false`
- 配置防火墙限制端口访问
- 使用 HTTPS 保护数据传输
- 定期清理上传目录和输出目录
- API密钥妥善保管，不要提交到版本控制

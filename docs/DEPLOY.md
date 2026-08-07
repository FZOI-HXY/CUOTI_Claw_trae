# DocFlow — AI智能文档识别与管理系统 - 部署指南

> **⭐ 桌面端现状**：当前桌面客户端为 **Tauri 桌面端**（Rust + Vue，识别走多模态 LLM「智谱 glm-4.5-air」），详见 → **[DEPLOY_TAURI.md](./DEPLOY_TAURI.md)**。本文档主体为旧的 Python Web 端与 Python 桌面端部署说明，保留供参考。

---

## 零、云端部署方案速查

| 方案 | 永久免费 | 需信用卡 | 内存 | 适合场景 | 配置文件 |
|------|----------|----------|------|----------|----------|
| **Hugging Face Spaces** | ✅ | ❌ 仅需邮箱 | **2核/16GB** | **⭐ 无信用卡首选** | `Dockerfile.hf` |
| Fly.io | ✅ | ✅ | 256MB | 有信用卡 | `Dockerfile.fly` + `fly.toml` |
| Docker Compose | ✅ 自建 | 自备服务器 | 不限 | 自有VPS | `Dockerfile` + `docker-compose.yml` |

---

### 🚀 无信用卡首选：Hugging Face Spaces 部署

**配置：2 vCPU / 16GB RAM / 50GB 磁盘，永久免费，仅需邮箱注册** [$TRAE_REF](http://m.toutiao.com/group/7637034971688862260/)

#### 步骤 1：注册账号

访问 https://huggingface.co/join ，用邮箱注册（**无需信用卡，无需实名认证**）

#### 步骤 2：安装工具并登录

```bash
# 安装 huggingface_hub CLI
pip install huggingface_hub

# 登录（会提示输入 Access Token，从 https://huggingface.co/settings/tokens 获取）
huggingface-cli login
```

#### 步骤 3：一键部署

```bash
# Linux/macOS
chmod +x deploy-hf.sh
./deploy-hf.sh

# Windows (Git Bash / WSL)
bash deploy-hf.sh
```

或手动部署：
```bash
# 1. 创建 Space（在网页操作或命令行）
huggingface-cli repo create docflow-ai --type space --space_sdk docker

# 2. 准备文件并推送
mkdir hf_deploy && cd hf_deploy
cp ../Dockerfile.hf ./Dockerfile
cp -r ../apps ./
cp ../README.md ./
cp ../deploy/hf-spaces/README.md ./README.md  # 覆盖（含 Spaces 元数据）
mkdir -p data/uploads data/output data/logs
git init && git add . && git commit -m "deploy"
git remote add origin https://huggingface.co/spaces/<你的用户名>/docflow-ai
git push --force origin main
```

#### 步骤 4：配置 API Key

1. 打开 Space 设置页：`https://huggingface.co/spaces/<用户名>/docflow-ai/settings`
2. 在 **Repository secrets** 中添加：
   - `PADDLEOCR_API_KEY` = 你的百度PaddleOCR Token
3. Space 自动重启后即可使用

#### 访问地址

```
https://huggingface.co/spaces/<你的用户名>/docflow-ai
```

> ⚠️ **注意**：HF Spaces 免费版有 48 小时休眠机制（无访问时自动休眠，首次访问需冷启动约 30-60 秒）。用于参赛 Demo 展示完全够用。

---

### 有信用卡方案

- **Fly.io**（256MB永久免费，不休眠）：见 `deploy-fly.sh`
- **Oracle Cloud**（4核24GB ARM永久免费）：使用根目录 `Dockerfile` + `docker-compose.yml`
- **阿里云/腾讯云**（新用户1-3个月试用）：国内节点，需备案

---

## 一、环境准备（本地部署）

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
cd Claw/apps/web/api
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
        root /path/to/Claw/apps/web/frontend;
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

### 当前推荐：Tauri 桌面端（多模态 LLM 识别）

构建、打包、LLM 配置、数据目录与常见问题，请直接查看 → **[DEPLOY_TAURI.md](./DEPLOY_TAURI.md)**。

```bash
# 开发运行
cd tauri && cargo tauri dev

# 打包（前端构建 + 桌面应用）
cd tauri/frontend && npm run build
cd tauri && cargo tauri build
```

### 旧版：Python 桌面端（可选，PaddleOCR）

> ⚠️ 已由 Tauri 桌面端取代，识别不再走 PaddleOCR，仅保留供参考。

```bash
cd Claw/apps/desktop
pip install -r requirements.txt
python main.py

# 打包为可执行文件（可选）
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
WorkingDirectory=/opt/claw/apps/web/api
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

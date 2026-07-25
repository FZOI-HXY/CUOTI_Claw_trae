#!/bin/bash
# ======================================================
# DocFlow - Hugging Face Spaces 一键部署脚本
# ======================================================
# 使用方法：
#   chmod +x deploy-hf.sh
#   ./deploy-hf.sh
#
# 前置条件：
#   1. 注册 Hugging Face 账号（仅需邮箱，无需信用卡）
#      https://huggingface.co/join
#   2. 安装 huggingface_hub CLI：
#      pip install huggingface_hub
#   3. 登录 HF：
#      huggingface-cli login
# ======================================================

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

print_info()  { echo -e "${BLUE}[INFO]${NC} $1"; }
print_ok()    { echo -e "${GREEN}[OK]${NC} $1"; }
print_warn()  { echo -e "${YELLOW}[WARN]${NC} $1"; }
print_error() { echo -e "${RED}[ERROR]${NC} $1"; }

# 0. 前置检查
print_info "检查 huggingface_hub CLI..."
if ! command -v huggingface-cli &> /dev/null; then
    print_warn "huggingface-cli 未安装，正在安装..."
    pip install huggingface_hub
fi
print_ok "huggingface_hub 已就绪"

# 检查登录状态
print_info "检查 HF 登录状态..."
if ! huggingface-cli whoami &> /dev/null; then
    print_warn "未登录，请先登录："
    echo "  huggingface-cli login"
    echo ""
    echo "注册地址：https://huggingface.co/join （仅需邮箱，无需信用卡）"
    exit 1
fi
HF_USER=$(huggingface-cli whoami)
print_ok "已登录为: $HF_USER"

# 1. Space 名称
SPACE_NAME=""
read -p "输入 Space 名称（默认 docflow-ai）: " SPACE_NAME
SPACE_NAME=${SPACE_NAME:-docflow-ai}

SPACE_ID="$HF_USER/$SPACE_NAME"
print_info "Space ID: $SPACE_ID"

# 2. 创建临时部署目录
DEPLOY_DIR=$(mktemp -d)
print_info "创建临时部署目录: $DEPLOY_DIR"

# 3. 复制必要文件
print_info "准备部署文件..."

# 复制 Dockerfile（HF Spaces 版本，必须命名为 Dockerfile 在根目录）
cp Dockerfile.hf "$DEPLOY_DIR/Dockerfile"

# 复制应用代码
cp -r apps "$DEPLOY_DIR/apps"

# 移除敏感文件（.env 中的 API Key 不应被提交到镜像）
rm -f "$DEPLOY_DIR/apps/web/api/.env" "$DEPLOY_DIR/apps/desktop/.env" 2>/dev/null || true

cp README.md "$DEPLOY_DIR/"
cp requirements.txt "$DEPLOY_DIR/" 2>/dev/null || true

# 复制 HF Spaces 配置 README（覆盖项目 README，包含 Spaces 元数据）
cp deploy/hf-spaces/README.md "$DEPLOY_DIR/README.md"

# 创建空数据目录
mkdir -p "$DEPLOY_DIR/data/uploads" "$DEPLOY_DIR/data/output" "$DEPLOY_DIR/data/logs"
touch "$DEPLOY_DIR/data/uploads/.gitkeep"
touch "$DEPLOY_DIR/data/output/.gitkeep"
touch "$DEPLOY_DIR/data/logs/.gitkeep"

# 创建 .dockerignore
cat > "$DEPLOY_DIR/.dockerignore" << 'EOF'
__pycache__/
*.pyc
.git/
data/uploads/*
data/output/*
data/logs/*
!data/*/.gitkeep
*.log
tests/
docs/
*.md
!README.md
.env
*.env.local
apps/web/api/.env
apps/desktop/.env
EOF

# 创建 .gitignore
cat > "$DEPLOY_DIR/.gitignore" << 'EOF'
.env
*.env.local
apps/web/api/.env
data/uploads/*
data/output/*
data/logs/*
!data/*/.gitkeep
EOF

# 4. 创建 Space
print_info "创建 Hugging Face Space: $SPACE_ID..."
huggingface-cli repo create "$SPACE_NAME" --type space --space_sdk docker 2>/dev/null || \
    print_warn "Space 可能已存在，继续部署..."

# 5. 初始化 Git 并推送
cd "$DEPLOY_DIR"

print_info "初始化 Git 仓库..."
git init
git checkout -b main
git add .
git commit -m "Deploy DocFlow to Hugging Face Spaces"

print_info "推送到 Hugging Face Spaces..."
git remote add origin "https://huggingface.co/spaces/$SPACE_ID"
git push --force origin main

# 6. 清理
cd -
rm -rf "$DEPLOY_DIR"

echo ""
print_ok "=========================================="
print_ok "  部署提交成功！"
print_ok "=========================================="
echo ""
echo "HF Spaces 正在构建 Docker 镜像（首次构建约 5-10 分钟）"
echo ""
echo "访问地址："
echo "  https://huggingface.co/spaces/$SPACE_ID"
echo ""
echo "查看构建日志："
echo "  https://huggingface.co/spaces/$SPACE_ID/settings"
echo ""
echo "重要：设置 PaddleOCR API Key"
echo "  1. 打开 Space 设置页：https://huggingface.co/spaces/$SPACE_ID/settings"
echo "  2. 在 'Repository secrets' 中添加："
echo "     PADDLEOCR_API_KEY = 你的Token"
echo "  3. 在 'Variables and secrets' 中添加环境变量"
echo "     PADDLEOCR_API_URL = https://paddleocr.aistudio-app.com/api/v2/ocr/jobs"
echo "  4. Space 会自动重启加载新配置"

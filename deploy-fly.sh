#!/bin/bash
# ======================================================
# Claw 错题管理系统 - Fly.io 一键部署脚本
# ======================================================
#
# 使用方法：
#   chmod +x deploy-fly.sh
#   ./deploy-fly.sh
#
# 前置条件：
#   1. 已安装 flyctl CLI
#   2. 已 fly auth login 登录
#   3. 准备好 PaddleOCR API Key
# ======================================================

set -e

# 颜色输出
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

print_info()  { echo -e "${BLUE}[INFO]${NC} $1"; }
print_ok()    { echo -e "${GREEN}[OK]${NC} $1"; }
print_warn()  { echo -e "${YELLOW}[WARN]${NC} $1"; }
print_error() { echo -e "${RED}[ERROR]${NC} $1"; }

# ---------- 0. 前置检查 ----------
print_info "检查 flyctl 是否安装..."
if ! command -v flyctl &> /dev/null; then
    print_error "flyctl 未安装！"
    echo ""
    echo "安装方法（macOS/Linux）："
    echo "  curl -L https://fly.io/install.sh | sh"
    echo ""
    echo "安装方法（Windows PowerShell）："
    echo "  iwr https://fly.io/install.ps1 -useb | iex"
    echo ""
    echo "安装后执行: flyctl auth login"
    exit 1
fi
print_ok "flyctl 已安装: $(flyctl version)"

# 检查登录状态
print_info "检查登录状态..."
if ! flyctl auth whoami &> /dev/null; then
    print_warn "未登录，正在打开浏览器登录..."
    flyctl auth login
fi
print_ok "已登录: $(flyctl auth whoami)"

# ---------- 1. 应用名称 ----------
APP_NAME=""
read -p "输入应用名称（全局唯一，默认 claw-ocr）: " APP_NAME
APP_NAME=${APP_NAME:-claw-ocr}

# 更新 fly.toml 中的 app 名称
if [[ "$OSTYPE" == "darwin"* ]]; then
    sed -i '' "s/^app = .*/app = \"$APP_NAME\"/" fly.toml
else
    sed -i "s/^app = .*/app = \"$APP_NAME\"/" fly.toml
fi
print_ok "fly.toml 应用名称已更新为: $APP_NAME"

# ---------- 2. 选择区域 ----------
echo ""
echo "可用区域（选择离你最近的）："
echo "  nrt  - 东京（推荐，亚洲快）"
echo "  sin  - 新加坡"
echo "  hkg  - 香港（如可用）"
echo "  lax  - 洛杉矶（美西）"
echo "  iad  - 阿什本（美东）"
echo "  fra  - 法兰克福（欧洲）"
REGION=""
read -p "输入区域代码（默认 nrt）: " REGION
REGION=${REGION:-nrt}

if [[ "$OSTYPE" == "darwin"* ]]; then
    sed -i '' "s/^primary_region = .*/primary_region = \"$REGION\"/" fly.toml
else
    sed -i "s/^primary_region = .*/primary_region = \"$REGION\"/" fly.toml
fi
print_ok "区域已设置为: $REGION"

# ---------- 3. 创建应用 ----------
print_info "创建 Fly.io 应用: $APP_NAME..."
if flyctl apps create "$APP_NAME" 2>/dev/null; then
    print_ok "应用创建成功"
else
    print_warn "应用可能已存在，继续部署..."
fi

# ---------- 4. 创建持久化卷 ----------
print_info "创建持久化卷 claw_data (1GB)..."
if flyctl volumes create claw_data --size 1 --region "$REGION" 2>/dev/null; then
    print_ok "卷创建成功"
else
    print_warn "卷可能已存在，继续..."
fi

# ---------- 5. 配置 Secrets ----------
echo ""
echo "=== 配置 PaddleOCR API ==="
echo "Token 获取地址: https://aistudio.baidu.com/paddleocr/task"
echo ""

API_KEY=""
read -p "输入 PaddleOCR API Key: " API_KEY
if [ -z "$API_KEY" ]; then
    print_warn "未输入 API Key，稍后可通过以下命令设置："
    echo "  flyctl secrets set PADDLEOCR_API_KEY=your_token"
else
    print_info "设置 PaddleOCR API Key..."
    flyctl secrets set PADDLEOCR_API_KEY="$API_KEY"
    print_ok "API Key 已设置"
fi

# API URL（默认官方地址，可选修改）
API_URL=""
read -p "输入 PaddleOCR API URL（回车使用默认）: " API_URL
if [ -n "$API_URL" ]; then
    flyctl secrets set PADDLEOCR_API_URL="$API_URL"
    print_ok "API URL 已设置"
fi

# ---------- 6. 部署 ----------
print_info "开始部署..."
echo ""
flyctl deploy --dockerfile Dockerfile.fly

# ---------- 7. 验证 ----------
print_info "等待服务启动..."
sleep 10

print_info "检查应用状态..."
flyctl status

echo ""
print_ok "=========================================="
print_ok "  部署完成！"
print_ok "=========================================="
echo ""
echo "访问地址："
flyctl apps list | grep "$APP_NAME" || true
echo ""
echo "  https://$APP_NAME.fly.dev/app"
echo ""
echo "常用命令："
echo "  flyctl status              # 查看状态"
echo "  flyctl logs                # 查看日志"
echo "  flyctl ssh console         # 进入容器"
echo "  flyctl secrets list        # 查看已设置的 secrets"
echo "  flyctl scale memory 512    # 升级到 512MB 内存（付费）"
echo "  flyctl apps destroy $APP_NAME  # 删除应用"
echo ""
echo "如需绑定自定义域名，参考：https://fly.io/docs/networking/custom-domains/"

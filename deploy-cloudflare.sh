#!/bin/bash
# ======================================================
# DocFlow - Cloudflare Tunnel 一键部署脚本
# ======================================================
# 使用方法：
#   bash deploy-cloudflare.sh
#
# 前置条件：
#   1. 已购买域名（如 .top 域名，约 5 元/年）
#   2. 域名已托管到 Cloudflare（免费）
#   3. 已安装 cloudflared 客户端
#   4. 已在 Cloudflare Zero Trust 创建 Tunnel
#
# 完整教程：https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/
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
print_info "检查 cloudflared..."
if ! command -v cloudflared &> /dev/null; then
    print_error "cloudflared 未安装"
    echo ""
    echo "安装方法："
    echo "  Windows: winget install --id Cloudflare.cloudflared"
    echo "  macOS:   brew install cloudflared"
    echo "  Linux:   curl -L https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64 -o /usr/local/bin/cloudflared && chmod +x /usr/local/bin/cloudflared"
    exit 1
fi
print_ok "cloudflared 已安装: $(cloudflared --version 2>&1)"

# 1. 检查登录状态
print_info "检查 Cloudflare 登录状态..."
if [ ! -f ~/.cloudflared/cert.pem ]; then
    print_warn "未登录 Cloudflare，开始登录..."
    echo ""
    echo "浏览器会打开授权页面，选择你的域名授权"
    echo ""
    cloudflared tunnel login
fi
print_ok "已登录 Cloudflare"

# 2. 创建 Tunnel
print_info "创建 Tunnel..."
read -p "输入 Tunnel 名称（默认 docflow）: " TUNNEL_NAME
TUNNEL_NAME=${TUNNEL_NAME:-docflow}

TUNNEL_ID=$(cloudflared tunnel create "$TUNNEL_NAME" 2>&1 | grep -oP 'Created \K[a-f0-9-]{36}' || echo "")
if [ -z "$TUNNEL_ID" ]; then
    print_warn "Tunnel 可能已存在，尝试获取 ID..."
    TUNNEL_ID=$(cloudflared tunnel list 2>&1 | grep "$TUNNEL_NAME" | awk '{print $1}')
fi

if [ -z "$TUNNEL_ID" ]; then
    print_error "无法创建或获取 Tunnel，请手动操作"
    exit 1
fi
print_ok "Tunnel ID: $TUNNEL_ID"

# 3. 配置域名
read -p "输入你的域名（如 docflow.example.top）: " DOMAIN
if [ -z "$DOMAIN" ]; then
    print_error "域名不能为空"
    exit 1
fi

print_info "配置 DNS 路由..."
cloudflared tunnel route dns "$TUNNEL_NAME" "$DOMAIN" 2>/dev/null || \
    print_warn "DNS 路由可能已存在，继续..."

# 4. 生成配置文件
CONFIG_DIR="$HOME/.cloudflared"
mkdir -p "$CONFIG_DIR"

cat > "$CONFIG_DIR/config.yml" << EOF
tunnel: $TUNNEL_ID
credentials-file: $CONFIG_DIR/$TUNNEL_ID.json

ingress:
  - hostname: $DOMAIN
    service: http://localhost:8500
  - service: http_status:404
EOF

print_ok "配置文件已生成: $CONFIG_DIR/config.yml"

# 5. 启动服务
echo ""
print_ok "=========================================="
print_ok "  配置完成！"
print_ok "=========================================="
echo ""
echo "访问地址：https://$DOMAIN"
echo ""
echo "启动命令："
echo "  1. 先启动 DocFlow 服务："
echo "     cd apps/web/api && python main.py"
echo ""
echo "  2. 再启动 Cloudflare Tunnel："
echo "     cloudflared tunnel run $TUNNEL_NAME"
echo ""
echo "  3. 浏览器访问：https://$DOMAIN"
echo ""
echo "停止服务：Ctrl+C 即可"

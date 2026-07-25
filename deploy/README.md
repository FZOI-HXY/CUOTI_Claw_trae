# 部署目录说明

本目录包含 DocFlow 的部署相关配置。

## 目录结构

```
deploy/
├── nginx/
│   ├── nginx.conf          # Nginx 反向代理配置
│   └── certs/              # SSL 证书目录（需自行放置）
│       ├── fullchain.pem   # 证书链
│       └── privkey.pem     # 私钥
└── README.md               # 本文件
```

## 使用方法

### 1. 准备 SSL 证书

将你的域名证书放入 `certs/` 目录：

```bash
mkdir -p deploy/nginx/certs
cp /path/to/fullchain.pem deploy/nginx/certs/
cp /path/to/privkey.pem deploy/nginx/certs/
```

如果使用 Let's Encrypt（免费证书）：

```bash
# 安装 certbot
sudo apt install certbot

# 获取证书（先停止 80 端口服务）
sudo certbot certonly --standalone -d your-domain.com

# 复制证书
sudo cp /etc/letsencrypt/live/your-domain.com/fullchain.pem deploy/nginx/certs/
sudo cp /etc/letsencrypt/live/your-domain.com/privkey.pem deploy/nginx/certs/
```

### 2. 启动生产环境

```bash
docker compose --profile production up -d
```

### 3. 证书自动续期

Let's Encrypt 证书有效期 90 天，建议设置 cron 自动续期：

```bash
# 编辑 crontab
sudo crontab -e

# 每月 1 号凌晨 3 点续期并重启 nginx
0 3 1 * * certbot renew --quiet && docker compose restart nginx
```

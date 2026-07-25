# ======================================================
# Claw 错题管理系统 - Dockerfile
# 多阶段构建：依赖层 + 运行层
# ======================================================

# ---------- 阶段 1: 依赖构建 ----------
FROM python:3.13-slim AS builder

# 设置 pip 缓存目录，加速重复构建
ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /build

# 仅复制依赖清单，利用 Docker 层缓存
COPY apps/web/api/requirements.txt ./requirements.txt

# 安装依赖到指定目录（便于第二阶段复制）
RUN pip install --upgrade pip && \
    pip install --prefix=/install -r requirements.txt

# ---------- 阶段 2: 运行时镜像 ----------
FROM python:3.13-slim AS runtime

# 元数据标签
LABEL maintainer="Claw Team" \
      description="Claw 错题管理系统 - 基于 PaddleOCR 的智能错题识别服务" \
      version="1.2.0"

# 运行时环境变量（不写入敏感信息）
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    TZ=Asia/Shanghai \
    HOST=0.0.0.0 \
    PORT=8500 \
    DEBUG=false \
    LOG_LEVEL=INFO

# 安装系统依赖（运行时所需的最小集）
#   - tzdata: 时区数据
#   - curl:  健康检查
#   - ca-certificates: HTTPS 出站（访问 PaddleOCR API）
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        tzdata \
        curl \
        ca-certificates && \
    ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && \
    echo $TZ > /etc/timezone && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# 从 builder 阶段复制已安装的 Python 依赖
COPY --from=builder /install /usr/local

# 创建非 root 用户运行应用（安全最佳实践，UID 1000 确保容器兼容性）
RUN groupadd --gid 1000 claw && \
    useradd -m -u 1000 -g claw -d /home/claw claw

ENV HOME=/home/claw \
    PATH=/home/claw/.local/bin:$PATH

# 设置工作目录
WORKDIR /app

# 复制项目代码
# 注意：.dockerignore 会排除不需要的文件
COPY --chown=claw:claw . /app

# 创建数据目录并设置权限
#   - uploads:   用户上传的图片
#   - output:    生成的报告 + SQLite 数据库
#   - logs:      应用日志
RUN mkdir -p /app/data/uploads /app/data/output /app/data/logs && \
    chown -R claw:claw /app/data

# 切换到非 root 用户
USER claw

# 暴露服务端口
EXPOSE 8500

# 健康检查：每 30 秒检查一次 /api/health
#   --interval:  检查间隔
#   --timeout:   超时时间
#   --start-period: 启动后宽限期（给应用预热时间）
#   --retries:   连续失败次数后标记为 unhealthy
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD curl -fs http://127.0.0.1:${PORT}/api/health || exit 1

# 启动命令
# 使用 uvicorn 直接启动，生产环境不启用 reload
# 通过环境变量 CLAW_DATA_DIR 将数据目录指向持久化卷
ENV CLAW_DATA_DIR=/app/data
CMD ["python", "-m", "uvicorn", "apps.web.api.main:app", \
     "--host", "0.0.0.0", "--port", "8500", \
     "--workers", "1", "--log-level", "info", "--no-access-log"]

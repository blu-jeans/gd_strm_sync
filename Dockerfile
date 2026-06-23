# Dockerfile for STRM Sync Portal
# 基于 Python 3.10-slim 构建，内置 rclone 支持与多线程加速
# @author: hyq
# @version: 2026-06-23

FROM python:3.10-slim

# 设置环境变量
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# 安装系统基础依赖与 SSL 证书
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    unzip \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# hyq: 2026-06-23 Modify for multi-architecture (AMD64/ARM64) rclone installation auto-adaptation
# # 下载并安装官方最新版 Rclone
# RUN curl -O https://downloads.rclone.org/rclone-current-linux-amd64.zip \
#     && unzip rclone-current-linux-amd64.zip \
#     && cp rclone-*-linux-amd64/rclone /usr/bin/ \
#     && chmod 755 /usr/bin/rclone \
#     && rm -rf rclone-* rclone-current-linux-amd64.zip

# 动态多架构安装 Rclone
ARG TARGETPLATFORM
RUN ARCH=$(echo ${TARGETPLATFORM} | cut -d'/' -f2) && \
    if [ "$ARCH" = "amd64" ]; then R_ARCH="amd64"; \
    elif [ "$ARCH" = "arm64" ] || [ "$ARCH" = "aarch64" ] || [ "$ARCH" = "arm" ]; then R_ARCH="arm64"; \
    else R_ARCH="amd64"; fi && \
    curl -O "https://downloads.rclone.org/rclone-current-linux-${R_ARCH}.zip" && \
    unzip "rclone-current-linux-${R_ARCH}.zip" && \
    cp rclone-*-linux-${R_ARCH}/rclone /usr/bin/ && \
    chmod 755 /usr/bin/rclone && \
    rm -rf rclone-* "rclone-current-linux-${R_ARCH}.zip"

# 创建应用目录
WORKDIR /app

# 安装 Python 依赖
COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

# 拷贝项目源码与静态网页文件
COPY . /app/

# 创建必要的持久化文件夹目录
RUN mkdir -p /app/logs /app/cache

# 暴露 FastAPI API 默认端口
EXPOSE 8000

# 运行 FastAPI 面板
CMD ["uvicorn", "web_app:app", "--host", "0.0.0.0", "--port", "8000"]

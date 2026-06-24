#!/bin/bash
# =================================================================
# STRM Sync Panel Docker Build & Push Script for Shell (Git Bash/WSL)
# @author: hyq
# @version: 2026-06-24
# =================================================================

IMAGE_NAME="fckipk/strm-sync-panel"
TAG="latest"

echo -e "\033[36m========== 🚀 STRM Sync Panel Docker 构建与推送系统 ==========\033[0m"

# 1. 确认 Docker 是否运行
if ! docker info >/dev/null 2>&1; then
    echo -e "\033[31m❌ Docker 守护进程未启动，请先运行 Docker！\033[0m"
    exit 1
fi

# 2. 提供选择
echo -e "\033[33m请选择构建模式：\033[0m"
echo "  [1] 单架构本地构建 (仅限本地当前架构，速度极快)"
echo "  [2] 多架构交叉编译构建并推送 (AMD64 & ARM64，推荐 NAS 部署使用)"
read -p "请输入选择 [1-2] (默认 1): " choice
choice=${choice:-1}

if [ "$choice" -eq 1 ]; then
    echo -e "\033[32m开始单架构本地构建...\033[0m"
    if docker build -t "${IMAGE_NAME}:${TAG}" .; then
        echo -e "\033[32m✅ 本地构建成功！镜像名: ${IMAGE_NAME}:${TAG}\033[0m"
        read -p "是否立即推送到 Docker Hub? (y/n, 默认 n): " push
        if [[ "$push" == "y" || "$push" == "Y" ]]; then
            echo -e "\033[32m正在推送到 Docker Hub...\033[0m"
            docker push "${IMAGE_NAME}:${TAG}"
        fi
    else
        echo -e "\033[31m❌ 本地构建失败！\033[0m"
    fi
else
    echo -e "\033[32m正在开启 Docker Buildx 交叉编译构建并推送...\033[0m"
    docker buildx create --use --name strm-builder 2>/dev/null || true
    docker buildx inspect --bootstrap
    
    echo -e "\033[32m开始多架构构建 (linux/amd64, linux/arm64) 并自动 Push...\033[0m"
    if docker buildx build --platform linux/amd64,linux/arm64 -t "${IMAGE_NAME}:${TAG}" --push .; then
        echo -e "\033[32m✅ 多架构镜像编译并推送成功！\033[0m"
    else
        echo -e "\033[31m❌ 多架构编译或推送失败！请确认已在终端执行过 'docker login'。\033[0m"
    fi
fi

echo -e "\033[36m========== 🎉 构建任务结束 ==========\033[0m"

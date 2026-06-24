# =================================================================
# STRM Sync Panel Docker Build & Push Script for Windows PowerShell
# @author: hyq
# @version: 2026-06-24
# =================================================================

$IMAGE_NAME="fckipk/strm-sync-panel"
$TAG="latest"

Write-Host "========== STRM Sync Panel Docker Build & Push ==========" -ForegroundColor Cyan

# 1. Check if Docker is running
try {
    $null = docker info
} catch {
    Write-Error "Docker is not running or not found! Please start Docker Desktop first."
    Exit 1
}
if ($LASTEXITCODE -ne 0) {
    Write-Error "Docker is not running! Please start Docker Desktop."
    Exit 1
}

# 2. Choice of build type
Write-Host "Select build mode:" -ForegroundColor Yellow
Write-Host "  [1] Single architecture local build (Fast, local only)"
Write-Host "  [2] Multi-architecture buildx build & push (AMD64 & ARM64)"
$choice = Read-Host "Enter your choice [1-2] (Default: 1)"
if ($choice -ne "2") { $choice = "1" }

if ($choice -eq "1") {
    Write-Host "Starting single architecture local build..." -ForegroundColor Green
    docker build -t "${IMAGE_NAME}:${TAG}" .
    if ($LASTEXITCODE -eq 0) {
        Write-Host "Local build success! Image: ${IMAGE_NAME}:${TAG}" -ForegroundColor Green
        $push = Read-Host "Do you want to push to Docker Hub now? (y/n, Default: n)"
        if ($push -eq "y" -or $push -eq "Y") {
            Write-Host "Pushing to Docker Hub..." -ForegroundColor Green
            docker push "${IMAGE_NAME}:${TAG}"
        }
    } else {
        Write-Error "Local build failed!"
    }
} else {
    Write-Host "Enabling Docker Buildx cross-compilation..." -ForegroundColor Green
    # Enable buildx instance
    docker buildx create --use --name strm-builder 2>$null
    docker buildx inspect --bootstrap
    
    Write-Host "Starting multi-architecture build (linux/amd64, linux/arm64) and push..." -ForegroundColor Green
    docker buildx build --platform linux/amd64,linux/arm64 -t "${IMAGE_NAME}:${TAG}" --push .
    if ($LASTEXITCODE -eq 0) {
        Write-Host "Multi-architecture build and push success!" -ForegroundColor Green
    } else {
        Write-Error "Multi-architecture build or push failed! Please check if you have executed 'docker login'."
    }
}

Write-Host "========== Build Process Finished ==========" -ForegroundColor Cyan

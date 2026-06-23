# ⚡ STRM Sync Panel - 媒体同步控制面板

这是一个基于 FastAPI + Tailwind UI (Sleek Dark Mode) 打造的 **STRM 媒体同步与控制面板**。它能够将谷歌云盘等远程挂载目录中的视频元数据，实时转换为 `.strm` 格式文件并挂载分发给 Emby。

本项目已被完全容器化，支持 **AMD64 / ARM64** 多架构构建，确保在 PC、群晖/威联通 NAS、软路由、树莓派等千差万别的运行环境中均可高效运行。

> **Author**: hyq  
> **Version**: 2026-06-23

---

## 🚀 部署指南

在服务器上运行该系统，只需准备一个 `docker-compose.yml` 配置文件即可直接运行。

### 1. 准备工作目录
在宿主机上创建一个空文件夹（例如 `/root/strm-sync`），并在该文件夹内新建 `docker-compose.yml`。

### 2. 编写 `docker-compose.yml`
```yaml
version: '3.8'

services:
  strm-sync-panel:
    image: fckipk/strm-sync-panel:latest
    container_name: strm-sync-panel
    restart: always
    ports:
      - "9000:8000"
    environment:
      # 宿主机上 emby 用户的 UID 和 GID，解决容器内外权限冲突，请根据 id emby 的实际结果进行替换
      - EMBY_UID=998
      - EMBY_GID=997
      # 2. 动态指定容器内可安全加载的挂载卷范围 (需与 volumes 保持一致)
      - GD_ROOT=/mnt          
      - STRM_ROOT=/mnt/strm
    volumes:
      # 挂载后，宿主机目录下会自动产生 cache/ 数据库和 logs/ 滚动日志
      - ./cache:/app/cache
      - ./logs:/app/logs
      # 挂载宿主机 rclone 配置文件目录 (只读)，确保容器内能识别远程网盘
      - /root/.config/rclone:/root/.config/rclone:ro
      # 挂载宿主机 rclone 的 Service Account 证书目录 (只读)，防止 accounts 文件找不到，没使用SA的可以忽略此配置
      - /root/accounts:/root/accounts:ro
      # 挂载宿主机的媒体根目录与 strm 目的输出目录 (视实际路径修改)
      - /mnt:/mnt
```

### 3. 启动服务
在当前工作目录下执行以下命令：
```bash
docker-compose up -d
```
启动后，访问 `http://<你的服务器IP>:9000` 即可登录控制面板进行可视化操作。

### 🔑 默认登录凭据

* **默认用户名**：`admin`
* **默认密码**：`admin123`

> ⚠️ **安全提醒**：首次登录成功后，**请务必立即修改默认密码**，防止服务暴露于公网产生安全隐患。

---

## ⚙️ 核心环境变量与配置项说明

系统通过环境变量来进行自适应运行调整，关键配置项如下：

| 环境变量 | 默认值 | 说明 |
| :--- | :--- | :--- |
| `EMBY_UID` | `998` | 宿主机上 Emby 用户的 UID。为解决容器内外权限冲突，**请在宿主机执行 `id emby` 获取实际结果并进行替换**。新生成的 `.strm` 文件与目录会被自动赋予该 UID 所有权。 |
| `EMBY_GID` | `997` | 宿主机上 Emby 用户的 GID。**请在宿主机执行 `id emby` 获取实际结果并进行替换**。 |
| `GD_ROOT` | `/mnt` | 远程网盘在本地映射的根路径白名单。面板只允许访问和同步在此根路径之下的目录，以防路径越权。 |
| `STRM_ROOT` | `/mnt/strm` | 生成 `.strm` 媒体文件的本地挂载输出目标目录。 |

---

## 📁 数据持久化与日志安全

* **数据库持久化**：SQLite 数据库保存在 `/app/cache/strm_sync.db` 中。在容器部署时，已将其映射到宿主机的 `./cache`。即使升级镜像或重构容器，所有同步任务、设置与网盘配置依然**保持原样不会丢失**。
* **按天滚动日志与防撑爆机制**：系统日志存储于 `/app/logs/` 下。为了防止服务器磁盘空间被无限增长的日志写满，后台日志记录器集成了**滚动备份与过期自动清理机制**（可在系统中指定最大保留体积/天数，超期将自动删除旧日志），保障生产环境的安全稳定。

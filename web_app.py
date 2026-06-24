# -*- coding: utf-8 -*-
"""
strm 同步控制面板后端主程序
使用 FastAPI 实现接口，APScheduler 管理定时，subprocess 管理同步进程并通过 SSE 实时传输日志。
@author: hyq
@version: 2026-06-23
"""
# hyq: 2026-06-23 Modify for imports preservation and MIME type initialization
# import os
# import sys
# import time
# import json
# import queue
# import subprocess
# import threading
# import datetime
# from typing import Optional, List
# from fastapi import FastAPI, Depends, HTTPException, status, Security
# from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
# from fastapi.responses import FileResponse, StreamingResponse
# from fastapi.staticfiles import StaticFiles
# from fastapi.middleware.cors import CORSMiddleware
# from pydantic import BaseModel
# import jwt
# from apscheduler.schedulers.background import BackgroundScheduler
# from apscheduler.triggers.cron import CronTrigger

import os
import sys
import time
import json
import queue
import subprocess
import threading
import datetime
import mimetypes
from typing import Optional, List
from fastapi import FastAPI, Depends, HTTPException, status, Security
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import jwt
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

# 强制注册 MIME 类型以应对 Windows 平台注册表异常导致的 JS/CSS 404/Block 问题
mimetypes.add_type("application/javascript", ".js")
mimetypes.add_type("text/css", ".css")

import db

# JWT 配置
JWT_SECRET = "strm_sync_dashboard_jwt_secret_2026_key"
JWT_ALGORITHM = "HS256"
TOKEN_EXPIRE_MINUTES = 60 * 24 # 24小时过期

app = FastAPI(title="STRM Sync Panel API", version="1.0.0")

# 跨域配置
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 挂载静态文件
STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
if not os.path.exists(STATIC_DIR):
    os.makedirs(STATIC_DIR, exist_ok=True)
    os.makedirs(os.path.join(STATIC_DIR, "css"), exist_ok=True)
    os.makedirs(os.path.join(STATIC_DIR, "js"), exist_ok=True)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


# 任务日志存储文件夹
LOGS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
if not os.path.exists(LOGS_DIR):
    os.makedirs(LOGS_DIR, exist_ok=True)

# 全局任务控制变量
current_process = None
current_task_id = None
task_thread = None
log_listeners = [] # 存储活动中的 SSE 客户端队列
latest_logs = []   # 保存最近 1000 行日志，供新连接的客户端查看
task_stats = {
    "items_parsed": 0,
    "strm_written": 0,
    "files_removed": 0,
    "dirs_removed": 0,
    "metadata_synced": 0,
    "elapsed_time": 0.0
}

# 调度器
scheduler = BackgroundScheduler()
scheduler.start()

# ----------------- JWT 验证依赖 -----------------
security = HTTPBearer()

def get_current_user(credentials: HTTPAuthorizationCredentials = Security(security)):
    token = credentials.credentials
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="凭证无效",
                headers={"WWW-Authenticate": "Bearer"},
            )
        return username
    except jwt.PyJWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="凭证已过期或无效",
            headers={"WWW-Authenticate": "Bearer"},
        )

# ----------------- 数据契约 -----------------
class LoginRequest(BaseModel):
    username: str
    password: str

class PasswordRequest(BaseModel):
    old_password: str
    new_password: str

class SourceRequest(BaseModel):
    name: str
    gd_path: str
    strm_path: str
    remote_path: str
    sync_metadata: Optional[int] = 1
    drive_type: Optional[str] = "GoogleDrive"

class ReorderRequest(BaseModel):
    ordered_ids: List[int]

class SettingsRequest(BaseModel):
    worker_concurrency: int
    batch_write_size: int
    source_concurrency: int
    cron_expression: str
    metadata_types: str

# ----------------- 帮助函数 -----------------

# hyq: 2026-06-23 Modify generate_ini_config to support single source triggering
# def generate_ini_config() -> str:
#     """从数据库读取配置并生成临时的 INI 配置文件"""
#     sources = db.get_all_sources()
#     global_cfg = db.get_all_global_configs()
# 
#     ini_content = []
#     # 全局部分
#     ini_content.append("[global]")
#     ini_content.append(f"WORKER_CONCURRENCY = {global_cfg.get('WORKER_CONCURRENCY', '16')}")
#     ini_content.append(f"BATCH_WRITE_SIZE = {global_cfg.get('BATCH_WRITE_SIZE', '1000')}")
#     ini_content.append(f"SOURCE_CONCURRENCY = {global_cfg.get('SOURCE_CONCURRENCY', '5')}")
#     ini_content.append("")
# 
#     # 各个源部分
#     for src in sources:
#         ini_content.append(f"[{src['name']}]")
#         ini_content.append(f"SOURCE_GD = {src['gd_path']}")
#         ini_content.append(f"SOURCE_STRM = {src['strm_path']}")
#         ini_content.append(f"SOURCE_CMD = {src['remote_path']}")
#         ini_content.append("")
# 
#     ini_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "strm_config_run.ini")
#     with open(ini_path, "w", encoding="utf-8") as f:
#         f.write("\n".join(ini_content))
#     return ini_path

def generate_ini_config(source_id: Optional[int] = None) -> str:
    """从数据库读取配置并生成临时的 INI 配置文件，支持指定单源进行同步"""
    if source_id is not None:
        source = db.get_source_by_id(source_id)
        if not source:
            raise HTTPException(status_code=400, detail=f"找不到指定的同步源 ID: {source_id}")
        sources = [source]
    else:
        sources = db.get_all_sources()
        
    global_cfg = db.get_all_global_configs()

    ini_content = []
    # 全局部分
    ini_content.append("[global]")
    ini_content.append(f"WORKER_CONCURRENCY = {global_cfg.get('WORKER_CONCURRENCY', '16')}")
    ini_content.append(f"BATCH_WRITE_SIZE = {global_cfg.get('BATCH_WRITE_SIZE', '1000')}")
    ini_content.append(f"SOURCE_CONCURRENCY = {global_cfg.get('SOURCE_CONCURRENCY', '5')}")
    ini_content.append(f"METADATA_TYPES = {global_cfg.get('METADATA_TYPES', 'nfo,jpg,jpeg,png,svg,ass,srt,sup,mp3,flac,wav,aac')}")
    ini_content.append("")

    # 各个源部分
    for src in sources:
        ini_content.append(f"[{src['name']}]")
        ini_content.append(f"SOURCE_GD = {src['gd_path']}")
        ini_content.append(f"SOURCE_STRM = {src['strm_path']}")
        ini_content.append(f"SOURCE_CMD = {src['remote_path']}")
        ini_content.append(f"SYNC_METADATA = {src.get('sync_metadata', 1)}")
        ini_content.append("")

    ini_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "strm_config_run.ini")
    with open(ini_path, "w", encoding="utf-8") as f:
        f.write("\n".join(ini_content))
    return ini_path

def broadcast_log(line: str):
    """广播日志到所有 SSE 客户端"""
    latest_logs.append(line)
    if len(latest_logs) > 1000:
        latest_logs.pop(0)
    
    # 向所有监听者推送
    for q in log_listeners:
        try:
            q.put_nowait(line)
        except Exception:
            pass

def parse_summary_from_logs(logs_list):
    """从日志行中分析出最终的数据统计"""
    stats = {
        "items_parsed": 0,
        "strm_written": 0,
        "files_removed": 0,
        "dirs_removed": 0,
        "metadata_synced": 0,
        "elapsed_time": 0.0
    }
    for line in logs_list:
        clean = line.strip()
        if "Wall Time:" in clean:
            try:
                stats["elapsed_time"] = float(clean.split("Wall Time:")[1].strip().replace("s", ""))
            except: pass
        elif "Items Parsed:" in clean:
            try:
                stats["items_parsed"] = int(clean.split("Items Parsed:")[1].strip())
            except: pass
        elif "Strm Written:" in clean:
            try:
                stats["strm_written"] = int(clean.split("Strm Written:")[1].strip())
            except: pass
        elif "Files Removed:" in clean:
            try:
                stats["files_removed"] = int(clean.split("Files Removed:")[1].strip())
            except: pass
        elif "Dirs Removed:" in clean:
            try:
                stats["dirs_removed"] = int(clean.split("Dirs Removed:")[1].strip())
            except: pass
        elif "Metadata Synced:" in clean:
            try:
                stats["metadata_synced"] = int(clean.split("Metadata Synced:")[1].strip())
            except: pass
    return stats

# hyq: 2026-06-23 Add cleanup_old_logs and extract_task_logs functions for log management
def cleanup_old_logs(max_days: int = 7, max_total_size_mb: float = 50.0):
    """
    清理旧日志文件以防磁盘撑爆：
    1. 清理超过 max_days 天前的旧 sync_*.log
    2. 若 logs/ 目录下总日志大小超过 max_total_size_mb，从最旧的文件开始删，直到小于容量限制
    """
    if not os.path.exists(LOGS_DIR):
        return
        
    try:
        now = time.time()
        log_files = []
        
        for fn in os.listdir(LOGS_DIR):
            if fn.startswith("sync_") and fn.endswith(".log"):
                path = os.path.join(LOGS_DIR, fn)
                st = os.stat(path)
                mtime = st.st_mtime
                size = st.st_size
                log_files.append((path, mtime, size))
                
        # 1. 按照天数清理
        cutoff = now - (max_days * 24 * 3600)
        remaining_files = []
        for path, mtime, size in log_files:
            if mtime < cutoff:
                try:
                    os.remove(path)
                except Exception: pass
            else:
                remaining_files.append((path, mtime, size))
                
        # 2. 按照总容量限制清理
        remaining_files.sort(key=lambda x: x[1])
        total_size = sum(f[2] for f in remaining_files)
        max_bytes = max_total_size_mb * 1024 * 1024
        
        while total_size > max_bytes and remaining_files:
            oldest_path, oldest_mtime, oldest_size = remaining_files.pop(0)
            try:
                os.remove(oldest_path)
                total_size -= oldest_size
            except Exception: pass
    except Exception as e:
        print(f"[LogCleanup] Error cleaning up logs: {e}")

def extract_task_logs(file_path: str, task_id: int) -> List[str]:
    """
    从按天记录的日志文件中提取指定 task_id 范围内的日志行。
    如果没找到对应的标记，则默认返回整天日志。
    """
    if not os.path.exists(file_path):
        return []
        
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            lines = [line.rstrip("\n") for line in f.readlines()]
            
        start_marker = f"Task {task_id} Start"
        end_marker = f"Task {task_id} End"
        
        extracted = []
        recording = False
        
        for line in lines:
            if start_marker in line:
                recording = True
                extracted.append(line)
                continue
            if end_marker in line:
                extracted.append(line)
                recording = False
                break
            if recording:
                extracted.append(line)
                
        if extracted:
            return extracted
        return lines # 没找到标记则降级返回整天日志
    except Exception:
        return []

# hyq: 2026-06-23 Modify run_sync_process to support daily log merging, task markers and auto pruning
# def run_sync_process(task_id: int, config_file: str, force_update: bool):
#     """在子进程中执行同步任务的主工作线程"""
#     global current_process, current_task_id, task_stats
#     
#     log_file_name = f"task_{task_id}.log"
#     log_file_path = os.path.join(LOGS_DIR, log_file_name)
#     log_file = open(log_file_path, "w", encoding="utf-8")
#     
#     latest_logs.clear()
#     task_stats = {
#         "items_parsed": 0,
#         "strm_written": 0,
#         "files_removed": 0,
#         "dirs_removed": 0,
#         "elapsed_time": 0.0
#     }
#     
#     broadcast_log(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] >>> 任务 {task_id} 启动...")
#     
#     # 组装命令
#     cmd = [sys.executable, "strm_fin.py", "--config", config_file]
#     if force_update:
#         cmd.append("--force")
#     
#     start_time = time.time()
#     
#     try:
#         current_process = subprocess.Popen(
#             cmd,
#             stdout=subprocess.PIPE,
#             stderr=subprocess.STDOUT,
#             text=True,
#             bufsize=1,
#             cwd=os.path.dirname(os.path.abspath(__file__))
#         )
#         
#         # 逐行读取子进程输出
#         for line in iter(current_process.stdout.readline, ""):
#             log_file.write(line)
#             log_file.flush()
#             # 推送到前端
#             broadcast_log(line.rstrip("\n"))
#             
#         current_process.wait()
#         return_code = current_process.returncode
#         
#         elapsed = time.time() - start_time
#         
#         # 统计解析
#         stats = parse_summary_from_logs(latest_logs)
#         task_stats.update(stats)
#         if task_stats["elapsed_time"] == 0.0:
#             task_stats["elapsed_time"] = round(elapsed, 3)
# 
#         if return_code == 0:
#             status_str = "success"
#             broadcast_log(f"\n[{datetime.datetime.now().strftime('%H:%M:%S')}] >>> 任务完成。")
#         elif return_code == -15 or return_code == -9 or return_code == 127: # 被手动强行终止
#             status_str = "stopped"
#             broadcast_log(f"\n[{datetime.datetime.now().strftime('%H:%M:%S')}] >>> 任务被用户中止。")
#         else:
#             status_str = "failed"
#             broadcast_log(f"\n[{datetime.datetime.now().strftime('%H:%M:%S')}] >>> 任务执行失败，退出码: {return_code}")
#             
#         db.finish_sync_task(
#             task_id, 
#             status_str,
#             items_parsed=task_stats["items_parsed"],
#             strm_written=task_stats["strm_written"],
#             files_removed=task_stats["files_removed"],
#             dirs_removed=task_stats["dirs_removed"],
#             elapsed_time=task_stats["elapsed_time"],
#             log_file=log_file_name
#         )
#         
#     except Exception as e:
#         broadcast_log(f"执行异常: {str(e)}")
#         db.finish_sync_task(task_id, "failed", log_file=log_file_name)
#     finally:
#         log_file.close()
#         current_process = None
#         current_task_id = None
#         # 清理临时 ini
#         try:
#             if os.path.exists(config_file):
#                 os.remove(config_file)
#         except: pass

def run_sync_process(task_id: int, config_file: str, force_update: bool):
    """在子进程中执行同步任务的主工作线程，按天追加记录日志并清理过期日志"""
    global current_process, current_task_id, task_stats
    
    today_str = datetime.date.today().strftime("%Y-%m-%d")
    log_file_name = f"sync_{today_str}.log"
    log_file_path = os.path.join(LOGS_DIR, log_file_name)
    
    try:
        log_file = open(log_file_path, "a", encoding="utf-8")
    except Exception as e:
        print(f"[Log] Failed to open log file {log_file_path}: {e}")
        return
    
    latest_logs.clear()
    task_stats = {
        "items_parsed": 0,
        "strm_written": 0,
        "files_removed": 0,
        "dirs_removed": 0,
        "metadata_synced": 0,
        "elapsed_time": 0.0
    }
    
    # 写入任务开始标记
    start_marker_msg = f"\n[{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] ==================== Task {task_id} Start ===================="
    try:
        log_file.write(start_marker_msg + "\n")
        log_file.flush()
    except: pass
    
    broadcast_log(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] >>> 任务 {task_id} 启动...")
    
    # 组装命令
    cmd = [sys.executable, "strm_fin.py", "--config", config_file]
    if force_update:
        cmd.append("--force")
    
    start_time = time.time()
    
    try:
        current_process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            cwd=os.path.dirname(os.path.abspath(__file__))
        )
        
        # 逐行读取子进程输出
        for line in iter(current_process.stdout.readline, ""):
            try:
                log_file.write(line)
                log_file.flush()
            except: pass
            # 推送到前端
            broadcast_log(line.rstrip("\n"))
            
        current_process.wait()
        return_code = current_process.returncode
        
        elapsed = time.time() - start_time
        
        # 统计解析
        stats = parse_summary_from_logs(latest_logs)
        task_stats.update(stats)
        if task_stats["elapsed_time"] == 0.0:
            task_stats["elapsed_time"] = round(elapsed, 3)
 
        if return_code == 0:
            status_str = "success"
            broadcast_log(f"\n[{datetime.datetime.now().strftime('%H:%M:%S')}] >>> 任务完成。")
        elif return_code == -15 or return_code == -9 or return_code == 127: # 被手动强行终止
            status_str = "stopped"
            broadcast_log(f"\n[{datetime.datetime.now().strftime('%H:%M:%S')}] >>> 任务被用户中止。")
        else:
            status_str = "failed"
            broadcast_log(f"\n[{datetime.datetime.now().strftime('%H:%M:%S')}] >>> 任务执行失败，退出码: {return_code}")
            
        db.finish_sync_task(
            task_id, 
            status_str,
            items_parsed=task_stats["items_parsed"],
            strm_written=task_stats["strm_written"],
            files_removed=task_stats["files_removed"],
            dirs_removed=task_stats["dirs_removed"],
            metadata_synced=task_stats["metadata_synced"],
            elapsed_time=task_stats["elapsed_time"],
            log_file=log_file_name
        )
        
    except Exception as e:
        broadcast_log(f"执行异常: {str(e)}")
        db.finish_sync_task(task_id, "failed", log_file=log_file_name)
    finally:
        # 写入任务结束标记并关闭文件
        try:
            end_marker_msg = f"[{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] ==================== Task {task_id} End ====================\n"
            log_file.write(end_marker_msg)
            log_file.flush()
        except: pass
        log_file.close()
        
        current_process = None
        current_task_id = None
        # 清理临时 ini
        try:
            if os.path.exists(config_file):
                os.remove(config_file)
        except: pass
        
        # 每次任务结束后，在工作线程中自动触发旧日志清理以防撑爆硬盘
        cleanup_old_logs(max_days=7, max_total_size_mb=50.0)

# ----------------- 路由定义 -----------------

@app.post("/api/auth/login")
def login(req: LoginRequest):
    user = db.verify_user(req.username, req.password)
    if not user:
        raise HTTPException(status_code=400, detail="用户名或密码错误")
    
    payload = {
        "sub": user["username"],
        "exp": datetime.datetime.utcnow() + datetime.timedelta(minutes=TOKEN_EXPIRE_MINUTES)
    }
    token = jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)
    return {"token": token, "username": user["username"]}

@app.get("/api/auth/me")
def get_me(username: str = Depends(get_current_user)):
    return {"username": username}

@app.post("/api/auth/password")
def change_password(req: PasswordRequest, username: str = Depends(get_current_user)):
    success, msg = db.change_user_password(username, req.old_password, req.new_password)
    if not success:
        raise HTTPException(status_code=400, detail=msg)
    return {"message": msg}

# ----------------- 源管理 API -----------------

@app.get("/api/sources")
def list_sources(username: str = Depends(get_current_user)):
    return db.get_all_sources()

@app.post("/api/sources")
def create_source(req: SourceRequest, username: str = Depends(get_current_user)):
    success, msg = db.add_sync_source(req.name, req.gd_path, req.strm_path, req.remote_path, req.sync_metadata, req.drive_type)
    if not success:
        raise HTTPException(status_code=400, detail=msg)
    return {"message": msg}

@app.put("/api/sources/{source_id}")
def update_source(source_id: int, req: SourceRequest, username: str = Depends(get_current_user)):
    success, msg = db.update_sync_source(source_id, req.name, req.gd_path, req.strm_path, req.remote_path, req.sync_metadata, req.drive_type)
    if not success:
        raise HTTPException(status_code=400, detail=msg)
    return {"message": msg}

@app.delete("/api/sources/{source_id}")
def delete_source(source_id: int, username: str = Depends(get_current_user)):
    db.delete_sync_source(source_id)
    return {"message": "删除成功"}

@app.post("/api/sources/reorder")
def reorder_sources(req: ReorderRequest, username: str = Depends(get_current_user)):
    """批量对同步源进行重新排序，@author: hyq, @version: 2026-06-24"""
    success = db.update_sources_order(req.ordered_ids)
    if not success:
        raise HTTPException(status_code=400, detail="更新排序失败")
    return {"message": "更新排序成功"}

# ----------------- Rclone 接口 -----------------

# hyq: 2026-06-23 Modify get_system_directories to support dynamic root path check and add configuration API
# @app.get("/api/system/dirs")
# def get_system_directories(parent_path: str = "/mnt", username: str = Depends(get_current_user)):
#     """
#     安全地获取指定 parent_path 下的所有子文件夹。
#     限制只能访问以 /mnt 开头的路径以保护系统安全。
#     """
#     # 规范化路径
#     normalized_path = os.path.abspath(parent_path)
#     
#     # 校验安全性：在 Linux 容器内限制只能访问 /mnt 下的目录；本地 Windows 调试做兼容
#     is_allowed = False
#     if normalized_path.startswith("/mnt") or "mnt" in normalized_path.lower() or normalized_path.startswith("C:\\") or normalized_path.startswith("D:\\"):
#         is_allowed = True
#         
#     if not is_allowed:
#         raise HTTPException(status_code=403, detail="只允许读取 /mnt 及其子目录下的文件夹列表")
#         
#     if not os.path.exists(normalized_path):
#         return []
#         
#     try:
#         subdirs = []
#         for name in os.listdir(normalized_path):
#             full_path = os.path.join(normalized_path, name)
#             # 过滤隐藏文件夹和普通文件，只保留目录
#             if os.path.isdir(full_path) and not name.startswith("."):
#                 subdirs.append(name)
#         subdirs.sort()
#         return subdirs
#     except Exception as e:
#         print(f"[System] Error listing subdirectories: {e}")
#         return []

@app.get("/api/system/config-paths")
def get_system_config_paths(username: str = Depends(get_current_user)):
    """获取容器内配置的 GD 和 STRM 安全映射根路径"""
    return {
        "gd_root": os.environ.get("GD_ROOT", "/mnt"),
        "strm_root": os.environ.get("STRM_ROOT", "/mnt/strm")
    }

@app.get("/api/system/dirs")
def get_system_directories(parent_path: Optional[str] = None, username: str = Depends(get_current_user)):
    """
    安全地获取指定 parent_path 下的所有子文件夹。
    如果 parent_path 未指定，则默认使用环境变量 GD_ROOT 对应的值。
    """
    gd_root = os.environ.get("GD_ROOT", "/mnt")
    strm_root = os.environ.get("STRM_ROOT", "/mnt/strm")
    
    if not parent_path:
        parent_path = gd_root
        
    # 规范化路径
    normalized_path = os.path.abspath(parent_path)
    gd_root_abs = os.path.abspath(gd_root)
    strm_root_abs = os.path.abspath(strm_root)
    
    # 校验安全性：只允许访问配置的安全根路径及其子目录
    is_allowed = False
    if normalized_path.startswith(gd_root_abs) or normalized_path.startswith(strm_root_abs):
        is_allowed = True
    # 兼容 Windows 本地开发环境调试
    if normalized_path.startswith("C:\\") or normalized_path.startswith("D:\\"):
        is_allowed = True
        
    if not is_allowed:
        raise HTTPException(status_code=403, detail="无权读取该路径下的文件夹列表")
        
    if not os.path.exists(normalized_path):
        return []
        
    try:
        subdirs = []
        for name in os.listdir(normalized_path):
            full_path = os.path.join(normalized_path, name)
            # 过滤隐藏文件夹和普通文件，只保留目录
            if os.path.isdir(full_path) and not name.startswith("."):
                subdirs.append(name)
        subdirs.sort()
        return subdirs
    except Exception as e:
        print(f"[System] Error listing subdirectories: {e}")
        return []

@app.get("/api/rclone/remotes")
def get_rclone_remotes(username: str = Depends(get_current_user)):
    """获取所有已配置的 rclone remotes"""
    try:
        proc = subprocess.run(
            ["rclone", "listremotes"],
            capture_output=True,
            text=True,
            timeout=5
        )
        if proc.returncode != 0:
            return []
        
        remotes = []
        for line in proc.stdout.strip().split("\n"):
            clean_line = line.strip()
            if clean_line:
                remotes.append(clean_line)
        return remotes
    except Exception as e:
        print(f"[Rclone] Error listing remotes: {e}")
        return []

@app.post("/api/rclone/test")
def test_rclone_connection(path: str, username: str = Depends(get_current_user)):
    """测试指定的 rclone 目录是否能正常访问"""
    if not path or not path.strip():
        raise HTTPException(status_code=400, detail="测试路径不能为空")
        
    try:
        proc = subprocess.run(
            ["rclone", "lsf", "--max-depth", "1", path.strip()],
            capture_output=True,
            text=True,
            timeout=8
        )
        if proc.returncode != 0:
            err_msg = proc.stderr.strip() or f"rclone 退出码: {proc.returncode}"
            raise HTTPException(status_code=400, detail=f"连接测试失败: {err_msg}")
            
        files = []
        for line in proc.stdout.strip().split("\n"):
            clean_line = line.strip()
            if clean_line:
                files.append(clean_line)
            if len(files) >= 5:
                break
                
        return {
            "success": True,
            "message": "连接测试成功！已成功读取目录。",
            "preview": files
        }
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=408, detail="连接测试超时，请检查网盘配置或网络连接。")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"系统错误: {str(e)}")

# ----------------- 系统配置 API -----------------

#     return {
#         "worker_concurrency": int(cfg.get("WORKER_CONCURRENCY", 16)),
#         "batch_write_size": int(cfg.get("BATCH_WRITE_SIZE", 1000)),
#         "source_concurrency": int(cfg.get("SOURCE_CONCURRENCY", 5)),
#         "cron_expression": cfg.get("CRON_EXPRESSION", "0 3 * * *")
#     }

@app.get("/api/settings")
def get_settings(username: str = Depends(get_current_user)):
    cfg = db.get_all_global_configs()
    return {
        "worker_concurrency": int(cfg.get("WORKER_CONCURRENCY", 16)),
        "batch_write_size": int(cfg.get("BATCH_WRITE_SIZE", 1000)),
        "source_concurrency": int(cfg.get("SOURCE_CONCURRENCY", 5)),
        "cron_expression": cfg.get("CRON_EXPRESSION", ""),
        "metadata_types": cfg.get("METADATA_TYPES", "nfo,jpg,jpeg,png,svg,ass,srt,sup,mp3,flac,wav,aac")
    }

@app.post("/api/settings")
def update_settings(req: SettingsRequest, username: str = Depends(get_current_user)):
    # hyq: 2026-06-23 Modify cron validation to allow empty string (disabling scheduler)
    # try:
    #     CronTrigger.from_crontab(req.cron_expression)
    # except Exception:
    #     raise HTTPException(status_code=400, detail="Cron 表达式格式无效")
    
    if req.cron_expression and req.cron_expression.strip():
        try:
            CronTrigger.from_crontab(req.cron_expression)
        except Exception:
            raise HTTPException(status_code=400, detail="Cron 表达式格式无效")

    configs = {
        "WORKER_CONCURRENCY": str(req.worker_concurrency),
        "BATCH_WRITE_SIZE": str(req.batch_write_size),
        "SOURCE_CONCURRENCY": str(req.source_concurrency),
        "CRON_EXPRESSION": req.cron_expression,
        "METADATA_TYPES": req.metadata_types
    }
    db.update_global_configs(configs)
    
    # 重新配置 APScheduler
    setup_cron_job(req.cron_expression)
    
    return {"message": "配置更新成功"}

# ----------------- 任务同步执行 API -----------------

# hyq: 2026-06-23 Modify run_task to support single source syncing
# @app.post("/api/tasks/run")
# def run_task(force: bool = False, username: str = Depends(get_current_user)):
#     global current_process, current_task_id, task_thread
#     
#     if current_process is not None:
#         raise HTTPException(status_code=400, detail="当前已有同步任务正在运行中")
#         
#     # 生成配置并启动
#     try:
#         config_file = generate_ini_config()
#     except Exception as e:
#         raise HTTPException(status_code=500, detail=f"生成配置文件失败: {str(e)}")
#         
#     task_id = db.create_sync_task("manual", force)
#     current_task_id = task_id
#     
#     task_thread = threading.Thread(target=run_sync_process, args=(task_id, config_file, force))
#     task_thread.daemon = True
#     task_thread.start()
#     
#     return {"task_id": task_id, "status": "running"}

@app.post("/api/tasks/run")
def run_task(force: bool = False, source_id: Optional[int] = None, username: str = Depends(get_current_user)):
    global current_process, current_task_id, task_thread
    
    if current_process is not None:
        raise HTTPException(status_code=400, detail="当前已有同步任务正在运行中")
        
    # 生成配置并启动
    try:
        config_file = generate_ini_config(source_id)
    except HTTPException as he:
        raise he
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"生成配置文件失败: {str(e)}")
        
    task_id = db.create_sync_task("manual", force)
    current_task_id = task_id
    
    task_thread = threading.Thread(target=run_sync_process, args=(task_id, config_file, force))
    task_thread.daemon = True
    task_thread.start()
    
    return {"task_id": task_id, "status": "running"}

@app.post("/api/tasks/stop")
def stop_task(username: str = Depends(get_current_user)):
    global current_process
    if current_process is None:
        raise HTTPException(status_code=400, detail="没有运行中的任务")
        
    # 终止子进程
    try:
        # 在 Windows 上可以使用 terminate，在 Linux 上也可以
        current_process.terminate()
        return {"message": "终止指令已发送"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"终止任务失败: {str(e)}")

@app.get("/api/tasks/status")
def get_task_status(username: str = Depends(get_current_user)):
    running = current_process is not None
    history = db.get_sync_tasks(15)
    return {
        "running": running,
        "current_task_id": current_task_id,
        "stats": task_stats if running else None,
        "history": history
    }

@app.get("/api/tasks/logs/stream")
def stream_logs(token: Optional[str] = None):
    # SSE 日志推送接口。由于 EventSource 在原生 JS 中无法方便加 Header，可以通过 URL 参数传 token
    if not token:
         raise HTTPException(status_code=401, detail="未授权访问")
    try:
        jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="凭证无效")

    def event_generator():
        q = queue.Queue()
        log_listeners.append(q)
        
        # 首先将缓存的最新日志全部推给这个新连接的客户端
        for old_line in latest_logs:
            yield f"data: {old_line}\n\n"
            
        try:
            while True:
                # 阻塞直到有新日志写入
                line = q.get()
                yield f"data: {line}\n\n"
        except GeneratorExit:
            pass
        finally:
            if q in log_listeners:
                log_listeners.remove(q)

    return StreamingResponse(event_generator(), media_type="text/event-stream")

# hyq: 2026-06-23 Modify download_log and get_task_log_text to fetch logs from daily merged files and filter logs by task ID
# @app.get("/api/tasks/logs/download/{task_id}")
# def download_log(task_id: int, username: str = Depends(get_current_user)):
#     log_file_name = f"task_{task_id}.log"
#     log_file_path = os.path.join(LOGS_DIR, log_file_name)
#     if not os.path.exists(log_file_path):
#         raise HTTPException(status_code=404, detail="日志文件不存在")
#     return FileResponse(log_file_path, filename=log_file_name, media_type="text/plain")
# 
# @app.get("/api/tasks/logs/text/{task_id}")
# def get_task_log_text(task_id: int, username: str = Depends(get_current_user)):
#     """获取指定任务的全部日志文本行，用于控制台回显"""
#     log_file_name = f"task_{task_id}.log"
#     log_file_path = os.path.join(LOGS_DIR, log_file_name)
#     
#     # 若此任务正是当前运行中的任务，则直接返回内存里的最新日志
#     global current_task_id
#     if current_task_id == task_id:
#         return {"logs": list(latest_logs)}
#         
#     if not os.path.exists(log_file_path):
#         return {"logs": []}
#         
#     try:
#         with open(log_file_path, "r", encoding="utf-8") as f:
#             lines = [line.rstrip("\n") for line in f.readlines()]
#         return {"logs": lines}
#     except Exception as e:
#         raise HTTPException(status_code=500, detail=f"读取日志失败: {str(e)}")

@app.get("/api/tasks/logs/download/{task_id}")
def download_log(task_id: int, username: str = Depends(get_current_user)):
    task = db.get_sync_task_by_id(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    log_file_name = task.get("log_file")
    if not log_file_name:
        raise HTTPException(status_code=404, detail="此任务没有关联的日志文件")
        
    log_file_path = os.path.join(LOGS_DIR, log_file_name)
    if not os.path.exists(log_file_path):
        raise HTTPException(status_code=404, detail="日志文件不存在或已被自动清理")
    return FileResponse(log_file_path, filename=log_file_name, media_type="text/plain")

@app.get("/api/tasks/logs/text/{task_id}")
def get_task_log_text(task_id: int, username: str = Depends(get_current_user)):
    """获取指定任务的日志文本行，支持从按天归并的文件中高精度筛选出该任务范围内的行"""
    # 若此任务正是当前运行中的任务，则直接返回内存里的最新日志
    global current_task_id
    if current_task_id == task_id:
        return {"logs": list(latest_logs)}
        
    task = db.get_sync_task_by_id(task_id)
    if not task:
        return {"logs": ["未找到指定任务信息"]}
    log_file_name = task.get("log_file")
    if not log_file_name:
        return {"logs": ["该任务无可用日志文件名"]}
        
    log_file_path = os.path.join(LOGS_DIR, log_file_name)
    if not os.path.exists(log_file_path):
        return {"logs": ["该日志文件已被自动清理或不存在"]}
        
    try:
        extracted = extract_task_logs(log_file_path, task_id)
        return {"logs": extracted}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"读取日志失败: {str(e)}")

# ----------------- 页面路由 -----------------

@app.get("/")
def read_index():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))

@app.get("/login")
def read_login():
    return FileResponse(os.path.join(STATIC_DIR, "login.html"))

# ----------------- 定时任务管理 -----------------

def run_scheduled_sync():
    """定时任务触发的逻辑"""
    global current_process, current_task_id, task_thread
    
    # 如果当前有手动任务正在执行，定时任务将跳过，避免冲突
    if current_process is not None:
        print("[Cron] Existing sync task is running. Cron skip.")
        return
        
    try:
        config_file = generate_ini_config()
    except Exception as e:
        print(f"[Cron] Error generating config: {e}")
        return
        
    task_id = db.create_sync_task("cron", False)
    current_task_id = task_id
    
    # 启动后台线程执行进程
    task_thread = threading.Thread(target=run_sync_process, args=(task_id, config_file, False))
    task_thread.daemon = True
    task_thread.start()

def setup_cron_job(cron_exp: str):
    """设置或重置 Cron 定时同步"""
    # 移除已有的定时任务
    for job in scheduler.get_jobs():
        job.remove()
        
    if cron_exp and cron_exp.strip():
        try:
            trigger = CronTrigger.from_crontab(cron_exp)
            scheduler.add_job(
                run_scheduled_sync,
                trigger,
                id="cron_sync_job",
                name="Cron strm sync"
            )
            print(f"[Scheduler] Successfully configured cron job: {cron_exp}")
        except Exception as e:
            print(f"[Scheduler] Error configuring cron job: {e}")

# hyq: 2026-06-23 Modify cron task startup initialization default to empty string
# try:
#     configs = db.get_all_global_configs()
#     setup_cron_job(configs.get("CRON_EXPRESSION", "0 3 * * *"))
# except Exception as e:
#     print(f"[Startup] Error loading default cron job: {e}")

try:
    configs = db.get_all_global_configs()
    setup_cron_job(configs.get("CRON_EXPRESSION", ""))
except Exception as e:
    print(f"[Startup] Error loading default cron job: {e}")

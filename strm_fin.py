#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
最终版同步脚本 (并发优化版)
- 多源并行：支持同时处理多个 Source，不再串行等待
- Rclone 参数精简：--recursive --fast-list --files-only
- 修复权限 bug：确保自动创建的父级、祖父级目录都归属为 emby
- 过滤逻辑：只为 MimeType 为 video/* 或常见视频后缀的文件生成 .strm
- 清理逻辑：自动删除垃圾、无效 strm 及孤儿目录
"""
import os, time, subprocess, json, argparse
import ijson
import concurrent.futures
import pwd
import shutil
from configparser import ConfigParser
from colorama import Fore, Style, init

# 初始化 colorama
init(autoreset=True)

# --- 配置部分 ---
# 默认配置（如果配置文件中没有指定，则使用这些默认值）
WORKER_CONCURRENCY = 32
SOURCE_CONCURRENCY = 5
BATCH_WRITE_SIZE = 1000
CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cache")

# 配置文件路径
DEFAULT_CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "strm_config.ini")

# 定义系统垃圾文件
JUNK_FILES = {'.ds_store', 'thumbs.db', 'desktop.ini', '._*'}

# 定义常用的视频后缀白名单
VIDEO_EXTS = {
    '.mkv', '.mp4', '.avi', '.mov', '.wmv', '.flv', '.webm', '.m4v',
    '.mpg', '.mpeg', '.m2ts', '.ts', '.iso', '.dat', '.vob', '.rmvb',
    '.3gp', '.asf', '.divx'
}

# ---------------------------------------------------------
# 获取 emby 用户的 UID
# ---------------------------------------------------------
# hyq: 2026-06-23 Modify EMBY_UID and EMBY_GID resolution to support docker environment variables
# try:
#     EMBY_UID = pwd.getpwnam("emby").pw_uid
# except KeyError:
#     # print(Fore.RED + "[WARNING] User 'emby' not found. Files will be owned by current user.") 
#     # 多线程打印警告可能会乱，这里暂时静默或者在 main 开头打印
#     EMBY_UID = None
EMBY_UID = None
EMBY_GID = None
try:
    emby_passwd = pwd.getpwnam("emby")
    EMBY_UID = emby_passwd.pw_uid
    EMBY_GID = emby_passwd.pw_gid
except KeyError:
    # 尝试从环境变量读取
    env_uid = os.environ.get("EMBY_UID")
    env_gid = os.environ.get("EMBY_GID")
    if env_uid:
        try:
            EMBY_UID = int(env_uid)
        except ValueError:
            pass
    if env_gid:
        try:
            EMBY_GID = int(env_gid)
        except ValueError:
            pass

# ---------------------------------------------------------
# 权限修改辅助函数
# ---------------------------------------------------------
# hyq: 2026-06-23 Modify change_owner and ensure_path_permissions to support environmental UID/GID overrides
# def change_owner(path):
#     """
#     修改 path 的所有者为 emby，组保持不变 (-1)
#     """
#     if EMBY_UID is not None and os.path.exists(path):
#         try:
#             current_stat = os.stat(path)
#             if current_stat.st_uid != EMBY_UID:
#                 os.chown(path, EMBY_UID, -1)
#         except Exception:
#             pass
# 
# def ensure_path_permissions(target_dir, root_stop_dir):
#     """
#     从 target_dir 开始向上追溯，直到 root_stop_dir (不包含)，
#     将沿途所有目录的权限修改为 emby。
#     """
#     if EMBY_UID is None:
#         return
# 
#     curr = os.path.abspath(target_dir)
#     root = os.path.abspath(root_stop_dir)
# 
#     while curr.startswith(root) and curr != root:
#         if os.path.exists(curr):
#             change_owner(curr)
#         
#         parent = os.path.dirname(curr)
#         if parent == curr: 
#             break
#         curr = parent

# hyq: 2026-06-23 Modify change_owner and ensure_path_permissions to accept custom uid/gid for dynamic inheritance
# def change_owner(path):
#     """
#     修改 path 的所有者和组所有权，解决容器内找不到 emby 用户引起的权限问题
#     """
#     if not os.path.exists(path):
#         return
#         
#     target_uid = EMBY_UID if EMBY_UID is not None else -1
#     target_gid = EMBY_GID if EMBY_GID is not None else -1
#     
#     if target_uid == -1 and target_gid == -1:
#         return
#         
#     try:
#         current_stat = os.stat(path)
#         need_chown = False
#         if target_uid != -1 and current_stat.st_uid != target_uid:
#             need_chown = True
#         if target_gid != -1 and current_stat.st_gid != target_gid:
#             need_chown = True
#             
#         if need_chown:
#             os.chown(path, target_uid, target_gid)
#     except Exception:
#         pass
# 
# def ensure_path_permissions(target_dir, root_stop_dir):
#     """
#     从 target_dir 开始向上追溯，直到 root_stop_dir (不包含)，
#     将沿途所有目录的权限进行修改。
#     """
#     if EMBY_UID is None and EMBY_GID is None:
#         return
# 
#     curr = os.path.abspath(target_dir)
#     root = os.path.abspath(root_stop_dir)
# 
#     while curr.startswith(root) and curr != root:
#         if os.path.exists(curr):
#             change_owner(curr)
#         
#         parent = os.path.dirname(curr)
#         if parent == curr: 
#             break
#         curr = parent

def detect_target_owner(strm_root):
    """
    自动向上寻找最近的已存在父目录，获取其 UID/GID。
    这样新生成的 strm 文件及层级目录将自动继承本地挂载根目录的权限所有者，实现零配置自适应。
    """
    # 优先采用环境变量指定的 UID/GID 强制覆盖
    env_uid = os.environ.get("EMBY_UID")
    env_gid = os.environ.get("EMBY_GID")
    
    target_uid = None
    target_gid = None
    
    if env_uid:
        try:
            target_uid = int(env_uid)
        except ValueError: pass
    if env_gid:
        try:
            target_gid = int(env_gid)
        except ValueError: pass
        
    if target_uid is not None or target_gid is not None:
        return target_uid, target_gid
        
    # 如果容器内本身就存在 emby 用户，且没有设置环境变量，我们也可以作为备用探测
    fallback_uid = EMBY_UID
    fallback_gid = EMBY_GID
        
    # 向上追溯寻找已存在的目录以继承其 UID/GID
    curr = os.path.abspath(strm_root)
    while True:
        if os.path.exists(curr):
            try:
                st = os.stat(curr)
                return st.st_uid, st.st_gid
            except Exception:
                break
        parent = os.path.dirname(curr)
        if parent == curr:
            break
        curr = parent
        
    return fallback_uid, fallback_gid

def change_owner(path, uid=None, gid=None):
    """
    修改 path 的所有者和组所有权，支持参数传入以实现权限继承
    """
    if not os.path.exists(path):
        return
        
    target_uid = uid if uid is not None else (EMBY_UID if EMBY_UID is not None else -1)
    target_gid = gid if gid is not None else (EMBY_GID if EMBY_GID is not None else -1)
    
    if target_uid == -1 and target_gid == -1:
        return
        
    try:
        current_stat = os.stat(path)
        need_chown = False
        if target_uid != -1 and current_stat.st_uid != target_uid:
            need_chown = True
        if target_gid != -1 and current_stat.st_gid != target_gid:
            need_chown = True
            
        if need_chown:
            os.chown(path, target_uid, target_gid)
    except Exception:
        pass

def ensure_path_permissions(target_dir, root_stop_dir, uid=None, gid=None):
    """
    从 target_dir 开始向上追溯，直到 root_stop_dir (不包含)，
    将沿途所有目录的权限修改为指定的 uid/gid 以实现继承。
    """
    target_uid = uid if uid is not None else EMBY_UID
    target_gid = gid if gid is not None else EMBY_GID
    
    if target_uid is None and target_gid is None:
        return

    curr = os.path.abspath(target_dir)
    root = os.path.abspath(root_stop_dir)

    while curr.startswith(root) and curr != root:
        if os.path.exists(curr):
            change_owner(curr, target_uid, target_gid)
        
        parent = os.path.dirname(curr)
        if parent == curr: 
            break
        curr = parent

# ---------------------------------------------------------
# 获取数据源
# ---------------------------------------------------------
def get_source_data(source_name, remote_path, force_update):
    if not os.path.exists(CACHE_DIR):
        try:
            os.makedirs(CACHE_DIR, exist_ok=True)
            change_owner(CACHE_DIR)
        except FileExistsError:
            pass
    
    # 每个源拥有独立的缓存文件，使用直观的名称
    cache_file = os.path.join(CACHE_DIR, f"{source_name}.json")
    
    if not force_update and os.path.exists(cache_file):
        print(Fore.BLUE + f"[{source_name}] Cache hit: {cache_file}")
        return open(cache_file, "r", encoding="utf-8"), 0.0

    cmd = [
        "rclone", "lsjson", remote_path,
        "--recursive",
        "--fast-list",
        "--files-only"
    ]
    
    print(Fore.YELLOW + f"[{source_name}] Rclone Executing: {remote_path}")

    t0 = time.time()
    # capture_output=True 会在内存缓存输出，对于巨大列表可能耗内存，但多源并发一般足以应付
    proc = subprocess.run(cmd, capture_output=True, text=True)
    elapsed = time.time() - t0

    if proc.returncode != 0:
        print(Fore.RED + f"[{source_name}] ERROR: rclone failed ({elapsed:.3f}s)")
        print(Fore.RED + proc.stderr.strip())
        return None, elapsed

    try:
        with open(cache_file, "w", encoding="utf-8") as f:
            f.write(proc.stdout)
        change_owner(cache_file)
        print(Fore.GREEN + f"[{source_name}] Rclone finished in {elapsed:.3f}s")
    except Exception as e:
        print(Fore.RED + f"[{source_name}] ERROR: Failed to write cache: {e}")
        return None, elapsed

    return open(cache_file, "r", encoding="utf-8"), elapsed


# ---------------------------------------------------------
# 写入与权限处理
# ---------------------------------------------------------
# hyq: 2026-06-23 Modify write_strm and write_strm_batch to accept uid/gid parameter for ownership inheritance
# def write_strm(dst, content, root_dir):
#     parent = os.path.dirname(dst)
#     
#     if parent and not os.path.exists(parent):
#         try:
#             os.makedirs(parent, exist_ok=True)
#             ensure_path_permissions(parent, root_dir)
#         except FileExistsError:
#             pass
# 
#     if os.path.exists(dst):
#         return False
# 
#     try:
#         with open(dst, "w", encoding="utf-8") as f:
#             f.write(content)
#         change_owner(dst)
#         return True
#     except Exception:
#         return False
# 
# def write_strm_batch(batch, root_dir):
#     cnt = 0
#     for dst, content in batch:
#         if write_strm(dst, content, root_dir):
#             cnt += 1
#     return cnt

def write_strm(dst, content, root_dir, uid, gid):
    parent = os.path.dirname(dst)
    
    if parent and not os.path.exists(parent):
        try:
            os.makedirs(parent, exist_ok=True)
            ensure_path_permissions(parent, root_dir, uid, gid)
        except FileExistsError:
            pass

    if os.path.exists(dst):
        return False

    try:
        with open(dst, "w", encoding="utf-8") as f:
            f.write(content)
        change_owner(dst, uid, gid)
        return True
    except Exception:
        return False

def write_strm_batch(batch, root_dir, uid, gid):
    cnt = 0
    for dst, content in batch:
        if write_strm(dst, content, root_dir, uid, gid):
            cnt += 1
    return cnt


# ---------------------------------------------------------
# 清理逻辑
# ---------------------------------------------------------
def clean_up(strm_root, valid_strms, source_idx):
    removed_files = 0
    removed_dirs = 0

    if not os.path.isdir(strm_root):
        return removed_files, removed_dirs

    # topdown=False 核心：先处理最底层的子目录
    for root, dirs, files in os.walk(strm_root, topdown=False):
        has_valid_strm = False
        
        # 1. 扫描文件
        for fn in files:
            full_path = os.path.join(root, fn)
            lower_fn = fn.lower()

            if lower_fn in JUNK_FILES or fn.startswith("._"):
                try:
                    os.remove(full_path)
                except OSError: pass
                continue

            if fn.endswith(".strm"):
                if full_path in valid_strms:
                    has_valid_strm = True
                else:
                    try:
                        os.remove(full_path)
                        removed_files += 1
                        # 日志过多可注释
                        # print(Fore.YELLOW + f"[Source {source_idx}] Deleted invalid strm: {full_path}")
                    except OSError: pass
        
        # 2. 目录决策
        try:
            remaining_items = os.listdir(root)
        except FileNotFoundError:
            continue

        if not remaining_items:
            try:
                os.rmdir(root)
                removed_dirs += 1
            except OSError: pass
            
        elif not has_valid_strm:
            # 只有当目录下没有子目录时，才敢断定这是个纯元数据孤儿目录
            has_subdirs = any(os.path.isdir(os.path.join(root, item)) for item in remaining_items)
            
            if not has_subdirs:
                try:
                    shutil.rmtree(root)
                    removed_dirs += 1
                    print(Fore.YELLOW + f"[Source {source_idx}] Deleted orphan dir: {root}")
                except Exception as e:
                    print(Fore.RED + f"[Source {source_idx}] Error removing dir {root}: {e}")

    return removed_files, removed_dirs


# ---------------------------------------------------------
# 处理单个源 (封装后的任务函数)
# ---------------------------------------------------------
def process_one_source_task(source_config, force_update):
    """
    线程池调用的入口函数
    """
    name = source_config['name']
    gd_root = source_config['gd']
    strm_root = source_config['strm']
    remote_path = source_config['remote_path']

    # 1. 获取数据 (Rclone)
    file_handle, rclone_elapsed = get_source_data(name, remote_path, force_update)
    if not file_handle:
        return 0, 0, 0, 0, rclone_elapsed

    # 自动探测或从环境变量获取此源的目标所有者 UID/GID 继承设置
    target_uid, target_gid = detect_target_owner(strm_root)
    if target_uid is not None or target_gid is not None:
        print(Fore.BLUE + f"[{name}] Ownership auto-inherited -> UID: {target_uid}, GID: {target_gid}")

    t0 = time.time()
    
    # 2. 解析 JSON
    parse_start = time.time()
    items = []
    try:
        # ijson 在处理大文件时比 json.load 更省内存
        for obj in ijson.items(file_handle, "item"):
            if obj.get("IsDir"):
                continue

            mime = obj.get("MimeType", "").lower()
            fname = obj.get("Name", "")
            ext = os.path.splitext(fname)[1].lower()

            is_video = False
            if mime.startswith("video/"):
                is_video = True
            elif ext in VIDEO_EXTS:
                is_video = True
            
            if not is_video:
                continue

            items.append(obj)
    except Exception as e:
        print(Fore.RED + f"[{name}] ERROR: JSON parse failed: {e}")
        file_handle.close()
        return 0, 0, 0, 0, rclone_elapsed

    file_handle.close()
    parse_time = time.time() - parse_start
    print(Fore.CYAN + f"[{name}] Parsed {len(items)} items ({parse_time:.2f}s)")

    # 3. 扫描现有文件
    existing = set()
    if os.path.isdir(strm_root):
        for root, dirs, files in os.walk(strm_root):
            for fn in files:
                if fn.endswith(".strm"):
                    existing.add(os.path.join(root, fn))

    # 4. 计算差异
    need_write = []
    valid = set()

    for it in items:
        path = it["Path"]
        fname = os.path.basename(path)
        name_no_ext = os.path.splitext(fname)[0]

        dirpart = os.path.dirname(path)
        rel_dst = os.path.join(dirpart, name_no_ext + ".strm") if dirpart else name_no_ext + ".strm"

        dst = os.path.join(strm_root, rel_dst)
        content = os.path.join(gd_root, path)

        valid.add(dst)

        if dst not in existing:
            need_write.append((dst, content))

    # 5. 批量写入 (内部再开线程池)
    # 预创建目录 (主线程做，减少竞争)
    for dst, _ in need_write:
        parent = os.path.dirname(dst)
        if parent and not os.path.exists(parent):
            try:
                os.makedirs(parent, exist_ok=True)
                ensure_path_permissions(parent, strm_root, target_uid, target_gid)
            except: pass

    written = 0
    if need_write:
        # 注意：这里是嵌套线程池，但因为是IO密集型，通常问题不大
        with concurrent.futures.ThreadPoolExecutor(max_workers=WORKER_CONCURRENCY) as exe:
            futures = []
            for i in range(0, len(need_write), BATCH_WRITE_SIZE):
                futures.append(exe.submit(write_strm_batch, need_write[i:i+BATCH_WRITE_SIZE], strm_root, target_uid, target_gid))
            for f in concurrent.futures.as_completed(futures):
                written += f.result()

    # 6. 清理
    removed_files, removed_dirs = clean_up(strm_root, valid, name)
    
    processing_time = time.time() - t0
    total_time = processing_time + rclone_elapsed
    
    print(Fore.MAGENTA + f"[{name}] DONE. Wrote: {written}, Removed: {removed_files} files / {removed_dirs} dirs. Total: {total_time:.2f}s")
    
    return len(items), written, removed_files, removed_dirs, total_time


# ---------------------------------------------------------
# 主程序
# ---------------------------------------------------------
def load_config(config_file):
    """
    从 INI 配置文件加载配置
    """
    global WORKER_CONCURRENCY, SOURCE_CONCURRENCY, BATCH_WRITE_SIZE
    
    config = ConfigParser()
    
    if not os.path.exists(config_file):
        print(Fore.RED + f"[ERROR] Config file not found: {config_file}")
        return []
    
    config.read(config_file, encoding='utf-8')
    
    # 读取全局配置
    if 'global' in config:
        WORKER_CONCURRENCY = config.getint('global', 'WORKER_CONCURRENCY', fallback=WORKER_CONCURRENCY)
        SOURCE_CONCURRENCY = config.getint('global', 'SOURCE_CONCURRENCY', fallback=SOURCE_CONCURRENCY)
        BATCH_WRITE_SIZE = config.getint('global', 'BATCH_WRITE_SIZE', fallback=BATCH_WRITE_SIZE)
    
    # 读取源配置
    sources = []
    for section in config.sections():
        if section == 'global':
            continue
        
        if config.has_option(section, 'SOURCE_GD') and \
           config.has_option(section, 'SOURCE_STRM') and \
           config.has_option(section, 'SOURCE_CMD'):
            sources.append({
                "name": section,
                "gd": config.get(section, 'SOURCE_GD'),
                "strm": config.get(section, 'SOURCE_STRM'),
                "remote_path": config.get(section, 'SOURCE_CMD')
            })
        else:
            print(Fore.YELLOW + f"[WARNING] Incomplete config for section: [{section}]")
    
    return sources


def main():
    parser = argparse.ArgumentParser(description="Generate .strm files from rclone sources with caching (Parallel).")
    parser.add_argument("--force", action="store_true", help="Force update caches (re-run rclone)")
    parser.add_argument("--config", default=DEFAULT_CONFIG_FILE, help="Path to config file (default: strm_config.ini)")
    args = parser.parse_args()

    # hyq: 2026-06-23 Modify emby user feedback in main to support customized UID/GID override
    # if EMBY_UID:
    #     print(Fore.BLUE + f"Running as root. New files/dirs will be owned by user 'emby' (UID: {EMBY_UID}).")
    # else:
    #     print(Fore.RED + "[WARNING] User 'emby' not found.")
    if EMBY_UID is not None or EMBY_GID is not None:
        uid_str = str(EMBY_UID) if EMBY_UID is not None else "keep current"
        gid_str = str(EMBY_GID) if EMBY_GID is not None else "keep current"
        print(Fore.BLUE + f"Running. New files/dirs ownership will be set to UID: {uid_str}, GID: {gid_str}.")
    else:
        print(Fore.RED + "[WARNING] User 'emby' not found, and no EMBY_UID/EMBY_GID environment variables specified. Owner permissions will keep default.")
    
    # 加载配置
    sources = load_config(args.config)
    if not sources:
        print(Fore.RED + f"[ERROR] No valid sources found in config file: {args.config}")
        return

    print(Fore.WHITE + f"Starting Sync. Sources: {len(sources)}, Concurrency: {SOURCE_CONCURRENCY}, Force Update: {args.force}")

    total_parsed = 0
    total_written = 0
    total_removed_files = 0
    total_removed_dirs = 0
    total_time_sum = 0
    
    start_all = time.time()

    # 使用 ThreadPoolExecutor 实现源级别的并发
    with concurrent.futures.ThreadPoolExecutor(max_workers=SOURCE_CONCURRENCY) as executor:
        # 提交所有任务
        future_to_source = {
            executor.submit(process_one_source_task, s, args.force): s 
            for s in sources
        }

        for future in concurrent.futures.as_completed(future_to_source):
            s = future_to_source[future]
            try:
                # 获取结果
                p, w, rf, rd, t = future.result()
                total_parsed += p
                total_written += w
                total_removed_files += rf
                total_removed_dirs += rd
                total_time_sum += t
            except Exception as exc:
                print(Fore.RED + f"[{s['name']}] Generated an exception: {exc}")

    wall_time = time.time() - start_all

    print(Fore.GREEN + "\n" + "="*50)
    print(Fore.GREEN + f"[Summary] ALL SOURCES PROCESSED")
    print(Fore.GREEN + f"  - Wall Time:     {wall_time:.3f}s")
    print(Fore.GREEN + f"  - Items Parsed:  {total_parsed}")
    print(Fore.GREEN + f"  - Strm Written:  {total_written}")
    print(Fore.GREEN + f"  - Files Removed: {total_removed_files}")
    print(Fore.GREEN + f"  - Dirs Removed:  {total_removed_dirs}")
    print(Fore.GREEN + "="*50)


if __name__ == "__main__":
    main()


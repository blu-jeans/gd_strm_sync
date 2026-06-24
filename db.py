# -*- coding: utf-8 -*-
"""
strm 同步控制面板数据库管理模块
使用 SQLite 实现轻量存储，并提供系统初试化与 CRUD 函数。
@author: hyq
@version: 2026-06-23
"""
import os
import sqlite3
import datetime
import hashlib

# hyq: 2026-06-23 Modify DB_PATH to keep strm_sync.db inside persistent cache directory, preventing container reset data loss
# # 默认数据库路径
# DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "strm_sync.db")

_base_dir = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(_base_dir, "cache", "strm_sync.db")

# 确保 cache 目录已存在，修复 unable to open database 报错
os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

# 迁移旧数据库文件的平滑防灾设计
_old_db_path = os.path.join(_base_dir, "strm_sync.db")
if os.path.exists(_old_db_path) and not os.path.exists(DB_PATH):
    try:
        import shutil
        shutil.move(_old_db_path, DB_PATH)
    except Exception:
        pass

# 尝试导入 bcrypt，如果不存在则使用 hashlib SHA256 降级，提高兼容性
try:
    import bcrypt
    HAS_BCRYPT = True
except ImportError:
    HAS_BCRYPT = False

def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def hash_password(password: str) -> str:
    """加密密码"""
    if HAS_BCRYPT:
        salt = bcrypt.gensalt()
        hashed = bcrypt.hashpw(password.encode('utf-8'), salt)
        return hashed.decode('utf-8')
    else:
        # 降级方案：使用 SHA256 加固定盐
        salt = "strm_sync_salt_2026"
        return hashlib.sha256((password + salt).encode('utf-8')).hexdigest()

def check_password(password: str, hashed: str) -> bool:
    """验证密码"""
    if HAS_BCRYPT:
        try:
            return bcrypt.checkpw(password.encode('utf-8'), hashed.encode('utf-8'))
        except Exception:
            return False
    else:
        salt = "strm_sync_salt_2026"
        expected = hashlib.sha256((password + salt).encode('utf-8')).hexdigest()
        return expected == hashed

def init_db():
    """初始化数据库表并写入默认数据"""
    conn = get_db_connection()
    cursor = conn.cursor()

    # 1. 创建用户表
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)

    # 2. 创建全局配置表
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS global_configs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        config_key TEXT UNIQUE NOT NULL,
        config_value TEXT NOT NULL
    );
    """)

    # hyq: 2026-06-24 Modify sync_sources table to add sort_order support
    # # 3. 创建同步源配置表
    # cursor.execute("""
    # CREATE TABLE IF NOT EXISTS sync_sources (
    # 3. 创建同步源配置表 (带 sort_order 与 drive_type 字段支持)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS sync_sources (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE NOT NULL,
        gd_path TEXT NOT NULL,
        strm_path TEXT NOT NULL,
        remote_path TEXT NOT NULL,
        sync_metadata INTEGER DEFAULT 1,
        sort_order INTEGER DEFAULT 0,
        drive_type TEXT DEFAULT 'GoogleDrive',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)

    # 兼容性升级：添加 sync_metadata 字段
    try:
        cursor.execute("ALTER TABLE sync_sources ADD COLUMN sync_metadata INTEGER DEFAULT 1")
        conn.commit()
    except sqlite3.OperationalError:
        pass

    # 兼容性升级：添加 sort_order 字段以实现拖动排序与置顶功能
    try:
        cursor.execute("ALTER TABLE sync_sources ADD COLUMN sort_order INTEGER DEFAULT 0")
        conn.commit()
    except sqlite3.OperationalError:
        pass

    # hyq: 2026-06-24 Add drive_type field migration for rclone multi-drive classification support
    try:
        cursor.execute("ALTER TABLE sync_sources ADD COLUMN drive_type TEXT DEFAULT 'GoogleDrive'")
        conn.commit()
    except sqlite3.OperationalError:
        pass

    # 4. 创建任务表
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS sync_tasks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        status TEXT NOT NULL, -- 'running', 'success', 'failed', 'stopped'
        trigger_type TEXT NOT NULL, -- 'manual', 'cron'
        start_time TIMESTAMP,
        end_time TIMESTAMP,
        force_update INTEGER DEFAULT 0,
        items_parsed INTEGER DEFAULT 0,
        strm_written INTEGER DEFAULT 0,
        files_removed INTEGER DEFAULT 0,
        dirs_removed INTEGER DEFAULT 0,
        metadata_synced INTEGER DEFAULT 0,
        elapsed_time REAL DEFAULT 0.0,
        log_file TEXT
    );
    """)

    # 兼容性升级：检查并添加 metadata_synced 字段
    try:
        cursor.execute("ALTER TABLE sync_tasks ADD COLUMN metadata_synced INTEGER DEFAULT 0")
        conn.commit()
    except sqlite3.OperationalError:
        pass

    conn.commit()

    # 5. 写入默认管理员用户 (admin / admin123)
    cursor.execute("SELECT COUNT(*) FROM users")
    if cursor.fetchone()[0] == 0:
        hashed = hash_password("admin123")
        cursor.execute("INSERT INTO users (username, password_hash) VALUES (?, ?)", ("admin", hashed))
        conn.commit()

    # 6. 写入默认全局配置
    default_configs = [
        ("WORKER_CONCURRENCY", "16"),
        ("BATCH_WRITE_SIZE", "1000"),
        ("SOURCE_CONCURRENCY", "5"),
        # hyq: 2026-06-23 Modify default CRON_EXPRESSION to empty string to disable schedule by default
        # ("CRON_EXPRESSION", "0 3 * * *") # 默认每天凌晨 3 点同步
        ("CRON_EXPRESSION", ""),
        ("METADATA_TYPES", "nfo,jpg,jpeg,png,svg,ass,srt,sup,mp3,flac,wav,aac")
    ]
    for key, val in default_configs:
        try:
            cursor.execute("INSERT OR REPLACE INTO global_configs (config_key, config_value) VALUES (?, ?)", (key, val))
        except sqlite3.IntegrityError:
            pass # 已存在则不覆盖
    conn.commit()

    # hyq: 2026-06-24 Populate mock sources only for Windows local testing, preventing server initialization pollution
    # cursor.execute("SELECT COUNT(*) FROM sync_sources")
    # if cursor.fetchone()[0] == 0:
    if os.name == 'nt':
        cursor.execute("SELECT COUNT(*) FROM sync_sources")
        if cursor.fetchone()[0] == 0:
            # hyq: 2026-06-24 Modify mock sources drive_type to GoogleDrive only for Google Drive adaptation
            # mock_sources = [
            #     ("emby_ani_now (测试源A)", "/mnt/emby4/emby_ani_now", "/mnt/strm/series_ani/now", "emby4:/emby_ani_now", 0, "GoogleDrive"),
            #     ("emby_series_now (测试源B)", "/mnt/emby4/emby_series_now", "/mnt/strm/series_mixed/now", "emby4:/emby_series_now", 1, "115"),
            #     ("emby_movies_edu (测试源C)", "/mnt/emby3/emby_movies_edu", "/mnt/strm/movies/edu", "emby3:/emby_movies_edu", 1, "OneDrive"),
            # ]
            mock_sources = [
                ("emby_ani_now (测试源A)", "/mnt/emby4/emby_ani_now", "/mnt/strm/series_ani/now", "emby4:/emby_ani_now", 0, "GoogleDrive"),
                ("emby_series_now (测试源B)", "/mnt/emby4/emby_series_now", "/mnt/strm/series_mixed/now", "emby4:/emby_series_now", 1, "GoogleDrive"),
                ("emby_movies_edu (测试源C)", "/mnt/emby3/emby_movies_edu", "/mnt/strm/movies/edu", "emby3:/emby_movies_edu", 1, "GoogleDrive"),
            ]
            for idx, (name, gd, strm, remote, meta, dtype) in enumerate(mock_sources):
                cursor.execute(
                    "INSERT INTO sync_sources (name, gd_path, strm_path, remote_path, sync_metadata, sort_order, drive_type) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (name, gd, strm, remote, meta, idx, dtype)
                )
            conn.commit()

    conn.close()

# ----------------- 用户操作 -----------------

def verify_user(username, password):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE username = ?", (username,))
    user = cursor.fetchone()
    conn.close()
    if user and check_password(password, user['password_hash']):
        return {"id": user['id'], "username": user['username']}
    return None

def change_user_password(username, old_password, new_password):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE username = ?", (username,))
    user = cursor.fetchone()
    if not user or not check_password(old_password, user['password_hash']):
        conn.close()
        return False, "原密码错误"
    
    new_hashed = hash_password(new_password)
    cursor.execute("UPDATE users SET password_hash = ? WHERE username = ?", (new_hashed, username))
    conn.commit()
    conn.close()
    return True, "密码修改成功"

# ----------------- 全局配置操作 -----------------

def get_all_global_configs():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT config_key, config_value FROM global_configs")
    rows = cursor.fetchall()
    conn.close()
    return {row['config_key']: row['config_value'] for row in rows}

def update_global_configs(configs_dict):
    conn = get_db_connection()
    cursor = conn.cursor()
    for key, val in configs_dict.items():
        cursor.execute("INSERT OR REPLACE INTO global_configs (config_key, config_value) VALUES (?, ?)", (key, str(val)))
    conn.commit()
    conn.close()
    return True

# ----------------- 数据源操作 -----------------

# hyq: 2026-06-24 Modify get_all_sources sorting order to support sort_order
# def get_all_sources():
#     conn = get_db_connection()
#     cursor = conn.cursor()
#     cursor.execute("SELECT * FROM sync_sources ORDER BY id DESC")
#     rows = cursor.fetchall()
#     conn.close()
#     return [dict(row) for row in rows]

def get_all_sources():
    conn = get_db_connection()
    cursor = conn.cursor()
    # 默认按 sort_order 升序，如果 sort_order 相同则按最新的 id 降序排在前面
    cursor.execute("SELECT * FROM sync_sources ORDER BY sort_order ASC, id DESC")
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]

def update_sources_order(ordered_ids):
    """根据前端传入的新 ID 顺序列表，批量更新对应的 sort_order，@author: hyq, @version: 2026-06-24"""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        for index, source_id in enumerate(ordered_ids):
            cursor.execute("UPDATE sync_sources SET sort_order = ? WHERE id = ?", (index, source_id))
        conn.commit()
        return True
    except Exception as e:
        print(f"[DB] 更新源排序异常: {e}")
        return False
    finally:
        conn.close()

def get_source_by_id(source_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM sync_sources WHERE id = ?", (source_id,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None

# hyq: 2026-06-24 Modify add_sync_source and update_sync_source to support drive_type field
# def add_sync_source(name, gd_path, strm_path, remote_path, sync_metadata=1):
#     conn = get_db_connection()
#     cursor = conn.cursor()
#     try:
#         cursor.execute(
#             "INSERT INTO sync_sources (name, gd_path, strm_path, remote_path, sync_metadata) VALUES (?, ?, ?, ?, ?)",
#             (name, gd_path, strm_path, remote_path, sync_metadata)
#         )
#         conn.commit()
#         success, msg = True, "添加源成功"
#     except sqlite3.IntegrityError:
#         success, msg = False, f"源名称 '{name}' 已存在"
#     finally:
#         conn.close()
#     return success, msg
# 
# def update_sync_source(source_id, name, gd_path, strm_path, remote_path, sync_metadata=1):
#     conn = get_db_connection()
#     cursor = conn.cursor()
#     try:
#         cursor.execute(
#             "UPDATE sync_sources SET name = ?, gd_path = ?, strm_path = ?, remote_path = ?, sync_metadata = ? WHERE id = ?",
#             (name, gd_path, strm_path, remote_path, sync_metadata, source_id)
#         )
#         conn.commit()
#         success, msg = True, "修改源成功"
#     except sqlite3.IntegrityError:
#         success, msg = False, f"源名称 '{name}' 已被占用"
#     finally:
#         conn.close()
#     return success, msg

def add_sync_source(name, gd_path, strm_path, remote_path, sync_metadata=1, drive_type='GoogleDrive'):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "INSERT INTO sync_sources (name, gd_path, strm_path, remote_path, sync_metadata, drive_type) VALUES (?, ?, ?, ?, ?, ?)",
            (name, gd_path, strm_path, remote_path, sync_metadata, drive_type)
        )
        conn.commit()
        success, msg = True, "添加源成功"
    except sqlite3.IntegrityError:
        success, msg = False, f"源名称 '{name}' 已存在"
    finally:
        conn.close()
    return success, msg

def update_sync_source(source_id, name, gd_path, strm_path, remote_path, sync_metadata=1, drive_type='GoogleDrive'):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "UPDATE sync_sources SET name = ?, gd_path = ?, strm_path = ?, remote_path = ?, sync_metadata = ?, drive_type = ? WHERE id = ?",
            (name, gd_path, strm_path, remote_path, sync_metadata, drive_type, source_id)
        )
        conn.commit()
        success, msg = True, "修改源成功"
    except sqlite3.IntegrityError:
        success, msg = False, f"源名称 '{name}' 已被占用"
    finally:
        conn.close()
    return success, msg

def delete_sync_source(source_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM sync_sources WHERE id = ?", (source_id,))
    conn.commit()
    conn.close()
    return True

# ----------------- 任务历史操作 -----------------

def create_sync_task(trigger_type, force_update):
    conn = get_db_connection()
    cursor = conn.cursor()
    start_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cursor.execute(
        "INSERT INTO sync_tasks (status, trigger_type, start_time, force_update) VALUES (?, ?, ?, ?)",
        ("running", trigger_type, start_time, 1 if force_update else 0)
    )
    task_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return task_id

def finish_sync_task(task_id, status, items_parsed=0, strm_written=0, files_removed=0, dirs_removed=0, metadata_synced=0, elapsed_time=0.0, log_file=""):
    conn = get_db_connection()
    cursor = conn.cursor()
    end_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cursor.execute(
        """UPDATE sync_tasks SET 
            status = ?, end_time = ?, items_parsed = ?, strm_written = ?, 
            files_removed = ?, dirs_removed = ?, metadata_synced = ?, elapsed_time = ?, log_file = ?
           WHERE id = ?""",
        (status, end_time, items_parsed, strm_written, files_removed, dirs_removed, metadata_synced, elapsed_time, log_file, task_id)
    )
    conn.commit()
    conn.close()

def get_sync_tasks(limit=10):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM sync_tasks ORDER BY id DESC LIMIT ?", (limit,))
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]

# hyq: 2026-06-23 Add get_sync_task_by_id to support single task query
def get_sync_task_by_id(task_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM sync_tasks WHERE id = ?", (task_id,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None

# 初始化数据库
init_db()

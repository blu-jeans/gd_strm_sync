# -*- coding: utf-8 -*-
import os
import db

def reset():
    # 导入 db 就会自动初始化数据库
    import sqlite3
    conn = sqlite3.connect(db.DB_PATH)
    cursor = conn.cursor()
    
    # 检查 admin 用户是否存在
    cursor.execute("SELECT * FROM users WHERE username = ?", ("admin",))
    user = cursor.fetchone()
    
    new_hashed = db.hash_password("admin123")
    
    if user:
        cursor.execute("UPDATE users SET password_hash = ? WHERE username = ?", (new_hashed, "admin"))
        print("用户 admin 的密码已重置为 admin123")
    else:
        cursor.execute("INSERT INTO users (username, password_hash) VALUES (?, ?)", ("admin", new_hashed))
        print("用户 admin 不存在，已创建默认管理员，密码为 admin123")
        
    conn.commit()
    conn.close()

if __name__ == "__main__":
    reset()

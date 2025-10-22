#!/usr/bin/env python3
"""
更新后端 CORS 配置脚本
允许前端 GitHub Pages 访问后端 API
"""

import re

def update_cors():
    # 读取 app.py
    with open('app.py', 'r', encoding='utf-8') as f:
        content = f.read()
    
    # 查找并替换 CORS 配置
    old_pattern = r'CORS\(app\)'
    
    new_cors = '''CORS(app, resources={
    r"/*": {
        "origins": [
            "https://zac-chen-2024.github.io",
            "http://localhost:3000",
            "http://127.0.0.1:3000"
        ],
        "methods": ["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        "allow_headers": ["Content-Type", "Authorization"],
        "supports_credentials": True,
        "expose_headers": ["Content-Type", "Authorization"]
    }
})'''
    
    # 替换配置
    new_content = re.sub(old_pattern, new_cors, content)
    
    # 检查是否有改变
    if new_content == content:
        print("❌ 未找到需要替换的 CORS 配置")
        return False
    
    # 写回文件
    with open('app.py', 'w', encoding='utf-8') as f:
        f.write(new_content)
    
    print("✅ CORS 配置已更新")
    print("\n新的 CORS 配置:")
    print("-" * 50)
    print(new_cors)
    print("-" * 50)
    
    return True

if __name__ == '__main__':
    update_cors()


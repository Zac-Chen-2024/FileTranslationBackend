#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
数据库初始化脚本
用于创建数据库表和初始数据
"""

import os
import sys
from datetime import datetime
from app import app, db
from werkzeug.security import generate_password_hash

def init_database():
    """初始化数据库"""
    with app.app_context():
        # 创建所有表
        db.create_all()
        print("✓ 数据库表创建成功")

        # 检查是否需要创建默认用户
        from app import User
        admin_user = User.query.filter_by(name='admin').first()

        if not admin_user:
            # 创建默认管理员用户
            admin_user = User(
                name='admin',
                email='admin@example.com',
                password_hash=generate_password_hash('admin123'),
                created_at=datetime.utcnow()
            )
            db.session.add(admin_user)
            db.session.commit()
            print("✓ 默认管理员用户创建成功")
            print("  用户名: admin")
            print("  密码: admin123")
            print("  请登录后立即修改密码！")
        else:
            print("✓ 管理员用户已存在")

        # 创建必要的文件夹
        folders = [
            'uploads',
            'downloads',
            'outputs',
            'original_snapshot',
            'translated_snapshot',
            'web_translation_output',
            'image_translation_output',
            'formula_output',
            'poster_output',
            'instance',
            'logs'
        ]

        for folder in folders:
            folder_path = os.path.join(os.path.dirname(__file__), folder)
            if not os.path.exists(folder_path):
                os.makedirs(folder_path)
                print(f"✓ 创建文件夹: {folder}")
            else:
                print(f"✓ 文件夹已存在: {folder}")

        print("\n数据库初始化完成！")
        return True

if __name__ == '__main__':
    try:
        init_database()
    except Exception as e:
        print(f"✗ 初始化失败: {str(e)}", file=sys.stderr)
        sys.exit(1)
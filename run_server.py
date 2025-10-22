#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
服务器启动脚本
支持开发和生产环境
"""

import os
import sys
import argparse
from pathlib import Path

def run_development():
    """运行开发服务器"""
    print("启动开发服务器...")
    os.environ['FLASK_ENV'] = 'development'
    os.environ['FLASK_DEBUG'] = '1'

    from app import app
    app.run(
        host='0.0.0.0',
        port=5010,
        debug=True,
        threaded=True
    )

def run_production():
    """运行生产服务器（使用Gunicorn）"""
    print("启动生产服务器...")
    os.environ['FLASK_ENV'] = 'production'

    # 检查是否安装了Gunicorn
    try:
        import gunicorn
    except ImportError:
        print("错误: Gunicorn未安装")
        print("请运行: pip install gunicorn")
        sys.exit(1)

    # 使用Gunicorn启动
    os.system('gunicorn -c gunicorn_config.py app:app')

def run_test():
    """运行测试服务器"""
    print("运行测试...")
    os.environ['FLASK_ENV'] = 'testing'

    # 这里可以添加测试代码
    print("测试功能尚未实现")

def check_environment():
    """检查环境配置"""
    print("检查环境配置...")

    # 检查Python版本
    python_version = sys.version_info
    print(f"✓ Python版本: {python_version.major}.{python_version.minor}.{python_version.micro}")

    if python_version.major < 3 or (python_version.major == 3 and python_version.minor < 8):
        print("⚠ 警告: 建议使用Python 3.8或更高版本")

    # 检查必要的环境变量
    env_file = Path('.env')
    if env_file.exists():
        print("✓ 找到.env文件")
    else:
        print("⚠ 警告: 未找到.env文件")
        print("  请创建.env文件并配置必要的环境变量")

    # 检查必要的文件夹
    required_folders = ['uploads', 'downloads', 'outputs', 'logs']
    for folder in required_folders:
        folder_path = Path(folder)
        if folder_path.exists():
            print(f"✓ 文件夹存在: {folder}")
        else:
            folder_path.mkdir(parents=True, exist_ok=True)
            print(f"✓ 创建文件夹: {folder}")

    # 检查数据库
    db_path = Path('instance/translation_platform.db')
    if db_path.exists():
        print("✓ 数据库文件存在")
    else:
        print("⚠ 警告: 数据库文件不存在")
        print("  运行 python init_db.py 来初始化数据库")

    print("\n环境检查完成！")

def main():
    """主函数"""
    parser = argparse.ArgumentParser(description='翻译平台服务器启动脚本')
    parser.add_argument(
        '--mode',
        choices=['dev', 'prod', 'test', 'check'],
        default='dev',
        help='运行模式: dev(开发), prod(生产), test(测试), check(检查环境)'
    )
    parser.add_argument(
        '--port',
        type=int,
        default=5010,
        help='服务器端口（仅开发模式）'
    )

    args = parser.parse_args()

    # 设置工作目录
    os.chdir(Path(__file__).parent)

    if args.mode == 'check':
        check_environment()
    elif args.mode == 'dev':
        check_environment()
        run_development()
    elif args.mode == 'prod':
        check_environment()
        run_production()
    elif args.mode == 'test':
        run_test()

if __name__ == '__main__':
    main()
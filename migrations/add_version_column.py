"""
数据库迁移脚本: 添加version列到materials表

用途: 为乐观锁机制添加版本号字段

执行方式:
    # 方式1: 使用虚拟环境
    cd backend_onserver
    source venv/bin/activate  # Linux/Mac
    venv\\Scripts\\activate   # Windows
    python migrations/add_version_column.py

    # 方式2: 使用系统Python（如果已安装依赖）
    cd backend_onserver
    python migrations/add_version_column.py

说明:
    由于现有数据都是测试数据，本脚本会删除并重新创建数据库
    如果需要保留数据，请使用 add_version_column_preserve_data.py
"""

import sys
import os

# 添加父目录到路径，以便导入app模块
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

print("正在导入Flask应用...")
print("注意: 请确保已激活虚拟环境或已安装所有依赖")
print()

try:
    from app import app, db
    from sqlalchemy import inspect
except ImportError as e:
    print(f"❌ 导入失败: {e}")
    print()
    print("请先激活虚拟环境:")
    print("  Windows: backend_onserver\\venv\\Scripts\\activate")
    print("  Linux/Mac: source backend_onserver/venv/bin/activate")
    print()
    print("或确保已安装所有依赖:")
    print("  pip install -r requirements.txt")
    sys.exit(1)

def check_version_column_exists():
    """检查version列是否已存在"""
    with app.app_context():
        inspector = inspect(db.engine)
        columns = [col['name'] for col in inspector.get_columns('materials')]
        return 'version' in columns

def recreate_database():
    """删除并重新创建数据库（适用于测试环境）"""
    print("=" * 60)
    print("数据库迁移: 添加version列")
    print("=" * 60)
    print()

    with app.app_context():
        # 检查是否已有version列
        if check_version_column_exists():
            print("✓ version列已存在，无需迁移")
            return

        print("⚠️  警告: 此操作将删除所有现有数据！")
        print()

        # 在生产环境应该需要确认
        # confirm = input("确认删除并重建数据库? (yes/no): ")
        # if confirm.lower() != 'yes':
        #     print("已取消迁移")
        #     return

        print("1. 删除所有表...")
        db.drop_all()
        print("   ✓ 已删除所有表")
        print()

        print("2. 重新创建表（包含version列）...")
        db.create_all()
        print("   ✓ 已创建所有表")
        print()

        # 验证version列存在
        inspector = inspect(db.engine)
        columns = [col['name'] for col in inspector.get_columns('materials')]

        if 'version' in columns:
            print("✓ 迁移成功！version列已添加到materials表")
            print()
            print("Materials表结构:")
            for col in inspector.get_columns('materials'):
                nullable = "NULL" if col['nullable'] else "NOT NULL"
                default = f" DEFAULT {col['default']}" if col['default'] else ""
                print(f"  - {col['name']}: {col['type']} {nullable}{default}")
        else:
            print("✗ 迁移失败：version列未找到")
            print()
            print("当前Materials表列:")
            for col in columns:
                print(f"  - {col}")

if __name__ == '__main__':
    try:
        recreate_database()
        print()
        print("=" * 60)
        print("迁移完成")
        print("=" * 60)
    except Exception as e:
        print(f"✗ 迁移失败: {str(e)}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

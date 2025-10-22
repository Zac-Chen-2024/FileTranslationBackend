"""
数据库迁移脚本: 添加version列到materials表（保留现有数据）

用途: 为乐观锁机制添加版本号字段，同时保留所有现有数据

执行方式:
    python migrations/add_version_column_preserve_data.py

注意:
    此脚本会保留所有现有数据，适用于生产环境
    测试环境可以使用 add_version_column.py 直接重建数据库
"""

import sys
import os

# 添加父目录到路径，以便导入app模块
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app, db
from sqlalchemy import text, inspect

def check_version_column_exists():
    """检查version列是否已存在"""
    with app.app_context():
        inspector = inspect(db.engine)
        columns = [col['name'] for col in inspector.get_columns('materials')]
        return 'version' in columns

def add_version_column_preserve_data():
    """添加version列并保留现有数据"""
    print("=" * 60)
    print("数据库迁移: 添加version列（保留数据）")
    print("=" * 60)
    print()

    with app.app_context():
        # 检查是否已有version列
        if check_version_column_exists():
            print("✓ version列已存在，无需迁移")
            return

        try:
            print("1. 检查数据库连接...")
            # 测试连接
            db.session.execute(text('SELECT 1'))
            print("   ✓ 数据库连接正常")
            print()

            print("2. 添加version列（允许NULL）...")
            # 先添加允许NULL的列
            db.session.execute(text(
                'ALTER TABLE materials ADD COLUMN version INTEGER'
            ))
            db.session.commit()
            print("   ✓ 已添加version列")
            print()

            print("3. 为现有记录设置初始版本号...")
            # 为所有现有记录设置version=0
            result = db.session.execute(text(
                'UPDATE materials SET version = 0 WHERE version IS NULL'
            ))
            affected_rows = result.rowcount
            db.session.commit()
            print(f"   ✓ 已更新 {affected_rows} 条记录的版本号为0")
            print()

            print("4. 设置version列为NOT NULL...")
            # SQLite不支持直接ALTER COLUMN，需要重建表
            # 但由于我们已经为所有记录设置了version=0，可以跳过此步骤
            # 在后续的表重建时会自动应用NOT NULL约束
            print("   ⚠️  SQLite不支持修改列约束，将在下次表重建时应用NOT NULL")
            print("   ℹ️  当前所有记录的version已设置为0，满足NOT NULL要求")
            print()

            # 验证迁移结果
            print("5. 验证迁移结果...")
            inspector = inspect(db.engine)
            columns = [col['name'] for col in inspector.get_columns('materials')]

            if 'version' in columns:
                print("   ✓ version列已成功添加")

                # 检查是否有NULL值
                result = db.session.execute(text(
                    'SELECT COUNT(*) FROM materials WHERE version IS NULL'
                ))
                null_count = result.scalar()

                if null_count == 0:
                    print("   ✓ 所有记录的version字段均已设置")
                else:
                    print(f"   ⚠️  警告: 仍有 {null_count} 条记录的version为NULL")

                # 显示材料总数
                result = db.session.execute(text('SELECT COUNT(*) FROM materials'))
                total_count = result.scalar()
                print(f"   ℹ️  材料总数: {total_count}")
                print()

                print("Materials表新增字段:")
                for col in inspector.get_columns('materials'):
                    if col['name'] == 'version':
                        nullable = "NULL" if col['nullable'] else "NOT NULL"
                        default = f" DEFAULT {col['default']}" if col['default'] else ""
                        print(f"  - {col['name']}: {col['type']} {nullable}{default}")
            else:
                print("   ✗ 迁移失败：version列未找到")

        except Exception as e:
            db.session.rollback()
            print(f"✗ 迁移过程中出错: {str(e)}")
            raise

if __name__ == '__main__':
    try:
        add_version_column_preserve_data()
        print()
        print("=" * 60)
        print("迁移完成")
        print("=" * 60)
        print()
        print("下一步:")
        print("1. 重启应用服务器")
        print("2. 测试翻译功能")
        print("3. 检查version字段是否正常递增")
    except Exception as e:
        print()
        print("=" * 60)
        print("迁移失败")
        print("=" * 60)
        import traceback
        traceback.print_exc()
        sys.exit(1)

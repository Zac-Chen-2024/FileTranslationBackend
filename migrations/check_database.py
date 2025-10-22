"""
检查数据库结构，不依赖Flask应用

用途: 检查materials表是否有version列
"""

import sqlite3
import os
import sys

def check_database():
    """检查数据库表结构"""
    db_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        'instance',
        'translation_platform.db'
    )

    if not os.path.exists(db_path):
        print(f"❌ 数据库不存在: {db_path}")
        return False

    print("=" * 60)
    print("数据库检查")
    print("=" * 60)
    print(f"数据库路径: {db_path}")
    print()

    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        # 获取materials表结构
        cursor.execute("PRAGMA table_info(materials)")
        columns = cursor.fetchall()

        if not columns:
            print("❌ materials表不存在")
            conn.close()
            return False

        print("Materials表字段:")
        print("-" * 60)

        has_version = False
        for col in columns:
            col_id, name, col_type, not_null, default_value, pk = col
            nullable = "NOT NULL" if not_null else "NULL"
            default = f" DEFAULT {default_value}" if default_value is not None else ""
            pk_flag = " PRIMARY KEY" if pk else ""

            print(f"{col_id:3}. {name:25} {col_type:12} {nullable:8}{default}{pk_flag}")

            if name == 'version':
                has_version = True

        print("-" * 60)
        print()

        if has_version:
            print("✅ version列已存在")

            # 检查version列的数据
            cursor.execute("SELECT COUNT(*) FROM materials")
            total = cursor.fetchone()[0]

            if total > 0:
                cursor.execute("SELECT COUNT(*) FROM materials WHERE version IS NULL")
                null_count = cursor.fetchone()[0]

                print(f"材料总数: {total}")
                print(f"version为NULL的数量: {null_count}")

                if null_count > 0:
                    print("⚠️  警告: 有材料的version为NULL，建议运行迁移脚本")
                else:
                    print("✅ 所有材料都有version值")
            else:
                print("ℹ️  数据库为空（无材料记录）")
        else:
            print("❌ version列不存在")
            print()
            print("需要执行以下操作之一:")
            print("1. 运行迁移脚本: python migrations/add_version_column.py")
            print("2. 删除数据库并重启应用（会自动创建新表）")

        conn.close()
        return has_version

    except Exception as e:
        print(f"❌ 检查失败: {str(e)}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == '__main__':
    print()
    result = check_database()
    print()
    print("=" * 60)
    if result:
        print("检查完成: version列已就绪")
    else:
        print("检查完成: 需要迁移")
    print("=" * 60)
    print()

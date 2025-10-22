"""
简单的数据库迁移脚本: 添加version列

不依赖Flask应用，直接操作SQLite数据库
适用于测试环境，会删除并重建数据库
"""

import sqlite3
import os
import sys

def migrate_database():
    """删除并重新创建数据库"""
    db_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        'instance',
        'translation_platform.db'
    )

    print("=" * 60)
    print("Database Migration: Add version column")
    print("=" * 60)
    print(f"Database path: {db_path}")
    print()

    if not os.path.exists(db_path):
        print("[ERROR] Database does not exist!")
        print("Please create database first by running the application.")
        return False

    print("[WARNING] This will DELETE all existing data!")
    print()

    # Since this is test data, we can directly delete and recreate
    try:
        # Backup old database
        backup_path = db_path + '.backup'
        if os.path.exists(db_path):
            import shutil
            shutil.copy2(db_path, backup_path)
            print(f"[1] Backup created: {backup_path}")

        # Delete database
        os.remove(db_path)
        print("[2] Old database deleted")

        print()
        print("[SUCCESS] Migration completed!")
        print()
        print("Next steps:")
        print("1. Restart the Flask application")
        print("2. Application will automatically create new database with version column")
        print("3. Test translation functionality")
        print()
        return True

    except Exception as e:
        print(f"[ERROR] Migration failed: {str(e)}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == '__main__':
    print()
    result = migrate_database()
    print("=" * 60)
    if result:
        print("Migration Status: SUCCESS")
        print()
        print("IMPORTANT: Please restart the Flask application now!")
    else:
        print("Migration Status: FAILED")
    print("=" * 60)
    print()
    sys.exit(0 if result else 1)

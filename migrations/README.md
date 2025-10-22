# 数据库迁移脚本

本目录包含数据库结构变更的迁移脚本。

## 📋 迁移列表

### 1. 添加version列（乐观锁支持）

为 `materials` 表添加 `version` 列，支持乐观锁并发控制。

#### 选项A: 重建数据库（测试环境，删除所有数据）

**脚本**: `add_version_column.py`

**适用场景**:
- 测试环境
- 现有数据可以删除
- 快速重建数据库

**执行方式**:
```bash
cd backend_onserver
python migrations/add_version_column.py
```

**操作**:
1. ✅ 删除所有表
2. ✅ 重新创建表（包含version列）
3. ✅ 验证表结构

**特点**:
- ⚡ 快速简单
- ⚠️  删除所有数据
- ✅ 确保表结构完全正确

---

#### 选项B: 保留现有数据（生产环境）

**脚本**: `add_version_column_preserve_data.py`

**适用场景**:
- 生产环境
- 需要保留现有数据
- 数据迁移

**执行方式**:
```bash
cd backend_onserver
python migrations/add_version_column_preserve_data.py
```

**操作**:
1. ✅ 添加version列（允许NULL）
2. ✅ 为所有现有记录设置version=0
3. ✅ 验证数据完整性

**注意事项**:
- SQLite不支持直接修改列约束为NOT NULL
- 所有现有记录的version会设置为0
- 后续新建的表会自动应用NOT NULL约束

**特点**:
- ✅ 保留所有数据
- ✅ 安全的增量迁移
- ⚠️  需要额外步骤处理约束

---

## 🚀 推荐执行方式

### 测试环境（当前推荐）

由于现有数据都是测试数据，推荐使用**选项A**直接重建：

```bash
cd backend_onserver
python migrations/add_version_column.py
```

### 生产环境（未来使用）

如果将来有重要数据，使用**选项B**保留数据：

```bash
cd backend_onserver
python migrations/add_version_column_preserve_data.py
```

---

## ✅ 迁移后验证

运行迁移脚本后，应该看到：

```
Materials表结构:
  - id: VARCHAR NOT NULL
  - name: VARCHAR NOT NULL
  - type: VARCHAR NOT NULL
  - status: VARCHAR DEFAULT '待处理'
  - version: INTEGER NOT NULL DEFAULT 0  ← 新增字段
  - client_id: VARCHAR NOT NULL
  - created_at: DATETIME
  - updated_at: DATETIME
  ...
```

---

## 🧪 测试迁移

迁移完成后，建议测试：

1. **上传材料**: 确认新材料的version=0
2. **翻译材料**: 确认每次状态更新version递增
3. **并发测试**: 快速点击重新翻译，确认锁机制生效
4. **检查日志**: 查看version递增日志

```bash
# 检查材料的version值
sqlite3 instance/translation_platform.db
> SELECT id, name, status, version FROM materials LIMIT 5;
```

---

## 📝 回滚（仅限测试环境）

如果需要回滚迁移（仅测试环境）：

```bash
cd backend_onserver
python migrations/rollback_version_column.py  # 需要创建此脚本
```

或者直接删除数据库文件：

```bash
rm -f backend_onserver/instance/translation_platform.db
# 然后重启应用，数据库会自动创建（不包含version列）
```

---

## 🔧 故障排除

### 问题1: "column version already exists"

**原因**: version列已存在

**解决**: 无需迁移，检查是否已执行过

```bash
python migrations/add_version_column.py
# 输出: ✓ version列已存在，无需迁移
```

### 问题2: ImportError

**原因**: Python路径问题

**解决**: 确保在backend_onserver目录下执行

```bash
cd backend_onserver
python migrations/add_version_column.py
```

### 问题3: 数据库锁定

**原因**: 应用正在运行

**解决**: 停止应用后再执行迁移

```bash
# 停止应用
# 执行迁移
python migrations/add_version_column.py
# 重启应用
```

---

## 📚 更多信息

- 乐观锁机制说明: 参见 `REFACTORING_PROGRESS.md` 第1.3节
- 状态更新函数: 参见 `app.py` Line 684-766 `update_material_status()`
- 锁检查函数: 参见 `app.py` Line 768-785 `check_translation_lock()`

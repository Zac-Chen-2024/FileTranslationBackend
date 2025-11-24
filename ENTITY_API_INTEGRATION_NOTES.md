# 实体识别 API 集成修正说明

## 修改日期
2025-11-19

## 修改目的
根据实际的 Entity Recognition API 规范（位于 `/home/translation/reference/entity`），修正后端的实体识别服务调用逻辑。

---

## Entity API 实际规范

### API 端点
- **URL**: `https://tns.drziangchen.uk/api/entity/analyze`
- **方法**: POST
- **Content-Type**: application/json

### 支持的模式

#### 1. identify 模式（快速识别）
- **用途**: 快速识别实体名称，不进行深度搜索
- **响应时间**: ~30秒
- **返回内容**: 只包含实体名称列表

**请求示例：**
```json
{
  "text": "公司查询：腾讯公司推出了微信",
  "mode": "identify"
}
```

**响应示例：**
```json
{
  "success": true,
  "mode": "identify",
  "count": 1,
  "entities": [
    {"entity": "腾讯公司"}
  ]
}
```

#### 2. analyze 模式（深度分析）
- **用途**: 完整查询，包含 Google 搜索和官网分析
- **响应时间**: ~1-2分钟
- **返回内容**: 包含英文名称、来源 URL、置信度

**请求示例：**
```json
{
  "text": "公司查询：腾讯公司",
  "mode": "analyze"
}
```

**响应示例：**
```json
{
  "success": true,
  "mode": "analyze",
  "count": 1,
  "entities": [
    {
      "chinese_name": "腾讯公司",
      "english_name": "Tencent Holdings Limited",
      "source": "https://www.tencent.com/en-us/",
      "confidence": "high"
    }
  ]
}
```

### 两阶段查询（推荐工作流）

**第一阶段：快速识别**
```json
{
  "text": "公司查询：腾讯和阿里",
  "mode": "identify"
}
```

**第二阶段：选择性深度分析**
```json
{
  "entities": ["腾讯公司"],  // 直接提供实体数组
  "mode": "analyze"
}
```

**优势：**
- 快速获取所有实体列表
- 用户可选择感兴趣的实体进行深度查询
- 节省 API 调用成本和时间

---

## 后端修改内容

### 文件：`entity_recognition_service.py`

#### 1. 修正模式映射

**修改前：**
- `fast` 模式 → 调用未定义的 API 模式
- `deep` 模式 → 调用未定义的 API 模式
- `manual_adjust` 模式 → 调用未定义的 API 模式

**修改后：**
- `fast` 模式 → 映射到 Entity API 的 `identify` 模式
- `deep` 模式 → 映射到 Entity API 的 `analyze` 模式
- `manual_adjust` 模式 → 使用 `analyze` 模式或两阶段查询

#### 2. 修正请求格式

**修改前：**
```python
payload = {
    "text": f"公司查询：{all_text}"
    # 缺少 mode 参数
}
```

**修改后：**
```python
payload = {
    "text": f"公司查询：{all_text}",
    "mode": mode  # "identify" 或 "analyze"
}
```

#### 3. 修正响应解析

**修改前：**
```python
# 没有区分 identify 和 analyze 模式的响应格式
for entity in entities:
    if 'type' not in entity:
        entity['type'] = 'ORGANIZATION'
```

**修改后：**
```python
# 根据不同模式处理响应
if api_mode == 'identify':
    # identify模式返回格式：[{"entity": "腾讯公司"}]
    # 转换为统一格式
    normalized_entities = []
    for entity in entities:
        normalized_entities.append({
            "chinese_name": entity.get('entity', ''),
            "english_name": None,  # identify模式不提供英文名
            "source": None,
            "confidence": None,
            "type": "ORGANIZATION"
        })
    entities = normalized_entities

elif api_mode == 'analyze':
    # analyze模式返回格式已包含所有字段
    for entity in entities:
        if 'type' not in entity:
            entity['type'] = 'ORGANIZATION'
```

#### 4. 新增两阶段查询支持

**新增方法：** `_call_analyze_with_entities(entities_list: List[str])`

```python
def _call_analyze_with_entities(self, entities_list: List[str]) -> Dict:
    """
    两阶段查询的第二阶段：直接提供实体列表进行深度分析

    Args:
        entities_list: 实体名称列表，如 ["腾讯公司", "阿里巴巴"]

    Returns:
        深度分析结果
    """
    payload = {
        "entities": entities_list,  # 直接提供实体数组
        "mode": "analyze"
    }
    # ... API 调用逻辑
```

**使用场景：**
```python
# 用户编辑后的实体列表
user_selected_entities = ["腾讯公司", "阿里巴巴"]

# 直接对选定实体进行深度分析
result = service._call_analyze_with_entities(user_selected_entities)
```

---

## 兼容性说明

### 外部接口保持不变

```python
# 外部调用方式不变
service.recognize_entities(ocr_result, mode="fast")   # 快速模式
service.recognize_entities(ocr_result, mode="deep")   # 深度模式
service.recognize_entities(ocr_result, mode="manual_adjust")  # 人工调整模式
```

### 内部实现映射

| 外部 mode 参数 | 内部 Entity API 模式 | 说明 |
|---------------|---------------------|------|
| `fast` | `identify` | 快速识别（~30秒） |
| `deep` | `analyze` | 深度分析（~1-2分钟） |
| `manual_adjust` | `analyze` 或两阶段查询 | 用户编辑后深度分析 |

---

## 返回格式统一化

**无论使用哪种模式，后端都返回统一的格式：**

```python
{
    "success": True/False,
    "mode": "identify" | "analyze",
    "entities": [
        {
            "chinese_name": "腾讯公司",
            "english_name": "Tencent Holdings Limited" | None,  # identify模式为None
            "source": "https://..." | None,  # identify模式为None
            "confidence": "high" | None,  # identify模式为None
            "type": "ORGANIZATION"
        }
    ],
    "total_entities": 1,
    "processing_time": 1.23,
    "error": None
}
```

**注意：**
- `identify` 模式的 `english_name`, `source`, `confidence` 字段为 `None`
- `analyze` 模式包含完整信息

---

## 推荐使用模式

### 场景 1：快速预览
```python
# 只需要知道文档中有哪些公司/机构
result = service.recognize_entities(ocr_result, mode="fast")
```

### 场景 2：完整翻译
```python
# 需要准确的英文名称用于翻译
result = service.recognize_entities(ocr_result, mode="deep")
```

### 场景 3：用户交互（两阶段查询）
```python
# 第一阶段：快速识别
quick_result = service.recognize_entities(ocr_result, mode="fast")
# 显示给用户，让用户选择/编辑

# 第二阶段：深度分析选定实体
selected_entities = ["腾讯公司", "阿里巴巴"]  # 用户选择的
detailed_result = service._call_analyze_with_entities(selected_entities)
```

---

## 性能对比

| 模式 | 响应时间 | Google 搜索 | 返回内容 | 适用场景 |
|------|---------|------------|---------|---------|
| `identify` | ~30秒 | 否 | 实体名称 | 快速预览 |
| `analyze` | ~1-2分钟 | 是 | 完整信息 | 完整翻译 |

---

## 错误处理

所有模式都实现了统一的错误处理：

1. **API 超时**：120秒超时限制
2. **网络错误**：返回可恢复错误，允许翻译流程继续
3. **API 调用失败**：记录错误信息，返回空结果

```python
{
    "success": False,
    "mode": "identify" | "analyze",
    "entities": [],
    "total_entities": 0,
    "processing_time": 120.0,
    "error": "API调用超时（超过120秒）",
    "recoverable": True,  # 标记为可恢复
    "message": "实体识别服务暂时不可用，但翻译流程可以继续"
}
```

---

## 测试建议

### 1. 单元测试
```python
# 测试 identify 模式
result = service.recognize_entities({
    "regions": [{"src": "腾讯公司"}]
}, mode="fast")
assert result['mode'] == 'identify'
assert result['entities'][0]['chinese_name'] == '腾讯公司'
assert result['entities'][0]['english_name'] is None

# 测试 analyze 模式
result = service.recognize_entities({
    "regions": [{"src": "腾讯公司"}]
}, mode="deep")
assert result['mode'] == 'analyze'
assert result['entities'][0]['english_name'] is not None
```

### 2. 集成测试
```bash
# 测试 Entity API 连接
curl -X POST https://tns.drziangchen.uk/api/entity/analyze \
  -H "Content-Type: application/json" \
  -d '{"text": "公司查询：腾讯", "mode": "identify"}'
```

---

## 注意事项

1. **API 地址**：确保 Entity API 服务运行在 `https://tns.drziangchen.uk/api/entity`
2. **超时设置**：`analyze` 模式需要较长时间（1-2分钟），已设置120秒超时
3. **错误恢复**：实体识别失败不应阻断整个翻译流程
4. **日志记录**：所有 API 调用都有详细日志，便于调试

---

## 相关文件

- **后端服务**: `/home/translation/backend/entity_recognition_service.py`
- **Entity API**: `/home/translation/reference/entity/app.py`
- **API 文档**: `/home/translation/reference/entity/API_MANUAL.md`

---

## 后续优化建议

1. **缓存机制**：对常见实体的识别结果进行缓存
2. **批量处理**：如果文档包含大量实体，考虑批量调用
3. **并发控制**：避免同时发起过多 API 请求
4. **重试机制**：对临时网络错误实施重试
5. **降级策略**：当 Entity API 不可用时，使用本地 LLM 直接翻译

---

## 版本历史

### v1.0 (2025-11-19)
- ✅ 修正 API 调用格式，使用正确的 `mode` 参数
- ✅ 实现 `identify` 和 `analyze` 两种模式
- ✅ 添加两阶段查询支持
- ✅ 统一响应格式处理
- ✅ 改进错误处理和日志记录

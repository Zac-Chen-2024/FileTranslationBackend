# 快速参考指南 - 前端开发

## 🔑 API基础信息

### 认证
```javascript
// 登录获取Token
POST /api/login
{ email, password }

// 所有请求携带Token
headers: {
    'Authorization': 'Bearer <token>'
}
```

## 📊 材料状态速查

### 状态字段
- `status`: 大状态 (pending/processing/completed/failed)
- `processing_step`: 具体步骤 (见下表)

### Processing Steps
| Step | 说明 | 可执行操作 |
|------|------|-----------|
| `uploaded` | 已上传 | 开始OCR |
| `translating` | OCR中 | 等待 |
| `translated` | OCR完成 | 选择实体识别/LLM |
| `entity_recognizing` | 识别中 | 等待 |
| `entity_pending_confirm` | 待确认 | 确认/编辑实体 |
| `entity_confirmed` | 已确认 | 开始LLM |
| `llm_translating` | LLM中 | 等待 |
| `llm_translated` | 完成 | 导出 |

## 🚀 核心API端点

### 1. 基础流程
```javascript
// 上传材料
POST /api/materials
FormData: { client_id, file, name }

// 开始OCR
POST /api/materials/{id}/translate
{ source_lang: 'zh', target_lang: 'en' }

// LLM优化
POST /api/materials/{id}/llm-translate

// 导出结果
GET /api/materials/{id}/export/word
```

### 2. 实体识别（可选）
```javascript
// 启用
POST /api/materials/{id}/enable-entity-recognition
{ enabled: true }

// 三种模式
POST /api/materials/{id}/entity-recognition/fast     // 快速
POST /api/materials/{id}/entity-recognition/deep     // 深度(全自动)
POST /api/materials/{id}/entity-recognition/manual-adjust // AI优化
{ fast_results: [...] }

// 确认实体
POST /api/materials/{id}/confirm-entities
{ entities: [...], translationGuidance: {...} }
```

## 🔄 WebSocket事件

```javascript
// 连接
const socket = io('wss://domain.com', {
    auth: { token: 'jwt_token' }
});

// 监听状态更新
socket.on('material_updated', (data) => {
    // { material_id, status, processing_step, progress }
});

// 监听进度
socket.on('translation_progress', (data) => {
    // { material_id, current_page, total_pages, progress }
});
```

## 🎯 实体识别三种模式

### 模式对比
| 模式 | 耗时 | 用户交互 | 准确度 | 使用场景 |
|------|------|---------|--------|----------|
| **深度(Deep)** | 30-120秒 | 无需 | 高 | 重要文档 |
| **快速+AI优化** | 5-15秒 | 需确认 | 中 | 一般文档 |
| **快速+人工** | 5秒+编辑时间 | 需编辑 | 自定义 | 特殊需求 |

### 深度模式流程
```javascript
// 一步到位，全自动
await axios.post(`/materials/${id}/entity-recognition/deep`);
// 自动确认，可直接LLM翻译
```

### 标准模式流程
```javascript
// 1. 快速识别
const fast = await axios.post(`/materials/${id}/entity-recognition/fast`);

// 2. 用户选择
if (userChoice === 'ai') {
    // AI优化
    await axios.post(`/materials/${id}/entity-recognition/manual-adjust`, {
        fast_results: fast.data.result.entities
    });
} else {
    // 人工编辑（前端处理）
    const edited = await showEditDialog(fast.data.result.entities);
}

// 3. 确认
await axios.post(`/materials/${id}/confirm-entities`, {
    entities: finalEntities
});
```

## ⚠️ 重要规则

### 1. 实体识别阻塞
```javascript
// 如果启用了实体识别，必须确认后才能LLM
if (material.entity_recognition_enabled &&
    !material.entity_recognition_confirmed) {
    // 会返回错误：请先完成实体识别确认
}
```

### 2. 翻译锁
```javascript
// 处理中的材料不能重复请求
const lockedSteps = [
    'splitting', 'translating',
    'entity_recognizing', 'llm_translating'
];
if (lockedSteps.includes(material.processing_step)) {
    // 材料被锁定，等待完成
}
```

### 3. 超时设置
```javascript
const TIMEOUTS = {
    ocr: 60000,          // 60秒
    entity_fast: 10000,  // 10秒
    entity_deep: 120000, // 120秒
    llm: 120000         // 120秒
};
```

## 📈 进度计算

```javascript
// 根据步骤估算进度
const stepProgress = {
    'uploaded': 10,
    'translating': 40,
    'translated': 50,
    'entity_recognizing': 60,
    'entity_pending_confirm': 65,
    'entity_confirmed': 70,
    'llm_translating': 85,
    'llm_translated': 100
};

// 或使用具体进度值
const progress = material.processing_progress ||
                 stepProgress[material.processing_step] || 0;
```

## 🔴 错误处理

### 错误响应格式
```json
{
    "success": false,
    "error": "错误类型",
    "message": "详细信息",
    "code": "ERROR_CODE"
}
```

### 可恢复错误
```javascript
if (response.data.recoverable) {
    // 实体识别服务不可用，但可以继续
    if (confirm('实体识别不可用，是否跳过？')) {
        // 禁用实体识别，继续流程
        await disableEntityRecognition(materialId);
        await startLLMTranslation(materialId);
    }
}
```

## 💡 最佳实践

1. **使用WebSocket监听状态**，避免轮询
2. **Deep模式显示明确的等待提示**（1-2分钟）
3. **保存用户的模式选择偏好**
4. **实体识别失败时提供跳过选项**
5. **显示具体的处理步骤**，而不只是"处理中"

---

*快速参考 v1.0 | 2024-11-18*
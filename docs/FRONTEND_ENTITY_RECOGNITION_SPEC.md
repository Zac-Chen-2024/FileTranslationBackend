# 实体识别功能 - 前端集成需求文档

## 一、功能概述

实体识别功能用于在OCR识别后、LLM翻译前，识别文本中的公司/品牌/产品等实体，获取其官方英文名称，从而指导LLM进行更准确的翻译。

## 二、用户交互流程

### 2.1 整体流程图

```
用户上传文档
    ↓
OCR识别完成
    ↓
[选择是否启用实体识别]
    ├─ 否 → 直接进行LLM翻译
    │
    └─ 是 → [选择识别模式]
            ├─ 深度模式（全自动）
            │   ↓
            │   调用Deep API
            │   ↓
            │   自动完成，直接LLM翻译
            │
            └─ 标准模式（半自动）
                ↓
                调用Fast API（快速识别）
                ↓
                展示识别结果
                ↓
                [用户选择处理方式]
                ├─ AI优化
                │   ↓
                │   调用Manual Adjust API
                │   ↓
                │   LLM翻译
                │
                └─ 人工编辑
                    ↓
                    用户输入翻译对应关系
                    ↓
                    LLM翻译
```

### 2.2 界面交互设计建议

#### 步骤1：OCR完成后的选项

```
┌────────────────────────────────────────┐
│ OCR识别完成                            │
│                                        │
│ 是否启用实体识别？                      │
│ （识别公司/品牌名称，获取官方英文名）     │
│                                        │
│ [不启用，直接翻译]  [启用实体识别]       │
└────────────────────────────────────────┘
```

#### 步骤2：选择识别模式

```
┌────────────────────────────────────────┐
│ 选择实体识别模式                        │
│                                        │
│ ◉ 深度模式（全自动）                    │
│   - 自动完成所有识别和翻译              │
│   - 耗时较长（30-120秒）               │
│   - 准确度最高                         │
│                                        │
│ ○ 标准模式（可人工调整）                │
│   - 先快速识别，再选择处理方式           │
│   - 可以人工编辑结果                    │
│   - 更灵活的控制                       │
│                                        │
│ [取消]                    [开始识别]    │
└────────────────────────────────────────┘
```

#### 步骤3：标准模式 - Fast结果展示

```
┌────────────────────────────────────────┐
│ 快速识别完成                            │
│                                        │
│ 识别到以下实体：                        │
│ ┌──────────────────────────────────┐  │
│ │ 1. 腾讯公司                      │  │
│ │ 2. 微信                          │  │
│ │ 3. 阿里巴巴                      │  │
│ │ 4. 支付宝                        │  │
│ └──────────────────────────────────┘  │
│                                        │
│ 请选择下一步操作：                      │
│                                        │
│ [AI深度查询]  [人工编辑]  [跳过]       │
└────────────────────────────────────────┘
```

#### 步骤4a：AI深度查询结果

```
┌────────────────────────────────────────┐
│ AI优化完成                             │
│                                        │
│ 实体翻译对应关系：                      │
│ ┌──────────────────────────────────┐  │
│ │ 腾讯公司 → Tencent Holdings Ltd  │  │
│ │ 微信 → WeChat                    │  │
│ │ 阿里巴巴 → Alibaba Group        │  │
│ │ 支付宝 → Alipay                  │  │
│ └──────────────────────────────────┘  │
│                                        │
│ [使用这些翻译]           [重新编辑]     │
└────────────────────────────────────────┘
```

#### 步骤4b：人工编辑界面

```
┌────────────────────────────────────────┐
│ 编辑实体翻译                            │
│                                        │
│ 中文实体        英文翻译               │
│ ┌────────────┬─────────────────────┐  │
│ │ 腾讯公司    │ [Tencent          ] │  │
│ │ 微信        │ [WeChat           ] │  │
│ │ 阿里巴巴    │ [Alibaba          ] │  │
│ │ 支付宝      │ [Alipay           ] │  │
│ └────────────┴─────────────────────┘  │
│                                        │
│ [+ 添加更多]                           │
│                                        │
│ [取消]                    [确认使用]    │
└────────────────────────────────────────┘
```

## 三、API接口说明

### 3.1 启用/禁用实体识别

```javascript
POST /api/materials/{material_id}/enable-entity-recognition
Body: {
    "enabled": true  // true启用，false禁用
}
```

### 3.2 快速识别（Fast模式）

```javascript
POST /api/materials/{material_id}/entity-recognition/fast

Response: {
    "success": true,
    "result": {
        "entities": [
            {
                "chinese_name": "腾讯公司",
                "english_name": null,  // Fast模式可能没有英文名
                "type": "ORGANIZATION"
            }
        ],
        "total_entities": 4,
        "mode": "fast"
    },
    "message": "快速识别完成，您可以选择AI深度查询或人工调整"
}
```

### 3.3 深度识别（Deep模式）

```javascript
POST /api/materials/{material_id}/entity-recognition/deep

Response: {
    "success": true,
    "result": {
        "entities": [
            {
                "chinese_name": "腾讯公司",
                "english_name": "Tencent Holdings Limited",
                "source": "https://www.tencent.com/",
                "confidence": "high",
                "type": "ORGANIZATION"
            }
        ],
        "total_entities": 4,
        "mode": "deep"
    },
    "message": "深度识别完成，已自动确认，可直接进行LLM翻译"
}
```

### 3.4 人工调整模式（AI优化）

```javascript
POST /api/materials/{material_id}/entity-recognition/manual-adjust
Body: {
    "fast_results": [...]  // Fast查询的结果
}

Response: {
    "success": true,
    "result": {
        "entities": [
            {
                "chinese_name": "腾讯公司",
                "english_name": "Tencent Holdings Limited",
                "confidence": "medium",
                "type": "ORGANIZATION"
            }
        ],
        "total_entities": 4,
        "mode": "manual_adjust"
    },
    "message": "AI优化完成，请确认后进行LLM翻译"
}
```

### 3.5 确认实体（用户最终确认）

```javascript
POST /api/materials/{material_id}/confirm-entities
Body: {
    "entities": [...],  // 用户确认/编辑后的实体列表
    "translationGuidance": {
        "organizations": ["腾讯公司 -> Tencent", "阿里巴巴 -> Alibaba"],
        "products": ["微信 -> WeChat", "支付宝 -> Alipay"]
    }
}
```

### 3.6 启动LLM翻译

```javascript
POST /api/materials/{material_id}/llm-translate

// 如果启用了实体识别但未确认，会返回错误
Response (错误): {
    "success": false,
    "error": "请先完成实体识别确认",
    "requireEntityConfirmation": true
}
```

## 四、状态管理

### 4.1 处理状态（processing_step）

材料会有以下相关状态：

- `translated` - OCR翻译完成
- `entity_recognizing` - 正在进行实体识别
- `entity_pending_confirm` - 实体识别完成，等待确认
- `entity_confirmed` - 实体已确认
- `llm_translating` - 正在进行LLM翻译
- `llm_translated` - LLM翻译完成

### 4.2 前端状态流转

1. **深度模式流程**：
   ```
   translated → entity_recognizing → entity_confirmed → llm_translating → llm_translated
   ```

2. **标准模式流程**：
   ```
   translated → entity_recognizing → entity_pending_confirm → entity_confirmed → llm_translating → llm_translated
   ```

## 五、注意事项

### 5.1 性能考虑

1. **API响应时间**：
   - Fast模式：1-5秒
   - Deep模式：30-120秒（需要显示loading状态）
   - Manual Adjust：5-10秒

2. **建议添加进度提示**：
   ```javascript
   // Deep模式时显示
   "正在进行深度搜索，这可能需要1-2分钟..."
   ```

### 5.2 错误处理

1. **API超时**：
   - 设置合理的前端超时（建议150秒）
   - 超时后提示用户可以跳过实体识别

2. **可恢复错误**：
   ```javascript
   if (response.recoverable) {
       // 显示：实体识别服务暂时不可用，但可以继续翻译
       // 提供：[跳过实体识别] [重试] 选项
   }
   ```

### 5.3 用户体验优化

1. **保存用户选择**：
   - 记住用户上次选择的模式（深度/标准）
   - 可以在设置中配置默认行为

2. **批量处理**：
   - 如果有多个文档，可以批量应用相同的实体识别设置

3. **实体缓存**：
   - 相同的实体可以缓存识别结果，避免重复查询

## 六、测试场景

### 6.1 基本流程测试

1. 不启用实体识别，直接翻译
2. 深度模式全自动流程
3. 标准模式 + AI优化
4. 标准模式 + 人工编辑
5. 标准模式 + 跳过

### 6.2 异常流程测试

1. API超时处理
2. 网络断开恢复
3. 实体识别失败但继续翻译
4. 用户中途取消

## 七、示例代码

### 7.1 完整流程示例（Vue.js）

```javascript
// 1. OCR完成后，询问是否启用实体识别
async function handleOCRComplete(materialId) {
    const useEntityRecognition = await this.$confirm(
        '是否启用实体识别功能？',
        '实体识别',
        {
            distinguishCancelAndClose: true,
            confirmButtonText: '启用',
            cancelButtonText: '跳过'
        }
    );

    if (!useEntityRecognition) {
        // 直接进行LLM翻译
        return this.startLLMTranslation(materialId);
    }

    // 2. 选择识别模式
    const mode = await this.selectRecognitionMode();

    if (mode === 'deep') {
        // 3a. 深度模式
        await this.runDeepRecognition(materialId);
    } else {
        // 3b. 标准模式
        await this.runStandardRecognition(materialId);
    }
}

// 深度模式处理
async function runDeepRecognition(materialId) {
    this.loading = true;
    this.loadingText = '正在进行深度识别（可能需要1-2分钟）...';

    try {
        const response = await api.post(
            `/materials/${materialId}/entity-recognition/deep`,
            { timeout: 150000 }  // 150秒超时
        );

        if (response.data.success) {
            // 深度模式自动确认，直接翻译
            await this.startLLMTranslation(materialId);
        }
    } catch (error) {
        this.handleError(error);
    } finally {
        this.loading = false;
    }
}

// 标准模式处理
async function runStandardRecognition(materialId) {
    // 1. Fast查询
    this.loading = true;
    this.loadingText = '正在快速识别实体...';

    const fastResponse = await api.post(
        `/materials/${materialId}/entity-recognition/fast`
    );

    this.loading = false;

    if (!fastResponse.data.success) {
        return this.handleError(fastResponse.data);
    }

    // 2. 显示结果，让用户选择
    const entities = fastResponse.data.result.entities;
    const action = await this.showEntityOptions(entities);

    if (action === 'ai_optimize') {
        // 3a. AI优化
        const adjustResponse = await api.post(
            `/materials/${materialId}/entity-recognition/manual-adjust`,
            { fast_results: entities }
        );

        // 使用AI优化结果
        await this.confirmEntities(materialId, adjustResponse.data.result.entities);

    } else if (action === 'manual_edit') {
        // 3b. 人工编辑
        const editedEntities = await this.showEntityEditor(entities);
        await this.confirmEntities(materialId, editedEntities);

    } else {
        // 3c. 跳过
        await this.disableEntityRecognition(materialId);
    }

    // 4. 开始LLM翻译
    await this.startLLMTranslation(materialId);
}
```

## 八、后续优化建议

1. **增加历史记录**：保存用户的实体翻译历史，下次自动建议
2. **批量操作**：支持多个文档使用相同的实体识别设置
3. **实体库管理**：建立常用实体翻译库，提高效率
4. **WebSocket实时更新**：Deep模式时通过WebSocket推送进度

## 九、联系方式

如有疑问，请联系后端开发团队。

---

*文档版本：1.0*
*更新日期：2024-11-18*
*作者：后端开发团队*
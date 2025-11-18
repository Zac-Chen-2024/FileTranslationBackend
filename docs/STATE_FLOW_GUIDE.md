# 状态流程详细说明 - 前后端对接指南

## 一、核心概念

### 1.1 两个关键字段
每个材料（Material）有两个状态字段：

| 字段 | 类型 | 说明 | 用途 |
|------|------|------|------|
| `status` | String | 材料整体状态 | 显示大的处理阶段 |
| `processing_step` | String | 具体处理步骤 | 显示详细进度 |

### 1.2 状态与步骤的关系
```
status (大状态)          processing_step (具体步骤)
├─ pending              → uploaded
├─ processing           → splitting/translating/entity_recognizing/llm_translating
└─ completed           → llm_translated
```

---

## 二、完整状态流程图

### 2.1 标准流程（不含实体识别）

```
[用户上传文件]
    ↓
status: pending
step: uploaded
    ↓
[开始翻译] POST /api/materials/{id}/translate
    ↓
status: processing
step: translating (OCR进行中)
    ↓
status: processing
step: translated (OCR完成)
    ↓
[开始LLM优化] POST /api/materials/{id}/llm-translate
    ↓
status: processing
step: llm_translating (LLM优化中)
    ↓
status: completed
step: llm_translated (全部完成)
```

### 2.2 包含实体识别的流程

#### 2.2.1 深度模式（全自动）

```
[OCR完成后]
step: translated
    ↓
[启用实体识别] POST /api/materials/{id}/enable-entity-recognition
    ↓
[深度识别] POST /api/materials/{id}/entity-recognition/deep
    ↓
step: entity_recognizing
    ↓
step: entity_confirmed (自动确认)
    ↓
[LLM翻译] POST /api/materials/{id}/llm-translate
    ↓
step: llm_translating
    ↓
step: llm_translated
```

#### 2.2.2 标准模式（需确认）

```
[OCR完成后]
step: translated
    ↓
[快速识别] POST /api/materials/{id}/entity-recognition/fast
    ↓
step: entity_recognizing
    ↓
step: entity_pending_confirm (等待用户确认)
    ↓
[用户选择]
    ├─ AI优化: POST /api/materials/{id}/entity-recognition/manual-adjust
    ├─ 人工编辑: 前端本地编辑
    └─ 跳过: 禁用实体识别
    ↓
[确认实体] POST /api/materials/{id}/confirm-entities
    ↓
step: entity_confirmed
    ↓
[LLM翻译] POST /api/materials/{id}/llm-translate
    ↓
step: llm_translating
    ↓
step: llm_translated
```

---

## 三、前端状态判断逻辑

### 3.1 显示状态文字

```javascript
function getStatusText(material) {
    // 根据processing_step显示详细状态
    const stepTexts = {
        'uploaded': '已上传',
        'splitting': '正在分页...',
        'split_completed': '分页完成',
        'translating': '正在OCR识别...',
        'translated': 'OCR完成',
        'entity_recognizing': '正在识别实体...',
        'entity_pending_confirm': '等待确认实体',
        'entity_confirmed': '实体已确认',
        'llm_translating': '正在AI优化...',
        'llm_translated': '翻译完成',
        'failed': '处理失败'
    };

    return stepTexts[material.processing_step] || material.status;
}
```

### 3.2 判断可执行操作

```javascript
function getAvailableActions(material) {
    const actions = [];

    switch (material.processing_step) {
        case 'uploaded':
            actions.push('start_ocr');  // 可以开始OCR
            break;

        case 'translated':
            actions.push('enable_entity_recognition');  // 可以启用实体识别
            actions.push('start_llm');  // 可以直接LLM翻译
            break;

        case 'entity_pending_confirm':
            actions.push('confirm_entities');  // 需要确认实体
            actions.push('edit_entities');  // 可以编辑实体
            break;

        case 'entity_confirmed':
            actions.push('start_llm');  // 可以开始LLM翻译
            break;

        case 'llm_translated':
            actions.push('export');  // 可以导出
            actions.push('ai_revise');  // 可以AI修订
            break;
    }

    return actions;
}
```

### 3.3 进度条显示

```javascript
function getProgress(material) {
    const stepProgress = {
        'uploaded': 10,
        'splitting': 20,
        'translating': 40,
        'translated': 50,
        'entity_recognizing': 60,
        'entity_pending_confirm': 65,
        'entity_confirmed': 70,
        'llm_translating': 85,
        'llm_translated': 100
    };

    // 如果有具体进度值，使用具体值
    if (material.processing_progress !== undefined) {
        return material.processing_progress;
    }

    // 否则根据步骤估算
    return stepProgress[material.processing_step] || 0;
}
```

---

## 四、重要的业务规则

### 4.1 实体识别的阻塞规则

**规则**：如果启用了实体识别，必须确认实体后才能进行LLM翻译

```javascript
// 后端会检查
if (material.entity_recognition_enabled && !material.entity_recognition_confirmed) {
    // 返回错误：请先完成实体识别确认
    return {
        success: false,
        error: "请先完成实体识别确认",
        requireEntityConfirmation: true
    };
}
```

### 4.2 翻译锁机制

**规则**：材料在处理中时不能重复发起翻译请求

```javascript
// 判断是否被锁定
function isLocked(material) {
    const lockedSteps = [
        'splitting',
        'translating',
        'entity_recognizing',
        'llm_translating'
    ];

    return lockedSteps.includes(material.processing_step);
}
```

### 4.3 PDF特殊处理

**规则**：PDF需要先分页，再逐页OCR

```
PDF流程：
uploaded → splitting → split_completed → translating → translated

图片流程：
uploaded → translating → translated
```

---

## 五、错误处理状态

### 5.1 失败状态恢复

当 `status = 'failed'` 时，检查 `processing_step` 确定失败位置：

```javascript
function getFailurePoint(material) {
    if (material.status === 'failed') {
        switch (material.processing_step) {
            case 'splitting':
                return 'PDF分页失败';
            case 'translating':
                return 'OCR识别失败';
            case 'entity_recognizing':
                return '实体识别失败';
            case 'llm_translating':
                return 'AI优化失败';
            default:
                return '处理失败';
        }
    }
    return null;
}
```

### 5.2 可恢复错误

实体识别可能返回可恢复错误：

```javascript
// API响应
{
    success: false,
    error: "实体识别服务暂时不可用",
    recoverable: true
}

// 前端处理
if (response.data.recoverable) {
    // 提供选项：跳过实体识别继续
    if (confirm('实体识别不可用，是否跳过继续翻译？')) {
        // 禁用实体识别
        await disableEntityRecognition(materialId);
        // 继续LLM翻译
        await startLLMTranslation(materialId);
    }
}
```

---

## 六、WebSocket事件与状态同步

### 6.1 监听状态变化

```javascript
socket.on('material_updated', (data) => {
    // data格式
    {
        material_id: 1,
        status: "processing",
        processing_step: "translating",
        processing_progress: 50
    }

    // 更新界面
    updateMaterialInList(data.material_id, {
        status: data.status,
        processing_step: data.processing_step,
        processing_progress: data.processing_progress
    });
});
```

### 6.2 实时进度更新

```javascript
// PDF翻译进度
socket.on('translation_progress', (data) => {
    // data格式
    {
        material_id: 1,
        current_page: 3,
        total_pages: 10,
        progress: 30
    }

    // 显示页面进度
    showPageProgress(data.material_id,
        `正在处理第 ${data.current_page}/${data.total_pages} 页`
    );
});
```

---

## 七、完整的前端状态管理示例

```javascript
class MaterialStateManager {
    constructor() {
        this.materials = new Map();
    }

    // 更新材料状态
    updateMaterial(id, updates) {
        const material = this.materials.get(id) || {};
        this.materials.set(id, { ...material, ...updates });
        this.render(id);
    }

    // 渲染状态UI
    render(id) {
        const material = this.materials.get(id);
        if (!material) return;

        // 1. 更新状态文字
        document.getElementById(`status-${id}`).textContent =
            this.getStatusText(material);

        // 2. 更新进度条
        document.getElementById(`progress-${id}`).style.width =
            `${this.getProgress(material)}%`;

        // 3. 更新操作按钮
        this.updateActionButtons(id, material);

        // 4. 显示/隐藏特定UI
        this.updateUIVisibility(id, material);
    }

    // 获取状态文字
    getStatusText(material) {
        const texts = {
            'uploaded': '等待处理',
            'splitting': '正在分页...',
            'translating': 'OCR识别中...',
            'translated': 'OCR完成',
            'entity_recognizing': '识别实体中...',
            'entity_pending_confirm': '请确认实体',
            'entity_confirmed': '实体已确认',
            'llm_translating': 'AI优化中...',
            'llm_translated': '翻译完成'
        };
        return texts[material.processing_step] || '未知状态';
    }

    // 获取进度
    getProgress(material) {
        // 具体进度优先
        if (material.processing_progress !== undefined) {
            return material.processing_progress;
        }

        // 步骤估算
        const estimates = {
            'uploaded': 10,
            'splitting': 20,
            'translating': 40,
            'translated': 50,
            'entity_recognizing': 60,
            'entity_pending_confirm': 65,
            'entity_confirmed': 70,
            'llm_translating': 85,
            'llm_translated': 100
        };
        return estimates[material.processing_step] || 0;
    }

    // 更新操作按钮
    updateActionButtons(id, material) {
        const buttons = {
            startOCR: document.getElementById(`btn-ocr-${id}`),
            entityRecog: document.getElementById(`btn-entity-${id}`),
            startLLM: document.getElementById(`btn-llm-${id}`),
            export: document.getElementById(`btn-export-${id}`)
        };

        // 根据状态启用/禁用按钮
        buttons.startOCR.disabled = material.processing_step !== 'uploaded';
        buttons.entityRecog.disabled = material.processing_step !== 'translated';
        buttons.startLLM.disabled = !(
            material.processing_step === 'translated' ||
            material.processing_step === 'entity_confirmed'
        );
        buttons.export.disabled = material.processing_step !== 'llm_translated';
    }

    // 更新UI可见性
    updateUIVisibility(id, material) {
        // 实体确认面板
        const entityPanel = document.getElementById(`entity-panel-${id}`);
        if (entityPanel) {
            entityPanel.style.display =
                material.processing_step === 'entity_pending_confirm'
                    ? 'block' : 'none';
        }

        // 结果面板
        const resultPanel = document.getElementById(`result-panel-${id}`);
        if (resultPanel) {
            resultPanel.style.display =
                material.processing_step === 'llm_translated'
                    ? 'block' : 'none';
        }
    }
}

// 使用示例
const stateManager = new MaterialStateManager();

// WebSocket监听
socket.on('material_updated', (data) => {
    stateManager.updateMaterial(data.material_id, {
        status: data.status,
        processing_step: data.processing_step,
        processing_progress: data.processing_progress
    });
});
```

---

## 八、状态流转决策树

```
当前状态是什么？
│
├─ uploaded → 可以开始OCR
│
├─ translated → 可以：
│   ├─ 启用实体识别
│   └─ 直接LLM翻译
│
├─ entity_pending_confirm → 必须：
│   ├─ 确认实体
│   ├─ 编辑实体
│   └─ 或跳过
│
├─ entity_confirmed → 可以开始LLM翻译
│
├─ llm_translated → 可以：
│   ├─ 导出结果
│   └─ AI修订文本
│
└─ failed → 检查失败原因，可能需要重试
```

---

## 九、常见问题

### Q1: 如何判断是否需要显示实体识别选项？
```javascript
function shouldShowEntityOption(material) {
    return material.processing_step === 'translated' &&
           !material.entity_recognition_enabled;
}
```

### Q2: 如何判断是否在等待用户确认？
```javascript
function isWaitingForConfirmation(material) {
    return material.processing_step === 'entity_pending_confirm';
}
```

### Q3: 如何知道整个流程是否完成？
```javascript
function isFullyCompleted(material) {
    return material.processing_step === 'llm_translated' &&
           material.status === 'completed';
}
```

### Q4: 如何处理长时间运行的操作？
```javascript
// 设置合理的超时
const TIMEOUTS = {
    ocr: 60000,        // 60秒
    entity_fast: 10000,     // 10秒
    entity_deep: 120000,    // 120秒
    llm: 120000            // 120秒
};

// 带超时的请求
async function requestWithTimeout(promise, timeout) {
    const timeoutPromise = new Promise((_, reject) =>
        setTimeout(() => reject(new Error('请求超时')), timeout)
    );
    return Promise.race([promise, timeoutPromise]);
}
```

---

*文档版本：1.0*
*创建日期：2024-11-18*
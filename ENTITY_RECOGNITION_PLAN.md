# 实体识别功能 - 未来开发计划

## 项目概述

实体识别功能已成功集成到翻译平台后端，作为 OCR 翻译和 LLM 翻译之间的可选卡关步骤。

**当前状态**: ✅ 架构完成，预留接口，等待实际 API 对接

**创建时间**: 2025-10-27
**负责人**: Translation Platform Team

---

## 功能架构

### 流程图

```
上传图片
  ↓
OCR翻译(百度API)
  ↓
是否启用实体识别?
  ├─ 否 → LLM翻译(可选) → 前端编辑 → 生成最终图片
  └─ 是 → 实体识别API → 返回实体列表
         ↓
      前端显示实体
         ↓
      用户确认/编辑实体
         ↓
      提交翻译指导信息
         ↓
      LLM翻译(使用实体prompt) → 前端编辑 → 生成最终图片
```

### 卡关机制

1. **启用实体识别** → 材料的 `entity_recognition_enabled` 设置为 `true`
2. **OCR完成后** → 自动触发实体识别，状态变为 `ENTITY_PENDING_CONFIRM`
3. **等待用户确认** → 前端显示实体识别结果，用户可编辑
4. **用户确认** → 调用 `/api/materials/<id>/confirm-entities`，状态变为 `ENTITY_CONFIRMED`
5. **允许LLM翻译** → 只有确认后才能调用LLM翻译接口

**关键点**: 如果启用了实体识别但未确认，LLM翻译接口会返回 400 错误，强制用户先完成实体识别。

---

## 已完成工作

### 1. 数据库设计 ✅

#### 新增字段 (Material 模型)

| 字段名 | 类型 | 说明 |
|-------|------|------|
| `entity_recognition_enabled` | Boolean | 是否启用实体识别 |
| `entity_recognition_result` | Text (JSON) | 实体识别结果 |
| `entity_recognition_confirmed` | Boolean | 是否已确认实体 |
| `entity_user_edits` | Text (JSON) | 用户编辑的实体翻译指导 |
| `entity_recognition_error` | Text | 实体识别错误信息 |

#### 新增处理步骤 (ProcessingStep 枚举)

```python
ENTITY_RECOGNIZING = 'entity_recognizing'          # 实体识别中
ENTITY_PENDING_CONFIRM = 'entity_pending_confirm'  # 等待实体确认
ENTITY_CONFIRMED = 'entity_confirmed'              # 实体已确认
LLM_TRANSLATING = 'llm_translating'                # LLM翻译中
LLM_TRANSLATED = 'llm_translated'                  # LLM翻译完成
```

### 2. 实体识别服务 ✅

**文件**: `entity_recognition_service.py`

**核心类**: `EntityRecognitionService`

**主要方法**:
- `recognize_entities(ocr_result)` - 调用实体识别API（当前为桩实现）
- `_call_entity_recognition_api_stub()` - 模拟实体识别（返回示例数据）
- `_call_real_api()` - 真实API调用接口（预留实现）
- `save_entity_recognition_log()` - 保存实体识别日志

**数据格式**:
```json
{
  "success": true,
  "entities": [
    {
      "region_id": 0,
      "text": "张三在北京大学工作",
      "entities": [
        {
          "type": "PERSON",
          "value": "张三",
          "start": 0,
          "end": 2,
          "confidence": 0.95,
          "translation_suggestion": "Zhang San",
          "context": "人名"
        }
      ]
    }
  ],
  "total_entities": 10,
  "processing_time": 1.23
}
```

### 3. API 路由 ✅

#### 已实现的接口

| 路由 | 方法 | 说明 |
|------|------|------|
| `/api/materials/<id>/enable-entity-recognition` | POST | 启用/禁用实体识别 |
| `/api/materials/<id>/entity-recognition` | POST | 开始实体识别 |
| `/api/materials/<id>/entity-recognition-result` | GET | 获取实体识别结果 |
| `/api/materials/<id>/confirm-entities` | POST | 用户确认实体（卡关确认） |
| `/api/materials/<id>/llm-translate` | POST | LLM翻译（已集成实体检查） |

### 4. LLM 翻译集成 ✅

**文件**: `llm_service.py`

**修改内容**:
- `optimize_translations()` 方法新增 `entity_guidance` 参数
- `_build_optimization_prompt()` 方法集成实体翻译指导
- Prompt 中自动添加实体翻译规则

**Prompt 示例**:
```
SPECIAL TRANSLATION GUIDANCE (from Entity Recognition):

Person Names:
  - 张三 -> Zhang San
  - 李四 -> Li Si

Location Names:
  - 北京 -> Beijing
  - 上海 -> Shanghai

Organization Names:
  - 北京大学 -> Peking University

Special Terms:
  - 机器学习 -> Machine Learning

IMPORTANT: When you encounter any of the above entities in the text, use the exact translation provided.
```

### 5. 翻译流程集成 ✅

**文件**: `app.py` - `translate_one_material()` 函数

**集成逻辑**:
1. OCR 翻译完成后，检查 `entity_recognition_enabled`
2. 如果启用，自动调用实体识别服务
3. 保存实体识别结果，状态设为 `ENTITY_PENDING_CONFIRM`
4. 等待前端用户确认
5. 确认后，状态设为 `ENTITY_CONFIRMED`，允许继续LLM翻译
6. LLM 翻译时，检查是否已确认实体，未确认则拒绝翻译

---

## 待完成工作

### Phase 1: 实体识别 API 对接 🔴 高优先级

#### 任务清单

- [ ] 1.1 确定实体识别 API 提供商
  - 候选: OpenAI GPT-4, Azure AI Language, Google Cloud NLP, 自建模型
  - 评估标准: 准确率、成本、响应速度、支持的实体类型

- [ ] 1.2 获取 API 密钥和配置
  - 申请 API 密钥
  - 配置存储到 `config/entity_recognition_api_key.txt`
  - 配置 API 端点 URL

- [ ] 1.3 实现真实 API 调用
  - 修改 `entity_recognition_service.py` 中的 `_call_real_api()` 方法
  - 替换 `recognize_entities()` 中的桩实现
  - 处理 API 响应格式

- [ ] 1.4 错误处理和重试机制
  - 添加网络超时处理
  - 添加重试逻辑（最多 3 次）
  - 添加降级策略（API 失败时如何处理）

- [ ] 1.5 测试和验证
  - 单元测试
  - 集成测试
  - 性能测试

#### API 对接示例代码

```python
def _call_real_api(self, ocr_result: Dict) -> Dict:
    """调用真实的实体识别API"""
    headers = {
        "Authorization": f"Bearer {self.api_key}",
        "Content-Type": "application/json"
    }

    payload = {
        "ocr_result": ocr_result,
        "source_lang": ocr_result.get("sourceLang", "zh"),
        "target_lang": ocr_result.get("targetLang", "en"),
        "entity_types": ["PERSON", "LOCATION", "ORGANIZATION", "TERM"]
    }

    # 添加重试机制
    for attempt in range(3):
        try:
            response = requests.post(
                self.api_url,
                headers=headers,
                json=payload,
                timeout=self.timeout
            )
            response.raise_for_status()
            return response.json()
        except requests.exceptions.Timeout:
            if attempt == 2:
                raise
            time.sleep(2 ** attempt)  # 指数退避
        except requests.exceptions.RequestException as e:
            raise Exception(f"实体识别API调用失败: {str(e)}")
```

### Phase 2: 前端集成 🟡 中优先级

#### 任务清单

- [ ] 2.1 实体识别开关UI
  - 在材料详情页添加"启用实体识别"开关
  - 调用 `/api/materials/<id>/enable-entity-recognition`

- [ ] 2.2 实体识别结果显示
  - OCR 完成后，检测 `processingStep === 'entity_pending_confirm'`
  - 显示实体识别结果界面
  - 按实体类型分组显示（人名、地名、组织、术语）

- [ ] 2.3 实体编辑功能
  - 允许用户编辑实体翻译
  - 允许用户删除误识别的实体
  - 允许用户添加新实体

- [ ] 2.4 实体确认提交
  - 用户点击"确认"按钮
  - 构建 `translationGuidance` 对象
  - 调用 `/api/materials/<id>/confirm-entities`

- [ ] 2.5 卡关提示
  - 如果用户未确认实体就尝试LLM翻译
  - 显示友好提示："请先确认实体识别结果"

#### 前端数据流示例

```typescript
// 1. OCR完成后，轮询状态
if (material.processingStep === 'entity_pending_confirm') {
  // 获取实体识别结果
  const result = await fetch(`/api/materials/${id}/entity-recognition-result`);
  showEntityConfirmationModal(result.data);
}

// 2. 用户确认实体
async function confirmEntities() {
  const guidance = {
    persons: ["张三 -> Zhang San"],
    locations: ["北京 -> Beijing"],
    organizations: ["北京大学 -> Peking University"],
    terms: ["机器学习 -> Machine Learning"]
  };

  await fetch(`/api/materials/${id}/confirm-entities`, {
    method: 'POST',
    body: JSON.stringify({ translationGuidance: guidance })
  });

  // 现在可以进行LLM翻译了
  proceedToLLMTranslation();
}
```

### Phase 3: 性能优化 🟢 低优先级

#### 任务清单

- [ ] 3.1 批处理支持
  - 如果API支持，一次发送多个区域
  - 减少API调用次数，降低成本

- [ ] 3.2 实体缓存
  - 缓存常见实体的识别结果
  - 减少重复调用

- [ ] 3.3 异步调用优化
  - 使用异步HTTP客户端（aiohttp）
  - 提高并发性能

- [ ] 3.4 超时优化
  - 根据文本长度动态调整超时时间
  - 添加取消机制

### Phase 4: 功能增强 🟢 低优先级

#### 任务清单

- [ ] 4.1 实体类型扩展
  - 支持更多实体类型：日期、数字、产品名等
  - 可配置的实体类型选择

- [ ] 4.2 实体关联
  - 识别实体之间的关系
  - 提供上下文信息辅助翻译

- [ ] 4.3 用户词典
  - 允许用户创建自定义实体词典
  - 自动应用到实体识别

- [ ] 4.4 统计和分析
  - 实体识别准确率统计
  - 常见实体报告
  - 翻译质量对比（有/无实体识别）

---

## 技术规范

### 实体类型定义

| 类型 | 代码 | 说明 | 示例 |
|------|------|------|------|
| 人名 | `PERSON` | 中文人名、英文人名 | 张三、John Smith |
| 地名 | `LOCATION` | 城市、国家、地址 | 北京、New York |
| 组织 | `ORGANIZATION` | 公司、学校、机构 | 北京大学、Google |
| 术语 | `TERM` | 专业术语、领域词汇 | 机器学习、AI |
| 日期 | `DATE` | 日期时间 | 2025年10月27日 |
| 数字 | `NUMBER` | 数字、金额 | 1000、$100 |
| 产品 | `PRODUCT` | 产品名称 | iPhone、ChatGPT |
| 事件 | `EVENT` | 事件名称 | 世界杯、奥运会 |

### API 响应格式标准

```json
{
  "success": true,
  "entities": [
    {
      "region_id": 0,
      "text": "原始文本",
      "entities": [
        {
          "type": "PERSON",
          "value": "实体值",
          "start": 0,
          "end": 2,
          "confidence": 0.95,
          "translation_suggestion": "建议翻译",
          "context": "上下文信息"
        }
      ]
    }
  ],
  "total_entities": 10,
  "processing_time": 1.23,
  "api_version": "v1",
  "error": null
}
```

### 错误处理标准

```json
{
  "success": false,
  "entities": [],
  "total_entities": 0,
  "processing_time": 0,
  "error": {
    "code": "API_ERROR",
    "message": "错误描述",
    "details": "详细信息"
  }
}
```

---

## 测试计划

### 单元测试

- [ ] 实体识别服务测试
- [ ] API 路由测试
- [ ] LLM Prompt 构建测试
- [ ] 数据库模型测试

### 集成测试

- [ ] 完整流程测试（OCR → 实体识别 → 确认 → LLM）
- [ ] 卡关逻辑测试（未确认时拒绝LLM）
- [ ] 错误处理测试（API失败、超时等）

### 性能测试

- [ ] 大量实体识别测试（100+ 实体）
- [ ] 并发测试（多个材料同时识别）
- [ ] 响应时间测试（<5秒完成识别）

### 用户验收测试

- [ ] 前端UI测试
- [ ] 实体编辑功能测试
- [ ] 翻译质量对比测试（有/无实体识别）

---

## 部署检查清单

### 环境准备

- [ ] 安装依赖包（如有新增）
- [ ] 配置实体识别 API 密钥
- [ ] 运行数据库迁移（新增字段）
- [ ] 创建日志目录 `outputs/logs/entity_recognition/`

### 数据库迁移

```bash
# 1. 生成迁移文件
flask db migrate -m "Add entity recognition fields"

# 2. 应用迁移
flask db upgrade

# 3. 验证字段
flask shell
>>> from app import Material
>>> Material.__table__.columns.keys()
```

### 配置检查

- [ ] `config/entity_recognition_api_key.txt` 存在且有效
- [ ] API 端点 URL 正确配置
- [ ] 日志目录权限正确
- [ ] WebSocket 推送测试

### 回归测试

- [ ] 现有翻译流程不受影响（未启用实体识别时）
- [ ] OCR 翻译正常工作
- [ ] LLM 翻译正常工作（无实体识别时）
- [ ] 前端所有功能正常

---

## 监控和日志

### 日志文件

| 文件路径 | 说明 |
|---------|------|
| `logs/server.log` | 主应用日志 |
| `outputs/logs/entity_recognition/entity_recognition_*.txt` | 实体识别详细日志 |

### 监控指标

- 实体识别成功率
- 平均识别时间
- API 调用次数和成本
- 用户确认率（多少用户确认vs跳过）

### 告警规则

- 实体识别失败率 > 10%
- 平均识别时间 > 10秒
- API 调用失败率 > 5%

---

## 成本估算

### API 调用成本（假设）

- 实体识别 API: $0.001/请求
- 平均每个材料: 1 次调用
- 月处理量: 10,000 材料
- **月成本**: $10

### 性能影响

- OCR → 实体识别 → LLM 总时间增加: 约 2-5 秒
- 用户可选择性跳过，不影响紧急翻译需求

---

## 常见问题 (FAQ)

### Q1: 实体识别是必须的吗？
**A**: 不是。实体识别是可选功能，用户可以选择启用或禁用。如果禁用，翻译流程和之前完全一样。

### Q2: 如果实体识别失败会怎样？
**A**: 系统会记录错误，但不会阻止翻译流程继续。用户可以跳过实体识别，直接进行LLM翻译。

### Q3: 实体识别支持哪些语言？
**A**: 当前主要支持中文到英文的翻译。未来可扩展到其他语言对。

### Q4: 用户可以修改实体翻译吗？
**A**: 可以。前端会显示识别到的实体，用户可以编辑翻译建议，然后提交给LLM作为翻译指导。

### Q5: 实体识别会增加多少时间？
**A**: 通常 2-5 秒，取决于文本长度和实体数量。这是异步处理的，不会阻塞用户操作。

### Q6: 如何对接自己的实体识别模型？
**A**: 修改 `entity_recognition_service.py` 中的 `_call_real_api()` 方法，指向你的模型API即可。只要返回格式符合规范，系统会自动集成。

---

## 联系方式

**技术支持**: Translation Platform Team
**文档维护**: 请在 GitHub Issues 中提出问题
**最后更新**: 2025-10-27

---

## 附录

### A. 实体识别 API 选型对比

| 提供商 | 优点 | 缺点 | 成本 | 推荐度 |
|--------|------|------|------|--------|
| OpenAI GPT-4 | 准确率高、支持自定义 | 成本较高 | $0.002/req | ⭐⭐⭐⭐ |
| Azure AI Language | 专业NER、多语言 | 需要Azure账号 | $0.001/req | ⭐⭐⭐⭐⭐ |
| Google Cloud NLP | 稳定可靠 | 配置复杂 | $0.0015/req | ⭐⭐⭐ |
| SpaCy (自建) | 免费、可控 | 需要维护 | 服务器成本 | ⭐⭐⭐ |

### B. 相关资源

- [百度翻译API文档](https://fanyi-api.baidu.com/doc/21)
- [OpenAI API文档](https://platform.openai.com/docs)
- [Azure AI Language文档](https://learn.microsoft.com/azure/ai-services/language-service/)
- [SpaCy NER文档](https://spacy.io/usage/linguistic-features#named-entities)

### C. 数据库Schema

```sql
-- 实体识别相关字段
ALTER TABLE materials ADD COLUMN entity_recognition_enabled BOOLEAN DEFAULT FALSE;
ALTER TABLE materials ADD COLUMN entity_recognition_result TEXT;
ALTER TABLE materials ADD COLUMN entity_recognition_confirmed BOOLEAN DEFAULT FALSE;
ALTER TABLE materials ADD COLUMN entity_user_edits TEXT;
ALTER TABLE materials ADD COLUMN entity_recognition_error TEXT;
```

---

**文档版本**: 1.0
**状态**: ✅ 架构完成，等待API对接
**下一步**: Phase 1 - 实体识别 API 对接

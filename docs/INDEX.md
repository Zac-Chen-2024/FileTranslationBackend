# 前端开发文档中心

## 📚 文档列表

| 文档名称 | 说明 | 重要程度 |
|---------|------|----------|
| [QUICK_REFERENCE.md](./QUICK_REFERENCE.md) | **快速参考指南** - 最常用的API和状态速查 | ⭐⭐⭐⭐⭐ |
| [API_DOCUMENTATION.md](./API_DOCUMENTATION.md) | **完整API手册** - 所有接口的详细说明 | ⭐⭐⭐⭐⭐ |
| [STATE_FLOW_GUIDE.md](./STATE_FLOW_GUIDE.md) | **状态流程指南** - 状态管理和流转逻辑 | ⭐⭐⭐⭐ |
| [FRONTEND_ENTITY_RECOGNITION_SPEC.md](./FRONTEND_ENTITY_RECOGNITION_SPEC.md) | **实体识别集成** - 实体识别功能的UI和交互 | ⭐⭐⭐⭐ |

---

## 🚀 快速开始指引

### 第1步：理解基础概念
先阅读 **[QUICK_REFERENCE.md](./QUICK_REFERENCE.md)**，快速了解：
- 核心API端点
- 材料状态管理
- 实体识别三种模式

### 第2步：深入了解API
查看 **[API_DOCUMENTATION.md](./API_DOCUMENTATION.md)**，包含：
- 完整的API接口列表
- 详细的请求/响应格式
- WebSocket事件说明
- 完整的代码示例

### 第3步：理解状态流转
阅读 **[STATE_FLOW_GUIDE.md](./STATE_FLOW_GUIDE.md)**，掌握：
- `status`和`processing_step`的区别
- 状态流转规则
- 前端判断逻辑

### 第4步：实体识别集成
参考 **[FRONTEND_ENTITY_RECOGNITION_SPEC.md](./FRONTEND_ENTITY_RECOGNITION_SPEC.md)**，了解：
- UI交互流程设计
- 三种模式的实现方式
- Vue.js代码示例

---

## 🔑 最重要的概念

### 1. 两个状态字段
```javascript
material.status          // 大状态: pending/processing/completed/failed
material.processing_step // 具体步骤: uploaded/translating/translated/...
```

### 2. 核心流程
```
上传 → OCR → [实体识别] → LLM优化 → 导出
         ↑ 可选步骤
```

### 3. 实体识别三种模式

| 模式 | 特点 | API调用 |
|------|------|---------|
| **深度模式** | 全自动，1-2分钟 | `/entity-recognition/deep` |
| **标准+AI** | 快速+AI优化 | `/fast` → `/manual-adjust` |
| **标准+人工** | 快速+人工编辑 | `/fast` → 前端编辑 |

### 4. 重要规则
- ⚠️ 启用实体识别后，必须确认才能LLM翻译
- ⏱️ Deep模式需要30-120秒，需要loading提示
- 🔒 处理中的材料不能重复发起请求

---

## 💬 常见问题

**Q: 如何判断材料当前可以执行什么操作？**
A: 查看 `processing_step` 字段，参考 QUICK_REFERENCE.md 中的状态表

**Q: 实体识别是必须的吗？**
A: 不是，完全可选。用户可以跳过直接进行LLM翻译

**Q: Deep模式和Fast模式的主要区别？**
A: Deep全自动但耗时长(1-2分钟)，Fast快速但需要用户确认

**Q: WebSocket是必须的吗？**
A: 强烈推荐，可以实时获取状态更新，避免轮询

---

## 📞 联系方式

如有疑问，请联系后端开发团队

---

*文档更新于 2024-11-18*
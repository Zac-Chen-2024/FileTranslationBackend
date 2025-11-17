# 公司查询API 使用手册

## 服务概述

**公司查询API** 是一个基于大语言模型和Google搜索的智能公司信息查询服务。通过输入公司名称、产品名称或品牌名称，系统会自动：
1. 识别实体名称
2. 通过Google搜索找到官方信息
3. 提取官方英文名称
4. 返回结果及来源

## 服务端点

### 内部访问（本地开发）
- **基础URL**: `http://localhost:5050`
- **健康检查**: `GET http://localhost:5050/health`
- **公司查询**: `POST http://localhost:5050/analyze`

### 外部访问（互联网）
- **基础URL**: `https://tns.drziangchen.uk/api/entity`
- **健康检查**: `GET https://tns.drziangchen.uk/api/entity/health`
- **公司查询**: `POST https://tns.drziangchen.uk/api/entity/analyze`

---

## API 接口

### 1. 健康检查

检查服务是否正常运行。

**请求**
```http
GET /health
```

**响应**
```json
{
  "status": "healthy",
  "service": "Entity Recognition and Translation"
}
```

---

### 2. 公司查询

查询公司、产品或品牌的官方英文名称。

**请求**
```http
POST /analyze
Content-Type: application/json
```

**请求体格式**

方式1：使用类别前缀（推荐）
```json
{
  "text": "公司查询：王者荣耀"
}
```

方式2：使用category参数
```json
{
  "text": "王者荣耀",
  "category": "company"
}
```

方式3：直接查询（默认为公司查询）
```json
{
  "text": "天津视达佳科技有限公司"
}
```

**参数说明**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| text | string | 是 | 查询内容，支持前缀"公司查询："或"企业查询：" |
| category | string | 否 | 查询类别，当前仅支持"company" |

**支持的类别前缀**
- `公司查询：`
- `企业查询：`
- `company:`

**响应格式（成功）**
```json
{
  "success": true,
  "count": 1,
  "entities": [
    {
      "chinese_name": "王者荣耀",
      "english_name": "Honor of Kings",
      "source": "https://www.honorofkings.com/",
      "confidence": "high"
    }
  ]
}
```

**响应格式（失败）**
```json
{
  "success": false,
  "error": "错误描述"
}
```

**字段说明**

| 字段 | 类型 | 说明 |
|------|------|------|
| success | boolean | 请求是否成功 |
| count | integer | 识别到的实体数量 |
| entities | array | 实体信息列表 |
| chinese_name | string | 中文名称 |
| english_name | string | 英文名称 |
| source | string | 信息来源URL |
| confidence | string | 置信度（high/medium/low） |

---

## 使用示例

> **提示**: 以下示例使用外部访问地址。如果在本地开发，请将 `https://tns.drziangchen.uk/api/entity` 替换为 `http://localhost:5050`

### 示例1：查询游戏公司

**请求（外部访问）**
```bash
curl -X POST https://tns.drziangchen.uk/api/entity/analyze \
  -H "Content-Type: application/json" \
  -d '{
    "text": "公司查询：王者荣耀"
  }'
```

**请求（本地开发）**
```bash
curl -X POST http://localhost:5050/analyze \
  -H "Content-Type: application/json" \
  -d '{
    "text": "公司查询：王者荣耀"
  }'
```

**响应**
```json
{
  "success": true,
  "count": 1,
  "entities": [
    {
      "chinese_name": "王者荣耀",
      "english_name": "Honor of Kings",
      "source": "https://www.honorofkings.com/en/",
      "confidence": "high"
    }
  ]
}
```

### 示例2：查询科技公司

**请求（外部访问）**
```bash
curl -X POST https://tns.drziangchen.uk/api/entity/analyze \
  -H "Content-Type: application/json" \
  -d '{
    "text": "公司查询：天津视达佳科技有限公司"
  }'
```

**响应**
```json
{
  "success": true,
  "count": 1,
  "entities": [
    {
      "chinese_name": "天津视达佳科技有限公司",
      "english_name": "Mastervision Technology Co., LTD",
      "source": "https://mastervision.cn/en/",
      "confidence": "high"
    }
  ]
}
```

### 示例3：查询多个实体

**请求（外部访问）**
```bash
curl -X POST https://tns.drziangchen.uk/api/entity/analyze \
  -H "Content-Type: application/json" \
  -d '{
    "text": "公司查询：腾讯公司推出了微信，与阿里巴巴的支付宝竞争"
  }'
```

**响应**
```json
{
  "success": true,
  "count": 2,
  "entities": [
    {
      "chinese_name": "腾讯公司",
      "english_name": "Tencent Holdings Limited",
      "source": "https://www.tencent.com/en-us/",
      "confidence": "high"
    },
    {
      "chinese_name": "阿里巴巴",
      "english_name": "Alibaba Group Holding Limited",
      "source": "https://www.alibabagroup.com/en-US/",
      "confidence": "high"
    }
  ]
}
```

---

## 工作流程

系统采用多级fallback策略确保高准确率：

### 1. 类别解析
- 从文本中识别类别前缀（如"公司查询："）
- 或使用category参数指定类别
- 默认使用"company"类别

### 2. 实体识别
- 使用LLM提取公司/产品/品牌名称
- 保持用户输入的原始名称（如"王者荣耀"不会被转换为"腾讯公司"）

### 3. Google搜索
- 精确搜索：`"实体名称" English name official`
- 变体搜索：提取核心名称再搜索

### 4. 搜索结果评分
根据多个因素对搜索结果评分：
- Copyright + 实体名：+100分（最高优先级）
- 企业信息网站（企查查、36氪等）：+90分
- 官网标识：+80分
- 百科网站：+70分
- 标题匹配：+60分
- 摘要包含核心名：+40分

### 5. 英文名称提取

**5.1 从snippet提取**
- 分析TOP3搜索结果的标题和摘要
- 提取明确出现的英文名称

**5.2 深度页面分析**（snippet未找到时）
- 抓取TOP3候选网站的完整页面
- 自动检测并切换到英文版：
  - 方式1：查找带href的语言切换链接
  - 方式2：检测无href的EN元素并推断URL
  - 方式3：去除语言子域名前缀（cn. → 主域名）
- 从英文页面内容中提取公司名称

**5.3 域名搜索**（页面分析仍未找到时）
- 提取TOP3的域名核心
- 直接用域名搜索
- 重复上述流程

### 6. 返回结果
返回英文名称、来源URL和置信度

---

## 技术特性

### 智能语言检测
系统能够自动检测并获取英文版网页：

1. **带href的语言切换链接**
   ```html
   <a href="/en/">EN</a>
   <a href="?lang=en">English</a>
   ```

2. **无href的语言切换元素**
   ```html
   <a class="en">EN</a>
   ```
   系统会推断并尝试：
   - `domain.com/en/`
   - `/cn/` → `/en/`
   - `cn.domain.com` → `en.domain.com`

3. **语言子域名自动去除**
   ```
   cn.example.com → example.com
   zh.example.com → example.com
   ```

### 可靠信息源
优先从以下来源提取信息：
- **官方网站**：公司官网的关于我们、版权信息等
- **企业信息网站**：企查查、天眼查、36氪Pitch、Crunchbase等
- **百科网站**：维基百科、百度百科等

---

## 错误码

| 错误信息 | 说明 | 解决方法 |
|---------|------|---------|
| 请提供 text 字段 | 请求缺少text参数 | 确保请求体包含text字段 |
| 不支持的类别: XXX | 使用了不支持的类别 | 当前仅支持"company"类别 |
| 未识别到公司或机构名称 | 无法从输入中识别实体 | 检查输入是否为有效的公司/产品名称 |

---

## 最佳实践

### 1. 使用类别前缀（推荐）
```json
{
  "text": "公司查询：王者荣耀"
}
```
明确指定查询类别，避免歧义。

### 2. 直接输入完整公司名
```json
{
  "text": "公司查询：天津视达佳科技有限公司"
}
```
提供完整公司名可获得更准确的结果。

### 3. 查询产品或品牌
```json
{
  "text": "公司查询：微信"
}
```
系统会查询"微信"这个产品本身的信息，而不是腾讯公司。

### 4. 批量查询
如需查询多个实体，可在一个句子中提供：
```json
{
  "text": "公司查询：华为和小米的竞争"
}
```

---

## 配置说明

系统配置位于 `config.py`：

```python
# 服务配置
SERVER_HOST = '0.0.0.0'
SERVER_PORT = 5000
DEBUG = False

# Google API配置
GOOGLE_API_KEY = 'your-api-key'
GOOGLE_SEARCH_ENGINE_ID = 'your-engine-id'

# 第三方平台过滤
BLOCKED_DOMAINS = [
    'zhihu.com', 'baidu.com', 'bilibili.com',
    'youtube.com', 'twitter.com', 'facebook.com',
    # ...
]

# 企业信息网站
ENTERPRISE_INFO_SITES = {
    'qcc.com': '企查查',
    'tianyancha.com': '天眼查',
    'pitchhub.36kr.com': '36氪Pitch',
    'crunchbase.com': 'Crunchbase',
    # ...
}
```

---

## 系统要求

- Python 3.8+
- Ollama (运行 qwen3:4b 模型)
- Google Custom Search API 密钥
- 稳定的网络连接

---

## 版本历史

### v1.0.0 (当前版本)
- ✅ 支持公司查询类别
- ✅ 智能语言检测和英文页面获取
- ✅ 多级fallback策略
- ✅ 企业信息网站优先级
- ✅ 完整的日志记录

### 未来计划
- 🔜 产品查询类别
- 🔜 人物查询类别
- 🔜 缓存机制
- 🔜 批量查询优化

---

## 常见问题

**Q: 为什么查询"王者荣耀"不返回"腾讯公司"？**

A: 这是设计行为。使用"公司查询"类别时，系统会查询您输入的实体本身（"王者荣耀"这个游戏），而不是其母公司。如果您想查询腾讯公司，请直接输入"腾讯公司"。

**Q: 如何确保返回的是英文官网？**

A: 系统会自动检测并切换到英文版页面，包括：
- 自动识别EN/English链接
- 推断英文URL（如 /en/）
- 去除语言子域名前缀

返回的 `source` 字段会显示实际抓取的URL（通常是英文版）。

**Q: 为什么有些公司查不到？**

A: 可能原因：
1. 公司规模较小，网络信息有限
2. 没有官方英文名称
3. Google API配额用尽
4. 公司名称输入不准确

建议：提供完整的公司全称，或尝试不同的变体。

**Q: 如何提高查询准确率？**

A:
1. 使用"公司查询："前缀
2. 提供完整的公司名称
3. 确保输入的是公司/产品本身的名称

---

## 技术支持

如有问题或建议，请联系开发团队或提交Issue。

**日志查看**
```bash
# 查看服务日志
journalctl -u qwen-entity-translator -f

# 查看最近的错误
journalctl -u qwen-entity-translator --since "10 minutes ago" | grep ERROR
```

**服务管理**
```bash
# 重启服务
systemctl restart qwen-entity-translator

# 查看状态
systemctl status qwen-entity-translator

# 停止服务
systemctl stop qwen-entity-translator
```

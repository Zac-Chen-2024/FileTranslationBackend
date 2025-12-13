#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
实体识别服务模块

这个模块用于处理OCR识别后的实体识别功能。
实体识别API将识别文本中的关键实体（人名、地名、专业术语等），
帮助LLM进行更精确的翻译。

当前状态：预留接口，等待实际API对接

作者：Translation Platform Team
创建日期：2025-10-27
"""

import json
import os
import time
from datetime import datetime
from typing import Dict, List, Optional, Tuple
import requests


class EntityRecognitionService:
    """实体识别服务类"""

    def __init__(self, api_key: Optional[str] = None, api_url: Optional[str] = None):
        """
        初始化实体识别服务

        Args:
            api_key: 实体识别API密钥（可选，未来使用）
            api_url: 实体识别API地址（可选）
        """
        self.api_key = api_key
        # 使用外部地址
        self.api_url = api_url or "https://tns.drziangchen.uk/api/entity/analyze"
        self.timeout = 120  # API调用超时时间（秒），增加到120秒因为需要Google搜索

    def recognize_entities(self, ocr_result: Dict, mode: str = "fast") -> Dict:
        """
        对OCR识别结果进行实体识别

        Args:
            ocr_result: OCR识别结果，格式：
                {
                    "regions": [
                        {
                            "src": "原文",
                            "dst": "翻译",
                            "points": [...],
                            ...
                        }
                    ],
                    "sourceLang": "zh",
                    "targetLang": "en"
                }
            mode: 查询模式（兼容旧接口，内部会映射到 Entity API 的模式）
                - "fast" -> 映射到 Entity API 的 "identify" 模式（快速识别，~30秒）
                - "deep" -> 映射到 Entity API 的 "analyze" 模式（深度分析，~1-2分钟）
                - "manual_adjust" -> 用户编辑后的深度分析（使用 "analyze" 模式）

        Returns:
            实体识别结果，格式：
                {
                    "success": True/False,
                    "mode": "identify" | "analyze",
                    "entities": [
                        {
                            "chinese_name": "腾讯公司",
                            "english_name": "Tencent Holdings Limited",  # identify模式为None
                            "source": "https://www.tencent.com/",  # identify模式为None
                            "confidence": "high",  # identify模式为None
                            "type": "ORGANIZATION"
                        }
                    ],
                    "total_entities": 10,
                    "processing_time": 1.23,
                    "error": None
                }
        """
        print(f"[实体识别] 开始处理，模式: {mode}, 区域数量: {len(ocr_result.get('regions', []))}")

        try:
            # 根据模式调用不同的API
            if mode == "fast":
                result = self._call_fast_query(ocr_result)
            elif mode == "deep":
                result = self._call_deep_query(ocr_result)
            elif mode == "manual_adjust":
                result = self._call_manual_adjust(ocr_result)
            else:
                raise ValueError(f"不支持的模式: {mode}")

            # 不覆盖 API 返回的 mode，保持 Entity API 的实际模式（'identify' 或 'analyze'）
            print(f"[实体识别] {mode}模式 → {result.get('mode')}模式完成，识别到 {result.get('total_entities', 0)} 个实体")
            return result

        except Exception as e:
            print(f"[实体识别] 错误: {str(e)}")
            import traceback
            traceback.print_exc()

            # 返回错误但标记为可恢复，允许翻译流程继续
            return {
                "success": False,
                "mode": mode,
                "entities": [],
                "total_entities": 0,
                "processing_time": 0,
                "error": str(e),
                "recoverable": True,  # 标记为可恢复错误
                "message": "实体识别服务暂时不可用，但翻译流程可以继续"
            }

    def _call_fast_query(self, ocr_result: Dict) -> Dict:
        """
        快速查询模式 - 快速识别实体 + LLM初步翻译英文名
        对应 Entity API 的 "identify" 模式，但额外用LLM翻译

        Args:
            ocr_result: OCR识别结果

        Returns:
            快速识别的实体结果（包含LLM翻译的初步英文名）
        """
        # 第一步：调用identify API识别实体
        result = self._call_company_query_api(ocr_result, mode="identify")

        # 第二步：如果识别成功且有实体，用LLM翻译英文名
        if result.get('success') and result.get('entities'):
            result = self._add_llm_translations(result)

        return result

    def _add_llm_translations(self, result: Dict) -> Dict:
        """
        用LLM为识别出的实体添加初步英文翻译

        Args:
            result: identify模式的识别结果

        Returns:
            添加了英文翻译的结果
        """
        entities = result.get('entities', [])
        if not entities:
            return result

        # 提取所有中文实体名
        chinese_names = [e.get('chinese_name', '') for e in entities if e.get('chinese_name')]

        if not chinese_names:
            return result

        print(f"[实体识别] 使用LLM翻译 {len(chinese_names)} 个实体名称...")

        try:
            # 导入LLM服务
            from llm_service import LLMTranslationService
            llm_service = LLMTranslationService()

            if not llm_service.client:
                print("[实体识别] LLM服务未配置，跳过英文翻译")
                return result

            # 构建翻译prompt
            prompt = f"""请将以下中文公司/组织/品牌名称翻译为英文。
如果是知名公司，请使用其官方英文名称。
如果不确定，请提供合理的英文翻译。

请严格按照JSON格式返回，每个名称一行：
{{"中文名": "英文名"}}

中文名称列表：
{chr(10).join(chinese_names)}

请直接返回JSON对象，不要有其他文字："""

            # 调用LLM
            response = llm_service.client.chat.completions.create(
                model="gpt-4o-mini",  # 使用快速模型
                messages=[
                    {"role": "system", "content": "你是一个专业的翻译助手，专门翻译公司和组织名称。"},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.3,
                max_tokens=1000
            )

            # 解析响应
            response_text = response.choices[0].message.content.strip()
            print(f"[实体识别] LLM翻译响应: {response_text[:200]}...")

            # 尝试解析JSON
            try:
                # 清理可能的markdown代码块
                if response_text.startswith('```'):
                    response_text = response_text.split('```')[1]
                    if response_text.startswith('json'):
                        response_text = response_text[4:]
                response_text = response_text.strip()

                translations = json.loads(response_text)

                # 更新实体的英文名（标准模式不显示证据来源）
                for entity in entities:
                    chinese_name = entity.get('chinese_name', '')
                    if chinese_name in translations:
                        entity['english_name'] = translations[chinese_name]
                        # 标准模式不设置source，留空让用户可以直接使用或选择深度搜索

                print(f"[实体识别] LLM翻译完成，已更新 {len(translations)} 个实体的英文名")

            except json.JSONDecodeError as e:
                print(f"[实体识别] LLM响应解析失败: {e}")
                # 尝试逐行解析
                for line in response_text.split('\n'):
                    line = line.strip()
                    if ':' in line or '：' in line:
                        parts = line.replace('：', ':').split(':')
                        if len(parts) >= 2:
                            cn = parts[0].strip().strip('"\'{}')
                            en = parts[1].strip().strip('"\'{}，,')
                            for entity in entities:
                                if entity.get('chinese_name') == cn:
                                    entity['english_name'] = en
                                    # 标准模式不设置source

        except Exception as e:
            print(f"[实体识别] LLM翻译失败: {e}")
            import traceback
            traceback.print_exc()
            # 翻译失败不影响整体流程，返回原结果

        result['entities'] = entities
        return result

    def _call_deep_query(self, ocr_result: Dict) -> Dict:
        """
        深度查询模式 - 进行完整的Google搜索和官网分析
        对应 Entity API 的 "analyze" 模式

        Args:
            ocr_result: OCR识别结果

        Returns:
            深度查询的实体结果，包含准确的官方英文名称
        """
        return self._call_company_query_api(ocr_result, mode="analyze")

    def _call_manual_adjust(self, ocr_result: Dict) -> Dict:
        """
        人工调整模式 - 对用户编辑后的实体列表进行深度分析

        注意：Entity API 没有单独的 manual_adjust 模式。
        这个模式实际上是：先用 identify 快速识别，用户编辑后，
        再用 analyze 模式对选定的实体进行深度分析。

        这里直接使用 analyze 模式进行深度查询。

        Args:
            ocr_result: OCR识别结果（可能包含用户编辑的实体列表）

        Returns:
            深度分析后的实体结果
        """
        # 如果 ocr_result 中包含用户编辑的实体列表，使用两阶段查询
        if 'user_entities' in ocr_result and ocr_result['user_entities']:
            return self._call_analyze_with_entities(ocr_result['user_entities'])
        else:
            # 否则，直接对整个文本进行 analyze
            return self._call_company_query_api(ocr_result, mode="analyze")

    def _call_analyze_with_entities(self, entities_list: List[str]) -> Dict:
        """
        两阶段查询的第二阶段：直接提供实体列表进行深度分析

        这对应 Entity API 的推荐工作流：
        1. 第一阶段：使用 identify 模式快速识别所有实体
        2. 用户选择/编辑感兴趣的实体
        3. 第二阶段：使用此方法对选定实体进行深度分析

        Args:
            entities_list: 实体名称列表，如 ["腾讯公司", "阿里巴巴"]

        Returns:
            深度分析结果
        """
        start_time = time.time()

        if not entities_list:
            return {
                "success": True,
                "mode": "analyze",
                "entities": [],
                "total_entities": 0,
                "processing_time": 0,
                "error": None
            }

        print(f"[实体识别] 两阶段查询 - 对 {len(entities_list)} 个实体进行深度分析")
        print(f"[实体识别] 实体列表: {entities_list}")

        # 准备API请求
        headers = {"Content-Type": "application/json"}

        # 根据 Entity API 的两阶段查询规范
        payload = {
            "entities": entities_list,  # 直接提供实体数组
            "mode": "analyze"  # 深度分析模式
        }

        print(f"[实体识别] 调用API: {self.api_url}")
        print(f"[实体识别] Payload: {payload}")

        try:
            response = requests.post(
                self.api_url,
                headers=headers,
                json=payload,
                timeout=self.timeout
            )

            response.raise_for_status()
            api_result = response.json()

            print(f"[实体识别] API响应: {api_result}")

            # 转换API返回格式
            if api_result.get('success'):
                entities = api_result.get('entities', [])

                # 为每个实体添加type字段（默认为ORGANIZATION）
                for entity in entities:
                    if 'type' not in entity:
                        entity['type'] = 'ORGANIZATION'

                processing_time = time.time() - start_time

                return {
                    "success": True,
                    "mode": "analyze",
                    "entities": entities,
                    "total_entities": api_result.get('count', len(entities)),
                    "processing_time": processing_time,
                    "error": None
                }
            else:
                return {
                    "success": False,
                    "mode": "analyze",
                    "entities": [],
                    "total_entities": 0,
                    "processing_time": time.time() - start_time,
                    "error": api_result.get('error', 'API调用失败')
                }

        except requests.exceptions.Timeout:
            return {
                "success": False,
                "mode": "analyze",
                "entities": [],
                "total_entities": 0,
                "processing_time": time.time() - start_time,
                "error": f"API调用超时（超过{self.timeout}秒）"
            }
        except requests.exceptions.RequestException as e:
            return {
                "success": False,
                "mode": "analyze",
                "entities": [],
                "total_entities": 0,
                "processing_time": time.time() - start_time,
                "error": f"API调用失败: {str(e)}"
            }
        except Exception as e:
            return {
                "success": False,
                "mode": "analyze",
                "entities": [],
                "total_entities": 0,
                "processing_time": time.time() - start_time,
                "error": f"处理异常: {str(e)}"
            }

    def _call_company_query_api(self, ocr_result: Dict, mode: str = "identify") -> Dict:
        """
        调用公司查询API（https://tns.drziangchen.uk/api/entity/analyze）

        Args:
            ocr_result: OCR识别结果
            mode: 查询模式 - "identify" (快速识别) 或 "analyze" (深度分析)

        Returns:
            实体识别结果，格式：
                {
                    "success": True,
                    "mode": "identify" | "analyze",
                    "entities": [
                        # identify模式：
                        {"entity": "腾讯公司"}
                        # analyze模式：
                        {
                            "chinese_name": "腾讯",
                            "english_name": "Tencent Holdings Limited",
                            "source": "https://www.tencent.com/",
                            "confidence": "high",
                            "type": "ORGANIZATION"
                        }
                    ],
                    "total_entities": 2,
                    "processing_time": 1.23
                }
        """
        start_time = time.time()

        # 合并所有region的文本
        regions = ocr_result.get("regions", [])
        all_text = " ".join([r.get('src', '') for r in regions if r.get('src')])

        if not all_text.strip():
            return {
                "success": True,
                "mode": mode,
                "entities": [],
                "total_entities": 0,
                "processing_time": 0,
                "error": None
            }

        print(f"[实体识别] 合并后的文本: {all_text[:200]}...")

        # 准备API请求
        headers = {"Content-Type": "application/json"}

        # 根据 Entity API 规范构建 payload
        # 支持两种模式：identify (快速) 和 analyze (深度)
        payload = {
            "text": f"公司查询：{all_text}",
            "mode": mode  # "identify" 或 "analyze"
        }

        print(f"[实体识别] 模式: {mode}, Payload: {payload}")

        print(f"[实体识别] 调用API: {self.api_url}")
        print(f"[实体识别] 注意：API可能需要较长时间响应（Google搜索延迟）")

        try:
            # 调用公司查询API
            # 注意：由于需要进行Google搜索，此API可能响应较慢
            response = requests.post(
                self.api_url,
                headers=headers,
                json=payload,
                timeout=self.timeout
            )

            response.raise_for_status()
            api_result = response.json()

            print(f"[实体识别] API响应: {api_result}")

            # 转换API返回格式
            if api_result.get('success'):
                entities = api_result.get('entities', [])
                api_mode = api_result.get('mode', mode)

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
                    # analyze模式返回格式：
                    # [{"chinese_name": "...", "english_name": "...", "source": "...", "confidence": "high"}]
                    # 为每个实体添加type字段（默认为ORGANIZATION）
                    for entity in entities:
                        if 'type' not in entity:
                            entity['type'] = 'ORGANIZATION'

                processing_time = time.time() - start_time

                return {
                    "success": True,
                    "mode": api_mode,
                    "entities": entities,
                    "total_entities": api_result.get('count', len(entities)),
                    "processing_time": processing_time,
                    "error": None
                }
            else:
                # API返回失败
                return {
                    "success": False,
                    "mode": mode,
                    "entities": [],
                    "total_entities": 0,
                    "processing_time": time.time() - start_time,
                    "error": api_result.get('error', 'API调用失败')
                }

        except requests.exceptions.Timeout:
            return {
                "success": False,
                "entities": [],
                "total_entities": 0,
                "processing_time": time.time() - start_time,
                "error": f"API调用超时（超过{self.timeout}秒）"
            }
        except requests.exceptions.RequestException as e:
            return {
                "success": False,
                "entities": [],
                "total_entities": 0,
                "processing_time": time.time() - start_time,
                "error": f"API调用失败: {str(e)}"
            }
        except Exception as e:
            return {
                "success": False,
                "entities": [],
                "total_entities": 0,
                "processing_time": time.time() - start_time,
                "error": f"处理异常: {str(e)}"
            }

    def save_entity_recognition_log(self, material_id: str, material_name: str,
                                   ocr_result: Dict, entity_result: Dict):
        """
        保存实体识别日志

        Args:
            material_id: 材料ID
            material_name: 材料名称
            ocr_result: OCR识别结果
            entity_result: 实体识别结果
        """
        try:
            # 创建日志目录
            log_dir = os.path.join(os.path.dirname(__file__), 'outputs', 'logs', 'entity_recognition')
            os.makedirs(log_dir, exist_ok=True)

            # 生成日志文件名
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            safe_name = "".join(c for c in material_name if c.isalnum() or c in (' ', '-', '_'))[:50]
            log_filename = f"entity_recognition_{timestamp}_{safe_name}.txt"
            log_path = os.path.join(log_dir, log_filename)

            # 写入日志
            with open(log_path, 'w', encoding='utf-8') as f:
                f.write("=" * 80 + "\n")
                f.write(f"实体识别日志\n")
                f.write(f"材料ID: {material_id}\n")
                f.write(f"材料名称: {material_name}\n")
                f.write(f"时间: {datetime.now().isoformat()}\n")
                f.write("=" * 80 + "\n\n")

                f.write(f"总区域数: {len(ocr_result.get('regions', []))}\n")
                f.write(f"识别到的实体总数: {entity_result.get('total_entities', 0)}\n")
                f.write(f"处理耗时: {entity_result.get('processing_time', 0):.2f}秒\n\n")

                f.write("=" * 80 + "\n")
                f.write("详细结果\n")
                f.write("=" * 80 + "\n\n")

                for idx, entity in enumerate(entity_result.get("entities", []), 1):
                    f.write(f"\n实体 #{idx}\n")
                    f.write(f"中文名称: {entity.get('chinese_name', 'N/A')}\n")
                    f.write(f"英文名称: {entity.get('english_name', 'N/A')}\n")
                    f.write(f"置信度: {entity.get('confidence', 'N/A')}\n")
                    f.write(f"类型: {entity.get('type', 'ORGANIZATION')}\n")
                    if entity.get('source'):
                        f.write(f"信息来源: {entity.get('source')}\n")
                    f.write("\n")

                if entity_result.get('error'):
                    f.write("\n" + "=" * 80 + "\n")
                    f.write("错误信息\n")
                    f.write("=" * 80 + "\n")
                    f.write(f"{entity_result.get('error')}\n")

            print(f"[实体识别] 日志已保存: {log_path}")

        except Exception as e:
            print(f"[实体识别] 保存日志失败: {str(e)}")
            import traceback
            traceback.print_exc()


# ============================================================================
# 未来开发指南
# ============================================================================
"""
## 实体识别API对接指南

### 1. API要求

实体识别API应该接收OCR结果，并返回识别到的实体信息。

#### 请求格式示例：
```json
POST https://api.entity-recognition.example.com/v1/recognize
Authorization: Bearer YOUR_API_KEY
Content-Type: application/json

{
    "ocr_result": {
        "regions": [...],
        "sourceLang": "zh",
        "targetLang": "en"
    },
    "options": {
        "entity_types": ["PERSON", "LOCATION", "ORGANIZATION", "TERM"],
        "return_translation_suggestions": true
    }
}
```

#### 响应格式示例：
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
                    "translation_suggestion": "Zhang San"
                },
                {
                    "type": "ORGANIZATION",
                    "value": "北京大学",
                    "start": 3,
                    "end": 7,
                    "confidence": 0.98,
                    "translation_suggestion": "Peking University"
                }
            ]
        }
    ],
    "total_entities": 2,
    "processing_time": 1.23
}
```

### 2. 当前实现状态

**注意**: 实体识别API已集成完成，使用 `_call_company_query_api()` 方法调用外部API。

当前实现:
- `recognize_entities()` 方法根据mode参数调用不同的查询方法
- `_call_fast_query()` -> 调用 Entity API 的 "identify" 模式（快速识别）
- `_call_deep_query()` -> 调用 Entity API 的 "analyze" 模式（深度分析）
- `_call_manual_adjust()` -> 用户编辑后的深度分析
- `_call_company_query_api()` -> 实际的API调用实现

API端点: https://tns.drziangchen.uk/api/entity/analyze

### 3. 实体类型定义

建议的实体类型（可根据实际API调整）：

- **PERSON**: 人名（如：张三、John Smith）
- **LOCATION**: 地名（如：北京、New York）
- **ORGANIZATION**: 组织机构名（如：北京大学、Google）
- **TERM**: 专业术语（如：机器学习、Artificial Intelligence）
- **DATE**: 日期时间
- **NUMBER**: 数字、金额
- **PRODUCT**: 产品名称
- **EVENT**: 事件名称

### 4. 翻译建议格式

实体识别API应该为每个实体提供翻译建议，帮助LLM进行更准确的翻译：

- 人名：音译（Zhang San）或意译
- 地名：标准英文名称（Beijing）
- 组织：官方英文名称（Peking University）
- 术语：专业英文术语（Machine Learning）

### 5. 性能优化

- **批处理**：如果API支持，一次发送多个区域
- **缓存**：缓存常见实体的识别结果
- **异步调用**：使用异步方式调用API，提高并发性能
- **超时控制**：设置合理的超时时间，避免长时间等待

### 6. 错误处理

- **API调用失败**：记录错误，返回空结果，允许翻译流程继续
- **网络超时**：实施重试机制（最多3次）
- **响应格式错误**：验证API响应格式，处理异常情况
"""

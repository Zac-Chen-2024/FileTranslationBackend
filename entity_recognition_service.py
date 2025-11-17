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
            mode: 查询模式 - "fast"(快速), "deep"(深度), "manual_adjust"(人工调整模式)

        Returns:
            实体识别结果，格式：
                {
                    "success": True/False,
                    "mode": "fast/deep/manual_adjust",
                    "entities": [
                        {
                            "chinese_name": "腾讯公司",
                            "english_name": "Tencent Holdings Limited",
                            "source": "https://www.tencent.com/",
                            "confidence": "high",
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

            result['mode'] = mode
            print(f"[实体识别] {mode}模式完成，识别到 {result.get('total_entities', 0)} 个实体")
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

    def _call_entity_recognition_api_stub(self, ocr_result: Dict) -> Dict:
        """
        实体识别API调用的桩实现（Stub）

        这是一个临时实现，返回模拟数据。
        未来需要替换为真实的API调用。

        Args:
            ocr_result: OCR识别结果

        Returns:
            模拟的实体识别结果
        """
        start_time = time.time()

        # 提取所有文本区域
        regions = ocr_result.get("regions", [])

        # 模拟实体识别结果
        entities_result = []

        for idx, region in enumerate(regions):
            src_text = region.get("src", "")

            # 模拟实体识别：简单的关键词匹配（未来需要替换为真实API）
            detected_entities = self._stub_detect_entities(src_text)

            if detected_entities:
                entities_result.append({
                    "region_id": idx,
                    "text": src_text,
                    "entities": detected_entities
                })

        processing_time = time.time() - start_time
        total_entities = sum(len(r["entities"]) for r in entities_result)

        return {
            "success": True,
            "entities": entities_result,
            "total_entities": total_entities,
            "processing_time": processing_time,
            "error": None,
            "note": "这是模拟数据，实际API未对接"
        }

    def _stub_detect_entities(self, text: str) -> List[Dict]:
        """
        模拟实体检测（桩实现）

        未来需要替换为真实的实体识别逻辑

        Args:
            text: 待识别的文本

        Returns:
            实体列表
        """
        entities = []

        # 简单的示例：检测常见的中文人名模式
        # TODO: 替换为真实的实体识别API
        sample_persons = ["张三", "李四", "王五", "张伟", "刘明"]
        for person in sample_persons:
            if person in text:
                pos = text.index(person)
                entities.append({
                    "type": "PERSON",
                    "value": person,
                    "start": pos,
                    "end": pos + len(person),
                    "confidence": 0.9,
                    "translation_suggestion": f"{person} (transliteration)",
                    "context": "人名"
                })

        return entities

    def _call_fast_query(self, ocr_result: Dict) -> Dict:
        """
        快速查询模式 - 快速识别实体但不进行深度搜索

        Args:
            ocr_result: OCR识别结果

        Returns:
            快速识别的实体结果
        """
        return self._call_company_query_api(ocr_result, mode="fast")

    def _call_deep_query(self, ocr_result: Dict) -> Dict:
        """
        深度查询模式 - 进行完整的Google搜索和官网分析

        Args:
            ocr_result: OCR识别结果

        Returns:
            深度查询的实体结果，包含准确的官方英文名称
        """
        return self._call_company_query_api(ocr_result, mode="deep")

    def _call_manual_adjust(self, ocr_result: Dict) -> Dict:
        """
        人工调整模式 - 基于fast结果进行AI优化

        Args:
            ocr_result: OCR识别结果（应该包含fast查询的结果）

        Returns:
            AI优化后的实体结果
        """
        return self._call_company_query_api(ocr_result, mode="manual_adjust")

    def _call_company_query_api(self, ocr_result: Dict, mode: str = "fast") -> Dict:
        """
        调用公司查询API（https://tns.drziangchen.uk/api/entity/analyze）

        Args:
            ocr_result: OCR识别结果

        Returns:
            实体识别结果，格式：
                {
                    "success": True,
                    "entities": [
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
                "entities": [],
                "total_entities": 0,
                "processing_time": 0,
                "error": None
            }

        print(f"[实体识别] 合并后的文本: {all_text[:200]}...")

        # 准备API请求
        headers = {"Content-Type": "application/json"}

        # 准备API请求payload
        # 注意：当前API可能不支持mode参数，需要通过其他方式区分模式
        payload = {
            "text": f"公司查询：{all_text}"
        }

        # TODO: 根据实际API文档，添加不同模式的参数
        # 例如：
        # - fast模式可能需要参数 "quick": true
        # - deep模式可能需要参数 "thorough": true
        # - manual_adjust模式可能需要传递已有结果

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

                # 为每个实体添加type字段（默认为ORGANIZATION）
                for entity in entities:
                    if 'type' not in entity:
                        entity['type'] = 'ORGANIZATION'

                processing_time = time.time() - start_time

                return {
                    "success": True,
                    "entities": entities,
                    "total_entities": api_result.get('count', len(entities)),
                    "processing_time": processing_time,
                    "error": None
                }
            else:
                # API返回失败
                return {
                    "success": False,
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

    def _call_real_api(self, ocr_result: Dict) -> Dict:
        """
        调用真实的实体识别API

        这个函数将在未来实现，当前不调用。

        Args:
            ocr_result: OCR识别结果

        Returns:
            实体识别结果

        Raises:
            NotImplementedError: 当前未实现
        """
        # 准备API请求
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

        payload = {
            "ocr_result": ocr_result,
            "source_lang": ocr_result.get("sourceLang", "zh"),
            "target_lang": ocr_result.get("targetLang", "en"),
            "options": {
                "entity_types": ["PERSON", "LOCATION", "ORGANIZATION", "TERM"],
                "return_translation_suggestions": True
            }
        }

        # 调用API
        response = requests.post(
            self.api_url,
            headers=headers,
            json=payload,
            timeout=self.timeout
        )

        response.raise_for_status()
        return response.json()

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

### 2. 集成步骤

1. **获取API密钥**：联系实体识别API提供商获取API密钥
2. **配置API密钥**：将密钥保存到 `config/entity_recognition_api_key.txt`
3. **修改代码**：
   - 在 `recognize_entities()` 方法中，将 `_call_entity_recognition_api_stub()`
     替换为 `_call_real_api()`
   - 更新 `_call_real_api()` 中的API端点和请求格式
4. **测试**：使用真实数据测试API调用
5. **错误处理**：添加重试机制和错误处理逻辑

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

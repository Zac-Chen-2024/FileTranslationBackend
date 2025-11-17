#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
简单测试实体识别API - 单个实体
"""

from entity_recognition_service import EntityRecognitionService

def test_simple():
    """测试单个实体"""

    # 创建服务实例
    service = EntityRecognitionService()

    # 简单的OCR结果 - 只有一个公司名
    ocr_result = {
        "regions": [
            {
                "id": 0,
                "src": "腾讯公司",
                "dst": "Tencent Company",
                "points": []
            }
        ],
        "sourceLang": "zh",
        "targetLang": "en"
    }

    print("测试简单实体识别")
    print(f"文本: {ocr_result['regions'][0]['src']}")
    print(f"API: {service.api_url}")
    print(f"超时时间: {service.timeout}秒")
    print("\n调用中，请等待...")

    # 调用API
    result = service.recognize_entities(ocr_result)

    if result.get('success'):
        print(f"\n✓ 成功! 识别到 {result.get('total_entities', 0)} 个实体")
        for entity in result.get('entities', []):
            print(f"  - {entity.get('chinese_name')} → {entity.get('english_name')}")
    else:
        print(f"\n✗ 失败: {result.get('error')}")

    return result

if __name__ == '__main__':
    test_simple()
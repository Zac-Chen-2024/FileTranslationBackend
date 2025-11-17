#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试实体识别API集成
"""

from entity_recognition_service import EntityRecognitionService

def test_entity_recognition():
    """测试实体识别服务"""

    # 创建服务实例
    service = EntityRecognitionService()

    # 模拟OCR结果
    ocr_result = {
        "regions": [
            {
                "id": 0,
                "src": "腾讯公司推出了微信，与阿里巴巴的支付宝竞争",
                "dst": "Tencent Company launched WeChat to compete with Alibaba's Alipay",
                "points": [{"x": 0, "y": 0}, {"x": 100, "y": 100}]
            },
            {
                "id": 1,
                "src": "王者荣耀是一款流行的手机游戏",
                "dst": "Honor of Kings is a popular mobile game",
                "points": [{"x": 0, "y": 100}, {"x": 100, "y": 200}]
            }
        ],
        "sourceLang": "zh",
        "targetLang": "en"
    }

    print("=" * 80)
    print("测试实体识别API")
    print("=" * 80)
    print(f"\nOCR区域数量: {len(ocr_result['regions'])}")
    print("\nOCR文本内容:")
    for i, region in enumerate(ocr_result['regions']):
        print(f"  区域{i}: {region['src']}")

    print("\n" + "-" * 80)
    print("调用实体识别服务...")
    print("-" * 80)

    # 调用实体识别
    result = service.recognize_entities(ocr_result)

    print("\n" + "=" * 80)
    print("实体识别结果")
    print("=" * 80)

    if result.get('success'):
        print(f"\n✓ 识别成功")
        print(f"总实体数: {result.get('total_entities', 0)}")
        print(f"处理耗时: {result.get('processing_time', 0):.2f}秒")

        print("\n详细实体信息:")
        for i, entity in enumerate(result.get('entities', []), 1):
            print(f"\n  实体 #{i}:")
            print(f"    中文名: {entity.get('chinese_name')}")
            print(f"    英文名: {entity.get('english_name')}")
            print(f"    类型: {entity.get('type', 'ORGANIZATION')}")
            print(f"    置信度: {entity.get('confidence')}")
            if entity.get('source'):
                print(f"    来源: {entity.get('source')}")
    else:
        print(f"\n✗ 识别失败")
        print(f"错误: {result.get('error')}")

    print("\n" + "=" * 80)

    return result

if __name__ == '__main__':
    test_entity_recognition()

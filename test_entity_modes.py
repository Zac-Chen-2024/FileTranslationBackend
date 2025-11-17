#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试实体识别的三种模式
"""

from entity_recognition_service import EntityRecognitionService
import json
import time

def test_three_modes():
    """测试三种模式"""

    # 创建服务实例
    service = EntityRecognitionService()

    # 模拟OCR结果
    ocr_result = {
        "regions": [
            {
                "id": 0,
                "src": "腾讯公司推出了微信",
                "dst": "Tencent launched WeChat",
                "points": []
            },
            {
                "id": 1,
                "src": "阿里巴巴的支付宝",
                "dst": "Alibaba's Alipay",
                "points": []
            }
        ],
        "sourceLang": "zh",
        "targetLang": "en"
    }

    print("=" * 80)
    print("测试实体识别三种模式")
    print("=" * 80)
    print("\nOCR文本内容:")
    for region in ocr_result['regions']:
        print(f"  - {region['src']}")
    print("\n" + "=" * 80)

    # 1. 测试Fast模式
    print("\n[1] 测试 FAST 模式（快速查询）")
    print("-" * 40)
    print("特点：快速识别实体，不进行深度搜索")
    print("调用中...")

    start_time = time.time()
    fast_result = service.recognize_entities(ocr_result, mode="fast")
    fast_time = time.time() - start_time

    if fast_result.get('success'):
        print(f"✓ Fast模式成功 (耗时: {fast_time:.2f}秒)")
        print(f"  识别到 {fast_result.get('total_entities', 0)} 个实体")
        for entity in fast_result.get('entities', [])[:3]:  # 显示前3个
            print(f"  - {entity.get('chinese_name')} → {entity.get('english_name', '待查询')}")
    else:
        print(f"✗ Fast模式失败: {fast_result.get('error')}")

    # 2. 测试Deep模式
    print("\n[2] 测试 DEEP 模式（深度查询）")
    print("-" * 40)
    print("特点：完整Google搜索，获取官方英文名")
    print("注意：此模式可能需要较长时间（30-120秒）")
    print("调用中...")

    start_time = time.time()
    deep_result = service.recognize_entities(ocr_result, mode="deep")
    deep_time = time.time() - start_time

    if deep_result.get('success'):
        print(f"✓ Deep模式成功 (耗时: {deep_time:.2f}秒)")
        print(f"  识别到 {deep_result.get('total_entities', 0)} 个实体")
        for entity in deep_result.get('entities', []):
            print(f"  - {entity.get('chinese_name')} → {entity.get('english_name')}")
            if entity.get('source'):
                print(f"    来源: {entity.get('source')}")
    else:
        print(f"✗ Deep模式失败: {deep_result.get('error')}")

    # 3. 测试Manual Adjust模式
    print("\n[3] 测试 MANUAL_ADJUST 模式（人工调整/AI优化）")
    print("-" * 40)
    print("特点：基于fast结果进行AI优化")

    # 模拟包含fast结果的OCR数据
    ocr_with_fast = ocr_result.copy()
    if fast_result.get('success'):
        ocr_with_fast['fast_results'] = fast_result.get('entities', [])
        print(f"使用fast模式的 {len(ocr_with_fast['fast_results'])} 个结果作为输入")
    else:
        ocr_with_fast['fast_results'] = []
        print("没有fast结果，使用空列表")

    print("调用中...")

    start_time = time.time()
    manual_result = service.recognize_entities(ocr_with_fast, mode="manual_adjust")
    manual_time = time.time() - start_time

    if manual_result.get('success'):
        print(f"✓ Manual Adjust模式成功 (耗时: {manual_time:.2f}秒)")
        print(f"  优化了 {manual_result.get('total_entities', 0)} 个实体")
        for entity in manual_result.get('entities', []):
            print(f"  - {entity.get('chinese_name')} → {entity.get('english_name')}")
    else:
        print(f"✗ Manual Adjust模式失败: {manual_result.get('error')}")

    # 总结
    print("\n" + "=" * 80)
    print("测试总结")
    print("=" * 80)
    print(f"Fast模式: {'成功' if fast_result.get('success') else '失败'} (耗时: {fast_time:.2f}秒)")
    print(f"Deep模式: {'成功' if deep_result.get('success') else '失败'} (耗时: {deep_time:.2f}秒)")
    print(f"Manual Adjust模式: {'成功' if manual_result.get('success') else '失败'} (耗时: {manual_time:.2f}秒)")

    return {
        'fast': fast_result,
        'deep': deep_result,
        'manual_adjust': manual_result
    }

if __name__ == '__main__':
    test_three_modes()
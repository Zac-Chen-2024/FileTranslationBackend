#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""快速测试实体识别服务"""

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from entity_recognition_service import EntityRecognitionService
import json


def main():
    print("="*80)
    print("  快速测试：实体识别服务 API 调用")
    print("="*80 + "\n")

    service = EntityRecognitionService()

    # 测试数据
    ocr_result = {
        "regions": [
            {"src": "腾讯公司"}
        ],
        "sourceLang": "zh",
        "targetLang": "en"
    }

    print("测试 1: Fast 模式 (identify)")
    print("-"*80)
    print(f"输入文本: {ocr_result['regions'][0]['src']}\n")

    try:
        result = service.recognize_entities(ocr_result, mode="fast")

        print("返回结果:")
        print(json.dumps(result, indent=2, ensure_ascii=False))

        print("\n验证:")
        if result.get('success'):
            print(f"  ✅ 成功")
            print(f"  ✅ 模式: {result.get('mode')}")
            print(f"  ✅ 实体数量: {result.get('total_entities')}")

            if result.get('entities'):
                for i, entity in enumerate(result['entities'], 1):
                    print(f"\n  实体 {i}:")
                    print(f"    中文名: {entity.get('chinese_name')}")
                    print(f"    英文名: {entity.get('english_name')} (identify模式应为None)")
                    print(f"    类型: {entity.get('type')}")
        else:
            print(f"  ❌ 失败: {result.get('error')}")

    except Exception as e:
        print(f"❌ 异常: {str(e)}")
        import traceback
        traceback.print_exc()

    print("\n" + "="*80)
    print("测试完成！")
    print("="*80)


if __name__ == "__main__":
    main()

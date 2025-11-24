#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
实体识别服务测试脚本

测试修正后的实体识别服务与 Entity API 的集成
"""

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from entity_recognition_service import EntityRecognitionService
import json
import time


def print_section(title):
    """打印分隔线"""
    print("\n" + "="*80)
    print(f"  {title}")
    print("="*80 + "\n")


def print_result(result):
    """格式化打印结果"""
    print(json.dumps(result, indent=2, ensure_ascii=False))


def test_fast_mode():
    """测试 fast 模式（映射到 identify）"""
    print_section("测试 1: Fast 模式（快速识别）")

    service = EntityRecognitionService()

    # 模拟 OCR 结果
    ocr_result = {
        "regions": [
            {"src": "深圳市腾讯计算机系统有限公司"},
            {"src": "与阿里巴巴集团合作"},
            {"src": "推出了微信产品"}
        ],
        "sourceLang": "zh",
        "targetLang": "en"
    }

    print("📥 输入 OCR 结果:")
    print(f"  - {ocr_result['regions'][0]['src']}")
    print(f"  - {ocr_result['regions'][1]['src']}")
    print(f"  - {ocr_result['regions'][2]['src']}")
    print(f"\n⏱️  模式: fast (identify)")
    print(f"⏱️  预计时间: ~30秒\n")

    start_time = time.time()
    result = service.recognize_entities(ocr_result, mode="fast")
    elapsed_time = time.time() - start_time

    print(f"✅ 完成! 耗时: {elapsed_time:.2f}秒\n")
    print("📤 返回结果:")
    print_result(result)

    # 验证结果
    print("\n🔍 验证:")
    if result.get('success'):
        print(f"  ✅ API 调用成功")
        print(f"  ✅ 模式: {result.get('mode')}")
        print(f"  ✅ 识别到 {result.get('total_entities')} 个实体")

        if result.get('entities'):
            for i, entity in enumerate(result['entities'], 1):
                print(f"\n  实体 {i}:")
                print(f"    - 中文名: {entity.get('chinese_name')}")
                print(f"    - 英文名: {entity.get('english_name')} (identify模式应为None)")
                print(f"    - 来源: {entity.get('source')} (identify模式应为None)")
                print(f"    - 置信度: {entity.get('confidence')} (identify模式应为None)")
                print(f"    - 类型: {entity.get('type')}")
    else:
        print(f"  ❌ API 调用失败: {result.get('error')}")

    return result


def test_deep_mode():
    """测试 deep 模式（映射到 analyze）"""
    print_section("测试 2: Deep 模式（深度分析）")

    service = EntityRecognitionService()

    # 使用简单的测试数据（减少 API 调用时间）
    ocr_result = {
        "regions": [
            {"src": "腾讯公司"}
        ],
        "sourceLang": "zh",
        "targetLang": "en"
    }

    print("📥 输入 OCR 结果:")
    print(f"  - {ocr_result['regions'][0]['src']}")
    print(f"\n⏱️  模式: deep (analyze)")
    print(f"⏱️  预计时间: ~1-2分钟（包含 Google 搜索）\n")

    start_time = time.time()
    result = service.recognize_entities(ocr_result, mode="deep")
    elapsed_time = time.time() - start_time

    print(f"✅ 完成! 耗时: {elapsed_time:.2f}秒\n")
    print("📤 返回结果:")
    print_result(result)

    # 验证结果
    print("\n🔍 验证:")
    if result.get('success'):
        print(f"  ✅ API 调用成功")
        print(f"  ✅ 模式: {result.get('mode')}")
        print(f"  ✅ 识别到 {result.get('total_entities')} 个实体")

        if result.get('entities'):
            for i, entity in enumerate(result['entities'], 1):
                print(f"\n  实体 {i}:")
                print(f"    - 中文名: {entity.get('chinese_name')}")
                print(f"    - 英文名: {entity.get('english_name')} (analyze模式应有值)")
                print(f"    - 来源: {entity.get('source')}")
                print(f"    - 置信度: {entity.get('confidence')}")
                print(f"    - 类型: {entity.get('type')}")
    else:
        print(f"  ❌ API 调用失败: {result.get('error')}")
        if result.get('recoverable'):
            print(f"  ℹ️  这是可恢复错误，翻译流程可以继续")

    return result


def test_two_stage_query():
    """测试两阶段查询"""
    print_section("测试 3: 两阶段查询（推荐工作流）")

    service = EntityRecognitionService()

    print("第一阶段: 快速识别所有实体\n")

    # 第一阶段 OCR 结果
    ocr_result_stage1 = {
        "regions": [
            {"src": "腾讯公司与阿里巴巴合作"}
        ],
        "sourceLang": "zh",
        "targetLang": "en"
    }

    print("📥 输入 OCR 结果:")
    print(f"  - {ocr_result_stage1['regions'][0]['src']}")
    print(f"\n⏱️  模式: identify")

    start_time = time.time()
    stage1_result = service.recognize_entities(ocr_result_stage1, mode="fast")
    elapsed_time = time.time() - start_time

    print(f"\n✅ 第一阶段完成! 耗时: {elapsed_time:.2f}秒")
    print("\n📤 第一阶段结果:")
    print_result(stage1_result)

    if not stage1_result.get('success') or not stage1_result.get('entities'):
        print("\n❌ 第一阶段失败，无法继续第二阶段")
        return stage1_result

    # 模拟用户选择实体
    selected_entities = [
        entity['chinese_name']
        for entity in stage1_result['entities'][:2]  # 选择前2个
    ]

    print(f"\n\n用户选择了 {len(selected_entities)} 个实体进行深度分析:")
    for i, entity_name in enumerate(selected_entities, 1):
        print(f"  {i}. {entity_name}")

    print("\n" + "-"*80)
    print("\n第二阶段: 深度分析选定实体\n")
    print(f"⏱️  模式: analyze (直接提供实体列表)")
    print(f"⏱️  预计时间: ~1-2分钟\n")

    start_time = time.time()
    stage2_result = service._call_analyze_with_entities(selected_entities)
    elapsed_time = time.time() - start_time

    print(f"✅ 第二阶段完成! 耗时: {elapsed_time:.2f}秒\n")
    print("📤 第二阶段结果:")
    print_result(stage2_result)

    # 验证结果
    print("\n🔍 验证:")
    if stage2_result.get('success'):
        print(f"  ✅ 两阶段查询成功")
        print(f"  ✅ 第一阶段识别: {stage1_result.get('total_entities')} 个实体")
        print(f"  ✅ 第二阶段分析: {len(selected_entities)} 个选定实体")
        print(f"  ✅ 获得详细信息: {stage2_result.get('total_entities')} 个")

        if stage2_result.get('entities'):
            for i, entity in enumerate(stage2_result['entities'], 1):
                print(f"\n  实体 {i}:")
                print(f"    - 中文名: {entity.get('chinese_name')}")
                print(f"    - 英文名: {entity.get('english_name')}")
                print(f"    - 来源: {entity.get('source')}")
                print(f"    - 置信度: {entity.get('confidence')}")
    else:
        print(f"  ❌ 第二阶段失败: {stage2_result.get('error')}")

    return stage2_result


def test_direct_api_call():
    """直接测试 Entity API"""
    print_section("测试 4: 直接调用 Entity API")

    import requests

    api_url = "https://tns.drziangchen.uk/api/entity/analyze"

    # 测试 identify 模式
    print("📡 直接调用 Entity API (identify 模式)\n")

    payload = {
        "text": "公司查询：腾讯公司",
        "mode": "identify"
    }

    print(f"请求 URL: {api_url}")
    print(f"请求 Payload:")
    print(json.dumps(payload, indent=2, ensure_ascii=False))

    try:
        print("\n⏱️  发送请求...")
        response = requests.post(
            api_url,
            headers={"Content-Type": "application/json"},
            json=payload,
            timeout=60
        )

        print(f"✅ 响应状态码: {response.status_code}\n")

        if response.status_code == 200:
            result = response.json()
            print("📤 API 响应:")
            print_result(result)

            print("\n🔍 验证:")
            if result.get('success'):
                print(f"  ✅ Entity API 可用")
                print(f"  ✅ 模式: {result.get('mode')}")
                print(f"  ✅ 识别到 {result.get('count')} 个实体")
            else:
                print(f"  ❌ API 返回失败: {result.get('error')}")
        else:
            print(f"❌ HTTP 错误: {response.status_code}")
            print(f"响应内容: {response.text}")

    except requests.exceptions.Timeout:
        print("❌ 请求超时")
    except Exception as e:
        print(f"❌ 请求失败: {str(e)}")


def main():
    """主测试函数"""
    print("\n")
    print("╔" + "═"*78 + "╗")
    print("║" + " "*20 + "实体识别服务集成测试" + " "*36 + "║")
    print("║" + " "*20 + "Entity Recognition Service Test" + " "*27 + "║")
    print("╚" + "═"*78 + "╝")

    print("\n本测试将验证修正后的实体识别服务是否正确对接 Entity API")
    print("\n测试内容:")
    print("  1. Fast 模式 (identify) - 快速识别")
    print("  2. Deep 模式 (analyze) - 深度分析")
    print("  3. 两阶段查询 - 推荐工作流")
    print("  4. 直接 API 调用 - 验证 API 可用性")

    print("\n⚠️  注意:")
    print("  - 测试 2 和测试 3 需要调用 Google 搜索，可能需要 1-2 分钟")
    print("  - 如果 Entity API 不可用，部分测试可能失败")
    print("  - 所有测试都会生成详细日志\n")

    input("按 Enter 键开始测试...")

    try:
        # 测试 1: Fast 模式
        test_fast_mode()

        input("\n\n按 Enter 键继续下一个测试...")

        # 测试 2: Deep 模式
        test_deep_mode()

        input("\n\n按 Enter 键继续下一个测试...")

        # 测试 3: 两阶段查询
        test_two_stage_query()

        input("\n\n按 Enter 键继续下一个测试...")

        # 测试 4: 直接 API 调用
        test_direct_api_call()

        print_section("测试完成")
        print("✅ 所有测试已执行完毕！")
        print("\n请查看上面的输出来验证:")
        print("  1. API 调用格式是否正确")
        print("  2. 响应解析是否正确")
        print("  3. 不同模式是否正确映射")
        print("  4. 两阶段查询是否正常工作")

    except KeyboardInterrupt:
        print("\n\n⚠️  测试被用户中断")
    except Exception as e:
        print(f"\n\n❌ 测试过程中出现异常: {str(e)}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()

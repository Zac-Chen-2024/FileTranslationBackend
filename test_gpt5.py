#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""测试 GPT-5-mini API"""

import sys
import os

# 添加当前目录到路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import load_api_keys

def test_gpt5_mini():
    """测试 GPT-5-mini 模型"""
    print("=" * 60)
    print("开始测试 GPT-5-mini 模型")
    print("=" * 60)

    # 加载 API Key
    print("\n1. 加载 API Key...")
    api_keys = load_api_keys()
    api_key = api_keys.get('OPENAI_API_KEY')

    if not api_key:
        print("❌ 错误: OpenAI API Key 未配置")
        return

    print(f"✅ API Key 已加载: {api_key[:10]}...")

    # 初始化 OpenAI 客户端
    print("\n2. 初始化 OpenAI 客户端...")
    try:
        from openai import OpenAI
        client = OpenAI(api_key=api_key)
        print("✅ OpenAI 客户端初始化成功")
    except Exception as e:
        print(f"❌ 初始化失败: {e}")
        return

    # 测试文本
    test_text = "Hello World"
    test_instruction = "请将这段文本翻译成中文"

    print(f"\n3. 测试参数:")
    print(f"   原始文本: {test_text}")
    print(f"   修改要求: {test_instruction}")

    # 构建提示词
    prompt = f"""你是一个专业的文本编辑助手。

原始文本：
{test_text}

用户的修改要求：
{test_instruction}

请严格按照用户的要求修改文本，只返回修改后的文本内容，不要添加任何解释或说明。
重要提示：
1. 必须严格遵循用户的指令，不要进行任何额外的优化或改动
2. 如果用户要求仅做格式修改（如添加标点、换行、空格等），必须完整保留原文的所有内容，只调整格式
3. 如果用户要求保留原文，绝对不能删除、替换或改写任何原文内容
4. 保持原文的语言（如果是中文就用中文，英文就用英文）"""

    print("\n4. 调用 GPT-5-mini API...")
    try:
        response = client.chat.completions.create(
            model="gpt-5-mini",
            messages=[
                {"role": "system", "content": "你是一个专业的文本编辑助手，必须严格按照用户要求修改文本，不做任何额外的优化或改动。"},
                {"role": "user", "content": prompt}
            ],
            max_completion_tokens=500
        )

        print("✅ API 调用成功")

        # 打印完整响应
        print("\n5. API 响应详情:")
        print(f"   模型: {response.model}")
        print(f"   ID: {response.id}")
        print(f"   完成原因: {response.choices[0].finish_reason}")
        print(f"   Usage: {response.usage}")
        print(f"\n   完整 response.choices[0]:")
        print(f"   {response.choices[0]}")
        print(f"\n   message 对象: {response.choices[0].message}")
        print(f"   message.content 类型: {type(response.choices[0].message.content)}")
        print(f"   message.content repr: {repr(response.choices[0].message.content)}")

        # 提取结果
        revised_text = response.choices[0].message.content

        print("\n6. 结果:")
        print(f"   原始文本: {test_text}")
        print(f"   修改后文本: {revised_text}")
        print(f"   修改后文本长度: {len(revised_text) if revised_text else 0}")

        if revised_text:
            print(f"\n   完整内容:\n   ---\n   {revised_text}\n   ---")
            print("\n✅ 测试成功!")
        else:
            print("\n⚠️  警告: 返回内容为空")

    except Exception as e:
        print(f"❌ API 调用失败: {e}")
        import traceback
        traceback.print_exc()

    print("\n" + "=" * 60)
    print("测试完成")
    print("=" * 60)

if __name__ == "__main__":
    test_gpt5_mini()

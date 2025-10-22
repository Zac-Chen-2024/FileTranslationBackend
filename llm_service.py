"""LLM翻译优化服务模块 - 与Reference项目保持一致"""
from openai import OpenAI
import os
import re
import json
import datetime

class LLMTranslationService:
    def __init__(self, api_key=None, output_folder='outputs'):
        self.api_key = api_key or self._load_api_key()
        self.client = OpenAI(api_key=self.api_key) if self.api_key else None
        self.output_folder = output_folder
        # 创建日志目录
        os.makedirs(os.path.join(output_folder, 'logs'), exist_ok=True)

    def _load_api_key(self):
        """加载OpenAI API密钥"""
        key_path = 'config/openai_api_key.txt'
        if os.path.exists(key_path):
            with open(key_path, 'r', encoding='utf-8') as f:
                return f.read().strip()
        return None

    def optimize_translations(self, regions, batch_size=30):
        """
        优化翻译结果（支持批处理，避免超时）
        Args:
            regions: 百度翻译返回的区域列表
                [
                    {
                        'id': 0,
                        'src': '原文',
                        'dst': '百度翻译',
                        'points': [{'x': x1, 'y': y1}, {'x': x2, 'y': y2}, ...],
                        ...
                    },
                    ...
                ]
            batch_size: 每批处理的regions数量（默认30，避免超时和token限制）
        Returns:
            优化后的翻译列表
                [
                    {
                        'id': 0,
                        'translation': 'LLM优化翻译',
                        'original': '百度翻译'
                    },
                    ...
                ]
        """
        if not self.client:
            raise Exception("OpenAI API未配置，请在config/openai_api_key.txt中添加API密钥")

        # 如果regions数量较少，直接处理
        if len(regions) <= batch_size:
            return self._optimize_batch(regions)

        # 大量regions时，分批处理
        print(f"检测到 {len(regions)} 个区域，将分批处理（每批 {batch_size} 个）")
        all_translations = []

        for i in range(0, len(regions), batch_size):
            batch = regions[i:i+batch_size]
            batch_num = i // batch_size + 1
            total_batches = (len(regions) + batch_size - 1) // batch_size

            print(f"正在处理第 {batch_num}/{total_batches} 批（{len(batch)} 个区域）...")

            try:
                batch_translations = self._optimize_batch(batch)
                all_translations.extend(batch_translations)
                print(f"第 {batch_num} 批完成，已优化 {len(batch_translations)} 个区域")
            except Exception as e:
                print(f"第 {batch_num} 批处理失败: {str(e)}")
                # 继续处理下一批，而不是完全失败
                continue

        return all_translations

    def _optimize_batch(self, regions):
        """
        优化单批翻译结果
        """
        # 准备批量翻译文本
        source_texts = []
        region_id_list = []

        for region in regions:
            if region.get('src'):
                region_id = region.get('id', len(source_texts))
                source_texts.append(f"[{region_id}] {region['src']}")
                region_id_list.append(region_id)

        if not source_texts:
            return []

        # 构建GPT提示
        prompt = self._build_optimization_prompt(source_texts, len(source_texts))

        try:
            # 调用GPT API（增加max_tokens以支持更多翻译）
            response = self.client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[
                    {"role": "system", "content": "You are a professional Chinese-English translator."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.3,
                max_tokens=4000  # 增加token限制以支持更多翻译
            )

            # 解析结果
            llm_output = response.choices[0].message.content
            return self._parse_llm_output(llm_output, regions)

        except Exception as e:
            raise Exception(f"LLM翻译调用失败: {str(e)}")

    def _build_optimization_prompt(self, source_texts, count):
        """构建优化提示词"""
        prompt = f"""You are a Chinese-English translator. For each input text:

TRANSLATION RULES:
- Chinese characters (中文) → Translate to English
- English text → Keep unchanged
- Mixed Chinese-English → Translate only Chinese parts
- Names/Proper nouns → Translate appropriately
- Maintain professional and accurate translation

MANDATORY OUTPUT FORMAT:
1. You MUST output exactly {count} lines
2. Each line MUST start with [number] matching the input
3. Never skip any input
4. Format: [ID] Translation

INPUT TEXTS TO TRANSLATE:
{chr(10).join(source_texts)}

OUTPUT INSTRUCTIONS: Provide exactly {count} translated lines, each starting with the corresponding [ID] number."""

        return prompt

    def _parse_llm_output(self, llm_output, original_regions):
        """解析LLM输出"""
        lines = llm_output.strip().split('\n')
        translations = []

        for line in lines:
            line = line.strip()
            if not line:
                continue

            # 提取ID和翻译文本
            match = re.match(r'\[(\d+)\]\s*(.+)', line)
            if match:
                region_id = int(match.group(1))
                translation = match.group(2).strip()

                # 找到对应的原始区域
                original = next(
                    (r['dst'] for r in original_regions if r.get('id') == region_id),
                    ''
                )

                translations.append({
                    'id': region_id,
                    'translation': translation,
                    'original': original
                })

        return translations

    def save_llm_translation_log(self, filename, baidu_regions, llm_translations):
        """保存LLM翻译结果和对比日志（与Reference项目一致）"""
        try:
            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")

            # 1. 保存LLM翻译日志
            llm_log_filename = f"llm_translation_log_{timestamp}_{filename}.txt"
            llm_log_path = os.path.join(self.output_folder, 'logs', llm_log_filename)

            with open(llm_log_path, 'w', encoding='utf-8') as f:
                f.write("=" * 80 + "\n")
                f.write(f"LLM翻译日志 (ChatGPT优化)\n")
                f.write(f"时间: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write(f"原始文件: {filename}\n")
                f.write("=" * 80 + "\n\n")

                f.write("【LLM翻译统计】\n")
                f.write(f"总区域数: {len(llm_translations)}\n")
                total_src_chars = sum(len(r.get('src', '')) for r in baidu_regions)
                total_llm_chars = sum(len(t.get('translation', '')) for t in llm_translations)
                f.write(f"源文本总字符: {total_src_chars}\n")
                f.write(f"LLM译文总字符: {total_llm_chars}\n")
                f.write(f"翻译比例: {total_llm_chars / total_src_chars if total_src_chars > 0 else 1:.2f}\n")
                f.write("\n")

                f.write("【LLM详细翻译内容】\n")
                for i, translation in enumerate(llm_translations):
                    region_id = translation.get('id', i)
                    # 找到对应的原始区域
                    original_region = next((r for r in baidu_regions if r.get('id') == region_id), {})

                    f.write(f"\n--- 区域 {i+1} (ID: {region_id}) ---\n")
                    f.write(f"原文: {original_region.get('src', '')}\n")
                    f.write(f"LLM译文: {translation.get('translation', '')}\n")
                    if original_region.get('points'):
                        f.write(f"位置: {original_region.get('points')}\n")

            # 2. 保存三种翻译对比文件
            comparison_filename = f"translation_comparison_{timestamp}_{filename}.txt"
            comparison_path = os.path.join(self.output_folder, 'logs', comparison_filename)

            with open(comparison_path, 'w', encoding='utf-8') as f:
                f.write("=" * 100 + "\n")
                f.write(f"翻译对比报告\n")
                f.write(f"时间: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write(f"原始文件: {filename}\n")
                f.write("=" * 100 + "\n\n")

                f.write("本报告对比三种翻译结果：\n")
                f.write("1. 原文 (Chinese)\n")
                f.write("2. 百度API翻译 (Baidu API Translation)\n")
                f.write("3. GPT优化翻译 (GPT Optimized Translation)\n")
                f.write("\n" + "=" * 100 + "\n\n")

                # 创建翻译映射
                llm_map = {t.get('id'): t.get('translation', '') for t in llm_translations}

                for i, region in enumerate(baidu_regions):
                    region_id = region.get('id', i)
                    src_text = region.get('src', '')
                    baidu_dst = region.get('dst', '')
                    llm_dst = llm_map.get(region_id, '')

                    f.write(f"【区域 {i+1}】\n")
                    f.write(f"原文: {src_text}\n")
                    f.write(f"百度翻译: {baidu_dst}\n")
                    f.write(f"GPT翻译: {llm_dst}\n")
                    f.write("-" * 80 + "\n\n")

            print(f"LLM翻译日志已保存: {llm_log_path}")
            print(f"翻译对比文件已保存: {comparison_path}")

            return {
                'llm_log': llm_log_filename,
                'comparison': comparison_filename
            }

        except Exception as e:
            print(f"保存LLM日志失败: {str(e)}")
            return None

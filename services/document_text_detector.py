"""
专业文档文字检测服务 - 针对扫描文档优化
专门处理合同、证书、表格等正式文档
"""
import cv2
import numpy as np
import base64
from PIL import Image
import io
from typing import List, Tuple, Dict, Any
from sklearn.cluster import DBSCAN
import scipy.ndimage as ndimage


class DocumentTextDetector:
    """文档专用文字检测器"""

    def __init__(self):
        """初始化检测器参数"""
        # 文档类型检测参数
        self.doc_types = {
            'contract': {'min_lines': 5, 'has_seal': True},
            'form': {'has_table': True, 'regular_layout': True},
            'certificate': {'has_seal': True, 'center_aligned': True},
            'letter': {'paragraph_structure': True}
        }

        # 中文文档特殊参数
        self.chinese_params = {
            'char_min_width': 12,  # 中文字符最小宽度
            'char_max_width': 60,  # 中文字符最大宽度
            'line_height_ratio': 1.5,  # 中文行高比例
            'char_aspect_ratio': (0.7, 1.3)  # 中文字符宽高比范围
        }

    def detect_document_text(self, image_bytes: bytes) -> Dict[str, Any]:
        """
        文档文字检测主函数

        Args:
            image_bytes: 图片二进制数据

        Returns:
            检测结果字典
        """
        # 读取图片
        nparr = np.frombuffer(image_bytes, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

        if img is None:
            raise ValueError("无法读取图片")

        original = img.copy()
        height, width = img.shape[:2]

        # 1. 文档预处理（去噪、校正）
        preprocessed = self._preprocess_document(img)

        # 2. 检测文字行
        text_lines = self._detect_text_lines(preprocessed['binary'])

        # 3. 检测表格结构
        table_regions = self._detect_tables(preprocessed['binary'])

        # 4. 检测印章（作为特殊区域）
        seal_regions = self._detect_seals(original)

        # 5. 合并和优化区域
        all_regions = self._merge_regions(text_lines, table_regions, seal_regions)

        # 6. 生成智能背景
        background = self._create_clean_background(original, all_regions)

        # 7. 格式化输出
        return self._format_results(original, background, all_regions)

    def _preprocess_document(self, img: np.ndarray) -> Dict[str, np.ndarray]:
        """
        文档专用预处理
        """
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

        # 1. 去噪 - 使用双边滤波保持边缘
        denoised = cv2.bilateralFilter(gray, 9, 75, 75)

        # 2. 增强对比度
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        enhanced = clahe.apply(denoised)

        # 3. 二值化 - 使用自适应阈值（针对中文优化）
        # 中文文档通常字体较小且密集，需要更精细的阈值
        binary = cv2.adaptiveThreshold(
            enhanced, 255,
            cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY,
            31, 15  # 增大块大小以更好处理中文
        )

        # 4. 去除小噪点
        kernel = np.ones((2, 2), np.uint8)
        cleaned = cv2.morphologyEx(binary, cv2.MORPH_OPEN, kernel)

        # 5. 文字区域反转（使文字为白色）
        text_mask = cv2.bitwise_not(cleaned)

        return {
            'gray': gray,
            'enhanced': enhanced,
            'binary': cleaned,
            'text_mask': text_mask
        }

    def _detect_text_lines(self, binary: np.ndarray) -> List[Dict[str, Any]]:
        """
        检测文字行 - 使用投影分析（针对中文优化）
        """
        h, w = binary.shape
        text_lines = []

        # 反转图像（文字变白）
        inverted = cv2.bitwise_not(binary)

        # 中文文档形态学处理 - 连接相近的中文字符
        # 水平膨胀将同一行的字符连接
        horizontal_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (15, 1))
        connected = cv2.morphologyEx(inverted, cv2.MORPH_CLOSE, horizontal_kernel)

        # 水平投影
        horizontal_projection = np.sum(connected, axis=1) / 255

        # 找到文字行（针对中文调整阈值）
        line_threshold = w * 0.005  # 降低阈值以检测更多中文行
        min_line_height = 10  # 中文最小行高
        max_line_height = 80  # 中文最大行高
        in_line = False
        line_start = 0

        for y in range(h):
            if horizontal_projection[y] > line_threshold:
                if not in_line:
                    in_line = True
                    line_start = y
            else:
                if in_line:
                    in_line = False
                    line_end = y

                    # 检查行高是否合理（针对中文字体大小）
                    if min_line_height < (line_end - line_start) < max_line_height:
                        # 对每一行进行垂直投影找到文字块
                        line_img = inverted[line_start:line_end, :]
                        vertical_projection = np.sum(line_img, axis=0) / 255

                        # 找到文字块（合并中文字符）
                        words = self._find_chinese_text_blocks(
                            vertical_projection, line_start, line_end - line_start
                        )
                        text_lines.extend(words)

        return text_lines

    def _find_chinese_text_blocks(self, projection: np.ndarray, y_start: int, height: int) -> List[Dict[str, Any]]:
        """
        在文字行中找到中文文字块（整行合并）
        """
        blocks = []
        threshold = height * 0.05  # 更低的阈值以检测中文

        # 找到整行的起始和结束位置
        text_start = -1
        text_end = -1

        # 从左到右扫描找到第一个文字
        for x in range(len(projection)):
            if projection[x] > threshold:
                text_start = x
                break

        # 从右到左扫描找到最后一个文字
        for x in range(len(projection) - 1, -1, -1):
            if projection[x] > threshold:
                text_end = x + 1
                break

        # 如果找到文字，创建一个覆盖整行的区域
        if text_start != -1 and text_end != -1:
            # 扩展边界以确保包含所有中文字符
            margin = 5
            text_start = max(0, text_start - margin)
            text_end = min(len(projection), text_end + margin)

            blocks.append({
                'type': 'text',
                'bbox': {
                    'x': text_start,
                    'y': y_start - 2,  # 稍微扩展垂直边界
                    'width': text_end - text_start,
                    'height': height + 4
                },
                'confidence': 0.85,
                'lang': 'zh'  # 标记为中文
            })

        return blocks

    def _find_word_blocks(self, projection: np.ndarray, y_start: int, height: int) -> List[Dict[str, Any]]:
        """
        在文字行中找到单词/文字块
        """
        blocks = []
        threshold = height * 0.1  # 至少占行高的10%
        in_word = False
        word_start = 0

        for x in range(len(projection)):
            if projection[x] > threshold:
                if not in_word:
                    in_word = True
                    word_start = x
            else:
                if in_word:
                    in_word = False
                    word_end = x

                    # 合并相近的文字
                    if blocks and (word_start - blocks[-1]['bbox']['x'] - blocks[-1]['bbox']['width']) < 20:
                        # 扩展上一个块
                        blocks[-1]['bbox']['width'] = word_end - blocks[-1]['bbox']['x']
                    else:
                        # 添加新块
                        blocks.append({
                            'type': 'text',
                            'bbox': {
                                'x': word_start,
                                'y': y_start,
                                'width': word_end - word_start,
                                'height': height
                            },
                            'confidence': 0.85
                        })

        # 处理行末
        if in_word and blocks:
            blocks[-1]['bbox']['width'] = len(projection) - blocks[-1]['bbox']['x']

        return blocks

    def _detect_tables(self, binary: np.ndarray) -> List[Dict[str, Any]]:
        """
        检测表格结构
        """
        tables = []

        # 检测水平和垂直线
        horizontal_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (40, 1))
        vertical_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (1, 40))

        # 提取线条
        horizontal_lines = cv2.morphologyEx(binary, cv2.MORPH_OPEN, horizontal_kernel)
        vertical_lines = cv2.morphologyEx(binary, cv2.MORPH_OPEN, vertical_kernel)

        # 合并线条
        table_mask = cv2.add(horizontal_lines, vertical_lines)

        # 查找表格轮廓
        contours, _ = cv2.findContours(table_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        for contour in contours:
            area = cv2.contourArea(contour)
            if area > 5000:  # 最小表格面积
                x, y, w, h = cv2.boundingRect(contour)
                tables.append({
                    'type': 'table',
                    'bbox': {'x': x, 'y': y, 'width': w, 'height': h},
                    'confidence': 0.9
                })

        return tables

    def _detect_seals(self, img: np.ndarray) -> List[Dict[str, Any]]:
        """
        检测印章（红色圆形区域）
        """
        seals = []
        hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)

        # 红色范围
        lower_red1 = np.array([0, 50, 50])
        upper_red1 = np.array([10, 255, 255])
        lower_red2 = np.array([170, 50, 50])
        upper_red2 = np.array([180, 255, 255])

        # 创建红色掩码
        mask1 = cv2.inRange(hsv, lower_red1, upper_red1)
        mask2 = cv2.inRange(hsv, lower_red2, upper_red2)
        red_mask = cv2.bitwise_or(mask1, mask2)

        # 形态学处理
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
        red_mask = cv2.morphologyEx(red_mask, cv2.MORPH_CLOSE, kernel)

        # 查找轮廓
        contours, _ = cv2.findContours(red_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        for contour in contours:
            area = cv2.contourArea(contour)
            if 500 < area < 50000:  # 印章大小范围
                x, y, w, h = cv2.boundingRect(contour)

                # 检查是否接近圆形
                circularity = 4 * np.pi * area / (cv2.arcLength(contour, True) ** 2)
                if circularity > 0.5:  # 圆形度阈值
                    seals.append({
                        'type': 'seal',
                        'bbox': {'x': x, 'y': y, 'width': w, 'height': h},
                        'confidence': 0.95
                    })

        return seals

    def _merge_regions(self, text_lines: List, tables: List, seals: List) -> List[Dict[str, Any]]:
        """
        合并所有检测区域
        """
        all_regions = []
        region_id = 0

        # 添加文字行
        for line in text_lines:
            line['id'] = f'text_{region_id}'
            all_regions.append(line)
            region_id += 1

        # 添加表格
        for table in tables:
            table['id'] = f'table_{region_id}'
            all_regions.append(table)
            region_id += 1

        # 添加印章
        for seal in seals:
            seal['id'] = f'seal_{region_id}'
            all_regions.append(seal)
            region_id += 1

        # 移除重叠区域
        return self._remove_overlaps(all_regions)

    def _remove_overlaps(self, regions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        移除重叠的区域
        """
        if not regions:
            return []

        # 按面积排序（大的优先）
        regions.sort(key=lambda r: r['bbox']['width'] * r['bbox']['height'], reverse=True)

        final_regions = []
        for region in regions:
            overlap = False
            for existing in final_regions:
                iou = self._calculate_iou(region['bbox'], existing['bbox'])
                if iou > 0.5:
                    overlap = True
                    break

            if not overlap:
                final_regions.append(region)

        return final_regions

    def _calculate_iou(self, bbox1: Dict, bbox2: Dict) -> float:
        """
        计算两个边界框的IoU
        """
        x1 = max(bbox1['x'], bbox2['x'])
        y1 = max(bbox1['y'], bbox2['y'])
        x2 = min(bbox1['x'] + bbox1['width'], bbox2['x'] + bbox2['width'])
        y2 = min(bbox1['y'] + bbox1['height'], bbox2['y'] + bbox2['height'])

        if x2 < x1 or y2 < y1:
            return 0.0

        intersection = (x2 - x1) * (y2 - y1)
        area1 = bbox1['width'] * bbox1['height']
        area2 = bbox2['width'] * bbox2['height']
        union = area1 + area2 - intersection

        return intersection / union if union > 0 else 0.0

    def _create_clean_background(self, img: np.ndarray, regions: List[Dict[str, Any]]) -> np.ndarray:
        """
        创建干净的背景（移除文字）
        """
        height, width = img.shape[:2]
        mask = np.zeros((height, width), dtype=np.uint8)

        # 创建文字掩码
        for region in regions:
            if region['type'] in ['text', 'seal']:
                bbox = region['bbox']
                # 稍微扩大区域
                x = max(0, bbox['x'] - 2)
                y = max(0, bbox['y'] - 2)
                w = min(width - x, bbox['width'] + 4)
                h = min(height - y, bbox['height'] + 4)
                cv2.rectangle(mask, (x, y), (x + w, y + h), 255, -1)

        # 使用图像修复
        result = cv2.inpaint(img, mask, 3, cv2.INPAINT_TELEA)

        return result

    def _format_results(self, original: np.ndarray, background: np.ndarray,
                        regions: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        格式化输出结果
        """
        height, width = original.shape[:2]

        # 创建可视化图
        viz = self._create_visualization(original, regions)

        # 编码图片
        original_base64 = self._encode_image(original)
        background_base64 = self._encode_image(background)
        viz_base64 = self._encode_image(viz)

        # 统计信息
        text_regions = [r for r in regions if r['type'] == 'text']
        table_regions = [r for r in regions if r['type'] == 'table']
        seal_regions = [r for r in regions if r['type'] == 'seal']
        chinese_regions = [r for r in regions if r.get('lang') == 'zh']

        return {
            'original_image': original_base64,
            'background_image': background_base64,
            'detection_visualization': viz_base64,
            'text_regions': regions,
            'original_size': {'width': width, 'height': height},
            'statistics': {
                'total_regions_detected': len(regions),
                'text_regions': len(text_regions),
                'chinese_text_regions': len(chinese_regions),
                'table_regions': len(table_regions),
                'seal_regions': len(seal_regions),
                'high_confidence_regions': len([r for r in regions if r.get('confidence', 0) > 0.8]),
                'average_confidence': np.mean([r.get('confidence', 0.8) for r in regions]) if regions else 0,
                'document_type': 'chinese_document' if len(chinese_regions) > 0 else 'general'
            }
        }

    def _create_visualization(self, img: np.ndarray, regions: List[Dict[str, Any]]) -> np.ndarray:
        """
        创建可视化图
        """
        viz = img.copy()

        for region in regions:
            bbox = region['bbox']
            region_type = region.get('type', 'text')

            # 根据类型选择颜色
            if region_type == 'text':
                color = (0, 255, 0)  # 绿色
            elif region_type == 'table':
                color = (255, 165, 0)  # 橙色
            elif region_type == 'seal':
                color = (0, 0, 255)  # 红色
            else:
                color = (128, 128, 128)  # 灰色

            # 绘制边界框
            cv2.rectangle(viz,
                         (bbox['x'], bbox['y']),
                         (bbox['x'] + bbox['width'], bbox['y'] + bbox['height']),
                         color, 2)

            # 添加标签
            label = f"{region_type}:{region.get('confidence', 0.8):.2f}"
            cv2.putText(viz, label,
                       (bbox['x'], bbox['y'] - 5),
                       cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1)

        return viz

    def _encode_image(self, img: np.ndarray) -> str:
        """
        编码图片为base64
        """
        img_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        pil_img = Image.fromarray(img_rgb)
        buffered = io.BytesIO()
        pil_img.save(buffered, format="PNG")
        img_base64 = base64.b64encode(buffered.getvalue()).decode('utf-8')
        return f'data:image/png;base64,{img_base64}'
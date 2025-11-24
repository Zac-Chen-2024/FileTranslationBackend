"""
图片背景文字分离服务
使用OpenCV进行图像处理
"""
import cv2
import numpy as np
import base64
from PIL import Image
import io


class ImageProcessor:
    """图片处理类"""

    @staticmethod
    def separate_background_text(image_bytes):
        """
        检测文字区域并保留原图作为背景

        Args:
            image_bytes: 图片的二进制数据

        Returns:
            dict: {
                'background_image': base64编码的原图（完整保留）,
                'text_regions': [{
                    'id': 文字区域ID,
                    'bbox': {'x': x坐标, 'y': y坐标, 'width': 宽度, 'height': 高度}
                }],
                'text_mask': base64编码的文字mask图（用于后续处理）
            }
        """
        # 1. 读取图片
        nparr = np.frombuffer(image_bytes, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

        if img is None:
            raise ValueError("无法读取图片")

        # 保存原图尺寸
        height, width = img.shape[:2]

        # 2. 检测文字区域（但不破坏原图）
        text_regions, text_mask = ImageProcessor.detect_text_regions(img)

        # 3. 原图作为背景（完整保留，不做任何修改）
        background_base64 = ImageProcessor.encode_image_base64(img)

        # 4. 编码文字mask供调试使用
        mask_base64 = None
        if text_mask is not None:
            mask_color = cv2.cvtColor(text_mask, cv2.COLOR_GRAY2RGB)
            mask_base64 = ImageProcessor.encode_image_base64(mask_color)

        return {
            'background_image': background_base64,
            'text_regions': text_regions,
            'original_size': {'width': width, 'height': height},
            'text_mask': mask_base64  # 可选，用于调试
        }

    @staticmethod
    def detect_text_regions(img):
        """
        检测图片中的文字区域（改进版本）

        Args:
            img: 原始彩色图片

        Returns:
            tuple: (text_regions列表, text_mask图像)
        """
        # 1. 转灰度
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

        # 2. 使用多种方法检测文字
        # 方法A: MSER (最大稳定极值区域) - 专门用于文字检测
        try:
            # 尝试标准版本参数名（不带下划线，OpenCV 3.x/4.x）
            mser = cv2.MSER_create(
                delta=5,  # 灰度变化阈值
                min_area=100,  # 最小区域面积
                max_area=14400,  # 最大区域面积
                max_variation=0.25,  # 区域变化率
                min_diversity=0.2  # 最小多样性
            )
        except (TypeError, cv2.error):
            try:
                # 如果失败，尝试带下划线的参数名（某些版本）
                mser = cv2.MSER_create(
                    _delta=5,  # 灰度变化阈值
                    _min_area=100,  # 最小区域面积
                    _max_area=14400,  # 最大区域面积
                    _max_variation=0.25,  # 区域变化率
                    _min_diversity=0.2  # 最小多样性
                )
            except (TypeError, cv2.error):
                # 如果都失败，使用默认参数
                mser = cv2.MSER_create()

        # 检测MSER区域
        regions, _ = mser.detectRegions(gray)

        # 方法B: 边缘检测 + 形态学操作
        # 使用Canny边缘检测
        edges = cv2.Canny(gray, 50, 150)

        # 形态学操作连接文字
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 2))
        dilated = cv2.dilate(edges, kernel, iterations=3)

        # 闭运算填充内部空隙
        kernel_close = cv2.getStructuringElement(cv2.MORPH_RECT, (15, 5))
        closed = cv2.morphologyEx(dilated, cv2.MORPH_CLOSE, kernel_close)

        # 3. 查找轮廓
        contours, _ = cv2.findContours(
            closed,
            cv2.RETR_EXTERNAL,
            cv2.CHAIN_APPROX_SIMPLE
        )

        # 4. 筛选和合并文字区域
        text_regions = []
        text_mask = np.zeros(gray.shape, dtype=np.uint8)

        # 获取图像尺寸
        height, width = gray.shape

        # 设置更严格的过滤条件
        min_area = 500  # 增加最小面积阈值
        max_area = width * height * 0.5  # 最大面积不超过图片的50%
        min_width = 20  # 最小宽度
        min_height = 10  # 最小高度

        valid_contours = []
        for contour in contours:
            x, y, w, h = cv2.boundingRect(contour)
            area = cv2.contourArea(contour)

            # 过滤条件
            if area < min_area or area > max_area:
                continue
            if w < min_width or h < min_height:
                continue

            # 宽高比过滤（文字通常有合理的宽高比）
            aspect_ratio = w / float(h)
            if aspect_ratio > 15 or aspect_ratio < 0.1:
                continue

            # 填充度检查（文字区域应该有一定的填充度）
            rect_area = w * h
            fill_ratio = area / rect_area if rect_area > 0 else 0
            if fill_ratio < 0.3:  # 填充度太低，可能是噪声
                continue

            # 边界检查（太靠近边缘的可能是边框）
            margin = 5
            if x < margin or y < margin or x + w > width - margin or y + h > height - margin:
                # 检查是否真的是边框（面积占比大）
                if rect_area > width * height * 0.3:
                    continue

            valid_contours.append((x, y, w, h))

            # 在mask上绘制轮廓
            cv2.rectangle(text_mask, (x, y), (x + w, y + h), 255, -1)

        # 5. 合并相近的文字区域
        merged_regions = ImageProcessor.merge_nearby_regions(valid_contours,
                                                           max_distance=30)

        # 6. 创建最终的文字区域列表
        for idx, (x, y, w, h) in enumerate(merged_regions):
            text_regions.append({
                'id': f'text_{idx}',
                'bbox': {
                    'x': int(x),
                    'y': int(y),
                    'width': int(w),
                    'height': int(h)
                }
            })

        return text_regions, text_mask

    @staticmethod
    def merge_nearby_regions(regions, max_distance=20):
        """
        合并相近的文字区域

        Args:
            regions: [(x, y, w, h), ...] 区域列表
            max_distance: 最大合并距离

        Returns:
            list: 合并后的区域列表
        """
        if not regions:
            return []

        # 将区域转换为矩形列表
        rects = []
        for x, y, w, h in regions:
            rects.append([x, y, x + w, y + h])

        # 合并相近的矩形
        merged = []
        used = [False] * len(rects)

        for i in range(len(rects)):
            if used[i]:
                continue

            # 当前矩形
            x1, y1, x2, y2 = rects[i]

            # 查找可以合并的矩形
            for j in range(i + 1, len(rects)):
                if used[j]:
                    continue

                x1j, y1j, x2j, y2j = rects[j]

                # 计算距离
                # 水平距离
                h_dist = max(0, max(x1j - x2, x1 - x2j))
                # 垂直距离
                v_dist = max(0, max(y1j - y2, y1 - y2j))

                # 如果距离小于阈值，合并
                if h_dist < max_distance and v_dist < max_distance:
                    # 合并矩形
                    x1 = min(x1, x1j)
                    y1 = min(y1, y1j)
                    x2 = max(x2, x2j)
                    y2 = max(y2, y2j)
                    used[j] = True

            # 添加合并后的矩形
            merged.append((x1, y1, x2 - x1, y2 - y1))
            used[i] = True

        return merged

    @staticmethod
    def simple_inpaint(img, mask, method='telea'):
        """
        简单的图像修复（不需要神经网络）

        Args:
            img: 原始图片
            mask: 需要修复的区域mask（255表示需要修复）
            method: 修复方法 ('telea' 或 'ns')

        Returns:
            修复后的图片
        """
        # 确保mask是单通道
        if len(mask.shape) > 2:
            mask = cv2.cvtColor(mask, cv2.COLOR_BGR2GRAY)

        # 使用OpenCV的inpaint功能
        if method == 'telea':
            # Telea方法 - 基于快速行进法
            result = cv2.inpaint(img, mask, 3, cv2.INPAINT_TELEA)
        else:
            # Navier-Stokes方法 - 基于流体动力学
            result = cv2.inpaint(img, mask, 3, cv2.INPAINT_NS)

        return result

    @staticmethod
    def remove_text_region(image_bytes, region_id, text_regions):
        """
        移除指定的文字区域并修复背景

        Args:
            image_bytes: 原始图片数据
            region_id: 要移除的文字区域ID
            text_regions: 所有文字区域列表

        Returns:
            dict: 包含修复后的图片
        """
        # 读取图片
        nparr = np.frombuffer(image_bytes, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

        # 创建mask
        mask = np.zeros(img.shape[:2], dtype=np.uint8)

        # 找到要移除的区域
        for region in text_regions:
            if region['id'] == region_id:
                bbox = region['bbox']
                x, y, w, h = bbox['x'], bbox['y'], bbox['width'], bbox['height']
                # 在mask上标记需要修复的区域
                cv2.rectangle(mask, (x, y), (x + w, y + h), 255, -1)
                break

        # 修复图片
        result = ImageProcessor.simple_inpaint(img, mask)

        # 编码结果
        result_base64 = ImageProcessor.encode_image_base64(result)

        return {
            'inpainted_image': result_base64
        }

    @staticmethod
    def encode_image_base64(img):
        """
        将OpenCV图片编码为base64字符串

        Args:
            img: OpenCV图片（numpy array）

        Returns:
            str: base64编码的图片
        """
        # 转换为PIL Image
        img_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        pil_img = Image.fromarray(img_rgb)

        # 编码为PNG
        buffered = io.BytesIO()
        pil_img.save(buffered, format="PNG")
        img_bytes = buffered.getvalue()

        # Base64编码
        img_base64 = base64.b64encode(img_bytes).decode('utf-8')

        return f'data:image/png;base64,{img_base64}'
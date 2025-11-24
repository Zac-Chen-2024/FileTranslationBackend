"""
高级文字检测服务 - 模拟 Adobe Acrobat 的专业文字检测
使用多种先进算法组合实现精确的文字区域检测
"""
import cv2
import numpy as np
import base64
from PIL import Image
import io
from typing import List, Tuple, Dict, Any
import scipy.ndimage as ndimage
from sklearn.cluster import DBSCAN


class AdvancedTextDetector:
    """专业级文字检测器"""

    def __init__(self):
        """初始化检测器参数"""
        # 自适应阈值参数
        self.adaptive_block_size = 11
        self.adaptive_c = 2

        # 形态学操作核大小
        self.morph_kernel_sizes = {
            'small': (2, 2),
            'medium': (3, 3),
            'large': (5, 5),
            'horizontal': (25, 1),
            'vertical': (1, 25)
        }

        # 文字区域过滤参数
        self.min_text_area = 100
        self.max_text_area_ratio = 0.5
        self.min_aspect_ratio = 0.1
        self.max_aspect_ratio = 15

        # 聚类参数
        self.clustering_eps = 50
        self.clustering_min_samples = 1

    def detect_text_regions(self, image_bytes: bytes) -> Dict[str, Any]:
        """
        主检测函数 - 使用多种技术检测文字区域

        Args:
            image_bytes: 图片二进制数据

        Returns:
            包含检测结果的字典
        """
        # 读取图片
        nparr = np.frombuffer(image_bytes, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

        if img is None:
            raise ValueError("无法读取图片")

        original = img.copy()
        height, width = img.shape[:2]

        # 1. 预处理
        preprocessed = self._preprocess_image(img)

        # 2. 多尺度文字检测
        text_maps = self._multiscale_text_detection(preprocessed)

        # 3. 区域提取
        regions = self._extract_text_regions(text_maps, original)

        # 4. 区域优化和聚类
        optimized_regions = self._optimize_regions(regions)

        # 5. 智能背景生成
        background = self._create_intelligent_background(original, optimized_regions)

        # 6. 生成输出
        return self._format_output(original, background, optimized_regions)

    def _preprocess_image(self, img: np.ndarray) -> Dict[str, np.ndarray]:
        """
        图像预处理 - 生成多种处理版本
        """
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

        # 1. 增强对比度 (CLAHE)
        clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
        enhanced = clahe.apply(gray)

        # 2. 去噪
        denoised = cv2.fastNlMeansDenoising(enhanced, h=10)

        # 3. 锐化
        kernel = np.array([[-1, -1, -1],
                          [-1,  9, -1],
                          [-1, -1, -1]])
        sharpened = cv2.filter2D(denoised, -1, kernel)

        # 4. 双边滤波（保边去噪）
        bilateral = cv2.bilateralFilter(gray, 9, 75, 75)

        return {
            'gray': gray,
            'enhanced': enhanced,
            'denoised': denoised,
            'sharpened': sharpened,
            'bilateral': bilateral
        }

    def _multiscale_text_detection(self, preprocessed: Dict[str, np.ndarray]) -> np.ndarray:
        """
        多尺度文字检测 - 组合多种方法
        """
        h, w = preprocessed['gray'].shape
        combined_mask = np.zeros((h, w), dtype=np.float32)

        # 1. Otsu 二值化
        _, otsu = cv2.threshold(preprocessed['enhanced'], 0, 255,
                                cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        combined_mask += otsu.astype(np.float32) / 255 * 0.2

        # 2. 自适应阈值（局部）
        adaptive = cv2.adaptiveThreshold(preprocessed['denoised'], 255,
                                        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                        cv2.THRESH_BINARY_INV,
                                        self.adaptive_block_size,
                                        self.adaptive_c)
        combined_mask += adaptive.astype(np.float32) / 255 * 0.3

        # 3. Canny 边缘检测
        edges = cv2.Canny(preprocessed['sharpened'], 50, 150)

        # 形态学处理连接边缘
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
        edges_dilated = cv2.dilate(edges, kernel, iterations=2)
        edges_closed = cv2.morphologyEx(edges_dilated, cv2.MORPH_CLOSE,
                                        cv2.getStructuringElement(cv2.MORPH_RECT, (7, 7)))
        combined_mask += edges_closed.astype(np.float32) / 255 * 0.2

        # 4. 梯度分析（Sobel）
        grad_x = cv2.Sobel(preprocessed['bilateral'], cv2.CV_64F, 1, 0, ksize=3)
        grad_y = cv2.Sobel(preprocessed['bilateral'], cv2.CV_64F, 0, 1, ksize=3)
        gradient = np.sqrt(grad_x**2 + grad_y**2)
        gradient_norm = (gradient / gradient.max() * 255).astype(np.uint8)
        _, gradient_thresh = cv2.threshold(gradient_norm, 30, 255, cv2.THRESH_BINARY)
        combined_mask += gradient_thresh.astype(np.float32) / 255 * 0.15

        # 5. 文字特征检测（SWT - Stroke Width Transform 简化版）
        swt_map = self._simplified_swt(preprocessed['gray'], edges)
        combined_mask += swt_map * 0.15

        # 归一化和阈值处理
        combined_mask = np.clip(combined_mask, 0, 1)
        final_mask = (combined_mask > 0.4).astype(np.uint8) * 255

        # 形态学优化
        kernel_open = cv2.getStructuringElement(cv2.MORPH_RECT, (2, 2))
        kernel_close = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 2))

        final_mask = cv2.morphologyEx(final_mask, cv2.MORPH_OPEN, kernel_open)
        final_mask = cv2.morphologyEx(final_mask, cv2.MORPH_CLOSE, kernel_close)

        return final_mask

    def _simplified_swt(self, gray: np.ndarray, edges: np.ndarray) -> np.ndarray:
        """
        简化的笔画宽度变换 - 检测文字笔画
        """
        h, w = gray.shape
        swt_map = np.zeros((h, w), dtype=np.float32)

        # 计算梯度方向
        dx = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3)
        dy = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3)

        # 归一化梯度
        magnitude = np.sqrt(dx**2 + dy**2)
        dx = np.divide(dx, magnitude, where=magnitude!=0)
        dy = np.divide(dy, magnitude, where=magnitude!=0)

        # 沿着梯度方向查找笔画宽度
        edge_points = np.where(edges > 0)

        for y, x in zip(edge_points[0], edge_points[1]):
            # 沿着梯度方向搜索
            for direction in [1, -1]:  # 正向和反向
                cur_x, cur_y = x, y
                stroke_width = 0
                max_steps = 50

                for step in range(max_steps):
                    cur_x += direction * dx[y, x]
                    cur_y += direction * dy[y, x]

                    if (0 <= cur_x < w and 0 <= cur_y < h):
                        ix, iy = int(cur_x), int(cur_y)
                        if edges[iy, ix] > 0 and step > 0:
                            stroke_width = step
                            break
                    else:
                        break

                if 2 <= stroke_width <= 30:  # 合理的笔画宽度范围
                    swt_map[y, x] = 1.0 / stroke_width

        # 模糊处理使结果更连续
        swt_map = cv2.GaussianBlur(swt_map, (5, 5), 1)

        return swt_map

    def _extract_text_regions(self, text_mask: np.ndarray,
                             original: np.ndarray) -> List[Dict[str, Any]]:
        """
        从检测掩码中提取文字区域
        """
        # 查找轮廓
        contours, _ = cv2.findContours(text_mask, cv2.RETR_EXTERNAL,
                                       cv2.CHAIN_APPROX_SIMPLE)

        height, width = text_mask.shape
        regions = []

        for idx, contour in enumerate(contours):
            # 计算边界框
            x, y, w, h = cv2.boundingRect(contour)

            # 基本过滤
            area = cv2.contourArea(contour)
            if area < self.min_text_area:
                continue

            if area > width * height * self.max_text_area_ratio:
                continue

            aspect_ratio = w / h if h > 0 else 0
            if aspect_ratio < self.min_aspect_ratio or aspect_ratio > self.max_aspect_ratio:
                continue

            # 计算区域特征
            region_mask = np.zeros(text_mask.shape, dtype=np.uint8)
            cv2.drawContours(region_mask, [contour], -1, 255, -1)

            # 计算填充率
            fill_ratio = cv2.countNonZero(region_mask[y:y+h, x:x+w]) / (w * h)
            if fill_ratio < 0.2:  # 填充率太低，可能是噪声
                continue

            # 提取区域图像
            region_img = original[y:y+h, x:x+w].copy()

            # 计算区域置信度
            confidence = self._calculate_text_confidence(region_img, region_mask[y:y+h, x:x+w])

            regions.append({
                'id': f'region_{idx}',
                'bbox': {'x': x, 'y': y, 'width': w, 'height': h},
                'contour': contour.tolist(),
                'confidence': confidence,
                'fill_ratio': fill_ratio,
                'aspect_ratio': aspect_ratio
            })

        return regions

    def _calculate_text_confidence(self, region_img: np.ndarray,
                                  region_mask: np.ndarray) -> float:
        """
        计算区域是文字的置信度
        """
        if region_img.size == 0:
            return 0.0

        gray = cv2.cvtColor(region_img, cv2.COLOR_BGR2GRAY) if len(region_img.shape) == 3 else region_img

        # 1. 边缘密度
        edges = cv2.Canny(gray, 50, 150)
        edge_density = cv2.countNonZero(edges) / edges.size

        # 2. 标准差（文字区域通常有较高对比度）
        std_dev = np.std(gray[region_mask > 0]) if cv2.countNonZero(region_mask) > 0 else 0

        # 3. 连通组件数量（文字区域通常有多个连通组件）
        num_labels, _ = cv2.connectedComponents(region_mask)
        component_ratio = min(num_labels / 100.0, 1.0)

        # 综合置信度
        confidence = (edge_density * 0.3 +
                     min(std_dev / 100, 1.0) * 0.4 +
                     component_ratio * 0.3)

        return min(confidence, 1.0)

    def _optimize_regions(self, regions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        优化检测区域 - 合并相近区域、去除重叠
        """
        if not regions:
            return []

        # 按置信度排序
        regions = sorted(regions, key=lambda r: r['confidence'], reverse=True)

        # 1. 使用 DBSCAN 聚类合并相近区域
        if len(regions) > 1:
            # 提取中心点
            centers = np.array([[r['bbox']['x'] + r['bbox']['width']/2,
                                r['bbox']['y'] + r['bbox']['height']/2]
                               for r in regions])

            # 聚类
            clustering = DBSCAN(eps=self.clustering_eps,
                               min_samples=self.clustering_min_samples).fit(centers)

            # 合并同一簇的区域
            merged_regions = []
            for label in set(clustering.labels_):
                if label == -1:  # 噪声点，保留原始区域
                    cluster_indices = np.where(clustering.labels_ == label)[0]
                    for idx in cluster_indices:
                        merged_regions.append(regions[idx])
                else:
                    cluster_indices = np.where(clustering.labels_ == label)[0]
                    cluster_regions = [regions[i] for i in cluster_indices]
                    merged = self._merge_regions(cluster_regions)
                    merged_regions.append(merged)

            regions = merged_regions

        # 2. 去除高度重叠的区域
        final_regions = []
        for i, region in enumerate(regions):
            overlap = False
            for j, other in enumerate(final_regions):
                if self._calculate_iou(region['bbox'], other['bbox']) > 0.7:
                    # 保留置信度更高的
                    if region['confidence'] > other['confidence']:
                        final_regions[j] = region
                    overlap = True
                    break

            if not overlap:
                final_regions.append(region)

        return final_regions

    def _merge_regions(self, regions: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        合并多个区域
        """
        if not regions:
            return None

        if len(regions) == 1:
            return regions[0]

        # 计算合并后的边界框
        min_x = min(r['bbox']['x'] for r in regions)
        min_y = min(r['bbox']['y'] for r in regions)
        max_x = max(r['bbox']['x'] + r['bbox']['width'] for r in regions)
        max_y = max(r['bbox']['y'] + r['bbox']['height'] for r in regions)

        # 平均置信度
        avg_confidence = np.mean([r['confidence'] for r in regions])

        return {
            'id': f'merged_{regions[0]["id"]}',
            'bbox': {
                'x': min_x,
                'y': min_y,
                'width': max_x - min_x,
                'height': max_y - min_y
            },
            'confidence': avg_confidence,
            'merged_from': len(regions)
        }

    def _calculate_iou(self, bbox1: Dict, bbox2: Dict) -> float:
        """
        计算两个边界框的 IoU (Intersection over Union)
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

    def _create_intelligent_background(self, original: np.ndarray,
                                      regions: List[Dict[str, Any]]) -> np.ndarray:
        """
        智能创建背景 - 使用高级图像修复技术
        """
        height, width = original.shape[:2]

        # 创建文字区域掩码
        mask = np.zeros((height, width), dtype=np.uint8)

        for region in regions:
            bbox = region['bbox']
            # 稍微扩大掩码区域以确保完全覆盖文字
            x = max(0, bbox['x'] - 2)
            y = max(0, bbox['y'] - 2)
            w = min(width - x, bbox['width'] + 4)
            h = min(height - y, bbox['height'] + 4)

            cv2.rectangle(mask, (x, y), (x + w, y + h), 255, -1)

        # 使用多种修复方法组合

        # 1. Telea 修复（快速）
        inpainted_telea = cv2.inpaint(original, mask, 3, cv2.INPAINT_TELEA)

        # 2. Navier-Stokes 修复（更自然）
        inpainted_ns = cv2.inpaint(original, mask, 3, cv2.INPAINT_NS)

        # 3. 边缘感知修复
        # 扩展边缘以获得更好的过渡
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
        mask_dilated = cv2.dilate(mask, kernel, iterations=2)
        mask_edge = mask_dilated - mask

        # 在边缘区域混合两种修复结果
        alpha = mask_edge.astype(np.float32) / 255
        alpha = cv2.GaussianBlur(alpha, (5, 5), 2)
        alpha = np.stack([alpha] * 3, axis=-1)

        # 混合修复结果
        background = inpainted_telea * (1 - alpha) + inpainted_ns * alpha
        background = background.astype(np.uint8)

        # 4. 颜色协调
        # 对修复区域进行颜色平滑
        background = self._harmonize_colors(background, mask)

        return background

    def _harmonize_colors(self, image: np.ndarray, mask: np.ndarray) -> np.ndarray:
        """
        颜色协调 - 使修复区域与周围颜色更协调
        """
        # 转换到 LAB 颜色空间
        lab = cv2.cvtColor(image, cv2.COLOR_BGR2LAB)
        l, a, b = cv2.split(lab)

        # 对修复区域进行平滑
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7))
        mask_dilated = cv2.dilate(mask, kernel, iterations=1)

        # 只对修复区域附近进行双边滤波
        l_smooth = cv2.bilateralFilter(l, 9, 75, 75)
        a_smooth = cv2.bilateralFilter(a, 9, 75, 75)
        b_smooth = cv2.bilateralFilter(b, 9, 75, 75)

        # 混合原始和平滑结果
        alpha = (mask_dilated / 255.0).astype(np.float32)
        alpha = cv2.GaussianBlur(alpha, (9, 9), 3)

        l = (l * (1 - alpha) + l_smooth * alpha).astype(np.uint8)
        a = (a * (1 - alpha) + a_smooth * alpha).astype(np.uint8)
        b = (b * (1 - alpha) + b_smooth * alpha).astype(np.uint8)

        # 转换回 BGR
        lab_smooth = cv2.merge([l, a, b])
        result = cv2.cvtColor(lab_smooth, cv2.COLOR_LAB2BGR)

        return result

    def _format_output(self, original: np.ndarray, background: np.ndarray,
                       regions: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        格式化输出结果
        """
        height, width = original.shape[:2]

        # 编码图片
        background_base64 = self._encode_image(background)
        original_base64 = self._encode_image(original)

        # 生成检测可视化图
        detection_viz = self._create_detection_visualization(original, regions)
        detection_viz_base64 = self._encode_image(detection_viz)

        # 只保留高置信度的区域
        filtered_regions = [r for r in regions if r['confidence'] > 0.5]

        # 格式化区域数据
        formatted_regions = []
        for region in filtered_regions:
            formatted_regions.append({
                'id': region['id'],
                'bbox': region['bbox'],
                'confidence': round(region['confidence'], 3)
            })

        return {
            'success': True,
            'original_image': original_base64,
            'background_image': background_base64,
            'detection_visualization': detection_viz_base64,
            'text_regions': formatted_regions,
            'original_size': {'width': width, 'height': height},
            'statistics': {
                'total_regions_detected': len(regions),
                'high_confidence_regions': len(filtered_regions),
                'average_confidence': round(np.mean([r['confidence'] for r in regions]), 3) if regions else 0
            }
        }

    def _create_detection_visualization(self, image: np.ndarray,
                                       regions: List[Dict[str, Any]]) -> np.ndarray:
        """
        创建检测结果可视化图
        """
        viz = image.copy()

        # 创建半透明覆盖层
        overlay = image.copy()

        for region in regions:
            bbox = region['bbox']
            confidence = region['confidence']

            # 根据置信度选择颜色
            if confidence > 0.8:
                color = (0, 255, 0)  # 绿色 - 高置信度
            elif confidence > 0.6:
                color = (0, 165, 255)  # 橙色 - 中置信度
            else:
                color = (0, 0, 255)  # 红色 - 低置信度

            # 绘制边界框
            cv2.rectangle(overlay,
                         (bbox['x'], bbox['y']),
                         (bbox['x'] + bbox['width'], bbox['y'] + bbox['height']),
                         color, 2)

            # 绘制置信度标签
            label = f"{confidence:.2f}"
            label_size = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)[0]

            # 标签背景
            cv2.rectangle(overlay,
                         (bbox['x'], bbox['y'] - label_size[1] - 4),
                         (bbox['x'] + label_size[0], bbox['y']),
                         color, -1)

            # 标签文字
            cv2.putText(overlay, label,
                       (bbox['x'], bbox['y'] - 2),
                       cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)

        # 混合原图和覆盖层
        cv2.addWeighted(overlay, 0.7, viz, 0.3, 0, viz)

        return viz

    def _encode_image(self, img: np.ndarray) -> str:
        """
        将图片编码为 base64
        """
        # 转换为 RGB (PIL 需要)
        img_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        pil_img = Image.fromarray(img_rgb)

        # 编码为 PNG
        buffered = io.BytesIO()
        pil_img.save(buffered, format="PNG")
        img_bytes = buffered.getvalue()

        # Base64 编码
        img_base64 = base64.b64encode(img_bytes).decode('utf-8')

        return f'data:image/png;base64,{img_base64}'
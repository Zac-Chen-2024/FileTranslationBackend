"""
图片背景文字分离API路由
"""
from flask import Blueprint, request, jsonify, current_app as app
from services.image_processor import ImageProcessor
from services.advanced_text_detector import AdvancedTextDetector
from services.document_text_detector import DocumentTextDetector
import traceback
import json
import numpy as np
import cv2

# 创建蓝图
image_separation_bp = Blueprint('image_separation', __name__, url_prefix='/api/image-separation')


@image_separation_bp.route('/upload', methods=['POST'])
def upload_and_separate():
    """
    上传图片并进行背景文字分离

    请求：
        - 文件: image (multipart/form-data)

    返回：
        {
            'success': true/false,
            'data': {
                'background_image': 'base64...',
                'text_regions': [...],
                'original_size': {'width': ..., 'height': ...}
            },
            'error': '错误信息'
        }
    """
    try:
        # 检查是否有文件
        if 'image' not in request.files:
            return jsonify({
                'success': False,
                'error': '未找到上传的图片文件'
            }), 400

        file = request.files['image']

        # 检查文件名
        if file.filename == '':
            return jsonify({
                'success': False,
                'error': '文件名为空'
            }), 400

        # 检查文件类型
        allowed_extensions = {'png', 'jpg', 'jpeg', 'bmp', 'tiff', 'webp'}
        file_ext = file.filename.rsplit('.', 1)[1].lower() if '.' in file.filename else ''

        if file_ext not in allowed_extensions:
            return jsonify({
                'success': False,
                'error': f'不支持的文件格式。支持的格式：{", ".join(allowed_extensions)}'
            }), 400

        # 读取文件数据
        image_bytes = file.read()

        # 检查文件大小（限制10MB）
        max_size = 10 * 1024 * 1024  # 10MB
        if len(image_bytes) > max_size:
            return jsonify({
                'success': False,
                'error': '文件大小超过10MB限制'
            }), 400

        # 检查使用哪种检测模式
        mode = request.args.get('mode', 'basic')

        if mode == 'document':
            # 使用文档专用检测器
            detector = DocumentTextDetector()
            result = detector.detect_document_text(image_bytes)
        elif mode == 'advanced':
            # 使用高级文字检测器
            detector = AdvancedTextDetector()
            result = detector.detect_text_regions(image_bytes)
        else:
            # 使用原始图片处理服务
            result = ImageProcessor.separate_background_text(image_bytes)

        return jsonify({
            'success': True,
            'data': result
        }), 200

    except ValueError as e:
        # 图片读取错误
        return jsonify({
            'success': False,
            'error': str(e)
        }), 400

    except Exception as e:
        # 其他错误
        print(f'图片分离错误: {str(e)}')
        print(traceback.format_exc())

        return jsonify({
            'success': False,
            'error': f'服务器处理错误: {str(e)}'
        }), 500


@image_separation_bp.route('/health', methods=['GET'])
def health_check():
    """健康检查端点"""
    return jsonify({
        'success': True,
        'service': 'image-separation',
        'status': 'running'
    }), 200


@image_separation_bp.route('/edit-text', methods=['POST'])
def edit_text_in_image():
    """编辑图片文字（使用已分离的背景+渲染英文）"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'error': '缺少请求数据'}), 400

        background_image_base64 = data.get('background_image')
        region = data.get('region')
        new_text = data.get('new_text')

        if not background_image_base64 or not region or not new_text:
            return jsonify({'success': False, 'error': '缺少必要参数'}), 400

        import base64
        import re
        from PIL import Image, ImageDraw, ImageFont
        import io

        # 解码背景图片（已经分离好的）
        image_data = re.sub('^data:image/.+;base64,', '', background_image_base64)
        image_bytes = base64.b64decode(image_data)
        nparr = np.frombuffer(image_bytes, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

        if img is None:
            return jsonify({'success': False, 'error': '无法解码图片'}), 400

        bbox = region['bbox']
        x, y, w, h = int(bbox['x']), int(bbox['y']), int(bbox['width']), int(bbox['height'])

        # 1. 直接使用已分离的背景图（不需要inpainting）
        # 2. 转换为PIL格式以渲染文字
        img_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        pil_img = Image.fromarray(img_rgb)
        draw = ImageDraw.Draw(pil_img)

        # 3. 根据区域高度计算字体大小
        font_size = int(h * 0.7)  # 字体大小为区域高度的70%

        # 尝试加载字体
        try:
            font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", font_size)
        except:
            try:
                font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", font_size)
            except:
                font = ImageFont.load_default()

        # 4. 计算文字位置（居中）
        bbox_text = draw.textbbox((0, 0), new_text, font=font)
        text_width = bbox_text[2] - bbox_text[0]
        text_height = bbox_text[3] - bbox_text[1]

        text_x = x + (w - text_width) // 2
        text_y = y + (h - text_height) // 2

        # 5. 绘制英文文字（黑色）
        draw.text((text_x, text_y), new_text, fill=(0, 0, 0), font=font)

        # 6. 转换回OpenCV格式
        result_img = cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGB2BGR)

        # 编码为base64
        _, buffer = cv2.imencode('.png', result_img)
        result_base64 = base64.b64encode(buffer).decode('utf-8')
        result_base64 = f'data:image/png;base64,{result_base64}'

        return jsonify({
            'success': True,
            'data': {
                'processed_image': result_base64
            }
        }), 200

    except Exception as e:
        app.logger.error(f"编辑文字失败: {str(e)}")
        traceback.print_exc()
        return jsonify({
            'success': False,
            'error': f'编辑文字失败: {str(e)}'
        }), 500


@image_separation_bp.route('/delete-text', methods=['POST'])
def delete_text_from_image():
    """从图片上删除文字区域（使用inpainting修复）"""
    try:
        # 获取请求数据
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'error': '缺少请求数据'}), 400

        original_image_base64 = data.get('original_image')
        region = data.get('region')

        if not original_image_base64 or not region:
            return jsonify({'success': False, 'error': '缺少必要参数'}), 400

        # 解码base64图片
        import base64
        import re

        # 移除data:image/png;base64,前缀
        image_data = re.sub('^data:image/.+;base64,', '', original_image_base64)
        image_bytes = base64.b64decode(image_data)

        # 读取图片
        nparr = np.frombuffer(image_bytes, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

        if img is None:
            return jsonify({'success': False, 'error': '无法解码图片'}), 400

        # 创建mask
        mask = np.zeros(img.shape[:2], dtype=np.uint8)
        bbox = region['bbox']
        x, y, w, h = int(bbox['x']), int(bbox['y']), int(bbox['width']), int(bbox['height'])

        # 稍微扩大区域以确保完全覆盖文字
        padding = 3
        x = max(0, x - padding)
        y = max(0, y - padding)
        w = min(img.shape[1] - x, w + 2 * padding)
        h = min(img.shape[0] - y, h + 2 * padding)

        cv2.rectangle(mask, (x, y), (x + w, y + h), 255, -1)

        # 使用inpainting修复
        result_img = cv2.inpaint(img, mask, 3, cv2.INPAINT_TELEA)

        # 编码为base64
        _, buffer = cv2.imencode('.png', result_img)
        result_base64 = base64.b64encode(buffer).decode('utf-8')
        result_base64 = f'data:image/png;base64,{result_base64}'

        return jsonify({
            'success': True,
            'data': {
                'processed_image': result_base64
            }
        }), 200

    except Exception as e:
        app.logger.error(f"删除文字失败: {str(e)}")
        traceback.print_exc()
        return jsonify({
            'success': False,
            'error': f'删除文字失败: {str(e)}'
        }), 500

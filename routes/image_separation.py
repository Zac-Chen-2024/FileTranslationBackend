"""
图片背景文字分离API路由
"""
from flask import Blueprint, request, jsonify, current_app as app
from services.image_processor import ImageProcessor
from services.advanced_text_detector import AdvancedTextDetector
import traceback
import json

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

        # 检查是否使用高级检测
        use_advanced = request.args.get('advanced', 'false').lower() == 'true'

        if use_advanced:
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


@image_separation_bp.route('/remove-text', methods=['POST'])
def remove_text_region():
    """移除文字区域并修复背景"""
    try:
        # 获取请求数据
        if 'image' not in request.files:
            return jsonify({'success': False, 'error': '未找到图片文件'}), 400

        data = request.form
        if 'region_id' not in data or 'text_regions' not in data:
            return jsonify({'success': False, 'error': '缺少必要参数'}), 400

        file = request.files['image']
        region_id = data['region_id']
        text_regions = json.loads(data['text_regions'])

        # 读取图片
        image_bytes = file.read()

        # 移除文字并修复
        result = ImageProcessor.remove_text_region(image_bytes, region_id, text_regions)

        return jsonify({
            'success': True,
            'data': result
        }), 200

    except Exception as e:
        app.logger.error(f"移除文字区域失败: {str(e)}")
        return jsonify({
            'success': False,
            'error': f'移除文字失败: {str(e)}'
        }), 500

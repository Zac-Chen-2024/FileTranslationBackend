# -*- coding: utf-8 -*-
"""
原子化翻译API路由

设计原则：
1. 每个API只做一件事
2. 返回 availableActions 让前端决定下一步
3. 不自动触发后续流程（除非明确要求）

API列表：
- POST /translate-baidu      只做百度OCR
- POST /entity/recognize     只做实体识别
- POST /entity/confirm       只确认实体
- POST /llm/optimize         只做LLM优化
"""

from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
import json
import logging

logger = logging.getLogger(__name__)

# 创建Blueprint
atomic_bp = Blueprint('atomic', __name__, url_prefix='/api/materials')


def get_material_with_permission(material_id, user_id):
    """获取材料并验证权限（延迟导入避免循环依赖）"""
    from app import Material, Client, db

    material = Material.query.join(Client).filter(
        Material.id == material_id,
        Client.user_id == user_id
    ).first()

    return material


def get_state_machine():
    """获取状态机实例"""
    from workflow.atomic_state_machine import state_machine, validate_transition
    return state_machine, validate_transition


@atomic_bp.route('/<material_id>/translate-baidu', methods=['POST'])
@jwt_required()
def translate_baidu(material_id):
    """
    原子操作：只执行百度OCR翻译

    不触发实体识别，不触发LLM优化。
    用于需要手动控制流程时。

    请求体:
        {
            "clearPreviousData": true  // 是否清除之前的翻译数据
        }

    返回:
        {
            "success": true,
            "processingStep": "translated",
            "translationTextInfo": {...},
            "availableActions": ["entity_recognize", "llm_optimize", "skip_to_review"]
        }
    """
    try:
        from app import (
            Material, Client, db, translate_image_reference,
            update_material_status, MaterialStatus, log_message,
            check_translation_lock, WEBSOCKET_ENABLED, emit_translation_started
        )
        from workflow.atomic_state_machine import ProcessingStep, AtomicAction, validate_transition

        user_id = get_jwt_identity()
        material = get_material_with_permission(material_id, user_id)

        if not material:
            return jsonify({'success': False, 'error': '材料不存在或无权限'}), 404

        if material.type not in ['image', 'pdf']:
            return jsonify({'success': False, 'error': '只支持图片和PDF材料'}), 400

        # 检查翻译锁
        is_locked, _ = check_translation_lock(material_id)
        if is_locked:
            return jsonify({
                'success': False,
                'error': '该材料正在翻译中，请等待完成'
            }), 409

        # 获取请求参数
        data = request.get_json() or {}
        clear_previous = data.get('clearPreviousData', True)

        log_message(f"[原子API] translate-baidu 开始: {material.name}", "INFO")

        # 清除旧数据（如果需要）
        if clear_previous:
            material.edited_image_path = None
            material.final_image_path = None
            material.has_edited_version = False
            material.edited_regions = None
            material.llm_translation_result = None
            # 注意：不清除实体数据，保留用户之前的设置

        # WebSocket推送
        if WEBSOCKET_ENABLED:
            emit_translation_started(material.client_id, material.id, f"开始翻译 {material.name}")

        # 调用百度翻译
        result = translate_image_reference(
            image_path=material.file_path,
            source_lang='zh',
            target_lang='en'
        )

        # 检查API错误
        error_code = result.get('error_code')
        if error_code and error_code not in [0, '0', None]:
            error_msg = result.get('error_msg', '翻译失败')
            log_message(f"[原子API] 百度API错误: {error_msg}", "ERROR")
            update_material_status(material, MaterialStatus.FAILED, translation_error=error_msg)
            return jsonify({'success': False, 'error': error_msg}), 500

        # 解析结果
        api_data = result.get('data', {})
        content = api_data.get('content', [])

        if not content:
            log_message(f"[原子API] 未识别到文字: {material.name}", "WARN")
            update_material_status(material, MaterialStatus.FAILED, translation_error='未识别到文字区域')
            return jsonify({'success': False, 'error': '未识别到文字区域'}), 400

        # 构建regions格式
        regions = [
            {
                'id': i,
                'src': item.get('src', ''),
                'dst': item.get('dst', ''),
                'points': item.get('points', []),
                'lineCount': item.get('lineCount', 1)
            } for i, item in enumerate(content)
        ]

        translation_data = {'regions': regions}

        # 更新状态
        update_material_status(
            material,
            MaterialStatus.TRANSLATED,
            translation_text_info=translation_data,
            translation_error=None,
            processing_step=ProcessingStep.TRANSLATED.value,
            processing_progress=100
        )

        log_message(f"[原子API] translate-baidu 完成: {material.name}, {len(regions)} 个区域", "SUCCESS")

        # 获取可用操作
        state_machine, _ = get_state_machine()
        available_actions = state_machine.get_available_actions(ProcessingStep.TRANSLATED.value)

        return jsonify({
            'success': True,
            'processingStep': ProcessingStep.TRANSLATED.value,
            'translationTextInfo': translation_data,
            'material': material.to_dict(),
            'availableActions': available_actions,
            'message': f'百度OCR完成，识别 {len(regions)} 个区域'
        })

    except Exception as e:
        logger.exception(f"translate-baidu 失败: {str(e)}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@atomic_bp.route('/<material_id>/entity/recognize', methods=['POST'])
@jwt_required()
def entity_recognize(material_id):
    """
    原子操作：只执行实体识别

    不自动确认，不自动触发LLM。
    识别完成后状态变为 entity_pending_confirm，等待用户确认。

    请求体:
        {
            "mode": "fast" | "deep"  // 识别模式
        }

    返回:
        {
            "success": true,
            "processingStep": "entity_pending_confirm",
            "entities": [...],
            "availableActions": ["entity_confirm", "entity_skip"]
        }
    """
    try:
        from app import Material, Client, db, update_material_status, MaterialStatus, log_message
        from workflow.atomic_state_machine import ProcessingStep, AtomicAction, validate_transition
        from entity_recognition_service import EntityRecognitionService

        user_id = get_jwt_identity()
        material = get_material_with_permission(material_id, user_id)

        if not material:
            return jsonify({'success': False, 'error': '材料不存在或无权限'}), 404

        # 验证状态转换
        current_step = material.processing_step or ProcessingStep.UPLOADED.value
        is_valid, next_step, error_msg = validate_transition(current_step, AtomicAction.ENTITY_RECOGNIZE.value)

        if not is_valid:
            return jsonify({'success': False, 'error': error_msg}), 400

        # 获取OCR结果
        if not material.translation_text_info:
            return jsonify({'success': False, 'error': '请先执行百度OCR翻译'}), 400

        ocr_result = json.loads(material.translation_text_info) if isinstance(material.translation_text_info, str) else material.translation_text_info

        # 获取识别模式
        data = request.get_json() or {}
        mode = data.get('mode', 'fast')

        if mode not in ['fast', 'deep']:
            return jsonify({'success': False, 'error': '无效的识别模式，必须为 fast 或 deep'}), 400

        log_message(f"[原子API] entity/recognize 开始: {material.name}, 模式: {mode}", "INFO")

        # 更新状态为识别中
        material.processing_step = ProcessingStep.ENTITY_RECOGNIZING.value
        material.entity_recognition_mode = mode
        material.entity_recognition_enabled = True
        db.session.commit()

        # 调用实体识别服务
        entity_service = EntityRecognitionService()
        entity_result = entity_service.recognize_entities(ocr_result, mode=mode)

        if not entity_result.get('success'):
            error = entity_result.get('error', '实体识别失败')
            material.entity_recognition_error = error
            material.processing_step = ProcessingStep.TRANSLATED.value
            db.session.commit()
            log_message(f"[原子API] 实体识别失败: {error}", "WARN")
            return jsonify({'success': False, 'error': error}), 500

        # 保存识别结果
        material.entity_recognition_result = json.dumps(entity_result, ensure_ascii=False)
        material.processing_step = ProcessingStep.ENTITY_PENDING_CONFIRM.value
        material.processing_progress = 100
        material.entity_recognition_error = None
        db.session.commit()

        log_message(f"[原子API] entity/recognize 完成: {material.name}, {entity_result.get('total_entities', 0)} 个实体", "SUCCESS")

        # 获取可用操作
        state_machine, _ = get_state_machine()
        available_actions = state_machine.get_available_actions(ProcessingStep.ENTITY_PENDING_CONFIRM.value)

        return jsonify({
            'success': True,
            'processingStep': ProcessingStep.ENTITY_PENDING_CONFIRM.value,
            'entities': entity_result.get('entities', []),
            'entityResult': entity_result,
            'material': material.to_dict(),
            'availableActions': available_actions,
            'message': f'实体识别完成，识别到 {entity_result.get("total_entities", 0)} 个实体'
        })

    except Exception as e:
        logger.exception(f"entity/recognize 失败: {str(e)}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@atomic_bp.route('/<material_id>/entity/confirm', methods=['POST'])
@jwt_required()
def entity_confirm(material_id):
    """
    原子操作：只确认实体编辑

    不自动触发LLM优化！前端需要根据 availableActions 决定是否调用 llm/optimize。

    请求体:
        {
            "entities": [...],           // 用户编辑后的实体列表
            "translationGuidance": {...} // 翻译指导
        }

    返回:
        {
            "success": true,
            "processingStep": "entity_confirmed",
            "availableActions": ["llm_optimize", "skip_to_review"]
        }
    """
    try:
        from app import Material, Client, db, log_message
        from workflow.atomic_state_machine import ProcessingStep, AtomicAction, validate_transition

        user_id = get_jwt_identity()
        material = get_material_with_permission(material_id, user_id)

        if not material:
            return jsonify({'success': False, 'error': '材料不存在或无权限'}), 404

        # 验证状态转换
        current_step = material.processing_step or ProcessingStep.UPLOADED.value
        is_valid, next_step, error_msg = validate_transition(current_step, AtomicAction.ENTITY_CONFIRM.value)

        if not is_valid:
            return jsonify({'success': False, 'error': error_msg}), 400

        # 获取请求数据
        data = request.get_json() or {}
        entities = data.get('entities', [])
        translation_guidance = data.get('translationGuidance', {})

        log_message(f"[原子API] entity/confirm 开始: {material.name}", "INFO")

        # 保存用户编辑
        user_edits = {
            'entities': entities,
            'translationGuidance': translation_guidance
        }
        material.entity_user_edits = json.dumps(user_edits, ensure_ascii=False)
        material.entity_recognition_confirmed = True
        material.processing_step = ProcessingStep.ENTITY_CONFIRMED.value
        db.session.commit()

        log_message(f"[原子API] entity/confirm 完成: {material.name}", "SUCCESS")

        # 获取可用操作
        state_machine, _ = get_state_machine()
        available_actions = state_machine.get_available_actions(ProcessingStep.ENTITY_CONFIRMED.value)

        # 注意：这里不自动触发LLM！
        # 前端需要根据 availableActions 决定是否调用 /llm/optimize

        return jsonify({
            'success': True,
            'processingStep': ProcessingStep.ENTITY_CONFIRMED.value,
            'material': material.to_dict(),
            'availableActions': available_actions,
            'message': '实体已确认，可以继续LLM优化或直接预览'
        })

    except Exception as e:
        logger.exception(f"entity/confirm 失败: {str(e)}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@atomic_bp.route('/<material_id>/llm/optimize', methods=['POST'])
@jwt_required()
def llm_optimize(material_id):
    """
    原子操作：只执行LLM优化翻译

    可以从 translated 或 entity_confirmed 状态调用。
    支持独立调用和重试。

    请求体:
        {
            "useEntityGuidance": true  // 是否使用实体指导（如果有）
        }

    返回:
        {
            "success": true,
            "processingStep": "llm_translated",
            "llmTranslationResult": [...],
            "availableActions": ["review", "llm_retry"]
        }
    """
    try:
        from app import Material, Client, db, update_material_status, MaterialStatus, log_message
        from workflow.atomic_state_machine import ProcessingStep, AtomicAction, validate_transition
        from llm_service import LLMTranslationService

        user_id = get_jwt_identity()
        material = get_material_with_permission(material_id, user_id)

        if not material:
            return jsonify({'success': False, 'error': '材料不存在或无权限'}), 404

        # 验证状态转换
        current_step = material.processing_step or ProcessingStep.UPLOADED.value
        is_valid, next_step, error_msg = validate_transition(current_step, AtomicAction.LLM_OPTIMIZE.value)

        if not is_valid:
            return jsonify({'success': False, 'error': error_msg}), 400

        # 获取OCR结果
        if not material.translation_text_info:
            return jsonify({'success': False, 'error': '请先执行百度OCR翻译'}), 400

        ocr_data = json.loads(material.translation_text_info) if isinstance(material.translation_text_info, str) else material.translation_text_info
        regions = ocr_data.get('regions', [])

        if not regions:
            return jsonify({'success': False, 'error': '没有可翻译的内容'}), 400

        # 获取请求参数
        data = request.get_json() or {}
        use_entity_guidance = data.get('useEntityGuidance', True)

        log_message(f"[原子API] llm/optimize 开始: {material.name}", "INFO")

        # 更新状态为LLM翻译中
        material.processing_step = ProcessingStep.LLM_TRANSLATING.value
        db.session.commit()

        # 获取实体指导（如果有且需要）
        entity_guidance = None
        if use_entity_guidance and material.entity_user_edits:
            try:
                user_edits = json.loads(material.entity_user_edits) if isinstance(material.entity_user_edits, str) else material.entity_user_edits
                entity_guidance = user_edits.get('translationGuidance')
            except:
                pass

        # 调用LLM服务
        llm_service = LLMTranslationService(output_folder='outputs')
        llm_translations = llm_service.optimize_translations(regions, entity_guidance=entity_guidance)

        # 保存结果
        update_material_status(
            material,
            MaterialStatus.TRANSLATED,
            llm_translation_result=json.dumps(llm_translations, ensure_ascii=False),
            processing_step=ProcessingStep.LLM_TRANSLATED.value,
            processing_progress=100
        )

        log_message(f"[原子API] llm/optimize 完成: {material.name}, {len(llm_translations)} 个翻译", "SUCCESS")

        # 获取可用操作
        state_machine, _ = get_state_machine()
        available_actions = state_machine.get_available_actions(ProcessingStep.LLM_TRANSLATED.value)

        return jsonify({
            'success': True,
            'processingStep': ProcessingStep.LLM_TRANSLATED.value,
            'llmTranslationResult': llm_translations,
            'material': material.to_dict(),
            'availableActions': available_actions,
            'message': f'LLM优化完成，{len(llm_translations)} 个翻译结果'
        })

    except Exception as e:
        logger.exception(f"llm/optimize 失败: {str(e)}")
        # 恢复状态
        try:
            from app import Material, db
            from workflow.atomic_state_machine import ProcessingStep
            material = Material.query.get(material_id)
            if material:
                material.processing_step = ProcessingStep.TRANSLATED.value
                db.session.commit()
        except:
            pass

        return jsonify({
            'success': False,
            'error': str(e),
            'availableActions': ['llm_retry', 'skip_to_review']  # 失败后可重试或跳过
        }), 500


@atomic_bp.route('/<material_id>/entity/skip', methods=['POST'])
@jwt_required()
def entity_skip(material_id):
    """
    原子操作：跳过实体识别/确认

    将状态从 entity_pending_confirm 恢复到 translated。

    返回:
        {
            "success": true,
            "processingStep": "translated",
            "availableActions": ["entity_recognize", "llm_optimize", "skip_to_review"]
        }
    """
    try:
        from app import Material, Client, db, log_message
        from workflow.atomic_state_machine import ProcessingStep, AtomicAction, validate_transition

        user_id = get_jwt_identity()
        material = get_material_with_permission(material_id, user_id)

        if not material:
            return jsonify({'success': False, 'error': '材料不存在或无权限'}), 404

        # 验证状态转换
        current_step = material.processing_step or ProcessingStep.UPLOADED.value
        is_valid, next_step, error_msg = validate_transition(current_step, AtomicAction.ENTITY_SKIP.value)

        if not is_valid:
            return jsonify({'success': False, 'error': error_msg}), 400

        log_message(f"[原子API] entity/skip: {material.name}", "INFO")

        # 清除实体数据，恢复到translated状态
        material.entity_recognition_enabled = False
        material.entity_recognition_result = None
        material.entity_user_edits = None
        material.entity_recognition_confirmed = False
        material.processing_step = ProcessingStep.TRANSLATED.value
        db.session.commit()

        # 获取可用操作
        state_machine, _ = get_state_machine()
        available_actions = state_machine.get_available_actions(ProcessingStep.TRANSLATED.value)

        return jsonify({
            'success': True,
            'processingStep': ProcessingStep.TRANSLATED.value,
            'material': material.to_dict(),
            'availableActions': available_actions,
            'message': '已跳过实体识别'
        })

    except Exception as e:
        logger.exception(f"entity/skip 失败: {str(e)}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

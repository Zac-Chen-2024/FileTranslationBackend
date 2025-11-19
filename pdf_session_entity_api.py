# PDF Session 整体实体识别 API
# 将下面的代码插入到 app.py 中 entity-recognition/deep 之后

@app.route('/api/pdf-sessions/<session_id>/entity-recognition/fast', methods=['POST'])
@jwt_required()
def pdf_session_entity_recognition_fast(session_id):
    """
    PDF Session 整体实体识别
    使用整个PDF所有页面的OCR结果一起进行实体识别
    """
    try:
        print(f"\n{'='*80}")
        print(f"[PDF Entity] PDF Session 整体实体识别开始")
        print(f"[PDF Entity] Session ID: {session_id}")
        print(f"{'='*80}\n")

        current_user_id = get_jwt_identity()
        user = User.query.get(current_user_id)
        if not user:
            return jsonify({'success': False, 'error': '用户不存在'}), 404

        # 获取该PDF Session的所有页面
        pages = Material.query.filter_by(pdf_session_id=session_id).order_by(Material.pdf_page_number).all()
        
        if not pages:
            return jsonify({'success': False, 'error': 'PDF Session不存在'}), 404

        # 验证权限（检查第一页）
        client = Client.query.get(pages[0].client_id)
        if not client or client.user_id != current_user_id:
            return jsonify({'success': False, 'error': '无权限操作此PDF'}), 403

        print(f"[PDF Entity] 找到 {len(pages)} 个页面")

        # 检查所有页面是否都完成了OCR
        all_ocr_completed = all(p.translation_text_info for p in pages)
        if not all_ocr_completed:
            not_completed = [p.pdf_page_number for p in pages if not p.translation_text_info]
            print(f"[PDF Entity] 部分页面未完成OCR: {not_completed}")
            return jsonify({
                'success': False, 
                'error': f'部分页面未完成OCR: {not_completed}',
                'not_completed_pages': not_completed
            }), 400

        # 合并所有页面的OCR结果
        print(f"[PDF Entity] 合并所有页面的OCR结果...")
        merged_ocr_result = {'regions': []}
        
        for page in pages:
            ocr_result = json.loads(page.translation_text_info)
            regions = ocr_result.get('regions', [])
            merged_ocr_result['regions'].extend(regions)
        
        total_regions = len(merged_ocr_result['regions'])
        print(f"[PDF Entity] 合并后共 {total_regions} 个文本区域")

        # 设置所有页面状态为识别中
        for page in pages:
            page.processing_step = ProcessingStep.ENTITY_RECOGNIZING.value
            page.entity_recognition_triggered = True
        db.session.commit()

        # WebSocket推送状态更新（第一页）
        if WEBSOCKET_ENABLED:
            emit_material_updated(
                pages[0].client_id,
                pages[0].id,
                processing_step=ProcessingStep.ENTITY_RECOGNIZING.value,
                material=pages[0].to_dict()
            )

        # 调用快速实体识别服务
        from entity_recognition_service import EntityRecognitionService
        entity_service = EntityRecognitionService()
        entity_result = entity_service.recognize_entities(merged_ocr_result, mode="fast")

        if entity_result.get('success'):
            print(f"[PDF Entity] 识别成功，识别到 {entity_result.get('total_entities', 0)} 个实体")

            # 保存结果到所有页面
            result_json = json.dumps(entity_result, ensure_ascii=False)
            for page in pages:
                page.entity_recognition_result = result_json
                page.processing_step = ProcessingStep.ENTITY_PENDING_CONFIRM.value
            
            db.session.commit()

            # WebSocket推送更新（只推送第一页，前端会显示Modal）
            if WEBSOCKET_ENABLED:
                emit_material_updated(
                    pages[0].client_id,
                    pages[0].id,
                    processing_step=ProcessingStep.ENTITY_PENDING_CONFIRM.value,
                    material=pages[0].to_dict()
                )

            log_message(f"PDF Session整体实体识别完成: {session_id}, 共{len(pages)}页, 识别到 {entity_result.get('total_entities', 0)} 个实体", "INFO")

            return jsonify({
                'success': True,
                'result': entity_result,
                'session_id': session_id,
                'total_pages': len(pages),
                'total_regions': total_regions,
                'message': f'PDF整体识别完成（{len(pages)}页），识别到{entity_result.get("total_entities", 0)}个实体'
            })
        else:
            log_message(f"PDF Session整体实体识别失败: {session_id}, 错误: {entity_result.get('error')}", "ERROR")

            # 恢复所有页面状态
            for page in pages:
                page.processing_step = ProcessingStep.TRANSLATED.value
            db.session.commit()

            return jsonify({
                'success': False,
                'error': entity_result.get('error', 'PDF整体识别失败'),
                'recoverable': entity_result.get('recoverable', False)
            }), 500

    except Exception as e:
        log_message(f"PDF Session整体实体识别异常: {str(e)}", "ERROR")
        import traceback
        traceback.print_exc()
        return jsonify({
            'success': False,
            'error': 'PDF整体识别异常',
            'message': str(e)
        }), 500

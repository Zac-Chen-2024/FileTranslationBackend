"""
app.py WebSocket 集成补丁

这个文件包含需要添加到 app.py 的代码片段
按照注释中的位置添加到对应的地方
"""

# ============================================================
# 1. 在文件开头的导入部分添加（第4行之后）
# ============================================================
IMPORTS_TO_ADD = """
from flask_socketio import SocketIO
"""

# ============================================================
# 2. 在创建 Flask app 和 CORS 之后添加（第71行之后）
# ============================================================
SOCKETIO_INIT = """
# ✅ 初始化 SocketIO（WebSocket 支持）
socketio = SocketIO(app, 
                   cors_allowed_origins="*",  # 生产环境应该限制具体域名
                   async_mode='eventlet',
                   logger=True,
                   engineio_logger=False)

# 导入并初始化 WebSocket 事件处理
try:
    from websocket_events import init_socketio_events, emit_translation_started, emit_material_updated, emit_material_error, emit_translation_completed, emit_llm_started, emit_llm_completed, emit_llm_error
    init_socketio_events(socketio)
    print('[WebSocket] SocketIO 初始化成功')
    WEBSOCKET_ENABLED = True
except Exception as e:
    print(f'[WebSocket] SocketIO 初始化失败: {e}')
    WEBSOCKET_ENABLED = False
    # 定义空函数，避免报错
    emit_translation_started = lambda *args, **kwargs: None
    emit_material_updated = lambda *args, **kwargs: None
    emit_material_error = lambda *args, **kwargs: None
    emit_translation_completed = lambda *args, **kwargs: None
    emit_llm_started = lambda *args, **kwargs: None
    emit_llm_completed = lambda *args, **kwargs: None
    emit_llm_error = lambda *args, **kwargs: None
"""

# ============================================================
# 3. 在文件最后的运行部分修改（替换 app.run）
# ============================================================
RUN_METHOD_OLD = """
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5010, debug=True)
"""

RUN_METHOD_NEW = """
if __name__ == '__main__':
    # ✅ 使用 SocketIO 运行（支持 WebSocket）
    if WEBSOCKET_ENABLED:
        print('[WebSocket] 使用 SocketIO 运行服务器')
        socketio.run(app, host='0.0.0.0', port=5010, debug=True)
    else:
        print('[WebSocket] WebSocket 未启用，使用普通模式运行')
        app.run(host='0.0.0.0', port=5010, debug=True)
"""

# ============================================================
# 4. 示例：在翻译路由中添加 WebSocket 推送
# ============================================================
TRANSLATION_ROUTE_EXAMPLE = """
@app.route('/api/clients/<client_id>/translate', methods=['POST'])
@jwt_required()
def start_translation(client_id):
    # ... 现有代码 ...
    
    # ✅ 推送翻译开始
    if WEBSOCKET_ENABLED:
        emit_translation_started(socketio, client_id, '翻译已开始')
    
    success_count = 0
    failed_count = 0
    
    # 处理每个材料
    for material in materials:
        try:
            # ... 翻译处理代码 ...
            
            # ✅ 推送材料更新
            if WEBSOCKET_ENABLED:
                emit_material_updated(
                    socketio,
                    client_id,
                    material.id,
                    status='翻译完成',
                    progress=100,
                    translated_path=translated_path,
                    translation_info=translation_text_info
                )
            
            success_count += 1
            
        except Exception as e:
            # ✅ 推送错误
            if WEBSOCKET_ENABLED:
                emit_material_error(socketio, client_id, material.id, str(e))
            
            failed_count += 1
    
    # ✅ 推送完成
    if WEBSOCKET_ENABLED:
        emit_translation_completed(
            socketio,
            client_id,
            f'完成 {success_count} 个翻译',
            success_count=success_count,
            failed_count=failed_count
        )
    
    return jsonify({...})
"""

# ============================================================
# 5. 示例：在 LLM 翻译路由中添加 WebSocket 推送
# ============================================================
LLM_ROUTE_EXAMPLE = """
@app.route('/api/materials/<material_id>/llm-translate', methods=['POST'])
@jwt_required()
def llm_translate_material(material_id):
    try:
        # ... 获取 material ...
        
        # ✅ 推送 LLM 开始
        if WEBSOCKET_ENABLED:
            emit_llm_started(socketio, material_id, progress=66)
        
        # ... 调用 LLM 服务处理翻译 ...
        result = llm_service.optimize_translations(regions)
        
        # 保存结果
        material.llmTranslationResult = json.dumps(result, ensure_ascii=False)
        material.processingProgress = 100
        db.session.commit()
        
        # ✅ 推送 LLM 完成
        if WEBSOCKET_ENABLED:
            emit_llm_completed(socketio, material_id, result, progress=100)
        
        return jsonify({
            'success': True,
            'llm_translations': result
        })
        
    except Exception as e:
        # ✅ 推送 LLM 错误
        if WEBSOCKET_ENABLED:
            emit_llm_error(socketio, material_id, str(e))
        
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500
"""

# ============================================================
# 使用说明
# ============================================================
USAGE = """
使用此补丁的步骤：

1. 备份 app.py
   cp app.py app.py.backup

2. 在 app.py 开头添加导入：
   在第4行 "from flask import ..." 之后添加：
   from flask_socketio import SocketIO

3. 在创建 app 后初始化 SocketIO：
   在第71行 "CORS(app)" 之后，添加 SOCKETIO_INIT 中的代码

4. 修改运行方式：
   在文件末尾，将 app.run(...) 替换为 socketio.run(...)

5. 在翻译函数中添加推送：
   参考 TRANSLATION_ROUTE_EXAMPLE 和 LLM_ROUTE_EXAMPLE

6. 测试：
   python app.py
   应该看到 "[WebSocket] SocketIO 初始化成功"
"""

print(USAGE)


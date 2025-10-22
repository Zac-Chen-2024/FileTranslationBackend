"""
WebSocket 事件处理模块
用于实时推送翻译进度和结果到前端
"""

from flask_socketio import emit, join_room, leave_room
from flask import request

# 全局 socketio 实例（初始化后设置）
_socketio = None

def init_socketio_events(socketio):
    """初始化 WebSocket 事件处理器"""
    global _socketio
    _socketio = socketio
    
    @socketio.on('connect')
    def handle_connect():
        """客户端连接"""
        print(f'[WebSocket] 客户端已连接: {request.sid}')
        emit('connected', {'data': '连接成功', 'sid': request.sid})
    
    @socketio.on('disconnect')
    def handle_disconnect():
        """客户端断开"""
        print(f'[WebSocket] 客户端已断开: {request.sid}')
    
    @socketio.on('join_client')
    def handle_join_client(data):
        """加入客户端房间，用于接收该客户端的更新"""
        client_id = data.get('client_id')
        if client_id:
            room_name = f'client_{client_id}'
            join_room(room_name)
            print(f'[WebSocket] 客户端 {request.sid} 加入房间: {room_name}')
            emit('joined', {'client_id': client_id, 'room': room_name})
        else:
            print(f'[WebSocket] 错误: 未提供 client_id')
            emit('error', {'message': '未提供 client_id'})
    
    @socketio.on('leave_client')
    def handle_leave_client(data):
        """离开客户端房间"""
        client_id = data.get('client_id')
        if client_id:
            room_name = f'client_{client_id}'
            leave_room(room_name)
            print(f'[WebSocket] 客户端 {request.sid} 离开房间: {room_name}')
            emit('left', {'client_id': client_id, 'room': room_name})
    
    @socketio.on('join_material')
    def handle_join_material(data):
        """加入材料房间，用于接收该材料的 LLM 更新"""
        material_id = data.get('material_id')
        if material_id:
            room_name = f'material_{material_id}'
            join_room(room_name)
            print(f'[WebSocket] 客户端 {request.sid} 加入材料房间: {room_name}')
            emit('joined_material', {'material_id': material_id, 'room': room_name})
    
    @socketio.on('ping')
    def handle_ping():
        """心跳检测"""
        emit('pong', {'timestamp': request.sid})
    
    print('[WebSocket] 事件处理器初始化完成')


# WebSocket 推送辅助函数（供其他模块调用）

def emit_translation_started(client_id, material_id, message='翻译已开始'):
    """推送翻译开始事件"""
    if not _socketio:
        print('[WebSocket] 警告: socketio 未初始化')
        return
    room_name = f'client_{client_id}'
    _socketio.emit('translation_started', {
        'client_id': client_id,
        'material_id': material_id,
        'message': message
    }, room=room_name)
    print(f'[WebSocket] 推送翻译开始: {room_name}, 材料={material_id}')


def emit_material_updated(client_id, material_id, status, progress=None,
                          translated_path=None, translation_info=None,
                          processing_step=None, processing_progress=None,
                          file_path=None):
    """推送材料更新事件"""
    if not _socketio:
        print('[WebSocket] 警告: socketio 未初始化')
        return
    room_name = f'client_{client_id}'
    data = {
        'client_id': client_id,
        'material_id': material_id,
        'status': status,
    }
    if progress is not None:
        data['progress'] = progress
    if translated_path:
        data['translated_path'] = translated_path
    if translation_info:
        data['translation_info'] = translation_info
    if processing_step is not None:
        data['processing_step'] = processing_step
    if processing_progress is not None:
        data['processing_progress'] = processing_progress
    if file_path is not None:
        data['file_path'] = file_path

    _socketio.emit('material_updated', data, room=room_name)
    print(f'[WebSocket] 推送材料更新: {room_name}, 材料={material_id}, 状态={status}, 进度={progress}')


def emit_material_error(client_id, material_id, error):
    """推送材料错误事件"""
    if not _socketio:
        print('[WebSocket] 警告: socketio 未初始化')
        return
    room_name = f'client_{client_id}'
    _socketio.emit('material_error', {
        'client_id': client_id,
        'material_id': material_id,
        'error': str(error)
    }, room=room_name)
    print(f'[WebSocket] 推送材料错误: {room_name}, 材料={material_id}, 错误={error}')


def emit_translation_completed(client_id, message, success_count=0, failed_count=0):
    """推送翻译完成事件"""
    if not _socketio:
        print('[WebSocket] 警告: socketio 未初始化')
        return
    room_name = f'client_{client_id}'
    _socketio.emit('translation_completed', {
        'client_id': client_id,
        'message': message,
        'success_count': success_count,
        'failed_count': failed_count
    }, room=room_name)
    print(f'[WebSocket] 推送翻译完成: {room_name}, 成功={success_count}, 失败={failed_count}')


def emit_llm_started(material_id, progress=66):
    """推送 LLM 翻译开始事件"""
    if not _socketio:
        print('[WebSocket] 警告: socketio 未初始化')
        return
    room_name = f'material_{material_id}'
    _socketio.emit('llm_started', {
        'material_id': material_id,
        'progress': progress,
        'message': 'LLM优化开始'
    }, room=room_name)
    # 同时广播到所有连接（因为前端可能没有加入 material 房间）
    _socketio.emit('llm_started', {
        'material_id': material_id,
        'progress': progress,
        'message': 'LLM优化开始'
    })
    print(f'[WebSocket] 推送 LLM 开始: 材料={material_id}, 进度={progress}')


def emit_llm_completed(material_id, translations, progress=100):
    """推送 LLM 翻译完成事件"""
    if not _socketio:
        print('[WebSocket] 警告: socketio 未初始化')
        return
    room_name = f'material_{material_id}'
    _socketio.emit('llm_completed', {
        'material_id': material_id,
        'progress': progress,
        'translations': translations,
        'message': 'LLM优化完成'
    }, room=room_name)
    # 同时广播到所有连接
    _socketio.emit('llm_completed', {
        'material_id': material_id,
        'progress': progress,
        'translations': translations,
        'message': 'LLM优化完成'
    })
    print(f'[WebSocket] 推送 LLM 完成: 材料={material_id}, 进度={progress}')


def emit_llm_error(material_id, error):
    """推送 LLM 翻译错误事件"""
    if not _socketio:
        print('[WebSocket] 警告: socketio 未初始化')
        return
    room_name = f'material_{material_id}'
    _socketio.emit('llm_error', {
        'material_id': material_id,
        'error': str(error),
        'message': 'LLM优化失败'
    }, room=room_name)
    # 同时广播到所有连接
    _socketio.emit('llm_error', {
        'material_id': material_id,
        'error': str(error),
        'message': 'LLM优化失败'
    })
    print(f'[WebSocket] 推送 LLM 错误: 材料={material_id}, 错误={error}')


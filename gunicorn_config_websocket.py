import os

# WebSocket 配置
bind = "0.0.0.0:5010"
workers = 1  # WebSocket 只能用1个worker
worker_class = "eventlet"  # 使用 eventlet
timeout = 300
keepalive = 5

# 日志配置
accesslog = os.path.join(os.path.dirname(__file__), 'logs', 'access.log')
errorlog = os.path.join(os.path.dirname(__file__), 'logs', 'error.log')
loglevel = 'info'

preload_app = True
daemon = False


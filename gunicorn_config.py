"""
Gunicorn配置文件
用于生产环境部署
"""

import multiprocessing
import os

# ✅ 使用标准同步worker + threading（最简单可靠）
bind = "0.0.0.0:5010"
workers = 1
worker_class = "sync"
threads = 4  # 每个worker 4个线程
timeout = 300
keepalive = 5

# 进程名称
proc_name = 'translation-platform'

# 日志配置
accesslog = os.path.join(os.path.dirname(__file__), 'logs', 'access.log')
errorlog = os.path.join(os.path.dirname(__file__), 'logs', 'error.log')
loglevel = 'info'
access_log_format = '%(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s" %(D)s'

# 预加载应用 - 暂时禁用以便代码热重载
preload_app = False

# PID文件
pidfile = os.path.join(os.path.dirname(__file__), 'gunicorn.pid')

# 守护进程
daemon = False

# 环境变量
raw_env = [
    'FLASK_ENV=production',
]

def when_ready(server):
    """服务器启动完成时的回调"""
    server.log.info("Server is ready. Spawning workers")

def worker_int(worker):
    """工作进程被中断时的回调"""
    worker.log.info("Worker received INT or QUIT signal")

def pre_fork(server, worker):
    """工作进程创建前的回调"""
    server.log.info(f"Worker spawned (pid: {worker.pid})")

def post_fork(server, worker):
    """工作进程创建后的回调"""
    server.log.info(f"Worker spawned (pid: {worker.pid})")

def worker_exit(server, worker):
    """工作进程退出时的回调"""
    server.log.info(f"Worker exit (pid: {worker.pid})")
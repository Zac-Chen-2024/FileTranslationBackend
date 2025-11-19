# 完整版翻译功能集成后端
# 基于app_with_translation.py，添加完整的翻译功能

from flask import Flask, request, jsonify, send_file, render_template, send_from_directory
from flask_cors import CORS
from flask_sqlalchemy import SQLAlchemy
from flask_jwt_extended import JWTManager, jwt_required, create_access_token, get_jwt_identity, get_jwt
from flask_socketio import SocketIO
from sqlalchemy import text
import os
import time
import base64
import re
import json
import math
import asyncio
import subprocess
import argparse
import sys
import uuid
from datetime import datetime, timedelta
from pathlib import Path
import requests
from urllib.parse import urljoin, urlparse, quote
from bs4 import BeautifulSoup
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
import sqlite3
import zipfile
import io
import tempfile
import shutil
from functools import wraps
from threading import Lock
from enum import Enum

# ========== 状态枚举定义 ==========

class MaterialStatus(str, Enum):
    """材料状态枚举 - 统一管理所有状态值"""
    PENDING = '待处理'          # 初始状态（未使用）
    UPLOADED = '已上传'         # 文件已上传，等待翻译
    SPLITTING = '拆分中'        # PDF拆分进行中
    TRANSLATING = '翻译中'      # 翻译进行中
    TRANSLATED = '翻译完成'     # 翻译完成
    FAILED = '翻译失败'         # 翻译失败
    CONFIRMED = '已确认'        # 用户确认

class ProcessingStep(str, Enum):
    """处理步骤枚举"""
    UPLOADED = 'uploaded'            # 已上传
    SPLITTING = 'splitting'          # 拆分中
    SPLIT_COMPLETED = 'split_completed'  # 拆分完成
    TRANSLATING = 'translating'      # 翻译中（OCR翻译）
    TRANSLATED = 'translated'        # 翻译完成（OCR翻译完成）
    ENTITY_RECOGNIZING = 'entity_recognizing'  # 实体识别中
    ENTITY_PENDING_CONFIRM = 'entity_pending_confirm'  # 等待实体确认
    ENTITY_CONFIRMED = 'entity_confirmed'  # 实体已确认
    LLM_TRANSLATING = 'llm_translating'  # LLM翻译中
    LLM_TRANSLATED = 'llm_translated'  # LLM翻译完成
    FAILED = 'failed'                # 失败

# 百度翻译API配置会在translate_filename函数中动态加载

# 尝试导入翻译相关的库
try:
    from openai import OpenAI
    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False

try:
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    SELENIUM_AVAILABLE = True
except ImportError:
    SELENIUM_AVAILABLE = False

try:
    from pyppeteer import launch
    from PIL import Image
    PYPPETEER_AVAILABLE = True
except ImportError:
    PYPPETEER_AVAILABLE = False
    print("WARNING: pyppeteer or PIL not installed, some PDF generation features may not be available")

try:
    import fitz  # PyMuPDF
    PYMUPDF_AVAILABLE = True
except ImportError:
    PYMUPDF_AVAILABLE = False
    print("WARNING: PyMuPDF not installed, PDF split features may not be available")

# 创建Flask应用
app = Flask(__name__)
CORS(app, origins=["https://zac-chen-2024.github.io"], supports_credentials=True)

# ✅ 初始化 SocketIO（使用长轮询，不需要WebSocket）
socketio = SocketIO(app,
                   cors_allowed_origins=["https://zac-chen-2024.github.io"],
                   async_mode='threading',  # 使用 threading（最简单最可靠）
                   logger=True,
                   engineio_logger=False,
                   ping_timeout=60,
                   ping_interval=25)

# 导入并初始化 WebSocket 事件处理
try:
    from websocket_events import (init_socketio_events, emit_translation_started, 
                                 emit_material_updated, emit_material_error, 
                                 emit_translation_completed, emit_llm_started, 
                                 emit_llm_completed, emit_llm_error)
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

# 配置
app.config['SECRET_KEY'] = 'your-secret-key-change-this-in-production'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///translation_platform.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['JWT_SECRET_KEY'] = 'jwt-secret-key-change-this-in-production'
app.config['JWT_ACCESS_TOKEN_EXPIRES'] = timedelta(hours=24)
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024

# 初始化扩展
db = SQLAlchemy(app)
jwt = JWTManager(app)

# 暂时注释掉，等模型定义完成后再调用
# def refresh_database_metadata():
#     """强制刷新数据库元数据，解决SQLAlchemy缓存问题"""
#     try:
#         with app.app_context():
#             # 关闭现有连接
#             db.engine.dispose()
#             
#             # 清除元数据缓存
#             db.metadata.clear()
#             
#             # 重新反射表结构
#             db.metadata.reflect(bind=db.engine)
#             
#             # 确保所有表都被创建
#             db.create_all()
#             
#             print("数据库元数据已刷新")
#             return True
#     except Exception as e:
#         print(f"刷新元数据失败: {e}")
#         return False

# 添加请求日志中间件
@app.before_request
def log_request_info():
    """记录每个请求的信息"""
    # 判断是否是轮询请求（GET材料列表）
    is_polling = request.method == 'GET' and '/materials' in request.path and 'client' in request.path
    log_message(f"请求: {request.method} {request.path} - IP: {request.remote_addr}", "INFO", is_polling=is_polling)

# 创建必要的文件夹
os.makedirs('downloads', exist_ok=True)
os.makedirs('original_snapshot', exist_ok=True)
os.makedirs('translated_snapshot', exist_ok=True)
os.makedirs('poster_output', exist_ok=True)
os.makedirs('web_translation_output', exist_ok=True)
os.makedirs('uploads', exist_ok=True)
os.makedirs('image_translation_output', exist_ok=True)
os.makedirs('formula_output', exist_ok=True)


# JWT Token黑名单存储
blacklisted_tokens = set()

@jwt.token_in_blocklist_loader
def check_if_token_revoked(jwt_header, jwt_payload):
    return jwt_payload['jti'] in blacklisted_tokens

# ========== Google 网页翻译工具函数 ==========

def _sanitize_title(title: str) -> str:
    """清理网页标题，使其适合作为文件名"""
    title = (title or "webpage").strip().replace('\n', ' ')
    title = re.sub(r'[\\/*?:"<>|]', '_', title)
    return title[:80] or "webpage"

def _hide_google_translate_toolbar(driver):
    """移除 Google Translate 顶部工具栏"""
    try:
        driver.execute_script("var nv = document.getElementById('gt-nvframe'); if(nv){ nv.remove(); }")
        driver.execute_script("""
            var css = document.createElement("style");
            css.type = "text/css";
            css.innerHTML = `
                .goog-te-gadget, .goog-te-gadget-simple, #goog-gt-tt { display: none !important; }
            `;
            document.head.appendChild(css);
        """)
        log_message("已移除 Google Translate 顶部工具栏", "SUCCESS")
    except Exception as e:
        log_message(f"移除顶部工具栏时出错：{e}", "WARNING")

def _setup_chrome(disable_js: bool = False):
    """设置Chrome浏览器选项"""
    if not SELENIUM_AVAILABLE:
        raise RuntimeError("Selenium 不可用，请安装依赖或配置 ChromeDriver")
    
    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--window-size=1280,800")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-setuid-sandbox")
    options.add_argument("--disable-gpu")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--allow-insecure-localhost")
    options.add_argument("--ignore-certificate-errors")
    options.add_argument("--disable-web-security")
    options.add_argument("--allow-running-insecure-content")
    options.add_argument("--lang=en-US,en;q=0.9")

    # 额外的隔离选项
    options.add_argument("--disable-extensions")
    options.add_argument("--disable-background-networking")
    options.add_argument("--disable-sync")
    options.add_argument("--disable-default-apps")
    options.add_argument("--no-first-run")
    options.add_argument("--disable-background-timer-throttling")
    options.add_argument("--disable-backgrounding-occluded-windows")
    options.add_argument("--disable-renderer-backgrounding")

    # 使用随机remote debugging port来避免冲突
    import random
    options.add_argument(f"--remote-debugging-port={random.randint(9222, 9999)}")

    # 使用内存中的profile，避免磁盘冲突
    options.add_argument("--disable-features=UseChromeOSDirectVideoDecoder")

    # 指定一个snap可以访问的目录（在项目目录内）
    import tempfile
    import uuid
    import os
    import time
    chrome_data_dir = os.path.join(os.path.dirname(__file__), 'tmp', 'chrome_data')
    os.makedirs(chrome_data_dir, exist_ok=True)
    user_data_dir = os.path.join(chrome_data_dir, f"profile_{os.getpid()}_{int(time.time()*1000)}_{uuid.uuid4().hex[:8]}")
    options.add_argument(f"--user-data-dir={user_data_dir}")

    # Snap专用：允许访问更多目录
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-software-rasterizer")

    if disable_js:
        prefs = {"profile.managed_default_content_settings.javascript": 2}
        options.add_experimental_option("prefs", prefs)

    # 打印Chrome启动参数用于调试
    log_message(f"[Chrome启动] 进程ID: {os.getpid()}, 临时目录: {user_data_dir}", "DEBUG")
    log_message(f"[Chrome启动] 所有参数: {options.arguments}", "DEBUG")

    driver = webdriver.Chrome(options=options)

    # 将临时目录路径附加到 driver 对象，便于后续清理
    driver._user_data_dir = user_data_dir

    log_message(f"[Chrome启动] 成功创建driver实例", "DEBUG")
    return driver

def _cleanup_chrome_driver(driver):
    """关闭Chrome driver并清理临时目录"""
    try:
        driver.quit()
    except Exception as e:
        log_message(f"关闭Chrome driver失败: {str(e)}", "WARN")

    # 清理临时用户数据目录
    if hasattr(driver, '_user_data_dir'):
        import shutil
        try:
            shutil.rmtree(driver._user_data_dir, ignore_errors=True)
        except Exception as e:
            log_message(f"清理临时目录失败: {str(e)}", "WARN")

def _print_to_pdf(driver, pdf_path: str, scale: float = 0.9):
    """使用Chrome将页面打印为PDF"""
    margins = {"top": 0.4, "bottom": 0.4, "left": 0.4, "right": 0.4}
    print_options = {
        "paperWidth": 8.27,
        "paperHeight": 11.7,
        "marginTop": margins.get("top", 0.4),
        "marginBottom": margins.get("bottom", 0.4),
        "marginLeft": margins.get("left", 0.4),
        "marginRight": margins.get("right", 0.4),
        "printBackground": True,
        "scale": scale,
        "preferCSSPageSize": False,
    }
    result = driver.execute_cdp_cmd("Page.printToPDF", print_options)
    pdf_data = base64.b64decode(result['data'])
    os.makedirs(os.path.dirname(pdf_path), exist_ok=True)
    with open(pdf_path, "wb") as f:
        f.write(pdf_data)
    log_message(f"已保存 PDF: {pdf_path}", "SUCCESS")

def _capture_google_translated_pdf_pyppeteer(url: str) -> (str, str):
    """使用 Pyppeteer 渲染翻译页为 PDF"""
    if not PYPPETEER_AVAILABLE:
        raise RuntimeError("Pyppeteer 不可用")
    
    import asyncio
    from pyppeteer import launch
    
    async def _run():
        browser = await launch({
            'headless': True,
            'args': [
                '--no-sandbox',
                '--disable-setuid-sandbox',
                '--disable-gpu',
                '--allow-insecure-localhost',
                '--ignore-certificate-errors',
                '--lang=en-US,en;q=0.9',
            ]
        })
        page = await browser.newPage()
        await page.setViewport({'width': 1280, 'height': 800, 'deviceScaleFactor': 1})
        from urllib.parse import quote
        translate_url = f"https://translate.google.com/translate?hl=en&sl=auto&tl=en&u={quote(url)}&prev=search"
        log_message(f"[pyppeteer] 打开: {translate_url}", "DEBUG")
        await page.goto(translate_url, {'waitUntil': 'networkidle2', 'timeout': 60000})
        
        # 尝试等待主体内容稳定
        try:
            await page.waitForSelector('body', {'timeout': 20000})
        except Exception:
            pass
        
        # 使用 print 媒体
        try:
            await page.emulateMediaType('print')
        except Exception:
            pass
        
        safe_title = _sanitize_title(await page.title())
        out_dir = os.path.join('translated_snapshot')
        os.makedirs(out_dir, exist_ok=True)
        pdf_filename = f"{safe_title}.pdf"
        pdf_path = os.path.join(out_dir, pdf_filename)
        await page.pdf({
            'path': pdf_path,
            'format': 'A4',
            'printBackground': True,
            'margin': {'top': '0.4in', 'bottom': '0.4in', 'left': '0.4in', 'right': '0.4in'},
            'scale': 0.9
        })
        await browser.close()
        return pdf_path, pdf_filename
    
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(_run())
    finally:
        loop.close()

def _capture_google_translated_pdf(url: str) -> (str, str):
    """打开Google翻译页面并生成PDF，返回 (pdf_path, pdf_filename)"""
    # 优先使用 Pyppeteer
    if PYPPETEER_AVAILABLE:
        try:
            return _capture_google_translated_pdf_pyppeteer(url)
        except Exception as e:
            log_message(f"Pyppeteer 转 PDF 失败，回退到 Selenium: {str(e)}", "ERROR")
    
    from urllib.parse import quote
    driver = None
    try:
        driver = _setup_chrome(disable_js=False)
        translate_url = f"https://translate.google.com/translate?hl=en&sl=auto&tl=en&u={quote(url)}&prev=search"
        log_message(f"打开Google翻译地址: {translate_url}", "DEBUG")
        driver.get(translate_url)
        
        # 基本等待
        try:
            WebDriverWait(driver, 20).until(EC.presence_of_element_located((By.TAG_NAME, 'body')))
        except Exception:
            time.sleep(2)
        
        # 设置打印媒体
        try:
            driver.execute_cdp_cmd('Emulation.setEmulatedMedia', {'media': 'print'})
        except Exception:
            pass
        
        safe_title = _sanitize_title(driver.title)
        out_dir = os.path.join('translated_snapshot')
        os.makedirs(out_dir, exist_ok=True)
        pdf_filename = f"{safe_title}.pdf"
        pdf_path = os.path.join(out_dir, pdf_filename)
        _print_to_pdf(driver, pdf_path, scale=0.9)
        return pdf_path, pdf_filename
    finally:
        if driver:
            _cleanup_chrome_driver(driver)

# ========== 缓存实现 ==========
class SimpleCache:
    """简单的内存缓存实现"""
    def __init__(self):
        self.cache = {}
        self.lock = Lock()
        self.ttl = {}  # 存储每个键的过期时间
    
    def get(self, key):
        """获取缓存值"""
        with self.lock:
            # 检查是否过期
            if key in self.ttl and datetime.now() > self.ttl[key]:
                del self.cache[key]
                del self.ttl[key]
                return None
            return self.cache.get(key)
    
    def set(self, key, value, timeout_seconds=300):
        """设置缓存值，默认5分钟过期"""
        with self.lock:
            self.cache[key] = value
            self.ttl[key] = datetime.now() + timedelta(seconds=timeout_seconds)
    
    def delete(self, key):
        """删除缓存值"""
        with self.lock:
            if key in self.cache:
                del self.cache[key]
            if key in self.ttl:
                del self.ttl[key]
    
    def clear_expired(self):
        """清理过期的缓存"""
        with self.lock:
            current_time = datetime.now()
            expired_keys = [k for k, v in self.ttl.items() if current_time > v]
            for key in expired_keys:
                del self.cache[key]
                del self.ttl[key]

# 创建缓存实例
api_cache = SimpleCache()

def cache_key_for_user(user_id, prefix):
    """生成用户相关的缓存键"""
    return f"{prefix}:user:{user_id}"

def cache_key_for_client_materials(client_id):
    """生成客户材料列表的缓存键"""
    return f"materials:client:{client_id}"

def invalidate_client_cache(user_id):
    """使客户相关的缓存失效"""
    cache_key = cache_key_for_user(user_id, 'clients_list')
    api_cache.delete(cache_key)

def invalidate_materials_cache(client_id):
    """使材料列表缓存失效"""
    cache_key = cache_key_for_client_materials(client_id)
    api_cache.delete(cache_key)

def cache_api_response(cache_key_prefix, timeout_seconds=300):
    """API响应缓存装饰器"""
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            # 获取用户ID
            try:
                user_id = get_jwt_identity()
            except:
                # 如果没有JWT，直接执行原函数
                return f(*args, **kwargs)
            
            # 生成缓存键
            cache_key = cache_key_for_user(user_id, cache_key_prefix)
            
            # 检查缓存
            cached_response = api_cache.get(cache_key)
            if cached_response is not None:
                response, status_code = cached_response
                return response, status_code
            
            # 执行原函数
            result = f(*args, **kwargs)
            
            # 缓存成功的响应
            if isinstance(result, tuple):
                response, status_code = result
                if status_code == 200:
                    api_cache.set(cache_key, result, timeout_seconds)
            else:
                # 如果只返回响应对象，假设状态码为200
                api_cache.set(cache_key, (result, 200), timeout_seconds)
            
            return result
        
        return decorated_function
    return decorator

# 定期清理过期缓存
def cleanup_cache():
    """定期清理过期缓存的后台任务"""
    while True:
        time.sleep(600)  # 每10分钟清理一次
        api_cache.clear_expired()

# ========== 工具函数 ========== 

def get_baidu_access_token(api_key, secret_key):
    """获取百度翻译API的access_token"""
    try:
        # 百度获取access_token的API
        url = "https://aip.baidubce.com/oauth/2.0/token"
        params = {
            'grant_type': 'client_credentials',
            'client_id': api_key,
            'client_secret': secret_key
        }
        
        response = requests.post(url, params=params, timeout=10)
        result = response.json()
        
        if 'access_token' in result:
            log_message(f"百度access_token获取成功")
            return result['access_token']
        else:
            error_msg = result.get('error_description', result.get('error', '未知错误'))
            log_message(f"获取access_token失败: {error_msg}", "ERROR")
            return None
            
    except Exception as e:
        log_message(f"获取access_token异常: {e}", "ERROR")
        return None

def translate_filename_with_token(filename, access_token, target_lang='en'):
    """使用已有的access_token翻译文件名"""
    try:
        # 使用access_token调用翻译API
        url = f"https://aip.baidubce.com/rpc/2.0/mt/texttrans/v1?access_token={access_token}"
        
        headers = {
            'Content-Type': 'application/json;charset=utf-8'
        }
        
        data = {
            'from': 'auto',  # 自动检测源语言
            'to': target_lang if target_lang == 'en' else 'zh',
            'q': filename
        }
        
        # 发送POST请求
        response = requests.post(url, headers=headers, json=data, timeout=10)
        result = response.json()
        
        # 检查响应
        if 'result' in result and 'trans_result' in result['result']:
            trans_results = result['result']['trans_result']
            if trans_results:
                translated_text = trans_results[0]['dst']
                # 清理翻译结果，移除特殊字符
                import re
                translated_text = re.sub(r'[^\w\s-]', '', translated_text)
                translated_text = translated_text.replace(' ', '_')
                log_message(f"文件名翻译成功: '{filename}' -> '{translated_text}'")
                return translated_text
        
        # 如果没有翻译结果，记录错误信息
        error_msg = result.get('error_msg', result.get('error_code', '未知错误'))
        log_message(f"百度翻译API错误: {error_msg}", "WARN")
        return filename
            
    except Exception as e:
        log_message(f"文件名翻译失败: {e}", "WARN")
        return filename

def translate_filename(filename, target_lang='en'):
    """使用百度机器翻译API翻译文件名（获取新token）"""
    # 加载百度API密钥
    api_keys = load_api_keys()
    baidu_api_key = api_keys.get('BAIDU_API_KEY')
    baidu_secret_key = api_keys.get('BAIDU_SECRET_KEY')
    
    if not baidu_api_key or not baidu_secret_key:
        log_message("百度翻译API密钥未配置，返回原文件名", "WARN")
        return filename
    
    # 获取access_token
    access_token = get_baidu_access_token(baidu_api_key, baidu_secret_key)
    if not access_token:
        log_message("无法获取access_token，返回原文件名", "WARN")
        return filename
    
    return translate_filename_with_token(filename, access_token, target_lang)

import logging
from logging.handlers import RotatingFileHandler
import os

# 自定义控制台过滤器：只显示重要信息，过滤掉轮询日志
class ConsoleFilter(logging.Filter):
    def filter(self, record):
        # 过滤掉轮询相关的日志
        if 'polling' in record.getMessage().lower():
            return False
        if 'materials' in record.getMessage() and 'GET' in record.getMessage():
            return False
        # 只显示WARNING以上，或者包含SUCCESS的INFO日志
        if record.levelno >= logging.WARNING:
            return True
        if 'SUCCESS' in record.levelname or '✓' in record.getMessage():
            return True
        return False

# 配置日志系统
def setup_logging():
    """设置日志系统：主日志和轮询日志分离"""
    # 创建logs目录
    if not os.path.exists('logs'):
        os.makedirs('logs')

    # 主日志 - 记录业务操作
    main_logger = logging.getLogger('main')
    main_logger.setLevel(logging.INFO)

    # 主日志文件：自动轮转，最多保留5个文件，每个10MB
    main_handler = RotatingFileHandler(
        'logs/server.log',
        maxBytes=10*1024*1024,  # 10MB
        backupCount=5,
        encoding='utf-8'
    )
    main_handler.setLevel(logging.INFO)
    main_formatter = logging.Formatter('[%(asctime)s] [%(levelname)s] %(message)s')
    main_handler.setFormatter(main_formatter)
    main_logger.addHandler(main_handler)

    # 控制台输出 - 使用自定义过滤器，只显示重要信息
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)  # 接收INFO级别
    console_handler.setFormatter(main_formatter)
    console_handler.addFilter(ConsoleFilter())  # 添加过滤器，只显示重要信息
    main_logger.addHandler(console_handler)

    # 禁用Flask的werkzeug日志输出到控制台（避免刷屏）
    werkzeug_logger = logging.getLogger('werkzeug')
    werkzeug_logger.setLevel(logging.ERROR)  # 只显示ERROR及以上

    # 轮询日志 - 单独记录，避免淹没主日志
    polling_logger = logging.getLogger('polling')
    polling_logger.setLevel(logging.DEBUG)

    # 轮询日志文件：自动轮转，最多保留3个文件，每个5MB
    polling_handler = RotatingFileHandler(
        'logs/polling.log',
        maxBytes=5*1024*1024,  # 5MB
        backupCount=3,
        encoding='utf-8'
    )
    polling_handler.setLevel(logging.DEBUG)
    polling_formatter = logging.Formatter('[%(asctime)s] [POLLING] %(message)s')
    polling_handler.setFormatter(polling_formatter)
    polling_logger.addHandler(polling_handler)

    return main_logger, polling_logger

# 初始化日志
main_logger, polling_logger = setup_logging()

# ========== 状态更新辅助函数 ==========

def update_material_status(material, status, **kwargs):
    """
    统一的材料状态更新函数，包含版本控制和WebSocket推送

    Args:
        material: Material对象或material_id
        status: MaterialStatus枚举值
        **kwargs: 其他需要更新的字段
            - processing_step: ProcessingStep枚举值
            - processing_progress: 0-100的进度
            - translation_text_info: 翻译数据（会自动JSON序列化）
            - translation_error: 错误信息
            - translated_image_path: 翻译后图片路径
            - emit_websocket: 是否推送WebSocket（默认True）

    Returns:
        bool: 更新是否成功（失败表示版本冲突）
    """
    from flask import current_app

    # 如果传入的是ID，先查询
    if isinstance(material, str):
        material = db.session.get(Material, material)
        if not material:
            log_message(f"Material {material} 不存在", "ERROR")
            return False

    # 记录旧版本号
    old_version = material.version

    try:
        # 更新状态（使用枚举值）
        if isinstance(status, MaterialStatus):
            material.status = status.value
        else:
            material.status = status

        # 更新其他字段
        for key, value in kwargs.items():
            if key == 'translation_text_info' and isinstance(value, dict):
                # 自动序列化JSON
                setattr(material, key, json.dumps(value, ensure_ascii=False))
            elif key != 'emit_websocket':  # emit_websocket不是数据库字段
                setattr(material, key, value)

        # 增加版本号（乐观锁）
        material.version = old_version + 1
        material.updated_at = datetime.utcnow()

        # 提交到数据库
        db.session.commit()

        # WebSocket推送（如果启用）
        emit_websocket = kwargs.get('emit_websocket', True)
        if emit_websocket and WEBSOCKET_ENABLED:
            # 准备WebSocket数据
            ws_data = {
                'material_id': material.id,
                'status': material.status,
                'progress': material.processing_progress
            }

            # 添加可选字段
            if 'translated_image_path' in kwargs:
                ws_data['translated_path'] = kwargs['translated_image_path']
            if 'translation_text_info' in kwargs:
                ws_data['translation_info'] = kwargs['translation_text_info'] if isinstance(kwargs['translation_text_info'], dict) else json.loads(kwargs['translation_text_info'])

            # 发送WebSocket事件
            if material.status == MaterialStatus.TRANSLATED.value:
                emit_material_updated(material.client_id, **ws_data)
            elif material.status == MaterialStatus.FAILED.value:
                emit_material_error(material.client_id, material.id, material.translation_error or '翻译失败')
            else:
                emit_material_updated(material.client_id, **ws_data)

        log_message(f"✓ Material {material.id} 状态更新: {material.status} (v{material.version})", "SUCCESS")
        return True

    except Exception as e:
        db.session.rollback()
        log_message(f"✗ Material {material.id if hasattr(material, 'id') else 'unknown'} 状态更新失败: {str(e)}", "ERROR")
        return False

def check_translation_lock(material_id):
    """
    检查材料是否正在翻译中（防止重复翻译）

    Args:
        material_id: Material ID

    Returns:
        tuple: (is_locked, material) - (是否被锁定, Material对象)
    """
    material = db.session.get(Material, material_id)
    if not material:
        return False, None

    # 检查是否正在翻译
    is_locked = material.status == MaterialStatus.TRANSLATING.value

    return is_locked, material

def log_message(message, level="INFO", is_polling=False):
    """统一的日志输出函数

    Args:
        message: 日志消息
        level: 日志级别 (INFO, DEBUG, WARNING, ERROR, SUCCESS)
        is_polling: 是否是轮询日志（轮询日志会单独记录到polling.log）
    """
    # 轮询日志单独处理
    if is_polling:
        polling_logger.debug(message)
        return

    # 主日志根据级别输出
    if level == "DEBUG":
        main_logger.debug(message)
    elif level == "INFO":
        main_logger.info(message)
    elif level == "WARNING" or level == "WARN":
        main_logger.warning(message)
    elif level == "ERROR":
        main_logger.error(message)
    elif level == "SUCCESS":
        main_logger.info(f"✓ {message}")
    else:
        main_logger.info(message)

def load_api_keys():
    """加载API密钥"""
    keys = {}
    
    # 首先从老后端方式的单独文件读取API密钥
    api_key_files = {
        'BAIDU_API_KEY': 'config/baidu_api_key.txt',
        'BAIDU_SECRET_KEY': 'config/baidu_secret_key.txt',
        'OPENAI_API_KEY': 'config/openai_api_key.txt'
    }

    for key_name, file_path in api_key_files.items():
        if os.path.exists(file_path):
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    value = f.read().strip()
                    if value:
                        keys[key_name] = value
                        log_message(f"从 {file_path} 加载了 {key_name}", "INFO")
            except Exception as e:
                log_message(f"读取 {file_path} 失败: {e}", "WARNING")
    
    # 然后从config.env文件加载其他配置
    config_path = "config.env"
    if os.path.exists(config_path):
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if '=' in line and not line.startswith('#') and line:
                        key, value = line.split('=', 1)
                        key = key.strip()
                        value = value.strip()
                        # 如果百度密钥还没有从单独文件读取到，则从config.env读取
                        if key not in keys:
                            keys[key] = value
            log_message(f"从配置文件 config.env 加载了额外配置", "INFO")
        except Exception as e:
            log_message(f"读取配置文件失败: {e}", "WARNING")
    
    # 从环境变量加载（优先级更高）
    keys.update({
        'OPENAI_API_KEY': os.getenv('OPENAI_API_KEY', keys.get('OPENAI_API_KEY', '')),
        'BAIDU_API_KEY': os.getenv('BAIDU_API_KEY', keys.get('BAIDU_API_KEY', '')),
        'BAIDU_SECRET_KEY': os.getenv('BAIDU_SECRET_KEY', keys.get('BAIDU_SECRET_KEY', ''))
    })
    
    # 打印配置状态（不显示实际密钥）
    log_message(f"OpenAI API: {'已配置' if keys.get('OPENAI_API_KEY') else '未配置'}", "INFO")
    log_message(f"百度API: {'已配置' if keys.get('BAIDU_API_KEY') else '未配置'}", "INFO")
    
    return keys

# ========== Reference项目的百度API调用方式（完全照搬） ==========

def get_access_token_reference():
    """获取access token - Reference项目方式（带重试机制）"""
    print(f"[TOKEN] 开始获取 Access Token", flush=True)
    # 加载API密钥
    api_keys = load_api_keys()
    API_KEY = api_keys.get('BAIDU_API_KEY')
    SECRET_KEY = api_keys.get('BAIDU_SECRET_KEY')

    if not API_KEY or not SECRET_KEY:
        raise Exception("百度API密钥未配置")

    print(f"[TOKEN] API密钥已加载", flush=True)
    log_message(f"获取Access Token...", "INFO")
    log_message(f"API_KEY: {API_KEY[:10]}...", "DEBUG")
    log_message(f"SECRET_KEY: {SECRET_KEY[:10]}...", "DEBUG")

    url = f"https://aip.baidubce.com/oauth/2.0/token?grant_type=client_credentials&client_id={API_KEY}&client_secret={SECRET_KEY}"

    payload = ""
    headers = {
        'Content-Type': 'application/json',
        'Accept': 'application/json'
    }

    # 重试机制：最多3次
    max_retries = 3
    for attempt in range(max_retries):
        try:
            print(f"[TOKEN] 尝试 {attempt + 1}/{max_retries}", flush=True)
            if attempt > 0:
                wait_time = 2 ** attempt  # 指数退避：2秒、4秒、8秒
                log_message(f"Token请求重试 {attempt + 1}/{max_retries}，等待 {wait_time} 秒...", "INFO")
                print(f"[TOKEN] 等待 {wait_time} 秒后重试", flush=True)
                time.sleep(wait_time)
            
            log_message("发送Token请求...", "DEBUG")
            print(f"[TOKEN] 准备发送POST请求到百度API", flush=True)
            
            # 使用 Session 以支持连接池和重用
            session = requests.Session()
            # 配置 urllib3 重试策略
            from requests.adapters import HTTPAdapter
            from urllib3.util.retry import Retry
            
            retry_strategy = Retry(
                total=3,
                backoff_factor=1,
                status_forcelist=[429, 500, 502, 503, 504],
                allowed_methods=["POST"]
            )
            adapter = HTTPAdapter(max_retries=retry_strategy)
            session.mount("https://", adapter)
            session.mount("http://", adapter)
            
            print(f"[TOKEN] 开始POST请求（超时180秒）", flush=True)
            response = session.post(url, headers=headers, data=payload, timeout=180)
            print(f"[TOKEN] POST请求完成，状态码: {response.status_code}", flush=True)
            log_message(f"Token响应状态: {response.status_code}", "DEBUG")

            data = response.json()
            log_message(f"Token响应: {json.dumps(data, ensure_ascii=False)[:100]}...", "DEBUG")

            if 'access_token' in data:
                log_message("成功获取Access Token", "SUCCESS")
                return data['access_token']
            else:
                log_message(f"获取Token失败: {data}", "ERROR")
                if attempt < max_retries - 1:
                    continue
                raise Exception(f"获取token失败: {data}")
                
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
            log_message(f"Token请求网络错误 (attempt {attempt + 1}/{max_retries}): {str(e)}", "WARNING")
            if attempt == max_retries - 1:
                raise Exception(f"获取Token失败：网络超时或连接错误（已重试{max_retries}次）")
        except Exception as e:
            log_message(f"获取Token异常 (attempt {attempt + 1}/{max_retries}): {str(e)}", "ERROR")
            if attempt == max_retries - 1:
                raise
    
    raise Exception(f"获取Token失败：已重试{max_retries}次")

def translate_image_reference(image_path, source_lang='zh', target_lang='en', max_retries=3):
    """调用百度图片翻译API - Reference项目方式（带重试机制）"""
    log_message(f"调用translate_image_reference函数", "INFO")
    log_message(f"图片路径(原始): {image_path}", "DEBUG")

    # 确保使用绝对路径
    if not os.path.isabs(image_path):
        # 如果是相对路径，转换为绝对路径
        abs_path = os.path.join(app.root_path, image_path)
        if os.path.exists(abs_path):
            image_path = abs_path
            log_message(f"转换为绝对路径: {image_path}", "DEBUG")
        else:
            log_message(f"警告：文件不存在于绝对路径: {abs_path}", "WARNING")
            # 尝试直接使用相对路径
            if not os.path.exists(image_path):
                raise FileNotFoundError(f"找不到图片文件: {image_path} (也尝试了 {abs_path})")

    log_message(f"最终图片路径: {image_path}", "DEBUG")
    log_message(f"文件是否存在: {os.path.exists(image_path)}", "DEBUG")
    log_message(f"源语言: {source_lang}, 目标语言: {target_lang}", "DEBUG")

    # 禁用SSL警告
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    for attempt in range(max_retries):
        try:
            if attempt > 0:
                log_message(f"重试第 {attempt + 1}/{max_retries} 次...", "INFO")
                import time
                time.sleep(2 * attempt)  # 指数退避：2秒、4秒

            log_message("正在获取access token...", "DEBUG")
            access_token = get_access_token_reference()
            log_message(f"Access Token: {access_token[:20]}...", "DEBUG")

            url = f"https://aip.baidubce.com/file/2.0/mt/pictrans/v1?access_token={access_token}"
            log_message(f"API URL: {url[:50]}...", "DEBUG")

            # 检查文件大小和分辨率
            file_size = os.path.getsize(image_path)
            log_message(f"图片文件大小: {file_size / 1024 / 1024:.2f}MB", "DEBUG")

            if file_size > 4 * 1024 * 1024:
                raise Exception(f"图片文件过大: {file_size / 1024 / 1024:.2f}MB，超过4MB限制")

            # 检查图片尺寸
            try:
                from PIL import Image
                img = Image.open(image_path)
                log_message(f"图片尺寸: {img.width}x{img.height}px", "DEBUG")
                if max(img.width, img.height) > 4096:
                    log_message(f"警告：图片尺寸超过4096px，可能导致翻译失败", "WARNING")
            except:
                pass

            with open(image_path, 'rb') as f:
                files = {
                    'image': ('image.jpg', f, 'image/jpeg')
                }

                data = {
                    'from': source_lang,
                    'to': target_lang,
                    'paste': '1'
                }

                log_message(f"请求参数: {data}", "DEBUG")
                log_message("发送POST请求到百度API...", "DEBUG")
                print(f"[TRANSLATE] 发送翻译API请求", flush=True)

                response = requests.post(
                    url,
                    files=files,
                    data=data,
                    verify=False,
                    timeout=180  # 超时时间：180秒（3分钟）
                )
                print(f"[TRANSLATE] 翻译API请求完成", flush=True)
                log_message(f"响应状态码: {response.status_code}", "DEBUG")

                result = response.json()
                log_message(f"响应内容长度: {len(str(result))} 字符", "DEBUG")

                # 检查错误码（0表示成功）
                error_code = result.get('error_code')
                if error_code and error_code not in [0, '0']:
                    error_msg = result.get('error_msg', '未知错误')
                    log_message(f"API返回错误: {error_code} - {error_msg}", "ERROR")

                    # 某些错误不需要重试（如图片格式错误）
                    no_retry_codes = [69006, 216015, 216201]  # 图片错误、参数错误等
                    if error_code in no_retry_codes:
                        return result  # 直接返回，不重试

                    # 其他错误继续重试
                    if attempt < max_retries - 1:
                        continue
                elif error_code == 0 or error_code == '0':
                    log_message("百度API调用成功", "SUCCESS")

                return result

        except requests.exceptions.Timeout as e:
            log_message(f"API请求超时 (attempt {attempt + 1}/{max_retries}): {str(e)}", "WARNING")
            if attempt == max_retries - 1:
                raise Exception(f"API请求超时（已重试{max_retries}次）")
        except requests.exceptions.SSLError as e:
            log_message(f"SSL连接错误 (attempt {attempt + 1}/{max_retries}): {str(e)}", "WARNING")
            if attempt == max_retries - 1:
                raise Exception(f"SSL连接失败（已重试{max_retries}次），请检查网络连接")
        except Exception as e:
            log_message(f"translate_image_reference异常 (attempt {attempt + 1}/{max_retries}): {str(e)}", "ERROR")
            if attempt == max_retries - 1:
                raise

    raise Exception(f"翻译失败：已重试{max_retries}次")

# ========== 图片生成工具函数 ==========

def generate_image_from_regions(original_image_path, regions_data):
    """
    从原图和regions数据生成最终的带文字图片

    Args:
        original_image_path: 原始图片路径
        regions_data: regions JSON数据（字符串或列表）

    Returns:
        PIL Image对象
    """
    from PIL import Image, ImageDraw, ImageFont

    try:
        # 打开原图
        img = Image.open(original_image_path)
        if img.mode == 'RGBA':
            img = img.convert('RGB')

        # 创建绘图对象
        draw = ImageDraw.Draw(img)

        # 解析regions数据
        if isinstance(regions_data, str):
            regions = json.loads(regions_data)
        else:
            regions = regions_data

        if not regions:
            log_message("没有regions数据，返回原图", "WARN")
            return img

        log_message(f"开始渲染 {len(regions)} 个文本区域", "INFO")

        # 遍历每个region，先绘制遮罩，再绘制文字
        for idx, region in enumerate(regions):
            try:
                # 获取位置和大小
                x = region.get('x', 0)
                y = region.get('y', 0)
                width = region.get('width', 100)
                height = region.get('height', 30)

                # 绘制白色遮罩背景
                mask_bbox = [x, y, x + width, y + height]
                draw.rectangle(mask_bbox, fill=(255, 255, 255, 255))

                # 获取文本内容
                text = region.get('dst', region.get('src', ''))
                if not text:
                    continue

                # 获取字体参数
                font_size = int(region.get('fontSize', 16))
                font_family = region.get('fontFamily', 'Arial')
                text_color = region.get('fill', '#000000')

                # 转换颜色格式
                if text_color.startswith('#'):
                    text_color = text_color.lstrip('#')
                    if len(text_color) == 6:
                        r = int(text_color[0:2], 16)
                        g = int(text_color[2:4], 16)
                        b = int(text_color[4:6], 16)
                        text_color_rgb = (r, g, b)
                    else:
                        text_color_rgb = (0, 0, 0)
                else:
                    text_color_rgb = (0, 0, 0)

                # 加载字体
                try:
                    # 尝试加载系统字体
                    if os.name == 'nt':  # Windows
                        font_paths = [
                            'C:/Windows/Fonts/msyh.ttc',  # 微软雅黑
                            'C:/Windows/Fonts/simhei.ttf',  # 黑体
                            'C:/Windows/Fonts/simsun.ttc',  # 宋体
                        ]
                    else:  # Linux/Mac
                        font_paths = [
                            '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
                            '/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf',
                            '/System/Library/Fonts/PingFang.ttc',
                        ]

                    font = None
                    for font_path in font_paths:
                        if os.path.exists(font_path):
                            font = ImageFont.truetype(font_path, font_size)
                            break

                    if not font:
                        font = ImageFont.load_default()
                        log_message(f"未找到系统字体，使用默认字体", "WARN")

                except Exception as font_error:
                    log_message(f"加载字体失败: {font_error}，使用默认字体", "WARN")
                    font = ImageFont.load_default()

                # 绘制文本
                text_align = region.get('textAlign', 'center')

                # 简单的文本换行处理
                lines = []
                words = text
                current_line = ""

                for char in words:
                    test_line = current_line + char
                    bbox = draw.textbbox((0, 0), test_line, font=font)
                    text_width = bbox[2] - bbox[0]

                    if text_width <= width - 10:  # 留10px边距
                        current_line = test_line
                    else:
                        if current_line:
                            lines.append(current_line)
                        current_line = char

                if current_line:
                    lines.append(current_line)

                # 绘制每一行
                line_height = region.get('lineHeight', 1.2)
                actual_line_height = font_size * line_height

                for line_idx, line in enumerate(lines):
                    bbox = draw.textbbox((0, 0), line, font=font)
                    text_width = bbox[2] - bbox[0]

                    # 根据对齐方式计算x坐标
                    if text_align == 'center':
                        text_x = x + (width - text_width) / 2
                    elif text_align == 'right':
                        text_x = x + width - text_width - 5
                    else:  # left
                        text_x = x + 5

                    text_y = y + line_idx * actual_line_height + 5

                    draw.text((text_x, text_y), line, fill=text_color_rgb, font=font)

                log_message(f"✓ 区域 {idx} 渲染完成: {text[:20]}...", "DEBUG")

            except Exception as region_error:
                log_message(f"渲染区域 {idx} 失败: {region_error}", "ERROR")
                continue

        log_message("图片生成完成", "SUCCESS")
        return img

    except Exception as e:
        log_message(f"生成图片失败: {str(e)}", "ERROR")
        import traceback
        log_message(traceback.format_exc(), "ERROR")
        raise

# ========== 数据库模型 ========== 

class User(db.Model):
    __tablename__ = 'users'
    __table_args__ = {'extend_existing': True}
    
    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    phone = db.Column(db.String(50))
    law_firm_id = db.Column(db.String(36))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    clients = db.relationship('Client', backref='user', lazy=True, cascade='all, delete-orphan')
    
    def set_password(self, password):
        self.password_hash = generate_password_hash(password)
    
    def check_password(self, password):
        return check_password_hash(self.password_hash, password)
    
    def to_dict(self):
        return {
            'uid': self.id,
            'name': self.name,
            'email': self.email,
            'created_at': self.created_at.isoformat(),
            'updated_at': self.updated_at.isoformat()
        }

class Client(db.Model):
    __tablename__ = 'clients'
    __table_args__ = {'extend_existing': True}
    
    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name = db.Column(db.String(100), nullable=False)
    case_type = db.Column(db.String(100))
    case_date = db.Column(db.String(20))
    user_id = db.Column(db.String(36), db.ForeignKey('users.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # 联系信息字段
    phone = db.Column(db.String(50))
    email = db.Column(db.String(100))
    address = db.Column(db.Text)
    notes = db.Column(db.Text)
    
    # 归档字段
    is_archived = db.Column(db.Boolean, default=False)
    archived_at = db.Column(db.DateTime)
    archived_reason = db.Column(db.String(500))
    
    materials = db.relationship('Material', backref='client', lazy=True, cascade='all, delete-orphan')
    
    def to_dict(self):
        return {
            'cid': self.id,
            'name': self.name,
            'caseType': self.case_type,
            'caseDate': self.case_date,
            'phone': self.phone,
            'email': self.email,
            'address': self.address,
            'notes': self.notes,
            'isArchived': bool(self.is_archived) if self.is_archived is not None else False,
            'archivedAt': self.archived_at.isoformat() if self.archived_at else None,
            'archivedReason': self.archived_reason,
            'createdAt': self.created_at.isoformat() if hasattr(self.created_at, 'isoformat') else str(self.created_at),
            'updatedAt': self.updated_at.isoformat() if hasattr(self.updated_at, 'isoformat') else str(self.updated_at)
        }

class Material(db.Model):
    __tablename__ = 'materials'
    __table_args__ = {'extend_existing': True}
    
    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name = db.Column(db.String(255), nullable=False)
    type = db.Column(db.String(50), nullable=False)
    status = db.Column(db.String(50), default='待处理')
    confirmed = db.Column(db.Boolean, default=False)
    selected_result = db.Column(db.String(20), default='api')  # 默认使用百度API翻译结果
    original_filename = db.Column(db.String(255))
    file_path = db.Column(db.String(500))
    url = db.Column(db.String(1000))
    # 翻译结果字段
    translated_image_path = db.Column(db.String(500))  # 翻译后的图片路径
    original_pdf_path = db.Column(db.String(500))  # 原始网页PDF路径（网页材料专用）
    translation_text_info = db.Column(db.Text)  # JSON格式的文本信息
    translation_error = db.Column(db.Text)  # API翻译错误信息
    latex_translation_result = db.Column(db.Text)  # LaTeX翻译结果
    latex_translation_error = db.Column(db.Text)  # LaTeX翻译错误信息
    llm_translation_result = db.Column(db.Text)  # LLM翻译结果（JSON格式）
    edited_image_path = db.Column(db.String(500))  # 编辑后的图片路径（不带文字版本，用于预览）
    final_image_path = db.Column(db.String(500))  # 最终图片路径（带文字完整版本，用于导出）
    has_edited_version = db.Column(db.Boolean, default=False)  # 是否有编辑版本
    edited_regions = db.Column(db.Text)  # 编辑的regions状态（JSON格式）
    # PDF多页相关字段
    pdf_session_id = db.Column(db.String(100))  # PDF会话ID（多页PDF共享）
    pdf_page_number = db.Column(db.Integer)  # PDF页码
    pdf_total_pages = db.Column(db.Integer)  # PDF总页数
    pdf_original_file = db.Column(db.String(500))  # PDF原始文件路径
    # 实体识别相关字段
    entity_recognition_enabled = db.Column(db.Boolean, default=False)  # 是否启用实体识别
    entity_recognition_mode = db.Column(db.String(20))  # 实体识别模式：'standard' 或 'deep'
    entity_recognition_result = db.Column(db.Text)  # 实体识别结果（JSON格式）
    entity_recognition_confirmed = db.Column(db.Boolean, default=False)  # 实体识别是否已确认
    entity_recognition_triggered = db.Column(db.Boolean, default=False)  # 是否已触发实体识别（防重复）
    entity_user_edits = db.Column(db.Text)  # 用户编辑后的实体信息（JSON格式，用于指导LLM翻译）
    entity_recognition_error = db.Column(db.Text)  # 实体识别错误信息
    # 处理步骤进度: uploaded, translating, llm_optimizing, completed, failed
    processing_step = db.Column(db.String(50), default='uploaded')
    processing_progress = db.Column(db.Integer, default=0)  # 0-100的进度百分比
    # 乐观锁版本号
    version = db.Column(db.Integer, default=0, nullable=False)
    client_id = db.Column(db.String(36), db.ForeignKey('clients.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    def to_dict(self):
        # 解析翻译文本信息
        text_info = None
        if self.translation_text_info:
            try:
                text_info = json.loads(self.translation_text_info)
            except:
                text_info = None

        # 解析LLM翻译结果
        llm_translation = None
        if self.llm_translation_result:
            try:
                llm_translation = json.loads(self.llm_translation_result)
            except:
                llm_translation = None

        # 解析实体识别结果
        entity_recognition = None
        if self.entity_recognition_result:
            try:
                entity_recognition = json.loads(self.entity_recognition_result)
            except:
                entity_recognition = None

        # 解析用户编辑的实体信息
        entity_edits = None
        if self.entity_user_edits:
            try:
                entity_edits = json.loads(self.entity_user_edits)
            except:
                entity_edits = None

        return {
            'id': self.id,
            'name': self.name,
            'type': self.type,
            'status': self.status,
            'confirmed': self.confirmed,
            'selectedResult': self.selected_result,
            'originalFilename': self.original_filename,
            'filePath': self.file_path,  # 原始文件路径（用于显示原图）
            'url': self.url,
            'clientId': self.client_id,
            'createdAt': self.created_at.isoformat(),
            'updatedAt': self.updated_at.isoformat(),
            # 翻译结果
            'translatedImagePath': self.translated_image_path,
            'originalPdfPath': self.original_pdf_path,  # 原始网页PDF路径
            'translationTextInfo': text_info,
            'translationError': self.translation_error,
            'latexTranslationResult': self.latex_translation_result,
            'latexTranslationError': self.latex_translation_error,
            'llmTranslationResult': llm_translation,  # LLM翻译结果
            'editedImagePath': self.edited_image_path,  # 编辑后的图片路径
            'finalImagePath': self.final_image_path,  # 最终图片路径（带文字完整版）
            'hasEditedVersion': self.has_edited_version,  # 是否有编辑版本
            'editedRegions': json.loads(self.edited_regions) if self.edited_regions else None,  # 编辑的regions
            # PDF多页相关
            'pdfSessionId': self.pdf_session_id,
            'pdfPageNumber': self.pdf_page_number,
            'pdfTotalPages': self.pdf_total_pages,
            'pdfOriginalFile': self.pdf_original_file,
            # 实体识别相关
            'entityRecognitionEnabled': self.entity_recognition_enabled,
            'entityRecognitionMode': self.entity_recognition_mode,  # ✅ 添加mode字段
            'entityRecognitionResult': entity_recognition,
            'entityRecognitionConfirmed': self.entity_recognition_confirmed,
            'entityRecognitionTriggered': self.entity_recognition_triggered,  # ✅ 添加triggered字段
            'entityUserEdits': entity_edits,
            'entityRecognitionError': self.entity_recognition_error,
            # 处理进度
            'processingStep': self.processing_step,
            'processingProgress': self.processing_progress
        }

class PosterTranslator:
    """海报翻译类，处理从图像到PDF的完整流程（增强版）"""
    
    def __init__(self, api_key=None, pdflatex_path=None):
        """
        初始化海报翻译器
        
        Args:
            api_key (str): OpenAI API密钥
            pdflatex_path (str): pdflatex.exe的路径，如果为None则使用默认路径
        """
        # 配置API密钥
        self.api_key = api_key or self._load_api_key()
        if self.api_key and OPENAI_AVAILABLE:
            self.client = OpenAI(api_key=self.api_key)
            self.log("OpenAI API密钥已配置", "SUCCESS")
        else:
            self.client = None
            if not OPENAI_AVAILABLE:
                self.log("[WARNING] OpenAI库未安装", "WARNING")
            else:
                self.log("[WARNING] OpenAI API密钥未设置", "WARNING")
        
        # 智能检测pdflatex路径
        self.pdflatex_path = self._detect_pdflatex_path(pdflatex_path)
        
        # 定义海报转LaTeX的详细提示词（增强版）
        self.custom_prompt = r"""
IMPORTANT: Generate ONLY pure LaTeX code. Do not include any explanatory text, markdown formatting, or instructions. The output must start with \documentclass and end with \end{document}.

Upload a source image (e.g., a poster, flyer, single-page document, etc.) and generate "directly compilable LaTeX code" that faithfully reproduces the layout of the source. The requirements are as follows:

1. Mandatory LaTeX Preamble (Crucial for Compatibility)
The generated code MUST use the following preamble exactly as provided. Do not add, remove, or alter packages in this section. The entire document structure must be built upon this foundation.

Code snippet

\documentclass[a4paper]{article}
\usepackage[utf8]{inputenc}
\usepackage[T1]{fontenc}
\usepackage{lmodern}
\usepackage[margin=2cm]{geometry}
\usepackage{tabularx}
\usepackage{array}
\usepackage{graphicx}
2. Primary Goal: Faithful and Complete Reproduction

Layout Fidelity: Your highest priority is to meticulously replicate the geometric layout, alignment, and relative spacing of the original source image. The output must be a structural mirror of the original.

Content Completeness (No Omissions): It is mandatory to transcribe all textual information from the source image without any omissions. This includes titles, body text, tables, speaker information, footnotes, and any fine print. Pay special attention to names of people and organizations (especially Chinese names), which must be accurately transcribed first and then appropriately translated or transliterated. No content should be summarized or left out, regardless of its perceived importance.
3. Page Boundary and Margin Control (Critical)
It is absolutely essential that all content remains strictly within the page boundaries defined by the preamble's geometry package. No text, tables, or placeholders should overflow the page. Use width-aware environments like tabularx, \parbox, or minipage to control element widths.

4. Text and Typography

Translation: The source document is written in Chinese. All textual content must be translated from Chinese to English.

Text Normalization and Sanitization (Critical): Before outputting any text, ensure all characters are normalized for maximum pdflatex compatibility.

Punctuation: All punctuation marks MUST be converted from full-width forms to their standard half-width ASCII equivalents (e.g., （ to (, ： to :, ， to ,).

Currency Symbols: Non-ASCII currency symbols must be translated to their English text equivalents. For example, a price like ￥100 should be translated to 100 Yuan or RMB 100. The symbol ￥ itself should not appear in the final code.

Hierarchy: Use \large or \Large for titles.

Emphasis: Bold key information as needed.

5. Conditional Placeholder Generation

Strict Condition: Only generate placeholders for photos or QR codes if they are explicitly present in the source image.

Representation: Use \fbox or \framebox to draw placeholders. For example: \fbox{\parbox[c][1.5cm][c]{2.5cm}{\centering Photo}}.

6. Strict Technical Constraints

100% Self-Contained Code: The \includegraphics command is strictly forbidden.

Special Character Escaping: Properly escape all special LaTeX characters (& must be \&, etc.).

Style Restrictions: No color commands. No font sizes larger than \Large.

Package Restrictions: DO NOT use any of the following packages which are incompatible with pdflatex: fontspec, xeCJK, ctex, polyglossia, luatex85. DO NOT use system fonts or \setmainfont commands.

Engine Compatibility: The code MUST be compilable with pdflatex ONLY. Do not use features that require xelatex or lualatex.

7. Final Output Format

Raw Code Only: The output must be raw LaTeX code, starting with \documentclass and ending with \end{document}. Do not enclose it in any markdown formatting. Do not include any text before \documentclass or after \end{document}.

8. Error Prevention

Ensure all environments are properly closed (every \begin{X} has a matching \end{X}).

Avoid empty commands like \text{} or \textbf{}.

Ensure the document has proper structure: \documentclass, necessary packages, \begin{document}, content, \end{document}.

9. Final Verification Step (Mandatory)
Before providing the final output, perform one last check. Verify that the generated code begins exactly with the mandatory preamble provided in step 1, from \documentclass{article} down to \usepackage{graphicx}. There must be no extra characters, words, or commands inserted within or immediately after the \documentclass or \usepackage lines. If any deviation is found, you must correct it before outputting the final code.

"""

    def _detect_pdflatex_path(self, custom_path=None):
        """智能检测pdflatex路径"""
        self.log("正在检测pdflatex路径...", "DEBUG")
        
        # 如果提供了自定义路径，先尝试
        if custom_path and os.path.exists(custom_path):
            self.log(f"使用自定义pdflatex路径: {custom_path}", "SUCCESS")
            return custom_path
        
        # 常见的MiKTeX安装路径（Windows）
        common_paths = [
            r"F:\\tex\\miktex\\bin\\x64\\pdflatex.exe",  # 原始路径
            r"C:\\Program Files\\MiKTeX\\miktex\\bin\\x64\\pdflatex.exe",
            r"C:\\Users\\{}\\AppData\\Local\\Programs\\MiKTeX\\miktex\\bin\\x64\\pdflatex.exe".format(os.getenv('USERNAME', '')),
            r"C:\\Program Files (x86)\\MiKTeX\\miktex\\bin\\pdflatex.exe",
            r"D:\\MiKTeX\\miktex\\bin\\x64\\pdflatex.exe",
            r"E:\\MiKTeX\\miktex\\bin\\x64\\pdflatex.exe"
        ]
        
        # 检查常见路径
        for path in common_paths:
            if os.path.exists(path):
                self.log(f"找到pdflatex: {path}", "SUCCESS")
                return path
        
        # 检查系统PATH
        try:
            result = subprocess.run(["pdflatex", "--version"], 
                                 check=True, capture_output=True, text=True, timeout=10)
            self.log("在系统PATH中找到pdflatex", "SUCCESS")
            return "pdflatex"
        except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
            pass
        
        # 如果都找不到，返回默认路径并记录警告
        default_path = r"F:\\tex\\miktex\\bin\\x64\\pdflatex.exe"
        self.log(f"未找到pdflatex，使用默认路径: {default_path}", "WARNING")
        return default_path

    def log(self, message, level="INFO"):
        """详细状态日志"""
        timestamp = datetime.now().strftime("%H:%M:%S")
        prefix = {
            "INFO": "[INFO]",
            "SUCCESS": "[SUCCESS]", 
            "WARNING": "[WARNING]",
            "ERROR": "[ERROR]",
            "DEBUG": "[DEBUG]"
        }
        print(f"[{timestamp}] {prefix.get(level, '[INFO]')} {message}")

    def _remove_chinese_content(self, latex_code):
        """
        从LaTeX代码中剔除所有中文内容
        
        Args:
            latex_code (str): 原始LaTeX代码
            
        Returns:
            str: 剔除中文后的LaTeX代码
        """
        import re
        
        # 定义中文字符的正则表达式
        chinese_pattern = r'[\u4e00-\u9fff]+'
        
        # 记录剔除的中文内容
        chinese_matches = re.findall(chinese_pattern, latex_code)
        if chinese_matches:
            self.log(f"发现中文内容: {chinese_matches}", "DEBUG")
        
        # 剔除中文内容，但保留LaTeX命令结构
        def replace_chinese(match):
            chinese_text = match.group(0)
            # 如果中文在LaTeX命令中（如\text{中文}），替换为空字符串
            return ""
        
        # 替换所有中文内容
        cleaned_code = re.sub(chinese_pattern, replace_chinese, latex_code)
        
        # 清理可能产生的多余空格和空行
        # 移除连续的空行
        cleaned_code = re.sub(r'\n\s*\n\s*\n', '\n\n', cleaned_code)
        
        # 移除行首行尾的多余空格
        lines = cleaned_code.split('\n')
        cleaned_lines = [line.rstrip() for line in lines]
        cleaned_code = '\n'.join(cleaned_lines)
        
        # 移除可能产生的空命令（如\text{}）
        cleaned_code = re.sub(r'\\\\text\{\s*\}', '', cleaned_code)
        cleaned_code = re.sub(r'\\\\textbf\{\s*\}', '', cleaned_code)
        cleaned_code = re.sub(r'\\\\textit\{\s*\}', '', cleaned_code)
        cleaned_code = re.sub(r'\\\\emph\{\s*\}', '', cleaned_code)
        
        # 移除可能产生的空表格单元格
        cleaned_code = re.sub(r'&\s*&', '& &', cleaned_code)  # 修复空单元格
        cleaned_code = re.sub(r'&\s*\\\\\\\\', '& \\\\\\\\', cleaned_code)  # 修复行尾空单元格
        
        # 移除可能产生的空段落
        cleaned_code = re.sub(r'\\\\par\s*\\\\par', '\\\\par', cleaned_code)
        
        if chinese_matches:
            self.log(f"已剔除 {len(chinese_matches)} 处中文内容", "SUCCESS")
        
        return cleaned_code

    def _enhance_latex_code(self, latex_code):
        """
        应用增强的LaTeX代码修复和过滤
        
        Args:
            latex_code (str): 原始LaTeX代码
            
        Returns:
            str: 修复后的LaTeX代码
        """
        # 1. 修复常见的文档类声明问题
        latex_code = self._fix_documentclass_issues(latex_code)
        
        # 2. 移除与pdflatex不兼容的包
        latex_code = self._remove_incompatible_packages(latex_code)
        
        # 3. 修复常见的LaTeX语法错误
        latex_code = self._fix_common_latex_errors(latex_code)
        
        # 4. 验证LaTeX文档结构
        latex_code = self._validate_and_fix_structure(latex_code)
        
        return latex_code
    
    def _fix_documentclass_issues(self, latex_code):
        """修复文档类声明问题"""
        # 修复错误的documentclass声明
        latex_code = re.sub(r'\\documentclass`\s*with.*?$', r'\\documentclass[12pt]{article}', latex_code, flags=re.MULTILINE)
        latex_code = re.sub(r'\\documentclass\\{', r'\\documentclass{', latex_code)
        
        # 如果没有documentclass，添加默认的
        if not re.search(r'\\documentclass', latex_code):
            self.log("未找到documentclass，添加默认文档类", "WARNING")
            latex_code = r"\documentclass[12pt]{article}\n" + latex_code
        
        return latex_code
    
    def _remove_incompatible_packages(self, latex_code):
        """移除与pdflatex不兼容的包"""
        # 与pdflatex不兼容的包列表
        incompatible_packages = ['fontspec', 'xeCJK', 'ctex', 'luatex85', 'polyglossia']
        
        for pkg in incompatible_packages:
            # 移除usepackage命令
            latex_code = re.sub(rf'\\usepackage(?:\[.*?\])?{{\s*{pkg}\s*}}.*?\n', '', latex_code)
            # 移除相关设置命令
            if pkg == 'fontspec':
                latex_code = re.sub(r'\\setmainfont\{.*?\}.*?\n', '', latex_code)
                latex_code = re.sub(r'\\setsansfont\{.*?\}.*?\n', '', latex_code)
                latex_code = re.sub(r'\\setmonofont\{.*?\}.*?\n', '', latex_code)
        
        # 确保有基本的utf8编码支持
        if 'inputenc' not in latex_code:
            # 在\documentclass后添加
            latex_code = re.sub(r'(\\documentclass.*?\n)', r'\1\\usepackage[utf8]{inputenc}\n', latex_code)
        
        return latex_code
    
    def _fix_common_latex_errors(self, latex_code):
        """修复常见的LaTeX语法错误"""
        # 修复未闭合的环境
        environments = re.findall(r'\\begin\{(\w+)\}', latex_code)
        for env in environments:
            # 检查是否有对应的\end
            if not re.search(rf'\\end\{{{env}\}}', latex_code):
                self.log(f"发现未闭合的环境: {env}", "WARNING")
                # 在文档末尾之前添加\end
                latex_code = re.sub(r'(\\end\{document\})', rf'\\end{{{env}}}\n\1', latex_code)
        
        # 修复数学模式中的非法字符
        # 在$...$中的_和^需要转义
        def fix_math_mode(match):
            content = match.group(1)
            # 如果是在数学命令中，不需要转义
            if '_' in content or '^' in content:
                # 检查是否已经在数学命令中
                if not re.search(r'\\[a-zA-Z]+', content):
                    content = content.replace('_', '\\_').replace('^', '\\^')
            return f'${content}$'
        
        # 不修改数学模式中的内容，因为_和^在数学模式中是合法的
        # latex_code = re.sub(r'\$([^$]+)\$', fix_math_mode, latex_code)
        
        # 修复连续的\\命令
        latex_code = re.sub(r'\\\\\s*\\\\', r'\\\\', latex_code)
        
        # 移除空的段落
        latex_code = re.sub(r'\n\s*\n\s*\n', '\n\n', latex_code)
        
        return latex_code
    
    def _validate_and_fix_structure(self, latex_code):
        """验证并修复LaTeX文档结构"""
        # 检查\begin{document}
        if not re.search(r'\\begin\{document\}', latex_code):
            self.log("缺少\\begin{document}，正在添加...", "WARNING")
            # 在\documentclass和\usepackage之后添加
            lines = latex_code.split('\n')
            insert_pos = 0
            for i, line in enumerate(lines):
                if re.search(r'\\documentclass|\\usepackage', line):
                    insert_pos = i + 1
            lines.insert(insert_pos, '\n\\begin{document}')
            latex_code = '\n'.join(lines)
        
        # 检查\end{document}
        if not re.search(r'\\end\{document\}', latex_code):
            self.log("缺少\\end{document}，正在添加...", "WARNING")
            latex_code += '\n\\end{document}'
        
        # 确保\end{document}是最后一个命令
        end_doc_match = re.search(r'\\end\{document\}', latex_code)
        if end_doc_match:
            end_pos = end_doc_match.end()
            # 移除\end{document}后的所有内容（除了空白）
            after_content = latex_code[end_pos:].strip()
            if after_content:
                self.log(f"发现\\end{{document}}后有额外内容: {after_content[:50]}...", "WARNING")
                latex_code = latex_code[:end_pos]
        
        return latex_code
    
    def _get_fallback_latex_template(self):
        """获取备用LaTeX模板"""
        return r"""
\documentclass[12pt]{article}
\usepackage[utf8]{inputenc}
\usepackage{geometry}
\geometry{a4paper, margin=1in}
\usepackage{graphicx}
\usepackage{amsmath}
\usepackage{hyperref}

\begin{document}

\section*{Translation Notice}

The automatic LaTeX generation failed for this document. 

This is a placeholder document. Please try the following:

\begin{itemize}
\item Ensure the input image is clear and readable
\item Try with a simpler layout
\item Check the LaTeX compilation logs for specific errors
\end{itemize}

\end{document}
"""

    def _load_api_key(self):
        """从环境变量或配置文件加载API密钥"""
        self.log("正在查找OpenAI API密钥...", "DEBUG")
        
        # 尝试从环境变量获取
        api_key = os.getenv('OPENAI_API_KEY')
        if api_key:
            self.log("从环境变量获取API密钥", "DEBUG")
            return api_key
        
        # 尝试从配置文件获取
        # config_files = ['api_key.txt', 'openai_key.txt', 'config.json']
        config_files = ['config/openai_api_key.txt', 'api_key.txt', 'openai_key.txt', 'config.json']
        for config_file in config_files:
            if os.path.exists(config_file):
                try:
                    self.log(f"尝试从 {config_file} 读取API密钥", "DEBUG")
                    with open(config_file, 'r', encoding='utf-8') as f:
                        content = f.read().strip()
                        if config_file.endswith('.json'):
                            data = json.loads(content)
                            return data.get('openai_api_key') or data.get('api_key')
                        else:
                            return content
                except Exception as e:
                    self.log(f"读取配置文件 {config_file} 失败: {e}", "WARNING")
        
        self.log("未找到API密钥配置", "WARNING")
        return None

    def check_requirements(self):
        """详细检查运行环境和要求"""
        self.log("🔍 开始详细环境检查...", "INFO")
        
        check_results = {
            "api_key": {"status": False, "details": [], "solutions": []},
            "pdflatex": {"status": False, "details": [], "solutions": []},
            "python_modules": {"status": False, "details": [], "solutions": []},
            "file_permissions": {"status": False, "details": [], "solutions": []}
        }
        
        # 1. 详细检查API密钥
        self.log("步骤1: 检查OpenAI API密钥配置", "DEBUG")
        api_check = self._check_api_key_detailed()
        check_results["api_key"] = api_check
        
        # 2. 详细检查pdflatex
        self.log("步骤2: 检查LaTeX环境", "DEBUG")
        latex_check = self._check_pdflatex_detailed()
        check_results["pdflatex"] = latex_check
        
        # 3. 检查Python模块
        self.log("步骤3: 检查Python模块依赖", "DEBUG")
        modules_check = self._check_python_modules()
        check_results["python_modules"] = modules_check
        
        # 4. 检查文件权限
        self.log("步骤4: 检查文件系统权限", "DEBUG")
        permissions_check = self._check_file_permissions()
        check_results["file_permissions"] = permissions_check
        
        # 汇总检查结果
        all_passed = all(result["status"] for result in check_results.values())
        
        if all_passed:
            self.log("🎉 所有环境检查通过!", "SUCCESS")
            return True
        else:
            self._generate_detailed_error_report(check_results)
            return False

    def _check_api_key_detailed(self):
        """详细检查API密钥配置"""
        result = {"status": False, "details": [], "solutions": []}
        
        # 检查环境变量
        env_key = os.getenv('OPENAI_API_KEY')
        if env_key:
            result["details"].append("✅ 环境变量 OPENAI_API_KEY 存在")
            if len(env_key.strip()) > 0:
                result["details"].append(f"✅ 密钥长度: {len(env_key)} 字符")
                if env_key.startswith('sk-'):
                    result["details"].append("✅ 密钥格式正确 (以sk-开头)")
                    result["status"] = True
                else:
                    result["details"].append("⚠️ 密钥格式可能有误 (不以sk-开头)")
                    result["solutions"].append("检查密钥是否为有效的OpenAI API密钥")
            else:
                result["details"].append("❌ 环境变量为空")
                result["solutions"].append("设置有效的OPENAI_API_KEY环境变量")
        else:
            result["details"].append("❌ 环境变量 OPENAI_API_KEY 未设置")
        
        # 检查配置文件
        config_files = [
            'config/openai_api_key.txt',
            'api_key.txt', 
            'openai_key.txt', 
            'config.json'
        ]
        
        found_config = False
        for config_file in config_files:
            if os.path.exists(config_file):
                found_config = True
                result["details"].append(f"✅ 找到配置文件: {config_file}")
                try:
                    with open(config_file, 'r', encoding='utf-8') as f:
                        content = f.read().strip()
                        if config_file.endswith('.json'):
                            data = json.loads(content)
                            key = data.get('openai_api_key') or data.get('api_key')
                            if key:
                                result["details"].append("✅ JSON配置文件包含API密钥")
                                if not result["status"] and key.startswith('sk-'):
                                    result["status"] = True
                            else:
                                result["details"].append("❌ JSON配置文件缺少API密钥字段")
                        else:
                            if content and content.startswith('sk-'):
                                result["details"].append("✅ 配置文件包含有效格式的API密钥")
                                if not result["status"]:
                                    result["status"] = True
                            else:
                                result["details"].append("❌ 配置文件密钥格式无效")
                except Exception as e:
                    result["details"].append(f"❌ 读取配置文件失败: {e}")
                    result["solutions"].append(f"检查文件 {config_file} 的权限和格式")
                break
        
        if not found_config and not env_key:
            result["details"].append("❌ 未找到任何API密钥配置")
            result["solutions"].extend([
                "方案1: 设置环境变量 OPENAI_API_KEY",
                "方案2: 创建 config/openai_api_key.txt 文件并写入密钥",
                "方案3: 创建 api_key.txt 文件并写入密钥",
                "请访问 https://platform.openai.com/account/api-keys 获取API密钥"
            ])
        
        return result

    def _check_pdflatex_detailed(self):
        """详细检查pdflatex环境"""
        result = {"status": False, "details": [], "solutions": []}
        
        # 检查配置的路径
        if self.pdflatex_path != "pdflatex":
            result["details"].append(f"🔍 检查配置路径: {self.pdflatex_path}")
            if os.path.exists(self.pdflatex_path):
                result["details"].append("✅ 配置路径存在")
                # 检查文件权限
                if os.access(self.pdflatex_path, os.X_OK):
                    result["details"].append("✅ 文件具有执行权限")
                    try:
                        # 测试执行
                        proc = subprocess.run([self.pdflatex_path, "--version"], 
                                            capture_output=True, text=True, timeout=10)
                        if proc.returncode == 0:
                            version_info = proc.stdout.split('\n')[0] if proc.stdout else "未知版本"
                            result["details"].append(f"✅ pdflatex版本: {version_info}")
                            result["status"] = True
                        else:
                            result["details"].append(f"❌ pdflatex执行失败: {proc.stderr}")
                            result["solutions"].append("检查pdflatex安装是否完整")
                    except subprocess.TimeoutExpired:
                        result["details"].append("❌ pdflatex执行超时")
                        result["solutions"].append("检查pdflatex是否响应")
                    except Exception as e:
                        result["details"].append(f"❌ pdflatex执行异常: {e}")
                else:
                    result["details"].append("❌ 文件没有执行权限")
                    result["solutions"].append(f"授予执行权限: chmod +x {self.pdflatex_path}")
            else:
                result["details"].append("❌ 配置路径不存在")
                result["solutions"].append("检查路径是否正确或重新安装LaTeX")
        
        # 检查系统PATH
        result["details"].append("🔍 检查系统PATH中的pdflatex")
        try:
            proc = subprocess.run(["pdflatex", "--version"], 
                                capture_output=True, text=True, timeout=10)
            if proc.returncode == 0:
                result["details"].append("✅ 系统PATH中找到pdflatex")
                version_info = proc.stdout.split('\n')[0] if proc.stdout else "未知版本"
                result["details"].append(f"✅ 系统pdflatex版本: {version_info}")
                if not result["status"]:
                    result["status"] = True
            else:
                result["details"].append("❌ 系统PATH中pdflatex执行失败")
        except subprocess.TimeoutExpired:
            result["details"].append("❌ 系统pdflatex执行超时")
        except FileNotFoundError:
            result["details"].append("❌ 系统PATH中未找到pdflatex")
        except Exception as e:
            result["details"].append(f"❌ 系统pdflatex检查异常: {e}")
        
        # 检查常见的LaTeX发行版
        common_latex_paths = [
            "C:\\Program Files\\MiKTeX\\miktex\\bin\\x64\\pdflatex.exe",
            "C:\\Users\\{username}\\AppData\\Local\\Programs\\MiKTeX\\miktex\\bin\\x64\\pdflatex.exe",
            "/usr/bin/pdflatex",
            "/usr/local/bin/pdflatex",
            "/Library/TeX/texbin/pdflatex"
        ]
        
        username = os.getenv('USERNAME', os.getenv('USER', ''))
        result["details"].append("🔍 检查常见LaTeX安装位置")
        found_latex = False
        
        for path_template in common_latex_paths:
            path = path_template.replace('{username}', username)
            if os.path.exists(path):
                result["details"].append(f"✅ 找到LaTeX安装: {path}")
                found_latex = True
                if not result["status"]:
                    # 更新配置建议
                    result["solutions"].append(f"可以手动设置路径: {path}")
                break
        
        if not found_latex:
            result["details"].append("❌ 未找到常见的LaTeX安装")
        
        # 添加安装建议
        if not result["status"]:
            result["solutions"].extend([
                "安装建议:",
                "Windows: 下载并安装 MiKTeX (https://miktex.org/download)",
                "macOS: 安装 MacTeX (https://www.tug.org/mactex/)",
                "Linux: sudo apt-get install texlive-latex-base",
                "安装后重启命令行或IDE",
                "确保LaTeX程序添加到系统PATH"
            ])
        
        return result

    def _check_python_modules(self):
        """检查Python模块依赖"""
        result = {"status": True, "details": [], "solutions": []}
        
        required_modules = [
            ('openai', 'OpenAI API客户端'),
            ('PIL', 'Python图像处理库'),
            ('pathlib', 'Python路径处理'),
            ('base64', 'Base64编码'),
            ('json', 'JSON处理'),
            ('subprocess', '子进程管理'),
            ('os', '操作系统接口')
        ]
        
        missing_modules = []
        for module_name, description in required_modules:
            try:
                __import__(module_name)
                result["details"].append(f"✅ {module_name}: {description}")
            except ImportError:
                result["details"].append(f"❌ {module_name}: {description} - 缺失")
                missing_modules.append(module_name)
        
        if missing_modules:
            result["status"] = False
            result["solutions"].append(f"安装缺失的模块: pip install {' '.join(missing_modules)}")
        
        return result

    def _check_file_permissions(self):
        """检查文件系统权限"""
        result = {"status": True, "details": [], "solutions": []}
        
        # 检查输出目录权限
        output_dirs = ['poster_output', 'uploads', 'downloads']
        
        for dir_name in output_dirs:
            try:
                os.makedirs(dir_name, exist_ok=True)
                # 测试写入权限
                test_file = os.path.join(dir_name, 'test_permission.tmp')
                with open(test_file, 'w') as f:
                    f.write('test')
                os.remove(test_file)
                result["details"].append(f"✅ {dir_name}: 读写权限正常")
            except PermissionError:
                result["details"].append(f"❌ {dir_name}: 权限不足")
                result["status"] = False
                result["solutions"].append(f"授予目录写入权限: {dir_name}")
            except Exception as e:
                result["details"].append(f"❌ {dir_name}: 检查失败 - {e}")
                result["status"] = False
        
        return result

    def _generate_detailed_error_report(self, check_results):
        """生成详细的错误报告"""
        self.log("=" * 60, "ERROR")
        self.log("🚨 环境检查失败 - 详细报告", "ERROR")
        self.log("=" * 60, "ERROR")
        
        for category, result in check_results.items():
            status_icon = "✅" if result["status"] else "❌"
            category_name = {
                "api_key": "OpenAI API密钥",
                "pdflatex": "LaTeX环境",
                "python_modules": "Python模块",
                "file_permissions": "文件权限"
            }.get(category, category)
            
            self.log(f"\n{status_icon} {category_name}:", "ERROR" if not result["status"] else "SUCCESS")
            
            for detail in result["details"]:
                print(f"   {detail}")
            
            if result["solutions"] and not result["status"]:
                self.log("   💡 解决方案:", "WARNING")
                for i, solution in enumerate(result["solutions"], 1):
                    print(f"      {i}. {solution}")
        
        self.log("\n" + "=" * 60, "ERROR")
        self.log("请解决上述问题后重试", "ERROR")
        self.log("=" * 60, "ERROR")

    def check_requirements_with_details(self):
        """检查环境并返回详细结果（用于API响应）"""
        self.log("🔍 开始详细环境检查...", "INFO")
        
        check_results = {
            "api_key": {"status": False, "details": [], "solutions": []},
            "pdflatex": {"status": False, "details": [], "solutions": []},
            "python_modules": {"status": False, "details": [], "solutions": []},
            "file_permissions": {"status": False, "details": [], "solutions": []}
        }
        
        # 执行各项检查
        check_results["api_key"] = self._check_api_key_detailed()
        check_results["pdflatex"] = self._check_pdflatex_detailed()
        check_results["python_modules"] = self._check_python_modules()
        check_results["file_permissions"] = self._check_file_permissions()
        
        # 汇总结果
        all_passed = all(result["status"] for result in check_results.values())
        
        if all_passed:
            self.log("🎉 所有环境检查通过!", "SUCCESS")
            return {
                'success': True,
                'message': '环境检查通过'
            }
        else:
            # 生成详细报告
            self._generate_detailed_error_report(check_results)
            
            # 准备API响应数据
            error_summary = []
            all_details = {}
            all_solutions = []
            
            for category, result in check_results.items():
                category_name = {
                    "api_key": "OpenAI API密钥",
                    "pdflatex": "LaTeX环境", 
                    "python_modules": "Python模块",
                    "file_permissions": "文件权限"
                }.get(category, category)
                
                if not result["status"]:
                    error_summary.append(f"❌ {category_name}: 检查失败")
                    all_details[category_name] = {
                        'details': result["details"],
                        'solutions': result["solutions"]
                    }
                    all_solutions.extend(result["solutions"])
                else:
                    error_summary.append(f"✅ {category_name}: 正常")
            
            return {
                'success': False,
                'error_summary': '; '.join(error_summary),
                'details': all_details,
                'solutions': all_solutions
            }

    def validate_image_file(self, image_path):
        """验证图像文件"""
        self.log(f"验证图像文件: {image_path}", "DEBUG")
        
        if not os.path.exists(image_path):
            self.log(f"文件不存在: {image_path}", "ERROR")
            return False
        
        if not os.path.isfile(image_path):
            self.log(f"不是文件: {image_path}", "ERROR")
            return False
        
        file_size = os.path.getsize(image_path)
        if file_size == 0:
            self.log(f"文件大小为0: {image_path}", "ERROR")
            return False
        
        self.log(f"文件验证通过，大小: {file_size} bytes", "SUCCESS")
        return True

    def encode_image_to_base64(self, image_path):
        """
        将图像文件编码为base64格式
        
        Args:
            image_path (str): 图像文件路径
            
        Returns:
            str: base64编码的图像数据
        """
        try:
            self.log(f"编码图像文件: {image_path}", "DEBUG")
            
            if not self.validate_image_file(image_path):
                raise FileNotFoundError(f"图像文件验证失败: {image_path}")
            
            with open(image_path, "rb") as image_file:
                image_data = image_file.read()
                image_base64 = base64.b64encode(image_data).decode("utf-8")
            
            self.log(f"图像编码成功，数据长度: {len(image_base64)} 字符", "SUCCESS")
            return image_base64
            
        except FileNotFoundError as e:
            self.log(f"文件未找到: {str(e)}", "ERROR")
            raise
        except Exception as e:
            self.log(f"图像编码失败: {str(e)}", "ERROR")
            raise Exception(f"图像编码失败: {str(e)}")

    def poster_to_latex(self, image_path, output_tex_file="output.tex"):
        """
        将海报图像转换为LaTeX代码
        
        Args:
            image_path (str): 海报图像路径
            output_tex_file (str): 输出的LaTeX文件名
            
        Returns:
            str: 生成的LaTeX代码
        """
        self.log(f"开始分析海报图像: {image_path}", "INFO")
        
        if not self.client:
            raise Exception("OpenAI API密钥未设置，无法生成LaTeX代码")
        
        # 编码图像
        image_base64 = self.encode_image_to_base64(image_path)
        
        # 确定图像MIME类型
        image_ext = Path(image_path).suffix.lower()
        if image_ext in ['.png']:
            mime_type = "image/png"
        elif image_ext in ['.jpg', '.jpeg']:
            mime_type = "image/jpeg"
        else:
            mime_type = "image/png"  # 默认为PNG
        
        self.log(f"图像类型: {mime_type}", "DEBUG")
        
        # 构建图像payload
        image_payload = {
            "type": "image_url",
            "image_url": {
                "url": f"data:{mime_type};base64,{image_base64}"
            }
        }
        
        # 调用OpenAI API
        self.log("调用OpenAI API生成LaTeX代码...", "INFO")
        try:
            response = self.client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {
                        "role": "system",
                        "content": "You are a helpful assistant that outputs complete LaTeX code for poster layout recreation."
                    },
                    {"role": "user", "content": self.custom_prompt},
                    {"role": "user", "content": [image_payload]}
                ]
            )
            
            # latex_code = response.choices[0].message.content
            raw_response = response.choices[0].message.content

            # --- START: 这是我们新增的清理代码 ---
            self.log("正在清理AI返回的LaTeX代码...", "DEBUG")
            
            # 首先尝试移除Markdown代码块标记
            cleaned_code = re.sub(r'^```(latex)?\s*', '', raw_response, flags=re.MULTILINE)
            cleaned_code = re.sub(r'```\s*$', '', cleaned_code, flags=re.MULTILINE)
            
            # 如果AI返回的内容包含说明文字，尝试提取LaTeX代码部分
            # 查找 \documentclass 开始的位置
            documentclass_match = re.search(r'\\documentclass', cleaned_code)
            if documentclass_match:
                # 从 \documentclass 开始提取
                latex_start = documentclass_match.start()
                cleaned_code = cleaned_code[latex_start:]
                self.log("检测到说明文字，已提取LaTeX代码部分", "DEBUG")
            
            # 查找 \end{document} 结束的位置
            end_document_match = re.search(r'\\end\{document\}', cleaned_code)
            if end_document_match:
                # 提取到 \end{document} 结束
                latex_end = end_document_match.end()
                cleaned_code = cleaned_code[:latex_end]
                self.log("已截取到LaTeX代码结束位置", "DEBUG")
            
            # 移除开头和结尾可能存在的任何空白字符
            latex_code = cleaned_code.strip()
            
            # 剔除所有中文内容
            self.log("正在剔除LaTeX代码中的中文内容...", "DEBUG")
            latex_code = self._remove_chinese_content(latex_code)
            
            # 应用增强的LaTeX代码修复
            self.log("正在应用增强的LaTeX代码修复...", "DEBUG")
            latex_code = self._enhance_latex_code(latex_code)
            # --- END: 清理代码结束 ---
            self.log("LaTeX代码生成成功!", "SUCCESS")
            
            # 保存LaTeX代码到文件
            try:
                with open(output_tex_file, "w", encoding="utf-8") as f:
                    f.write(latex_code)
                self.log(f"LaTeX代码已保存到: {output_tex_file}", "SUCCESS")
            except Exception as e:
                self.log(f"保存LaTeX文件失败: {e}", "ERROR")
                raise
            
            return latex_code
            
        except Exception as e:
            self.log(f"OpenAI API调用失败: {str(e)}", "ERROR")
            raise Exception(f"OpenAI API调用失败: {str(e)}")

    def compile_tex_to_pdf(self, tex_filename):
        """
        编译LaTeX文件为PDF（增强版）
        
        Args:
            tex_filename (str): LaTeX文件名
            
        Returns:
            str: 生成的PDF文件路径
        """
        try:
            self.log(f"开始编译LaTeX文件: {tex_filename}", "INFO")
            
            if not os.path.exists(tex_filename):
                raise FileNotFoundError(f"LaTeX文件不存在: {tex_filename}")
            
            # 检查LaTeX文件内容
            file_size = os.path.getsize(tex_filename)
            self.log(f"LaTeX文件大小: {file_size} bytes", "DEBUG")
            
            if file_size == 0:
                raise Exception("LaTeX文件为空")
            
            # 确定pdflatex命令
            pdflatex_cmd = self._get_pdflatex_command()
            
            # 编译LaTeX文件 - 获取文件所在目录
            tex_dir = os.path.dirname(os.path.abspath(tex_filename))
            tex_basename = os.path.basename(tex_filename)
            
            self.log("执行pdflatex编译...", "DEBUG")
            self.log(f"工作目录: {tex_dir}", "DEBUG")
            self.log(f"编译文件: {tex_basename}", "DEBUG")
            self.log(f"使用命令: {pdflatex_cmd}", "DEBUG")
            
            # 清理之前的辅助文件
            self._cleanup_before_compile(tex_filename)
            
            # 尝试编译（可能需要多次）
            max_attempts = 2
            for attempt in range(max_attempts):
                self.log(f"编译尝试 {attempt + 1}/{max_attempts}", "INFO")
                
                try:
                    result = subprocess.run(
                        [pdflatex_cmd, "-interaction=nonstopmode", "-halt-on-error", tex_basename], 
                        capture_output=True, text=True, cwd=tex_dir, timeout=60
                    )
                except UnicodeDecodeError:
                    # 如果出现编码问题，使用错误忽略模式
                    result = subprocess.run(
                        [pdflatex_cmd, "-interaction=nonstopmode", "-halt-on-error", tex_basename], 
                        capture_output=True, text=True, cwd=tex_dir, errors='ignore', timeout=60
                    )
                except subprocess.TimeoutExpired:
                    raise Exception("pdflatex编译超时（60秒）")
                
                # 详细的错误分析
                if result.returncode != 0:
                    self.log(f"编译尝试 {attempt + 1} 失败，返回码: {result.returncode}", "ERROR")
                    
                    # 分析错误类型
                    error_analysis = self._analyze_compilation_error(result.stdout, result.stderr)
                    
                    if error_analysis["is_miktex_update_issue"]:
                        raise Exception(
                            "MiKTeX需要更新。请按以下步骤操作：\n" 
                            "1. 打开 MiKTeX Console (管理员模式)\n" 
                            "2. 点击 'Check for updates'\n" 
                            "3. 安装所有可用更新\n" 
                            "4. 重启应用程序\n" 
                            f"详细错误: {error_analysis['error_message']}"
                        )
                    
                    if error_analysis["is_missing_package"]:
                        self.log(f"检测到缺失包: {error_analysis['missing_packages']}", "WARNING")
                        if attempt < max_attempts - 1:
                            self.log("尝试自动安装缺失包...", "INFO")
                            self._install_missing_packages(error_analysis['missing_packages'])
                            continue
                    
                    if attempt == max_attempts - 1:
                        # 最后一次尝试失败，输出详细错误
                        self._output_detailed_error(result.stdout, result.stderr, tex_filename)
                        raise Exception(f"pdflatex编译失败，返回码: {result.returncode}")
                else:
                    self.log("pdflatex编译成功!", "SUCCESS")
                    if result.stdout:
                        self.log(f"编译输出摘要: {result.stdout[:200]}...", "DEBUG")
                    break
            
            # 检查PDF是否生成
            pdf_filename = tex_filename.replace(".tex", ".pdf")
            if os.path.exists(pdf_filename):
                pdf_size = os.path.getsize(pdf_filename)
                self.log(f"PDF编译成功: {pdf_filename} ({pdf_size} bytes)", "SUCCESS")
                return pdf_filename
            else:
                raise Exception("PDF文件未生成，即使编译返回成功")
            
        except subprocess.CalledProcessError as e:
            self.log(f"编译过程出错: {e}", "ERROR")
            raise Exception(f"编译 {tex_filename} 时出错: {e}")

    def _get_pdflatex_command(self):
        """获取可用的pdflatex命令"""
        if self.pdflatex_path == "pdflatex":
            return "pdflatex"
        elif os.path.exists(self.pdflatex_path):
            return self.pdflatex_path
        else:
            # 最后尝试系统PATH
            try:
                subprocess.run(["pdflatex", "--version"], 
                             check=True, capture_output=True, text=True, timeout=5)
                return "pdflatex"
            except:
                raise FileNotFoundError(
                    f"pdflatex未找到。请检查MiKTeX安装或路径配置。\n" 
                    f"当前配置路径: {self.pdflatex_path}\n" 
                    "建议：\n" 
                    "1. 重新安装MiKTeX\n" 
                    "2. 确保MiKTeX添加到系统PATH\n" 
                    "3. 或者手动指定pdflatex.exe的完整路径"
                )

    def _cleanup_before_compile(self, tex_filename):
        """编译前清理辅助文件"""
        base_name = tex_filename.replace(".tex", "")
        cleanup_extensions = ["aux", "log", "out", "toc", "nav", "snm", "fdb_latexmk", "fls"]
        
        for ext in cleanup_extensions:
            aux_file = f"{base_name}.{ext}"
            try:
                if os.path.exists(aux_file):
                    os.remove(aux_file)
                    self.log(f"清理旧文件: {aux_file}", "DEBUG")
            except Exception as e:
                self.log(f"清理文件 {aux_file} 时出错: {e}", "WARNING")

    def _analyze_compilation_error(self, stdout, stderr):
        """分析编译错误"""
        analysis = {
            "is_miktex_update_issue": False,
            "is_missing_package": False,
            "missing_packages": [],
            "error_message": "",
            "suggestions": []
        }
        
        error_text = (stdout or "") + (stderr or "")
        error_text_lower = error_text.lower()
        
        # 检查MiKTeX更新问题
        miktex_update_keywords = [
            "you have not checked for miktex updates",
            "miktex update required",
            "miktex console",
            "check for updates"
        ]
        
        for keyword in miktex_update_keywords:
            if keyword in error_text_lower:
                analysis["is_miktex_update_issue"] = True
                analysis["error_message"] = error_text[:500]
                break
        
        # 检查缺失包
        import re
        package_patterns = [
            r"File `([^']+\.sty)' not found",
            r"LaTeX Error: File `([^']+)' not found",
            r"! Package (\\w+) Error"
        ]
        
        for pattern in package_patterns:
            matches = re.findall(pattern, error_text)
            for match in matches:
                package_name = match.replace('.sty', '')
                if package_name not in analysis["missing_packages"]:
                    analysis["missing_packages"].append(package_name)
                    analysis["is_missing_package"] = True
        
        return analysis

    def _install_missing_packages(self, packages):
        """尝试安装缺失的包"""
        for package in packages:
            try:
                self.log(f"尝试安装包: {package}", "INFO")
                # 使用MiKTeX包管理器安装
                subprocess.run(["mpm", "--install", package], 
                             check=True, capture_output=True, text=True, timeout=30)
                self.log(f"包安装成功: {package}", "SUCCESS")
            except Exception as e:
                self.log(f"包安装失败: {package} - {e}", "WARNING")

    def _output_detailed_error(self, stdout, stderr, tex_filename):
        """输出详细的错误信息"""
        self.log("=== 详细编译错误信息 ===", "ERROR")
        
        if stdout:
            self.log("编译输出 (stdout):", "DEBUG")
            # 输出最后1000个字符，这通常包含关键错误信息
            print(stdout[-1000:] if len(stdout) > 1000 else stdout)
        
        if stderr:
            self.log("编译错误 (stderr):", "DEBUG")
            print(stderr[-1000:] if len(stderr) > 1000 else stderr)
        
        # 尝试查找.log文件获取更多信息
        log_file = tex_filename.replace(".tex", ".log")
        if os.path.exists(log_file):
            try:
                with open(log_file, 'r', encoding='utf-8', errors='ignore') as f:
                    log_content = f.read()
                    # 查找错误行
                    lines = log_content.split('\n')
                    error_lines = [line for line in lines if 'error' in line.lower() or '!' in line]
                    if error_lines:
                        self.log("LaTeX日志中的错误行:", "DEBUG")
                        for line in error_lines[-10:]:
                            print(f"  {line}")
            except Exception as e:
                self.log(f"无法读取LaTeX日志文件: {e}", "WARNING")

    def clean_auxiliary_files(self, tex_filename):
        """
        清理编译过程中产生的辅助文件
        
        Args:
            tex_filename (str): LaTeX文件名
        """
        base_name = tex_filename.replace(".tex", "")
        auxiliary_extensions = ["aux", "log", "out", "toc", "nav", "snm"]
        
        cleaned_files = []
        for ext in auxiliary_extensions:
            aux_file = f"{base_name}.{ext}"
            try:
                if os.path.exists(aux_file):
                    os.remove(aux_file)
                    cleaned_files.append(aux_file)
            except Exception as e:
                self.log(f"清理文件 {aux_file} 时出错: {e}", "WARNING")
        
        if cleaned_files:
            self.log(f"已清理辅助文件: {', '.join(cleaned_files)}", "SUCCESS")

    def translate_poster_complete(self, image_path, output_base_name="output", clean_aux=True):
        """
        完整的海报翻译流程：图像 -> LaTeX -> PDF
        
        Args:
            image_path (str): 海报图像路径
            output_base_name (str): 输出文件基础名称
            clean_aux (bool): 是否清理辅助文件
            
        Returns:
            dict: 包含生成文件信息的字典
        """
        self.log("🚀 开始海报翻译流程...", "INFO")
        
        try:
            # 验证图像文件
            if not self.validate_image_file(image_path):
                raise FileNotFoundError(f"图像文件无效: {image_path}")
            
            # 第一步：生成LaTeX代码
            tex_filename = f"{output_base_name}.tex"
            self.log("第1步: 生成LaTeX代码", "INFO")
            latex_code = self.poster_to_latex(image_path, tex_filename)
            
            # 第二步：编译PDF
            self.log("第2步: 编译PDF", "INFO")
            pdf_filename = self.compile_tex_to_pdf(tex_filename)
            
            # 第三步：清理辅助文件（可选）
            if clean_aux:
                self.log("第3步: 清理辅助文件", "INFO")
                self.clean_auxiliary_files(tex_filename)
            
            result = {
                "success": True,
                "tex_file": tex_filename,
                "pdf_file": pdf_filename,
                "image_file": image_path,
                "latex_code_length": len(latex_code)
            }
            
            self.log("🎉 海报翻译完成!", "SUCCESS")
            self.log(f"   输入图像: {image_path}", "INFO")
            self.log(f"   LaTeX文件: {tex_filename}", "INFO")
            self.log(f"   PDF文件: {pdf_filename}", "INFO")
            
            return result
            
        except Exception as e:
            self.log(f"海报翻译失败: {str(e)}", "ERROR")
            return {
                "success": False,
                "error": str(e),
                "image_file": image_path
            }

# ========== 翻译功能类 ========== 

class SimpleTranslator:
    """简化的翻译器类，包含核心翻译功能"""
    
    def __init__(self, api_keys=None):
        self.api_keys = api_keys or load_api_keys()
        
        # 初始化OpenAI客户端
        if OPENAI_AVAILABLE and self.api_keys.get('OPENAI_API_KEY'):
            try:
                self.openai_client = OpenAI(api_key=self.api_keys['OPENAI_API_KEY'])
                log_message("OpenAI客户端初始化成功", "SUCCESS")
            except Exception as e:
                log_message(f"OpenAI客户端初始化失败: {e}", "ERROR")
                self.openai_client = None
        else:
            self.openai_client = None
            log_message("OpenAI不可用或API密钥未设置", "WARNING")
    
    def translate_poster(self, image_path, output_dir='poster_output'):
        """海报翻译功能（简化版）"""
        try:
            if not self.openai_client:
                return {
                    'success': False,
                    'error': 'OpenAI API未配置'
                }
            
            # 读取图片并编码为base64
            with open(image_path, 'rb') as image_file:
                image_base64 = base64.b64encode(image_file.read()).decode('utf-8')
            
            # 构建请求
            messages = [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": "请将这张海报翻译成LaTeX代码，要求：1. 翻译所有文字内容 2. 保持原有布局结构 3. 生成可直接编译的LaTeX代码 4. 不使用外部图片文件"
                        },
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/jpeg;base64,{image_base64}"
                            }
                        }
                    ]
                }
            ]
            
            # 调用OpenAI API
            response = self.openai_client.chat.completions.create(
                model="gpt-4o",
                messages=messages,
                max_tokens=4000
            )
            
            latex_content = response.choices[0].message.content
            
            # 保存LaTeX文件
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            tex_filename = f"poster_{timestamp}.tex"
            tex_path = os.path.join(output_dir, tex_filename)
            
            os.makedirs(output_dir, exist_ok=True)
            with open(tex_path, 'w', encoding='utf-8') as f:
                f.write(latex_content)
            
            log_message(f"海报翻译完成: {tex_filename}", "SUCCESS")
            
            return {
                'success': True,
                'message': '海报翻译完成',
                'tex_filename': tex_filename,
                'tex_path': tex_path,
                'latex_content': latex_content[:500] + '...' if len(latex_content) > 500 else latex_content
            }
            
        except Exception as e:
            log_message(f"海报翻译失败: {str(e)}", "ERROR")
            return {
                'success': False,
                'error': f'海报翻译失败: {str(e)}'
            }
    
    def translate_webpage_google(self, url):
        """Google网页翻译（简化版）"""
        try:
            if not SELENIUM_AVAILABLE:
                return {
                    'success': False,
                    'error': 'Selenium未安装，无法进行网页翻译'
                }
            
            # 设置Chrome选项
            chrome_options = Options()
            chrome_options.add_argument('--headless')
            chrome_options.add_argument('--no-sandbox')
            chrome_options.add_argument('--disable-dev-shm-usage')
            chrome_options.add_argument('--disable-gpu')

            # 额外的隔离选项
            chrome_options.add_argument("--disable-extensions")
            chrome_options.add_argument("--disable-background-networking")
            chrome_options.add_argument("--disable-sync")
            chrome_options.add_argument("--disable-default-apps")
            chrome_options.add_argument("--no-first-run")
            chrome_options.add_argument("--disable-background-timer-throttling")
            chrome_options.add_argument("--disable-backgrounding-occluded-windows")
            chrome_options.add_argument("--disable-renderer-backgrounding")

            # 使用随机remote debugging port来避免冲突
            import random
            chrome_options.add_argument(f"--remote-debugging-port={random.randint(9222, 9999)}")

            # 指定一个snap可以访问的目录（在项目目录内）
            import tempfile
            import uuid
            import os
            import time
            chrome_data_dir = os.path.join(os.path.dirname(__file__), 'tmp', 'chrome_data')
            os.makedirs(chrome_data_dir, exist_ok=True)
            user_data_dir = os.path.join(chrome_data_dir, f"profile_{os.getpid()}_{int(time.time()*1000)}_{uuid.uuid4().hex[:8]}")
            chrome_options.add_argument(f"--user-data-dir={user_data_dir}")

            # Snap专用：允许访问更多目录
            chrome_options.add_argument("--disable-software-rasterizer")

            driver = None
            try:
                driver = webdriver.Chrome(options=chrome_options)
                
                # 访问Google翻译
                translate_url = f"https://translate.google.com/translate?sl=auto&tl=zh&u={url}"
                driver.get(translate_url)
                
                # 等待页面加载
                time.sleep(5)
                
                # 获取翻译后的内容
                page_source = driver.page_source
                
                # 解析内容
                soup = BeautifulSoup(page_source, 'html.parser')
                
                # 保存结果
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                output_filename = f"google_translate_{timestamp}.html"
                output_path = os.path.join('web_translation_output', output_filename)
                
                os.makedirs('web_translation_output', exist_ok=True)
                with open(output_path, 'w', encoding='utf-8') as f:
                    f.write(page_source)
                
                log_message(f"Google网页翻译完成: {output_filename}", "SUCCESS")
                
                return {
                    'success': True,
                    'message': 'Google网页翻译完成',
                    'output_filename': output_filename,
                    'output_path': output_path,
                    'url': url
                }
                
            finally:
                if driver:
                    _cleanup_chrome_driver(driver)
                # 清理临时用户数据目录
                try:
                    import shutil
                    shutil.rmtree(user_data_dir, ignore_errors=True)
                except Exception:
                    pass
            
        except Exception as e:
            log_message(f"Google网页翻译失败: {str(e)}", "ERROR")
            return {
                'success': False,
                'error': f'Google网页翻译失败: {str(e)}'
            }
    
    def translate_webpage_gpt(self, url):
        """GPT网页翻译（简化版）"""
        try:
            if not self.openai_client:
                return {
                    'success': False,
                    'error': 'OpenAI API未配置'
                }
            
            # 获取网页内容
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            }
            
            response = requests.get(url, headers=headers, timeout=30)
            response.raise_for_status()
            
            # 解析HTML内容
            soup = BeautifulSoup(response.content, 'html.parser')
            
            # 提取主要文本内容
            for script in soup(["script", "style"]):
                script.decompose()
            
            text_content = soup.get_text()
            text_content = '\n'.join(line.strip() for line in text_content.splitlines() if line.strip())
            
            # 限制文本长度
            if len(text_content) > 8000:
                text_content = text_content[:8000] + "..."
            
            # 使用GPT翻译
            messages = [
                {
                    "role": "system",
                    "content": "你是一个专业的网页翻译助手。请将提供的网页内容翻译成中文，保持原有的结构和格式。"
                },
                {
                    "role": "user",
                    "content": f"请将以下网页内容翻译成中文：\n\n{text_content}"
                }
            ]
            
            gpt_response = self.openai_client.chat.completions.create(
                model="gpt-4",
                messages=messages,
                max_tokens=4000
            )
            
            translated_content = gpt_response.choices[0].message.content
            
            # 保存翻译结果
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_filename = f"gpt_translate_{timestamp}.txt"
            output_path = os.path.join('web_translation_output', output_filename)
            
            os.makedirs('web_translation_output', exist_ok=True)
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write(f"原始URL: {url}\n")
                f.write("="*50 + "\n")
                f.write(translated_content)
            
            log_message(f"GPT网页翻译完成: {output_filename}", "SUCCESS")
            
            return {
                'success': True,
                'message': 'GPT网页翻译完成',
                'output_filename': output_filename,
                'output_path': output_path,
                'url': url,
                'translated_content': translated_content[:500] + '...' if len(translated_content) > 500 else translated_content
            }
            
        except Exception as e:
            log_message(f"GPT网页翻译失败: {str(e)}", "ERROR")
            return {
                'success': False,
                'error': f'GPT网页翻译失败: {str(e)}'
            }
    
    # ========== DEPRECATED: 保留以备后用 ==========
    # 旧的百度图片翻译方法，已被 translate_image_reference() 替代
    # def translate_image_baidu(self, image_path, from_lang='en', to_lang='zh'):
    #     """百度图片翻译（完整版）"""
    #     try:
    #         log_message(f"开始百度图片翻译: {image_path}", "INFO")
    #
    #         # 创建百度翻译器实例
    #         baidu_translator = BaiduImageTranslator(
    #             api_key=self.api_keys.get('BAIDU_API_KEY'),
    #             secret_key=self.api_keys.get('BAIDU_SECRET_KEY')
    #         )
    #
    #         # 获取access token
    #         if not baidu_translator.get_access_token():
    #             return {
    #                 'success': False,
    #                 'error': '百度API密钥未配置或无效'
    #             }
    #
    #         # 调用完整的翻译流程
    #         result = baidu_translator.translate_image_complete(
    #             image_path=image_path,
    #             from_lang=from_lang,
    #             to_lang=to_lang,
    #             save_image=True
    #         )
    #
    #         if result['success']:
    #             log_message(f"百度图片翻译成功: {image_path}", "SUCCESS")
    #             return {
    #                 'success': True,
    #                 'message': '百度图片翻译完成',
    #                 'original_image': result['original_image'],
    #                 'translated_image': result.get('translated_image'),
    #                 'text_info': result['text_info'],
    #                 'translation_direction': f"{from_lang} -> {to_lang}",
    #                 'has_translated_image': bool(result.get('translated_image'))
    #             }
    #         else:
    #             return {
    #                 'success': False,
    #                 'error': result.get('error', '翻译失败')
    #             }
    #
    #     except Exception as e:
    #         log_message(f"百度图片翻译失败: {str(e)}", "ERROR")
    #         return {
    #             'success': False,
    #             'error': f'百度图片翻译失败: {str(e)}'
    #         }

# 延迟初始化翻译器实例
translator = None

def get_translator():
    """获取翻译器实例（延迟初始化）"""
    global translator
    if translator is None:
        translator = SimpleTranslator()
    return translator

# ========== 网页翻译API接口 ==========

@app.route('/api/webpage-google-translate', methods=['POST'])
@jwt_required()
def webpage_google_translate():
    """Google网页翻译API（完整版）"""
    try:
        log_message("开始Google网页翻译API请求处理", "INFO")
        
        data = request.get_json()
        if not data or not data.get('url'):
            return jsonify({
                'success': False,
                'error': '请提供网页URL'
            }), 400
        
        url = data['url'].strip()
        
        # 验证URL格式
        try:
            from urllib.parse import urlparse
            parsed = urlparse(url)
            if not parsed.scheme or not parsed.netloc:
                raise ValueError("无效的URL格式")
        except Exception:
            return jsonify({
                'success': False,
                'error': '无效的URL格式'
            }), 400
        
        # 使用缓存：根据URL生成稳定文件名（MD5）
        import hashlib
        url_hash = hashlib.md5(url.encode('utf-8')).hexdigest()[:16]
        cache_dir = os.path.join('translated_snapshot')
        os.makedirs(cache_dir, exist_ok=True)
        cached_pdf = os.path.join(cache_dir, f"web_{url_hash}.pdf")
        
        if os.path.exists(cached_pdf) and os.path.getsize(cached_pdf) > 0:
            pdf_filename = os.path.basename(cached_pdf)
            log_message(f"命中网页翻译缓存: {pdf_filename}", "INFO")
            return jsonify({
                'success': True,
                'message': '缓存命中',
                'pdf_filename': pdf_filename,
                'preview_url': f'/preview/translated/{pdf_filename}',
                'original_url': url,
                'file_size': os.path.getsize(cached_pdf)
            })

        # 未命中则执行抓取并生成PDF
        try:
            pdf_path, pdf_filename_real = _capture_google_translated_pdf(url)
            # 复制为稳定hash命名，便于复用
            try:
                import shutil
                shutil.copy2(pdf_path, cached_pdf)
                pdf_filename = os.path.basename(cached_pdf)
            except Exception:
                pdf_filename = pdf_filename_real
                cached_pdf = pdf_path

            result = {
                'success': True,
                'pdf_filename': pdf_filename,
                'output_filename': pdf_filename
            }
        except Exception as e:
            result = {
                'success': False,
                'error': str(e)
            }
        
        if result['success']:
            return jsonify({
                'success': True,
                'message': 'Google网页翻译完成',
                'pdf_filename': result['pdf_filename'],
                'output_filename': result['output_filename'],
                'preview_url': f'/preview/translated/{result["pdf_filename"]}',
                'url': url,
                'file_size': os.path.getsize(cached_pdf) if 'cached_pdf' in locals() else 0
            })
        else:
            return jsonify(result), 500
        
    except Exception as e:
        log_message(f"Google网页翻译API失败: {str(e)}", "ERROR")
        return jsonify({
            'success': False,
            'error': f'Google网页翻译失败: {str(e)}'
        }), 500

# GPT网页翻译功能暂时移除，待稳定后再添加
# 未来可以在这里添加GPT网页翻译的实现

# ========== 网页翻译辅助函数 ==========

def _sanitize_title(title: str) -> str:
    """
    清理网页标题，使其适合作为文件名
    
    参数:
        title: 原始网页标题
        
    返回:
        清理后的安全文件名
    """
    # 如果标题为空，使用默认值
    title = (title or "webpage").strip().replace('\n', ' ')
    # 移除Windows文件名中的非法字符
    title = re.sub(r'[\\/*?:"<>|]', '_', title)
    # 限制长度为80个字符
    return title[:80] or "webpage"

async def _capture_google_translated_pdf_pyppeteer_async(url: str):
    """
    使用Pyppeteer（异步）渲染Google翻译页面并生成PDF
    
    参数:
        url: 要翻译的原始网页URL
        
    返回:
        (pdf_path, pdf_filename): PDF文件的完整路径和文件名
    """
    browser = await launch({
        'headless': True,
        'args': [
            '--no-sandbox',
            '--disable-setuid-sandbox',
            '--disable-gpu',
            '--allow-insecure-localhost',
            '--ignore-certificate-errors',
            '--lang=en-US,en;q=0.9',
        ]
    })
    
    page = await browser.newPage()
    
    # 设置视口大小
    await page.setViewport({
        'width': 1280,
        'height': 800,
        'deviceScaleFactor': 1
    })
    
    # 构建Google翻译URL
    translate_url = f"https://translate.google.com/translate?hl=en&sl=auto&tl=en&u={quote(url)}&prev=search"
    log_message(f"[pyppeteer] 打开: {translate_url}", "DEBUG")
    
    # 访问页面并等待加载完成
    await page.goto(translate_url, {
        'waitUntil': 'networkidle2',  # 等待网络空闲
        'timeout': 60000              # 60秒超时
    })
    
    # 尝试等待主体内容稳定
    try:
        await page.waitForSelector('body', {'timeout': 20000})
    except Exception:
        pass
    
    # 移除Google翻译工具栏
    try:
        await page.evaluate("var nv = document.getElementById('gt-nvframe'); if(nv){ nv.remove(); }")
        await page.evaluate("""
            var css = document.createElement("style");
            css.type = "text/css";
            css.innerHTML = `
                .goog-te-gadget, .goog-te-gadget-simple, #goog-gt-tt { display: none !important; }
            `;
            document.head.appendChild(css);
        """)
        log_message("[pyppeteer] 已移除 Google Translate 顶部工具栏", "SUCCESS")
    except Exception as e:
        log_message(f"[pyppeteer] 移除顶部工具栏时出错：{e}", "WARNING")
    
    # 使用print媒体类型（更适合PDF输出）
    try:
        await page.emulateMediaType('print')
    except Exception:
        pass
    
    # 获取并清理页面标题
    safe_title = _sanitize_title(await page.title())
    
    # 设置输出目录
    out_dir = 'translated_snapshot'
    os.makedirs(out_dir, exist_ok=True)
    
    # 生成PDF
    pdf_filename = f"{safe_title}.pdf"
    pdf_path = os.path.join(out_dir, pdf_filename)
    
    await page.pdf({
        'path': pdf_path,
        'format': 'A4',
        'printBackground': True,
        'margin': {
            'top': '0.4in',
            'bottom': '0.4in',
            'left': '0.4in',
            'right': '0.4in'
        },
        'scale': 0.9
    })
    
    await browser.close()
    
    return pdf_path, pdf_filename

def _capture_google_translated_pdf_pyppeteer(url: str):
    """
    Pyppeteer的同步包装器
    """
    if not PYPPETEER_AVAILABLE:
        raise RuntimeError("Pyppeteer 不可用")
    
    # 创建新的事件循环
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(
            _capture_google_translated_pdf_pyppeteer_async(url)
        )
    finally:
        loop.close()

def _capture_original_webpage_pdf(url: str) -> tuple:
    """
    生成原始网页的PDF
    
    参数:
        url: 原始网页URL
        
    返回:
        (pdf_path, pdf_filename): PDF文件的完整路径和文件名
    """
    # 优先尝试使用Pyppeteer
    if PYPPETEER_AVAILABLE:
        try:
            return _capture_original_webpage_pdf_pyppeteer(url)
        except Exception as e:
            log_message(f"Pyppeteer 生成原始PDF失败，回退到 Selenium: {str(e)}", "ERROR")
    
    # 使用Selenium作为备选方案
    driver = None
    try:
        # 启动Chrome浏览器
        driver = _setup_chrome(disable_js=False)
        
        log_message(f"打开原始网页: {url}", "DEBUG")
        
        # 访问页面
        driver.get(url)
        
        # 等待页面基本加载完成
        try:
            WebDriverWait(driver, 20).until(
                EC.presence_of_element_located((By.TAG_NAME, 'body'))
            )
        except Exception:
            time.sleep(2)  # 兜底等待
        
        # 设置打印媒体类型
        try:
            driver.execute_cdp_cmd('Emulation.setEmulatedMedia', {'media': 'print'})
        except Exception:
            pass
        
        # 获取并清理页面标题
        safe_title = _sanitize_title(driver.title)
        
        # 设置输出目录
        out_dir = 'original_snapshot'
        os.makedirs(out_dir, exist_ok=True)
        
        # 生成PDF
        pdf_filename = f"{safe_title}_original.pdf"
        pdf_path = os.path.join(out_dir, pdf_filename)
        _print_to_pdf(driver, pdf_path, scale=0.9)
        
        return pdf_path, pdf_filename
        
    finally:
        # 确保关闭浏览器
        if driver:
            try:
                driver.quit()
            except Exception:
                pass

async def _capture_original_webpage_pdf_pyppeteer_async(url: str):
    """
    使用Pyppeteer（异步）生成原始网页PDF
    """
    browser = await launch({
        'headless': True,
        'args': [
            '--no-sandbox',
            '--disable-setuid-sandbox',
            '--disable-gpu',
            '--allow-insecure-localhost',
            '--ignore-certificate-errors',
            '--lang=zh-CN,zh;q=0.9',  # 使用中文语言设置
        ]
    })
    
    page = await browser.newPage()
    
    # 设置视口大小
    await page.setViewport({
        'width': 1280,
        'height': 800,
        'deviceScaleFactor': 1
    })
    
    log_message(f"[pyppeteer] 打开原始网页: {url}", "DEBUG")
    
    # 访问页面并等待加载完成
    await page.goto(url, {
        'waitUntil': 'networkidle2',  # 等待网络空闲
        'timeout': 60000              # 60秒超时
    })
    
    # 尝试等待主体内容稳定
    try:
        await page.waitForSelector('body', {'timeout': 20000})
    except Exception:
        pass
    
    # 使用print媒体类型（更适合PDF输出）
    try:
        await page.emulateMediaType('print')
    except Exception:
        pass
    
    # 获取并清理页面标题
    safe_title = _sanitize_title(await page.title())
    
    # 设置输出目录
    out_dir = 'original_snapshot'
    os.makedirs(out_dir, exist_ok=True)
    
    # 生成PDF
    pdf_filename = f"{safe_title}_original.pdf"
    pdf_path = os.path.join(out_dir, pdf_filename)
    
    await page.pdf({
        'path': pdf_path,
        'format': 'A4',
        'printBackground': True,
        'margin': {
            'top': '0.4in',
            'bottom': '0.4in',
            'left': '0.4in',
            'right': '0.4in'
        },
        'scale': 0.9
    })
    
    await browser.close()
    
    return pdf_path, pdf_filename

def _capture_original_webpage_pdf_pyppeteer(url: str):
    """
    Pyppeteer的同步包装器
    """
    if not PYPPETEER_AVAILABLE:
        raise RuntimeError("Pyppeteer 不可用")
    
    # 创建新的事件循环
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(
            _capture_original_webpage_pdf_pyppeteer_async(url)
        )
    finally:
        loop.close()

def _capture_google_translated_pdf(url: str) -> tuple:
    """
    打开Google翻译页面并生成PDF
    优先使用Pyppeteer，失败时回退到Selenium
    
    参数:
        url: 要翻译的原始网页URL
        
    返回:
        (pdf_path, pdf_filename): PDF文件的完整路径和文件名
        
    异常:
        可能抛出各种浏览器相关的异常
    """
    # 优先尝试使用Pyppeteer（通常更稳定）
    if PYPPETEER_AVAILABLE:
        try:
            return _capture_google_translated_pdf_pyppeteer(url)
        except Exception as e:
            log_message(f"Pyppeteer 转 PDF 失败，回退到 Selenium: {str(e)}", "ERROR")
    
    # 使用Selenium作为备选方案
    driver = None
    try:
        # 启动Chrome浏览器
        driver = _setup_chrome(disable_js=False)
        
        # 构建Google翻译URL
        translate_url = f"https://translate.google.com/translate?hl=en&sl=auto&tl=en&u={quote(url)}&prev=search"
        log_message(f"打开Google翻译地址: {translate_url}", "DEBUG")
        
        # 访问页面
        driver.get(translate_url)
        
        # 等待页面基本加载完成
        try:
            WebDriverWait(driver, 20).until(
                EC.presence_of_element_located((By.TAG_NAME, 'body'))
            )
        except Exception:
            time.sleep(2)  # 兜底等待
        
        # 移除Google翻译工具栏
        _hide_google_translate_toolbar(driver)
        
        # 设置打印媒体类型
        try:
            driver.execute_cdp_cmd('Emulation.setEmulatedMedia', {'media': 'print'})
        except Exception:
            pass
        
        # 获取并清理页面标题
        safe_title = _sanitize_title(driver.title)
        
        # 设置输出目录
        out_dir = 'translated_snapshot'
        os.makedirs(out_dir, exist_ok=True)
        
        # 生成PDF
        pdf_filename = f"{safe_title}.pdf"
        pdf_path = os.path.join(out_dir, pdf_filename)
        _print_to_pdf(driver, pdf_path, scale=0.9)
        
        return pdf_path, pdf_filename
        
    finally:
        # 确保关闭浏览器
        if driver:
            try:
                driver.quit()
            except Exception:
                pass

# ========== 网址上传接口 ==========


# ========== 认证相关API（复制之前的实现）========== 

@app.route('/api/auth/signup', methods=['POST'])
def signup():
    try:
        data = request.get_json()
        if not data or not all(k in data for k in ('name', 'email', 'password')):
            return jsonify({'success': False, 'error': '请提供姓名、邮箱和密码'}), 400
        
        name = data['name'].strip()
        email = data['email'].strip().lower()
        password = data['password']
        
        if len(name) < 2:
            return jsonify({'success': False, 'error': '姓名至少需要2个字符'}), 400
        
        if len(password) < 6:
            return jsonify({'success': False, 'error': '密码至少需要6个字符'}), 400
        
        if User.query.filter_by(email=email).first():
            return jsonify({'success': False, 'error': '该邮箱已被注册'}), 400
        
        user = User(name=name, email=email)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        
        access_token = create_access_token(identity=user.id)
        log_message(f"新用户注册成功: {user.email}", "SUCCESS")
        
        return jsonify({
            'success': True,
            'message': '注册成功',
            'user': user.to_dict(),
            'token': access_token
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': '注册失败，请稍后重试'}), 500

@app.route('/api/auth/signin', methods=['POST'])
def signin():
    try:
        data = request.get_json()
        if not data or not all(k in data for k in ('email', 'password')):
            return jsonify({'success': False, 'error': '请提供邮箱和密码'}), 400
        
        email = data['email'].strip().lower()
        password = data['password']
        
        user = User.query.filter_by(email=email).first()
        if not user or not user.check_password(password):
            return jsonify({'success': False, 'error': '邮箱或密码错误'}), 401
        
        access_token = create_access_token(identity=user.id)
        log_message(f"用户登录成功: {user.email}", "SUCCESS")
        
        return jsonify({
            'success': True,
            'message': '登录成功',
            'user': user.to_dict(),
            'token': access_token
        })
    except Exception as e:
        return jsonify({'success': False, 'error': '登录失败，请稍后重试'}), 500

@app.route('/api/auth/logout', methods=['POST'])
@jwt_required()
def logout():
    try:
        jti = get_jwt()['jti']
        blacklisted_tokens.add(jti)
        return jsonify({'success': True, 'message': '登出成功'})
    except Exception as e:
        return jsonify({'success': False, 'error': '登出失败'}), 500

@app.route('/api/auth/user', methods=['GET'])
@jwt_required()
def get_current_user():
    try:
        user_id = get_jwt_identity()
        user = User.query.get(user_id)
        if not user:
            return jsonify({'success': False, 'error': '用户不存在'}), 404
        return jsonify({'success': True, 'user': user.to_dict()})
    except Exception as e:
        return jsonify({'success': False, 'error': '获取用户信息失败'}), 500

# ========== 客户管理（复制之前的实现）========== 

@app.route('/api/clients', methods=['GET'])
@jwt_required()
@cache_api_response('clients_list', timeout_seconds=300)  # 缓存5分钟
def get_clients():
    try:
        user_id = get_jwt_identity()
        # 获取查询参数，默认只显示未归档的客户
        include_archived = request.args.get('include_archived', 'false').lower() == 'true'
        
        # 使用SQLAlchemy ORM（元数据已刷新）
        if include_archived:
            clients = Client.query.filter_by(user_id=user_id).order_by(Client.created_at.desc()).all()
        else:
            clients = Client.query.filter(
                Client.user_id == user_id,
                (Client.is_archived == False) | (Client.is_archived.is_(None))
            ).order_by(Client.created_at.desc()).all()
        
        clients_data = [client.to_dict() for client in clients]
        
        return jsonify({'success': True, 'clients': clients_data})
        
    except Exception as e:
        print(f"获取客户列表错误: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': '获取客户列表失败', 'details': str(e)}), 500

@app.route('/api/clients', methods=['POST'])
@jwt_required()
def add_client():
    try:
        user_id = get_jwt_identity()
        data = request.get_json()
        if not data or not data.get('name', '').strip():
            return jsonify({'success': False, 'error': '请提供客户姓名'}), 400
        
        # 使用SQLAlchemy ORM（元数据已刷新）
        client = Client(
            name=data['name'].strip(),
            case_type=data.get('caseType', '').strip(),
            case_date=data.get('caseDate', '').strip(),
            phone=data.get('phone', '').strip() if data.get('phone') else None,
            email=data.get('email', '').strip() if data.get('email') else None,
            address=data.get('address', '').strip() if data.get('address') else None,
            notes=data.get('notes', '').strip() if data.get('notes') else None,
            user_id=user_id
        )
        db.session.add(client)
        db.session.commit()
        
        # 使客户列表缓存失效
        invalidate_client_cache(user_id)
        
        return jsonify({'success': True, 'message': '客户添加成功', 'client': client.to_dict()})
    except Exception as e:
        db.session.rollback()
        print(f"添加客户错误: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': '添加客户失败', 'details': str(e)}), 500

@app.route('/api/clients/<client_id>', methods=['DELETE'])
@jwt_required()
def delete_client(client_id):
    """删除客户"""
    try:
        user_id = get_jwt_identity()
        client = Client.query.filter_by(id=client_id, user_id=user_id).first()
        if not client:
            return jsonify({'success': False, 'error': '客户不存在'}), 404
        
        client_name = client.name
        
        # 删除客户（材料会因为外键约束自动删除）
        db.session.delete(client)
        db.session.commit()
        
        # 使客户列表缓存失效
        invalidate_client_cache(user_id)
        # 使材料列表缓存失效
        invalidate_materials_cache(client_id)
        
        log_message(f"客户删除成功: {client_name}", "SUCCESS")
        
        return jsonify({'success': True, 'message': f'客户 {client_name} 删除成功'})
    except Exception as e:
        db.session.rollback()
        log_message(f"删除客户失败: {str(e)}", "ERROR")
        return jsonify({'success': False, 'error': '删除客户失败'}), 500

# ========== 材料管理（复制之前的实现）========== 

@app.route('/api/clients/<client_id>/materials', methods=['GET'])
@jwt_required()
def get_materials(client_id):
    try:
        user_id = get_jwt_identity()
        client = Client.query.filter_by(id=client_id, user_id=user_id).first()
        if not client:
            return jsonify({'success': False, 'error': '客户不存在'}), 404
        
        # 检查缓存
        cache_key = cache_key_for_client_materials(client_id)
        cached_materials = api_cache.get(cache_key)
        if cached_materials is not None:
            log_message(f"从缓存获取材料列表: 客户ID={client_id}", "INFO", is_polling=True)
            return jsonify({'success': True, 'materials': cached_materials})

        # 强制刷新会话以获取最新数据
        db.session.expire_all()
        materials = Material.query.filter_by(client_id=client_id).order_by(Material.created_at.desc()).all()

        log_message(f"获取材料列表: 客户ID={client_id}, 找到{len(materials)}个材料", "INFO", is_polling=True)
        
        # 序列化材料列表
        materials_data = []
        for material in materials:
            try:
                materials_data.append(material.to_dict())
            except Exception as dict_error:
                log_message(f"序列化材料失败: {material.id}, 错误: {str(dict_error)}", "ERROR")
                import traceback
                traceback.print_exc()
                # 跳过这个材料，继续处理其他的
                continue

        # 缓存结果，材料列表缓存1分钟（实时性要求高）
        api_cache.set(cache_key, materials_data, timeout_seconds=60)

        return jsonify({'success': True, 'materials': materials_data})
    except Exception as e:
        log_message(f"获取材料列表失败: {str(e)}", "ERROR")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': f'获取材料列表失败: {str(e)}'}), 500

@app.route('/api/clients/<client_id>/materials/upload', methods=['POST'])
@jwt_required()
def upload_files(client_id):
    """文件上传接口"""
    try:
        user_id = get_jwt_identity()
        client = Client.query.filter_by(id=client_id, user_id=user_id).first()
        if not client:
            return jsonify({'success': False, 'error': '客户不存在'}), 404
        
        if 'files' not in request.files:
            return jsonify({'success': False, 'error': '没有上传文件'}), 400
        
        files = request.files.getlist('files')
        if not files or all(file.filename == '' for file in files):
            return jsonify({'success': False, 'error': '没有选择文件'}), 400
        
        uploaded_materials = []

        for file in files:
            if file.filename:
                # 保存文件
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                file_ext = Path(file.filename).suffix.lower()
                safe_filename = secure_filename(file.filename)
                filename = f"{timestamp}_{safe_filename}"
                file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)

                file.save(file_path)

                file_type = get_file_type(file.filename)

                # 检测PDF文件，创建占位记录后台拆分
                if file_ext == '.pdf' and PYMUPDF_AVAILABLE:
                    log_message(f"检测到PDF文件: {file.filename}", "INFO")

                    try:
                        # 快速获取页数
                        doc = fitz.open(file_path)
                        total_pages = len(doc)
                        doc.close()

                        # 创建PDF会话ID
                        pdf_session_id = f"pdf_{timestamp}_{uuid.uuid4().hex[:8]}"

                        # 立即创建占位Material记录（显示"拆分中"）
                        log_message(f"PDF共有 {total_pages} 页，创建占位记录", "INFO")
                        for page_num in range(total_pages):
                            page_material = Material(
                                name=f"{file.filename} - 第{page_num + 1}页",
                                type='image',
                                original_filename=f"{file.filename}_page_{page_num + 1}",
                                file_path=file_path,  # 暂时指向原PDF
                                status='拆分中',  # 统一状态值
                                client_id=client_id,
                                pdf_session_id=pdf_session_id,
                                pdf_page_number=page_num + 1,
                                pdf_total_pages=total_pages,
                                pdf_original_file=file_path,
                                processing_step='splitting',
                                processing_progress=0  # 0%开始
                            )
                            db.session.add(page_material)
                            uploaded_materials.append(page_material)

                        # 立即提交，让前端看到
                        db.session.commit()
                        log_message(f"✓ 已创建 {total_pages} 个占位记录", "SUCCESS")

                        # 启动后台线程处理PDF拆分+翻译
                        import threading
                        from concurrent.futures import ThreadPoolExecutor, as_completed

                        def process_pdf_async(pdf_file_path, session_id, client_id):
                            """后台拆分PDF并翻译"""
                            try:
                                with app.app_context():
                                    # 创建会话目录
                                    session_dir = os.path.join(app.root_path, 'uploads', 'pdf_sessions', session_id)
                                    os.makedirs(session_dir, exist_ok=True)

                                    # 打开PDF
                                    doc = fitz.open(pdf_file_path)
                                    total_pages = len(doc)

                                    # 拆分每一页
                                    for page_num in range(total_pages):
                                        page = doc[page_num]

                                        # 转换为图片，限制分辨率（降低到3000px以提高稳定性）
                                        page_rect = page.rect
                                        page_width = page_rect.width
                                        page_height = page_rect.height

                                        # 计算zoom，确保最长边不超过3000px（降低分辨率提高稳定性）
                                        max_dimension = max(page_width, page_height)
                                        max_allowed = 3000  # 从4096降低到3000

                                        if max_dimension * 2.0 > max_allowed:
                                            # 如果2倍会超标，按比例缩小
                                            zoom = max_allowed / max_dimension * 0.9  # 留10%余量
                                        else:
                                            zoom = 2.0  # 默认2倍高清

                                        mat = fitz.Matrix(zoom, zoom)
                                        pix = page.get_pixmap(matrix=mat)

                                        log_message(f"第 {page_num + 1} 页尺寸: {int(pix.width)}x{int(pix.height)}px (zoom={zoom:.2f})", "DEBUG")

                                        # 保存图片
                                        img_filename = f"page_{page_num + 1}.png"
                                        img_path = os.path.join(session_dir, img_filename)
                                        pix.save(img_path)

                                        # 加强压缩：目标2MB，分辨率3000px
                                        try:
                                            from PIL import Image
                                            file_size = os.path.getsize(img_path)
                                            max_size = 2 * 1024 * 1024  # 降低到2MB，提高上传稳定性

                                            img = Image.open(img_path)

                                            # 再次检查尺寸（降低到3000px）
                                            if max(img.width, img.height) > 3000:
                                                # 计算缩放比例
                                                scale = 2800 / max(img.width, img.height)  # 目标2800px
                                                new_width = int(img.width * scale)
                                                new_height = int(img.height * scale)
                                                img = img.resize((new_width, new_height), Image.Resampling.LANCZOS)
                                                log_message(f"第 {page_num + 1} 页缩放到: {new_width}x{new_height}px", "INFO")

                                            if img.mode == 'RGBA':
                                                img = img.convert('RGB')

                                            jpg_path = img_path.replace('.png', '.jpg')

                                            # 无论文件大小，都进行压缩以提高稳定性
                                            if file_size > max_size:
                                                # 二分查找最佳质量（降低范围）
                                                low, high = 10, 85  # 从95降到85
                                                best_quality = low

                                                while low <= high:
                                                    mid = (low + high) // 2
                                                    img.save(jpg_path, 'JPEG', quality=mid, optimize=True)
                                                    current_size = os.path.getsize(jpg_path)

                                                    if current_size <= max_size:
                                                        best_quality = mid
                                                        low = mid + 1
                                                    else:
                                                        high = mid - 1

                                                img.save(jpg_path, 'JPEG', quality=best_quality, optimize=True)
                                                final_size = os.path.getsize(jpg_path)

                                                if final_size <= max_size:
                                                    # ⭐ 安全删除：确保不是同一个文件
                                                    if img_path != jpg_path and os.path.exists(img_path):
                                                        os.remove(img_path)
                                                    img_path = jpg_path
                                                    log_message(f"✓ 第 {page_num + 1} 页压缩完成: {final_size / 1024 / 1024:.2f}MB (质量: {best_quality})", "SUCCESS")
                                                else:
                                                    try:
                                                        if os.path.exists(jpg_path) and jpg_path != img_path:
                                                            os.remove(jpg_path)
                                                    except:
                                                        pass
                                                    raise Exception(f"第 {page_num + 1} 页图片过大")
                                            else:
                                                # 文件较小，但仍压缩到合理质量（提高稳定性）
                                                img.save(jpg_path, 'JPEG', quality=75, optimize=True)  # 从95降到75
                                                # ⭐ 安全删除：确保不是同一个文件
                                                if img_path != jpg_path and os.path.exists(img_path):
                                                    os.remove(img_path)
                                                img_path = jpg_path
                                                final_size = os.path.getsize(jpg_path)
                                                log_message(f"✓ 第 {page_num + 1} 页转换完成: {final_size / 1024 / 1024:.2f}MB", "SUCCESS")

                                        except Exception as compress_error:
                                            log_message(f"第 {page_num + 1} 页压缩失败: {str(compress_error)}", "WARNING")

                                        # 更新Material记录的文件路径和状态
                                        page_material = Material.query.filter_by(
                                            pdf_session_id=session_id,
                                            pdf_page_number=page_num + 1
                                        ).first()

                                        if page_material:
                                            # 存储相对路径（相对于项目根目录）
                                            relative_path = os.path.relpath(img_path, app.root_path)
                                            page_material.file_path = relative_path
                                            page_material.status = '已上传'  # 统一状态：拆分完成后等待翻译
                                            page_material.processing_step = 'split_completed'
                                            page_material.processing_progress = 100  # 拆分完成
                                            db.session.commit()

                                            # 推送WebSocket更新，通知前端拆分完成
                                            if WEBSOCKET_ENABLED:
                                                emit_material_updated(
                                                    client_id,
                                                    material_id=page_material.id,
                                                    status=page_material.status,
                                                    processing_step=page_material.processing_step,
                                                    processing_progress=page_material.processing_progress,
                                                    file_path=page_material.file_path
                                                )

                                        log_message(f"✓ 第 {page_num + 1} 页已拆分", "SUCCESS")

                                    doc.close()
                                    log_message(f"✓ PDF拆分完成: {total_pages} 页，等待用户手动开始翻译", "SUCCESS")

                            except Exception as e:
                                log_message(f"PDF处理异常: {str(e)}", "ERROR")

                        # 启动后台任务
                        bg_thread = threading.Thread(
                            target=process_pdf_async,
                            args=(file_path, pdf_session_id, client_id),
                            daemon=True
                        )
                        bg_thread.start()
                        log_message(f"✓ 后台任务已启动", "SUCCESS")

                    except Exception as e:
                        log_message(f"PDF处理失败: {str(e)}", "ERROR")
                        db.session.rollback()
                        # 失败时创建普通记录
                        material = Material(
                            name=file.filename,
                            type=file_type,
                            original_filename=file.filename,
                            file_path=file_path,
                            status='已上传',
                            client_id=client_id
                        )
                        db.session.add(material)
                        uploaded_materials.append(material)
                else:
                    # 非PDF文件或PDF库不可用，正常处理
                    # 如果是图片，加强压缩
                    if file_type == 'image':
                        try:
                            from PIL import Image
                            img = Image.open(file_path)

                            log_message(f"原始图片尺寸: {img.width}x{img.height}px", "DEBUG")

                            # 限制分辨率到3000px（降低以提高稳定性）
                            if max(img.width, img.height) > 3000:
                                scale = 2800 / max(img.width, img.height)  # 目标2800px
                                new_width = int(img.width * scale)
                                new_height = int(img.height * scale)
                                img = img.resize((new_width, new_height), Image.Resampling.LANCZOS)
                                log_message(f"图片已缩放到: {new_width}x{new_height}px", "INFO")

                            # 转换为RGB（如果是RGBA）
                            if img.mode == 'RGBA':
                                img = img.convert('RGB')

                            # 检查文件大小（降低到2MB）
                            file_size = os.path.getsize(file_path)
                            max_size = 2 * 1024 * 1024  # 降低到2MB

                            # 无论什么情况都转换并压缩
                            # ⭐ 修复：避免jpg_path和file_path相同导致文件被删除
                            base_path = file_path.rsplit('.', 1)[0]
                            original_ext = file_path.rsplit('.', 1)[1] if '.' in file_path else ''

                            # 如果原文件已经是jpg，使用临时文件名避免覆盖
                            if original_ext.lower() in ['jpg', 'jpeg']:
                                jpg_path = base_path + '_compressed.jpg'
                            else:
                                jpg_path = base_path + '.jpg'

                            if file_size > max_size:
                                # 需要压缩：二分查找最佳质量
                                log_message(f"图片过大 ({file_size / 1024 / 1024:.2f}MB)，开始压缩", "INFO")
                                low, high = 10, 85  # 降低质量上限
                                best_quality = low

                                while low <= high:
                                    mid = (low + high) // 2
                                    img.save(jpg_path, 'JPEG', quality=mid, optimize=True)
                                    current_size = os.path.getsize(jpg_path)

                                    if current_size <= max_size:
                                        best_quality = mid
                                        low = mid + 1
                                    else:
                                        high = mid - 1

                                img.save(jpg_path, 'JPEG', quality=best_quality, optimize=True)
                                final_size = os.path.getsize(jpg_path)

                                if final_size <= max_size:
                                    # ⭐ 安全删除：确保不是同一个文件
                                    if file_path != jpg_path and os.path.exists(file_path):
                                        os.remove(file_path)
                                    file_path = jpg_path
                                    log_message(f"✓ 压缩完成: {final_size / 1024 / 1024:.2f}MB (质量: {best_quality})", "SUCCESS")
                                else:
                                    if os.path.exists(jpg_path) and jpg_path != file_path:
                                        os.remove(jpg_path)
                                    raise Exception(f"图片压缩失败，仍超过2MB限制")
                            else:
                                # 文件较小，但仍压缩到合理质量
                                img.save(jpg_path, 'JPEG', quality=75, optimize=True)
                                # ⭐ 安全删除：确保不是同一个文件
                                if file_path != jpg_path and os.path.exists(file_path):
                                    os.remove(file_path)
                                file_path = jpg_path
                                final_size = os.path.getsize(jpg_path)
                                log_message(f"✓ 压缩完成: {final_size / 1024 / 1024:.2f}MB", "SUCCESS")

                        except Exception as img_error:
                            log_message(f"图片处理失败: {str(img_error)}", "WARNING")

                    material = Material(
                        name=file.filename,
                        type=file_type,
                        original_filename=file.filename,
                        file_path=file_path,
                        status='已上传',  # ✅ 改为'已上传'，等待用户手动开始翻译
                        client_id=client_id,
                        processing_step='uploaded',
                        processing_progress=0  # ✅ 改为0，表示未开始
                    )
                    db.session.add(material)
                    uploaded_materials.append(material)

        db.session.commit()

        # 使材料列表缓存失效
        invalidate_materials_cache(client_id)

        # ❌ 不在上传时自动翻译，等待前端调用 start_translation
        # 上传时只设置状态为 '处理中'，翻译在 start_translation API 中进行

        log_message(f"成功上传 {len(uploaded_materials)} 个文件", "SUCCESS")
        
        return jsonify({
            'success': True,
            'message': f'成功上传 {len(uploaded_materials)} 个文件',
            'materials': [material.to_dict() for material in uploaded_materials]
        })
        
    except Exception as e:
        db.session.rollback()
        log_message(f"文件上传失败: {str(e)}", "ERROR")
        return jsonify({'success': False, 'error': '文件上传失败'}), 500

@app.route('/api/clients/<client_id>/materials/urls', methods=['POST'])
@jwt_required()
def upload_urls(client_id):
    try:
        user_id = get_jwt_identity()
        client = Client.query.filter_by(id=client_id, user_id=user_id).first()
        if not client:
            return jsonify({'success': False, 'error': '客户不存在'}), 404
        
        data = request.get_json()
        if not data or not data.get('urls'):
            return jsonify({'success': False, 'error': '请提供网页URL'}), 400
        
        urls = data['urls']
        uploaded_materials = []
        
        for url in urls:
            if url.strip():
                # 获取网页标题
                title = url.strip()  # 默认使用URL
                try:
                    response = requests.get(url.strip(), timeout=10, headers={
                        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
                    })
                    if response.status_code == 200:
                        soup = BeautifulSoup(response.content, 'html.parser')
                        if soup.title and soup.title.string:
                            title = soup.title.string.strip().replace('\n', ' ')[:100]
                except Exception as e:
                    log_message(f"获取网页标题失败: {url} - {str(e)}", "WARNING")
                
                material = Material(
                    name=title,  # 使用网页标题
                    type='webpage',
                    url=url.strip(),
                    status='已添加',
                    client_id=client_id
                )
                db.session.add(material)
                uploaded_materials.append(material)
        
        db.session.commit()

        # 使材料列表缓存失效
        invalidate_materials_cache(client_id)

        # ✅ 网页自动翻译 - 异步处理
        material_ids = [m.id for m in uploaded_materials]
        log_message(f"网页添加成功，启动自动翻译任务: {len(material_ids)} 个网页", "INFO")

        import threading

        def auto_translate_webpages():
            """后台自动翻译网页"""
            with app.app_context():
                for mat_id in material_ids:
                    try:
                        material = db.session.get(Material, mat_id)
                        if not material:
                            continue

                        log_message(f"开始自动翻译网页: {material.name}", "INFO")

                        # 更新状态为翻译中
                        material.status = MaterialStatus.TRANSLATING
                        db.session.commit()

                        # WebSocket推送
                        if WEBSOCKET_ENABLED:
                            emit_translation_started(client_id, material.id, f"开始翻译网页 {material.name}")

                        try:
                            # 1. 生成原始网页PDF
                            log_message(f"生成原始网页PDF: {material.name}", "INFO")
                            original_pdf_path, original_pdf_filename = _capture_original_webpage_pdf(material.url)
                            material.original_pdf_path = original_pdf_filename

                            # 2. 生成Google翻译PDF
                            log_message(f"生成翻译网页PDF: {material.name}", "INFO")
                            pdf_path, pdf_filename = _capture_google_translated_pdf(material.url)

                            # 更新状态为翻译完成
                            update_material_status(
                                material,
                                MaterialStatus.TRANSLATED,
                                translated_image_path=pdf_filename,
                                translation_error=None,
                                processing_progress=100
                            )

                            log_message(f"网页自动翻译完成: {material.name}", "SUCCESS")

                        except Exception as e:
                            update_material_status(
                                material,
                                MaterialStatus.FAILED,
                                translation_error=str(e)
                            )
                            log_message(f"网页自动翻译失败: {material.name} - {str(e)}", "ERROR")
                            import traceback
                            traceback.print_exc()

                    except Exception as e:
                        log_message(f"网页翻译异常: {str(e)}", "ERROR")
                        import traceback
                        traceback.print_exc()

        # 启动后台翻译线程
        thread = threading.Thread(target=auto_translate_webpages)
        thread.daemon = True
        thread.start()

        return jsonify({
            'success': True,
            'message': f'成功添加 {len(uploaded_materials)} 个网页，正在自动翻译...',
            'materials': [material.to_dict() for material in uploaded_materials]
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': '网页添加失败'}), 500

@app.route('/api/materials/<material_id>', methods=['GET'])
@jwt_required()
def get_material(material_id):
    """获取单个材料的详细信息"""
    try:
        user_id = get_jwt_identity()

        # 通过material找到client，验证用户权限
        material = Material.query.join(Client).filter(
            Material.id == material_id,
            Client.user_id == user_id
        ).first()

        if not material:
            return jsonify({'success': False, 'error': '材料不存在或无权限'}), 404

        # 返回材料的完整信息
        return jsonify({
            'success': True,
            'material': material.to_dict()
        })
    except Exception as e:
        log_message(f"获取材料详情失败: {str(e)}", "ERROR")
        return jsonify({'success': False, 'error': '获取材料详情失败'}), 500

@app.route('/api/materials/<material_id>', methods=['DELETE'])
@jwt_required()
def delete_material(material_id):
    """删除材料"""
    try:
        user_id = get_jwt_identity()

        # 通过material找到client，验证用户权限
        material = Material.query.join(Client).filter(
            Material.id == material_id,
            Client.user_id == user_id
        ).first()

        if not material:
            return jsonify({'success': False, 'error': '材料不存在或无权限'}), 404
        
        # 保存client_id以便后续使用
        client_id = material.client_id
        material_name = material.name
        
        # 删除关联的文件
        if material.file_path and os.path.exists(material.file_path):
            try:
                os.remove(material.file_path)
                log_message(f"删除文件: {material.file_path}", "INFO")
            except Exception as e:
                log_message(f"删除文件失败: {material.file_path} - {str(e)}", "WARNING")
        
        # 删除数据库记录
        db.session.delete(material)
        db.session.commit()
        
        # 使材料列表缓存失效
        invalidate_materials_cache(client_id)
        
        log_message(f"材料删除成功: {material_name}", "SUCCESS")
        
        return jsonify({'success': True, 'message': f'材料 {material_name} 删除成功'})
    except Exception as e:
        db.session.rollback()
        log_message(f"删除材料失败: {str(e)}", "ERROR")
        return jsonify({'success': False, 'error': '删除材料失败'}), 500

@app.route('/api/clients/<client_id>/materials/translate', methods=['POST'])
@jwt_required()
def start_translation(client_id):
    """开始翻译客户的材料（异步处理）

    请求体（可选）:
    {
        "material_ids": ["id1", "id2"]  // 如果提供，只翻译指定的材料；否则翻译所有材料
    }
    """
    try:
        user_id = get_jwt_identity()
        client = Client.query.filter_by(id=client_id, user_id=user_id).first()
        if not client:
            return jsonify({'success': False, 'error': '客户不存在'}), 404

        # 🔧 修复：支持只翻译指定的材料
        # 使用silent=True避免Content-Type错误
        data = request.get_json(silent=True) or {}
        requested_material_ids = data.get('material_ids', [])

        if requested_material_ids:
            # 只翻译指定的材料
            log_message(f"收到翻译请求，指定材料ID: {requested_material_ids}", "INFO")
            materials = Material.query.filter(
                Material.client_id == client_id,
                Material.id.in_(requested_material_ids),
                Material.type.in_(['image', 'webpage'])
            ).all()
        else:
            # 翻译所有材料（原有行为）
            log_message(f"收到翻译请求，翻译所有材料", "INFO")
            materials = Material.query.filter(
                Material.client_id == client_id,
                Material.type.in_(['image', 'webpage'])
            ).all()

        # 筛选需要翻译的材料（ID列表，避免在异步中使用对象）
        material_ids_to_translate = [m.id for m in materials if m.status in ['已上传', '已添加', '处理中']]
        
        log_message(f"找到 {len(materials)} 个材料，其中 {len(material_ids_to_translate)} 个需要翻译", "INFO")
        
        if not material_ids_to_translate:
            return jsonify({
                'success': True,
                'message': '没有需要翻译的材料',
                'translated_count': 0,
                'failed_count': 0,
                'translated_materials': []
            })
        
        # ✅ 使用普通线程异步翻译（gevent会自动处理）
        import threading
        
        def translate_one_material(material_id):
            """翻译单个材料"""
            print(f"[TRANSLATE] 开始翻译材料: {material_id}", flush=True)
            with app.app_context():
                try:
                    # ✅ 检查翻译锁，防止重复翻译
                    print(f"[TRANSLATE] 检查翻译锁: {material_id}", flush=True)
                    is_locked, locked_material = check_translation_lock(material_id)
                    if is_locked:
                        print(f"[TRANSLATE] 材料正在翻译中，跳过: {material_id}", flush=True)
                        log_message(f"材料正在翻译中，跳过: {material_id}", "WARN")
                        return {'success': False, 'error': '该材料正在翻译中', 'skipped': True}

                    print(f"[TRANSLATE] 查询材料: {material_id}", flush=True)
                    material = db.session.get(Material, material_id)
                    if not material:
                        print(f"[TRANSLATE] 材料不存在: {material_id}", flush=True)
                        return {'success': False, 'error': '材料不存在'}

                    print(f"[TRANSLATE] 材料名称: {material.name}, 类型: {material.type}, 状态: {material.status}", flush=True)
                    
                    # 网页类型的特殊处理
                    if material.type == 'webpage':
                        log_message(f"开始网页翻译: {material.name}", "INFO")
                        
                        # ✅ WebSocket 推送：翻译开始
                        if WEBSOCKET_ENABLED:
                            emit_translation_started(client_id, material.id, f"开始翻译网页 {material.name}")
                        
                        try:
                            # 1. 先生成原始网页的PDF
                            log_message(f"生成原始网页PDF: {material.name}", "INFO")
                            original_pdf_path, original_pdf_filename = _capture_original_webpage_pdf(material.url)
                            material.original_pdf_path = original_pdf_filename
                            
                            # 2. 生成Google翻译的PDF
                            log_message(f"生成翻译网页PDF: {material.name}", "INFO")
                            pdf_path, pdf_filename = _capture_google_translated_pdf(material.url)

                            # ✅ 使用统一函数更新状态（会自动推送WebSocket）
                            update_material_status(
                                material,
                                MaterialStatus.TRANSLATED,
                                translated_image_path=pdf_filename,
                                translation_error=None,
                                processing_progress=100
                            )

                            log_message(f"网页翻译完成: {material.name}", "SUCCESS")

                            return {'success': True}
                            
                        except Exception as e:
                            # ✅ 使用统一函数更新状态（会自动推送WebSocket）
                            update_material_status(
                                material,
                                MaterialStatus.FAILED,
                                translation_error=str(e)
                            )
                            log_message(f"网页翻译失败: {material.name} - {str(e)}", "ERROR")

                            return {'success': False, 'error': str(e)}
                    
                    # 图片翻译（百度API）
                    print(f"[TRANSLATE] 开始百度翻译: {material.name}", flush=True)
                    log_message(f"开始百度翻译: {material.name}", "INFO")
                    
                    # ✅ WebSocket 推送：翻译开始
                    if WEBSOCKET_ENABLED:
                        print(f"[TRANSLATE] 发送翻译开始事件", flush=True)
                        emit_translation_started(client_id, material.id, f"开始翻译 {material.name}")

                    try:
                        print(f"[TRANSLATE] 调用 translate_image_reference: {material.file_path}", flush=True)
                        # 调用百度翻译
                        result = translate_image_reference(
                            image_path=material.file_path,
                            source_lang='zh',
                            target_lang='en'
                        )
                        print(f"[TRANSLATE] 百度API返回，结果长度: {len(str(result))}", flush=True)

                        # 检查API错误
                        error_code = result.get('error_code')
                        if error_code and error_code not in [0, '0', None]:
                            error_msg = result.get('error_msg', '翻译失败')
                            log_message(f"百度API错误: {material.name} - {error_msg}", "ERROR")
                            # ✅ 使用统一函数更新状态（会自动推送WebSocket）
                            update_material_status(
                                material,
                                MaterialStatus.FAILED,
                                translation_error=error_msg
                            )

                            return {'success': False, 'error': error_msg}

                        # 解析regions数据
                        data = result.get('data', {})
                        content = data.get('content', [])

                        if not content:
                            log_message(f"百度翻译未识别到文字: {material.name}", "WARN")
                            # ✅ 使用统一函数更新状态（会自动推送WebSocket）
                            update_material_status(
                                material,
                                MaterialStatus.FAILED,
                                translation_error='未识别到文字区域'
                            )

                            return {'success': False, 'error': '未识别到文字区域'}

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

                        # 构建完整的翻译数据结构
                        translation_data = {
                            'regions': regions,
                            'sourceLang': data.get('from', 'zh'),
                            'targetLang': data.get('to', 'en'),
                            'statistics': {
                                'totalRegions': len(regions),
                                'totalSrcChars': sum(len(r['src']) for r in regions),
                                'totalDstChars': sum(len(r['dst']) for r in regions),
                                'translationRatio': sum(len(r['dst']) for r in regions) / sum(len(r['src']) for r in regions) if sum(len(r['src']) for r in regions) > 0 else 1
                            }
                        }

                        # 保存翻译数据
                        # ✅ 使用统一函数更新状态（会自动推送WebSocket）
                        update_material_status(
                            material,
                            MaterialStatus.TRANSLATED,
                            translation_text_info=translation_data,
                            translation_error=None,
                            processing_step=ProcessingStep.TRANSLATED.value,  # 🔧 修复：设置processing_step
                            processing_progress=100
                        )

                        log_message(f"百度翻译完成: {material.name}, 识别到 {len(regions)} 个区域", "SUCCESS")

                        # 如果启用了实体识别，自动触发实体识别
                        if material.entity_recognition_enabled:
                            log_message(f"检测到启用了实体识别，开始实体识别: {material.name}", "INFO")
                            try:
                                # 更新状态为实体识别中
                                material.processing_step = ProcessingStep.ENTITY_RECOGNIZING.value
                                material.processing_progress = 0
                                db.session.commit()

                                # 调用实体识别服务
                                from entity_recognition_service import EntityRecognitionService
                                entity_service = EntityRecognitionService()
                                entity_result = entity_service.recognize_entities(translation_data)

                                if entity_result.get('success'):
                                    # 保存实体识别结果
                                    material.entity_recognition_result = json.dumps(entity_result, ensure_ascii=False)
                                    material.processing_step = ProcessingStep.ENTITY_PENDING_CONFIRM.value
                                    material.processing_progress = 100
                                    material.entity_recognition_error = None

                                    # 保存日志
                                    entity_service.save_entity_recognition_log(
                                        material_id=material.id,
                                        material_name=material.name,
                                        ocr_result=translation_data,
                                        entity_result=entity_result
                                    )

                                    db.session.commit()

                                    log_message(f"实体识别完成: {material.name}, 识别到 {entity_result.get('total_entities', 0)} 个实体，等待用户确认", "INFO")
                                else:
                                    # 识别失败，记录错误但不阻止流程
                                    material.entity_recognition_error = entity_result.get('error')
                                    material.processing_step = ProcessingStep.TRANSLATED.value
                                    material.entity_recognition_triggered = True  # 标记已尝试过
                                    db.session.commit()
                                    log_message(f"实体识别失败: {material.name}, 错误: {entity_result.get('error')}", "WARN")

                                    # 🔧 推送WebSocket更新，告知前端实体识别失败
                                    if WEBSOCKET_ENABLED:
                                        emit_material_updated(
                                            material.client_id,
                                            material.id,
                                            processing_step=material.processing_step,
                                            material=material.to_dict(),
                                            entity_recognition_error=entity_result.get('error')
                                        )

                            except Exception as e:
                                # 实体识别异常，记录错误但不阻止流程
                                log_message(f"实体识别异常: {material.name} - {str(e)}", "ERROR")
                                import traceback
                                traceback.print_exc()
                                material.entity_recognition_error = str(e)
                                material.processing_step = ProcessingStep.TRANSLATED.value
                                material.entity_recognition_triggered = True  # 标记已尝试过
                                db.session.commit()

                                # 🔧 推送WebSocket更新，告知前端实体识别失败
                                if WEBSOCKET_ENABLED:
                                    emit_material_updated(
                                        material.client_id,
                                        material.id,
                                        processing_step=material.processing_step,
                                        material=material.to_dict(),
                                        entity_recognition_error=str(e)
                                    )

                        return {'success': True}

                    except Exception as e:
                        log_message(f"百度翻译异常: {material.name} - {str(e)}", "ERROR")
                        # ✅ 使用统一函数更新状态（会自动推送WebSocket）
                        update_material_status(
                            material,
                            MaterialStatus.FAILED,
                            translation_error=str(e)
                        )

                        return {'success': False, 'error': str(e)}
                        
                except Exception as e:
                    log_message(f"翻译材料异常: {material_id} - {str(e)}", "ERROR")
                    return {'success': False, 'error': str(e)}
        
        def translate_all_materials_async():
            """异步翻译所有材料"""
            print(f"[ASYNC] ========== 开始异步翻译 {len(material_ids_to_translate)} 个材料 ==========", flush=True)
            log_message(f"开始异步翻译 {len(material_ids_to_translate)} 个材料", "INFO")

            # 直接顺序执行（gevent会自动并发处理）
            translated_count = 0
            failed_count = 0
            skipped_count = 0

            for material_id in material_ids_to_translate:
                print(f"[ASYNC] 翻译材料: ID {material_id}", flush=True)
                log_message(f"翻译材料: ID {material_id}", "INFO")
                result = translate_one_material(material_id)
                print(f"[ASYNC] 任务完成，结果: {result}", flush=True)
                if result.get('success'):
                    translated_count += 1
                elif result.get('skipped'):
                    skipped_count += 1
                else:
                    failed_count += 1

            status_msg = f"成功 {translated_count} 个，失败 {failed_count} 个"
            if skipped_count > 0:
                status_msg += f"，跳过 {skipped_count} 个（正在翻译中）"
            print(f"[ASYNC] 所有材料翻译完成：{status_msg}", flush=True)
            log_message(f"所有材料翻译完成：{status_msg}", "SUCCESS")
            
            # ✅ WebSocket 推送：所有翻译完成
            if WEBSOCKET_ENABLED:
                emit_translation_completed(client_id, f'翻译完成：{status_msg}', success_count=translated_count, failed_count=failed_count)
        
        # 使用普通线程启动异步任务（gevent会自动处理）
        print(f"[MAIN] 准备启动异步翻译任务，材料数: {len(material_ids_to_translate)}", flush=True)
        thread = threading.Thread(target=translate_all_materials_async)
        thread.daemon = True
        thread.start()
        print(f"[MAIN] 已启动后台线程，异步任务正在执行", flush=True)
        log_message(f"✓ 已提交 {len(material_ids_to_translate)} 个材料到翻译队列", "INFO")
        
        # ✅ 立即返回，不等待翻译完成
        return jsonify({
            'success': True,
            'message': f'翻译完成：成功 0 个，失败 0 个',
            'translated_count': 0,
            'failed_count': 0,
            'translated_materials': []
        })
        
    except Exception as e:
        db.session.rollback()
        log_message(f"启动翻译失败: {str(e)}", "ERROR")
        return jsonify({'success': False, 'error': '启动翻译失败'}), 500

@app.route('/api/materials/<material_id>/retry-latex', methods=['POST'])
@jwt_required()
def retry_latex_translation(material_id):
    """重试LaTeX翻译"""
    try:
        user_id = get_jwt_identity()
        
        # 通过material找到client，验证用户权限
        material = Material.query.join(Client).filter(
            Material.id == material_id,
            Client.user_id == user_id
        ).first()
        
        if not material:
            return jsonify({'success': False, 'error': '材料不存在或无权限'}), 404
        
        if material.type != 'image' and material.type != 'pdf':
            return jsonify({'success': False, 'error': '只有图片或PDF材料支持LaTeX翻译'}), 400
        
        log_message(f"开始重试LaTeX翻译: {material.name}", "INFO")
        
        # 生成输出文件名
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_base_name = f"poster_output/latex_retry_{material.id}_{timestamp}"
        
        # 执行LaTeX翻译，包含重试逻辑
        max_retries = 3
        retry_delay = 2  # 秒
        
        for attempt in range(max_retries):
            try:
                log_message(f"LaTeX翻译尝试 {attempt + 1}/{max_retries}", "INFO")
                
                latex_result = poster_translator.translate_poster_complete(
                    image_path=material.file_path,
                    output_base_name=output_base_name,
                    clean_aux=True
                )
                
                if latex_result['success']:
                    # 更新材料的LaTeX翻译结果
                    material.latex_translation_result = json.dumps({
                        'tex_file': latex_result.get('tex_file'),
                        'pdf_file': latex_result.get('pdf_file'),
                        'latex_code_length': latex_result.get('latex_code_length', 0)
                    }, ensure_ascii=False)
                    material.latex_translation_error = None
                    
                    # 如果之前完全失败，现在更新状态为翻译完成
                    if material.status == '翻译失败':
                        material.status = '翻译完成'
                    
                    db.session.commit()
                    
                    log_message(f"LaTeX翻译重试成功: {material.name}", "SUCCESS")
                    
                    return jsonify({
                        'success': True,
                        'message': 'LaTeX翻译重试成功',
                        'material': material.to_dict(),
                        'latex_result': {
                            'tex_file': latex_result.get('tex_file'),
                            'pdf_file': latex_result.get('pdf_file')
                        }
                    })
                    
                else:
                    # 如果不是最后一次尝试，等待后重试
                    if attempt < max_retries - 1:
                        log_message(f"LaTeX翻译失败，{retry_delay}秒后重试: {latex_result.get('error')}", "WARNING")
                        time.sleep(retry_delay)
                    else:
                        # 最后一次尝试失败
                        raise Exception(latex_result.get('error', 'LaTeX翻译失败'))
                        
            except Exception as e:
                if attempt < max_retries - 1:
                    log_message(f"LaTeX翻译异常，{retry_delay}秒后重试: {str(e)}", "WARNING")
                    time.sleep(retry_delay)
                else:
                    # 所有重试都失败了
                    material.latex_translation_error = str(e)
                    db.session.commit()
                    log_message(f"LaTeX翻译重试失败: {material.name} - {str(e)}", "ERROR")
                    
                    return jsonify({
                        'success': False,
                        'error': f'LaTeX翻译失败: {str(e)}',
                        'material': material.to_dict()
                    }), 500
        
    except Exception as e:
        db.session.rollback()
        log_message(f"LaTeX翻译重试异常: {str(e)}", "ERROR")
        return jsonify({'success': False, 'error': f'重试失败: {str(e)}'}), 500

@app.route('/api/clients/<client_id>/materials/cancel', methods=['POST'])
@jwt_required()
def cancel_upload(client_id):
    """取消上传，删除最近上传的材料"""
    try:
        user_id = get_jwt_identity()
        client = Client.query.filter_by(id=client_id, user_id=user_id).first()
        if not client:
            return jsonify({'success': False, 'error': '客户不存在'}), 404
        
        data = request.get_json()
        material_ids = data.get('material_ids', [])
        
        if not material_ids:
            return jsonify({'success': False, 'error': '没有指定要删除的材料'}), 400
        
        deleted_count = 0
        
        for material_id in material_ids:
            material = Material.query.filter_by(id=material_id, client_id=client_id).first()
            if material:
                # 删除关联文件
                if material.file_path and os.path.exists(material.file_path):
                    try:
                        os.remove(material.file_path)
                        log_message(f"删除文件: {material.file_path}", "INFO")
                    except Exception as e:
                        log_message(f"删除文件失败: {material.file_path} - {str(e)}", "WARNING")
                
                # 删除数据库记录
                db.session.delete(material)
                deleted_count += 1
        
        db.session.commit()
        
        log_message(f"取消上传，删除了 {deleted_count} 个材料", "SUCCESS")
        
        return jsonify({
            'success': True,
            'message': f'已删除 {deleted_count} 个材料',
            'deleted_count': deleted_count
        })
        
    except Exception as e:
        db.session.rollback()
        log_message(f"取消上传失败: {str(e)}", "ERROR")
        return jsonify({'success': False, 'error': '取消上传失败'}), 500

# ========== 文件下载端点 ========== 

@app.route('/download/image/<path:filename>')
def download_image(filename):
    """下载翻译后的图片或编辑后的图片"""
    try:
        # 支持完整路径和文件名
        if '/' in filename:
            # 如果包含路径，尝试多个可能的位置
            possible_paths = [
                filename,  # 直接使用提供的路径
                os.path.join('uploads', filename),  # uploads目录
                os.path.join(app.root_path, 'uploads', filename),  # 绝对路径的uploads目录
                os.path.join('image_translation_output', filename)  # 原始翻译输出目录
            ]
        else:
            # 否则在多个目录中查找
            possible_paths = [
                os.path.join('image_translation_output', filename),
                os.path.join('uploads', 'edited', filename),
                os.path.join(app.root_path, 'uploads', 'edited', filename)
            ]

        # 尝试找到文件
        for path in possible_paths:
            if os.path.exists(path):
                log_message(f"找到图片文件: {path}", "INFO")
                return send_file(path)

        # 文件未找到
        log_message(f"图片文件不存在，尝试过的路径: {possible_paths}", "ERROR")
        return jsonify({'error': '文件不存在'}), 404
    except Exception as e:
        log_message(f"下载图片失败: {str(e)}", "ERROR")
        return jsonify({'error': '下载失败'}), 500

def get_file_type(filename):
    """根据文件名获取文件类型"""
    ext = filename.split('.').pop().lower()
    if ext in ['pdf']:
        return 'pdf'
    elif ext in ['jpg', 'jpeg', 'png', 'gif', 'bmp', 'tiff']:
        return 'image'
    elif ext in ['doc', 'docx', 'txt', 'rtf']:
        return 'document'
    else:
        return 'document'

# ========== 预览/下载功能 ==========

@app.route('/preview/translated/<path:filename>')
def preview_translated_file(filename):
    """预览翻译后的PDF文件"""
    try:
        log_message(f"预览PDF请求 - 原始filename参数: {filename}", "INFO")

        # Flask会自动解码URL，所以filename已经是解码后的
        file_path = os.path.join('translated_snapshot', filename)
        log_message(f"完整文件路径: {file_path}", "INFO")
        log_message(f"文件是否存在: {os.path.exists(file_path)}", "INFO")

        if not os.path.exists(file_path):
            log_message(f"文件不存在: {file_path}", "ERROR")
            # 列出目录中的文件用于调试
            if os.path.exists('translated_snapshot'):
                files = os.listdir('translated_snapshot')
                log_message(f"translated_snapshot目录中的文件: {files}", "INFO")
            return jsonify({'error': '文件不存在', 'path': file_path}), 404

        log_message(f"发送文件: {file_path}", "SUCCESS")
        response = send_file(
            file_path,
            as_attachment=False,
            mimetype='application/pdf',
            conditional=True
        )

        # 允许 iframe 和跨域
        # 使用RFC 2231格式处理中文文件名
        encoded_filename = quote(filename.encode('utf-8'))
        response.headers['Content-Disposition'] = f"inline; filename*=UTF-8''{encoded_filename}"
        response.headers['Cache-Control'] = 'public, max-age=3600'
        response.headers['Access-Control-Allow-Origin'] = '*'
        response.headers['Access-Control-Allow-Methods'] = 'GET, OPTIONS'
        response.headers['Access-Control-Allow-Headers'] = '*'

        # 移除可能阻止iframe的安全头
        for h in ['X-Frame-Options', 'Content-Security-Policy', 'X-Content-Type-Options']:
            if h in response.headers:
                del response.headers[h]

        return response
    except Exception as e:
        log_message(f"预览PDF失败: {str(e)}", "ERROR")
        import traceback
        log_message(f"错误堆栈: {traceback.format_exc()}", "ERROR")
        return jsonify({'error': str(e)}), 500


# ========== 系统功能 ========== 

@app.route('/')
def index():
    return jsonify({
        'message': '智能文书翻译平台 - 完整版后端API',
        'version': '4.0',
        'features': {
            'user_authentication': True,
            'client_management': True,
            'material_management': True,
            'translation_services': True,
            'poster_translation': OPENAI_AVAILABLE,
            'image_translation': True,
            'webpage_translation': True,
            'gpt_translation': OPENAI_AVAILABLE,
            'google_translation': SELENIUM_AVAILABLE
        },
        'dependencies': {
            'openai': OPENAI_AVAILABLE,
            'selenium': SELENIUM_AVAILABLE,
            'beautifulsoup4': True,
            'requests': True
        }
    })

@app.route('/health')
def health():
    try:
        from sqlalchemy import text
        db.session.execute(text('SELECT 1'))
        return jsonify({
            'status': 'healthy',
            'timestamp': datetime.now().isoformat(),
            'database': 'connected',
            'version': '4.0',
            'translation_ready': OPENAI_AVAILABLE or SELENIUM_AVAILABLE
        })
    except Exception as e:
        return jsonify({
            'status': 'unhealthy',
            'timestamp': datetime.now().isoformat(),
            'error': str(e)
        }), 500

# ========== 数据库初始化 ========== 

def init_database():
    with app.app_context():
        try:
            db.create_all()
            log_message("数据库初始化成功", "SUCCESS")
            
            if User.query.count() == 0:
                test_user = User(name="测试用户", email="test@example.com")
                test_user.set_password("password123")
                db.session.add(test_user)
                db.session.commit()
                log_message("已创建测试用户: test@example.com / password123", "SUCCESS")
        except Exception as e:
            log_message(f"数据库初始化失败: {str(e)}", "ERROR")

# ========== Phase 1: 新增的API端点 ========== 

@app.route('/api/clients/<client_id>', methods=['PUT'])
@jwt_required()
def update_client(client_id):
    """更新客户信息"""
    try:
        current_user_id = get_jwt_identity()
        
        # 查找客户
        client = Client.query.filter_by(id=client_id, user_id=current_user_id).first()
        if not client:
            return jsonify({
                'success': False,
                'error': '客户不存在'
            }), 404
        
        data = request.get_json()
        if not data:
            return jsonify({
                'success': False,
                'error': '请提供要更新的数据'
            }), 400
        
        # 更新字段（支持前端的驼峰命名）
        if 'name' in data:
            client.name = data['name']
        if 'case_type' in data:
            client.case_type = data['case_type']
        if 'caseType' in data:
            client.case_type = data['caseType']
        if 'case_date' in data:
            client.case_date = data['case_date']
        if 'caseDate' in data:
            client.case_date = data['caseDate']
        if 'phone' in data:
            client.phone = data['phone']
        if 'email' in data:
            client.email = data['email']
        if 'address' in data:
            client.address = data['address']
        if 'notes' in data:
            client.notes = data['notes']
        
        client.updated_at = datetime.utcnow()
        
        db.session.commit()
        log_message(f"客户信息更新成功: {client_id}")
        
        return jsonify({
            'success': True,
            'client': client.to_dict(),
            'message': '客户信息更新成功'
        })
        
    except Exception as e:
        log_message(f"更新客户信息失败: {str(e)}", "ERROR")
        db.session.rollback()
        return jsonify({
            'success': False,
            'error': '更新客户信息失败',
            'message': str(e)
        }), 500

@app.route('/api/clients/<client_id>/archive', methods=['PUT'])
@jwt_required()
def archive_client(client_id):
    """归档客户"""
    try:
        current_user_id = get_jwt_identity()
        
        # 查找客户
        client = Client.query.filter_by(id=client_id, user_id=current_user_id).first()
        if not client:
            return jsonify({
                'success': False,
                'error': '客户不存在'
            }), 404
        
        data = request.get_json()
        reason = data.get('reason', '用户手动归档')
        
        # 设置归档状态
        client.is_archived = True
        client.archived_at = datetime.utcnow()
        client.archived_reason = reason
        client.updated_at = datetime.utcnow()
        
        db.session.commit()
        log_message(f"客户归档成功: {client_id}")
        
        return jsonify({
            'success': True,
            'client': client.to_dict(),
            'message': '客户已归档'
        })
        
    except Exception as e:
        log_message(f"归档客户失败: {str(e)}", "ERROR")
        db.session.rollback()
        return jsonify({
            'success': False,
            'error': '归档客户失败',
            'message': str(e)
        }), 500

@app.route('/api/clients/<client_id>/unarchive', methods=['PUT'])
@jwt_required()
def unarchive_client(client_id):
    """取消归档客户"""
    try:
        current_user_id = get_jwt_identity()
        
        # 查找客户
        client = Client.query.filter_by(id=client_id, user_id=current_user_id).first()
        if not client:
            return jsonify({
                'success': False,
                'error': '客户不存在'
            }), 404
        
        # 取消归档状态
        client.is_archived = False
        client.archived_at = None
        client.archived_reason = None
        client.updated_at = datetime.utcnow()
        
        db.session.commit()
        log_message(f"客户取消归档成功: {client_id}")
        
        return jsonify({
            'success': True,
            'client': client.to_dict(),
            'message': '客户已取消归档'
        })
        
    except Exception as e:
        log_message(f"取消归档客户失败: {str(e)}", "ERROR")
        db.session.rollback()
        return jsonify({
            'success': False,
            'error': '取消归档客户失败',
            'message': str(e)
        }), 500

@app.route('/api/materials/<material_id>', methods=['PUT'])
@jwt_required()
def update_material(material_id):
    """更新材料状态"""
    try:
        current_user_id = get_jwt_identity()
        
        # 查找材料并验证权限
        material = Material.query.join(Client).filter(
            Material.id == material_id,
            Client.user_id == current_user_id
        ).first()
        
        if not material:
            return jsonify({
                'success': False,
                'error': '材料不存在'
            }), 404
        
        data = request.get_json()
        if not data:
            return jsonify({
                'success': False,
                'error': '请提供要更新的数据'
            }), 400
        
        # 更新字段
        if 'status' in data:
            material.status = data['status']
        if 'confirmed' in data:
            material.confirmed = data['confirmed']
        if 'selectedResult' in data:
            material.selected_result = data['selectedResult']
        if 'selectedTranslationType' in data:
            material.selected_translation_type = data['selectedTranslationType']
        if 'translationConfirmed' in data:
            material.translation_confirmed = data['translationConfirmed']
        
        material.updated_at = datetime.utcnow()
        
        db.session.commit()
        log_message(f"材料状态更新成功: {material_id}")
        
        return jsonify({
            'success': True,
            'material': material.to_dict(),
            'message': '材料状态更新成功'
        })
        
    except Exception as e:
        log_message(f"更新材料状态失败: {str(e)}", "ERROR")
        db.session.rollback()
        return jsonify({
            'success': False,
            'error': '更新材料状态失败',
            'message': str(e)
        }), 500

@app.route('/api/materials/<material_id>/confirm', methods=['POST'])
@jwt_required()
def confirm_material(material_id):
    """确认材料翻译结果"""
    try:
        current_user_id = get_jwt_identity()
        
        # 查找材料并验证权限
        material = Material.query.join(Client).filter(
            Material.id == material_id,
            Client.user_id == current_user_id
        ).first()
        
        if not material:
            return jsonify({
                'success': False,
                'error': '材料不存在'
            }), 404
        
        data = request.get_json()
        translation_type = data.get('translation_type') if data else None

        # 如果是PDF材料，确认整个PDF会话的所有页面
        if material.pdf_session_id:
            log_message(f"检测到PDF材料，将确认整个PDF会话: {material.pdf_session_id}", "INFO")

            # 查找同一PDF会话的所有页面
            pdf_pages = Material.query.filter_by(
                pdf_session_id=material.pdf_session_id
            ).all()

            confirmed_count = 0
            for page in pdf_pages:
                page.confirmed = True
                page.status = '已确认'
                page.updated_at = datetime.utcnow()
                confirmed_count += 1

            log_message(f"已确认PDF的 {confirmed_count} 个页面", "SUCCESS")
        else:
            # 非PDF材料，只确认当前材料
            material.confirmed = True
            material.status = '已确认'

            # 如果指定了翻译类型，设置选择的翻译类型（仅限图片材料）
            if translation_type and translation_type in ['api', 'latex'] and material.type == 'image':
                material.selected_translation_type = translation_type
                material.selected_result = translation_type

            material.updated_at = datetime.utcnow()
            log_message(f"材料翻译结果确认成功: {material_id}, 类型: {translation_type}", "SUCCESS")

        db.session.commit()
        
        return jsonify({
            'success': True,
            'material': material.to_dict(),
            'message': '翻译结果确认成功'
        })
        
    except Exception as e:
        log_message(f"确认材料翻译结果失败: {str(e)}", "ERROR")
        db.session.rollback()
        return jsonify({
            'success': False,
            'error': '确认翻译结果失败',
            'message': str(e)
        }), 500

@app.route('/api/materials/<material_id>/edit', methods=['POST'])
@jwt_required()
def edit_material_latex(material_id):
    """编辑材料的LaTeX内容"""
    try:
        current_user_id = get_jwt_identity()
        
        # 查找材料并验证权限
        material = Material.query.join(Client).filter(
            Material.id == material_id,
            Client.user_id == current_user_id
        ).first()
        
        if not material:
            return jsonify({
                'success': False,
                'error': '材料不存在'
            }), 404
        
        data = request.get_json()
        if not data or 'description' not in data:
            return jsonify({
                'success': False,
                'error': '请提供编辑描述'
            }), 400
        
        description = data['description']
        
        # 这里可以添加重新生成LaTeX的逻辑
        # 目前只记录编辑请求
        material.latex_translation_result = f"编辑请求: {description}"
        material.updated_at = datetime.utcnow()
        
        db.session.commit()
        log_message(f"LaTeX编辑请求已记录: {material_id}")
        
        return jsonify({
            'success': True,
            'material': material.to_dict(),
            'message': 'LaTeX编辑请求已提交'
        })
        
    except Exception as e:
        log_message(f"编辑LaTeX失败: {str(e)}", "ERROR")
        db.session.rollback()
        return jsonify({
            'success': False,
            'error': '编辑LaTeX失败',
            'message': str(e)
        }), 500

@app.route('/api/materials/<material_id>/select', methods=['POST'])
@jwt_required()
def select_translation_result(material_id):
    """选择翻译结果"""
    try:
        current_user_id = get_jwt_identity()
        
        # 查找材料并验证权限
        material = Material.query.join(Client).filter(
            Material.id == material_id,
            Client.user_id == current_user_id
        ).first()
        
        if not material:
            return jsonify({
                'success': False,
                'error': '材料不存在'
            }), 404
        
        data = request.get_json()
        if not data or 'resultType' not in data:
            return jsonify({
                'success': False,
                'error': '请指定要选择的翻译结果类型'
            }), 400
        
        result_type = data['resultType']
        if result_type not in ['api', 'latex']:
            return jsonify({
                'success': False,
                'error': '无效的翻译结果类型'
            }), 400
        
        # 设置选择的翻译类型
        material.selected_translation_type = result_type
        material.selected_result = result_type
        material.updated_at = datetime.utcnow()
        
        db.session.commit()
        log_message(f"翻译结果选择成功: {material_id}, 类型: {result_type}")
        
        return jsonify({
            'success': True,
            'material': material.to_dict(),
            'message': f'已选择{result_type}翻译结果'
        })
        
    except Exception as e:
        log_message(f"选择翻译结果失败: {str(e)}", "ERROR")
        db.session.rollback()
        return jsonify({
            'success': False,
            'error': '选择翻译结果失败',
            'message': str(e)
        }), 500

@app.route('/api/materials/<material_id>/unconfirm', methods=['POST'])
@jwt_required()
def unconfirm_material(material_id):
    """取消确认材料翻译结果"""
    try:
        log_message(f"开始取消确认材料: {material_id}", "INFO")
        current_user_id = get_jwt_identity()
        log_message(f"当前用户ID: {current_user_id}", "INFO")

        # 查找材料并验证权限
        material = Material.query.join(Client).filter(
            Material.id == material_id,
            Client.user_id == current_user_id
        ).first()

        if not material:
            return jsonify({
                'success': False,
                'error': '材料不存在'
            }), 404

        # 如果是PDF材料，取消确认整个PDF会话的所有页面
        if material.pdf_session_id:
            log_message(f"检测到PDF材料，将取消确认整个PDF会话: {material.pdf_session_id}", "INFO")

            # 查找同一PDF会话的所有页面
            pdf_pages = Material.query.filter_by(
                pdf_session_id=material.pdf_session_id
            ).all()

            unconfirmed_count = 0
            for page in pdf_pages:
                page.confirmed = False
                page.status = '翻译完成'
                page.updated_at = datetime.utcnow()
                unconfirmed_count += 1

            log_message(f"已取消确认PDF的 {unconfirmed_count} 个页面", "SUCCESS")
        else:
            # 非PDF材料，只取消确认当前材料
            material.confirmed = False
            material.status = '翻译完成'
            material.updated_at = datetime.utcnow()
            log_message(f"取消确认材料: {material_id}", "SUCCESS")

        # 注意：不要重置 edited_image_path 和 has_edited_version
        # 这些字段应该保持不变，因为编辑内容应该被保留

        db.session.commit()

        return jsonify({
            'success': True,
            'material': material.to_dict(),
            'message': '已取消确认'
        })

    except Exception as e:
        log_message(f"取消确认材料失败: {str(e)}", "ERROR")
        db.session.rollback()
        return jsonify({
            'success': False,
            'error': '取消确认失败',
            'message': str(e)
        }), 500

@app.route('/api/materials/<material_id>/save-edited-image', methods=['POST'])
@jwt_required()
def save_edited_image(material_id):
    """保存编辑后的图片"""
    try:
        log_message(f"保存编辑图片 - 材料ID: {material_id}", "INFO")

        user_id = get_jwt_identity()

        # 查找材料并验证权限
        material = Material.query.join(Client).filter(
            Material.id == material_id,
            Client.user_id == user_id
        ).first()

        if not material:
            return jsonify({
                'success': False,
                'error': '材料不存在或无权访问'
            }), 404

        # 获取上传的两个版本的图片
        # 1. 不带文字版本（用于预览）
        if 'edited_image' not in request.files:
            return jsonify({
                'success': False,
                'error': '未找到编辑后的图片（不带文字版本）'
            }), 400

        edited_image = request.files['edited_image']

        # 2. 带文字版本（用于导出）
        if 'final_image' not in request.files:
            return jsonify({
                'success': False,
                'error': '未找到最终图片（带文字版本）'
            }), 400

        final_image = request.files['final_image']

        if edited_image.filename == '' or final_image.filename == '':
            return jsonify({
                'success': False,
                'error': '未选择完整的文件'
            }), 400

        # 获取编辑的regions状态（可选）
        edited_regions = None
        if 'edited_regions' in request.form:
            try:
                edited_regions = request.form.get('edited_regions')
                log_message(f"接收到编辑regions数据", "INFO")
            except Exception as e:
                log_message(f"解析regions失败: {e}", "WARN")

        # 创建两个保存路径
        edited_dir = os.path.join(app.root_path, 'uploads', 'edited')
        final_dir = os.path.join(app.root_path, 'uploads', 'final')
        os.makedirs(edited_dir, exist_ok=True)
        os.makedirs(final_dir, exist_ok=True)

        # 生成唯一的文件名
        timestamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
        edited_filename = f"edited_{material.id}_{timestamp}.jpg"
        final_filename = f"final_{material.id}_{timestamp}.jpg"

        edited_file_path = os.path.join(edited_dir, edited_filename)
        final_file_path = os.path.join(final_dir, final_filename)

        # 保存两个版本的图片
        edited_image.save(edited_file_path)
        final_image.save(final_file_path)

        log_message(f"编辑图片已保存（不带文字）: {edited_file_path}", "INFO")
        log_message(f"最终图片已保存（带文字）: {final_file_path}", "SUCCESS")

        # 更新材料记录，保存两个版本的路径和regions
        material.edited_image_path = f"edited/{edited_filename}"
        material.final_image_path = f"final/{final_filename}"
        material.has_edited_version = True
        # 保存编辑图片时，自动将选择结果设为 'api'，以便导出时使用编辑后的图片
        material.selected_result = 'api'
        if edited_regions:
            material.edited_regions = edited_regions
        material.updated_at = datetime.utcnow()
        db.session.commit()

        return jsonify({
            'success': True,
            'message': '编辑图片保存成功',
            'edited_image_path': material.edited_image_path,
            'final_image_path': material.final_image_path,
            'material': material.to_dict()
        })

    except Exception as e:
        log_message(f"保存编辑图片失败: {str(e)}", "ERROR")
        db.session.rollback()
        return jsonify({
            'success': False,
            'error': '保存编辑图片失败',
            'message': str(e)
        }), 500

@app.route('/api/materials/<material_id>/save-regions', methods=['POST'])
@jwt_required()
def save_material_regions(material_id):
    """✅ 重构：只保存材料的regions数据，不保存图片文件"""
    try:
        log_message(f"保存regions数据 - 材料ID: {material_id}", "INFO")

        user_id = get_jwt_identity()
        data = request.get_json()

        # 查找材料并验证权限
        material = Material.query.join(Client).filter(
            Material.id == material_id,
            Client.user_id == user_id
        ).first()

        if not material:
            return jsonify({
                'success': False,
                'error': '材料不存在或无权访问'
            }), 404

        # 获取regions数据
        regions = data.get('regions', [])

        if not regions:
            log_message(f"警告：保存了空的regions数据", "WARN")

        # 保存regions数据到数据库
        material.edited_regions = json.dumps(regions, ensure_ascii=False)
        material.has_edited_version = True
        material.selected_result = 'api'  # 标记为使用编辑版本
        material.updated_at = datetime.utcnow()

        db.session.commit()

        log_message(f"✅ Regions保存成功: {len(regions)}个区域", "SUCCESS")

        # 使材料列表缓存失效
        invalidate_materials_cache(material.client_id)

        # 推送WebSocket更新（如果启用）
        if WEBSOCKET_ENABLED:
            emit_material_updated(
                material.client_id,
                material_id=material.id,
                edited_regions=regions,
                has_edited_version=True
            )

        return jsonify({
            'success': True,
            'message': f'成功保存{len(regions)}个编辑区域',
            'material': material.to_dict()
        })

    except Exception as e:
        log_message(f"保存regions失败: {str(e)}", "ERROR")
        db.session.rollback()
        return jsonify({
            'success': False,
            'error': '保存regions失败',
            'message': str(e)
        }), 500

@app.route('/api/materials/<material_id>/save-final-image', methods=['POST'])
@jwt_required()
def save_final_image(material_id):
    """保存前端生成的最终图片（用于导出）"""
    try:
        log_message(f"保存最终图片 - 材料ID: {material_id}", "INFO")

        user_id = get_jwt_identity()

        # 查找材料并验证权限
        material = Material.query.join(Client).filter(
            Material.id == material_id,
            Client.user_id == user_id
        ).first()

        if not material:
            return jsonify({
                'success': False,
                'error': '材料不存在或无权访问'
            }), 404

        # 获取上传的图片文件
        if 'final_image' not in request.files:
            return jsonify({
                'success': False,
                'error': '没有上传图片文件'
            }), 400

        file = request.files['final_image']
        if not file or file.filename == '':
            return jsonify({
                'success': False,
                'error': '文件名为空'
            }), 400

        # 生成文件名
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f"final_{material_id}_{timestamp}.jpg"

        # 保存到 uploads 目录
        upload_folder = os.path.join(app.root_path, 'uploads')
        os.makedirs(upload_folder, exist_ok=True)
        filepath = os.path.join(upload_folder, filename)

        file.save(filepath)
        log_message(f"最终图片已保存: {filepath}", "SUCCESS")

        # 更新数据库，保存相对路径
        relative_path = os.path.join('uploads', filename)
        material.final_image_path = relative_path
        material.has_edited_version = True
        material.updated_at = datetime.utcnow()

        db.session.commit()

        log_message(f"✅ 最终图片保存成功: {relative_path}", "SUCCESS")

        return jsonify({
            'success': True,
            'message': '最终图片保存成功',
            'final_image_path': relative_path
        })

    except Exception as e:
        log_message(f"保存最终图片失败: {str(e)}", "ERROR")
        db.session.rollback()
        return jsonify({
            'success': False,
            'error': '保存最终图片失败',
            'message': str(e)
        }), 500

@app.route('/api/ai-revise-text', methods=['POST'])
@jwt_required()
def ai_revise_text():
    """使用AI修改单个或多个文本框的内容"""
    try:
        data = request.get_json()
        texts = data.get('texts', [])  # 文本列表，支持单个或多个
        instruction = data.get('instruction', '')
        mode = data.get('mode', 'unified')  # unified, merge, individual

        if not texts or not instruction:
            return jsonify({
                'success': False,
                'error': '缺少必要参数'
            }), 400

        log_message(f"AI文本修改 - 模式: {mode}, 文本数量: {len(texts)}", "INFO")

        # 检查OpenAI配置
        api_keys = load_api_keys()
        api_key = api_keys.get('OPENAI_API_KEY')
        if not api_key:
            return jsonify({
                'success': False,
                'error': 'OpenAI API密钥未配置'
            }), 500

        try:
            from openai import OpenAI
            client = OpenAI(api_key=api_key)
        except ImportError:
            return jsonify({
                'success': False,
                'error': 'OpenAI库未安装'
            }), 500

        results = []

        if mode == 'merge':
            # 合并模式：先合并所有文本，再修改
            merged_text = '\n'.join(texts)

            prompt = f"""你是一个专业的文本编辑助手。

原始文本：
{merged_text}

用户的修改要求：
{instruction}

请严格按照用户的要求修改文本，只返回修改后的文本内容，不要添加任何解释或说明。
重要提示：
1. 必须严格遵循用户的指令，不要进行任何额外的优化或改动
2. 如果用户要求仅做格式修改（如添加标点、换行、空格等），必须完整保留原文的所有内容，只调整格式
3. 如果用户要求保留原文，绝对不能删除、替换或改写任何原文内容
4. 保持原文的语言（如果是中文就用中文，英文就用英文）"""

            response = client.chat.completions.create(
                model="gpt-5-mini",
                messages=[
                    {"role": "system", "content": "你是一个专业的文本编辑助手，必须严格按照用户要求修改文本，不做任何额外的优化或改动。"},
                    {"role": "user", "content": prompt}
                ],
                max_completion_tokens=5000
            )

            # 记录 token 使用情况
            usage = response.usage
            log_message(f"Token使用情况 - prompt: {usage.prompt_tokens}, completion: {usage.completion_tokens}, reasoning: {getattr(usage.completion_tokens_details, 'reasoning_tokens', 0)}, total: {usage.total_tokens}", "INFO")
            log_message(f"完成原因: {response.choices[0].finish_reason}", "INFO")

            revised_text = response.choices[0].message.content.strip() if response.choices[0].message.content else ""
            log_message(f"AI返回内容 - 原文长度: {len(merged_text)}, 修改后长度: {len(revised_text)}, 内容预览: {revised_text[:100] if revised_text else '(空)'}", "INFO")
            results.append({
                'original': merged_text,
                'revised': revised_text
            })

        else:
            # unified 或 individual 模式：分别处理每个文本
            for original_text in texts:
                prompt = f"""你是一个专业的文本编辑助手。

原始文本：
{original_text}

用户的修改要求：
{instruction}

请严格按照用户的要求修改文本，只返回修改后的文本内容，不要添加任何解释或说明。
重要提示：
1. 必须严格遵循用户的指令，不要进行任何额外的优化或改动
2. 如果用户要求仅做格式修改（如添加标点、换行、空格等），必须完整保留原文的所有内容，只调整格式
3. 如果用户要求保留原文，绝对不能删除、替换或改写任何原文内容
4. 保持原文的语言（如果是中文就用中文，英文就用英文）"""

                response = client.chat.completions.create(
                    model="gpt-5-mini",
                    messages=[
                        {"role": "system", "content": "你是一个专业的文本编辑助手，必须严格按照用户要求修改文本，不做任何额外的优化或改动。"},
                        {"role": "user", "content": prompt}
                    ],
                    max_completion_tokens=5000
                )

                # 记录 token 使用情况
                usage = response.usage
                log_message(f"Token使用情况 - prompt: {usage.prompt_tokens}, completion: {usage.completion_tokens}, reasoning: {getattr(usage.completion_tokens_details, 'reasoning_tokens', 0)}, total: {usage.total_tokens}", "INFO")
                log_message(f"完成原因: {response.choices[0].finish_reason}", "INFO")

                revised_text = response.choices[0].message.content.strip() if response.choices[0].message.content else ""
                log_message(f"AI返回内容 - 原文长度: {len(original_text)}, 修改后长度: {len(revised_text)}, 内容预览: {revised_text[:100] if revised_text else '(空)'}", "INFO")
                results.append({
                    'original': original_text,
                    'revised': revised_text
                })

        log_message(f"AI文本修改成功 - 处理了{len(results)}个文本", "INFO")

        return jsonify({
            'success': True,
            'mode': mode,
            'results': results
        })

    except Exception as e:
        log_message(f"AI文本修改失败: {str(e)}", "ERROR")
        import traceback
        traceback.print_exc()
        return jsonify({
            'success': False,
            'error': '文本修改失败',
            'message': str(e)
        }), 500

@app.route('/api/ai-global-optimize', methods=['POST'])
@jwt_required()
def ai_global_optimize():
    """全局AI优化：检查术语一致性、风格统一等"""
    try:
        data = request.get_json()
        texts = data.get('texts', [])  # 所有文本框的内容列表
        task_type = data.get('taskType', 'custom')  # terminology, style, custom
        instruction = data.get('instruction', '')

        if not texts:
            return jsonify({
                'success': False,
                'error': '缺少文本内容'
            }), 400

        log_message(f"全局AI优化 - 任务类型: {task_type}, 文本数量: {len(texts)}", "INFO")

        # 检查OpenAI配置
        api_key = os.getenv('OPENAI_API_KEY')
        if not api_key:
            return jsonify({
                'success': False,
                'error': 'OpenAI API密钥未配置'
            }), 500

        try:
            from openai import OpenAI
            client = OpenAI(api_key=api_key)
        except ImportError:
            return jsonify({
                'success': False,
                'error': 'OpenAI库未安装'
            }), 500

        # 构建系统提示
        system_prompts = {
            'terminology': '你是一个专业的翻译审校专家，擅长检查和统一术语使用。',
            'style': '你是一个专业的文本编辑专家，擅长统一文本风格和语气。',
            'custom': '你是一个专业的文本优化助手，擅长根据用户要求优化文本。'
        }

        # 构建用户提示 - 使用更紧凑的格式
        texts_list = [{"i": i, "t": text} for i, text in enumerate(texts)]

        prompt = f"""用户要求：{instruction}

文本列表（共{len(texts)}个）：
{json.dumps(texts_list, ensure_ascii=False)}

请分析这些文本，根据用户要求提出修改建议。
返回JSON格式（必须是有效的JSON）：
{{
  "suggestions": [
    {{"index": 0, "original": "原文", "revised": "修改后", "changes": "说明"}},
    ...
  ]
}}

注意：
1. index对应文本序号
2. 如果不需要修改，revised与original相同，changes为空字符串
3. changes简短说明修改原因
4. 确保返回完整有效的JSON"""

        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_prompts.get(task_type, system_prompts['custom'])},
                {"role": "user", "content": prompt}
            ],
            temperature=0.3,
            max_tokens=4000,
            response_format={"type": "json_object"}
        )

        result_text = response.choices[0].message.content.strip()
        log_message(f"AI返回内容长度: {len(result_text)}", "INFO")

        try:
            result_json = json.loads(result_text)
        except json.JSONDecodeError as e:
            log_message(f"JSON解析失败: {str(e)}", "ERROR")
            log_message(f"返回内容前500字符: {result_text[:500]}", "ERROR")
            # 尝试修复常见的JSON问题
            import re
            # 移除可能的markdown代码块标记
            result_text = re.sub(r'```json\s*', '', result_text)
            result_text = re.sub(r'```\s*$', '', result_text)
            result_json = json.loads(result_text)

        suggestions = result_json.get('suggestions', [])

        log_message(f"全局AI优化成功 - 生成了{len(suggestions)}条建议", "INFO")

        return jsonify({
            'success': True,
            'taskType': task_type,
            'suggestions': suggestions
        })

    except Exception as e:
        log_message(f"全局AI优化失败: {str(e)}", "ERROR")
        import traceback
        traceback.print_exc()
        return jsonify({
            'success': False,
            'error': '全局优化失败',
            'message': str(e)
        }), 500

# ============================================================================
# 实体识别相关路由（预留接口）
# ============================================================================

@app.route('/api/materials/<material_id>/enable-entity-recognition', methods=['POST'])
@jwt_required()
def toggle_entity_recognition(material_id):
    """
    启用/禁用材料的实体识别功能

    请求体:
        {
            "enabled": true/false,
            "mode": "standard" 或 "deep" (可选，默认为"standard")
        }
    """
    try:
        current_user_id = get_jwt_identity()
        user = User.query.get(current_user_id)
        if not user:
            return jsonify({'success': False, 'error': '用户不存在'}), 404

        material = Material.query.get(material_id)
        if not material:
            return jsonify({'success': False, 'error': '材料不存在'}), 404

        # 验证权限
        client = Client.query.get(material.client_id)
        if not client or client.user_id != current_user_id:
            return jsonify({'success': False, 'error': '无权限操作此材料'}), 403

        data = request.get_json()
        enabled = data.get('enabled', False)
        mode = data.get('mode', 'standard')  # 默认为standard模式

        # 🔍 调试日志：接收到的参数
        print(f"\n{'='*60}")
        print(f"[DEBUG] enable-entity-recognition 接口调用")
        print(f"材料ID: {material_id}")
        print(f"接收参数: enabled={enabled}, mode={mode}")
        print(f"当前状态: processing_step={material.processing_step}")
        print(f"{'='*60}\n")

        # 验证mode值
        if mode not in ['standard', 'deep']:
            return jsonify({'success': False, 'error': '无效的mode值，必须为standard或deep'}), 400

        material.entity_recognition_enabled = enabled
        if enabled:
            # 如果启用，设置模式
            material.entity_recognition_mode = mode
            print(f"[DEBUG] ✅ 已设置 entity_recognition_mode = {mode}")
        else:
            # 如果禁用，清除相关数据
            material.entity_recognition_mode = None
            material.entity_recognition_result = None
            material.entity_recognition_confirmed = False
            material.entity_recognition_triggered = False
            material.entity_user_edits = None
            material.entity_recognition_error = None

        db.session.commit()

        # 🔍 调试日志：保存后的值
        print(f"[DEBUG] 数据库提交后:")
        print(f"  entity_recognition_enabled = {material.entity_recognition_enabled}")
        print(f"  entity_recognition_mode = {material.entity_recognition_mode}")
        print(f"  to_dict()包含的值:")
        material_dict = material.to_dict()
        print(f"    entityRecognitionEnabled = {material_dict.get('entityRecognitionEnabled')}")
        print(f"    entityRecognitionMode = {material_dict.get('entityRecognitionMode')}")
        print(f"    processingStep = {material_dict.get('processingStep')}")

        log_message(f"材料 {material.name} 实体识别已{'启用' if enabled else '禁用'}" +
                   (f"，模式: {mode}" if enabled else ""), "INFO")

        return jsonify({
            'success': True,
            'enabled': enabled,
            'mode': mode,  # ✅ 返回mode给前端
            'material': material_dict,  # ✅ 返回完整material对象
            'message': f"实体识别已{'启用' if enabled else '禁用'}"
        })

    except Exception as e:
        log_message(f"切换实体识别失败: {str(e)}", "ERROR")
        import traceback
        traceback.print_exc()
        return jsonify({
            'success': False,
            'error': '切换实体识别失败',
            'message': str(e)
        }), 500


@app.route('/api/materials/<material_id>/entity-recognition', methods=['POST'])
@jwt_required()
def start_entity_recognition(material_id):
    """
    开始实体识别（OCR完成后调用）

    这是一个卡关步骤：
    1. 调用实体识别API
    2. 返回识别结果给前端
    3. 等待前端用户确认/编辑实体
    4. 用户确认后才能继续进行LLM翻译
    """
    try:
        current_user_id = get_jwt_identity()
        user = User.query.get(current_user_id)
        if not user:
            return jsonify({'success': False, 'error': '用户不存在'}), 404

        material = Material.query.get(material_id)
        if not material:
            return jsonify({'success': False, 'error': '材料不存在'}), 404

        # 验证权限
        client = Client.query.get(material.client_id)
        if not client or client.user_id != current_user_id:
            return jsonify({'success': False, 'error': '无权限操作此材料'}), 403

        # 检查是否已启用实体识别
        if not material.entity_recognition_enabled:
            return jsonify({
                'success': False,
                'error': '实体识别未启用',
                'message': '请先启用实体识别功能'
            }), 400

        # 检查是否已完成OCR翻译
        if not material.translation_text_info:
            return jsonify({
                'success': False,
                'error': 'OCR翻译未完成',
                'message': '请先完成OCR翻译再进行实体识别'
            }), 400

        log_message(f"开始实体识别: {material.name}", "INFO")

        # 更新状态为实体识别中
        material.processing_step = ProcessingStep.ENTITY_RECOGNIZING.value
        material.processing_progress = 0
        db.session.commit()

        # 解析OCR结果
        ocr_result = json.loads(material.translation_text_info)

        # 调用实体识别服务
        from entity_recognition_service import EntityRecognitionService
        entity_service = EntityRecognitionService()
        entity_result = entity_service.recognize_entities(ocr_result)

        if entity_result.get('success'):
            # 保存实体识别结果
            material.entity_recognition_result = json.dumps(entity_result, ensure_ascii=False)
            material.processing_step = ProcessingStep.ENTITY_PENDING_CONFIRM.value
            material.processing_progress = 100
            material.entity_recognition_error = None

            # 保存日志
            entity_service.save_entity_recognition_log(
                material_id=material.id,
                material_name=material.name,
                ocr_result=ocr_result,
                entity_result=entity_result
            )

            db.session.commit()

            log_message(f"实体识别完成: {material.name}, 识别到 {entity_result.get('total_entities', 0)} 个实体", "INFO")

            return jsonify({
                'success': True,
                'result': entity_result,
                'message': '实体识别完成，请确认识别结果'
            })
        else:
            # 识别失败
            material.entity_recognition_error = entity_result.get('error')

            # 检查是否是可恢复错误
            if entity_result.get('recoverable'):
                # 可恢复错误，允许继续翻译流程
                material.entity_recognition_enabled = False
                material.processing_step = ProcessingStep.TRANSLATED.value
                db.session.commit()

                log_message(f"实体识别服务不可用，已禁用: {material.name}, 错误: {entity_result.get('error')}", "WARN")

                return jsonify({
                    'success': False,
                    'error': '实体识别服务暂时不可用',
                    'message': entity_result.get('error'),
                    'recoverable': True,
                    'canContinue': True
                }), 503  # Service Unavailable
            else:
                # 不可恢复错误
                material.processing_step = ProcessingStep.FAILED.value
                db.session.commit()

                log_message(f"实体识别失败: {material.name}, 错误: {entity_result.get('error')}", "ERROR")

                return jsonify({
                    'success': False,
                    'error': '实体识别失败',
                    'message': entity_result.get('error')
                }), 500

    except Exception as e:
        log_message(f"实体识别异常: {str(e)}", "ERROR")
        import traceback
        traceback.print_exc()

        # 更新错误状态
        try:
            material.entity_recognition_error = str(e)
            material.processing_step = ProcessingStep.FAILED.value
            db.session.commit()
        except:
            pass

        return jsonify({
            'success': False,
            'error': '实体识别异常',
            'message': str(e)
        }), 500


@app.route('/api/materials/<material_id>/entity-recognition-result', methods=['GET'])
@jwt_required()
def get_entity_recognition_result(material_id):
    """获取材料的实体识别结果"""
    try:
        current_user_id = get_jwt_identity()
        user = User.query.get(current_user_id)
        if not user:
            return jsonify({'success': False, 'error': '用户不存在'}), 404

        material = Material.query.get(material_id)
        if not material:
            return jsonify({'success': False, 'error': '材料不存在'}), 404

        # 验证权限
        client = Client.query.get(material.client_id)
        if not client or client.user_id != current_user_id:
            return jsonify({'success': False, 'error': '无权限访问此材料'}), 403

        # 解析实体识别结果
        entity_result = None
        if material.entity_recognition_result:
            try:
                entity_result = json.loads(material.entity_recognition_result)
            except:
                entity_result = None

        # 解析用户编辑的实体信息
        entity_edits = None
        if material.entity_user_edits:
            try:
                entity_edits = json.loads(material.entity_user_edits)
            except:
                entity_edits = None

        return jsonify({
            'success': True,
            'enabled': material.entity_recognition_enabled,
            'confirmed': material.entity_recognition_confirmed,
            'result': entity_result,
            'userEdits': entity_edits,
            'error': material.entity_recognition_error,
            'processingStep': material.processing_step,
            'processingProgress': material.processing_progress
        })

    except Exception as e:
        log_message(f"获取实体识别结果失败: {str(e)}", "ERROR")
        return jsonify({
            'success': False,
            'error': '获取实体识别结果失败',
            'message': str(e)
        }), 500


@app.route('/api/materials/<material_id>/confirm-entities', methods=['POST'])
@jwt_required()
def confirm_entities(material_id):
    """
    用户确认/编辑实体识别结果（卡关步骤的确认）

    请求体:
        {
            "entities": [
                {
                    "region_id": 0,
                    "entities": [
                        {
                            "type": "PERSON",
                            "value": "张三",
                            "translation_instruction": "translate as 'Zhang San'"
                        }
                    ]
                }
            ],
            "translationGuidance": {
                "persons": ["张三 -> Zhang San"],
                "locations": ["北京 -> Beijing"],
                "organizations": ["北京大学 -> Peking University"],
                "terms": ["机器学习 -> Machine Learning"]
            }
        }
    """
    try:
        current_user_id = get_jwt_identity()
        user = User.query.get(current_user_id)
        if not user:
            return jsonify({'success': False, 'error': '用户不存在'}), 404

        material = Material.query.get(material_id)
        if not material:
            return jsonify({'success': False, 'error': '材料不存在'}), 404

        # 验证权限
        client = Client.query.get(material.client_id)
        if not client or client.user_id != current_user_id:
            return jsonify({'success': False, 'error': '无权限操作此材料'}), 403

        # 检查是否在等待确认状态
        if material.processing_step != ProcessingStep.ENTITY_PENDING_CONFIRM.value:
            return jsonify({
                'success': False,
                'error': '状态错误',
                'message': '当前不在等待实体确认状态'
            }), 400

        data = request.get_json()
        entities = data.get('entities', [])
        translation_guidance = data.get('translationGuidance', {})

        # 保存用户编辑的实体信息
        user_edits = {
            'entities': entities,
            'translationGuidance': translation_guidance,
            'confirmedAt': datetime.utcnow().isoformat()
        }
        material.entity_user_edits = json.dumps(user_edits, ensure_ascii=False)
        material.entity_recognition_confirmed = True
        material.processing_step = ProcessingStep.ENTITY_CONFIRMED.value

        # ⭐ 关键功能：如果是PDF，将translationGuidance应用到所有同一Session的页面
        if material.pdf_session_id:
            log_message(f"PDF Session检测到: {material.pdf_session_id}，应用translationGuidance到所有页面", "INFO")
            session_materials = Material.query.filter_by(
                pdf_session_id=material.pdf_session_id
            ).all()

            affected_count = 0
            for mat in session_materials:
                if mat.id != material.id:  # 跳过当前材料（已经设置过了）
                    mat.entity_user_edits = json.dumps(user_edits, ensure_ascii=False)
                    mat.entity_recognition_confirmed = True
                    if mat.processing_step == ProcessingStep.ENTITY_PENDING_CONFIRM.value:
                        mat.processing_step = ProcessingStep.ENTITY_CONFIRMED.value
                    affected_count += 1

            log_message(f"已为 {affected_count} 个PDF页面应用相同的translationGuidance", "INFO")

        db.session.commit()

        log_message(f"实体识别已确认: {material.name}", "INFO")

        # ⭐ 自动触发LLM翻译
        try:
            from threading import Thread
            log_message(f"自动触发LLM翻译: {material.name}", "INFO")

            # 创建线程异步执行LLM翻译
            def trigger_llm_translation():
                with app.app_context():
                    try:
                        # 更新状态为LLM翻译中
                        mat = Material.query.get(material_id)
                        if mat:
                            mat.processing_step = ProcessingStep.LLM_TRANSLATING.value
                            db.session.commit()

                            # WebSocket推送
                            if WEBSOCKET_ENABLED:
                                emit_llm_started(material_id, progress=70)

                        # 执行LLM翻译
                        baidu_result = json.loads(mat.translation_text_info)
                        regions = baidu_result.get('regions', [])

                        # 读取实体识别指导
                        entity_guidance = None
                        if mat.entity_user_edits:
                            entity_data = json.loads(mat.entity_user_edits)
                            entity_guidance = entity_data.get('translationGuidance', {})

                        from llm_service import LLMTranslationService
                        llm_service = LLMTranslationService(output_folder='outputs')
                        llm_translations = llm_service.optimize_translations(regions, entity_guidance=entity_guidance)

                        # 保存结果
                        mat.llm_translation_result = json.dumps(llm_translations, ensure_ascii=False)
                        mat.processing_step = ProcessingStep.LLM_TRANSLATED.value
                        mat.processing_progress = 100
                        mat.status = MaterialStatus.TRANSLATED.value
                        db.session.commit()

                        # WebSocket推送完成
                        if WEBSOCKET_ENABLED:
                            emit_llm_completed(material_id, llm_translations, progress=100)

                        log_message(f"自动LLM翻译完成: {mat.name}", "SUCCESS")

                    except Exception as e:
                        log_message(f"自动触发LLM翻译失败: {str(e)}", "ERROR")
                        import traceback
                        traceback.print_exc()

                        # 标记失败
                        mat = Material.query.get(material_id)
                        if mat:
                            mat.status = MaterialStatus.FAILED.value
                            mat.processing_step = ProcessingStep.FAILED.value
                            mat.translation_error = f"LLM翻译失败: {str(e)}"
                            db.session.commit()

            thread = Thread(target=trigger_llm_translation)
            thread.daemon = True
            thread.start()

        except Exception as e:
            log_message(f"启动LLM翻译线程失败: {str(e)}", "WARNING")

        return jsonify({
            'success': True,
            'message': '实体识别已确认，LLM翻译已自动启动',
            'canProceedToLLM': True,
            'autoStartedLLM': True
        })

    except Exception as e:
        log_message(f"确认实体失败: {str(e)}", "ERROR")
        import traceback
        traceback.print_exc()
        return jsonify({
            'success': False,
            'error': '确认实体失败',
            'message': str(e)
        }), 500


@app.route('/api/materials/<material_id>/entity-recognition/fast', methods=['POST'])
@jwt_required()
def entity_recognition_fast(material_id):
    """
    快速实体识别查询
    仅识别实体，不进行深度搜索
    """
    try:
        print(f"\n{'='*80}")
        print(f"[DEBUG] ========== 快速实体识别开始 ==========")
        print(f"[DEBUG] 材料ID: {material_id}")
        print(f"{'='*80}\n")

        current_user_id = get_jwt_identity()
        user = User.query.get(current_user_id)
        if not user:
            return jsonify({'success': False, 'error': '用户不存在'}), 404

        material = Material.query.get(material_id)
        if not material:
            return jsonify({'success': False, 'error': '材料不存在'}), 404

        # 🔍 调试日志：当前状态
        print(f"[DEBUG] 当前状态:")
        print(f"  processing_step = {material.processing_step}")
        print(f"  entity_recognition_enabled = {material.entity_recognition_enabled}")
        print(f"  entity_recognition_mode = {material.entity_recognition_mode}")
        print(f"  entity_recognition_triggered = {material.entity_recognition_triggered}")

        # 验证权限
        client = Client.query.get(material.client_id)
        if not client or client.user_id != current_user_id:
            return jsonify({'success': False, 'error': '无权限操作此材料'}), 403

        # 确保有OCR结果
        if not material.translation_text_info:
            return jsonify({'success': False, 'error': '请先完成OCR识别'}), 400

        # 解析OCR结果
        ocr_result = json.loads(material.translation_text_info)

        # ⭐ 1. 设置状态为识别中
        material.processing_step = ProcessingStep.ENTITY_RECOGNIZING.value
        material.entity_recognition_triggered = True
        db.session.commit()

        # WebSocket推送状态更新
        if WEBSOCKET_ENABLED:
            emit_material_updated(
                material.client_id,
                material.id,
                processing_step=material.processing_step,
                material=material.to_dict()  # ✅ 传递完整的material对象
            )

        # 2. 调用快速实体识别服务
        from entity_recognition_service import EntityRecognitionService
        entity_service = EntityRecognitionService()
        entity_result = entity_service.recognize_entities(ocr_result, mode="fast")

        if entity_result.get('success'):
            print(f"\n[DEBUG] ========== 设置状态为 entity_pending_confirm ==========")

            # ⭐ 3. 保存结果并设置状态为等待确认
            material.entity_recognition_result = json.dumps(entity_result, ensure_ascii=False)
            material.processing_step = ProcessingStep.ENTITY_PENDING_CONFIRM.value  # ✅ 关键：设置为待确认
            db.session.commit()

            print(f"[DEBUG] ✅ 已设置: processing_step = {material.processing_step}")
            print(f"[DEBUG] ✅ 已保存: entity_recognition_mode = {material.entity_recognition_mode}")
            print(f"[DEBUG] ✅ 已保存: entity_recognition_result 包含 {entity_result.get('total_entities', 0)} 个实体")

            # ⭐ 4. WebSocket推送更新（包含完整material对象）
            material_dict = material.to_dict()

            print(f"\n[DEBUG] ========== 准备推送 WebSocket ==========")
            print(f"[DEBUG] 推送数据:")
            print(f"  processingStep = {material_dict.get('processingStep')}")
            print(f"  entityRecognitionMode = {material_dict.get('entityRecognitionMode')}")
            print(f"  entityRecognitionEnabled = {material_dict.get('entityRecognitionEnabled')}")
            print(f"  entityRecognitionResult 包含实体数: {len(material_dict.get('entityRecognitionResult', {}).get('entities', []))}")
            print(f"  client_id = {material.client_id}")
            print(f"  material_id = {material.id}")

            if WEBSOCKET_ENABLED:
                emit_material_updated(
                    material.client_id,
                    material.id,
                    processing_step=material.processing_step,
                    material=material_dict  # ✅ 传递完整的material对象
                )
                print(f"[DEBUG] ✅ WebSocket已推送")

            log_message(f"快速实体识别完成: {material.name}, 识别到 {entity_result.get('total_entities', 0)} 个实体", "INFO")

            return jsonify({
                'success': True,
                'result': entity_result,
                'mode': 'fast',
                'material': material.to_dict(),  # ✅ 返回完整material对象
                'message': '快速识别完成，您可以选择AI深度查询或人工调整'
            })
        else:
            log_message(f"快速实体识别失败: {material.name}, 错误: {entity_result.get('error')}", "ERROR")

            return jsonify({
                'success': False,
                'error': entity_result.get('error', '快速识别失败'),
                'recoverable': entity_result.get('recoverable', False)
            }), 500

    except Exception as e:
        log_message(f"快速实体识别异常: {str(e)}", "ERROR")
        import traceback
        traceback.print_exc()
        return jsonify({
            'success': False,
            'error': '快速实体识别异常',
            'message': str(e)
        }), 500


@app.route('/api/materials/<material_id>/entity-recognition/deep', methods=['POST'])
@jwt_required()
def entity_recognition_deep(material_id):
    """
    深度实体识别查询（全自动）
    进行完整的Google搜索和官网分析，获取准确的官方英文名称
    """
    try:
        current_user_id = get_jwt_identity()
        user = User.query.get(current_user_id)
        if not user:
            return jsonify({'success': False, 'error': '用户不存在'}), 404

        material = Material.query.get(material_id)
        if not material:
            return jsonify({'success': False, 'error': '材料不存在'}), 404

        # 验证权限
        client = Client.query.get(material.client_id)
        if not client or client.user_id != current_user_id:
            return jsonify({'success': False, 'error': '无权限操作此材料'}), 403

        # 确保有OCR结果
        if not material.translation_text_info:
            return jsonify({'success': False, 'error': '请先完成OCR识别'}), 400

        # 解析OCR结果
        ocr_result = json.loads(material.translation_text_info)

        # ⭐ 1. 设置状态为识别中
        material.processing_step = ProcessingStep.ENTITY_RECOGNIZING.value
        material.entity_recognition_triggered = True
        db.session.commit()

        # WebSocket推送状态更新
        if WEBSOCKET_ENABLED:
            emit_material_updated(
                material.client_id,
                material.id,
                processing_step=material.processing_step,
                material=material.to_dict()  # ✅ 传递完整的material对象
            )

        # 2. 调用深度实体识别服务
        from entity_recognition_service import EntityRecognitionService
        entity_service = EntityRecognitionService()
        entity_result = entity_service.recognize_entities(ocr_result, mode="deep")

        if entity_result.get('success'):
            # ⭐ 3. 保存深度识别结果并自动确认
            material.entity_recognition_result = json.dumps(entity_result, ensure_ascii=False)
            material.entity_recognition_confirmed = True  # 深度查询自动确认
            material.processing_step = ProcessingStep.ENTITY_CONFIRMED.value

            # 保存translationGuidance（从实体结果中提取）
            if entity_result.get('translationGuidance'):
                user_edits = {
                    'entities': entity_result.get('entities', []),
                    'translationGuidance': entity_result.get('translationGuidance', {}),
                    'confirmedAt': datetime.utcnow().isoformat()
                }
                material.entity_user_edits = json.dumps(user_edits, ensure_ascii=False)

            db.session.commit()

            # ⭐ 4. WebSocket推送更新
            if WEBSOCKET_ENABLED:
                emit_material_updated(
                    material.client_id,
                    material.id,
                    processing_step=material.processing_step,
                    material=material.to_dict()  # ✅ 传递完整的material对象
                )

            # 保存日志
            entity_service.save_entity_recognition_log(
                material_id=material.id,
                material_name=material.name,
                ocr_result=ocr_result,
                entity_result=entity_result
            )

            log_message(f"深度实体识别完成: {material.name}, 识别到 {entity_result.get('total_entities', 0)} 个实体", "INFO")

            # ⭐ 5. 自动触发LLM翻译（深度模式全自动）
            try:
                from threading import Thread
                log_message(f"深度模式：自动触发LLM翻译: {material.name}", "INFO")

                def trigger_llm_translation():
                    with app.app_context():
                        try:
                            mat = Material.query.get(material_id)
                            if mat:
                                mat.processing_step = ProcessingStep.LLM_TRANSLATING.value
                                db.session.commit()

                                if WEBSOCKET_ENABLED:
                                    emit_llm_started(material_id, progress=70)

                            baidu_result = json.loads(mat.translation_text_info)
                            regions = baidu_result.get('regions', [])

                            entity_guidance = None
                            if mat.entity_user_edits:
                                entity_data = json.loads(mat.entity_user_edits)
                                entity_guidance = entity_data.get('translationGuidance', {})

                            from llm_service import LLMTranslationService
                            llm_service = LLMTranslationService(output_folder='outputs')
                            llm_translations = llm_service.optimize_translations(regions, entity_guidance=entity_guidance)

                            mat.llm_translation_result = json.dumps(llm_translations, ensure_ascii=False)
                            mat.processing_step = ProcessingStep.LLM_TRANSLATED.value
                            mat.processing_progress = 100
                            mat.status = MaterialStatus.TRANSLATED.value
                            db.session.commit()

                            if WEBSOCKET_ENABLED:
                                emit_llm_completed(material_id, llm_translations, progress=100)

                            log_message(f"深度模式：自动LLM翻译完成: {mat.name}", "SUCCESS")

                        except Exception as e:
                            log_message(f"深度模式：自动LLM翻译失败: {str(e)}", "ERROR")
                            import traceback
                            traceback.print_exc()

                            mat = Material.query.get(material_id)
                            if mat:
                                mat.status = MaterialStatus.FAILED.value
                                mat.processing_step = ProcessingStep.FAILED.value
                                mat.translation_error = f"LLM翻译失败: {str(e)}"
                                db.session.commit()

                thread = Thread(target=trigger_llm_translation)
                thread.daemon = True
                thread.start()

            except Exception as e:
                log_message(f"深度模式：启动LLM翻译线程失败: {str(e)}", "WARNING")

            return jsonify({
                'success': True,
                'result': entity_result,
                'mode': 'deep',
                'material': material.to_dict(),  # ✅ 返回完整material对象
                'autoStartedLLM': True,  # ✅ 告知前端已自动启动LLM
                'message': '深度识别完成，已自动确认，LLM翻译已自动启动'
            })
        else:
            log_message(f"深度实体识别失败: {material.name}, 错误: {entity_result.get('error')}", "ERROR")

            return jsonify({
                'success': False,
                'error': entity_result.get('error', '深度识别失败'),
                'recoverable': entity_result.get('recoverable', False)
            }), 500

    except Exception as e:
        log_message(f"深度实体识别异常: {str(e)}", "ERROR")
        import traceback
        traceback.print_exc()
        return jsonify({
            'success': False,
            'error': '深度实体识别异常',
            'message': str(e)
        }), 500


@app.route('/api/materials/<material_id>/entity-recognition/manual-adjust', methods=['POST'])
@jwt_required()
def entity_recognition_manual_adjust(material_id):
    """
    人工调整模式（AI优化）
    基于fast查询结果进行AI优化

    请求体:
        {
            "fast_results": [...]  # fast查询的结果
        }
    """
    try:
        current_user_id = get_jwt_identity()
        user = User.query.get(current_user_id)
        if not user:
            return jsonify({'success': False, 'error': '用户不存在'}), 404

        material = Material.query.get(material_id)
        if not material:
            return jsonify({'success': False, 'error': '材料不存在'}), 404

        # 验证权限
        client = Client.query.get(material.client_id)
        if not client or client.user_id != current_user_id:
            return jsonify({'success': False, 'error': '无权限操作此材料'}), 403

        # 确保有OCR结果
        if not material.translation_text_info:
            return jsonify({'success': False, 'error': '请先完成OCR识别'}), 400

        # 解析OCR结果
        ocr_result = json.loads(material.translation_text_info)

        # 获取fast查询结果
        data = request.get_json()
        fast_results = data.get('fast_results', [])
        ocr_result['fast_results'] = fast_results  # 将fast结果添加到OCR结果中

        # 调用人工调整模式服务
        from entity_recognition_service import EntityRecognitionService
        entity_service = EntityRecognitionService()
        entity_result = entity_service.recognize_entities(ocr_result, mode="manual_adjust")

        if entity_result.get('success'):
            log_message(f"人工调整模式完成: {material.name}, 优化了 {entity_result.get('total_entities', 0)} 个实体", "INFO")

            return jsonify({
                'success': True,
                'result': entity_result,
                'mode': 'manual_adjust',
                'message': 'AI优化完成，请确认后进行LLM翻译'
            })
        else:
            log_message(f"人工调整模式失败: {material.name}, 错误: {entity_result.get('error')}", "ERROR")

            return jsonify({
                'success': False,
                'error': entity_result.get('error', '人工调整模式失败'),
                'recoverable': entity_result.get('recoverable', False)
            }), 500

    except Exception as e:
        log_message(f"人工调整模式异常: {str(e)}", "ERROR")
        import traceback
        traceback.print_exc()
        return jsonify({
            'success': False,
            'error': '人工调整模式异常',
            'message': str(e)
        }), 500


@app.route('/api/materials/<material_id>/llm-translate', methods=['POST'])
@jwt_required()
def llm_translate_material(material_id):
    """使用LLM优化材料的翻译"""
    try:
        log_message(f"========== 开始LLM翻译优化 ==========", "INFO")
        log_message(f"材料ID: {material_id}", "INFO")

        # ✅ 检查翻译锁，防止重复LLM优化请求
        is_locked, locked_material = check_translation_lock(material_id)
        if is_locked:
            log_message(f"材料正在翻译中，拒绝LLM优化请求: {material_id}", "WARN")
            return jsonify({
                'success': False,
                'error': '该材料正在翻译中，请等待完成后再试',
                'status': locked_material.status
            }), 409

        user_id = get_jwt_identity()
        log_message(f"用户ID: {user_id}", "INFO")

        # 查找材料并验证权限
        material = Material.query.join(Client).filter(
            Material.id == material_id,
            Client.user_id == user_id
        ).first()

        if not material:
            log_message(f"材料不存在或无权限: {material_id}", "ERROR")
            return jsonify({'success': False, 'error': '材料不存在'}), 404

        log_message(f"材料名称: {material.name}", "INFO")

        # 如果已经有LLM翻译结果，直接返回（避免重复调用）
        if material.llm_translation_result:
            log_message(f"材料 {material.name} 已有LLM翻译结果，直接返回", "INFO")
            llm_translations = json.loads(material.llm_translation_result)
            return jsonify({
                'success': True,
                'llm_translations': llm_translations,
                'message': f'已有 {len(llm_translations)} 个优化结果（来自缓存）',
                'from_cache': True
            })

        # 检查实体识别状态（如果启用了实体识别，必须先确认实体）
        if material.entity_recognition_enabled:
            if not material.entity_recognition_confirmed:
                log_message(f"材料 {material.name} 启用了实体识别但尚未确认，拒绝LLM翻译", "ERROR")
                return jsonify({
                    'success': False,
                    'error': '请先完成实体识别确认',
                    'message': '实体识别已启用，需要先确认实体信息后才能进行LLM翻译',
                    'requireEntityConfirmation': True,
                    'processingStep': material.processing_step
                }), 400

        # 获取百度翻译结果
        if not material.translation_text_info:
            log_message("材料缺少百度翻译结果", "ERROR")
            return jsonify({
                'success': False,
                'error': '请先完成百度翻译'
            }), 400

        baidu_result = json.loads(material.translation_text_info)
        regions = baidu_result.get('regions', [])
        log_message(f"百度翻译regions数量: {len(regions)}", "INFO")

        if not regions:
            log_message("百度翻译结果为空", "ERROR")
            return jsonify({
                'success': False,
                'error': '没有可翻译的文本区域'
            }), 400

        # 使用LLM优化
        log_message(f"开始调用LLM服务优化翻译...", "INFO")

        # ✅ WebSocket 推送：LLM 翻译开始
        if WEBSOCKET_ENABLED:
            emit_llm_started(material_id, progress=66)

        # 获取实体信息（如果已确认）
        entity_guidance = None
        if material.entity_recognition_enabled and material.entity_recognition_confirmed:
            if material.entity_user_edits:
                try:
                    entity_data = json.loads(material.entity_user_edits)
                    entity_guidance = entity_data.get('translationGuidance', {})
                    log_message(f"使用实体识别信息指导LLM翻译: {len(entity_guidance)} 类实体", "INFO")
                except:
                    log_message("解析实体信息失败，忽略", "WARN")

        from llm_service import LLMTranslationService
        llm_service = LLMTranslationService(output_folder='outputs')

        log_message(f"LLM服务初始化成功，开始优化 {len(regions)} 个区域", "INFO")
        llm_translations = llm_service.optimize_translations(regions, entity_guidance=entity_guidance)
        log_message(f"LLM优化完成，返回 {len(llm_translations)} 个翻译结果", "SUCCESS")

        # 保存LLM翻译日志和对比报告（与Reference项目一致）
        log_files = llm_service.save_llm_translation_log(
            material.name,
            regions,
            llm_translations
        )

        # 保存LLM翻译结果到数据库
        # ✅ 使用统一函数更新状态（会自动推送WebSocket）
        update_material_status(
            material,
            MaterialStatus.TRANSLATED,
            llm_translation_result=json.dumps(llm_translations, ensure_ascii=False),
            processing_step=ProcessingStep.TRANSLATED.value,
            processing_progress=100
        )

        log_message(f"LLM翻译完成: {material_id}, 优化了 {len(llm_translations)} 个区域")

        # ✅ 额外推送LLM完成事件（保留特殊事件）
        if WEBSOCKET_ENABLED:
            emit_llm_completed(material_id, llm_translations, progress=100)

        result = {
            'success': True,
            'llm_translations': llm_translations,
            'message': f'成功优化 {len(llm_translations)} 个翻译区域'
        }

        # 添加日志文件信息（与Reference项目一致）
        if log_files:
            result['log_files'] = log_files

        return jsonify(result)

    except Exception as e:
        db.session.rollback()
        import traceback
        error_traceback = traceback.format_exc()
        log_message(f"LLM翻译失败: {str(e)}", "ERROR")
        log_message(f"错误堆栈:\n{error_traceback}", "ERROR")
        
        # ✅ WebSocket 推送：LLM 翻译失败
        if WEBSOCKET_ENABLED:
            emit_llm_error(material_id, str(e))

        # 返回详细错误信息给前端
        return jsonify({
            'success': False,
            'error': str(e),
            'error_type': type(e).__name__,
            'traceback': error_traceback
        }), 500

@app.route('/api/materials/<material_id>/retranslate', methods=['POST'])
@jwt_required()
def retranslate_material(material_id):
    """重新翻译单个材料（百度翻译 + LLM优化）"""
    try:
        log_message(f"========== 开始重新翻译材料 ==========", "INFO")
        log_message(f"材料ID: {material_id}", "INFO")

        # ✅ 检查翻译锁，防止重复翻译
        is_locked, locked_material = check_translation_lock(material_id)
        if is_locked:
            log_message(f"材料正在翻译中，拒绝重复请求: {material_id}", "WARN")
            return jsonify({
                'success': False,
                'error': '该材料正在翻译中，请等待完成后再试',
                'status': locked_material.status
            }), 409

        user_id = get_jwt_identity()

        # 查找材料并验证权限
        material = Material.query.join(Client).filter(
            Material.id == material_id,
            Client.user_id == user_id
        ).first()

        if not material:
            log_message(f"材料不存在或无权限: {material_id}", "ERROR")
            return jsonify({'success': False, 'error': '材料不存在'}), 404

        if material.type not in ['image', 'pdf']:
            return jsonify({'success': False, 'error': '只支持图片和PDF材料'}), 400

        log_message(f"材料名称: {material.name}, 类型: {material.type}", "INFO")

        # 调用Reference方式的百度翻译（函数在app.py内部定义）
        result = translate_image_reference(
            image_path=material.file_path,
            source_lang='zh',
            target_lang='en'
        )

        # 检查API错误
        error_code = result.get('error_code')
        if error_code and error_code not in [0, '0', None]:
            error_msg = result.get('error_msg', '翻译失败')
            log_message(f"百度API错误: {material.name} - {error_msg}", "ERROR")
            # ✅ 使用统一函数更新状态
            update_material_status(
                material,
                MaterialStatus.FAILED,
                translation_error=error_msg
            )
            return jsonify({'success': False, 'error': error_msg}), 500

        # 解析regions数据
        data = result.get('data', {})
        content = data.get('content', [])

        if not content:
            log_message(f"百度翻译未识别到文字: {material.name}", "WARN")
            # ✅ 使用统一函数更新状态
            update_material_status(
                material,
                MaterialStatus.FAILED,
                translation_error='未识别到文字区域'
            )
            return jsonify({'success': False, 'error': '未识别到文字区域'}), 400

        # 清除旧的编辑内容，从原始图片重新开始
        material.edited_image_path = None
        material.final_image_path = None
        material.has_edited_version = False
        material.edited_regions = None

        # 保存新的百度翻译结果（覆盖旧的）
        regions_data = {'regions': content}
        # ✅ 使用统一函数更新状态
        update_material_status(
            material,
            MaterialStatus.TRANSLATED,
            translation_text_info=regions_data,
            translation_error=None,
            processing_step=ProcessingStep.TRANSLATED.value,
            processing_progress=66
        )

        log_message(f"百度翻译成功: {material.name}, 识别了 {len(content)} 个区域", "SUCCESS")

        # 自动触发LLM优化（覆盖旧的）
        log_message(f"开始LLM优化翻译...", "INFO")
        from llm_service import LLMTranslationService
        llm_service = LLMTranslationService(output_folder='outputs')

        llm_translations = llm_service.optimize_translations(content)
        log_message(f"LLM优化完成，返回 {len(llm_translations)} 个翻译结果", "SUCCESS")

        # 保存LLM翻译结果（覆盖旧的）
        # ✅ 使用统一函数更新状态
        update_material_status(
            material,
            MaterialStatus.TRANSLATED,
            llm_translation_result=json.dumps(llm_translations, ensure_ascii=False),
            processing_step=ProcessingStep.TRANSLATED.value,
            processing_progress=100
        )

        log_message(f"重新翻译完成: {material.name}", "SUCCESS")

        return jsonify({
            'success': True,
            'material': {
                'id': material.id,
                'name': material.name,
                'status': material.status,
                'filePath': material.file_path,
                'translationTextInfo': regions_data,
                'llmTranslationResult': llm_translations,
                'processingProgress': 100,
                'processingStep': 'completed',
                # 保留PDF相关字段，避免前端更新时丢失
                'pdfSessionId': material.pdf_session_id,
                'pdfPageNumber': material.pdf_page_number,
                'pdfTotalPages': material.pdf_total_pages
            },
            'message': '重新翻译成功'
        })

    except Exception as e:
        db.session.rollback()
        import traceback
        error_traceback = traceback.format_exc()
        log_message(f"重新翻译失败: {str(e)}", "ERROR")
        log_message(f"错误堆栈:\n{error_traceback}", "ERROR")

        return jsonify({
            'success': False,
            'error': str(e),
            'error_type': type(e).__name__
        }), 500


@app.route('/api/materials/<material_id>/rotate', methods=['POST'])
@jwt_required()
def rotate_material(material_id):
    """旋转材料图片90度（只旋转，不重新翻译）"""
    try:
        log_message(f"========== 开始旋转图片 ==========", "INFO")
        log_message(f"材料ID: {material_id}", "INFO")

        user_id = get_jwt_identity()

        # 查找材料并验证权限
        material = Material.query.join(Client).filter(
            Material.id == material_id,
            Client.user_id == user_id
        ).first()

        if not material:
            log_message(f"材料不存在或无权限: {material_id}", "ERROR")
            return jsonify({'success': False, 'error': '材料不存在'}), 404

        if material.type not in ['image', 'pdf']:
            return jsonify({'success': False, 'error': '只支持图片和PDF材料'}), 400

        log_message(f"材料名称: {material.name}, 类型: {material.type}", "INFO")

        # 读取原始图片
        from PIL import Image
        import os

        # material.file_path 已经包含了 'uploads/' 前缀，不需要再加
        original_path = material.file_path
        if not os.path.exists(original_path):
            log_message(f"文件不存在: {original_path}", "ERROR")
            return jsonify({'success': False, 'error': '原始图片文件不存在'}), 404

        # 旋转图片90度（顺时针）
        img = Image.open(original_path)
        rotated_img = img.rotate(-90, expand=True)  # -90表示顺时针旋转90度

        # 保存旋转后的图片（覆盖原文件）
        rotated_img.save(original_path)
        log_message(f"图片已旋转90度: {original_path}", "SUCCESS")

        # 清除旧的翻译结果和编辑图片，让用户重新点击翻译按钮
        material.translation_text_info = None
        material.llm_translation_result = None
        material.edited_image_path = None
        material.final_image_path = None
        material.has_edited_version = False
        material.edited_regions = None
        material.status = '已上传'  # 重置状态为已上传
        material.processing_step = None
        material.processing_progress = 0
        material.updated_at = datetime.utcnow()

        db.session.commit()

        return jsonify({
            'success': True,
            'material': {
                'id': material.id,
                'name': material.name,
                'status': material.status,
                'filePath': material.file_path,
                'processingProgress': 0,
                'processingStep': None,
                # 保留PDF相关字段，避免前端更新时丢失
                'pdfSessionId': material.pdf_session_id,
                'pdfPageNumber': material.pdf_page_number,
                'pdfTotalPages': material.pdf_total_pages
            },
            'message': '图片已旋转90度，请点击重新翻译按钮'
        })

    except Exception as e:
        db.session.rollback()
        import traceback
        error_traceback = traceback.format_exc()
        log_message(f"旋转图片失败: {str(e)}", "ERROR")
        log_message(f"错误堆栈:\n{error_traceback}", "ERROR")

        return jsonify({
            'success': False,
            'error': str(e),
            'error_type': type(e).__name__
        }), 500


@jwt_required()
def export_client_materials(client_id):
    """导出客户的所有已确认材料"""
    try:
        current_user_id = get_jwt_identity()
        
        # 查找客户并验证权限
        client = Client.query.filter_by(id=client_id, user_id=current_user_id).first()
        if not client:
            return jsonify({
                'success': False,
                'error': '客户不存在'
            }), 404
        
        # 查找所有已确认的材料
        confirmed_materials = Material.query.filter_by(
            client_id=client_id,
            confirmed=True
        ).all()
        
        if not confirmed_materials:
            return jsonify({
                'success': False,
                'error': '没有已确认的翻译材料'
            }), 404
        
        # 创建导出文件列表
        export_data = []
        for material in confirmed_materials:
            material_data = {
                'id': material.id,
                'name': material.name,
                'type': material.type,
                'selected_type': material.selected_result,
                'confirmed_at': material.updated_at.isoformat() if material.updated_at else None
            }
            
            # 根据选择的翻译类型提供文件路径
            if material.selected_result == 'api' and material.translated_image_path:
                material_data['file_path'] = material.translated_image_path
            elif material.selected_result == 'latex' and material.latex_translation_result:
                material_data['latex_content'] = material.latex_translation_result
            
            export_data.append(material_data)
        
        # 创建ZIP文件
        zip_buffer = io.BytesIO()
        client_name = client.name.replace(' ', '_').replace('/', '_')
        # 修改日期格式：年月日小时分钟
        date_str = datetime.now().strftime('%Y%m%d_%H%M')
        
        # 获取一次百度翻译的access_token供本次导出使用
        access_token = None
        api_keys = load_api_keys()
        baidu_api_key = api_keys.get('BAIDU_API_KEY')
        baidu_secret_key = api_keys.get('BAIDU_SECRET_KEY')
        
        if baidu_api_key and baidu_secret_key:
            access_token = get_baidu_access_token(baidu_api_key, baidu_secret_key)
            if access_token:
                log_message("获取百度翻译access_token成功，将用于本次导出的文件名翻译")
            else:
                log_message("获取百度翻译access_token失败，文件名将保持原文", "WARN")
        else:
            log_message("百度翻译API未配置，文件名将保持原文", "WARN")
        
        with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
            # 收集文件名对应关系
            file_pairs = []

            # 追踪已处理的PDF会话,避免重复处理
            processed_pdf_sessions = set()

            # 添加实际文件到materials文件夹
            for material in confirmed_materials:
                # 如果是PDF多页的一部分,且还未处理过该会话
                if material.pdf_session_id and material.pdf_session_id not in processed_pdf_sessions:
                    # 标记为已处理
                    processed_pdf_sessions.add(material.pdf_session_id)

                    # 获取该PDF会话的所有页面
                    pdf_pages = Material.query.filter_by(
                        pdf_session_id=material.pdf_session_id,
                        client_id=client_id,
                        confirmed=True
                    ).order_by(Material.pdf_page_number).all()

                    if not pdf_pages:
                        continue

                    # 获取原始PDF名称(去掉页码)
                    pdf_base_name = material.name.rsplit(' - ', 1)[0] if ' - 第' in material.name else material.name

                    # 翻译PDF名称
                    if access_token:
                        pdf_name_en = translate_filename_with_token(pdf_base_name, access_token, 'en')
                    else:
                        pdf_name_en = pdf_base_name

                    # 添加原始PDF文件
                    if material.pdf_original_file and os.path.exists(material.pdf_original_file):
                        original_filename = f"{pdf_base_name}_原文.pdf"
                        zip_file.write(material.pdf_original_file, f"materials/{original_filename}")
                        log_message(f"添加原始PDF: {original_filename}")

                    # 合并所有页面的翻译图片为PDF
                    try:
                        from PIL import Image
                        images = []

                        for page in pdf_pages:
                            log_message(f"处理第 {page.pdf_page_number} 页", "DEBUG")

                            # ✅ 优先使用前端生成的 final_image_path（100%一致）
                            if page.final_image_path:
                                image_path = page.final_image_path
                                log_message(f"✓ 使用前端生成的 final_image_path: {image_path}", "SUCCESS")

                                # 处理路径
                                if not os.path.isabs(image_path):
                                    image_path = os.path.join(app.root_path, image_path)

                                if not os.path.exists(image_path):
                                    log_message(f"final_image_path 文件不存在: {image_path}", "ERROR")
                                    continue

                                try:
                                    img = Image.open(image_path)
                                    if img.mode == 'RGBA':
                                        img = img.convert('RGB')
                                    images.append(img)
                                    log_message(f"✓ 第 {page.pdf_page_number} 页使用前端生成的图片", "SUCCESS")
                                    continue
                                except Exception as e:
                                    log_message(f"打开 final_image 失败: {e}", "ERROR")

                            # 备用方案：从 regions + 原图动态生成
                            if page.edited_regions and page.file_path:
                                try:
                                    log_message(f"从 regions + 原图动态生成", "INFO")

                                    # 获取原图路径
                                    original_path = page.file_path
                                    if not os.path.isabs(original_path):
                                        original_path = os.path.join(app.root_path, original_path)

                                    if not os.path.exists(original_path):
                                        log_message(f"原图不存在: {original_path}", "ERROR")
                                        continue

                                    # 从 regions 生成图片
                                    generated_img = generate_image_from_regions(original_path, page.edited_regions)
                                    images.append(generated_img)
                                    log_message(f"✓ 第 {page.pdf_page_number} 页动态生成成功", "SUCCESS")

                                except Exception as gen_error:
                                    log_message(f"第 {page.pdf_page_number} 页生成失败: {gen_error}", "ERROR")
                                    continue
                            else:
                                log_message(f"第 {page.pdf_page_number} 页没有可用数据，跳过", "WARN")
                                continue

                        # 下面继续处理图片路径（这段代码已经不会被执行，因为上面都是continue）
                        # 保留代码结构避免语法错误
                        if False:  # 永远不执行
                            image_path = None
                            # 处理路径
                            if not os.path.isabs(image_path):
                                log_message(f"路径不是绝对路径，尝试查找: {image_path}", "DEBUG")
                                possible_paths = [
                                    image_path,
                                    os.path.join('uploads', image_path),
                                    os.path.join(app.root_path, 'uploads', image_path),
                                    os.path.join('image_translation_output', image_path)
                                ]
                                found = False
                                for possible_path in possible_paths:
                                    log_message(f"  尝试路径: {possible_path}, 存在={os.path.exists(possible_path)}", "DEBUG")
                                    if os.path.exists(possible_path):
                                        image_path = possible_path
                                        found = True
                                        log_message(f"  ✓ 找到文件: {image_path}", "DEBUG")
                                        break
                                if not found:
                                    log_message(f"  ✗ 所有可能路径都不存在", "ERROR")

                            if os.path.exists(image_path):
                                # 检查文件大小，跳过空文件
                                file_size = os.path.getsize(image_path)
                                if file_size == 0:
                                    log_message(f"✗ 文件是空的(0字节): {image_path}", "ERROR")
                                    log_message(f"跳过第 {page.pdf_page_number} 页", "WARN")
                                    continue

                                try:
                                    img = Image.open(image_path)
                                    if img.mode == 'RGBA':
                                        img = img.convert('RGB')
                                    images.append(img)
                                    log_message(f"✓ 添加PDF页面 {page.pdf_page_number}: {image_path} ({file_size/1024:.1f}KB)", "SUCCESS")
                                except Exception as img_error:
                                    log_message(f"✗ 无法打开图片: {image_path}, 错误: {str(img_error)}", "ERROR")
                                    continue
                            else:
                                log_message(f"✗ 文件不存在: {image_path}", "ERROR")

                        if images:
                            # 生成合并后的PDF
                            merged_pdf_path = os.path.join(app.root_path, 'uploads', f"merged_{pdf_name_en}_{datetime.now().strftime('%Y%m%d%H%M%S')}.pdf")
                            images[0].save(merged_pdf_path, save_all=True, append_images=images[1:] if len(images) > 1 else [], resolution=100.0, quality=95)

                            translated_filename = f"{pdf_name_en}_translated.pdf"
                            zip_file.write(merged_pdf_path, f"materials/{translated_filename}")
                            log_message(f"✓ 合并PDF完成: {len(images)} 页 -> {translated_filename}")

                            # 删除临时合并文件
                            try:
                                os.remove(merged_pdf_path)
                            except:
                                pass

                            # 添加到文件对应关系
                            if original_filename and translated_filename:
                                original_name = os.path.splitext(original_filename)[0]
                                translated_name = os.path.splitext(translated_filename)[0]
                                file_pairs.append(f"{original_name}\n{translated_name}")

                    except Exception as e:
                        log_message(f"PDF合并失败: {str(e)}", "ERROR")

                    # 跳过后续的单页处理
                    continue

                # 如果是PDF的单个页面但已经处理过会话,跳过
                if material.pdf_session_id:
                    continue

                original_filename = None
                translated_filename = None

                # 翻译材料名到英文（仅用于翻译文件），复用access_token
                if access_token:
                    material_name_en = translate_filename_with_token(material.name, access_token, 'en')
                else:
                    material_name_en = material.name  # 翻译失败则使用原名
                
                # 添加原始文件（如果存在）- 保持中文名
                if material.file_path and os.path.exists(material.file_path):
                    original_ext = os.path.splitext(material.original_filename)[1] if material.original_filename else os.path.splitext(material.file_path)[1]
                    original_filename = f"{material.name}_原文{original_ext}"
                    zip_file.write(material.file_path, f"materials/{original_filename}")
                
                # 网页材料使用原始PDF作为"原文"
                elif material.type == 'webpage' and material.original_pdf_path:
                    # 原始PDF文件路径
                    original_pdf_path = os.path.join('original_snapshot', material.original_pdf_path)
                    if os.path.exists(original_pdf_path):
                        original_filename = f"{material.name}_原文.pdf"
                        zip_file.write(original_pdf_path, f"materials/{original_filename}")
                        log_message(f"添加原始网页PDF: {original_pdf_path} -> {original_filename}")
                    else:
                        log_message(f"原始网页PDF不存在: {original_pdf_path}", "WARN")
                        # 如果PDF不存在，创建备用的URL文本文件
                        original_filename = f"{material.name}_网址.txt"
                        url_content = f"网页标题: {material.name}\n网页地址: {material.url}\n"
                        zip_file.writestr(f"materials/{original_filename}", url_content)
                
                # 添加翻译文件 - 使用英文名
                # 处理网页类型材料
                if material.type == 'webpage' and material.translated_image_path:
                    # 网页翻译的PDF文件
                    pdf_path = os.path.join('translated_snapshot', material.translated_image_path)
                    if os.path.exists(pdf_path):
                        translated_filename = f"{material_name_en}_translated.pdf"
                        zip_file.write(pdf_path, f"materials/{translated_filename}")
                        log_message(f"添加网页翻译文件: {pdf_path} -> {translated_filename}")
                    else:
                        log_message(f"网页翻译文件不存在: {pdf_path}", "WARN")
                
                elif (material.selected_result == 'api' and
                    (material.final_image_path or material.edited_image_path or material.translated_image_path)):

                    # 优先级：final_image_path（带文字完整版） > edited_image_path（不带文字） > translated_image_path（API原始翻译）
                    if material.has_edited_version and material.final_image_path:
                        # 最优先：使用带文字的完整版本（用于导出）
                        image_path = material.final_image_path
                        log_message(f"✅ 使用最终图片（带文字完整版）: {image_path}", "SUCCESS")

                        # 如果路径不是绝对路径，尝试几个可能的目录
                        if not os.path.isabs(image_path):
                            possible_paths = [
                                os.path.join('uploads', image_path),
                                os.path.join(app.root_path, 'uploads', image_path),
                                image_path
                            ]

                            found_path = None
                            for possible_path in possible_paths:
                                if os.path.exists(possible_path):
                                    found_path = possible_path
                                    log_message(f"找到最终图片文件: {found_path}", "INFO")
                                    break

                            if not found_path:
                                log_message(f"❌ 最终图片文件不存在，尝试查找路径: {possible_paths}", "ERROR")
                            image_path = found_path

                    elif material.has_edited_version and material.edited_image_path:
                        # 备选：使用编辑后的图片（不带文字版本）
                        image_path = material.edited_image_path
                        log_message(f"⚠️ 使用编辑后的图片（不带文字版）: {image_path}", "WARN")

                        # 如果路径不是绝对路径，尝试几个可能的目录
                        if not os.path.isabs(image_path):
                            possible_paths = [
                                os.path.join('uploads', image_path),
                                os.path.join(app.root_path, 'uploads', image_path),
                                image_path
                            ]

                            found_path = None
                            for possible_path in possible_paths:
                                if os.path.exists(possible_path):
                                    found_path = possible_path
                                    break
                            image_path = found_path
                    else:
                        # 兜底：使用API翻译的图片
                        image_path = material.translated_image_path
                        log_message(f"使用API翻译图片: {image_path}", "INFO")

                        # 如果路径不是绝对路径，尝试几个可能的目录
                        if not os.path.isabs(image_path):
                            possible_paths = [
                                image_path,  # 直接使用存储的路径
                                os.path.join('image_translation_output', image_path),
                                os.path.join('translated_images', image_path),
                                os.path.join('web_translation_output', image_path)
                            ]

                            found_path = None
                            for possible_path in possible_paths:
                                if os.path.exists(possible_path):
                                    found_path = possible_path
                                    break
                            image_path = found_path

                    if image_path and os.path.exists(image_path):
                        # 获取原始文件扩展名，如果没有则使用.jpg
                        original_ext = os.path.splitext(material.original_filename)[1] if material.original_filename else '.jpg'
                        translated_filename = f"{material_name_en}_translated{original_ext}"
                        zip_file.write(image_path, f"materials/{translated_filename}")
                        log_message(f"添加翻译文件: {image_path} -> {translated_filename}")
                    else:
                        log_message(f"翻译文件不存在: {image_path}", "WARN")
                    
                elif (material.selected_result == 'latex' and 
                      material.latex_translation_result):
                    
                    try:
                        latex_data = json.loads(material.latex_translation_result)
                        
                        # 只添加PDF文件（如果存在）
                        if 'pdf_file' in latex_data:
                            pdf_path = latex_data['pdf_file']
                            if os.path.exists(pdf_path):
                                translated_filename = f"{material_name_en}_translated.pdf"
                                zip_file.write(pdf_path, f"materials/{translated_filename}")
                            
                    except json.JSONDecodeError:
                        # 如果不是JSON格式，跳过LaTeX翻译
                        pass
                
                # 如果有原文件和翻译文件，添加到列表中
                if original_filename and translated_filename:
                    # 去掉扩展名
                    original_name = os.path.splitext(original_filename)[0]
                    translated_name = os.path.splitext(translated_filename)[0]
                    file_pairs.append(f"{original_name}\n{translated_name}")
            
            # 创建list.txt文件
            list_content = '\n'.join(file_pairs)
            zip_file.writestr('list.txt', list_content)
        
        zip_buffer.seek(0)
        
        # 返回ZIP文件，使用新的文件名格式：客户名_年月日小时分钟.zip
        filename = f"{client_name}_{date_str}.zip"
        
        # 尝试使用download_name（Flask 2.2+）或 attachment_filename（旧版本）
        try:
            return send_file(
                zip_buffer,
                as_attachment=True,
                download_name=filename,
                mimetype='application/zip'
            )
        except TypeError:
            # 如果download_name不被支持，使用attachment_filename
            zip_buffer.seek(0)
            return send_file(
                zip_buffer,
                as_attachment=True,
                attachment_filename=filename,
                mimetype='application/zip'
            )
        
    except Exception as e:
        log_message(f"导出客户材料失败: {str(e)}", "ERROR")
        return jsonify({
            'success': False,
            'error': '导出失败',
            'message': str(e)
        }), 500

# ========== 用户设置相关API ==========

@app.route('/api/user/settings', methods=['GET'])
@jwt_required()
def get_user_settings():
    """获取用户设置"""
    try:
        current_user_id = get_jwt_identity()
        user = User.query.get(current_user_id)
        
        if not user:
            return jsonify({
                'success': False,
                'error': '用户不存在'
            }), 404
        
        # 返回用户设置
        settings = {
            'basicInfo': {
                'name': user.name,
                'email': user.email,
                'phone': user.phone,
                'lawFirm': user.law_firm
            },
            'notificationSettings': {
                'translationComplete': getattr(user, 'notification_translation_complete', True),
                'translationFailed': getattr(user, 'notification_translation_failed', False),
                'dailySummary': getattr(user, 'notification_daily_summary', False),
                'emailEnabled': user.email_notification if hasattr(user, 'email_notification') else True,
                'browserPushEnabled': getattr(user, 'browser_push_enabled', True)
            },
            'translationPreferences': {
                'retryCount': user.auto_retry_count if hasattr(user, 'auto_retry_count') else 3,
                'enginePriority': getattr(user, 'engine_priority', 'latex')
            }
        }
        
        return jsonify({
            'success': True,
            'settings': settings
        })
        
    except Exception as e:
        log_message(f"获取用户设置失败: {str(e)}", "ERROR")
        return jsonify({
            'success': False,
            'error': '获取设置失败',
            'message': str(e)
        }), 500

@app.route('/api/user/basic-info', methods=['PUT'])
@jwt_required()
def update_basic_info():
    """更新用户基本信息"""
    try:
        current_user_id = get_jwt_identity()
        user = User.query.get(current_user_id)
        
        if not user:
            return jsonify({
                'success': False,
                'error': '用户不存在'
            }), 404
        
        data = request.get_json()
        
        # 更新基本信息
        if 'name' in data:
            user.name = data['name']
        if 'email' in data:
            user.email = data['email']
        if 'phone' in data:
            user.phone = data['phone']
        if 'lawFirm' in data:
            user.law_firm = data['lawFirm']
        
        user.updated_at = datetime.utcnow()
        db.session.commit()
        
        log_message(f"用户基本信息更新成功: {current_user_id}")
        
        return jsonify({
            'success': True,
            'message': '基本信息更新成功',
            'user': user.to_dict()
        })
        
    except Exception as e:
        log_message(f"更新用户基本信息失败: {str(e)}", "ERROR")
        db.session.rollback()
        return jsonify({
            'success': False,
            'error': '更新失败',
            'message': str(e)
        }), 500

@app.route('/api/user/change-password', methods=['PUT'])
@jwt_required()
def change_password():
    """修改用户密码"""
    try:
        current_user_id = get_jwt_identity()
        user = User.query.get(current_user_id)
        
        if not user:
            return jsonify({
                'success': False,
                'error': '用户不存在'
            }), 404
        
        data = request.get_json()
        current_password = data.get('currentPassword')
        new_password = data.get('newPassword')
        
        if not current_password or not new_password:
            return jsonify({
                'success': False,
                'error': '请提供当前密码和新密码'
            }), 400
        
        # 验证当前密码
        if not check_password_hash(user.password, current_password):
            return jsonify({
                'success': False,
                'error': '当前密码不正确'
            }), 400
        
        # 验证新密码长度
        if len(new_password) < 6:
            return jsonify({
                'success': False,
                'error': '新密码长度至少为6位'
            }), 400
        
        # 更新密码
        user.password = generate_password_hash(new_password)
        user.updated_at = datetime.utcnow()
        db.session.commit()
        
        log_message(f"用户密码修改成功: {current_user_id}")
        
        return jsonify({
            'success': True,
            'message': '密码修改成功'
        })
        
    except Exception as e:
        log_message(f"修改密码失败: {str(e)}", "ERROR")
        db.session.rollback()
        return jsonify({
            'success': False,
            'error': '密码修改失败',
            'message': str(e)
        }), 500

# ========== 错误处理 ========== 

@app.errorhandler(404)
def not_found(error):
    return jsonify({
        'success': False,
        'error': '接口不存在'
    }), 404

@app.errorhandler(500)
def internal_error(error):
    db.session.rollback()
    return jsonify({
        'success': False,
        'error': '服务器内部错误'
    }), 500

@app.errorhandler(Exception)
def handle_exception(e):
    log_message(f"未处理的异常: {str(e)}", "ERROR")
    db.session.rollback()
    return jsonify({
        'success': False,
        'error': '服务器内部错误',
        'message': str(e)
    }), 500

# ========== 路由映射 ==========
# 添加所有路由映射
app.add_url_rule('/api/clients/<client_id>/export', 'export_client_materials', 
                export_client_materials, methods=['GET'])

if __name__ == '__main__':
    # 确保工作目录在脚本所在目录
    script_dir = os.path.dirname(os.path.abspath(__file__))
    os.chdir(script_dir)
    print(f"工作目录: {os.getcwd()}")
    
    print("启动智能文书翻译平台 - 完整版后端服务 v4.0...")
    print("功能: 用户认证、客户管理、材料管理、完整翻译服务")
    print("认证方式: JWT Bearer Token")
    print("数据库: SQLite (translation_platform.db)")
    print("测试用户: test@example.com / password123")
    print(f"OpenAI可用: {OPENAI_AVAILABLE}")
    print(f"Selenium可用: {SELENIUM_AVAILABLE}")
    print()
    
    # 初始化数据库并添加新列
    with app.app_context():
        # 强制刷新元数据解决缓存问题
        try:
            # 1. 释放所有数据库连接
            db.engine.dispose()
            
            # 2. 不要清除元数据！这会移除所有模型定义
            # db.metadata.clear()  # 这是问题所在！
            
            # 3. 重新创建所有表（基于模型定义）
            db.create_all()
            
            # 3.5 手动确保Client表有所有必要的列
            # 这是一个临时解决方案，用于解决SQLAlchemy可能的bug
            try:
                from sqlalchemy import text as sql_text
                with db.engine.begin() as conn:
                    # 添加缺失的列（如果不存在）
                    missing_columns = [
                        ("ALTER TABLE clients ADD COLUMN phone VARCHAR(50)", "phone"),
                        ("ALTER TABLE clients ADD COLUMN email VARCHAR(100)", "email"),
                        ("ALTER TABLE clients ADD COLUMN address TEXT", "address"),
                        ("ALTER TABLE clients ADD COLUMN notes TEXT", "notes"),
                        ("ALTER TABLE clients ADD COLUMN is_archived BOOLEAN DEFAULT 0", "is_archived"),
                        ("ALTER TABLE clients ADD COLUMN archived_at DATETIME", "archived_at"),
                        ("ALTER TABLE clients ADD COLUMN archived_reason VARCHAR(500)", "archived_reason"),
                        ("ALTER TABLE users ADD COLUMN phone VARCHAR(50)", "users.phone"),
                        ("ALTER TABLE users ADD COLUMN law_firm_id VARCHAR(36)", "users.law_firm_id"),
                        ("ALTER TABLE materials ADD COLUMN processing_step VARCHAR(50) DEFAULT 'uploaded'", "processing_step"),
                        ("ALTER TABLE materials ADD COLUMN processing_progress INTEGER DEFAULT 0", "processing_progress")
                    ]
                    
                    for sql, col_name in missing_columns:
                        try:
                            conn.execute(sql_text(sql))
                            log_message(f"添加列: {col_name}", "INFO")
                        except Exception as e:
                            if "duplicate column name" in str(e):
                                pass  # 列已存在，忽略
                            else:
                                log_message(f"添加列 {col_name} 失败: {e}", "WARNING")
            except Exception as e:
                log_message(f"手动添加列时出错: {e}", "WARNING")
            
            # 4. 强制重新加载元数据
            db.metadata.reflect(bind=db.engine)
            
            log_message("数据库元数据已完全重置并初始化成功", "SUCCESS")
            
            # 5. 验证表结构
            inspector = db.inspect(db.engine)
            tables = inspector.get_table_names()
            log_message(f"数据库表: {tables}", "INFO")
            
            if 'clients' in tables:
                columns = [col['name'] for col in inspector.get_columns('clients')]
                log_message(f"clients表列: {columns}", "INFO")
                
        except Exception as e:
            log_message(f"数据库初始化失败: {e}", "ERROR")
            import traceback
            traceback.print_exc()
        
        # 添加新列（如果不存在）
        try:
            db.engine.execute(text("ALTER TABLE materials ADD COLUMN translated_image_path VARCHAR(500)"))
            log_message("添加translated_image_path列", "SUCCESS")
        except Exception:
            pass  # 列已存在
        
        try:
            db.engine.execute(text("ALTER TABLE materials ADD COLUMN translation_text_info TEXT"))
            log_message("添加translation_text_info列", "SUCCESS")
        except Exception:
            pass  # 列已存在
            
        try:
            db.engine.execute(text("ALTER TABLE materials ADD COLUMN translation_error TEXT"))
            log_message("添加translation_error列", "SUCCESS")
        except Exception:
            pass  # 列已存在
            
        try:
            db.engine.execute(text("ALTER TABLE materials ADD COLUMN latex_translation_result TEXT"))
            log_message("添加latex_translation_result列", "SUCCESS")
        except Exception:
            pass  # 列已存在
            
        try:
            db.engine.execute(text("ALTER TABLE materials ADD COLUMN latex_translation_error TEXT"))
            log_message("添加latex_translation_error列", "SUCCESS")
        except Exception:
            pass  # 列已存在

        try:
            db.engine.execute(text("ALTER TABLE materials ADD COLUMN llm_translation_result TEXT"))
            log_message("添加llm_translation_result列", "SUCCESS")
        except Exception:
            pass  # 列已存在

        # 添加PDF多页相关字段
        try:
            db.engine.execute(text("ALTER TABLE materials ADD COLUMN pdf_session_id VARCHAR(100)"))
            log_message("添加pdf_session_id列", "SUCCESS")
        except Exception:
            pass

        try:
            db.engine.execute(text("ALTER TABLE materials ADD COLUMN pdf_page_number INTEGER"))
            log_message("添加pdf_page_number列", "SUCCESS")
        except Exception:
            pass

        try:
            db.engine.execute(text("ALTER TABLE materials ADD COLUMN pdf_total_pages INTEGER"))
            log_message("添加pdf_total_pages列", "SUCCESS")
        except Exception:
            pass

        try:
            db.engine.execute(text("ALTER TABLE materials ADD COLUMN pdf_original_file VARCHAR(500)"))
            log_message("添加pdf_original_file列", "SUCCESS")
        except Exception:
            pass


    # ✅ 使用 SocketIO 运行（支持 WebSocket）
    if WEBSOCKET_ENABLED:
        print('[WebSocket] 使用 SocketIO 运行服务器')
        socketio.run(app, host='0.0.0.0', port=5010, debug=True)
    else:
        print('[WebSocket] WebSocket 未启用，使用普通模式运行')
        app.run(debug=True, host='0.0.0.0', port=5010)

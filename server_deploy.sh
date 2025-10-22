#!/bin/bash

# 翻译平台后端服务器自动部署脚本
# 使用方法: 
#   1. 上传此脚本到服务器
#   2. chmod +x server_deploy.sh
#   3. ./server_deploy.sh

set -e

# 颜色输出
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# 配置变量
APP_NAME="translation-platform"
APP_DIR="/home/translation/backend"
APP_USER="translation"
PYTHON_VERSION="python3"

# 日志函数
log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

log_step() {
    echo -e "${BLUE}==== $1 ====${NC}"
}

# 检查是否为 root 用户
check_root() {
    if [ "$EUID" -eq 0 ]; then 
        log_warn "检测到 root 用户，建议使用普通用户运行此脚本"
        log_warn "按 Ctrl+C 取消，或等待 5 秒继续..."
        sleep 5
    fi
}

# 检测操作系统
detect_os() {
    log_step "检测操作系统"
    
    if [ -f /etc/os-release ]; then
        . /etc/os-release
        OS=$NAME
        VER=$VERSION_ID
        log_info "操作系统: $OS $VER"
    else
        log_error "无法检测操作系统"
        exit 1
    fi
}

# 安装系统依赖
install_dependencies() {
    log_step "安装系统依赖"
    
    log_info "更新软件包列表..."
    sudo apt update
    
    log_info "安装基础工具..."
    sudo apt install -y git curl wget vim htop unzip
    
    log_info "安装 Python 和开发工具..."
    sudo apt install -y python3 python3-pip python3-venv python3-dev
    
    log_info "安装系统库（OpenCV 依赖）..."
    sudo apt install -y libgl1-mesa-glx libglib2.0-0
    
    log_info "安装 Chrome/Chromium（Selenium 需要）..."
    if ! command -v chromium-browser &> /dev/null; then
        sudo apt install -y chromium-browser chromium-chromedriver
    else
        log_info "Chromium 已安装"
    fi
    
    log_info "安装 Nginx..."
    sudo apt install -y nginx
    
    log_info "安装 Supervisor..."
    sudo apt install -y supervisor
    
    log_info "系统依赖安装完成"
}

# 创建应用目录
setup_directories() {
    log_step "创建应用目录"
    
    if [ ! -d "$APP_DIR" ]; then
        log_info "创建应用目录: $APP_DIR"
        mkdir -p $APP_DIR
    fi
    
    cd $APP_DIR
    
    log_info "创建必要的子目录..."
    mkdir -p uploads downloads outputs logs temp config instance
    
    log_info "设置目录权限..."
    chmod 755 uploads downloads outputs logs temp
    
    log_info "目录创建完成"
}

# 创建虚拟环境
setup_virtualenv() {
    log_step "配置 Python 虚拟环境"
    
    cd $APP_DIR
    
    if [ -d "venv" ]; then
        log_warn "虚拟环境已存在，跳过创建"
    else
        log_info "创建虚拟环境..."
        $PYTHON_VERSION -m venv venv
    fi
    
    log_info "激活虚拟环境..."
    source venv/bin/activate
    
    log_info "升级 pip..."
    pip install --upgrade pip
    
    log_info "虚拟环境配置完成"
}

# 安装 Python 依赖
install_python_dependencies() {
    log_step "安装 Python 依赖"
    
    cd $APP_DIR
    source venv/bin/activate
    
    if [ -f "requirements.txt" ]; then
        log_info "从 requirements.txt 安装依赖..."
        pip install -r requirements.txt
        log_info "Python 依赖安装完成"
    else
        log_warn "requirements.txt 不存在，跳过依赖安装"
    fi
}

# 配置环境变量
setup_environment() {
    log_step "配置环境变量"
    
    cd $APP_DIR/config
    
    # 检查 API Key 文件
    if [ ! -f "openai_api_key.txt" ]; then
        log_warn "openai_api_key.txt 不存在"
        read -p "请输入 OpenAI API Key: " openai_key
        echo "$openai_key" > openai_api_key.txt
        chmod 600 openai_api_key.txt
    fi
    
    if [ ! -f "baidu_api_key.txt" ]; then
        log_warn "baidu_api_key.txt 不存在"
        read -p "请输入百度 API Key: " baidu_key
        echo "$baidu_key" > baidu_api_key.txt
        chmod 600 baidu_api_key.txt
    fi
    
    if [ ! -f "baidu_secret_key.txt" ]; then
        log_warn "baidu_secret_key.txt 不存在"
        read -p "请输入百度 Secret Key: " baidu_secret
        echo "$baidu_secret" > baidu_secret_key.txt
        chmod 600 baidu_secret_key.txt
    fi
    
    log_info "环境变量配置完成"
}

# 初始化数据库
init_database() {
    log_step "初始化数据库"
    
    cd $APP_DIR
    source venv/bin/activate
    
    if [ -f "init_db.py" ]; then
        log_info "运行数据库初始化脚本..."
        python init_db.py
    else
        log_warn "init_db.py 不存在，尝试手动初始化..."
        python << EOF
from app import app, db
with app.app_context():
    db.create_all()
    print("数据库初始化成功")
EOF
    fi
    
    log_info "数据库初始化完成"
}

# 配置 Nginx
setup_nginx() {
    log_step "配置 Nginx"
    
    local nginx_config="/etc/nginx/sites-available/$APP_NAME"
    
    log_info "创建 Nginx 配置文件..."
    
    # 获取服务器 IP
    SERVER_IP=$(curl -s ifconfig.me)
    
    sudo tee $nginx_config > /dev/null << 'EOF'
server {
    listen 80;
    server_name _;

    client_max_body_size 100M;

    location / {
        proxy_pass http://127.0.0.1:5010;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        
        proxy_read_timeout 300s;
        proxy_connect_timeout 300s;
        proxy_send_timeout 300s;
    }

    location /uploads {
        alias /home/translation/backend/uploads;
        expires 7d;
    }

    location /outputs {
        alias /home/translation/backend/outputs;
        expires 7d;
    }
}
EOF
    
    # 启用配置
    if [ -L "/etc/nginx/sites-enabled/$APP_NAME" ]; then
        log_info "Nginx 配置已启用"
    else
        log_info "启用 Nginx 配置..."
        sudo ln -s $nginx_config /etc/nginx/sites-enabled/
    fi
    
    # 删除默认配置
    if [ -L "/etc/nginx/sites-enabled/default" ]; then
        log_info "删除默认 Nginx 配置..."
        sudo rm /etc/nginx/sites-enabled/default
    fi
    
    # 测试配置
    log_info "测试 Nginx 配置..."
    sudo nginx -t
    
    # 重启 Nginx
    log_info "重启 Nginx..."
    sudo systemctl restart nginx
    sudo systemctl enable nginx
    
    log_info "Nginx 配置完成"
    log_info "您的服务器 IP: $SERVER_IP"
}

# 配置 Supervisor
setup_supervisor() {
    log_step "配置 Supervisor"
    
    local supervisor_config="/etc/supervisor/conf.d/$APP_NAME.conf"
    
    log_info "创建 Supervisor 配置文件..."
    
    sudo tee $supervisor_config > /dev/null << EOF
[program:$APP_NAME]
command=$APP_DIR/venv/bin/gunicorn -c gunicorn_config.py app:app
directory=$APP_DIR
user=$USER
autostart=true
autorestart=true
startsecs=10
stopwaitsecs=600
redirect_stderr=true
stdout_logfile=$APP_DIR/logs/supervisor.log
stdout_logfile_maxbytes=50MB
stdout_logfile_backups=10
stderr_logfile=$APP_DIR/logs/supervisor_error.log
environment=PATH="$APP_DIR/venv/bin",LANG="en_US.UTF-8",LC_ALL="en_US.UTF-8"
EOF
    
    # 创建日志文件
    touch $APP_DIR/logs/supervisor.log
    touch $APP_DIR/logs/supervisor_error.log
    
    # 重新加载配置
    log_info "重新加载 Supervisor 配置..."
    sudo supervisorctl reread
    sudo supervisorctl update
    
    # 启动服务
    log_info "启动应用..."
    sudo supervisorctl restart $APP_NAME || sudo supervisorctl start $APP_NAME
    
    # 查看状态
    sleep 3
    sudo supervisorctl status $APP_NAME
    
    log_info "Supervisor 配置完成"
}

# 配置防火墙
setup_firewall() {
    log_step "配置防火墙"
    
    if command -v ufw &> /dev/null; then
        log_info "配置 UFW 防火墙..."
        
        # 允许 SSH
        sudo ufw allow ssh
        sudo ufw allow 22/tcp
        
        # 允许 HTTP 和 HTTPS
        sudo ufw allow 80/tcp
        sudo ufw allow 443/tcp
        
        # 启用防火墙
        echo "y" | sudo ufw enable
        
        # 查看状态
        sudo ufw status
        
        log_info "防火墙配置完成"
    else
        log_warn "UFW 未安装，跳过防火墙配置"
    fi
}

# 验证部署
verify_deployment() {
    log_step "验证部署"
    
    log_info "检查服务状态..."
    sudo supervisorctl status $APP_NAME
    
    log_info "检查 Nginx 状态..."
    sudo systemctl status nginx --no-pager
    
    log_info "测试 API 连接..."
    sleep 2
    
    if curl -s http://localhost:5010 > /dev/null; then
        log_info "✅ API 服务正常运行"
    else
        log_warn "⚠️ API 服务可能未正常启动，请检查日志"
    fi
    
    # 显示服务器信息
    log_info ""
    log_info "================================"
    log_info "部署完成！"
    log_info "================================"
    log_info "服务器 IP: $(curl -s ifconfig.me)"
    log_info "API 地址: http://$(curl -s ifconfig.me)"
    log_info ""
    log_info "常用命令："
    log_info "  查看日志: tail -f $APP_DIR/logs/error.log"
    log_info "  重启服务: sudo supervisorctl restart $APP_NAME"
    log_info "  查看状态: sudo supervisorctl status $APP_NAME"
    log_info "================================"
}

# 主函数
main() {
    echo -e "${BLUE}"
    echo "========================================"
    echo "   翻译平台后端自动部署脚本"
    echo "========================================"
    echo -e "${NC}"
    
    check_root
    detect_os
    
    log_warn "此脚本将安装并配置以下组件："
    log_warn "  - Python 虚拟环境"
    log_warn "  - Nginx"
    log_warn "  - Supervisor"
    log_warn "  - 系统依赖"
    log_warn ""
    log_warn "按 Enter 继续，或 Ctrl+C 取消..."
    read
    
    install_dependencies
    setup_directories
    setup_virtualenv
    install_python_dependencies
    setup_environment
    init_database
    setup_nginx
    setup_supervisor
    setup_firewall
    verify_deployment
    
    echo -e "${GREEN}"
    echo "🎉 部署成功！"
    echo -e "${NC}"
}

# 运行主函数
main


# 后端部署完整指南

## 📋 前置准备清单

### 1. 服务器信息
- [ ] 服务器 IP 地址
- [ ] SSH 登录信息
- [ ] 域名（可选，建议配置）

### 2. API 密钥准备
- [ ] OpenAI API Key
- [ ] 百度翻译 API Key 和 Secret Key

### 3. 本地准备
- [ ] 后端代码已准备就绪
- [ ] 所有配置文件已检查

---

## 🖥️ 服务器规格建议

### 推荐配置（适合中小型使用）
- **操作系统**: Ubuntu 20.04/22.04 LTS
- **CPU**: 4核心
- **内存**: 8GB RAM
- **存储**: 80GB SSD
- **带宽**: 10Mbps

### VPS 服务商推荐
1. **阿里云 ECS**（适合中国用户）
2. **腾讯云 CVM**（适合中国用户）
3. **Vultr**（国际用户）
4. **DigitalOcean**（国际用户）
5. **AWS Lightsail**（全球）

---

## 📦 第一步：服务器初始化

### 1.1 连接到服务器
```bash
# 使用 SSH 连接（Windows 用户可以用 PowerShell 或 PuTTY）
ssh root@your_server_ip

# 首次登录建议修改 root 密码
passwd
```

### 1.2 更新系统
```bash
# 更新软件包列表
sudo apt update
sudo apt upgrade -y

# 安装基础工具
sudo apt install -y git curl wget vim htop
```

### 1.3 创建应用用户（安全考虑）
```bash
# 创建专用用户
sudo adduser translation
sudo usermod -aG sudo translation

# 切换到新用户
su - translation
```

### 1.4 安装 Python 3.10+
```bash
# 安装 Python 和相关工具
sudo apt install -y python3.10 python3.10-venv python3-pip

# 验证安装
python3 --version
```

### 1.5 安装系统依赖
```bash
# 安装 OpenCV 依赖
sudo apt install -y libgl1-mesa-glx libglib2.0-0

# 安装 Chrome/Chromium（Selenium 需要）
sudo apt install -y chromium-browser chromium-chromedriver

# 或者安装 Google Chrome
wget https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb
sudo apt install -y ./google-chrome-stable_current_amd64.deb

# 安装 Nginx（反向代理）
sudo apt install -y nginx

# 安装 Supervisor（进程管理）
sudo apt install -y supervisor
```

---

## 📂 第二步：上传代码到服务器

### 方式 1: 使用 SCP（从本地 Windows）
```powershell
# 在本地 Windows PowerShell 中运行
cd F:\Python-Project\FL_CC_Production

# 打包后端代码
Compress-Archive -Path backend -DestinationPath backend.zip

# 上传到服务器
scp backend.zip translation@your_server_ip:/home/translation/
```

### 方式 2: 使用 Git（推荐）
```bash
# 在服务器上执行
cd /home/translation

# 创建后端仓库（如果还没有）
git init
git remote add origin https://github.com/Zac-Chen-2024/FileTranslationBackend.git

# 或者直接克隆
git clone https://github.com/Zac-Chen-2024/FileTranslationBackend.git backend
cd backend
```

### 方式 3: 直接在服务器创建文件
```bash
# 创建项目目录
mkdir -p /home/translation/backend
cd /home/translation/backend

# 手动上传文件（可以使用 SFTP 工具如 FileZilla）
```

---

## 🔧 第三步：配置后端应用

### 3.1 创建虚拟环境
```bash
cd /home/translation/backend

# 创建虚拟环境
python3 -m venv venv

# 激活虚拟环境
source venv/bin/activate
```

### 3.2 安装依赖
```bash
# 升级 pip
pip install --upgrade pip

# 安装所有依赖
pip install -r requirements.txt

# 如果安装失败，可以尝试
pip install --no-cache-dir -r requirements.txt
```

### 3.3 配置环境变量
```bash
# 进入 config 目录
cd config

# 创建 OpenAI API Key 文件
echo "your_openai_api_key" > openai_api_key.txt

# 创建百度 API 文件
echo "your_baidu_api_key" > baidu_api_key.txt
echo "your_baidu_secret_key" > baidu_secret_key.txt

# 设置文件权限（仅所有者可读）
chmod 600 *.txt

# 返回后端目录
cd ..
```

### 3.4 创建必要的目录
```bash
# 创建上传、输出、日志等目录
mkdir -p uploads downloads outputs logs temp

# 设置权限
chmod 755 uploads downloads outputs logs temp
```

### 3.5 初始化数据库
```bash
# 确保虚拟环境已激活
source venv/bin/activate

# 运行初始化脚本
python init_db.py

# 或者手动初始化
python << EOF
from app import app, db
with app.app_context():
    db.create_all()
    print("数据库初始化成功！")
EOF
```

---

## 🚀 第四步：配置 Gunicorn

### 4.1 检查 Gunicorn 配置
```bash
# 查看配置文件
cat gunicorn_config.py

# 配置文件已经存在，主要参数：
# - 端口: 5010
# - Workers: CPU核心数 × 2 + 1
# - 超时: 300秒
```

### 4.2 测试运行
```bash
# 激活虚拟环境
source venv/bin/activate

# 启动 Gunicorn
gunicorn -c gunicorn_config.py app:app

# 如果成功，按 Ctrl+C 停止
```

---

## 🌐 第五步：配置 Nginx

### 5.1 创建 Nginx 配置文件
```bash
sudo vim /etc/nginx/sites-available/translation-platform
```

### 5.2 添加以下配置
```nginx
server {
    listen 80;
    server_name your_domain.com;  # 或者使用 IP 地址

    # 最大上传文件大小
    client_max_body_size 100M;

    # API 代理
    location / {
        proxy_pass http://127.0.0.1:5010;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        
        # 超时设置（处理大文件）
        proxy_read_timeout 300s;
        proxy_connect_timeout 300s;
        proxy_send_timeout 300s;
    }

    # 静态文件服务
    location /uploads {
        alias /home/translation/backend/uploads;
        expires 7d;
        add_header Cache-Control "public, immutable";
    }

    location /outputs {
        alias /home/translation/backend/outputs;
        expires 7d;
        add_header Cache-Control "public, immutable";
    }

    # CORS 头部（如果需要）
    add_header Access-Control-Allow-Origin "https://zac-chen-2024.github.io" always;
    add_header Access-Control-Allow-Methods "GET, POST, PUT, DELETE, OPTIONS" always;
    add_header Access-Control-Allow-Headers "Authorization, Content-Type" always;
}
```

### 5.3 启用配置
```bash
# 创建符号链接
sudo ln -s /etc/nginx/sites-available/translation-platform /etc/nginx/sites-enabled/

# 删除默认配置
sudo rm /etc/nginx/sites-enabled/default

# 测试配置
sudo nginx -t

# 重启 Nginx
sudo systemctl restart nginx
sudo systemctl enable nginx
```

---

## 🔄 第六步：配置 Supervisor（进程守护）

### 6.1 创建 Supervisor 配置
```bash
sudo vim /etc/supervisor/conf.d/translation-platform.conf
```

### 6.2 添加以下内容
```ini
[program:translation-platform]
command=/home/translation/backend/venv/bin/gunicorn -c gunicorn_config.py app:app
directory=/home/translation/backend
user=translation
autostart=true
autorestart=true
startsecs=10
stopwaitsecs=600
redirect_stderr=true
stdout_logfile=/home/translation/backend/logs/supervisor.log
stdout_logfile_maxbytes=50MB
stdout_logfile_backups=10
stderr_logfile=/home/translation/backend/logs/supervisor_error.log
environment=PATH="/home/translation/backend/venv/bin",LANG="en_US.UTF-8",LC_ALL="en_US.UTF-8"
```

### 6.3 启动服务
```bash
# 创建日志文件
touch /home/translation/backend/logs/supervisor.log
touch /home/translation/backend/logs/supervisor_error.log

# 重新加载配置
sudo supervisorctl reread
sudo supervisorctl update

# 启动应用
sudo supervisorctl start translation-platform

# 查看状态
sudo supervisorctl status translation-platform
```

---

## 🔒 第七步：配置防火墙

```bash
# 启用 UFW 防火墙
sudo ufw enable

# 允许 SSH（重要！）
sudo ufw allow ssh
sudo ufw allow 22/tcp

# 允许 HTTP 和 HTTPS
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp

# 查看状态
sudo ufw status
```

---

## 🔐 第八步：配置 HTTPS（可选但推荐）

### 8.1 使用 Let's Encrypt 免费证书
```bash
# 安装 Certbot
sudo apt install -y certbot python3-certbot-nginx

# 获取证书（将自动配置 Nginx）
sudo certbot --nginx -d your_domain.com

# 设置自动续期
sudo certbot renew --dry-run
```

---

## ✅ 第九步：验证部署

### 9.1 检查服务状态
```bash
# 检查 Supervisor
sudo supervisorctl status

# 检查 Nginx
sudo systemctl status nginx

# 检查日志
tail -f /home/translation/backend/logs/error.log
tail -f /home/translation/backend/logs/supervisor.log
```

### 9.2 测试 API
```bash
# 测试健康检查（如果有）
curl http://your_server_ip/health

# 或者测试主页
curl http://your_server_ip/
```

### 9.3 从浏览器访问
```
http://your_server_ip
或
https://your_domain.com
```

---

## 🔄 第十步：更新前端配置

在您的前端项目中更新 API 地址：

```bash
# 在本地编辑 frontend/.env.production
cd F:\Python-Project\FL_CC_Production\frontend
```

编辑 `.env.production` 文件：
```env
REACT_APP_API_URL=http://your_server_ip:80
# 或者如果配置了 HTTPS
REACT_APP_API_URL=https://your_domain.com
```

然后重新部署前端：
```bash
npm run deploy
```

---

## 🛠️ 常用维护命令

### 查看日志
```bash
# 应用错误日志
tail -f /home/translation/backend/logs/error.log

# 访问日志
tail -f /home/translation/backend/logs/access.log

# Supervisor 日志
tail -f /home/translation/backend/logs/supervisor.log

# Nginx 日志
sudo tail -f /var/log/nginx/access.log
sudo tail -f /var/log/nginx/error.log
```

### 重启服务
```bash
# 重启应用
sudo supervisorctl restart translation-platform

# 重启 Nginx
sudo systemctl restart nginx

# 重启所有
sudo supervisorctl restart all
sudo systemctl restart nginx
```

### 更新代码
```bash
cd /home/translation/backend

# 拉取最新代码
git pull

# 激活虚拟环境
source venv/bin/activate

# 更新依赖
pip install -r requirements.txt

# 重启服务
sudo supervisorctl restart translation-platform
```

### 数据库备份
```bash
# 手动备份
cp /home/translation/backend/instance/translation_platform.db \
   /home/translation/backups/translation_platform_$(date +%Y%m%d).db

# 设置自动备份（添加到 crontab）
crontab -e
# 添加以下行（每天凌晨 2 点备份）
0 2 * * * cp /home/translation/backend/instance/translation_platform.db /home/translation/backups/translation_platform_$(date +\%Y\%m\%d).db
```

---

## ⚠️ 故障排查

### 问题 1: 502 Bad Gateway
```bash
# 检查 Gunicorn 是否运行
sudo supervisorctl status translation-platform

# 查看错误日志
tail -f /home/translation/backend/logs/error.log

# 重启服务
sudo supervisorctl restart translation-platform
```

### 问题 2: 文件上传失败
```bash
# 检查目录权限
ls -la /home/translation/backend/uploads

# 修复权限
sudo chown -R translation:translation /home/translation/backend/uploads
chmod 755 /home/translation/backend/uploads
```

### 问题 3: 内存不足
```bash
# 查看内存使用
free -h
htop

# 添加 Swap 空间
sudo fallocate -l 4G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
```

### 问题 4: CPU 占用过高
```bash
# 调整 Gunicorn workers 数量
# 编辑 gunicorn_config.py
vim /home/translation/backend/gunicorn_config.py

# 修改 workers 数量（例如从 9 改为 4）
workers = 4

# 重启服务
sudo supervisorctl restart translation-platform
```

---

## 📊 性能监控

### 安装监控工具
```bash
# 安装 htop
sudo apt install -y htop

# 实时查看资源使用
htop

# 查看磁盘使用
df -h

# 查看网络连接
sudo netstat -tuln
```

---

## 🔐 安全加固

1. **修改 SSH 端口**
2. **禁用 root 登录**
3. **配置 fail2ban 防止暴力破解**
4. **定期更新系统和依赖**
5. **使用环境变量存储敏感信息**
6. **启用 HTTPS**
7. **配置防火墙规则**

---

## 📞 技术支持

如遇问题，请检查：
1. 日志文件
2. 服务器资源（CPU、内存、磁盘）
3. 网络连接
4. API 密钥是否正确

祝部署顺利！🎉


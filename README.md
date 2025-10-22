# 翻译平台后端 API

## 概述

这是翻译平台的后端服务，提供完整的RESTful API，支持文档翻译、用户管理、材料管理等功能。

## 功能特性

- 🔐 用户认证与授权（JWT）
- 📄 多格式文档支持（PDF、Word、图片、网页）
- 🤖 AI翻译（OpenAI GPT、百度翻译）
- 📁 文件上传与管理
- 🖼️ 图像处理与编辑
- 📊 材料批量管理
- 🔄 实时翻译状态跟踪

## API端点列表

### 认证相关
- `POST /api/auth/signup` - 用户注册
- `POST /api/auth/signin` - 用户登录
- `POST /api/auth/logout` - 用户登出
- `GET /api/auth/user` - 获取当前用户信息

### 客户管理
- `GET /api/clients` - 获取客户列表
- `POST /api/clients` - 创建新客户
- `PUT /api/clients/<client_id>` - 更新客户信息
- `DELETE /api/clients/<client_id>` - 删除客户
- `PUT /api/clients/<client_id>/archive` - 归档客户
- `PUT /api/clients/<client_id>/unarchive` - 取消归档

### 材料管理
- `GET /api/clients/<client_id>/materials` - 获取材料列表
- `POST /api/clients/<client_id>/materials/upload` - 上传材料文件
- `POST /api/clients/<client_id>/materials/urls` - 添加网页材料
- `DELETE /api/materials/<material_id>` - 删除材料
- `PUT /api/materials/<material_id>` - 更新材料信息
- `POST /api/materials/<material_id>/confirm` - 确认材料
- `POST /api/materials/<material_id>/unconfirm` - 取消确认

### 翻译功能
- `POST /api/clients/<client_id>/materials/translate` - 批量翻译
- `POST /api/materials/<material_id>/llm-translate` - LLM翻译
- `POST /api/materials/<material_id>/retranslate` - 重新翻译
- `POST /api/materials/<material_id>/retry-latex` - 重试LaTeX翻译
- `POST /api/ai-revise-text` - AI文本修订
- `POST /api/ai-global-optimize` - AI全局优化

### 图像编辑
- `POST /api/materials/<material_id>/edit` - 编辑材料
- `POST /api/materials/<material_id>/save-edited-image` - 保存编辑后的图像
- `POST /api/materials/<material_id>/rotate` - 旋转图像

### 特殊翻译
- `POST /api/poster-translate` - 海报翻译
- `POST /api/latex-translate` - LaTeX翻译
- `POST /api/image-translate` - 图片翻译
- `POST /api/webpage-google-translate` - 网页翻译

### 文件下载
- `GET /download/image/<filename>` - 下载图片
- `GET /download/poster/<filename>` - 下载海报
- `GET /download/latex/<filename>` - 下载LaTeX
- `GET /preview/translated/<filename>` - 预览翻译文件

### 用户设置
- `GET /api/user/settings` - 获取用户设置
- `PUT /api/user/basic-info` - 更新基本信息
- `PUT /api/user/change-password` - 修改密码

### PDF处理
- `POST /api/pdf/split-pages` - 分割PDF页面
- `POST /api/pdf/save-page-edit` - 保存PDF页面编辑
- `POST /api/pdf/merge-pages` - 合并PDF页面

### 系统
- `GET /` - 首页
- `GET /health` - 健康检查

## 快速开始

### 1. 安装依赖

```bash
# 创建虚拟环境
python -m venv venv

# 激活虚拟环境
# Windows:
venv\Scripts\activate
# Linux/Mac:
source venv/bin/activate

# 安装依赖
pip install -r requirements.txt
```

### 2. 配置环境变量

创建 `.env` 文件：

```env
# Flask配置
FLASK_APP=app.py
FLASK_ENV=development
SECRET_KEY=your-secret-key-here

# 数据库
DATABASE_URL=sqlite:///translation_platform.db

# OpenAI配置
OPENAI_API_KEY=your-openai-api-key
OPENAI_BASE_URL=https://api.openai.com/v1
OPENAI_MODEL=gpt-4-turbo-preview

# 百度翻译配置（可选）
BAIDU_APP_ID=your-baidu-app-id
BAIDU_SECRET_KEY=your-baidu-secret-key

# JWT配置
JWT_SECRET_KEY=your-jwt-secret-key
JWT_ACCESS_TOKEN_EXPIRES=86400

# 文件上传配置
MAX_CONTENT_LENGTH=104857600
UPLOAD_FOLDER=uploads
OUTPUT_FOLDER=outputs

# CORS配置
CORS_ORIGINS=http://localhost:3000,https://yourdomain.com
```

### 3. 初始化数据库

```bash
python init_db.py
```

### 4. 启动服务器

#### 开发环境
```bash
# 方法1：直接运行
python app.py

# 方法2：使用启动脚本
python run_server.py --mode dev

# 方法3：使用Flask命令
flask run --host=0.0.0.0 --port=5010
```

#### 生产环境
```bash
# 使用Gunicorn
gunicorn -c gunicorn_config.py app:app

# 或使用启动脚本
python run_server.py --mode prod
```

## 目录结构

```
backend/
├── app.py                 # 主应用文件
├── llm_service.py        # LLM服务
├── init_db.py            # 数据库初始化
├── run_server.py         # 启动脚本
├── gunicorn_config.py    # Gunicorn配置
├── requirements.txt      # Python依赖
├── .env                  # 环境变量（需创建）
├── .env.example          # 环境变量示例
├── config/               # 配置文件
├── templates/            # HTML模板
├── instance/             # 实例文件（数据库等）
├── uploads/              # 上传文件
├── downloads/            # 下载文件
├── outputs/              # 输出文件
└── logs/                 # 日志文件
```

## 开发指南

### 添加新的API端点

```python
@app.route('/api/new-endpoint', methods=['POST'])
@jwt_required()  # 需要认证
def new_endpoint():
    try:
        # 获取请求数据
        data = request.get_json()

        # 业务逻辑
        result = process_data(data)

        # 返回成功响应
        return jsonify({
            'success': True,
            'data': result
        }), 200

    except Exception as e:
        # 错误处理
        app.logger.error(f"Error in new_endpoint: {str(e)}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500
```

### 数据库操作

```python
# 查询
materials = Material.query.filter_by(client_id=client_id).all()

# 创建
new_material = Material(
    client_id=client_id,
    name=name,
    type=file_type
)
db.session.add(new_material)
db.session.commit()

# 更新
material = Material.query.get(material_id)
material.status = 'completed'
db.session.commit()

# 删除
db.session.delete(material)
db.session.commit()
```

## 测试

### 运行测试
```bash
python -m pytest tests/
```

### 测试API端点
```bash
# 健康检查
curl http://localhost:5010/health

# 登录获取token
curl -X POST http://localhost:5010/api/auth/signin \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"admin123"}'

# 使用token访问API
curl http://localhost:5010/api/clients \
  -H "Authorization: Bearer YOUR_TOKEN"
```

## 部署

### Docker部署

创建 `Dockerfile`：

```dockerfile
FROM python:3.9-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN python init_db.py

EXPOSE 5010

CMD ["gunicorn", "-c", "gunicorn_config.py", "app:app"]
```

构建和运行：
```bash
docker build -t translation-backend .
docker run -p 5010:5010 -v ./data:/app/instance translation-backend
```

### Linux服务器部署

参见主项目的 `docs/deployment.md` 文档。

## 故障排查

### 常见问题

1. **数据库锁定错误**
   - 解决：使用SQLite WAL模式
   - 在app.py中添加：`?mode=wal` 到数据库URL

2. **CORS错误**
   - 检查.env中的CORS_ORIGINS配置
   - 确保包含前端地址

3. **文件上传失败**
   - 检查文件夹权限
   - 检查MAX_CONTENT_LENGTH设置

4. **内存不足**
   - 调整Gunicorn workers数量
   - 使用分块处理大文件

## 维护

### 日志查看
```bash
# 应用日志
tail -f logs/error.log

# 访问日志
tail -f logs/access.log
```

### 数据库备份
```bash
# 备份
cp instance/translation_platform.db backup/translation_platform_$(date +%Y%m%d).db

# 恢复
cp backup/translation_platform_20240101.db instance/translation_platform.db
```

### 更新依赖
```bash
pip install --upgrade -r requirements.txt
```

## 支持

如有问题，请查看：
1. 项目文档：`docs/`目录
2. 提交Issue：GitHub仓库
3. 联系开发团队

## 许可证

Copyright © 2024. All rights reserved.
# 📋 HƯỚNG DẪN DEPLOY - NHẠt TUYẾN (TEST ENVIRONMENT)

## 🎯 Lựa Chọn Deploy

### Tuỳ chọn 1: **RAILWAY** ⭐ (Khuyến nghị - Dễ & Miễn Phí)
- Tương tự Heroku nhưng miễn phí hơn
- Hỗ trợ MySQL tích hợp
- Tự động deploy khi push GitHub
- Thích hợp cho TEST

### Tuỳ chọn 2: **Docker + VPS**
- Điều khiển toàn quyền
- Phù hợp production
- Yêu cầu VPS (DigitalOcean, Vultr, etc)

### Tuỳ chọn 3: **Heroku**
- Cũ hơn Railway nhưng vẫn dùng được
- Miễn phí tier bị xoá (2022)
- Phải trả phí

---

## 🚀 CÁCH 1: DEPLOY TRÊN RAILWAY (Khuyến Nghị)

### Bước 1: Tạo Tài Khoản Railway
```
1. Truy cập https://railway.app
2. Đăng ký bằng GitHub (Authorization)
3. Xác nhận email
```

### Bước 2: Tạo Project Mới trên Railway
```
1. Nhấp "New Project"
2. Chọn "Deploy from GitHub"
3. Chọn repo: IrRoot/trung-tam-nhat-tuyen
4. Cho phép Railway access repo
```

### Bước 3: Thêm MySQL Database
```
1. Nhấp dấu "+"
2. Chọn "MySQL"
3. Database sẽ được tự động tạo
4. Railway sẽ tạo variable: DATABASE_URL
```

### Bước 4: Thiết Lập Environment Variables
Tại Dashboard > Variables, thêm:
```
FLASK_ENV=production
SECRET_KEY=your-secret-key-here-change-this-to-random-string
PORT=5000
```

### Bước 5: Deploy
```
1. Railway sẽ tự động detect Procfile
2. Chọn branch: main
3. Nhấp "Deploy"
4. Chờ ~2-3 phút
5. Truy cập domain được cấp (xxx.railway.app)
```

### Bước 6: Khởi Tạo Database (Lần Đầu)
Sau deploy thành công, chạy commands SSH trên Railway:
```bash
# Kết nối vào Railway console
flask shell

# Trong Flask shell
from app import create_app, db
from models import *
app = create_app('production')
with app.app_context():
    db.create_all()
    # Có thể chạy init_db.py để thêm dữ liệu test
```

**Hoặc dùng CLI Railway:**
```bash
# Cài Railway CLI
npm i -g @railway/cli

# Login
railway login

# Vào project
railway link

# Chạy migrations
railway run flask db upgrade

# Hoặc khởi tạo DB
railway run python -c "from app import create_app, db; app=create_app('production'); db.create_all()"
```

---

## 🐳 CÁCH 2: DEPLOY BẰNG DOCKER + VPS (DigitalOcean/Vultr)

### Bước 1: Chuẩn Bị VPS
```bash
# Tạo VM trên DigitalOcean / Vultr
# - OS: Ubuntu 22.04 LTS
# - RAM: 2GB trở lên
# - CPU: 1 core
# - Storage: 25GB
```

### Bước 2: SSH vào VPS và Setup
```bash
# SSH vào server
ssh root@YOUR_SERVER_IP

# Update & Install Docker
apt update && apt upgrade -y
apt install -y docker.io docker-compose git

# Thêm user vào docker group
usermod -aG docker $USER
newgrp docker

# Clone repo
cd /opt
git clone https://github.com/IrRoot/trung-tam-nhat-tuyen.git
cd trung-tam-nhat-tuyen
```

### Bước 3: Cấu Hình Để Deploy

Tạo file `docker-compose.prod.yml`:
```yaml
version: '3.8'

services:
  web:
    build: .
    container_name: nhat-tuyen-web
    command: gunicorn --bind 0.0.0.0:5000 --workers 4 wsgi:app
    environment:
      FLASK_ENV: production
      SECRET_KEY: ${SECRET_KEY}
      DATABASE_URL: mysql+pymysql://nhat_tuyen_user:${DB_PASSWORD}@db:3306/nhat_tuyen_db
    ports:
      - "5000:5000"
    depends_on:
      - db
    restart: always
    volumes:
      - ./uploads:/app/uploads

  db:
    image: mysql:8.0
    container_name: nhat-tuyen-mysql
    environment:
      MYSQL_ROOT_PASSWORD: ${DB_ROOT_PASSWORD}
      MYSQL_DATABASE: nhat_tuyen_db
      MYSQL_USER: nhat_tuyen_user
      MYSQL_PASSWORD: ${DB_PASSWORD}
    volumes:
      - mysql_data:/var/lib/mysql
    restart: always
    healthcheck:
      test: ["CMD", "mysqladmin", "ping", "-h", "localhost"]
      timeout: 20s
      retries: 10

  nginx:
    image: nginx:latest
    container_name: nhat-tuyen-nginx
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./nginx.conf:/etc/nginx/nginx.conf:ro
      - ./ssl:/etc/nginx/ssl:ro
      - ./uploads:/app/uploads:ro
    depends_on:
      - web
    restart: always

volumes:
  mysql_data:
    driver: local
```

### Bước 4: Tạo .env.prod
```bash
cat > /opt/trung-tam-nhat-tuyen/.env.prod << EOF
FLASK_ENV=production
SECRET_KEY=$(openssl rand -hex 32)
DB_PASSWORD=$(openssl rand -hex 16)
DB_ROOT_PASSWORD=$(openssl rand -hex 16)
EOF
```

### Bước 5: Tạo Dockerfile
```dockerfile
FROM python:3.13-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    libmysqlclient-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy app
COPY . .

# Create upload directories
RUN mkdir -p uploads/documents uploads/students

# Expose port
EXPOSE 5000

CMD ["gunicorn", "--bind", "0.0.0.0:5000", "wsgi:app"]
```

### Bước 6: Deploy
```bash
cd /opt/trung-tam-nhat-tuyen

# Build & start containers
docker-compose -f docker-compose.prod.yml up -d

# Kiểm tra logs
docker-compose -f docker-compose.prod.yml logs -f web

# Khởi tạo database
docker-compose -f docker-compose.prod.yml exec web flask db upgrade
# Hoặc
docker-compose -f docker-compose.prod.yml exec web python -c \
  "from app import create_app, db; app=create_app('production'); db.create_all()"
```

### Bước 7: Setup SSL (HTTPS)
```bash
# Cài Certbot
apt install -y certbot python3-certbot-nginx

# Lấy chứng chỉ SSL
certbot certonly --standalone -d your-domain.com

# Cài đặt trong nginx.conf
```

---

## ✅ CÁCH 3: DEPLOY TRÊN HEROKU (Dự Phòng)

### Bước 1: Cài Heroku CLI
```bash
# macOS
brew tap heroku/brew && brew install heroku

# Linux
curl https://cli-assets.heroku.com/install.sh | sh

# Windows: Download từ https://devcenter.heroku.com/articles/heroku-cli
```

### Bước 2: Login & Create App
```bash
heroku login
heroku create nhat-tuyen-app
```

### Bước 3: Thêm MySQL Add-on
```bash
heroku addons:create cleardb:ignite
# Hoặc
heroku addons:create jawsdb:kitefin
```

### Bước 4: Set Environment Variables
```bash
heroku config:set FLASK_ENV=production
heroku config:set SECRET_KEY=your-random-secret-key
```

### Bước 5: Deploy
```bash
git push heroku main
```

### Bước 6: Khởi Tạo Database
```bash
heroku run flask db upgrade
```

---

## 🧪 TEST DEPLOYMENT TRƯỚC KHI PUSH PRODUCTION

### Test Locally (Trước Push)
```bash
# Thiết lập .env.test
cp .env.example .env.test
nano .env.test
# Thay DATABASE_URL = mysql+pymysql://user:pass@localhost/test_db

# Export config
export FLASK_ENV=production
export $(cat .env.test | xargs)

# Chạy app
gunicorn --bind 127.0.0.1:5000 --workers 2 wsgi:app

# Test tại http://localhost:5000
```

### Checklist Trước Push Lên Test
- [ ] Tất cả code đã commit
- [ ] `.env` có SECRET_KEY mạnh
- [ ] DATABASE_URL trỏ đúng
- [ ] Chạy `python -m pytest` (nếu có tests)
- [ ] Các migration đã chạy
- [ ] Upload folder permissions OK
- [ ] Logs không có error

### URLs Test Environments
| Nền Tảng | URL Mẫu | Bước Tạo |
|---------|--------|---------|
| Railway | `https://app-name.railway.app` | Railway Dashboard |
| VPS | `https://your-domain.com` | Liên hệ VPS provider |
| Heroku | `https://app-name.herokuapp.com` | `heroku create` |

---

## 🔍 VERIFY DEPLOYMENT

### Kiểm Tra Health Status
```bash
# SSH vào server hoặc Railway console
curl http://localhost:5000/
# Hoặc
curl https://your-app.railway.app/
```

### Kiểm Tra Database Connection
```bash
flask shell
# Trong Flask shell:
from models import User
User.query.count()  # Nếu không error = OK
```

### Xem Logs
```bash
# Railway:
railway logs

# Docker:
docker-compose logs -f web

# Heroku:
heroku logs --tail
```

---

## ⚠️ COMMON ISSUES & FIXES

### Issue 1: Database Connection Error
```
Error: "Can't connect to MySQL server"
```
**Fix:**
```bash
# Kiểm tra DATABASE_URL format
echo $DATABASE_URL

# Đúng format:
mysql+pymysql://user:password@host:port/database

# Test kết nối:
python -c "import sqlalchemy; engine = sqlalchemy.create_engine('DATABASE_URL'); conn = engine.connect(); print('OK')"
```

### Issue 2: Static Files Not Loading
```
CSS/JS không tải
```
**Fix:**
```bash
# Chạy collectstatic (nếu dùng storage cloud)
flask assets build

# Hoặc kiểm tra STATIC_FOLDER trong config
```

### Issue 3: Memory/Timeout
```
Error: H14 - App crashed | Timeout after 30s
```
**Fix:**
```bash
# Tăng workers
gunicorn -w 2 -b 0.0.0.0:$PORT wsgi:app

# Hoặc tối ưu code
# - Add caching
# - Optimize queries
```

### Issue 4: Secret Key Error
```
RuntimeError: The session interface is invalid
```
**Fix:**
```bash
# Set SECRET_KEY
railway config:set SECRET_KEY=your-long-random-string
# hoặc
heroku config:set SECRET_KEY=your-long-random-string
```

---

## 📊 MONITORING & LOGS

### Setup Logging
Thêm vào `config.py`:
```python
import logging
from logging.handlers import RotatingFileHandler

def setup_logging(app):
    if not app.debug:
        handler = RotatingFileHandler('app.log', maxBytes=10240, backupCount=10)
        handler.setLevel(logging.INFO)
        app.logger.addHandler(handler)
```

### View Logs
```bash
# Docker
docker-compose logs -f web

# Railway
railway logs -t

# Production folder
cat /var/log/app.log
tail -f /var/log/app.log
```

---

## 🎬 SETUP AUTOMATION (Optional)

### GitHub Actions - Auto Deploy
Tạo `.github/workflows/deploy.yml`:
```yaml
name: Deploy to Railway

on:
  push:
    branches: [main]

jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2
      - name: Deploy to Railway
        env:
          RAILWAY_TOKEN: ${{ secrets.RAILWAY_TOKEN }}
        run: |
          npm i -g @railway/cli
          railway up --service api
```

---

## 📞 SUPPORT & RESOURCES

- **Railway Docs**: https://docs.railway.app
- **Flask Deployment**: https://flask.palletsprojects.com/deployment
- **Docker Guide**: https://docker.com/resources/what-is-docker
- **GitHub Actions**: https://github.com/features/actions

---

**Lựa chọn giới thiệu: RAILWAY (Dễ, Miễn phí, Nhanh)**
Muốn tôi hướng dẫn chi tiết từng bước không?

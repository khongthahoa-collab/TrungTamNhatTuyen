# 📚 HƯỚNG DẪN DEPLOY CHI TIẾT - NHẠt TUYẾN

> 🎯 Bạn đây là hướng dẫn **BƯỚC-BY-BƯỚC** chi tiết nhất để deploy dự án lên test environment

---

## 🚀 LỰA CHỌN DEPLOY

### **Tuỳ Chọn 1: RAILWAY** ⭐⭐⭐ (Khuyến Nghị Nhất)
- ✅ **Dễ nhất**: Chỉ cần GitHub + click
- ✅ **Miễn phí**: $5/tháng free credits
- ✅ **Tự động**: Tự deploy khi push GitHub
- ✅ **MySQL tích hợp**: Không cần config DB riêng
- ⏱️ **Thời gian**: ~5 phút
- 📍 **Phù hợp**: TEST environment

### **Tuỳ Chọn 2: Docker (Trên VPS)**
- ✅ **Đầy đủ**: Điều khiển tất cả
- ✅ **Sản xuất**: Sẵn sàng cho production
- ✅ **Rẻ**: VPS từ $3-5/tháng
- ❌ **Phức tạp hơn**: Cần setup VPS, SSL, etc
- ⏱️ **Thời gian**: ~15 phút
- 📍 **Phù hợp**: Production / Self-hosted

### **Tuỳ Chọn 3: Heroku**
- ✅ **Dễ**: Giống Railway
- ❌ **Trả phí**: Free tier bị xoá (2022)
- ❌ **Đắt hơn**: $7-50/tháng tùy config
- ⏱️ **Thời gian**: ~5 phút
- 📍 **Phù hợp**: Legacy projects

---

# 1️⃣ RAILWAY DEPLOYMENT (Khuyến Nghị)

## Step 1: Chuẩn Bị Tài Khoản

### 1.1 Tạo GitHub Account (Nếu Chưa Có)
```
1. Truy cập: https://github.com
2. Nhấp "Sign up"
3. Email -> Password -> Username
4. Xác nhận email
5. Xong!
```

### 1.2 Tạo Railway Account
```
1. Truy cập: https://railway.app
2. Nhấp nút "Login" ở trên phải
3. Chọn "Sign up with GitHub"
4. Cho phép Railway access GitHub
5. (Optional) Chọn plan (Free $5/tháng hoặc Pro)
```

## Step 2: Import GitHub Repository

### 2.1 Vào Railway Dashboard
```
1. Đăng nhập Railway: https://railway.app/dashboard
2. Nhấp nút "New Project"
3. Chọn "Deploy from GitHub"
```

### 2.2 Kết Nối GitHub
```
1. Nhấp "Install & Authorize"
2. GitHub sẽ mở, nhấp "Authorize RailwayApp"
3. Quay lại Railway
4. Chọn repo: IrRoot/trung-tam-nhat-tuyen
5. Chọn branch: main (mặc định)
6. Nhấp "Deploy"
```

Railway sẽ tự động:
- ✅ Tìm Procfile
- ✅ Detect Python environment
- ✅ Install dependencies từ requirements.txt
- ✅ Build & deploy app

**Chờ 2-3 phút cho build xong** (Xem Build Logs để monitor)

## Step 3: Thêm MySQL Database

Sau khi app deployed xong:

```
1. Vào Railway Project Dashboard
2. Nhấp dấu "+"
3. Chọn "MySQL"
4. Chọn "Create"
5. Chờ database ready (~30 giây)
```

Railway sẽ tự động tạo các biến:
```
DATABASE_URL=mysql+pymysql://root:password@containers.railway.app:port/database
MYSQLHOST=containers.railway.app
MYSQLPASSWORD=...
MYSQLPORT=...
MYSQLUSER=root
```

## Step 4: Set Environment Variables

Vào tab "Variables":

```
Thêm 2 biến:
────────────────────────────────────────
Key: FLASK_ENV
Value: production

────────────────────────────────────────
Key: SECRET_KEY
Value: [Generate strong key]
```

### Cách Generate SECRET_KEY Mạnh

**Trên Mac/Linux:**
```bash
openssl rand -hex 32
# Output: abc123def456... (dán vào Railway)
```

**Hoặc online:**
```
https://www.random.org/strings/?num=1&len=64&digits=on&loweralpha=on&upperalpha=on&unique=on
```

**Hoặc Python:**
```python
import secrets
secrets.token_hex(32)
```

## Step 5: Khởi Tạo Database

Sau khi set variables, database chưa có tables. Cần chạy migrations:

### Option A: Dùng Railway CLI (Dễ nhất)

```bash
# 1. Install Railway CLI
npm install -g @railway/cli

# 2. Login
railway login
# (Sẽ mở browser, đăng nhập GitHub)

# 3. Link project
cd /path/to/trung-tam-nhat-tuyen
railway link
# (Chọn project trong list)

# 4. Initialize database
railway run python -c "from app import create_app, db; app=create_app('production'); db.create_all()"

# 5. Xác nhận (Output không có error = OK)
```

### Option B: SSH vào Container

```bash
# 1. Vào Railway Project
# 2. Tìm "Web" service
# 3. Nhấp "Shell"
# 4. Chạy commands:

python -c "from app import create_app, db; app=create_app('production'); db.create_all()"
```

### Option C: GitHub Actions (Automatic)

```bash
# Sẽ tự động chạy migrations khi deploy
# Nhưng cần setup thêm file
# (Chi tiết ở advanced section)
```

## Step 6: Verify Deployment

### 6.1 Lấy App URL
```
1. Vào Railway Project > Web service
2. Tìm "Domains" section
3. Copy URL (dạng: app-abc123.railway.app)
```

### 6.2 Test App
```bash
# Trong terminal:
curl https://app-name.railway.app

# Hoặc dùng browser:
https://app-name.railway.app
```

### 6.3 Test Login
```
Vào: https://app-name.railway.app/auth/login

Tài khoản test:
────────────────────
Admin:
  Username: admin
  Password: admin123

Teacher:
  Username: gvtoan
  Password: teacher123

Parent:
  Username: parent01
  Password: parent123
```

Nếu login thành công = **Deployment Successful!** 🎉

## Step 7: Monitor & Troubleshoot

### View Logs
```
Railway Dashboard > Web Service > Logs
```

### Common Issues

**Error: "Error: Can't connect to MySQL server"**
```
Giải pháp:
1. Chắc chắn DATABASE_URL được set
2. Khởi tạo database lại: railway run python ...
```

**Error: "ModuleNotFoundError"**
```
Giải pháp:
1. Check requirements.txt cùng cấp thư mục với Procfile
2. Push lại & deploy
```

**Error: 502 Bad Gateway**
```
Giải pháp:
1. Check logs: railway logs -t
2. Có thể app crash, đọc error message
3. Fix code, push GitHub, Railway auto re-deploy
```

---

# 2️⃣ DOCKER DEPLOYMENT (VPS)

## Chuẩn Bị

### VPS Provider (Chọn 1)
```
DigitalOcean:    https://www.digitalocean.com
Vultr:           https://www.vultr.com  
Linode:          https://www.linode.com
AWS EC2:         https://aws.amazon.com
```

### Yêu Cầu VPS
```
OS: Ubuntu 22.04 LTS
RAM: 2GB (tối thiểu)
CPU: 1 core
Storage: 25GB
Price: $3-10/tháng
```

## Step 1: Tạo VPS Server

Ví dụ DigitalOcean:
```
1. Login: https://cloud.digitalocean.com
2. Create > Droplet
3. Image: Ubuntu 22.04 x64
4. Size: Basic ($4/mo, 512MB RAM)
5. Region: Singapore/Tokyo (gần Việt Nam)
6. Nhấp "Create Droplet"
7. Chờ server ready
8. Ghi lại IP (123.45.67.89)
```

## Step 2: SSH vào Server

```bash
# Lần đầu (setup SSH key nếu cần)
ssh -i path/to/key.pem root@123.45.67.89

# Hoặc nhập password khi yêu cầu
ssh root@123.45.67.89
```

## Step 3: Install Docker & Dependencies

```bash
# Update system
apt update && apt upgrade -y

# Install Docker
apt install -y docker.io docker-compose git curl

# Thêm user vào docker group (để không cần sudo)
usermod -aG docker $USER
newgrp docker

# Verify Docker
docker --version
docker-compose --version
```

## Step 4: Clone Repository

```bash
# Vào /opt folder
cd /opt

# Clone repo
git clone https://github.com/IrRoot/trung-tam-nhat-tuyen.git

# Vào folder
cd trung-tam-nhat-tuyen

# Verify files
ls -la | grep docker-compose.prod.yml
```

## Step 5: Setup Environment File

```bash
# Copy template
cp .env.production .env.prod

# Edit file
nano .env.prod

# Sửa những giá trị:
────────────────────────────────────────
FLASK_ENV=production
SECRET_KEY=<generate strong key>
DB_PASSWORD=<strong-password>
DB_ROOT_PASSWORD=<strong-root-password>
────────────────────────────────────────

# Save & exit (Ctrl+X, Y, Enter)
```

## Step 6: Build & Run Docker

```bash
# Build images
docker-compose -f docker-compose.prod.yml build

# Start containers (-d = detach/background)
docker-compose -f docker-compose.prod.yml up -d

# Chờ containers start (5-10 giây)
sleep 10

# Check status
docker-compose -f docker-compose.prod.yml ps
```

Output sẽ như:
```
NAME                          STATUS
nhat-tuyen-web-prod          Up 2 seconds
nhat-tuyen-mysql-prod        Up 5 seconds
nhat-tuyen-nginx-prod        Up 1 second
```

## Step 7: Initialize Database

```bash
# Run database initialization
docker-compose -f docker-compose.prod.yml exec web python -c \
  "from app import create_app, db; app=create_app('production'); db.create_all()"

# Check (should print number of users)
docker-compose -f docker-compose.prod.yml exec web python -c \
  "from app import create_app; from models import User; app=create_app('production'); print(User.query.count())"
```

## Step 8: Verify

```bash
# Test app locally (dalam VPS)
curl http://localhost:80

# Hoặc từ laptop
curl http://123.45.67.89

# Hoặc browser
http://123.45.67.89
```

## Step 9: Setup Domain & SSL (Optional)

```bash
# A. Buy domain (Namecheap, GoDaddy, etc)
# B. Point DNS to VPS IP: 123.45.67.89
# C. Wait DNS propagate (24 hours)

# D. Generate SSL cert
docker run --rm --name=letsencrypt \
  -v /etc/letsencrypt:/etc/letsencrypt \
  -p 80:80 \
  certbot/certbot certonly --standalone \
  -d your-domain.com \
  --agree-tos -m your-email@example.com

# E. Copy certs to nginx folder
sudo cp /etc/letsencrypt/live/your-domain.com/fullchain.pem ./ssl/cert.pem
sudo cp /etc/letsencrypt/live/your-domain.com/privkey.pem ./ssl/key.pem

# F. Restart nginx
docker-compose -f docker-compose.prod.yml restart nginx

# Sekarang https://your-domain.com sẽ work!
```

## Step 10: Monitoring

```bash
# View logs real-time
docker-compose -f docker-compose.prod.yml logs -f web

# View specific service
docker-compose -f docker-compose.prod.yml logs -f db

# Check resource usage
docker stats
```

---

# 3️⃣ HEROKU DEPLOYMENT

## Step 1: Chuẩn Bị

```bash
# 1. Tài khoản Heroku: https://signup.heroku.com
# 2. Cài Heroku CLI
# - macOS:
  brew tap heroku/brew && brew install heroku
# - Ubuntu:
  sudo apt install heroku
# - Windows: Download từ https://devcenter.heroku.com/articles/heroku-cli
```

## Step 2: Login & Create App

```bash
# 1. Login
heroku login
# (Mở browser, đăng nhập)

# 2. Vào repo folder
cd /path/to/trung-tam-nhat-tuyen

# 3. Tạo Heroku app
heroku create nhat-tuyen-app-test
# (Hoặc để Heroku tự generate tên)

# 4. Verify
git remote -v | grep heroku
```

## Step 3: Add MySQL Database

```bash
# Thêm ClearDB MySQL
heroku addons:create cleardb:ignite -a nhat-tuyen-app-test

# Verify
heroku config -a nhat-tuyen-app-test | grep CLEARDB
```

## Step 4: Set Config Vars

```bash
# Set environment
heroku config:set FLASK_ENV=production -a nhat-tuyen-app-test
heroku config:set SECRET_KEY=$(openssl rand -hex 32) -a nhat-tuyen-app-test

# Check
heroku config -a nhat-tuyen-app-test
```

## Step 5: Deploy

```bash
# Push code
git push heroku main

# Chờ build (2-3 phút)
# (Xem output có error không)
```

## Step 6: Initialize Database

```bash
# Run migrations
heroku run flask db upgrade -a nhat-tuyen-app-test

# Hoặc create db
heroku run python -c "from app import create_app, db; app=create_app('production'); db.create_all()" -a nhat-tuyen-app-test
```

## Step 7: Test

```bash
# Open app
heroku open -a nhat-tuyen-app-test

# Hoặc manual
https://nhat-tuyen-app-test.herokuapp.com

# View logs
heroku logs --tail -a nhat-tuyen-app-test
```

---

# ✅ FINAL CHECKLIST

Sau khi deploy, kiểm tra:

- [ ] App loads tại URL
- [ ] Login page accessible
- [ ] Test login (admin account)
- [ ] Can see database data
- [ ] CSS/Images load correctly
- [ ] No errors in logs
- [ ] Database tables created
- [ ] File uploads work

---

# 🔧 TROUBLESHOOTING

## Issue 1: "Application Error"

```bash
# Check logs
railway logs -t  # Railway
docker logs -f nhat-tuyen-web-prod  # Docker
heroku logs --tail  # Heroku

# Tìm error message, fix code, deploy lại
```

## Issue 2: "Can't connect to database"

```bash
# Verify DATABASE_URL set
railway config  # Railway
heroku config  # Heroku
docker-compose exec web echo $DATABASE_URL  # Docker

# Test kết nối
python -c "import sqlalchemy; engine = sqlalchemy.create_engine('$DATABASE_URL'); print('OK')"
```

## Issue 3: "Module not found"

```bash
# Check requirements.txt
cat requirements.txt

# Sau đó
git add requirements.txt
git commit -m "Fix dependencies"
git push origin main
# Railway sẽ auto re-deploy
```

## Issue 4: "Port already in use"

```bash
# Docker
docker-compose -f docker-compose.prod.yml down
docker-compose -f docker-compose.prod.yml up -d

# VPS
lsof -i :5000  # Find process
kill -9 <PID>
```

---

# 📱 QUICK REFERENCE

| Task | Command |
|------|---------|
| View Railway logs | `railway logs -t` |
| View Docker logs | `docker-compose logs -f web` |
| View Heroku logs | `heroku logs --tail` |
| SSH Railway | `railway shell` |
| SSH Docker | `docker-compose exec web bash` |
| SSH Heroku | `heroku run bash` |
| Restart Railway | Manual via dashboard |
| Restart Docker | `docker-compose restart` |
| Restart Heroku | `heroku restart` |

---

**💡 Khuyến Nghị: Chọn RAILWAY cho lần đầu tiên!**
- Dễ nhất (~5 phút)
- Miễn phí ($5/tháng free)
- Tự động deploy khi push GitHub
- MySQL tích hợp

**Cần giúp đỡ?**
- Railway Docs: https://docs.railway.app
- GitHub Issues: https://github.com/IrRoot/trung-tam-nhat-tuyen/issues
- Flask Docs: https://flask.palletsprojects.com

---

**Happy Deploying! 🚀**

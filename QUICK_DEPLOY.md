# ⚡ QUICK START DEPLOY - NHẠt TUYẾN

## 🎯 Nhanh Nhất: Deploy Lên RAILWAY (5 Phút)

### 1️⃣ Chuẩn Bị
```bash
# ✓ Đã push lên GitHub
# ✓ Có GitHub account
# ✓ Đã đăng ký Railway (Free)
```

### 2️⃣ Trên Railway Dashboard

#### Bước A: Tạo Project
```
1. Vào https://railway.app
2. Nhấp "New Project"
3. Chọn "Deploy from GitHub"
4. Tìm repo: IrRoot/trung-tam-nhat-tuyen
5. Cho phép Railway access
```

#### Bước B: Thêm MySQL Database
```
1. Trên project, nhấp "+"
2. Chọn "MySQL"
3. Chọn instance
4. Railway tự động tạo DATABASE_URL
```

#### Bước C: Set Environment Variables
Vào "Variables" tab, thêm:
```
FLASK_ENV=production
SECRET_KEY=change-me-to-random-string-$(openssl rand -hex 32)
```

Railway tự động tạo những biến này:
```
DATABASE_URL=mysql+pymysql://...
MYSQL_URL=mysql://...
```

#### Bước D: Deploy
```
1. Railway tự detect Procfile
2. Chọn branch: main
3. Nhấp "Deploy"
4. Chờ 2-3 phút
5. Xem logs (Should be GREEN)
```

### 3️⃣ Khởi Tạo Database

Sau deploy thành công, vào Railway Console:
```bash
# SSH vào container
railway shell

# Hoặc chạy command trực tiếp
railway run python -c "from app import create_app, db; app=create_app('production'); db.create_all()"
```

### 4️⃣ Verify
```bash
# Railway sẽ tạo URL như:
# https://app-abc123.railway.app

# Truy cập trang chủ
curl https://app-abc123.railway.app

# Đăng nhập test
# Admin: admin / admin123
# Teacher: gvtoan / teacher123
# Parent: parent01 / parent123
```

---

## 📱 USING Railway CLI (Advanced)

```bash
# 1. Install CLI
npm install -g @railway/cli

# 2. Login
railway login

# 3. Vào project folder
cd trung-tam-nhat-tuyen

# 4. Link project
railway link

# 5. Set variables
railway config:set FLASK_ENV=production
railway config:set SECRET_KEY=$(openssl rand -hex 32)

# 6. View variables
railway config

# 7. Deploy
railway up --service api

# 8. View logs
railway logs -t

# 9. SSH vào container
railway shell

# 10. Run commands
railway run python -c "..."
```

---

## 🐳 DEPLOY BẰNG DOCKER (5 Phút - Cho VPS)

```bash
# 1. Clone repo
git clone https://github.com/IrRoot/trung-tam-nhat-tuyen.git
cd trung-tam-nhat-tuyen

# 2. Chuẩn bị env
cp .env.production .env.prod
nano .env.prod  # Edit giá trị

# 3. Build & Run
docker-compose -f docker-compose.prod.yml up -d

# 4. Chờ DB ready (10 giây)
sleep 10

# 5. Init database
docker-compose -f docker-compose.prod.yml exec web python -c \
  "from app import create_app, db; app=create_app('production'); db.create_all()"

# 6. Check status
docker-compose -f docker-compose.prod.yml ps

# 7. View logs
docker-compose -f docker-compose.prod.yml logs -f web

# App sẽ chạy tại http://localhost:80
```

---

## 📊 MONITORING & TROUBLESHOOTING

### Check Status
```bash
# Railway
railway config  # View all variables
railway logs -t  # Tail logs
railway status  # Service status

# Docker
docker-compose -f docker-compose.prod.yml logs web
docker-compose -f docker-compose.prod.yml ps
docker ps
```

### Common Issues

**Problem: "Can't connect to MySQL"**
```bash
# Solution 1: Check DATABASE_URL
railway config | grep DATABASE_URL

# Solution 2: Make sure DB initialized
railway run python -c "from models import *; User.query.count()"
```

**Problem: "Error 502 Bad Gateway"**
```bash
# Solution: Check app logs
railway logs -t | grep ERROR
```

**Problem: "Static files not loading"**
```bash
# Solution: Check if upload folder exists
railway run python -c "import os; os.makedirs('uploads', exist_ok=True)"
```

---

## ✅ DEPLOYMENT CHECKLIST

- [ ] Push code lên GitHub
- [ ] Tạo Railway project
- [ ] Thêm MySQL database
- [ ] Set FLASK_ENV=production
- [ ] Set SECRET_KEY
- [ ] Deploy
- [ ] Initialize database
- [ ] Test login (admin/admin123)
- [ ] Check logs for errors
- [ ] Verify database connection
- [ ] Test xem có thể view dữ liệu không

---

## 🔗 USEFUL LINKS

| Resource | Link |
|----------|------|
| Railway Docs | https://docs.railway.app |
| Railway Dashboard | https://railway.app/dashboard |
| GitHub Repo | https://github.com/IrRoot/trung-tam-nhat-tuyen |
| Full Deploy Guide | See DEPLOYMENT_GUIDE.md |

---

## 🚀 RECAP: 3 Cách Deploy

| Method | Time | Difficulty | Best For |
|--------|------|-----------|----------|
| **Railway** | 5 min | Easy ⭐ | **TEST** |
| **Docker** | 10 min | Medium | Self-hosted |
| **Heroku** | 5 min | Easy | Legacy |

**Khuyến nghị: RAILWAY vì dễ, miễn phí, và tự động deploy khi push GitHub** 🚀

---

## 📞 Need Help?

- **Railway Issues**: https://github.com/railwayapp/help
- **Flask Deployment**: https://flask.palletsprojects.com/deployment
- **Docker Guide**: https://docker.com/get-started
- **Our Repo Issues**: https://github.com/IrRoot/trung-tam-nhat-tuyen/issues

---

**Happy Deploying!** 🎉

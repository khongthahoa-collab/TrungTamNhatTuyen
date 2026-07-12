# 📚 HƯỚNG DẪN DEPLOY CHI TIẾT — NHẬT TUYỀN

Stack production thật: **Railway** (build image từ `Dockerfile` ở repo root, tự deploy mỗi khi push lên `main`) + **Supabase PostgreSQL** (database, quản lý riêng ngoài Railway).

Xem `QUICK_DEPLOY.md` nếu chỉ cần các bước tóm tắt. File này giải thích sâu hơn từng phần.

---

## 1. Vì sao dùng Railway + Supabase

- **Railway** tự nhận diện `Dockerfile` ở root — không cần `railway.json`/`nixpacks.toml`. Chỉ cần connect GitHub repo, mỗi lần push `main` sẽ tự build lại và deploy.
- **Supabase** là Postgres quản lý (managed), tách rời khỏi Railway — nghĩa là dù đổi/xoá Railway project, dữ liệu vẫn an toàn trên Supabase. Railway chỉ cần biết `DATABASE_URL` trỏ tới đó.
- Local dev **không cần Docker/MySQL**: mặc định app fallback sang SQLite (`sqlite:///nhat_tuyen_dev.db`, tự tạo trong `instance/`) khi không có `DATABASE_URL` — xem `config.py`.

## 2. Chuẩn bị tài khoản

- GitHub: repo đã push (private là được, Railway hỗ trợ deploy từ private repo sau khi authorize).
- Railway: https://railway.app — đăng nhập bằng GitHub, authorize quyền truy cập repo.
- Supabase: https://supabase.com/dashboard — tạo project mới nếu chưa có (chọn region gần người dùng nhất, ví dụ Singapore cho Việt Nam).

## 3. Kết nối GitHub repo với Railway

1. Railway Dashboard → **New Project** → **Deploy from GitHub repo**
2. Chọn đúng repo (`TrungTamNhatTuyen` hoặc tên hiện tại)
3. Railway tự phát hiện `Dockerfile` và dùng nó để build — không cần chỉnh gì ở bước này

## 4. Lấy connection string từ Supabase

Vào project Supabase → **Project Settings → Database → Connection string**:

- **Direct connection** (port `5432`, host `db.<project-ref>.supabase.co`): đơn giản, phù hợp cho script chạy 1 lần (`seed_supabase.py`) hoặc traffic thấp. Supabase free tier giới hạn số connection trực tiếp đồng thời khá thấp.
- **Transaction pooler** (port `6543`, host dạng `aws-<n>-<region>.pooler.supabase.com`, username `postgres.<project-ref>`): nên dùng cho app production chạy nhiều gunicorn worker, vì pooler chia sẻ connection hiệu quả hơn.

⚠️ **Lấy đúng host từ trang Connection string thật của project** — đừng copy lại host mẫu từ nơi khác, vì mỗi project được gán pooler theo đúng region lúc tạo. Dùng sai region host sẽ ra lỗi `tenant/user ... not found`.

⚠️ **Percent-encode mật khẩu** nếu có ký tự đặc biệt (`/ * # @ : ? [ ]`), nếu không URL sẽ bị parse sai (điển hình: `#` bị hiểu là bắt đầu fragment, cắt mất phần sau):
```bash
python3 -c "from urllib.parse import quote; print(quote('<mật khẩu thật>', safe=''))"
```

## 5. Set Environment Variables trên Railway

Railway project → **Variables** tab:

| Key | Giá trị |
|---|---|
| `FLASK_ENV` | `production` |
| `SECRET_KEY` | chuỗi random dài — generate bằng `openssl rand -hex 32` |
| `DATABASE_URL` | connection string Supabase (đã percent-encode password) |
| `UPLOAD_FOLDER` | `uploads/documents` |
| `MAX_CONTENT_LENGTH` | `20971520` |

`config.py` sẽ **raise lỗi khi khởi động** nếu `SECRET_KEY` bị để nguyên giá trị dev mặc định trong production — đây là chủ đích, để tránh quên set secret thật.

## 6. Khởi tạo schema + import dữ liệu

Chạy **từ máy local** (không phải trên Railway), một lần duy nhất khi setup Supabase mới:

```bash
FLASK_ENV=production DATABASE_URL="<connection string thật>" python seed_supabase.py
```

Script (`seed_supabase.py`) sẽ:
1. `db.create_all()` — tạo toàn bộ bảng theo `models.py` (không cần Flask-Migrate, project này không dùng migrations/ folder)
2. Đọc dữ liệu từ `nhat_tuyen.db` (SQLite local) và import sang Supabase
3. Reset lại các sequence (auto-increment) của Postgres cho khớp dữ liệu vừa import

Chạy lại script này an toàn (idempotent) — nó tự xoá dữ liệu cũ trước khi import lại.

## 7. Deploy

Railway tự build + deploy mỗi khi có commit mới trên `main`. Theo dõi tiến trình ở tab **Deployments**, xem log build/runtime trực tiếp trên dashboard.

## 8. Verify

```bash
curl -I https://<app>.up.railway.app
```

Đăng nhập thử qua trình duyệt với tài khoản admin đã seed.

## 9. Troubleshooting

### "tenant/user ... not found"
Sai region host của pooler. Quay lại đúng trang Connection string trên Supabase dashboard của project, copy chính xác host hiển thị ở đó (đừng tái sử dụng host từ project/hướng dẫn khác).

### Kết nối được nhưng "password authentication failed"
Mật khẩu chưa được percent-encode đúng, hoặc bị copy thiếu ký tự. Encode lại bằng `urllib.parse.quote(pw, safe='')` và test connect trực tiếp bằng `psycopg` trước khi set vào Railway.

### `SECRET_KEY must be set to a secure value in production!`
Chưa set `SECRET_KEY` trên Railway Variables, hoặc đang để đúng giá trị mặc định dev (`dev-secret-key-change-in-production`).

### Build fail — Docker lint warning `JSONArgsRecommended`
`Dockerfile` phải dùng CMD dạng JSON-array (`CMD ["sh", "-c", "..."]`) thay vì shell-form (`CMD gunicorn ...`), để tránh cảnh báo và đảm bảo signal (SIGTERM khi Railway restart/scale) được forward đúng tới process.

### App chạy nhưng dữ liệu trống
Chưa chạy `seed_supabase.py` để tạo bảng + import dữ liệu vào Supabase (bước 6). `db.create_all()` **không** tự chạy trong production (chỉ chạy tự động ở dev, xem `app.py`).

### Cần backup
Supabase tự động backup theo plan (xem Database → Backups trên dashboard). Backup thủ công:
```bash
pg_dump "<connection string thật>" > backup_$(date +%Y%m%d).sql
```

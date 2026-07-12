# ⚡ QUICK DEPLOY — NHẬT TUYỀN

Stack thật đang dùng: **Railway** (build từ `Dockerfile`, tự động khi push lên `main`) + **Supabase PostgreSQL** (database).

## 1️⃣ Chuẩn bị

- Code đã push lên GitHub (repo private là được)
- Có tài khoản Railway đã link với GitHub repo
- Có project Supabase (tạo tại https://supabase.com/dashboard)

## 2️⃣ Lấy connection string từ Supabase

1. Vào Supabase dashboard → chọn project → **Project Settings → Database**
2. Mục **Connection string** → tab **URI**
3. Copy chuỗi dạng:
   ```
   postgresql://postgres:[YOUR-PASSWORD]@db.<project-ref>.supabase.co:5432/postgres
   ```
   hoặc bản pooler (khuyến nghị cho production nhiều connection đồng thời):
   ```
   postgresql://postgres.<project-ref>:[YOUR-PASSWORD]@<pooler-host>:6543/postgres?pgbouncer=true
   ```
4. **Nếu mật khẩu có ký tự đặc biệt** (`/ * # @ : ...`), phải percent-encode trước khi dùng:
   ```bash
   python3 -c "from urllib.parse import quote; print(quote('mật khẩu thật', safe=''))"
   ```

## 3️⃣ Set biến môi trường trên Railway

Vào project → **Variables**:
```
FLASK_ENV=production
SECRET_KEY=<chuỗi random dài, vd: openssl rand -hex 32>
DATABASE_URL=<connection string Supabase ở bước 2, đã percent-encode>
UPLOAD_FOLDER=uploads/documents
MAX_CONTENT_LENGTH=20971520
```

Railway tự build lại và deploy mỗi khi có commit mới trên `main` (không cần CLI, không cần thao tác gì thêm).

## 4️⃣ Khởi tạo schema + import dữ liệu (chạy 1 lần, từ máy local)

```bash
FLASK_ENV=production DATABASE_URL="<connection string thật>" python seed_supabase.py
```

Script này tự `db.create_all()` (tạo toàn bộ bảng theo `models.py`) và import dữ liệu hiện có từ `nhat_tuyen.db` local sang Supabase.

## 5️⃣ Verify

- Mở URL Railway cấp (dạng `https://<app>.up.railway.app`)
- Đăng nhập thử với tài khoản admin đã seed

## Troubleshooting

| Lỗi | Nguyên nhân thường gặp |
|---|---|
| `tenant/user ... not found` | Sai region host của pooler — quay lại đúng trang Connection string trên Supabase, đừng tự đoán host |
| Kết nối được nhưng auth fail | Mật khẩu có ký tự đặc biệt chưa percent-encode |
| `SECRET_KEY must be set...` | Chưa set `SECRET_KEY` trên Railway, hoặc đang để giá trị mặc định dev |
| Build fail vì Dockerfile lint | Kiểm tra `Dockerfile` dùng JSON-array CMD (`["sh", "-c", "..."]`), không dùng shell-form |

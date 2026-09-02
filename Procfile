# Railway WSGI entry point - must use wsgi module, not app module
# --workers 2: mặc định gunicorn chỉ chạy 1 worker nếu không chỉ định — mọi
# request phải xếp hàng xử lý tuần tự trên đúng 1 tiến trình. 1 request chậm
# (VD trang /admin/tuition quét nhiều lớp) từng chặn đứng toàn bộ trang khác
# (kể cả Dashboard) cho tới khi xử lý xong — xem sự cố 31/08. 2 worker cho
# phép xử lý song song, giảm hẳn rủi ro 1 request chậm làm nghẽn cả server.
# Bắt đầu ở mức thận trọng (2) vì chưa rõ RAM của gói Railway đang dùng —
# có thể tăng thêm nếu theo dõi thấy dư tài nguyên.
web: gunicorn wsgi:app --workers 2

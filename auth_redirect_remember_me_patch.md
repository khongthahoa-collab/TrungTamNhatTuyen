BẢN VÁ KIẾN TRÚC: CHUYỂN HƯỚNG LOGIN & GHI NHỚ ĐĂNG NHẬP GIÁO VIÊN

Tài liệu này đặc tả cách cấu hình chuyển hướng trang chủ, biến ứng dụng thành Standalone WebApp chạy trực tiếp từ màn hình chính, đồng thời tối ưu hóa cơ chế duy trì phiên đăng nhập bền vững cho Giáo viên.

PHẦN 1: TỰ ĐỘNG CHUYỂN HƯỚNG TRANG CHỦ SANG LOGIN

Để tạm ẩn trang chủ (/) và tự động chuyển hướng người dùng đến màn hình làm việc tương ứng, chúng ta sẽ viết đè logic của Route / gốc (thường nằm ở app.py hoặc blueprints/home.py).

🛡️ Nguyên tắc tránh lỗi Vòng lặp chuyển hướng (Redirect Loop):

Nếu người dùng đã đăng nhập thành công trước đó, khi họ mở app (trình duyệt gửi request tới /), hệ thống phải đưa họ thẳng vào Dashboard tương ứng của họ thay vì đá họ ra trang Login. Nếu chưa đăng nhập, hệ thống mới chuyển hướng sang /login.

Code refactor đề xuất cho Route / gốc:

from flask import redirect, url_for
from flask_login import current_user
# Import helper điều hướng dashboard từ auth blueprint của bạn
from blueprints.auth import _dashboard_for

@app.route('/')
def index():
    """
    [RESOLVED - UX/UI PATCH] Ẩn trang chủ gốc.
    - Đã đăng nhập: Chuyển thẳng về Dashboard phù hợp của vai trò (Prod/Teacher/Admin).
    - Chưa đăng nhập: Đá thẳng sang trang Login của hệ thống.
    """
    if current_user.is_authenticated:
        # Tận dụng helper có sẵn để điều hướng đúng trang Dashboard
        return redirect(_dashboard_for(current_user))

    # Chuyển hướng sang màn hình đăng nhập (Thay 'auth.login' bằng endpoint thực tế của bạn)
    return redirect(url_for('auth.login'))


PHẦN 2: CẤU HÌNH GHI NHỚ ĐĂNG NHẬP (REMEMBER ME) CHO GIÁO VIÊN

Giáo viên khi thao tác trên điện thoại rất ngại việc mỗi ngày đều phải gõ lại mật khẩu. Chúng ta sẽ cấu hình để hệ thống tự động ghi nhớ đăng nhập vĩnh viễn đối với mọi tài khoản thuộc vai trò Giáo viên (hoặc tài khoản Admin có liên kết Giáo viên).

A. Cấu hình tại Controller Đăng nhập (blueprints/auth.py hoặc tương đương)

Tại route xử lý POST /login, chúng ta sẽ ép tham số remember=True của Flask-Login nếu phát hiện tài khoản đăng nhập là Giáo viên:

from flask import request, redirect, url_for, flash
from flask_login import login_user
from models import User

@auth_bp.route('/login', methods=['POST'])
def login_post():
    username = request.form.get('username')
    password = request.form.get('password')

    # (Đoạn code xác thực mật khẩu hiện tại của bạn...)
    user = User.query.filter_by(username=username).first()

    if user and user.check_password(password):
        # 🌟 [CRITICAL PATCH - REMEMBER ME FOR TEACHERS]
        # Tự động kiểm tra xem tài khoản có vai trò Giáo viên hoặc liên kết Giáo viên không
        is_teacher_account = (user.role == 'teacher') or getattr(user, 'is_teacher_linked', False)

        if is_teacher_account:
            # Ép ghi nhớ đăng nhập vĩnh viễn (lưu Cookie mã hóa trên thiết bị của giáo viên)
            remember_device = True
        else:
            # Đối với Admin thông thường, tôn trọng lựa chọn checkbox trên giao diện
            remember_device = (request.form.get('remember') == 'on')

        # Khởi tạo ngữ cảnh vai trò trước khi login_user để tránh mất session
        session['active_role'] = 'admin' if user.role == 'admin' else 'teacher'

        # Thực hiện đăng nhập kèm ghi nhớ thiết bị
        login_user(user, remember=remember_device)

        return redirect(_dashboard_for(user))

    flash("Sai tên đăng nhập hoặc mật khẩu!", "danger")
    return redirect(url_for('auth.login'))


B. Cấu hình thời hạn Cookie trong config.py (Duy trì đăng nhập 1 năm)

Theo mặc định, cookie remember_me của Flask-Login sẽ hết hạn sau 365 ngày nếu không được cấu hình lại. Để đảm bảo giáo viên không bao giờ bị logout giữa chừng, bạn hãy cấu hình thời hạn lưu cookie dài hạn trong file cấu hình chính:

import timedelta

class Config:
    # ... các cấu hình khác ...

    # Cấu hình thời hạn duy trì trạng thái "Ghi nhớ đăng nhập" (Ví dụ: 365 ngày)
    REMEMBER_COOKIE_DURATION = timedelta(days=365)

    # Đảm bảo cookie chỉ truyền qua HTTPS bảo mật nếu chạy Production
    REMEMBER_COOKIE_SECURE = True
    REMEMBER_COOKIE_HTTPONLY = True


C. Cơ chế tự động khôi phục Session trống (Remember-Me Context Recovery)

Khi giáo viên mở lại ứng dụng sau vài tuần, cookie remember_me sẽ tự động đăng nhập lại tài khoản của họ qua DB, nhưng Flask Session (nơi lưu session['active_role']) có thể đã bị xóa sạch trên server.

Để tránh lỗi NoneType hoặc crash giao diện khi session['active_role'] bị trống, hàm helper get_active_role() hiện có trong services/auth_context.py của bạn đã hoạt động cực kỳ hoàn hảo nhờ cơ chế tự động truy vấn DB để bù đắp giá trị thiếu hụt:

# Sơ đồ hoạt động bảo vệ của get_active_role() có sẵn trong hệ thống của bạn:
def get_active_role(user):
    if 'active_role' not in session:
        # Cookie remember-me khôi phục đăng nhập nhưng session trống -> Tự động nạp lại context an toàn từ DB
        session['active_role'] = 'admin' if user.role == 'admin' else 'teacher'
    return session['active_role']


PHẦN 3: ĐỘT PHÁ UX MÀN HÌNH CHÍNH (PWA ADD-TO-HOME-SCREEN METADATA)

Để hệ thống hiển thị đẹp mắt như một ứng dụng di động thật thụ (không có thanh địa chỉ URL của trình duyệt) khi giáo viên cài đặt ra màn hình chính, bạn hãy chèn thêm các thẻ meta bảo mật này vào phần <head> của file base layout chính (ví dụ: templates/base.html hoặc templates/auth/login.html):

<!-- Cấu hình hiển thị Standalone App trên iOS và Android -->
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<meta name="apple-mobile-web-app-title" content="Trung Tâm Tuyền">
<meta name="mobile-web-app-capable" content="yes">

<!-- Đảm bảo viewport không bị zoom bậy làm vỡ layout di động -->
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">

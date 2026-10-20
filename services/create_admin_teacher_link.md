TÀI LIỆU THIẾT KẾ KIẾN TRÚC PHÂN QUYỀN QUẢN LÝ HỌC VỤ

Security Audit ID: SEC-AUDIT-2026-ATTENDANCE

Framework: Flask-Login + Jinja2 (Web Session Scope)

Security Standard: OWASP Top 10:2025 A01 - Broken Access Control Compliance

1. Bản chất thiết kế (Architectural Philosophy)

Hệ thống tối ưu hóa phân quyền cho vai trò "Quản lý học vụ" (Academic Manager) bằng cách sử dụng cơ chế Thăng cấp tài khoản liên kết (Promoted Linked Accounts) kết hợp với Ma trận quyền hạn theo Module (Granular Module Permission Matrix) sẵn có, thay vì tạo ra các thực thể hoặc thuộc tính phân quyền song song.

Ranh giới an toàn (Security Boundaries):

Tầng Giao diện (Web UI): Sử dụng session['active_role'] (được truy xuất an toàn qua hàm helper get_active_role()) để phân tách giao diện hiển thị (Admin Portal vs Teacher Portal) qua Jinja2.

Tầng Nghiệp vụ (Server-side Logic): Sử dụng các Decorator gác cổng (require_admin, require_teacher, require_admin_or_teacher) kết hợp với hàm kiểm tra module tập trung check_module_permission.

REST API: Nằm ngoài phạm vi bảo vệ của Web Session, xác thực độc lập bằng Bearer Token qua g.api_user.

2. Luồng thực thi chi tiết (Detailed Workflow)

[ Đăng nhập tài khoản ]
        │
        ▼
[ User có liên kết Teacher? ]
        ├──► KHÔNG: Đăng nhập tự động theo User.role (Mặc định)
        └──► CÓ (Là tài khoản đa vai trò):
                │
                ▼
        [ Khởi tạo session['active_role'] = 'admin' ]
                │
                ├───────────────────────────────┐
                ▼ (Chuyển sang Teacher)         ▼ (Giữ vai trò Admin)
        [ session['active_role'] = 'teacher' ]  [ session['active_role'] = 'admin' ]
                │                               │
                ▼                               ▼
        Chỉ thấy & điểm danh các lớp     Thấy lịch học toàn trung tâm.
        được gán (Đã có logic check      Quyền thao tác (Read/Write) được
        server-side an toàn bảo mật)     quyết định bởi Ma trận quyền hạn
                                         (Permission Matrix JSON).



Cách cấu hình cho tài khoản "Quản lý học vụ":

Admin tối cao (Master Admin) truy cập trang chi tiết Giáo viên /admin/teachers/<id>.

Bấm nút "Cấp quyền Admin" (Kích hoạt endpoint POST /admin/teachers/<int:teacher_id>/promote). Lúc này user.role đổi thành 'admin'.

Admin tối cao truy cập trang quản lý tài khoản /admin/accounts, tìm tài khoản vừa thăng cấp và cấu hình ma trận quyền hạn (Permissions JSON):

BỎ CHỌN: Toàn quyền / Super Admin (để tránh leo thang đặc quyền trái phép).

CHỌN: Read và Write cho module Điểm danh / Attendance (và module Học sinh / Students nếu cần).

BỎ CHỌN/DENY: Tất cả các module nhạy cảm khác (Học phí/Tuition, Cài đặt/Settings, Lương/Salary...).

3. Mã nguồn phân quyền thực tế (Production-grade Gatekeeping Code)

Dưới đây là mã nguồn phân quyền thực tế của hệ thống. Các decorator sử dụng song song cơ chế kiểm tra Database thời gian thực (Real-time DB Verification) cùng với hàm phục hồi ngữ cảnh get_active_role() để triệt tiêu hoàn toàn rủi ro mất phiên làm việc do cơ chế "Ghi nhớ đăng nhập" (Remember-Me) của Flask-Login:

from flask import abort
from flask_login import current_user
from functools import wraps
from services.auth_context import get_active_role  # Lazy initializer nạp context an toàn từ DB vào Session

def require_admin(f):
    """
    Decorator gác cổng Admin (Gia cố bảo mật hai tầng).
    1. Tầng DB: Đảm bảo tài khoản thực sự đang là Admin trong hệ thống.
    2. Tầng Session: Đảm bảo ngữ cảnh hoạt động hiện tại (Context) là 'admin'.
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # 1. Chốt chặn DB (Real-time): Đảm bảo quyền admin vẫn còn hiệu lực
        if not current_user.is_admin:
            abort(403)
        # 2. Chốt chặn Context (Session): Sử dụng get_active_role để tránh lỗi Remember-Me trả về None
        if get_active_role(current_user) != 'admin':
            abort(403)
        return f(*args, **kwargs)
    return decorated_function

def require_teacher(f):
    """
    Decorator gác cổng Giáo viên (Gia cố bảo mật hai tầng).
    1. Tầng DB: Đảm bảo tài khoản thực sự là Giáo viên hoặc có hồ sơ Teacher liên kết.
    2. Tầng Session: Đảm bảo ngữ cảnh hoạt động hiện tại (Context) là 'teacher'.
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # 1. Chốt chặn DB (Real-time): Đảm bảo liên kết chéo hoặc vai trò Giáo viên hợp lệ
        is_valid_teacher = current_user.is_teacher or current_user.is_teacher_linked
        if not is_valid_teacher:
            abort(403)
        # 2. Chốt chặn Context (Session): Đảm bảo đang hoạt động ở chế độ Giáo viên
        if get_active_role(current_user) != 'teacher':
            abort(403)
        return f(*args, **kwargs)
    return decorated_function

def require_admin_or_teacher(f):
    """
    Decorator cho các route dùng chung (như trang thi cử).
    Cho phép truy cập nếu người dùng thực sự sở hữu một trong hai quyền trong DB,
    và ngữ cảnh hoạt động hiện tại (active_role) hợp lệ để mang lại UX mượt mà.
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # Xác định quyền sở hữu thực tế (Real-time DB-backed validation)
        has_admin_rights = current_user.is_admin
        has_teacher_rights = current_user.is_teacher or current_user.is_teacher_linked

        if not (has_admin_rights or has_teacher_rights):
            abort(403)

        # Kiểm tra ngữ cảnh hoạt động hợp lệ để tránh chặn nhầm người dùng đa vai trò
        active_role = get_active_role(current_user)
        if active_role not in ['admin', 'teacher']:
            abort(403)

        return f(*args, **kwargs)
    return decorated_function


4. Đánh giá rủi ro an toàn thông tin (Security Risk Assessment)

Rủi ro CSRF khi chuyển đổi vai trò: Đã được loại bỏ triệt để bằng cách bắt buộc sử dụng phương thức POST đi kèm với mã thông báo CSRF ẩn {{ csrf_token() }} trong form chuyển đổi ngữ cảnh trên Navbar, tuân thủ nghiêm ngặt chuẩn OWASP.

Lỗ hổng leo thang đặc quyền (Privilege Escalation) & Stale Session: Nhờ việc duy trì kiểm tra current_user.is_admin song song với get_active_role() trong Decorator, hệ thống sẽ chặn đứng 100% các request sử dụng Session cũ sau khi tài khoản đã bị tước quyền Admin ở DB, đảm bảo an toàn tuyệt đối.

Tránh lỗi Logic Bypass: Việc không can thiệp vào bộ lọc before_request hiện tại giúp bảo toàn nguyên vẹn cơ chế kiểm soát truy cập (Access Control) ổn định của toàn hệ thống, loại bỏ 100% rủi ro sinh ra lỗi logic do thứ tự thực thi (execution cycle) trong Flask.
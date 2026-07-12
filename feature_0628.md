Chỉnh sửa trang List students (danh sách học sinh)
1. Thêm phân trang dạng < ... >
2. Lựa chọn số lượng record trên phân trang theo option 10/20/40/80/All ở trước phần danh sách (list)
3. Trong file import nếu có lỗi thì hiển thị thông báo dạng errors là "Thiếu thông tin học sinh, vui lòng nhập đầy đủ thông tin cần thiết"'
4. Khi chọn tạo tài khoản phụ huynh mặc định lấy ten_hoc_sinh và sử dụng @+ten_hoc_sinh+nam_sinh (nội dung ở họ và tên không dấu) để làm thông tin đăng nhập
4. Ở trang chi tiết thông tin học sinh cho phép admin có thể nhấn reset password ở về định dạng chung @+ten_hoc_sinh+nam_sinh 
5. Cho phép chọn nhiều và xoá nhiều, hiển thị pop-up cảnh báo nếu xác nhận thì xoá mềm (bật cờ delete_flat= 1 ở database)
6. Không bắt buộc nhập tên phụ huynh và số điện thoại của phụ huynh đối với chức năng import trong admin và create trong admin.
Chỉnh sửa thông tin ở Parent
1. Cho phép thay đổi mật khẩu. 
Chỉnh sửa trang quản lý đề thi
1. Thêm chức năng tạo thư mục (chọn tạo cho lớp hoặc tạo cho môn)
2. Bổ sung chức năng lọc
3. Thêm chức năng hiển thị kết quả làm bài cho mỗi đề gồm 
Tên học sinh|Điểm (số lần làm bài: ) |Thời gian làm bài| Số lần cảnh cáo|
4. Bổ sung gửi cảnh báo về cho admin và người tạo đề (gíao viên chính của lớp) về tên học sinh thoát màn hình quá 3 lần. 
5. Đảm bảo đề có thể tái sử dụng nhiều lần
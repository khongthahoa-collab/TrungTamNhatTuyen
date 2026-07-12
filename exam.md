Tạo thêm 1 trang phục vụ cho mục đích thi online trên máy tính và cả điện thoại, ipad. Có chức năng cảnh báo nếu phát hiện gian lận ví dụ như thoát màn hình… quá 3 lần và tự động kết thúc bài làm sau đó trả kết quả thi trực tiếp về cho học sinh. 
Thiết kế màn hình admin/teacher
Ở trang tạo đề thi hiển thị thành 3 phần. Tham khảo trang https://azota.vn/ làm mẫu để tạo đề chuẩn hoá.
Phần 1: Ô nhập tên đề thi, ví dụ: Đề ôn thi giữa kì 1 nằm ở trên cùng chính giữa chỉ chiếm 1 phần nhỏ trong trang
Phần 2 và 3 chi màn hình còn lại thành 2 phần mỗi bên 1 nửa. Phần số 2 nằm bên trái hiển thị kết quả hiển thị nhập liệu dạng trực quan. Phần 3 nằm bên phải là phần imput đề và đáp án. 
Ở trang xác nhận tạo đề có các tính năng:
Chọn môn thi (dropdown select), loại bài thi (ôn tập, kiểm tra 15 phút, kiểm tra định kì, giữa kì 1, cuối kì 1, giữa kì 2, cuối kì 2, khác)
Chọn lớp cần giao (dropdown select) , đề có thể lưu dưới dạng nháp để xem lại. 
Cài đặt thời gian làm bài (radiobox) ( 15 phút, 20 phút, 30 phút, 60 phút, 90 phút)
Cài đặt thời gian có thể làm bài ( từ ngày - đến ngày, không giới hạn, trong khung giờ học của lớp học). 
Cài đặt số lần làm lại (radiobox): chọn bài ôn tập thì có thể làm nhiều lần, chọn bài thi thì chỉ có thể làm 1 lần. Mỗi lần làm sẽ xáo trộn vị trí câu hỏi và đáp án.
Cài đặt số lượng đề (nhiều nhất là 24 đề) với nội dung giống nhau nhưng khác vị trí câu hỏi và đáp án nếu. 
Các đề thi đã được tạo sẽ được thêm vào trang Quản lý tài liệu ( hiện có ) để sau này tái xử dụng.
Phân quyền
Teacher: có quyền tạo đề và xoá đề (chỉ xoá các đề mà mình tạo ra) . Có thể export đề đã làm về dạng pdf hoặc word
Admin: có quyền tạo đề và xoá tất cả các đề.
Các thao tác sẽ được lưu vào database ở bảng log_exam
Thiết kế màn hình parent
Chỉ có quyền làm bài thi không có quyền chỉnh sửa đề
Phải đăng nhập mới có quyền làm bài thi. Thi xong kết quả sẽ được hiển thị trên màn hình chính. Bài làm bị đánh dấu là gian lận sẽ tính như đã làm xong và tính điểm nhưng sẽ hiển thị cảnh báo vàng. 

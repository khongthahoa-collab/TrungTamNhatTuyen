# Phương án trang chi tiết điểm giáo viên

## 1. Phạm vi đề xuất

Tạo thêm luồng quản lý điểm cho giáo viên theo ba tầng:

```text
/teacher/scores
    -> Danh sách lớp

/teacher/scores/<class_id>/detai
    -> Chi tiết điểm của một lớp theo năm

/teacher/scores/<class_id>
    -> Nhập điểm cho lớp
```

Trang `/teacher/scores/<class_id>/detai` chỉ dùng để xem và phân tích điểm. Trang nhập điểm hiện tại vẫn được giữ riêng để tránh trộn hai mục đích trong cùng một màn hình.

## 1.1. Quy tắc nghiệp vụ

- Điểm dưới ngưỡng 50%, tương ứng dưới `5` trên thang điểm mặc định 10, là `Không đạt`.
- Điểm từ `5` trở lên trên thang điểm mặc định 10 là `Đạt`.
- Giao diện hiển thị điểm dạng số đơn, ví dụ `2.25`, không hiển thị hậu tố `/10`.
- Thang điểm mặc định hiện tại là `10`; `max_score` vẫn phải được lưu riêng để sẵn sàng mở rộng sau này.
- Chỉ điểm của Trung tâm Nhật Tuyến (`score_source = center`) được dùng để tính Đạt/Không đạt, điểm trung bình, đánh giá tiến bộ và các thống kê.
- Điểm thi tại trường học không tham gia vào các chỉ số của Trung tâm.
- Điểm trường học có thể được giữ lại để quan sát trong dữ liệu cũ, nhưng không hiển thị trong luồng đánh giá mới.
- Đợt đầu chỉ nhập điểm thủ công; điểm từ bài thi trực tuyến chưa phát sinh vì hệ thống thi trực tuyến chưa được triển khai.
- Khi triển khai thi trực tuyến, điểm nhập tay và điểm từ bài thi trực tuyến đều là điểm Trung tâm, được phân biệt bằng `entry_method`.
- Admin và teacher được xem hoặc cập nhật điểm trong phạm vi được phép.
- Parent và student chỉ được xem thống kê của học sinh mà mình được phép xem; không được sửa, xóa hoặc thêm điểm.

## 2. Đánh giá hiện trạng

Hệ thống đã có các thành phần phù hợp để thực hiện tính năng này:

- Đã có route `/teacher/scores` để liệt kê lớp.
- Đã có route `/teacher/scores/<class_id>` để nhập điểm.
- Bảng `scores` đã có:
  - `student_id`
  - `class_id`
  - `score_source`
  - `score_type`
  - `score_value`
  - `max_score`
  - `exam_date`
  - `note`
  - `entered_by`
- Đã tách nguồn điểm thành điểm tại Trung tâm và điểm từ trường.
- Đã có các enum/label `ScoreSource` và `ScoreType`.

Vì vậy, không cần tạo bảng điểm mới. Nên tái sử dụng bảng `scores`, bổ sung validate và audit cho luồng điểm thủ công, sau đó mới bổ sung provenance và đồng bộ điểm trực tuyến khi hệ thống thi trực tuyến được triển khai.

### 2.1. Các tiền điều kiện cần chuẩn hóa

> **Đã xác minh trong code ngày 13/09/2026.** Hai tiền điều kiện đầu tiên dưới đây không còn là giả định — đã kiểm tra và xác nhận là vấn đề có thật, xem phần 2.2.

- Chỉ sử dụng giá trị enum `center` và `school` cho `score_source`; không sử dụng giá trị hiển thị như `truong` làm giá trị lưu trong database.
- Kiểm tra `student_id` thực sự thuộc `class_id` trước khi tạo hoặc cập nhật điểm.
- Kiểm tra `score_value >= 0`, `max_score > 0` và `score_value <= max_score` trước khi ghi.
- Dùng một hàm kiểm tra quyền lớp chung cho danh sách lớp, trang chi tiết và trang nhập điểm; không chỉ ẩn nút trên giao diện.
- Đợt đầu, bộ lọc `năm` là năm dương lịch của `exam_date`. Nếu sau này cần lọc theo năm học, bổ sung `academic_year_id` hoặc một quy tắc năm học riêng.
- Nếu parent hiện có luồng báo cáo điểm bên ngoài, phải tắt hoặc tách luồng đó nếu chính sách mới yêu cầu parent/student tuyệt đối không được thêm điểm.

### 2.2. Hai vấn đề đã xác minh trong code (phải xử lý trước khi lập trình)

#### Vấn đề 1: Phụ huynh HIỆN ĐANG được phép tự thêm điểm

Đây không phải giả định — route đã tồn tại trong `blueprints/parent.py`:

```python
@parent_bp.route('/students/<int:student_id>/scores/report', methods=['POST'])
def score_report(student_id):
    """Parent reports an external/school score for their child."""
```

Chức năng này **mâu thuẫn trực tiếp** với quy tắc mới ở mục 1.1: *"Parent và student chỉ được xem thống kê... không được sửa, xóa hoặc thêm điểm."*

Đây là quyết định nghiệp vụ, không phải quyết định kỹ thuật. Cần chốt một trong ba hướng:

| Hướng xử lý | Hệ quả |
|---|---|
| Bỏ hẳn chức năng phụ huynh báo điểm | Đúng chính sách mới, nhưng mất một kênh thu thập điểm trường học |
| Giữ nhưng chỉ cho `score_source = school` | Phụ huynh vẫn báo được điểm trường, điểm đó không ảnh hưởng thống kê Trung tâm (vì luồng mới chỉ lọc `center`) |
| Giữ nhưng chuyển sang cơ chế duyệt | Phụ huynh gửi đề xuất, giáo viên duyệt mới thành điểm chính thức — tốn công nhất |

**Khuyến nghị:** hướng thứ hai. Quy tắc mới chỉ lọc `score_source = center` cho mọi thống kê, nên điểm trường do phụ huynh nhập tự động nằm ngoài luồng đánh giá mà không cần bỏ tính năng. Chỉ cần đảm bảo route này **không thể** tạo điểm với `score_source = center`.

#### Vấn đề 2: Phải kiểm tra dữ liệu `score_source` thật trước khi tin vào bộ lọc

Toàn bộ logic Đạt/Không đạt, điểm trung bình và chỉ báo tiến bộ đều lọc theo `score_source = 'center'`. Nếu dữ liệu cũ trên production có dòng nào lưu sai giá trị (ví dụ `truong`, `Trung tâm`, chuỗi rỗng hoặc `NULL`), các dòng đó sẽ **âm thầm biến mất** khỏi mọi thống kê — trang vẫn chạy bình thường, không báo lỗi, nhưng số liệu sai.

Đây là loại lỗi nguy hiểm nhất vì không có dấu hiệu nào để phát hiện.

Bắt buộc chạy kiểm tra trên database production **trước khi** lập trình:

```sql
SELECT score_source, COUNT(*)
FROM scores
GROUP BY score_source
ORDER BY COUNT(*) DESC;
```

Xử lý theo kết quả:

- Chỉ thấy `center` và `school`: dữ liệu sạch, làm tiếp bình thường.
- Có giá trị lạ hoặc `NULL`: phải viết script chuẩn hóa dữ liệu **trước**, và quyết định từng giá trị lạ thuộc nhóm nào.
- Số dòng `center` bằng 0 hoặc quá ít so với thực tế: dừng lại, dữ liệu cũ có thể đang dùng quy ước khác hẳn.

## 3. Giao diện đề xuất

### 3.1. Danh sách lớp

Tại `/teacher/scores`, mỗi lớp có hai thao tác:

- `Chi tiết điểm`: mở `/teacher/scores/<class_id>/detai`.
- `Nhập điểm`: mở `/teacher/scores/<class_id>`.

Cách tách này giúp giáo viên không nhầm giữa việc xem lịch sử và việc tạo một lần điểm mới.

### 3.2. Chi tiết điểm theo năm

URL đề xuất:

```text
/teacher/scores/<class_id>/detai
```

Có thể hỗ trợ thêm alias `/teacher/scores/<class_id>/detail` nếu cần URL tiếng Anh. URL `/detai` được giữ theo yêu cầu hiện tại.

> **Khuyến nghị cập nhật 13/09/2026:** `/detai` là lỗi chính tả của `detail`. Nên **đảo ngược lại**: dùng `/detail` làm URL chính thức, và chỉ giữ `/detai` làm alias chuyển hướng nếu đã lỡ có link trỏ tới. Lý do: URL sai chính tả một khi đã đưa vào vận hành sẽ tồn tại vĩnh viễn (nằm trong bookmark, link đã gửi, lịch sử trình duyệt), gây khó hiểu cho bất kỳ ai bảo trì hệ thống về sau. Chi phí sửa bây giờ bằng 0, chi phí sửa sau này là phải duy trì mãi cả hai đường dẫn.

Bộ lọc:

| Bộ lọc | Giá trị |
|---|---|
| Năm | Ví dụ 2026 |
| Loại kiểm tra | Tất cả, KT thường xuyên, 15 phút, Miệng, Giữa kỳ, Cuối kỳ |
| Nguồn | Trung tâm NT |

Mặc định đề xuất:

- Năm: năm hiện tại.
- Nguồn: `Trung tâm NT`, cố định trong luồng đánh giá.
- Loại kiểm tra: Tất cả.

Mục đích của trang là theo dõi kết quả học tập tại Trung tâm Nhật Tuyến. Điểm trường học chỉ là thông tin quan sát, không được trộn vào kết quả đánh giá của Trung tâm.

Nếu cần quản lý dữ liệu trường học cũ, nên đặt ở một màn hình quan sát riêng hoặc ẩn khỏi trang này.

### 3.3. Bảng lịch sử điểm

Các cột hiển thị:

```text
Tên học sinh
Loại kiểm tra
Nguồn
Điểm
Trạng thái
Ngày thi
Ghi chú
```

Ví dụ:

```text
Lưu Lam | KT thường xuyên | Trung tâm NT | 8.5 | Đạt       | 13/09/2026
Tuệ Di  | KT thường xuyên | Trung tâm NT | 4.9 | Không đạt | 13/09/2026
```

Giao diện không hiển thị `/10` vì thang điểm hiện tại mặc định là 10. Giá trị lưu trong database vẫn gồm `score_value` và `max_score` để không mất thông tin khi mở rộng thang điểm.

Trạng thái được tính theo điểm đã chuẩn hóa:

```text
normalized_score = score_value / max_score * 10

normalized_score >= 5: Đạt
normalized_score < 5: Không đạt
```

Khi mở rộng thang điểm, nên dùng tỷ lệ phần trăm:

```text
normalized_percent = score_value / max_score * 100
normalized_percent >= pass_percent: Đạt
normalized_percent < pass_percent: Không đạt
```

Phải kiểm tra `max_score > 0` trước khi tính để tránh chia cho 0.

### 3.4. Import và export

Import và export là nhóm chức năng mở rộng, không bắt buộc trong MVP của trang chi tiết.

#### Import điểm từ file

Admin và teacher có thể import điểm Trung tâm từ CSV hoặc Excel (`.xlsx`) trong giai đoạn sau. File mẫu có thể gồm:

```text
Mã học sinh hoặc ID học sinh
Tên học sinh (để đối chiếu, không dùng làm khóa duy nhất)
Lớp
Loại kiểm tra
Điểm
Điểm tối đa
Ngày thi
Ghi chú
Phương thức
Mã bài thi trực tuyến (nếu có)
```

Quy trình bắt buộc:

1. Tải file mẫu từ trang thống kê.
2. Upload file.
3. Kiểm tra định dạng và hiển thị preview, chưa ghi database.
4. Đối chiếu học sinh theo ID/mã học sinh và lớp.
5. Kiểm tra điểm, `max_score`, ngày thi, loại kiểm tra và quyền của người import.
6. Báo rõ dòng hợp lệ, dòng lỗi và lý do lỗi.
7. Chỉ ghi database sau khi người dùng xác nhận.
8. Tạo audit log cho lần import và từng dòng dữ liệu.

Quy tắc an toàn:

- Import chỉ được tạo điểm `score_source = center`.
- Parent/student không có quyền import.
- Teacher chỉ import cho lớp được phân công; admin được import trong phạm vi quản trị.
- Không dùng tên học sinh làm khóa duy nhất.
- Nếu có `online_attempt_id`, phải kiểm tra unique để không tạo điểm trùng.
- Nếu trùng bản ghi, mặc định không tự động ghi đè; phải cho chọn `bỏ qua` hoặc `cập nhật`.
- File lỗi không được ghi một phần mà không thông báo rõ kết quả.
- Giới hạn kích thước file và chỉ chấp nhận CSV/XLSX.

#### Export dữ liệu

Admin và teacher có thể export đúng tập dữ liệu đang lọc:

- CSV cho xử lý nhanh và backup.
- XLSX cho giáo viên tiếp tục làm việc trên Excel.
- Bao gồm học sinh, lớp, loại kiểm tra, điểm, `max_score`, trạng thái, ngày thi, ghi chú và phương thức.
- Mặc định chỉ export điểm `score_source = center`.
- Teacher chỉ export các lớp được phân công.
- Parent/student không export bảng điểm tập thể; chỉ có thể tải thống kê cá nhân được phép xem.

Export phải áp dụng lại bộ lọc năm, loại kiểm tra và học sinh đang chọn. Không export mật khẩu, token, audit chi tiết hoặc thông tin của học sinh khác.

### 3.5. Xuất ảnh và gửi điểm

Đây là chức năng mở rộng sau khi bảng thống kê ổn định. Luồng đề xuất:

1. Chọn một học sinh.
2. Chọn năm và phạm vi điểm Trung tâm.
3. Tạo bản xem trước thống kê dạng ảnh.
4. Cho phép `Tải ảnh`, `Chia sẻ` hoặc `Gửi điểm`.

Ảnh thống kê nên gồm:

```text
Tên học sinh
Lớp
Khoảng thời gian
Danh sách các lần kiểm tra Trung tâm
Điểm hiển thị dạng số đơn
Trạng thái Đạt/Không đạt
Điểm trung bình
Chỉ báo tiến bộ
Ngày tạo ảnh
```

Không hiển thị điểm trường học hoặc thông tin nội bộ trong ảnh thống kê Trung tâm.

Trên trình duyệt, ưu tiên Web Share API nếu thiết bị hỗ trợ; nếu không, cho tải ảnh JPEG/PNG. Nếu dùng `ZaloService`, cần có preview, xác nhận người nhận, giới hạn gửi lại và delivery log. Không cho phép gửi hàng loạt mặc định.

## 4. Đánh giá sự tiến bộ

### 4.1. Cách tính đơn giản

Chỉ lấy các bản ghi có `score_source = center` trong cùng bộ lọc năm và loại kiểm tra:

- Sắp xếp điểm của từng học sinh theo ngày thi tăng dần.
- Lấy điểm đầu tiên.
- Lấy điểm gần nhất.
- Tính chênh lệch:

```text
delta = điểm_gần_nhất - điểm_đầu_tiên
```

Bảng tiến bộ:

```text
Tên học sinh
Số lần kiểm tra
Điểm lần đầu
Điểm gần nhất
Thay đổi
Đánh giá
```

Nhãn đánh giá:

- `Có tiến bộ`: `delta > 0`.
- `Cần theo dõi`: `delta < 0`.
- `Ổn định`: `delta = 0`.
- `Cần thêm lần kiểm tra`: mới có một lần điểm.

Quy tắc Đạt/Không đạt của từng lần kiểm tra độc lập với `delta`. Ví dụ, học sinh tăng từ 3.0 lên 4.5 là có tiến bộ nhưng vẫn chưa đạt; học sinh tăng từ 4.5 lên 5.5 là có tiến bộ và đã đạt.

### 4.2. Giới hạn của cách tính

So sánh lần đầu và lần gần nhất dễ hiểu nhưng chưa phân biệt được:

- Bài dễ và bài khó.
- Loại bài kiểm tra khác nhau.
- Khoảng cách thời gian giữa hai lần thi.
- Một điểm bất thường do nhập sai.

Vì vậy, không nên dùng `delta` làm kết luận duy nhất về học lực. Nên đặt tên là `Chỉ báo tiến bộ` và cho phép giáo viên xem lịch sử chi tiết.

### 4.3. Giai đoạn mở rộng

Khi dữ liệu đủ ổn định, có thể thêm:

- Điểm trung bình theo thời gian.
- Trung bình trượt của 3 lần gần nhất.
- So sánh cùng loại bài kiểm tra qua các lần.
- Biểu đồ theo ngày thi.
- Cảnh báo học sinh giảm điểm liên tiếp 2-3 lần.
- Mục tiêu học tập riêng của từng học sinh.

Không nên làm biểu đồ trước khi bộ lọc và dữ liệu điểm ổn định.

## 5. Nguồn điểm và phương thức ghi nhận

Tiếp tục dùng trường `score_source`:

```text
center -> Trung tâm Nhật Tuyến
school -> Trường học
```

Trong MVP, điểm nhập tay dùng `entry_method = manual`. Các trường chuẩn bị cho hệ thống thi trực tuyến có thể nullable:

```text
entry_method = manual | online_exam
online_attempt_id = nullable, unique khi có
entered_by = user id, bắt buộc với điểm nhập tay
updated_by = user id
updated_at = datetime
```

> **Khuyến nghị thu hẹp phạm vi đợt đầu (13/09/2026):** nên tách 5 cột trên thành hai nhóm thay vì thêm hết cùng lúc:
>
> | Cột | Đợt đầu | Lý do |
> |---|---|---|
> | `updated_by`, `updated_at` | **Thêm ngay** | Hữu ích lập tức: cần cho audit khi giáo viên sửa điểm, không phụ thuộc hệ thống nào khác |
> | `entry_method`, `online_attempt_id` | **Hoãn** | Chỉ phục vụ hệ thống thi trực tuyến — thứ chưa tồn tại |
>
> Lý do hoãn hai cột sau: hệ thống thi trực tuyến còn xa hơn dự kiến ban đầu (xem đánh giá quy mô trong `plan_online_exam_architecture.md` mục 3.5 — bài toán 1000 user đồng thời cần thay đổi hạ tầng, không chỉ viết thêm tính năng). Thêm `entry_method` ngay bây giờ nghĩa là phải backfill toàn bộ dòng điểm cũ, và code bắt đầu rẽ nhánh theo một trường chỉ có duy nhất một giá trị.
>
> Thêm một cột nullable vào lúc thực sự cần là việc rất nhanh. Hoãn không mất gì; thêm sớm thì phải mang theo trong mọi lần đọc/ghi/migration từ nay tới lúc dùng.

Nếu cần bảo toàn cấu hình tại thời điểm nhập, có thể bổ sung `pass_percent`. Trong đợt đầu, dùng mặc định hệ thống là `50` thay vì tạo ngay một bảng cấu hình riêng.

Quy tắc nghiệp vụ cho tương lai:

- Điểm nhập tay của giáo viên/admin là `score_source = center` và `entry_method = manual`.
- Khi hệ thống thi trực tuyến được triển khai, điểm đã nộp và chấm thành công mới được tạo hoặc cập nhật vào `Score` với `entry_method = online_exam`.
- `online_attempt_id` phải duy nhất để retry đồng bộ không tạo điểm trùng.
- Không tạo điểm online khi attempt chưa nộp hoặc chấm điểm chưa thành công.
- Mọi lần sửa phải lưu `updated_by`, `updated_at` và audit log.
- Giá trị lưu trong database phải dùng enum ổn định, không dùng nhãn hiển thị.

## 6. Đồng bộ điểm từ thi trực tuyến trong tương lai

Hiện tại hệ thống chưa có thi trực tuyến. Vì vậy, phần này là thiết kế chuẩn bị và không phải blocker của MVP trang chi tiết điểm. Chưa cần tạo endpoint đồng bộ hoặc worker trước khi có `ExamAttempt` và quy trình chấm điểm thực tế.

Luồng đề xuất khi bắt đầu triển khai:

```text
Học sinh nộp ExamAttempt
    -> Server chấm điểm
    -> Kiểm tra attempt đã submitted và có kết quả hợp lệ
    -> Tạo/cập nhật Score
    -> score_source = center
    -> entry_method = online_exam
    -> online_attempt_id = ExamAttempt.id
```

Khuyến nghị đồng bộ ngay khi nộp bài và chấm điểm thành công trong cùng transaction. Nếu ghi `Score` thất bại, transaction phải rollback hoặc đánh dấu attempt cần đồng bộ lại.

Trước khi triển khai, cần chốt mapping từ bài thi sang `class_id`, `score_type`, `exam_date`, `max_score` và trạng thái chấm điểm. Cần có thao tác nội bộ để đồng bộ lại các attempt `submitted` chưa có `Score`, với cơ chế idempotent chống nhân đôi.

Parent/student không được gọi endpoint đồng bộ hoặc sửa `Score`.

## 7. Truy vấn và hiệu năng

Route mới cần lọc ngay trong SQL:

- `class_id`.
- Năm của `exam_date`.
- Cố định `score_source = center`.
- `score_type` nếu có chọn.
- `entry_method` nếu admin/teacher cần phân biệt điểm nhập tay và điểm online.

Không lấy toàn bộ điểm của tất cả lớp rồi lọc trong Python.

Query sắp xếp theo:

```text
exam_date DESC, id DESC
```

Để tránh truy vấn lặp lại:

- Join `Score` với `Student` trong một query.
- Không gọi `student.scores` riêng cho từng học sinh.
- Có thể tính tiến bộ từ tập kết quả đã lọc nếu quy mô lớp vừa phải.
- Nếu lịch sử lớn, phân trang bảng lịch sử và dùng query aggregate riêng cho phần tổng hợp.

Index đề xuất:

```text
scores(class_id, exam_date)
scores(class_id, score_source, exam_date)
scores(student_id, exam_date)
scores(online_attempt_id) UNIQUE khi có
```

Trước khi tạo migration index, kiểm tra query plan bằng `EXPLAIN`.

## 8. Quyền truy cập

Giáo viên chỉ được xem và nhập điểm cho lớp được phân công hoặc lớp mà giáo viên là giáo viên chính theo quy tắc hiện tại của hệ thống. Route chi tiết phải kiểm tra quyền trên server. Khi đổi `class_id` trên URL sang lớp không có quyền, phải trả về `403`.

### Admin

- Xem, thêm, sửa và xóa điểm nhập tay trong phạm vi quản trị.
- Xem provenance và lịch sử thay đổi khi audit log đã được triển khai.
- Khi hệ thống thi trực tuyến được triển khai, được xem, điều chỉnh và đồng bộ điểm online theo quy trình kiểm soát.

### Teacher

- Xem điểm của lớp được phân công.
- Thêm và sửa điểm nhập tay trong phạm vi được phép.
- Không sửa điểm của lớp không được phân công.
- Quyền sửa điểm online chỉ mở sau khi có hệ thống thi trực tuyến và quy trình phê duyệt rõ ràng.

### Parent

- Chỉ xem thống kê điểm của con mình.
- Chỉ xem điểm `score_source = center`.
- Không thêm, sửa, xóa điểm và không xem danh sách điểm của học sinh khác.

### Student

- Chỉ xem thống kê điểm của tài khoản/học sinh đang đăng nhập.
- Chỉ xem điểm `score_source = center`.
- Không thêm, sửa, xóa điểm hoặc xem dữ liệu nội bộ như `entered_by` và audit log.

## 9. Phương án kỹ thuật khuyến nghị

### Giai đoạn 1: MVP trang chi tiết

- Thêm route chi tiết và template riêng.
- Thêm bộ lọc năm, loại kiểm tra; nguồn `center` được cố định trong luồng đánh giá.
- Hiển thị bảng lịch sử điểm.
- Hiển thị chỉ báo tiến bộ điểm đầu tiên/gần nhất.
- Tái sử dụng `Score`, `ScoreSource`, `ScoreType` hiện có.
- Chuẩn hóa `score_source` về `center`/`school` và validate điểm trước khi ghi.
- Dùng một hàm kiểm tra quyền lớp chung cho teacher và admin.
- Phân trang bảng lịch sử khi cần.
- Chưa bắt buộc import, export, xuất ảnh, gửi điểm hoặc đồng bộ online.

### Giai đoạn 2: Dữ liệu và chia sẻ

- Thêm audit log cho thao tác tạo/sửa/xóa điểm.
- Thêm import CSV/XLSX có preview, validate, chống ghi một phần và xác nhận trước khi ghi.
- Thêm export CSV/XLSX theo đúng bộ lọc và quyền.
- Thêm trang thống kê riêng cho parent/student, chỉ đọc.
- Thêm index kết hợp sau khi kiểm tra query plan bằng `EXPLAIN`.
- Thêm xuất ảnh và Web Share API sau khi bảng thống kê ổn định.
- Chỉ thêm gửi điểm qua Zalo sau khi có preview, xác nhận người nhận, giới hạn gửi lại và delivery log.

### Giai đoạn 3: Khi bắt đầu hệ thống thi trực tuyến

- Bổ sung `online_attempt_id`, `updated_by` và `updated_at` nếu chưa có.
- Chốt mapping từ `ExamAttempt` sang lớp, loại kiểm tra, ngày thi và thang điểm.
- Đồng bộ `ExamAttempt` sang `Score` trong cùng transaction sau khi nộp và chấm điểm thành công.
- Thêm thao tác đồng bộ lại cho bản ghi thất bại, có cơ chế idempotent chống nhân đôi.
- Mở quyền xem/sửa điểm online theo quy trình kiểm soát và audit log.
- Không cho parent/student gọi endpoint đồng bộ hoặc sửa điểm online.

### Giai đoạn 4: Phân tích mở rộng

- Thêm biểu đồ và các cảnh báo tiến bộ nâng cao.
- Thêm hệ thống rubric/mục tiêu học tập nếu Trung tâm có nhu cầu.
- Chỉ thêm snapshot hoặc materialized summary khi dữ liệu thực sự lớn.
- Không tạo microservice riêng cho trang điểm; đây là nghiệp vụ quản lý nhỏ và nên nằm trong teacher app.

## 10. Kết luận và các điểm cần phê duyệt

Phương án phù hợp nhất hiện tại là thêm trang chi tiết `/teacher/scores/<class_id>/detai`, chỉ lọc và đánh giá điểm Trung tâm Nhật Tuyến, áp dụng ngưỡng 50% tương ứng điểm 5 trên thang mặc định 10, lưu điểm nhập tay trong bảng `scores`, đồng thời kiểm tra quyền admin/teacher trên server và để parent/student chỉ xem thống kê cá nhân.

Không cần tạo bảng điểm mới, không cần tách service và không cần Redis trong đợt đầu. Hệ thống thi trực tuyến chưa triển khai nên không phải blocker của trang chi tiết. Tuy nhiên, cần chuẩn hóa `score_source` và validate dữ liệu trước khi triển khai; cần audit log trước khi mở các luồng sửa/xóa, import hoặc cập nhật hàng loạt.

Các điểm cần xác nhận trước khi lập trình:

1. ~~Giữ URL `/teacher/scores/<class_id>/detai`.~~ **Cập nhật 13/09/2026:** nên dùng `/detail` làm chính, `/detai` làm alias (xem mục 3.2).
2. Loại nguồn `school` khỏi luồng đánh giá mới; dữ liệu cũ nếu giữ chỉ dùng để quan sát.
3. Ngưỡng 50%, tương ứng điểm 5 trên thang mặc định 10, là `Đạt`.
4. Đợt đầu chỉ nhập điểm thủ công; quy tắc tạo `Score` từ điểm online sẽ được phê duyệt khi bắt đầu xây dựng hệ thống thi trực tuyến.
5. Parent/student chỉ xem thống kê điểm cá nhân, không xem bảng điểm lớp và không được thêm điểm.
6. Audit log là bắt buộc trước khi cho phép sửa/xóa hoặc import cập nhật dữ liệu.

### Bổ sung 13/09/2026: hai việc phải làm TRƯỚC khi viết dòng code đầu tiên

7. **Chốt hướng xử lý route `score_report` của phụ huynh** — route này đang tồn tại và cho phép phụ huynh thêm điểm, mâu thuẫn với quy tắc ở mục 1.1. Xem mục 2.2, vấn đề 1. Khuyến nghị: giới hạn route đó chỉ tạo được `score_source = school`.
8. **Chạy kiểm tra dữ liệu `score_source` trên production** — xem mục 2.2, vấn đề 2. Nếu dữ liệu không sạch, toàn bộ thống kê sẽ sai một cách âm thầm. Đây là bước kiểm tra 1 câu SQL, không được bỏ qua.

### Đánh giá khả thi tổng thể (13/09/2026)

Tài liệu này **khả thi cao, rủi ro thấp** và nên được ưu tiên triển khai trước hệ thống thi trực tuyến:

- Không cần thay đổi hạ tầng, không cần dịch vụ mới, không cần Redis.
- Quy mô dữ liệu nhỏ (điểm một lớp trong một năm chỉ vài trăm dòng) nên không có rủi ro hiệu năng như bài toán thi online.
- Tái sử dụng đúng bảng `Score`, enum `ScoreSource`/`ScoreType` và các route `/teacher/scores` đã có sẵn — kết luận "không cần tạo bảng điểm mới" là chính xác.
- Giá trị sử dụng đến ngay với giáo viên, không phụ thuộc vào bất kỳ hệ thống nào chưa tồn tại.

Rủi ro duy nhất đáng kể là **chất lượng dữ liệu `score_source` cũ** (mục 2.2) — không phải rủi ro kỹ thuật mà là rủi ro số liệu sai mà không ai phát hiện.

Tài liệu này là phương án theo giai đoạn. Phạm vi MVP là trang chi tiết và phân tích điểm nhập tay; import/export, audit nâng cao, chia sẻ và đồng bộ thi trực tuyến sẽ triển khai sau khi chốt yêu cầu tương ứng.

(() => {
  const openButton = document.getElementById('examGuideOpen');
  const dialog = document.getElementById('examGuide');
  if (!openButton || !dialog) return;

  const guides = {
    create: [
      ['[data-guide="compose"]', '1. Bắt đầu soạn đề',
        'Chọn “Bắt đầu soạn đề” để nhập câu hỏi trực quan hoặc soạn bằng văn bản. Hướng dẫn không tự chuyển trang; hãy đóng hướng dẫn rồi chọn cách tạo đề.'],
      ['[data-guide="reuse"]', 'Dùng lại đề có sẵn',
        'Bạn cũng có thể sao chép đề được phép dùng lại. Bản sao là đề nháp để kiểm tra, chỉnh sửa và chọn lớp giao mới.'],
      ['[data-guide="workflow"]', '2. Cấu hình và giao đề',
        'Sau khi soạn câu hỏi, chọn “Cấu hình”, thiết lập môn, thời lượng, lớp và thời gian làm bài. Kiểm tra nội dung rồi lưu nháp hoặc chọn “Đã đăng” để giao đề.'],
    ],
    compose: [
      ['#examTitle', '1. Đặt tên đề thi',
        'Nhập tên dễ nhận biết, ví dụ “Ôn tập giữa kỳ 1 – Toán 8”.'],
      ['#groupsContainer', '2. Soạn câu hỏi và đáp án',
        'Nhập nội dung câu hỏi, các lựa chọn và đánh dấu đáp án đúng. Có thể thêm câu hỏi trong mỗi phần. Với tự luận, giáo viên sẽ chấm tay.'],
      ['[data-guide="add-group"]', '3. Thêm dạng câu hỏi',
        'Chọn dạng câu hỏi rồi bấm “Thêm phần thi”. Một đề có thể kết hợp trắc nghiệm, đúng/sai, trả lời ngắn, tự luận và tìm lỗi sai.'],
      ['#rawTextEditor', '4. Soạn bằng văn bản',
        'Có thể sửa hoặc dán nội dung theo mẫu đang hiển thị. Văn bản và khung soạn trực quan đồng bộ hai chiều; hãy kiểm tra lại câu hỏi và đáp án sau khi dán.'],
      ['[data-guide="configure"]', '5. Chuyển sang cấu hình',
        'Khi đã nhập tên đề và câu hỏi, bấm “Cấu hình” để chọn môn, cách chia điểm và lớp cần giao. Bước này chưa đăng đề cho học sinh.'],
    ],
    confirm: [
      ['#subjectSelect', '1. Thông tin đề thi',
        'Chọn môn và loại bài thi. Bạn có thể chọn thư mục và thêm ghi chú nếu cần.'],
      ['[data-guide="assignment"]', '2. Chọn lớp và trạng thái',
        'Tìm và chọn một hoặc nhiều lớp cần giao. “Lưu nháp” chưa hiển thị cho học sinh; chọn “Đã đăng” khi đã sẵn sàng giao đề.'],
      ['[data-guide="scoring"]', '3. Điểm và thời lượng',
        'Kiểm tra cách chia điểm và chọn thời lượng làm bài phù hợp. Thời lượng khác khung thời gian được phép mở đề.'],
      ['[data-guide="availability"]', '4. Thời gian mở đề',
        'Chọn không giới hạn, khoảng ngày mở/đóng đề hoặc khung giờ học của lớp. Kiểm tra thêm số lần được làm bài ở bên dưới.'],
      ['[data-guide="save"]', '5. Kiểm tra và hoàn tất',
        'Xem lại nội dung trước khi xác nhận lưu. Để giao đề, cần chọn lớp và trạng thái “Đã đăng”, rồi bấm nút lưu. Đóng hướng dẫn để thao tác; hướng dẫn không tự lưu hoặc đăng đề.'],
    ],
  };
  const steps = (guides[openButton.dataset.guidePage] || [])
    .map(([selector, title, text]) => ({ target: document.querySelector(selector), title, text }))
    .filter(step => step.target);
  if (!steps.length) return;

  const storageKey = `teacher-exam-guide:v1:${openButton.dataset.userId}:${openButton.dataset.guidePage}`;
  const title = document.getElementById('examGuideTitle');
  const text = document.getElementById('examGuideText');
  const progress = document.getElementById('examGuideProgress');
  const previous = document.getElementById('examGuidePrevious');
  const next = document.getElementById('examGuideNext');
  const warning = document.getElementById('examGuideStorageWarning');
  let index = 0;
  let highlighted = null;
  let returnFocus = null;

  function position() {
    if (!dialog.open) return;
    const rect = steps[index].target.getBoundingClientRect();
    const width = dialog.offsetWidth;
    const height = dialog.offsetHeight;
    const left = Math.max(12, Math.min(rect.left, window.innerWidth - width - 12));
    let top = rect.bottom + 12;
    if (top + height > window.innerHeight - 12) top = rect.top - height - 12;
    top = Math.max(12, Math.min(top, window.innerHeight - height - 12));
    dialog.style.left = `${left}px`;
    dialog.style.top = `${top}px`;
  }

  function showStep() {
    if (highlighted) highlighted.classList.remove('exam-guide-target');
    const step = steps[index];
    highlighted = step.target;
    highlighted.classList.add('exam-guide-target');
    highlighted.scrollIntoView({ block: 'center', behavior: 'instant' });
    title.textContent = step.title;
    text.textContent = step.text;
    progress.textContent = `Bước ${index + 1}/${steps.length}`;
    previous.disabled = index === 0;
    next.textContent = index === steps.length - 1 ? 'Đã hiểu' : 'Tiếp';
    position();
    title.focus({ preventScroll: true });
  }

  function start() {
    if (dialog.open) return;
    returnFocus = document.activeElement;
    index = 0;
    dialog.showModal();
    showStep();
    try {
      localStorage.setItem(storageKey, 'seen');
    } catch (error) {
      console.warn('Không thể lưu trạng thái hướng dẫn tạo đề.', error);
      warning.hidden = false;
      position();
    }
  }

  openButton.addEventListener('click', start);
  previous.addEventListener('click', () => {
    if (index > 0) {
      index -= 1;
      showStep();
    }
  });
  next.addEventListener('click', () => {
    if (index === steps.length - 1) {
      dialog.close();
    } else {
      index += 1;
      showStep();
    }
  });
  document.getElementById('examGuideClose').addEventListener('click', () => dialog.close());
  document.getElementById('examGuideSkip').addEventListener('click', () => dialog.close());
  dialog.addEventListener('close', () => {
    if (highlighted) highlighted.classList.remove('exam-guide-target');
    if (returnFocus instanceof HTMLElement) returnFocus.focus({ preventScroll: true });
  });
  window.addEventListener('resize', position);
  window.addEventListener('scroll', position, { passive: true });

  let firstVisit = true;
  try {
    firstVisit = localStorage.getItem(storageKey) !== 'seen';
  } catch (error) {
    console.warn('Không thể đọc trạng thái hướng dẫn tạo đề.', error);
    warning.hidden = false;
  }
  if (firstVisit) start();
})();

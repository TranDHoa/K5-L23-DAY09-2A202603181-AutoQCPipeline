# Báo cáo Day 09 — Trần Đức Hòa, 2A202603181

## 1. Kết luận trước
Pipeline trả về kết luận **Hold** (mã thoát `10`). Từ tổng số **224** ảnh đầu vào trong lô `raw`, cổng kiểm soát cửa vào (intake) đã loại **22** ảnh lỗi/trùng/rò rỉ tập test, còn lại **202** ảnh đi qua bước tự động sửa lỗi và duyệt mẫu (`80/202` ảnh được người duyệt). Mặc dù toàn bộ lỗi nghiêm trọng đã được xử lý sạch (`0 ERROR`), tỉ lệ ảnh còn mang cảnh báo chưa được duyệt là **18.81% (`38/202` ảnh)**, vượt ngưỡng cho phép `10.00%` nên pipeline tạm giữ lô dữ liệu ở trạng thái **Hold** để chờ bổ sung ngân sách duyệt trước khi huấn luyện.

## 2. Lỗi và phân việc
Tổng hợp toàn bộ các mã lỗi phát hiện trước khi sửa (`02_error_list_v1.txt` trên 202 ảnh qua intake và 22 ảnh bị loại ở bước 1):

| Mã lỗi | Số ảnh/dòng | Ai sửa (máy/người) | Vì sao |
|---|---:|---|---|
| `DUP_IMAGE_EXACT` | 8 ảnh | Máy (`remove_image`) | Trùng lặp từng byte (MD5), máy tự xóa bản sao an toàn để tránh thiên lệch dữ liệu. |
| `LEAK_TEST` | 5 ảnh | Máy (`remove_image`) | Trùng với kho ảnh `test`/`gold_val`, bắt buộc loại bỏ để chống rò rỉ dữ liệu đánh giá. |
| `DUP_IMAGE_NEAR` | 4 ảnh | Máy (`remove_image`) | Trùng gần đúng (biến đổi kích thước/độ sáng, `phash_dist <= 12`), máy tự loại bản trùng. |
| `BAD_SIZE` | 3 ảnh | Máy (`remove_image`) | Cạnh ngắn `< 250px`, không đạt chuẩn phân giải đầu vào nên máy loại bỏ. |
| `CORRUPT_IMAGE` | 2 ảnh | Máy (`remove_image`) | File ảnh hỏng/cắt cụt (`UnidentifiedImageError`/`OSError`), máy loại bỏ tự động. |
| `BOX_OUT_OF_IMAGE` | 8 dòng | Máy (`clip_box`) | Tọa độ box tràn nhẹ ra ngoài `[0, 1]`, máy cắt chuẩn về biên ảnh an toàn. |
| `DUP_BOX` | 7 dòng | Máy (`drop_line`) | Trùng lặp box cùng lớp (`IoU > 0.9`), máy xóa dòng dư thừa mà không mất thông tin. |
| `BAD_CLASS_ID` | 6 dòng | Máy (`drop_line`) | ID lớp nằm ngoài `0..3` (`-1, 4, 7, 93`), máy xóa dòng rác định danh. |
| `BOX_ZERO` | 4 dòng | Máy (`drop_line`) | Chiều rộng hoặc cao `<= 0`, box vô nghĩa nên máy xóa dòng. |
| `BAD_FORMAT` | 3 dòng | Máy (`drop_line`) | Dòng thiếu cột hoặc chứa `nan`/`inf`, máy xóa dòng lỗi cú pháp. |
| `BAD_CLASS_NAME` | 2 dòng | Máy (`rename_classes`) | Tên lớp trong `data.yaml` viết hoa sai (`Person`, `Bus`), máy chuẩn hóa lại theo config. |
| `MISSING_LABEL_FILE` | 6 ảnh | Người (`needs_label`) | Máy không được phép tự bịa nhãn; đẩy lên đầu hàng đợi để người gán mới. |
| `POSSIBLE_MISSING` | 53 dòng | Người (hàng đợi) | Nghi ngờ thiếu box so với `yolo26l`, cần mắt người xác nhận tránh gán nhầm nền/vật khuất. |
| `POSSIBLE_FALSE_POS` | 29 dòng | Người (hàng đợi) | Box nhãn không khớp dự đoán của model, cần người kiểm tra xem có phải nhiễu hay vật thật bị model sót. |
| `POSSIBLE_LOOSE_BOX` | 28 dòng | Người (hàng đợi) | Box cùng lớp nhưng `IoU < 0.5`, cần người tinh chỉnh lại độ khít khung. |
| `POSSIBLE_WRONG_CLASS` | 18 dòng | Người (hàng đợi) | Lệch lớp giữa nhãn và model (`IoU >= 0.5`), cần người phân định các lớp dễ nhầm (`car`/`truck`/`bus`). |
| `EMPTY_LABEL` | 12 ảnh | Người (hàng đợi) | File nhãn rỗng (0 dòng), cần người phân biệt ảnh nền thật sự hay bị xóa sót nhãn. |
| `BOX_TINY` | 6 dòng | Người (hàng đợi) | Cạnh ngắn `< 12px`, cần người quyết định giữ hay bỏ theo guideline vật thể nhỏ. |
| `CLASS_RARE` | 4 dòng | Người (cảnh báo) | Cảnh báo cấp dataset do các ID lớp rác (`-1, 4, 7, 93`) xuất hiện ít trước khi autofix xóa. |
| `BOX_HUGE` | 3 dòng | Người (hàng đợi) | Box chiếm `> 95%` diện tích ảnh, cần người kiểm tra xem có bị khoanh nhầm toàn khung hình không. |

**Cơ chế xếp hạng hàng đợi (`05_review_queue.csv`) và hiệu quả ngân sách 80 ảnh:**
Hàng đợi ưu tiên tính điểm rủi ro cho từng ảnh dựa trên trọng số trong `configs/pipeline.yaml`: ảnh thiếu file nhãn (`NEEDS_LABEL`: `10` điểm) được đẩy lên đầu hàng đợi để giải quyết triệt để lỗi bắt buộc (`ERROR`), tiếp theo là các ảnh mang nhiều cảnh báo ngữ nghĩa nghiêm trọng như `POSSIBLE_WRONG_CLASS` (`3`), `POSSIBLE_MISSING` (`2`), `POSSIBLE_FALSE_POS` (`2`), `POSSIBLE_LOOSE_BOX` (`1.5`). Với ngân sách **80 ảnh**, người duyệt đã xử lý xong toàn bộ **6/6** ảnh thiếu file nhãn và giải quyết được **71/128** cảnh báo ngữ nghĩa từ `second_opinion` (giảm tổng cảnh báo của `second_opinion` từ 128 dòng xuống còn 57 dòng ở `07_error_list_v3.txt`).

## 3. Calibration (2 ngưỡng)

| Tham số | Khởi đầu | Đã chọn | Precision / Recall (trước → sau) | Lý do (đánh đổi) |
|---|---:|---:|---|---|
| `duplicates.phash_dist` | 2 | 12 | `DUP_IMAGE_NEAR`: 1.00/0.50 → 1.00/0.67 | Nâng từ 2 lên 12 giúp tăng Recall bắt ảnh gần trùng từ 0.50 lên 0.67 mà vẫn giữ tuyệt đối Precision = 1.00, tránh rủi ro autofix xóa nhầm ảnh sạch. Không chọn 16–20 vì dễ gây nhận nhầm trên tập raw lớn. |
| `second_opinion.conf` | 0.25 | 0.6 | `WRONG_CLASS`: 0.56/0.83 → 0.62/0.83<br>`MISSING`: 0.50/1.00 → 0.57/1.00 | Giữ nguyên Recall tối đa (1.00 cho MISSING, 0.83 cho WRONG_CLASS) nhưng tăng Precision, cắt giảm báo động giả để tập trung ngân sách 80 ảnh duyệt vào các ca rủi ro cao nhất. |

**Chỗ calibration có thể đánh lừa:**
Tập `calib` chỉ gồm 39 ảnh nên các bước nhảy Precision/Recall rất thô; trên bảng sweep, `phash_dist = 16` đạt F1 cao nhất (`0.91` với Precision = `1.00`), nhưng đây là ảo giác do ít mẫu — khi tăng lên `20`, `DUP_IMAGE_EXACT` bị tụt Recall từ `1.00` xuống `0.33` do ảnh gốc bị ghép nhầm vào nhóm gần trùng của ảnh khác đứng trước. Tương tự, `POSSIBLE_LOOSE_BOX` và `POSSIBLE_FALSE_POS` có Precision thấp (`0.20–0.31`) do nhãn người chuẩn trên `calib` vẫn có sai lệch tự nhiên về độ khít khung so với `yolo26l`. Kiểm tra thực tế trên `01_intake.txt` của lô `raw` ở ngưỡng `12` cho thấy cả 4 ảnh bị loại do `DUP_IMAGE_NEAR` (`img_0076` trùng `img_0042`, `img_0143` trùng `img_0037`, `img_0186` trùng `img_0061` với `phash=10`, `img_0223` trùng `img_0077` với `phash=6`) đều là ảnh biến đổi kích thước/sáng hợp lệ, không có ảnh nào bị loại nhầm.

## 4. Cửa chặn và điều pipeline KHÔNG bắt được
**(a) Chứng minh gate chặn đúng:**
Khi chạy thử nghiệm với ngân sách người duyệt bằng 0 (`python -m pipeline.run --budget 0 --reports work/rep_nb --export-dir work/exp_nb`), 6 ảnh bị lỗi `MISSING_LABEL_FILE` không được người xử lý nên vẫn tồn tại lỗi mức `ERROR`. Cổng kiểm soát trả về kết luận **Rework** với mã thoát `20` và **không xuất** thư mục dataset đầu ra (`work/exp_nb`), ngăn chặn thành công dữ liệu thiếu nhãn đi vào huấn luyện.

**(b) Điểm mù của pipeline (các lỗi quan sát thực tế ở Bước 1 nhưng pipeline bỏ sót trong `02_error_list_v1.txt`):**
1. **Gán nhầm vật thể tĩnh thành người (`img_0005`):** Ở rìa trái của bức ảnh, một cột biển báo/trụ đèn đường bị khoanh khung và gán nhãn `person`, nhưng `img_0005` không hề xuất hiện trong `02_error_list_v1.txt` vì `yolo26l` không đủ tự tin để bác bỏ hoặc bị nhiễu bối cảnh đô thị.
2. **Gán nhầm thiết bị/động cơ thành người (`img_0002`):** Cụm động cơ ở phía đuôi thuyền bên phải ảnh bị gán nhầm nhãn `person`, nhưng pipeline hoàn toàn bỏ sót lỗi này trong danh sách cảnh báo v1.
3. **Bỏ sót đối tượng chính rõ nét (`img_0001`):** Người mặc quân phục đứng rõ ràng ở nửa bên phải khung hình không có box nhãn `person` (pipeline chỉ bắt được một box khác ở `img_0001` với `conf=0.95` nhưng bỏ qua đối tượng này do trùng lặp vùng quan tâm/che khuất một phần).

## 5. Train: raw vs clean (tùy chọn, chấm riêng)
Chưa chạy phần huấn luyện trên Colab do tập trung hoàn thiện phần lõi pipeline kiểm soát chất lượng dữ liệu cục bộ theo tùy chọn `check-core`.

## 6. Quyết định và ghi chú AI
**(a) Quyết định cuối và lộ trình chuyển sang Release:**
Chấp nhận trạng thái **Hold** cho lô dữ liệu hiện tại (không đưa thẳng vào train tự động khi chưa duyệt nốt). Để chuyển trạng thái từ **Hold** sang **Release**, cần cấp thêm ngân sách duyệt thủ công cho ít nhất **18 ảnh** đứng đầu phần còn lại của hàng đợi (giảm số ảnh mang cảnh báo chưa duyệt từ `38/202` = `18.81%` xuống dưới `20/202` = `9.90% < 10.00%`), ưu tiên xử lý dứt điểm 3 ca `POSSIBLE_WRONG_CLASS` (`img_0078`, `img_0083`, `img_0220`) và 13 ca `POSSIBLE_MISSING` còn lại trong `07_error_list_v3.txt`.

**(b) Ghi chú sử dụng AI:**
- **Prompt chính:** Cung cấp docstring, bảng quy ước mã lỗi và file unit test (`test_*.py`) của từng module (`label_format`, `gate`, `autofix`, `second_opinion`) để sinh mã xử lý các trường hợp biên như giữ nguyên số dòng gốc khi có dòng trống và ưu tiên xóa dòng trước khi cắt box.
- **Cách kiểm tra code AI:** Chạy đối chiếu từng file bằng `python -m pytest tests/test_<module>.py -q` (đạt 79/79 test pass), sau đó chạy thử trên lô `raw` thật và kiểm tra chéo báo cáo `01_intake.txt`, `03_fixes.csv` cùng hình ảnh trực quan bằng `viz_labels.py`.
- **Một lần AI sai / cần chỉnh:** Ở lần chạy thử đầu tiên sau khi sinh code, cấu hình `second_opinion.conf` vẫn giữ nguyên giá trị khởi đầu `0.25` khiến hàng đợi phình to (94 cảnh báo `POSSIBLE_MISSING`), buộc phải rà soát lại `configs/pipeline.yaml` và hiệu chỉnh lên `0.6` dựa trên bảng sweep calibration.
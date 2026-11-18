"""CHECK 2 — Dòng nhãn YOLO: sai định dạng, ID lớp lạ, box tràn ảnh, box rỗng, box lặp.   (Script 2 trong slide)   ★★

Test:  pytest tests/test_label_format.py -q

Mỗi dòng nhãn: `id cx cy w h` (5 số, toạ độ 0–1). Trả về list[Issue]; `Issue.line` = số dòng (đếm từ 1).

| code             | severity | khi nào                                                                  |
|------------------|----------|--------------------------------------------------------------------------|
| BAD_FORMAT       | ERROR    | không đúng 5 cột số (dùng `parse_yolo_line`, bắt `ValueError`)           |
| BAD_CLASS_ID     | ERROR    | id lớp ngoài 0..len(ds.classes)-1                                        |
| BOX_ZERO         | ERROR    | w <= 0 hoặc h <= 0                                                       |
| BOX_OUT_OF_IMAGE | ERROR    | mép box vượt [0,1] quá `cfg["label_format"]["overflow_tol"]`; extra={"overflow": mức tràn} |
| DUP_BOX          | ERROR    | cùng lớp với một dòng TRƯỚC ĐÓ và IoU > `dup_box_iou`; báo ở dòng SAU    |
| BOX_TINY         | WARN     | cạnh ngắn của box (px) < `min_box_px`  (cần `ds.image_size(stem)`)       |
| BOX_HUGE         | WARN     | w*h > `max_box_frac`                                                     |

Gợi ý
- Mép trái = x - w/2, mép phải = x + w/2 (xem câu hỏi "dòng YOLO nào lỗi?" trong slide).
- Một dòng hỏng (BAD_FORMAT, BAD_CLASS_ID, BOX_ZERO) thì `continue`, đừng kiểm tiếp hình học của dòng đó.
- Dòng thiếu cột làm script của slide dừng giữa chừng: đây là lý do phải `try/except`.
- `iou_xywh(a, b)` có sẵn trong common.py.
- Ngưỡng nằm trong `cfg["label_format"]` — đừng viết cứng số vào code.
"""
from ..common import ERROR, WARN, Issue, iou_xywh, parse_yolo_line


def run(ds, cfg):
    issues = []
    lf_cfg = cfg["label_format"]
    overflow_tol = lf_cfg["overflow_tol"]
    dup_box_iou = lf_cfg["dup_box_iou"]
    min_box_px = lf_cfg["min_box_px"]
    max_box_frac = lf_cfg["max_box_frac"]
    num_classes = len(ds.classes)

    stems = sorted({p.stem for p in ds.image_files()})
    for stem in stems:
        lines = ds.read_label_lines(stem)
        if not lines:
            continue

        seen_boxes = []  # lưu (cid, (cx, cy, w, h)) của các dòng hợp lệ trước đó
        img_size = ds.image_size(stem)

        for line_no, text in lines:
            # 1. Kiểm tra định dạng 5 cột số
            try:
                cid, cx, cy, w, h = parse_yolo_line(text)
            except ValueError as e:
                issues.append(
                    Issue("label_format", ERROR, "BAD_FORMAT", stem, f"lỗi định dạng: {e}", line=line_no)
                )
                continue

            # 2. Kiểm tra ID lớp
            if not (0 <= cid < num_classes):
                issues.append(
                    Issue("label_format", ERROR, "BAD_CLASS_ID", stem, f"id lớp không hợp lệ: {cid}", line=line_no)
                )
                continue

            # 3. Kiểm tra kích thước rỗng
            if w <= 0 or h <= 0:
                issues.append(
                    Issue("label_format", ERROR, "BOX_ZERO", stem, f"kích thước box <= 0 ({w}x{h})", line=line_no)
                )
                continue

            # 4. Kiểm tra box tràn ra ngoài ảnh [0, 1]
            x1, y1 = cx - w / 2.0, cy - h / 2.0
            x2, y2 = cx + w / 2.0, cy + h / 2.0
            overflow = max(0.0, -x1, -y1, x2 - 1.0, y2 - 1.0)
            if overflow > overflow_tol:
                issues.append(
                    Issue(
                        "label_format",
                        ERROR,
                        "BOX_OUT_OF_IMAGE",
                        stem,
                        f"box tràn khỏi ảnh mức {overflow:.4f}",
                        line=line_no,
                        extra={"overflow": round(overflow, 6)},
                    )
                )

            # 5. Kiểm tra box lặp (cùng class với dòng trước đó và IoU > ngưỡng)
            box_xywh = (cx, cy, w, h)
            is_dup = False
            for prev_cid, prev_box in seen_boxes:
                if prev_cid == cid and iou_xywh(prev_box, box_xywh) > dup_box_iou:
                    is_dup = True
                    break
            if is_dup:
                issues.append(
                    Issue("label_format", ERROR, "DUP_BOX", stem, "box trùng lặp với dòng trước đó", line=line_no)
                )
            seen_boxes.append((cid, box_xywh))

            # 6. Cảnh báo box quá nhỏ (tính theo pixel)
            if img_size is not None:
                img_w, img_h = img_size
                short_side_px = min(w * img_w, h * img_h)
                if short_side_px < min_box_px:
                    issues.append(
                        Issue(
                            "label_format",
                            WARN,
                            "BOX_TINY",
                            stem,
                            f"cạnh ngắn box quá nhỏ ({short_side_px:.1f}px < {min_box_px}px)",
                            line=line_no,
                        )
                    )

            # 7. Cảnh báo box quá lớn (diện tích chiếm tỷ lệ lớn)
            if w * h > max_box_frac:
                issues.append(
                    Issue(
                        "label_format",
                        WARN,
                        "BOX_HUGE",
                        stem,
                        f"diện tích box quá lớn ({w * h:.2f} > {max_box_frac})",
                        line=line_no,
                    )
                )

    return issues
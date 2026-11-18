"""BƯỚC 2/4 — Sửa tự động những lỗi bắt buộc mà máy sửa được AN TOÀN.   ★★

Test:  pytest tests/test_autofix.py -q

`fix(ds, issues, cfg) -> list[dict]`: duyệt `issues` (chỉ lỗi severity ERROR), sửa thẳng vào thư mục `ds`,
và trả về danh sách thay đổi; mỗi phần tử có khoá: image, line, action, before, after
(đây chính là file `03_fixes.csv` — bằng chứng pipeline đã làm gì, người có thể kiểm lại).

| code lỗi                                       | cách sửa                                    | action           |
|------------------------------------------------|---------------------------------------------|------------------|
| BAD_FORMAT, BAD_CLASS_ID, BOX_ZERO, DUP_BOX    | xoá dòng đó khỏi file nhãn                  | "drop_line"      |
| BOX_OUT_OF_IMAGE                               | cắt box về trong [0,1] (giữ nguyên lớp)     | "clip_box"       |
| MISSING_LABEL_FILE                             | KHÔNG sửa file (máy không thể bịa nhãn): ghi 1 dòng fix, before="(không có file)", after="chuyển người gán" | "needs_label" |
| BAD_CLASS_NAME                                 | ghi lại `names` trong data.yaml đúng `cfg["classes"]` | "rename_classes" |
| DUP_IMAGE_*, LEAK_TEST, CORRUPT_IMAGE, BAD_SIZE| xoá ảnh + nhãn khỏi `ds`                    | "remove_image"   |

Bẫy cần nghĩ tới (có test cho từng cái)
- Một file có NHIỀU dòng lỗi: số dòng trong `issues` là số dòng GỐC. Nếu xoá từng dòng một thì số dòng lệch.
  Gom theo file, rồi ghi lại MỘT lần.
- Sau khi cắt, box có thể không còn diện tích (nằm hẳn ngoài ảnh): lúc đó xoá dòng thay vì ghi box rỗng.
- Một dòng có 2 lỗi (vd. BOX_OUT_OF_IMAGE + DUP_BOX): xoá dòng thắng, chỉ ghi 1 fix `drop_line`, không ghi thêm `clip_box`. Dòng trống ở giữa file vẫn đếm vào số dòng gốc.
- Ảnh vừa bị xoá (DUP_IMAGE_*...) mà còn issue dòng của chính nó: bỏ qua êm, không được báo lỗi/chết.
- Không động tới lỗi WARN (cảnh báo là việc của người). Không sửa file ở `data/raw/` — chỉ sửa `ds`.
- Chạy lần 2 trên dữ liệu đã sửa phải không làm gì thêm (idempotent) — NGOẠI LỆ duy nhất: `needs_label` được ghi lại mỗi lần còn lỗi `MISSING_LABEL_FILE` (vì ảnh vẫn chưa có nhãn).

- `needs_label` KHÔNG tạo file nhãn rỗng (rỗng = "ảnh nền", khác với "chưa gán"). `review_queue` sẽ đẩy ảnh này lên đầu hàng đợi cho người.

Gợi ý: `yaml.safe_load / safe_dump`.
"""
from collections import defaultdict

import yaml

from ..common import ERROR, parse_yolo_line

DROP_CODES = {"BAD_FORMAT", "BAD_CLASS_ID", "BOX_ZERO", "DUP_BOX"}
REMOVE_IMG_PREFIXES = ("DUP_IMAGE_",)
REMOVE_IMG_CODES = {"LEAK_TEST", "CORRUPT_IMAGE", "BAD_SIZE"}


def _is_remove_image_code(code: str) -> bool:
    return code in REMOVE_IMG_CODES or code.startswith(REMOVE_IMG_PREFIXES)


def fix(ds, issues, cfg):
    fixes = []
    err_issues = [i for i in issues if i.severity == ERROR]

    # 1. Xác định các ảnh cần xoá hoàn toàn khỏi ds
    removed_stems = set()
    remove_reasons = {}
    for iss in err_issues:
        if _is_remove_image_code(iss.code):
            removed_stems.add(iss.image)
            remove_reasons.setdefault(iss.image, iss.code)

    for stem in sorted(removed_stems):
        img_p = ds.image_path(stem)
        lbl_p = ds.label_path(stem)
        existed = False
        if img_p and img_p.exists():
            img_p.unlink()
            existed = True
        if lbl_p.exists():
            lbl_p.unlink()
            existed = True
        if existed:
            fixes.append(
                {
                    "image": stem,
                    "line": "",
                    "action": "remove_image",
                    "before": remove_reasons[stem],
                    "after": "(đã xoá ảnh và nhãn)",
                }
            )

    # 2. Sửa data.yaml nếu có lỗi BAD_CLASS_NAME (chỉ ghi 1 lần)
    has_bad_class_name = any(iss.code == "BAD_CLASS_NAME" for iss in err_issues)
    if has_bad_class_name and ds.yaml_path.exists():
        data = yaml.safe_load(ds.yaml_path.read_text(encoding="utf-8")) or {}
        before_names = str(data.get("names", ""))
        target_classes = list(cfg["classes"])
        if data.get("names") != target_classes:
            data["names"] = target_classes
            ds.yaml_path.write_text(
                yaml.safe_dump(data, sort_keys=False, allow_unicode=True),
                encoding="utf-8",
            )
            fixes.append(
                {
                    "image": "data.yaml",
                    "line": "",
                    "action": "rename_classes",
                    "before": before_names,
                    "after": str(target_classes),
                }
            )

    # 3. Ghi nhận MISSING_LABEL_FILE (không tạo file rỗng, chuyển người gán)
    missing_stems = sorted(
        {
            iss.image
            for iss in err_issues
            if iss.code == "MISSING_LABEL_FILE" and iss.image not in removed_stems
        }
    )
    for stem in missing_stems:
        fixes.append(
            {
                "image": stem,
                "line": "",
                "action": "needs_label",
                "before": "(không có file)",
                "after": "chuyển người gán",
            }
        )

    # 4. Gom lỗi theo từng file nhãn (bỏ qua ảnh đã bị xoá)
    line_actions = defaultdict(dict)  # stem -> {line_no: "drop" | "clip"}
    for iss in err_issues:
        if iss.image in removed_stems or iss.line is None:
            continue
        if iss.code in DROP_CODES:
            # Xoá dòng luôn thắng cắt box
            line_actions[iss.image][iss.line] = "drop"
        elif iss.code == "BOX_OUT_OF_IMAGE":
            if line_actions[iss.image].get(iss.line) != "drop":
                line_actions[iss.image][iss.line] = "clip"

    # 5. Xử lý và ghi lại từng file nhãn MỘT lần duy nhất
    for stem in sorted(line_actions):
        lbl_p = ds.label_path(stem)
        if not lbl_p.exists():
            continue

        raw_lines = lbl_p.read_text(encoding="utf-8", errors="replace").splitlines()
        actions_map = line_actions[stem]
        new_lines = []
        changed = False

        for line_no, text in enumerate(raw_lines, 1):
            act = actions_map.get(line_no)
            if act is None:
                new_lines.append(text)
                continue

            if act == "drop":
                changed = True
                fixes.append(
                    {
                        "image": stem,
                        "line": line_no,
                        "action": "drop_line",
                        "before": text.strip(),
                        "after": "(đã xoá)",
                    }
                )
            elif act == "clip":
                try:
                    cid, cx, cy, w, h = parse_yolo_line(text)
                except ValueError:
                    changed = True
                    fixes.append(
                        {
                            "image": stem,
                            "line": line_no,
                            "action": "drop_line",
                            "before": text.strip(),
                            "after": "(đã xoá)",
                        }
                    )
                    continue

                x1 = max(0.0, min(1.0, cx - w / 2.0))
                y1 = max(0.0, min(1.0, cy - h / 2.0))
                x2 = max(0.0, min(1.0, cx + w / 2.0))
                y2 = max(0.0, min(1.0, cy + h / 2.0))
                nw, nh = x2 - x1, y2 - y1

                if nw <= 1e-9 or nh <= 1e-9:
                    changed = True
                    fixes.append(
                        {
                            "image": stem,
                            "line": line_no,
                            "action": "drop_line",
                            "before": text.strip(),
                            "after": "(đã xoá)",
                        }
                    )
                else:
                    ncx = (x1 + x2) / 2.0
                    ncy = (y1 + y2) / 2.0
                    clipped_str = f"{cid} {ncx:.6f} {ncy:.6f} {nw:.6f} {nh:.6f}"
                    if clipped_str != text.strip():
                        changed = True
                        fixes.append(
                            {
                                "image": stem,
                                "line": line_no,
                                "action": "clip_box",
                                "before": text.strip(),
                                "after": clipped_str,
                            }
                        )
                    new_lines.append(clipped_str)

        if changed:
            content = "\n".join(new_lines) + ("\n" if new_lines else "")
            lbl_p.write_text(content, encoding="utf-8")

    return fixes
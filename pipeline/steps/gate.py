"""BƯỚC 4 — Cửa chặn: quyết định Release / Hold / Rework.   ★

Test:  pytest tests/test_gate.py -q

Cây quyết định Day 07 (slide Day 09: "Lỗi bắt buộc chặn pipeline; lỗi cảnh báo chuyển người xem"):

  còn ≥ 1 lỗi bắt buộc (severity ERROR)                          -> "Rework"
  không còn lỗi bắt buộc, nhưng tỉ lệ ẢNH còn cảnh báo
      >= cfg["gate"]["warn_ratio_hold"]                          -> "Hold"
  còn lại                                                        -> "Release"

Tỉ lệ cảnh báo = (số ẢNH khác nhau có ≥ 1 cảnh báo) / (tổng số ảnh).  Chú ý:
- chỉ đếm issue có `image` nằm trong `image_stems` (bỏ "<dataset>", "data.yaml");
- bỏ qua ảnh nằm trong `reviewed` (người đã xem, cảnh báo của ảnh đó coi như đã xử lý) — nhưng LỖI BẮT BUỘC thì không bao giờ được bỏ qua;
- mẫu số là số ảnh, không phải số issue.

Trả về dict: decision, n_errors, n_warn_images, n_images, warn_ratio (làm tròn 4 chữ số), reasons (list[str], giải thích bằng tiếng Việt, có số liệu).
"""
from ..common import ERROR, WARN


def decide(issues, image_stems, cfg, reviewed=frozenset()):
    stem_set = set(image_stems)
    reviewed_set = set(reviewed)
    n_images = len(stem_set)
    hold_thresh = cfg["gate"]["warn_ratio_hold"]

    # 1. Đếm toàn bộ lỗi bắt buộc (ERROR) - không bao giờ bỏ qua dù nằm trong reviewed
    n_errors = sum(1 for i in issues if i.severity == ERROR)

    # 2. Tập hợp các ảnh hợp lệ có cảnh báo (WARN) và chưa được người duyệt
    warn_images = {
        i.image
        for i in issues
        if i.severity == WARN and i.image in stem_set and i.image not in reviewed_set
    }
    n_warn_images = len(warn_images)

    # 3. Tính tỉ lệ cảnh báo (tránh chia cho 0)
    raw_ratio = (n_warn_images / n_images) if n_images > 0 else 0.0
    warn_ratio = round(raw_ratio, 4)

    # 4. Cây quyết định
    reasons = []
    if n_errors >= 1:
        decision = "Rework"
        reasons.append(f"Còn {n_errors} lỗi bắt buộc (ERROR) chưa được khắc phục.")
    elif warn_ratio >= hold_thresh:
        decision = "Hold"
        reasons.append(
            f"Tỉ lệ ảnh còn cảnh báo là {warn_ratio:.2%} ({n_warn_images}/{n_images} ảnh), "
            f"vượt hoặc chạm ngưỡng giữ lại {hold_thresh:.2%}."
        )
    else:
        decision = "Release"
        reasons.append(
            f"Không còn lỗi bắt buộc (0 ERROR) và tỉ lệ ảnh cảnh báo ở mức an toàn "
            f"{warn_ratio:.2%} ({n_warn_images}/{n_images} ảnh < {hold_thresh:.2%})."
        )

    return {
        "decision": decision,
        "n_errors": n_errors,
        "n_warn_images": n_warn_images,
        "n_images": n_images,
        "warn_ratio": warn_ratio,
        "reasons": reasons,
    }

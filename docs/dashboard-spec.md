# Yêu cầu dashboard

Contract có thể kiểm tra bằng máy nằm tại `config/dashboard.yaml`. Hướng dẫn dựng và kiểm tra runtime nằm tại [DASHBOARD_SETUP.md](DASHBOARD_SETUP.md).

Dashboard chính cần đủ 6 nhóm thông tin:

1. Latency P50/P95/P99.
2. Traffic: request count hoặc QPS.
3. Error rate và breakdown theo loại lỗi.
4. Cost theo thời gian.
5. Tổng token input/output.
6. Quality proxy.

Tiêu chuẩn trình bày:

- Khoảng thời gian mặc định: 1 giờ.
- Tự refresh mỗi 15–30 giây nếu công cụ hỗ trợ.
- Có threshold hoặc SLO line.
- Ghi rõ đơn vị.
- Chỉ giữ 6–8 panel quan trọng ở lớp chính.
- Screenshot phải nhìn được tên panel và khoảng thời gian.

Kiểm tra contract trước khi chụp evidence:

```bash
python scripts/validate_dashboard.py
```

---

## Triển khai của nhóm

### Công cụ

Dashboard tự dựng bằng `scripts/build_dashboard.py`, render ra một file HTML tự chứa
(`submission/evidence/dashboard.html`) — không phụ thuộc Grafana hay tài khoản ngoài,
mở bằng trình duyệt bất kỳ là chụp được evidence.

Lý do không dùng Langfuse dashboard cho phần này: theo [README.md](../README.md),
nguồn chuẩn của 6 panel là `data/logs.jsonl`. Langfuse vẫn là nơi mở trace và prompt
version để điều tra sâu, nhưng số liệu 6 panel phải đến từ log của chính app.

```bash
python scripts/build_dashboard.py           # dựng lại từ log hiện tại
python scripts/build_dashboard.py --open    # dựng xong mở luôn trình duyệt
```

Script đọc trực tiếp `config/dashboard.yaml` để lấy danh sách panel, đơn vị và
threshold — không hard-code giá trị nào. Sửa contract thì dashboard đổi theo.
Percentile dùng chung hàm `app.metrics.percentile` với endpoint `/metrics`, nên số
trên dashboard và số trên API luôn khớp.

### Sáu panel

| # | Panel | Event/field nguồn | Tổng hợp | Đơn vị | Threshold | Dạng hiển thị |
|---|---|---|---|---|---|---|
| 1 | Latency percentiles | `response_sent.latency_ms` | p50, p95, p99 | ms | p95 ≤ 3000 | bar ngang + SLO line |
| 2 | Request traffic | `request_received` | count, rate/phút | requests_per_minute | rate ≥ 1 | cột theo phút |
| 3 | Error rate and breakdown | `request_received`, `request_failed`, `error_type` | error_rate_pct, count_by_value | percent | ≤ 2% | hero number + meter + bảng breakdown |
| 4 | Cost over time | `response_sent.cost_usd` | sum theo phút, total | usd | total ≤ 2.5 | hero number + cột theo phút |
| 5 | Input and output tokens | `response_sent.tokens_in`, `tokens_out` | sum theo từng field | tokens | mỗi field ≤ 50 000 | bar ngang 2 series + legend |
| 6 | Quality proxy | `response_sent.quality_score` | mean | score_0_to_1 | ≥ 0.75 | hero number + meter |

Mỗi panel hiển thị: tên, đơn vị, phép tổng hợp đang dùng, ngưỡng, và trạng thái
**đạt/vi phạm** bằng **icon + nhãn chữ** — không bao giờ chỉ dựa vào màu.

### Cửa sổ thời gian và refresh

- Time range: **60 phút**, tính lùi từ bản ghi log mới nhất (không phải từ thời điểm
  mở file), để dashboard vẫn đọc được log đã sinh từ trước.
- Trục thời gian **liên tục**: phút không có traffic vẫn là một cột giá trị 0, để
  khoảng lặng hiện ra đúng thay vì bị nén mất.
- Auto refresh: **30 giây**, đúng khoảng 15–30s mà contract yêu cầu.
- Header ghi rõ khoảng thời gian thực tế, đường dẫn file log nguồn và thời điểm sinh.

### Khả năng đọc

- Bảng màu dùng slot 1 (xanh) và slot 2 (cam), đã chạy validator: đạt toàn bộ 5 check
  ở cả light và dark mode (CVD ΔE 24.7 light / 26.8 dark, ngưỡng ≥ 8).
- Panel có 2 series (tokens) luôn có legend; panel 1 series không có legend vì tiêu đề
  đã nói rõ đang vẽ gì.
- Mỗi panel có mục **"Bảng dữ liệu"** mở ra xem số gốc — không phụ thuộc vào việc đọc
  được biểu đồ.
- Hover từng cột/bar hiện tooltip giá trị.
- Tự đổi theo light/dark mode của máy người xem.

### Kết quả baseline

Chạy trên `data/logs.jsonl` sau `python scripts/load_test.py` (22 request, cửa sổ 60 phút):

| Panel | Giá trị đo được | Ngưỡng | Trạng thái |
|---|---|---|---|
| Latency | p50 150 ms · p95 1 088 ms · p99 1 117 ms | p95 ≤ 3 000 ms | đạt |
| Traffic | 22 request · 7.33 req/phút | ≥ 1 req/phút | đạt |
| Errors | 0.0% (0/22) | ≤ 2% | đạt |
| Cost | $0.0476 | ≤ $2.5 | đạt |
| Tokens | 707 in · 3 035 out | mỗi field ≤ 50 000 | đạt |
| Quality | 0.88 | ≥ 0.75 | đạt |

P95 cao hơn P50 **7.25 lần** vì request đầu tiên của mỗi lần khởi động server phải
fetch prompt từ Langfuse (~1 giây), các request sau dùng cache 60 giây. Đây chính là
lý do phải nhìn percentile chứ không nhìn trung bình: average latency chỉ **236.9 ms**,
nằm gọn dưới ngưỡng và giấu mất hoàn toàn phần đuôi hơn 1 giây này.

### Kiểm tra runtime

Ảnh baseline chưa đủ — phải chứng minh dashboard phản ứng đúng khi có sự cố:

```bash
python scripts/inject_incident.py --scenario rag_slow
python scripts/load_test.py --concurrency 5
python scripts/build_dashboard.py
```

Panel Latency phải tăng rõ rệt ở P95/P99. Sau đó tắt incident:

```bash
python scripts/inject_incident.py --scenario rag_slow --disable
```

### Evidence

- `submission/evidence/dashboard.html` — dashboard dựng lại được từ log.
- `submission/evidence/dashboard-baseline.png` — ảnh chụp trạng thái bình thường.
- `submission/evidence/dashboard-incident.png` — ảnh chụp khi P95 vi phạm SLO.
- `submission/evidence/validate-dashboard.png` — kết quả `HỢP LỆ: 6/6 panel`.

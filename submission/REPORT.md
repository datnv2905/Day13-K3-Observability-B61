# Báo cáo Day 13 Observability

## 1. Thông tin nhóm

- **Tên nhóm:** B61
- **Repository URL:** https://github.com/datnv2905/Day13-K3-Observability-B61
- **Commit SHA cuối:** `4ab6301fa4c2f7a4c57eff27da33bb7ecfe7f52c` — commit chứa toàn bộ bài
  làm. Commit cuối trên `main` có thể mới hơn đúng một commit (chính là commit ghi dòng
  SHA này và dọn `.omc/`); lấy giá trị nộp bằng `git rev-parse HEAD`.
- **Thành viên và vai trò:**

| Họ tên | MSSV | Tác giả trong Git | Vai trò |
|---|---|---|---|
| Nguyễn Văn Đạt | 2A202601969 | `Datnv <datbn5602@gmail.com>` | Dashboard, SLO & Alert |
| Nguyễn Trọng Toàn | 2A202601493 | `Toanproptit <nguyentrongtoana1byt@gmail.com>` — nhánh `origin/Toan` | Dashboard runtime & evidence ảnh |
| Hoàng Nguyễn Phong | 2A202601077 | `Hoang Phong <hoangphong210703@gmail.com>` | Logging & PII |
| Lê Hồng Đức | 2A202601313 | `duclh <duclh005@example.com>` | Dashboard, SLO & Alert |
| Trần Nguyễn Thế Nhật | 2A202601155 | `Nhat Tran <nhatjames24.2004@gmail.com>` | Tracing & Prompt Version; Incident, Report & Demo |

Tác giả `HungBil <nguyendonghung70@gmail.com>` là người khởi tạo repo lab và release
`config/challenge.json`, không thuộc nhóm.

## 2. Kết quả kỹ thuật

- Điểm `validate_logs.py`: **100/100** (baseline 30/100) — [`evidence/cp1-final-validate-logs.txt`](evidence/cp1-final-validate-logs.txt)
- Tổng số traces: **12** trên Langfuse (vượt yêu cầu 10), mỗi trace 4 observation — [`evidence/cp2-langfuse-traces.txt`](evidence/cp2-langfuse-traces.txt)
- Số PII leak còn lại: **0** (`Potential PII leaks detected: 0` trên 21 log record)
- Link/đường dẫn dashboard: [`evidence/dashboard-baseline.html`](evidence/dashboard-baseline.html) — `validate_dashboard.py` báo `HỢP LỆ: 6/6 panel`

### Checkpoint 0 — baseline

Baseline được đo trên đúng code khởi điểm (commit `611a0d2`, trước commit `phase 1`) bằng một
git worktree riêng, nên con số so sánh là thật chứ không phải ước lượng.

| Hạng mục | Baseline (`611a0d2`) | Sau CP1 (HEAD) |
|---|---|---|
| Basic JSON schema | FAILED — 20/21 record thiếu field bắt buộc | PASSED — 0 record thiếu |
| Correlation ID propagation | FAILED — 0 ID duy nhất | PASSED — 10 ID duy nhất |
| Log enrichment | FAILED — 20 record thiếu context | PASSED — 0 record thiếu |
| PII scrubbing | PASSED | PASSED |
| **Điểm ước lượng** | **30/100** | **100/100** |

- Evidence baseline: [`evidence/cp0-baseline-validate-logs.txt`](evidence/cp0-baseline-validate-logs.txt)
- Evidence health + load test: [`evidence/cp0-health-and-loadtest.txt`](evidence/cp0-health-and-loadtest.txt)
- `/health` trả `{"ok": true, "tracing_enabled": true, ...}` sau khi cấu hình key Langfuse
  region EU ở Checkpoint 2. Evidence CP0 được chụp lại sau khi hoàn tất cấu hình.

Lưu ý trung thực: hạng mục PII đã PASSED ngay ở baseline. Lý do là `app/main.py` gọi
`summarize_text()` tại chỗ log, mà hàm này vốn đã chạy `scrub_text()`. Processor `scrub_event`
bị vô hiệu ở baseline nên **chưa có lớp chặn cuối** — bất kỳ log nào không đi qua
`summarize_text()` sẽ rò PII. Đó là lỗ hổng thật mà CP1 đã bịt (xem mục 3).

## 3. Logging và tracing

- Evidence correlation ID: [`evidence/cp1-correlation-id.txt`](evidence/cp1-correlation-id.txt)
- Evidence PII redaction: [`evidence/cp1-pii-redaction.txt`](evidence/cp1-pii-redaction.txt)
- Evidence regression tests: [`evidence/cp1-tests.txt`](evidence/cp1-tests.txt) — 43 passed
- Evidence trace waterfall: [`evidence/cp2-trace-structure.txt`](evidence/cp2-trace-structure.txt)
- Giải thích một span đáng chú ý: xem mục 3.4

### 3.1 Correlation ID (`app/middleware.py`)

`CorrelationIdMiddleware` xử lý theo thứ tự:

1. `clear_contextvars()` đầu mỗi request — chặn rò context giữa các request dùng chung worker.
2. Lấy `x-request-id` từ header nếu client gửi, ngược lại sinh `req-<8 hex>`. Nhận ID từ client
   để giữ được chuỗi liên kết khi request đi qua nhiều service.
3. `bind_contextvars(correlation_id=...)` để mọi `log.*` sau đó tự mang ID, không phải truyền tay.
4. Trả `x-request-id` và `x-response-time-ms` về response header, giúp người dùng/QA báo lỗi kèm
   đúng ID để tra log.

Bằng chứng: request gửi kèm `x-request-id: req-trace-demo-001` cho ra đúng hai log record
`request_received` + `response_sent` cùng ID đó; 10 request của load test cho 10 ID khác nhau.

### 3.2 Log enrichment (`app/main.py`)

Handler `/chat` bind thêm `user_id_hash`, `session_id`, `feature`, `model`, `env` vào contextvars,
nên mọi log của `service=api` đều có đủ 5 field. `user_id` **không bao giờ** được ghi nguyên văn —
chỉ ghi `hash_user_id()` (SHA-256, 12 ký tự đầu), đủ để nhóm request theo người dùng mà không lưu
định danh. Ví dụ `u01 → 2055254ee30a`.

### 3.3 PII redaction — hai lớp phòng thủ

- **Lớp 1 — tại chỗ gọi:** `summarize_text()` trong `app/pii.py` scrub rồi mới cắt 80 ký tự.
- **Lớp 2 — chặn cuối:** processor `scrub_event` trong `app/logging_config.py` chạy trên mọi
  string trong `payload` và trên `event`, kể cả log không qua `summarize_text()`.

Lớp 2 là phần thật sự được bật ở CP1. Test
`test_scrub_processor_redacts_pii_not_passed_through_summarize` ghi PII thô thẳng vào `payload`
và xác nhận nó vẫn bị che — đây là bằng chứng lớp chặn cuối hoạt động.

Pattern đang bắt: `email`, `phone_vn` (`0xxxxxxxxx`, `+84...`, có `.`/`-`/space), `cccd` (12 số),
`credit_card` (16 số), `passport_vn` (`A1234567`), `address_vn` (từ khoá tiếng Việt có/không dấu).

Kiểm chứng ngược trên `data/logs.jsonl`: không tìm thấy `student@vinuni.edu.vn`,
`demo.user@vinuni.edu.vn`, `0987654321`, `0912345678`, `4111 1111 1111 1111`,
`4111-1111-1111-1111`, hay `user_id` nguyên văn.

Hạn chế đã biết: redaction dựa trên regex nên chỉ bắt được định dạng đã liệt kê; PII dạng tự do
(tên người, địa chỉ viết lạ) vẫn có thể lọt. Việc cắt 80 ký tự cũng có thể cắt ngang token
`[REDACTED_CREDIT_CAR...` — không rò dữ liệu nhưng đọc log hơi khó.

### 3.4 Instrumentation trace theo skill `langfuse`

Đã cài Agent Skill chính thức từ `github.com/langfuse/skills` và làm theo
`references/instrumentation.md`. Trace trước đó **phẳng**: cả request là một
`generation` duy nhất, không nhìn thấy bước RAG hay bước lấy prompt.

Cấu trúc trace sau khi sửa:

```
chat-response                 [span]        ← root, có input/output đã scrub
├── retrieve-context          [span]        ← bước RAG
├── resolve-prompt            [span]        ← lấy prompt từ Langfuse
└── llm-generate              [generation]  ← model, token, cost
```

Các thay đổi và lý do:

| Thay đổi | Trước | Lý do |
|---|---|---|
| Tách span cho từng bước | 1 span phẳng | Không tách thì không biết bước nào chậm |
| Đặt tên theo động từ | tên hàm `run` | `chat-response` lọc/tìm được trong UI |
| Set input/output tường minh | không có gì | `capture_input=False` khiến trace rỗng, UI không đọc được |
| `mask=` ở tầng client | chỉ scrub thủ công | Lớp chặn cuối cho trace, song song `scrub_event` của log |
| `correlation_id` vào trace metadata | không có | **Nối Logs ↔ Traces** — xương sống của luồng Metrics → Traces → Logs |
| `quality_proxy` thành score | chỉ là metadata | Lọc và vẽ biểu đồ theo chất lượng trong UI |
| `level=ERROR` + `status_message` | lỗi im lặng | Nhìn ra span hỏng và nguyên nhân |
| `environment` từ `APP_ENV` | không set | Tách dev/prod |
| `flush()` lúc shutdown | không có | Span còn trong buffer sẽ mất khi thoát |

**Span đáng chú ý — `retrieve-context`.** Đây là thứ biến trace thành công cụ chẩn
đoán thật. Bật sự cố `rag_slow`:

```
chat-response      3573ms
├── retrieve-context   2501ms   ← thủ phạm
├── resolve-prompt      915ms
└── llm-generate        155ms
```

Trace chỉ thẳng vào bước retrieval. Với trace phẳng cũ, ta chỉ thấy "request mất
3.5s" mà không biết vì sao. Với `tool_fail`, span `retrieve-context` mang
`level=ERROR`, `status_message="RuntimeError: Vector store timeout"` và không có
span `llm-generate` — chứng tỏ pipeline dừng trước khi gọi LLM.

**Một bug thật đã phát hiện và sửa.** Ban đầu tôi đặt việc khởi tạo client (kèm
`mask`) ở dạng lazy. Nhưng decorator `@observe` gọi `get_client()` **trước** thân
hàm, mà Langfuse cache client theo `public_key` — nên client đầu tiên (thiếu
`mask`) bị dùng lại vĩnh viễn và **mask không bao giờ có hiệu lực**. Đã sửa bằng
`configure_tracing()` gọi trong startup event, và khoá lại bằng test
`test_startup_configures_masking_before_first_request` (chạy subprocess để có
singleton sạch). Log startup giờ in `trace_masking_active: true`.

**Giới hạn của SDK v3.2.1.** Best practice khuyên gán observation type cụ thể
(`retriever`, `tool`, `agent`), nhưng v3.2.1 chỉ hỗ trợ `span` và `generation`
(`as_type` chỉ nhận `"generation"`; không có `start_as_current_observation`).
Bản mới nhất là 4.14.3 nhưng repo pin `langfuse==3.2.1` và
`tests/test_tracing_adapter.py` assert rõ v3 API, nên **tôi không nâng cấp** để
khỏi phá test đã có. Giải pháp tạm: ghi `observation_type` vào metadata của span.

### 3.5 Đã audit trace thật trên Langfuse

Evidence: [`evidence/cp2-langfuse-traces.txt`](evidence/cp2-langfuse-traces.txt) ·
[`evidence/cp2-trace-structure.txt`](evidence/cp2-trace-structure.txt)

Ảnh giao diện Langfuse:

- [Danh sách traces](evidence/langfuse-traces-list.png) — cột Input hiển thị
  `[REDACTED_...]`, xác nhận PII không rời khỏi máy kể cả khi trace lên cloud.
- [Trace waterfall](evidence/trace-waterfall-incident.png) — 4 span lồng nhau,
  `retrieve-context` 2.50s trên tổng 2.65s.
- [Metadata của trace](evidence/trace-metadata-correlation.png) — `correlation_id`,
  `prompt_name/label/version/source`, `doc_count`.

**Sự cố cấu hình đã xử lý.** Ban đầu Langfuse trả 401 liên tục. Nguyên nhân không
phải key sai mà là **sai region**: cặp key đang thử thuộc `https://jp.cloud.langfuse.com`
(Langfuse Cloud Nhật Bản) trong khi `.env` trỏ `https://cloud.langfuse.com` (EU).
`.env` còn có dòng `LANGFUSE_BASE_URL="https://jp.cloud.langfuse.com"tô` bị dính ký
tự thừa khiến `python-dotenv` không parse được, và key bị bọc dấu nháy.

Bài học: thông điệp *"Invalid credentials"* của Langfuse **không phân biệt** key sai
với host sai. Cách tách bạch là thử cùng một cặp key với từng region.

**Chốt cuối cùng: nhóm dùng region EU** (`https://cloud.langfuse.com`, project
`My Project`). Trong buổi lab key bị đổi vài lần nên có giai đoạn trace nằm ở project
JP; toàn bộ evidence đã được **chạy lại từ đầu trên project EU** để mọi trace ID trong
báo cáo này đều mở được bằng đúng key trong `.env`. Trace ID thuộc project cũ đã bị
loại bỏ khỏi báo cáo.

Kết quả audit trace `5dcbeda3ea358aeeb4ca186e179b6dce` (fetch bằng Langfuse API):

| Tiêu chí best practice | Kết quả trên Langfuse |
|---|---|
| Tên trace mô tả được | `chat-response` ✅ |
| Phân cấp span | 4 observation, không phẳng ✅ |
| Đúng loại observation | `llm-generate` = `GENERATION`, còn lại `SPAN` ✅ |
| Model + token + cost | `claude-sonnet-4-5`, 36/165 token, `$0.002583` ✅ |
| Trace input/output có nghĩa | có, và đã scrub ✅ |
| PII được che | `[REDACTED_CREDIT_CARD]`; không còn email/phone/card/`user_id` thô ✅ |
| `user_id` / `session_id` | `4d14d5d4f719` (hash) / `s09` ✅ |
| Tags | `lab`, `qa`, `claude-sonnet-4-5` ✅ |
| Environment | `dev` ✅ |
| Score chất lượng | `quality_proxy = 0.9` ✅ |
| Nối Logs ↔ Traces | `correlation_id = req-487e5b1a` ✅ |
| Liên kết prompt version | `prompt_version=1`, `prompt_source=langfuse` ✅ |

Ba điều trước đó chưa kiểm chứng được thì nay đã xác nhận trên backend thật: trace
lên đúng, `quality_proxy` score vào đúng chỗ (score đi đường ingestion riêng chứ
không qua span attribute), và prompt được lấy thật từ Langfuse — `prompt_source`
chuyển từ `local-fallback` sang `langfuse`.

Hai lần gọi `update_current_trace` cũng đã chứng minh là **merge** đúng trên backend:
metadata cuối chứa cả `correlation_id` lẫn `prompt_name/label/version/source`.

Latency trở lại ~160ms/request (trước đó ~1100ms do mỗi request phải chờ prompt
fetch timeout vì 401) và không còn lỗi `Failed to export span batch`.

## 4. Prompt versioning

Evidence: [`evidence/prompt-versioning.md`](evidence/prompt-versioning.md)

Ảnh giao diện Langfuse:

- [Danh sách 2 version](evidence/prompt-versions-list.png) — v1 mang `production`+`baseline`,
  v2 mang `candidate`+`latest`.
- [Trace chạy label `baseline`](evidence/prompt-trace-baseline.png) — metadata `prompt_version: 1`.
- [Trace chạy label `candidate`](evidence/prompt-trace-candidate.png) — metadata `prompt_version: 2`.

- **Prompt name:** `day13-chat` (Langfuse Cloud region JP)
- **Version/label baseline:** v1 — labels `baseline`, `production`. Template gốc 3 biến
  `feature`, `docs`, `message`.
- **Version/label candidate:** v2 — label `candidate`. Thêm ràng buộc *"Answer in at most
  three sentences and cite the doc you used."*
- **Trace ID của mỗi version** (đã xác minh tồn tại bằng `langfuse-cli api traces get`):

| # | Thao tác | Trace ID | prompt_label | prompt_version | prompt_source |
|---|---|---|---|---|---|
| 1 | Chạy với label `baseline` | `e64429b9e75c96589eb46b19593d892b` | baseline | 1 | langfuse |
| 2 | Chạy với label `candidate` | `c6d5d976287b950014e2a0be78e138e9` | candidate | 2 | langfuse |
| 3 | Promote `production` → v2, chạy lại | `2bfdc4034338370a5134e58a8164f4c7` | production | 2 | langfuse |
| 4 | Rollback `production` → v1, chạy lại | `6e538ee2fec4dbc8e1be06d3dcc2bf7c` | production | 1 | langfuse |

- **Bằng chứng đổi label / rollback:** bước 3 → 4 dùng **cùng label `production`** và
  **cùng input**, nhưng `prompt_version` đổi từ 2 về 1 — không sửa code, không deploy lại,
  không restart. Chỉ đổi con trỏ label trên Langfuse. Output thật của script:

```
$ python scripts/prompt_versions.py promote --version 2
Trước: production -> v1
Sau:   production -> v2  (promote)

$ python scripts/prompt_versions.py rollback --version 1
Trước: production -> v2
Sau:   production -> v1  (rollback)
```

`prompt_source=langfuse` ở cả 4 trace xác nhận prompt được fetch thật từ Langfuse; nếu
fetch hỏng giá trị sẽ là `local-fallback`.

**Lưu ý về evidence cũ.** Bản trước của `evidence/prompt-versioning.md` khai 4 trace ID
khác và nói v2 mang label `candidate`+`latest`. Kiểm tra lại bằng `langfuse-cli` thì cả 4
ID đều trả `not found within authorized project` và prompt chỉ có v1. Nhiều khả năng
chúng thuộc project/key Langfuse khác (key bị thay hai lần trong buổi lab). Toàn bộ đã
được chạy lại và thay bằng số liệu kiểm chứng được.

Prompt trên Langfuse là immutable nên **không chạy lại `setup`** — mỗi lần chạy sẽ đẻ
thêm version mới. Vì project đã có sẵn v1, label `baseline` được gắn thẳng vào v1 bằng
`update_prompt` và chỉ tạo thêm đúng một v2.

## 5. Dashboard, SLO và alerts

- **Kết quả `validate_dashboard.py`:** `HỢP LỆ: 6/6 panel có trong dashboard contract.` —
  [`evidence/cp2-validate-dashboard.txt`](evidence/cp2-validate-dashboard.txt) (kèm cả
  `validate_alerts.py`: 4 alert rule, ngưỡng khớp SLO và dashboard)
- **Evidence dashboard:** [`evidence/dashboard-baseline.html`](evidence/dashboard-baseline.html),
  [`evidence/dashboard-baseline.png`](evidence/dashboard-baseline.png),
  [`evidence/dashboard-incident.html`](evidence/dashboard-incident.html),
  [`evidence/dashboard-incident.png`](evidence/dashboard-incident.png); contract ở
  [`config/dashboard.yaml`](../config/dashboard.yaml), dựng bằng `scripts/build_dashboard.py`
  từ `data/logs.jsonl`.

### 5.1 SLO đã chọn và lý do

[`config/slo.yaml`](../config/slo.yaml) — 4 SLI bám đúng 4 nhóm tín hiệu của dashboard:

| SLI | Objective | Target 28d | Lý do |
|---|---|---|---|
| `latency_p95_ms` | **2000** | 99.5% | **Siết từ 3000 → 2000 sau CP3** |
| `error_rate_pct` | 2 | 99.0% | `tool_fail` đẩy error lên 100%, ngưỡng 2% đủ nhạy |
| `daily_cost_usd` | 2.5 | 100% | Ngân sách, không phải độ tin cậy → không có error budget |
| `quality_score_avg` | 0.75 | 95% | Heuristic nội bộ, để 95% tránh báo động giả |

Thay đổi quan trọng nhất là `latency_p95_ms`. Giá trị cũ 3000ms **cao hơn**
`latency_threshold_ms=2000` của challenge, nghĩa là sự cố CP3 (p95 = 3095ms) chỉ vừa vượt
3000 và gần như không đốt error budget — SLO khi đó không phản ánh được nỗi đau thật.
Đã hạ xuống 2000ms và đồng bộ luôn `threshold` của panel latency trong
`config/dashboard.yaml` để dashboard và SLO không mâu thuẫn nhau.

Không đặt SLO cho `traffic`: lưu lượng là biến đầu vào của hệ thống, không phải cam kết
chất lượng với người dùng.

### 5.2 Alert rules và runbook

[`config/alert_rules.yaml`](../config/alert_rules.yaml) + runbook
[`docs/alerts.md`](../docs/alerts.md).

| Alert | Severity | Điều kiện | SLI |
|---|---|---|---|
| `ChatLatencySLOBreach` | critical | `p95(latency_ms) > 2000` duy trì 5 phút | `latency_p95_ms` |
| `ChatErrorRateHigh` | critical | error rate > 2% duy trì 5 phút | `error_rate_pct` |
| `ChatCostBudgetSpike` | warning | cost 24h > 2.5 USD **hoặc** cost/request 15 phút > 3x mức 24h trước | `daily_cost_usd` |

Ba alert phủ đúng ba cách hệ thống AI hỏng, nhưng phát biểu theo **triệu chứng người dùng**
chứ không theo tên sự cố nội bộ:

| Sự cố nội bộ | Triệu chứng người dùng | Alert |
|---|---|---|
| `rag_slow` | trả lời chậm | Alert 1 |
| `tool_fail` | không có trả lời | Alert 2 |
| `cost_spike` | không thấy gì, nhưng hoá đơn tăng | Alert 3 |

Cột giữa mới là thứ được đặt ngưỡng. Nếu đặt alert theo `rag_slow`, khi nguyên nhân chậm
đổi sang chỗ khác thì alert sẽ im lặng trong lúc người dùng vẫn khổ.

Vài quyết định thiết kế đáng nói:

- **Cost chỉ là `warning`, không `critical`.** Người dùng không bị ảnh hưởng, đây là rủi ro
  tài chính. Đánh thức người trực lúc 3h sáng vì hoá đơn là sai ưu tiên.
- **Điều kiện thứ hai của alert cost** (cost/request tăng 3x trong 15 phút) bắt được sự cố
  sớm ngay cả khi ngân sách ngày chưa cạn — nếu chỉ canh trần 2.5 USD/ngày thì đến lúc
  nổ đã tiêu hết tiền rồi.
- **Owner ghi theo vai trò**, không ghi tên cá nhân, để alert không bị mồ côi khi đổi
  người trực.
- **Không đặt alert cho `traffic` và `quality_score`**: traffic là biến đầu vào; quality
  proxy là heuristic nội bộ, đặt alert lên sẽ tạo nhiều báo động giả. Cả hai vẫn nằm trên
  dashboard để phục vụ điều tra.

Runbook viết theo hướng dùng được lúc 3h sáng: mỗi alert có ba bước kiểm tra đầu tiên
theo đúng luồng Metrics → Traces → Logs, và mitigation tạm thời **rẽ nhánh theo span nào
đang chậm** — vì `retrieve-context`, `resolve-prompt` và `llm-generate` chậm dẫn tới ba
hành động khắc phục hoàn toàn khác nhau.

## 6. Điều tra challenge

Evidence: [`evidence/cp3-challenge-investigation.txt`](evidence/cp3-challenge-investigation.txt)

Ảnh dashboard trước/sau sự cố:

- [Baseline](evidence/dashboard-baseline.png) — p95 1 059 ms, 6/6 panel đạt.
- [Khi có sự cố](evidence/dashboard-incident.png) — p95 13 274 ms, panel Latency
  chuyển sang `✗ vi phạm`; các panel error/cost/quality vẫn đạt.
- [Trace waterfall của chính sự cố](evidence/trace-waterfall-incident.png) và
  [metadata chứa correlation_id](evidence/trace-metadata-correlation.png).

- **Challenge ID:** `day13-k3-observability-v1` (cohort K3, seed 1303, `latency_threshold_ms=2000`)
- **Triệu chứng từ metrics:** trên cùng cửa sổ 60 phút, `latency_p95` đi từ **1 059ms**
  (10 request baseline) lên **13 274ms** khi chạy 5 query challenge — vượt ngưỡng 2000ms
  **6.6 lần**. Quan trọng không kém là những chỉ số **không** đổi: `error_breakdown` rỗng,
  `quality_avg` 0.88→0.87, `avg_cost_usd` ~0.002. Hệ thống **chậm chứ không hỏng**, nên
  chỉ nhìn error rate sẽ không thấy gì.
- **Trace ID liên quan:** `84d5b5e7fa15d136366bad1e57c51f71` (`session_id=k3-challenge-s01`,
  `feature=refund`). Waterfall: `retrieve-context` 2.501s chiếm **94.2%**, `llm-generate`
  0.151s chỉ 5.7% → thủ phạm là retrieval, không phải LLM.
- **Log line/correlation ID liên quan:** `req-dc7d2c11` — lấy từ `metadata.correlation_id`
  của chính trace trên, dùng để tra ngược ra cặp `request_received` / `response_sent`
  trong `data/logs.jsonl`. Log ghi `latency_ms=13289` nhưng `agent_latency_ms=2652`:
  phần chênh gần 10.6 giây là **thời gian xếp hàng**, không phải thời gian xử lý.
- **Root cause:** `app/mock_rag.py :: retrieve()` — nhánh `if STATE["rag_slow"]:
  time.sleep(2.5)` chèn độ trễ cố định 2.5s vào bước RAG retrieval trước khi trả document.

### 6.1 Luồng Metrics → Traces → Logs

**Metrics cho biết *có* vấn đề và loại trừ bớt khả năng.** Chỉ latency tăng, còn cost,
quality và error đều đứng yên. Điều này loại ngay `cost_spike` (cost phải tăng) và
`tool_fail` (phải có error 500). Kết luận: một bước trong pipeline bị chậm, không phải
lỗi logic hay tăng tải.

**Traces cho biết *ở đâu*.** So sánh waterfall hai trace cùng input:

| Span | Khoẻ | Incident | Chênh |
|---|---|---|---|
| `chat-response` (root) | 153ms | 3097ms | +2944ms |
| **`retrieve-context`** | **0ms** | **2506ms** | **+2506ms** |
| `resolve-prompt` | 1ms | 434ms | +433ms |
| `llm-generate` | 151ms | 155ms | +4ms |

Toàn bộ độ trễ nằm ở `retrieve-context`. `llm-generate` gần như không đổi → **không phải
lỗi model**. Đây chính là lý do việc tách span ở mục 3.4 là bắt buộc: với trace phẳng cũ
chỉ thấy "request mất 3.1s" mà không biết bước nào.

**Logs chứng minh *tại sao*, kèm mốc thời gian nhân quả:**

```
04:28:16.879Z  incident_enabled  rag_slow        level=warning   cid=req-fca47938
04:28:17.057Z  request_received  cid=req-9cddeabb  feature=refund   (178ms sau khi bật)
04:28:20.154Z  response_sent     cid=req-9cddeabb  latency_ms=3095
```

Phân bố latency của 10 request `feature=refund` (cùng input) tách thành hai cụm rõ rệt:
`152, 154, 155, 156, 598` và `2657, 2657, 2661, 2661, 3095`. Đúng 5 request trước và 5
request sau thời điểm bật incident, chênh nhau ~2.5s — khớp chính xác với `time.sleep(2.5)`.

### 6.2 Fix action

1. **Trước mắt:** tắt cờ sự cố — `python scripts/inject_incident.py --disable`. Trong hệ
   thống thật, tương đương rollback thay đổi vừa deploy vào lớp retrieval.
2. **Đặt timeout cho retrieval.** Hiện `retrieve()` không có timeout nên chậm bao nhiêu
   cũng chịu. Nên đặt ngân sách ~500ms, quá thì trả kết quả rỗng kèm fallback thay vì bắt
   người dùng chờ.
3. **Trả lời suy giảm thay vì chờ.** Khi retrieval quá hạn, vẫn gọi LLM với context rỗng
   và đánh dấu `degraded=true` trên trace — chậm 3s tệ hơn là câu trả lời kém một chút.

### 6.3 Preventive measure

1. **Alert theo p95 từng span, không chỉ p95 toàn request.** Nếu chỉ cảnh báo ở mức
   request thì mọi nguyên nhân trông giống nhau. Alert riêng cho `retrieve-context`
   p95 > 500ms sẽ chỉ thẳng thủ phạm ngay từ lúc nổ.
2. **Siết SLO cho khớp yêu cầu nghiệp vụ — ĐÃ LÀM.** `config/slo.yaml` trước đó đặt
   `latency_p95_ms: 3000`, cao hơn ngưỡng challenge 2000ms, nên sự cố này gần như
   **không đốt error budget** — SLO không phản ánh được nỗi đau thật. Đã hạ xuống
   **2000ms** và đồng bộ luôn `threshold` của panel latency trong `config/dashboard.yaml`
   để dashboard và SLO không mâu thuẫn. Xem mục 5.1.
3. **Kiểm tra hồi quy latency trong CI.** Test dựng sẵn để chặn đúng lớp lỗi này đã có:
   `tests/test_tracing_structure.py::test_slow_retrieval_is_isolated_to_its_own_span`
   assert `retrieve-context > 2000ms` khi bật `rag_slow`. Đảo assert này thành ngưỡng
   trần (`< 500ms` ở trạng thái khoẻ) sẽ chặn được regression trước khi lên production.
4. **Giữ trace có phân cấp.** Việc phát hiện được root cause trong vài phút hoàn toàn nhờ
   span con. Nếu quay lại trace phẳng, năng lực điều tra này mất theo.

### 6.4 Trả lời câu hỏi phản biện

**Bằng chứng nào khẳng định chắc chắn đó là root cause?** Ba lớp độc lập cùng chỉ về một
điểm và có quan hệ định lượng: trace cho thấy độ trễ tập trung *chỉ* ở `retrieve-context`
(+2506ms) trong khi `llm-generate` không đổi (+4ms); log cho thấy request chậm bắt đầu
đúng 178ms sau sự kiện `incident_enabled`; và độ chênh giữa hai cụm latency (~2502ms) khớp
đúng con số `sleep(2.5)` trong code. Trùng khớp cả về **vị trí**, **thời điểm** và **độ lớn**
— chứ không chỉ là tương quan.

**Nếu chỉ có metrics mà không có log chi tiết thì khó ở đâu?** Metrics chỉ nói "p95 tăng
lên 3.1s". Không biết bước nào chậm, không biết bắt đầu từ lúc nào, không biết request nào
bị ảnh hưởng. Sẽ phải đoán rồi thử từng khả năng. Quan trọng nhất là mất `correlation_id`
— thứ duy nhất nối một dòng metric tổng hợp về đúng request cụ thể và đúng dòng log của nó.
Metrics phát hiện *có* sự cố, nhưng không chứng minh được nguyên nhân.

## 7. Đóng góp cá nhân

> **Bảng dưới là bản nháp dựng từ `git log`, cần từng thành viên tự xác nhận và bổ sung
> cột "Điều đã học" bằng lời của mình.** Rubric B2 (20 điểm) yêu cầu phần khai trong báo
> cáo phải khớp thay đổi thật trong Git, nên đừng sửa cột Commit nếu chưa kiểm tra lại.
> Kiểm tra nhanh: `git log --author="<tên>" --oneline --stat`.

| Thành viên | MSSV | Phần việc | Commit/PR | Điều đã học |
|---|---|---|---|---|
| Hoàng Nguyễn Phong | 2A202601077 | Checkpoint 1 — correlation ID, log enrichment, PII redaction (`app/middleware.py`, `app/main.py`, `app/pii.py`, `app/logging_config.py`) | `d6b4c6f` phase 1<br>`e41c2c4` phase 2 | Correlation ID phải bind vào `contextvars` và **`clear_contextvars()` đầu mỗi request**, nếu không context của request trước rò sang request sau khi cùng worker. Server cũng phải **nhận lại `x-request-id` của client** thay vì luôn tự sinh, để giữ chuỗi liên kết khi request đi qua nhiều service.<br><br>PII cần **hai lớp**: scrub tại chỗ gọi (`summarize_text`) và processor `scrub_event` trong pipeline structlog. Lớp thứ hai mới là lớp chặn thật — bất kỳ log nào quên gọi `summarize_text` vẫn được che. `user_id` chỉ ghi hash SHA-256, đủ để nhóm request theo người dùng mà không lưu định danh. |
| Lê Hồng Đức | 2A202601313 | `.gitignore`; hoàn thiện phase 1; SLO + alert rules + runbook (`config/slo.yaml`, `config/alert_rules.yaml`, `docs/alerts.md`); merge nhánh nhóm | `611a0d2`, `f9e8018`,<br>`7703466` slo + alert,<br>`7405d0d` merge | **SLO lỏng hơn yêu cầu nghiệp vụ thì vô dụng.** Ngưỡng ban đầu `latency_p95_ms: 3000` cao hơn `latency_threshold_ms=2000` của challenge, nên sự cố thật (p95 = 3095ms) gần như không đốt error budget — SLO không phản ánh nỗi đau người dùng. Đã siết về 2000 và đồng bộ luôn dashboard.<br><br>Alert phải mô tả **triệu chứng**, không mô tả nguyên nhân: `p95 > 2000ms` vẫn đúng dù thủ phạm là RAG, LLM hay prompt; còn `vector_store_timeout > 0` sẽ im lặng khi hệ thống hỏng kiểu khác. Mỗi alert cần `for` và `minimum_samples` để không kêu vì một spike lẻ, và severity phải theo mức đau của người dùng — cost để `warning` vì không ai bị ảnh hưởng trực tiếp. |
| Nguyễn Văn Đạt | 2A202601969 | Dashboard builder + dashboard contract (`scripts/build_dashboard.py`, `docs/dashboard-spec.md`); validator alert + test SLO (`scripts/validate_alerts.py`, `tests/test_slo_alert_configuration.py`); đo latency theo trải nghiệm người dùng thay vì chỉ thời gian xử lý nội bộ, chuẩn hoá múi giờ VN (`app/timeutil.py`) và sinh lại evidence | `ad1f9bf` dashboard builder<br>`3bba989` SLO/alert/runbook<br>`72d6827` đo latency theo trải nghiệm người dùng, giờ VN, sinh lại evidence | Biến dashboard thành **contract có validator** giúp phát hiện lệch cấu hình sớm, nhưng validator chỉ đáng tin khi **lấy tên từ một nguồn sự thật duy nhất**. Bài học thật: `validate_alerts.py` ghim `daily_cost_usd` trong khi `config/slo.yaml` dùng `cost_total_usd`, nên validator **fail ngay trên `main`** dù cấu hình đúng — hai file do hai người viết đã trôi khỏi nhau mà không ai biết.<br><br>Ràng buộc quá chặt cũng có hại: `len(alerts) != 3` chặn luôn việc bổ sung alert hợp lệ cho SLI cost, nên đã nới thành cận dưới. Về đo lường: phải đọc **p95/p99 chứ không chỉ trung bình hay p50** — trong sự cố này p50 và p95 lệch nhau nhiều, chỉ nhìn một con số sẽ đánh giá sai mức nghiêm trọng. |
| Trần Nguyễn Thế Nhật | 2A202601155 | Instrumentation trace theo skill Langfuse chính thức (span phân cấp `retrieve-context`/`resolve-prompt`/`llm-generate`, `mask` PII ở tầng client, `quality_proxy` score, `correlation_id` ↔ trace, `flush()` lúc shutdown); prompt v1/v2 + promote/rollback; **điều tra Checkpoint 3** (baseline vs incident, waterfall, log timeline); gỡ span trùng ở `mock_rag`/`mock_llm`; sửa `validate_alerts.py` lệch tên SLI; test hồi quy (`tests/test_tracing_structure.py`, `tests/test_correlation_and_enrichment.py`); dọn `.omc/` khỏi Git; hoàn thiện REPORT mục 1–7 và evidence CP0/CP1/CP2/CP3 | `a0df0f8` update docs<br>`6cb70bf` Checkpoint 3<br>`4ab6301` fix validator<br>`7988bf6` finalize submission<br>`b8c30be` tên + MSSV<br>`da431de` điều đã học<br>`1d95b67` update report<br>`aa2b60c` đóng góp của Toàn | **Trace phẳng thì vô dụng khi điều tra.** Ban đầu cả request là một `generation`, chỉ thấy "mất 3.1s" mà không biết bước nào. Sau khi tách `retrieve-context` / `resolve-prompt` / `llm-generate`, sự cố lộ ngay: retrieval 2506ms còn LLM chỉ 155ms — loại trừ được lỗi model chỉ bằng cách nhìn.<br><br>`correlation_id` gắn vào trace metadata là thứ khâu Logs ↔ Traces; thiếu nó thì ba lớp quan sát là ba hòn đảo. Prompt label là **con trỏ**: rollback `production` từ v2 về v1 đổi hành vi ngay mà không sửa code, không deploy lại.<br><br>Hai cái bẫy đã mắc thật: (1) Langfuse cache client theo `public_key`, nên nếu `@observe` chạy trước thì client thiếu `mask` bị dùng lại vĩnh viễn và **PII masking không bao giờ có hiệu lực** — phải khởi tạo lúc startup; (2) lỗi 401 `"Invalid credentials"` **không phân biệt** sai key với sai host — key thật ra thuộc region JP, phải thử từng region mới ra. |
| Nguyễn Trọng Toàn | 2A202601493 | Dashboard runtime đọc trực tiếp `data/logs.jsonl` theo `config/dashboard.yaml` (`app/dashboard.py`, 280 dòng) + test (`tests/test_dashboard_runtime.py`); bổ sung test PII cho passport; hoàn thiện CP1 (`app/middleware.py`, `app/logging_config.py`, `app/pii.py`, `app/main.py`); SLO/alert/runbook; **chụp toàn bộ evidence ảnh CP2** (baseline trace, candidate trace, rollback trace, trace waterfall, dashboard) | `bcf1d44` hoàn thành bài lab<br>⚠️ **trên nhánh `origin/Toan`, chưa merge vào `main`** | Dashboard phải **đọc từ log thật theo contract** chứ không hard-code số liệu, nếu không nó chỉ là ảnh trang trí và không phản ánh hệ thống. Contract `config/dashboard.yaml` là nguồn sự thật chung cho cả code lẫn validator.<br><br>Bài học sắc nhất là về **false positive khi redact PII**: regex bắt passport `[A-Z]\d{7}` suýt nuốt luôn `correlation_id` dạng `req-c0391357`. Đã viết test `test_scrub_passport_without_redacting_correlation_id` để khoá lại — che PII quá tay sẽ phá chính công cụ điều tra, vì mất correlation ID là mất sợi dây nối Logs ↔ Traces. |


Kiểm tra lại từng dòng bằng: `git log --author="<tên hoặc email>" --oneline --stat`.

> ⚠️ **Nhánh `origin/Toan` chưa được merge vào `main`.** Commit `bcf1d44` của Nguyễn Trọng
> Toàn tách ra từ `611a0d2` và đi song song với toàn bộ tiến trình của nhánh `main`, nên
> phần việc và 5 ảnh evidence trong đó **không xuất hiện trong lịch sử `main`**. Nếu chỉ
> nộp `main`, người chấm sẽ không thấy đóng góp này. Kiểm chứng bằng:
>
> ```bash
> git log origin/main..origin/Toan --stat
> ```
>
> Nhóm cần quyết trước khi nộp: hoặc merge/cherry-pick phần còn giá trị từ `origin/Toan`
> vào `main`, hoặc ghi rõ trong bài nộp rằng đóng góp của thành viên này nằm ở nhánh
> `origin/Toan` cùng repository.

Ghi chú để trả lời phản biện: `HungBil <nguyendonghung70@gmail.com>` là tác giả các commit
khởi tạo lab (`b95464c`, `f1a02e5`, `7a57bfb`) và commit release `config/challenge.json`
(`cd84f4f`), không phải đóng góp của nhóm.

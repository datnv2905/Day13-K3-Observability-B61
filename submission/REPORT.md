# Báo cáo Day 13 Observability

## 1. Thông tin nhóm

- Tên nhóm:
- Repository URL:
- Commit SHA cuối:
- Thành viên và vai trò:

## 2. Kết quả kỹ thuật

- Điểm `validate_logs.py`: **100/100** (baseline 30/100) — [`evidence/cp1-final-validate-logs.txt`](evidence/cp1-final-validate-logs.txt)
- Tổng số traces: **10** trên Langfuse, mỗi trace 4 observation — [`evidence/cp2-langfuse-traces.txt`](evidence/cp2-langfuse-traces.txt)
- Số PII leak còn lại: **0** (`Potential PII leaks detected: 0` trên 23 log record)
- Link/đường dẫn dashboard: _chưa làm — Checkpoint 2_

### Checkpoint 0 — baseline

Baseline được đo trên đúng code khởi điểm (commit `611a0d2`, trước commit `phase 1`) bằng một
git worktree riêng, nên con số so sánh là thật chứ không phải ước lượng.

| Hạng mục | Baseline (`611a0d2`) | Sau CP1 (HEAD) |
|---|---|---|
| Basic JSON schema | FAILED — 20/21 record thiếu field bắt buộc | PASSED — 0 record thiếu |
| Correlation ID propagation | FAILED — 0 ID duy nhất | PASSED — 11 ID duy nhất |
| Log enrichment | FAILED — 20 record thiếu context | PASSED — 0 record thiếu |
| PII scrubbing | PASSED | PASSED |
| **Điểm ước lượng** | **30/100** | **100/100** |

- Evidence baseline: [`evidence/cp0-baseline-validate-logs.txt`](evidence/cp0-baseline-validate-logs.txt)
- Evidence health + load test: [`evidence/cp0-health-and-loadtest.txt`](evidence/cp0-health-and-loadtest.txt)
- `/health` trả `{"ok": true, "tracing_enabled": false, ...}`. `tracing_enabled=false` vì
  `LANGFUSE_PUBLIC_KEY`/`LANGFUSE_SECRET_KEY` trong `.env` còn rỗng; sẽ cấu hình ở Checkpoint 2.

Lưu ý trung thực: hạng mục PII đã PASSED ngay ở baseline. Lý do là `app/main.py` gọi
`summarize_text()` tại chỗ log, mà hàm này vốn đã chạy `scrub_text()`. Processor `scrub_event`
bị vô hiệu ở baseline nên **chưa có lớp chặn cuối** — bất kỳ log nào không đi qua
`summarize_text()` sẽ rò PII. Đó là lỗ hổng thật mà CP1 đã bịt (xem mục 3).

## 3. Logging và tracing

- Evidence correlation ID: [`evidence/cp1-correlation-id.txt`](evidence/cp1-correlation-id.txt)
- Evidence PII redaction: [`evidence/cp1-pii-redaction.txt`](evidence/cp1-pii-redaction.txt)
- Evidence regression tests: [`evidence/cp1-tests.txt`](evidence/cp1-tests.txt) — 28 passed
- Evidence trace waterfall: [`evidence/cp2-trace-structure.txt`](evidence/cp2-trace-structure.txt)
- Giải thích một span đáng chú ý: xem mục 3.4

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

Evidence: [`evidence/cp2-langfuse-traces.txt`](evidence/cp2-langfuse-traces.txt)

**Sự cố cấu hình đã xử lý.** Ban đầu Langfuse trả 401 liên tục. Nguyên nhân không
phải key sai mà là **sai region**: key thuộc `https://jp.cloud.langfuse.com`
(Langfuse Cloud Nhật Bản) trong khi `.env` trỏ `https://cloud.langfuse.com` (EU).
`.env` còn có dòng `LANGFUSE_BASE_URL="https://jp.cloud.langfuse.com"tô` bị dính ký
tự thừa khiến `python-dotenv` không parse được, và key bị bọc dấu nháy. Đã sửa
`LANGFUSE_HOST` về region JP, bỏ dòng hỏng và bỏ dấu nháy → `auth_check()` trả `True`.

Bài học: thông điệp *"Invalid credentials"* của Langfuse **không phân biệt** key sai
với host sai. Cách tách bạch là thử cùng một cặp key với từng region.

Kết quả audit trace `922e771578daf7302bb2fe579af07ad5` (fetch bằng `langfuse-cli`):

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

## 4. Prompt versioning

- Prompt name:
- Version/label baseline:
- Version/label candidate:
- Trace ID của mỗi version:
- Bằng chứng đổi label hoặc rollback:

## 5. Dashboard, SLO và alerts

- Kết quả `validate_dashboard.py`:
- Evidence dashboard:
- SLO đã chọn và lý do:
- Alert rules và runbook:

## 6. Điều tra challenge

- Challenge ID:
- Triệu chứng từ metrics:
- Trace ID liên quan:
- Log line/correlation ID liên quan:
- Root cause:
- Fix action:
- Preventive measure:

## 7. Đóng góp cá nhân

Với mỗi thành viên, ghi rõ nhiệm vụ và link commit/PR tương ứng.

| Thành viên | Phần việc | Commit/PR | Điều đã học |
|---|---|---|---|
| | | | |

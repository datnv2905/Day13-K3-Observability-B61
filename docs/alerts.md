# Template Alert và Runbook

Mỗi alert phải dựa trên triệu chứng người dùng hoặc SLO, không dựa trực tiếp vào tên implementation nội bộ.

Cấu hình máy đọc được nằm tại [`config/alert_rules.yaml`](../config/alert_rules.yaml); ngưỡng lấy từ [`config/slo.yaml`](../config/slo.yaml).

Cùng một ngưỡng đang nằm ở ba file (`slo.yaml`, `alert_rules.yaml`, `dashboard.yaml`), nên sửa
một chỗ phải sửa cả ba. Kiểm tra bằng:

```bash
python scripts/validate_alerts.py
```

Ba bước kiểm tra trong mọi runbook dưới đây đi theo cùng một thứ tự:
**Metrics** nói *có* chuyện gì đó → **Traces** nói chuyện đó xảy ra *ở đâu* → **Logs** nói *tại sao*.
Không kết luận khi mới có một lớp.

## Alert 1

- **Tên:** `high_latency_p95`
- **Severity:** warning
- **SLI/SLO liên quan:** `latency_p95_ms` — objective 3000 ms, target 99.5% trong 28 ngày
- **Điều kiện và thời gian duy trì:** `latency_p95 > 3000ms` **duy trì 5 phút**.
  Duration 5 phút để không kêu vì một spike lẻ; warning chứ không critical vì hệ thống
  vẫn trả lời được, chỉ chậm.
- **Ảnh hưởng tới người dùng:** câu trả lời về sau hơn 3 giây. Người dùng nghĩ hệ thống
  treo, bấm gửi lại, làm tải tăng thêm và đẩy latency lên tiếp.

### Ba bước kiểm tra đầu tiên

1. **Metrics — chậm toàn bộ hay chỉ phần đuôi?**

   ```bash
   curl http://127.0.0.1:8000/metrics
   python scripts/build_dashboard.py --open
   ```

   So `latency_p50` với `latency_p95`. P50 cũng tăng → cả hệ thống chậm (nghi tài nguyên,
   tải). Chỉ P95/P99 tăng còn P50 bình thường → chỉ một nhóm request bị ảnh hưởng, sang bước 2
   tìm xem nhóm đó có gì chung. Đồng thời xem panel Traffic: latency tăng vì tải tăng hay
   tự nhiên tăng.

2. **Traces — thời gian tiêu ở span nào?**

   Mở Langfuse → Tracing → sắp xếp theo Latency giảm dần → mở trace chậm nhất trong khung
   giờ alert. Đọc waterfall và so hai span con:

   | Span chiếm phần lớn thời gian | Hướng điều tra |
   |---|---|
   | `retrieve` | vector store / RAG chậm |
   | `llm_generate` | LLM chậm hoặc prompt phình to |
   | Cả hai đều nhanh nhưng tổng chậm | overhead ngoài agent — middleware, hàng đợi |

   Ghi lại `trace_id` và `session_id`.

3. **Logs — xác nhận bằng bản ghi của chính request đó.**

   ```bash
   python -c "import json;[print(json.dumps(r,ensure_ascii=False)) for r in map(json.loads,open('data/logs.jsonl',encoding='utf-8')) if r.get('session_id')=='<session_id>']"
   ```

   Đối chiếu `latency_ms` trong log với latency trên trace. Khớp thì kết luận đứng vững;
   lệch nhiều thì chậm nằm ngoài `agent.run()` và giả thuyết ở bước 2 sai.

### Mitigation tạm thời

- Nếu `retrieve` là thủ phạm và có incident đang bật: `python scripts/inject_incident.py --scenario rag_slow --disable`.
- Nếu vừa đổi prompt: rollback về bản đã biết là ổn — `python scripts/prompt_versions.py rollback --version 1`,
  sau đó xác nhận `python scripts/prompt_versions.py list` báo `production -> v1`.
- Nếu không chốt được nguyên nhân trong 15 phút: escalate cho team-lead, **không** tự ý sửa code trên production.

- **Owner:** on-call-engineer

## Alert 2

- **Tên:** `elevated_error_rate`
- **Severity:** critical
- **SLI/SLO liên quan:** `error_rate_pct` — objective 2%, target 99.0%
- **Điều kiện và thời gian duy trì:** `error_rate_pct > 2` **duy trì 3 phút**.
  Duration ngắn hơn Alert 1 và mức critical vì lỗi nặng hơn chậm: người dùng không nhận
  được câu trả lời nào chứ không phải nhận muộn.
- **Ảnh hưởng tới người dùng:** request trả HTTP 500. Với error rate 2%, cứ 50 người thì
  1 người không dùng được — con số này lớn hơn cảm giác "chỉ 2%" rất nhiều.

### Ba bước kiểm tra đầu tiên

1. **Metrics — lỗi thuộc loại nào?**

   ```bash
   curl http://127.0.0.1:8000/metrics
   ```

   Đọc `error_breakdown`. Một loại lỗi chiếm đa số → hỏng một chỗ cụ thể. Nhiều loại lỗi
   khác nhau cùng lúc → nghi hạ tầng hoặc thay đổi vừa deploy. Đối chiếu thời điểm lỗi bắt
   đầu với lần đổi prompt/deploy gần nhất.

2. **Traces — lỗi xảy ra ở bước nào trong request?**

   Trong Langfuse lọc trace có status lỗi trong khung giờ đó. Xem span nào là span cuối
   cùng chạy được: dừng ở `retrieve` nghĩa là chưa kịp gọi LLM; chạy hết `llm_generate` mới
   lỗi nghĩa là hỏng ở khâu xử lý sau. Kiểm tra luôn `prompt_version` của các trace lỗi — nếu
   tất cả cùng một version thì đó là nghi phạm số một.

3. **Logs — đọc `error_type` và chi tiết.**

   ```bash
   python -c "import json;[print(r['correlation_id'],r.get('error_type'),(r.get('payload') or {}).get('detail')) for r in map(json.loads,open('data/logs.jsonl',encoding='utf-8')) if r.get('event')=='request_failed']"
   ```

   `error_type` là tên exception thật. Ví dụ `RuntimeError` kèm detail `Vector store timeout`
   chỉ thẳng vào `mock_rag.retrieve`. Lấy `correlation_id` để tra ngược sang `request_received`
   cùng ID và biết request đó có gì đặc biệt.

### Mitigation tạm thời

- Nếu trace lỗi tập trung ở một `prompt_version`: rollback ngay — `python scripts/prompt_versions.py rollback --version 1`.
- Nếu là incident đang bật: `python scripts/inject_incident.py --scenario tool_fail --disable`.
- Nếu lỗi đến từ dependency ngoài: xác nhận app có fallback đúng không. Langfuse chết thì
  `resolve_prompt` phải ghi `prompt_source=local-fallback` và app vẫn chạy — nếu app chết theo
  thì đó mới là bug thật cần sửa.

- **Owner:** on-call-engineer

## Alert 3

- **Tên:** `cost_budget_exceeded`
- **Severity:** warning
- **SLI/SLO liên quan:** `daily_cost_usd` — objective $2.5/ngày, target 100%
- **Điều kiện và thời gian duy trì:** `daily_cost_usd > 2.5`, cộng dồn theo ngày UTC, đánh
  giá mỗi giờ. Không đặt duration ngắn vì đây là chỉ số tích luỹ — đã vượt thì không tự
  giảm lại trong ngày.
- **Ảnh hưởng tới người dùng:** không ảnh hưởng ngay, nhưng vượt ngân sách dẫn tới bị chặn
  quota và khi đó **toàn bộ** người dùng mất dịch vụ. Cảnh báo sớm chính là để tránh cái đó.

### Ba bước kiểm tra đầu tiên

1. **Metrics — cost tăng vì nhiều request hơn hay vì mỗi request đắt hơn?**

   Đây là câu hỏi phải trả lời trước tiên. So panel Cost với panel Traffic:

   | Traffic | Cost | Kết luận |
   |---|---|---|
   | tăng | tăng | nhu cầu tăng thật — xem có phải bot/retry không |
   | **không đổi** | **tăng** | mỗi request đắt lên → sang bước 2 xem token |

   Kiểm tra chéo `tokens_out_total / traffic` giữa hôm nay và baseline.

2. **Traces — token phình ở đâu?**

   Mở vài generation trong Langfuse, đọc `usage_details`. Baseline là khoảng
   **24 prompt tokens / 179 completion tokens** mỗi request. `completion_tokens` tăng vọt
   nghĩa là model trả lời dài ra — thường do prompt vừa đổi. `prompt_tokens` tăng nghĩa là
   context nhồi vào nhiều hơn, ví dụ RAG trả về quá nhiều tài liệu. Đối chiếu `prompt_version`
   của các trace đắt với version đang gắn label `production`.

3. **Logs — xác nhận trên toàn bộ dữ liệu, không chỉ vài mẫu.**

   ```bash
   python -c "import json;rs=[r for r in map(json.loads,open('data/logs.jsonl',encoding='utf-8')) if r.get('event')=='response_sent'];print('n=%d  tokens_out/req=%.1f  cost/req=%.6f'%(len(rs),sum(r['tokens_out'] for r in rs)/len(rs),sum(r['cost_usd'] for r in rs)/len(rs)))"
   ```

   Vài trace đắt có thể chỉ là ngoại lệ; trung bình trên toàn bộ log mới chứng minh được
   đây là thay đổi hệ thống.

### Mitigation tạm thời

- Nếu token phình sau khi đổi prompt: `python scripts/prompt_versions.py rollback --version 1`,
  rồi chạy lại load test và so `cost/req` trước–sau.
- Nếu là incident đang bật: `python scripts/inject_incident.py --scenario cost_spike --disable`.
- Nếu do nhu cầu tăng thật: không rollback. Báo team-lead xin nâng ngân sách và cập nhật
  `daily_cost_usd` trong `config/slo.yaml` cùng threshold panel Cost trong `config/dashboard.yaml`
  — hai chỗ phải đổi cùng nhau.

- **Owner:** team-lead

---

## Vì sao không đặt alert cho quality proxy

`quality_score_avg` có trong SLO nhưng cố ý **không** có alert. Quality proxy là heuristic
tự viết ([`app/agent.py::_heuristic_quality`](../app/agent.py)), chỉ nhận vài giá trị rời rạc
(baseline chỉ ra 0.8 và 0.9), nên nó dao động vì lý do vô hại và sẽ tạo alert nhiễu. Một alert
mà người trực học được cách phớt lờ còn tệ hơn là không có alert.

Chỉ số này vẫn được theo dõi trên dashboard và xem lại định kỳ. Khi nào có evaluation thật
thay cho heuristic thì mới cân nhắc đặt alert.

## Vì sao alert phải symptom-based

Câu hỏi phản biện của Checkpoint 2. Ba lý do:

1. **Triệu chứng không đổi, nguyên nhân thì có.** `latency_p95 > 3000ms` vẫn đúng dù thủ phạm
   là vector store, LLM hay prompt mới. Alert dạng `vector_store_timeout > 0` chỉ bắt được đúng
   một cách hỏng và **im lặng** khi hệ thống hỏng theo cách khác — đó là kiểu hỏng nguy hiểm
   nhất vì người trực tưởng mọi thứ bình thường.

2. **Alert theo nguyên nhân sinh ra rừng alert.** Mỗi thành phần lại thêm vài rule, đa số
   không ảnh hưởng người dùng. Người trực bị đánh thức vì những thứ không ai cảm nhận được,
   rồi bắt đầu bỏ qua alert — và bỏ qua luôn cái quan trọng.

3. **Alert theo triệu chứng bám vào SLO, tức bám vào cam kết với người dùng.** Mỗi alert ở
   trên đều trỏ về một SLI trong `config/slo.yaml`. Đánh thức người khác lúc 3 giờ sáng chỉ
   chính đáng khi cam kết đó đang bị vi phạm.

Nguyên nhân không bị bỏ quên — nó là nội dung của **bước 2 và 3** trong runbook. Alert trả lời
"có đang hỏng không"; runbook trả lời "hỏng ở đâu và vì sao".

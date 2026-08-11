# Evidence — Prompt versioning và rollback (Checkpoint 2)

Toàn bộ trace ID dưới đây đã được fetch lại từ Langfuse API để xác minh tồn tại,
không phải chép tay.

- Project: **Langfuse Cloud region EU** (`https://cloud.langfuse.com`), project `My Project`
- Prompt name: `day13-chat`
- Input dùng chung cho mọi lần chạy: `"What is your refund policy?"`

Sinh lại được bằng `scripts/prompt_versions.py`:

```bash
python scripts/prompt_versions.py list                  # xem label đang trỏ version nào
python scripts/prompt_versions.py compare               # bước 3-4: 2 label, 2 trace ID
python scripts/prompt_versions.py promote --version 2   # bước 5
python scripts/prompt_versions.py rollback --version 1  # bước 6
```

**Không chạy lại `setup`** — prompt trên Langfuse là immutable nên mỗi lần chạy `setup`
sẽ đẻ thêm version mới (v3, v4...) thay vì sửa v1/v2 đang có. Project đã có sẵn v1 nên
label `baseline` được gắn thẳng vào v1 bằng `update_prompt`, và chỉ tạo thêm đúng một v2.

## Hai version

| Version | Labels sau cùng | Nội dung |
|---|---|---|
| v1 | `baseline`, `production` | 3 biến gốc: `feature`, `docs`, `message` |
| v2 | `candidate` | thêm dòng "Answer in at most three sentences and cite the doc you used." |

## Chuỗi trace chứng minh

| # | Thao tác | Trace ID | prompt_label | prompt_version | prompt_source |
|---|---|---|---|---|---|
| 1 | Chạy với label `baseline` | `e64429b9e75c96589eb46b19593d892b` | baseline | 1 | langfuse |
| 2 | Chạy với label `candidate` | `c6d5d976287b950014e2a0be78e138e9` | candidate | 2 | langfuse |
| 3 | Promote `production` sang v2, chạy lại | `2bfdc4034338370a5134e58a8164f4c7` | production | 2 | langfuse |
| 4 | Rollback `production` về v1, chạy lại | `6e538ee2fec4dbc8e1be06d3dcc2bf7c` | production | 1 | langfuse |

Mở trực tiếp: `https://cloud.langfuse.com/project/cmso2x37a03i3ad0jjy09f5pm/traces/<trace_id>`

## Con trỏ label trước/sau (output thật của `prompt_versions.py list`)

```
ban đầu              promote --version 2      rollback --version 1
production  -> v1    production  -> v2        production  -> v1
baseline    -> v1    baseline    -> v1        baseline    -> v1
candidate   -> v2    candidate   -> v2        candidate   -> v2
```

Output thật của lệnh promote và rollback:

```
$ python scripts/prompt_versions.py promote --version 2
Trước: production -> v1
Sau:   production -> v2  (promote)

$ python scripts/prompt_versions.py rollback --version 1
Trước: production -> v2
Sau:   production -> v1  (rollback)
```

## Vì sao đây là bằng chứng rollback

Bước 3 → 4 dùng **cùng một label `production`** và **cùng một input**, nhưng
`prompt_version` đổi từ 2 về 1. Không sửa một dòng code nào, không deploy lại, không
restart app — chỉ đổi con trỏ label trên Langfuse. Đó chính là giá trị của prompt
management: đưa việc đổi prompt ra khỏi vòng đời release của code.

`prompt_source=langfuse` ở cả 4 trace xác nhận prompt được fetch thật từ Langfuse chứ
không phải template local fallback (nếu fetch hỏng, giá trị sẽ là `local-fallback`).

## Ghi chú về các phiên bản trước của file này

Trong buổi lab, key Langfuse bị đổi vài lần và nhóm có lúc dùng region JP, có lúc EU.
Hệ quả là hai bản trước của file này khai trace ID thuộc **project khác** với project
đang cấu hình trong `.env`, nên tra bằng API đều trả `not found within authorized project`:

- Bản 1 khai `4ccc605b…`, `6eca60ce…`, `12fda507…`, `8abcc3eb…` (project EU cũ, key đã bị thay).
- Bản 2 khai `d383d92f…`, `22c9281a…`, `cb924f04…`, `129ab7dc…` (project JP).

Nhóm đã **chốt dùng region EU**, và toàn bộ số liệu trong file này được chạy lại từ đầu
trên project đang cấu hình. Cả 4 trace ID ở bảng trên đều đã fetch được qua API.

## Ảnh cần chụp bổ sung

Trace ID là bằng chứng kiểm chứng được, nhưng lab còn yêu cầu ảnh giao diện:

- [ ] `prompt-versions-list.png` — danh sách 2 version kèm label trên tab Prompts
- [ ] `prompt-trace-baseline.png` — trace #1, metadata hiện `prompt_version: 1`
- [ ] `prompt-trace-candidate.png` — trace #2, metadata hiện `prompt_version: 2`
- [ ] `prompt-rollback.png` — nhãn `production` trước/sau khi đổi

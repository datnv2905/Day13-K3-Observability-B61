# Evidence — Prompt versioning và rollback (Checkpoint 2)

Toàn bộ số liệu dưới đây đã được fetch lại từ Langfuse bằng `langfuse-cli` để xác minh,
không phải chép tay.

- Project: Langfuse Cloud region JP (`https://jp.cloud.langfuse.com`)
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
sẽ đẻ thêm version mới (v3, v4...) thay vì sửa v1/v2 đang có. Vì project đã có sẵn v1,
label `baseline` được gắn thẳng vào v1 bằng `update_prompt` và chỉ tạo thêm đúng một v2,
để không sinh version thừa.

## Hai version

| Version | Labels sau cùng | Nội dung |
|---|---|---|
| v1 | `baseline`, `production` | 3 biến gốc: `feature`, `docs`, `message` |
| v2 | `candidate` | thêm dòng "Answer in at most three sentences and cite the doc you used." |

## Chuỗi trace chứng minh

Tất cả 4 trace đã được xác minh tồn tại bằng `npx langfuse-cli api traces get <id>`.

| # | Thao tác | Trace ID | prompt_label | prompt_version | prompt_source |
|---|---|---|---|---|---|
| 1 | Chạy với label `baseline` | `d383d92f39a27f7f3ce274fa78976f73` | baseline | 1 | langfuse |
| 2 | Chạy với label `candidate` | `22c9281a410b9ab1fb4d43d0c4f60aa0` | candidate | 2 | langfuse |
| 3 | Promote `production` sang v2, chạy lại | `cb924f04ecffbc155d531b1c051ac363` | production | 2 | langfuse |
| 4 | Rollback `production` về v1, chạy lại | `129ab7dc2f4a6e074a3b49163ae9f70d` | production | 1 | langfuse |

## Con trỏ label trước/sau (output thật của `prompt_versions.py list`)

```
sau setup            promote --version 2      rollback --version 1
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

## Ghi chú về phiên bản trước của file này

Bản trước của file này khai 4 trace ID khác (`4ccc605b…`, `6eca60ce…`, `12fda507…`,
`8abcc3eb…`) và nói v2 mang label `candidate`+`latest`. Kiểm tra lại bằng
`langfuse-cli` thì cả 4 ID đều trả `not found within authorized project`, và prompt
chỉ có v1. Nhiều khả năng chúng thuộc một project/key Langfuse khác (key đã bị thay
hai lần trong buổi lab). Toàn bộ số liệu đã được chạy lại và thay bằng dữ liệu
kiểm chứng được trên project hiện tại.

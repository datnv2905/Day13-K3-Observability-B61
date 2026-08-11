# Evidence — Prompt versioning và rollback (Checkpoint 2)

Sinh lại được bằng `scripts/prompt_versions.py`:

```bash
python scripts/prompt_versions.py list                  # xem label đang trỏ version nào
python scripts/prompt_versions.py compare               # bước 3-4: 2 label, 2 trace ID
python scripts/prompt_versions.py promote --version 2   # bước 5
python scripts/prompt_versions.py rollback --version 1  # bước 6
```

Lưu ý: **không chạy lại `setup`** — prompt trên Langfuse là immutable nên mỗi lần
chạy `setup` sẽ đẻ thêm version mới (v3, v4...) thay vì sửa v1/v2 đang có.

- Prompt name: `day13-chat`
- Input dùng chung cho mọi lần chạy: `"What is your refund policy?"`
- Feature: `refund`

## Hai version

| Version | Labels | Nội dung khác biệt |
|---|---|---|
| v1 | `baseline`, `production` | 3 biến gốc: `feature`, `docs`, `message` |
| v2 | `candidate`, `latest` | thêm ràng buộc "Answer in at most 3 sentences and cite the retrieved docs." |

## Chuỗi trace chứng minh

| # | Thao tác | Trace ID | prompt_label | prompt_version | prompt_source |
|---|---|---|---|---|---|
| 1 | Chạy với label `baseline` | `4ccc605bec35d9475b13efe7d58a61bc` | baseline | 1 | langfuse |
| 2 | Chạy với label `candidate` | `6eca60ce251ab917def3acdb340f6704` | candidate | 2 | langfuse |
| 3 | Promote `production` sang v2, chạy lại | `12fda507ed70665a64e9c1bdec6d4b71` | production | 2 | langfuse |
| 4 | Rollback `production` về v1, chạy lại | `8abcc3eb15209475fc3744f03b68c1e6` | production | 1 | langfuse |

Bước 3 → 4 là bằng chứng rollback: cùng label `production`, cùng input, nhưng version
đổi từ 2 về 1 **mà không sửa code và không deploy lại**. Chỉ đổi con trỏ label trên Langfuse.

`prompt_source=langfuse` ở cả 4 trace xác nhận prompt được fetch thật từ Langfuse,
không phải template local fallback.

## Ảnh cần chụp bổ sung

- [ ] `evidence/prompt-versions-list.png` — danh sách 2 version kèm label
- [ ] `evidence/prompt-trace-baseline.png` — trace #1, metadata hiện `prompt_version=1`
- [ ] `evidence/prompt-trace-candidate.png` — trace #2, metadata hiện `prompt_version=2`
- [ ] `evidence/prompt-rollback.png` — trước/sau khi đổi label `production`

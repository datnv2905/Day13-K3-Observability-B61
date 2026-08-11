# Phase 1 validation — local run

Run date: 2026-08-11 (Asia/Ho_Chi_Minh)

## Runtime checks

- `GET /health` returned `ok: true`; Langfuse tracing was deliberately disabled for this
  local Phase 1 verification.
- `python scripts/load_test.py` sent 10 requests and all returned HTTP 200.
- Newly generated API events carried a unique `req-<hex>` correlation ID, request context
  (`user_id_hash`, `session_id`, `feature`, `model`, `env`), and response metrics.

## Validator result

`python scripts/validate_logs.py` reported:

- 48 JSON log records analyzed
- 0 records missing required fields
- 0 API events missing request enrichment
- 21 unique correlation IDs
- 0 detected raw PII leaks
- Estimated score: **100/100**

## Automated coverage

`python -m pytest -q -p no:cacheprovider` passed **23 tests**. The Phase 1 additions verify:

- inbound `x-request-id` is echoed and response timing is returned;
- API logs contain the required request context;
- email, Vietnamese phone number, credit-card, CCCD, passport, and nested values are redacted
  before JSON rendering.

No Langfuse trace, secret, or raw PII is included in this evidence file.

# CP1 Logging and PII evidence

## Validation

- Basic JSON schema: passed.
- Correlation ID propagation: passed (10 unique IDs in the validation run).
- Log enrichment: passed.
- PII scrubbing: passed, 0 detected leaks.
- Estimated score: 100/100.

## Correlation and enrichment example

```json
{"event":"request_received","correlation_id":"req-132d41e2","user_id_hash":"2055254ee30a","session_id":"s01","feature":"qa","model":"claude-sonnet-4-5","env":"dev"}
```

The matching `response_sent` record uses the same correlation ID `req-132d41e2`.

## PII redaction examples

```json
{"message_preview":"What is your refund policy? My email is [REDACTED_EMAIL]"}
{"message_preview":"Here is my phone [REDACTED_PHONE_VN], what should be logged?"}
{"message_preview":"What is the policy for PII and credit card [REDACTED_CREDIT_CARD]?"}
```

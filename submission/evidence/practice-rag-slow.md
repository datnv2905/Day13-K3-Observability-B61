# Practice incident: rag_slow

Practice scenario allowed by the README; this is not presented as the official challenge.

- Baseline latency: 1019 ms.
- `rag_slow` latency: 2650 ms.
- Increase: approximately 160%.
- Baseline correlation ID: `req-c0391357`.
- Slow correlation ID: `req-a5051032`.
- Baseline trace ID: `65fa079002dce42d39eaee51de58c0b0`.
- Slow trace ID: `05e549cd933c0fc06cda9e54833e3675`.
- Practice incident was disabled immediately after the slow request.

The run also exposed an over-broad passport regex that could redact a lowercase correlation-ID suffix. The regex was restricted to uppercase passport formats and a regression test was added.

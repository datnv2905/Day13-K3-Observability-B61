# CP2 Langfuse prompt trace evidence

Prompt name: `day13-chat`

Total traces verified through the Langfuse API after the practice run: **28**.

| Purpose | Trace ID | Label | Version | Source |
|---|---|---|---:|---|
| Baseline | `41dcfe875f88da75f4190bd0ec712cb0` | `baseline` | 1 | `langfuse` |
| Candidate | `ca55680b65fa8370e375fdb81d6f72fa` | `candidate` | 2 | `langfuse` |
| Production before rollback | `6885f08e8b2afcedad56e68531411e3b` | `production` | 2 | `langfuse` |
| Production after rollback | `3012069c364eb7e195d188d33389b0a2` | `production` | 1 | `langfuse` |

Final prompt label state verified through the Langfuse API:

- Version 1: `baseline`, `production`.
- Version 2: `candidate`, `latest`.

All four traces used the same comparison question: `What is your refund policy?`.

## Ten recent trace IDs

1. `3012069c364eb7e195d188d33389b0a2`
2. `6885f08e8b2afcedad56e68531411e3b`
3. `ca55680b65fa8370e375fdb81d6f72fa`
4. `2df71ede9e89700a1b34db08707a3981`
5. `41dcfe875f88da75f4190bd0ec712cb0`
6. `82dfe6b68311d2ccff06394db750115d`
7. `b021603403003c8787d40d8033b953c4`
8. `7cc90ff2e7bccb1c211a144d055c09d1`
9. `a7de332b17242c22a67fa9efc5231503`
10. `35fd3f11aeb826e5953af7310e580360`

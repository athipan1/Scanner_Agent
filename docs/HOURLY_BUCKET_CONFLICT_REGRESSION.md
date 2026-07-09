# Hourly Bucket Conflict Regression

This document records the July 9, 2026 paper-trading regression that motivated `scanner-bucket-hint-policy-v3`.

## Observed failure mode

Scanner returned advisory bucket metadata and copied machine-oriented tags into the candidate's generic `tags` array. Manager then interpreted strings containing `dividend`, `rebound`, `news`, and `momentum` as separate business evidence.

A single Scanner hint was therefore counted twice:

```text
Scanner typed bucket score
+ generic tag interpretation in Manager
```

This produced avoidable multi-bucket conflicts and quarantined every candidate in the hourly run.

## Regression symbols

The test fixture uses the actual Scanner inputs captured for:

- ACGL
- BKNG
- ADBE
- CINF
- ACIC
- CGEN
- BFC
- ACAD

The policy requires that none of these fixtures emits `bucket_hint_status=conflict` solely from broad Scanner evidence.

## Expected policy behavior

- Strong deep-value evidence may emit `value_rebound`.
- Advisory ambiguity emits `review` so Manager can use richer Fundamental and Technical evidence.
- Generic tags are never modified with bucket control metadata.
- Scanner still remains non-binding and cannot authorize a BUY.

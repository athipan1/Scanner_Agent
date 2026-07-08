# Strategy Bucket Hint Contract

Scanner_Agent emits non-binding evidence to help Manager_Agent classify candidates into the controlled strategy buckets:

- `core_dividend`
- `value_rebound`
- `news_momentum`

Scanner never assigns the final portfolio bucket.

## Version

```text
scanner-bucket-hints-v2
```

Every `CandidateResult` and `ScannerCandidateContract` contains a typed `bucket_hint` object. The same fields are mirrored into candidate `metadata` for backward compatibility with Manager_Agent.

## Output fields

- `bucket_hint_version`
- `bucket_hint_status`
- `primary_strategy_bucket_hint`
- `primary_strategy_bucket_confidence`
- `strategy_bucket_confidence`
- `strategy_bucket_hints`
- `bucket_hint_scores`
- `bucket_hint_margin`
- `bucket_hint_evidence`
- `bucket_hint_reasons`
- `bucket_hint_is_binding=false`
- `manager_decision_required=true`
- `controlled_strategy_buckets`

## Status policy

```text
suggested             top score >= 0.65 and margin >= 0.10
review                top score >= 0.50 but not strong enough to suggest
conflict              top two scores >= 0.60 and margin < 0.10
insufficient_evidence top score < 0.50
```

Only `suggested` emits `primary_strategy_bucket_hint`. Review, conflict, and insufficient-evidence candidates abstain instead of manufacturing a bucket.

## Evidence sources

Core-dividend evidence can include quality, positive free cash flow, lower leverage, dividend yield, and defensive/income-oriented sectors.

Value-rebound evidence can include valuation score, low PE/PB, quality support, and positive free cash flow.

News-momentum evidence can include growth, momentum, relative strength, technical votes, volume expansion, and proximity to a breakout.

## Safety properties

- No ticker-specific rules.
- No unknown bucket names.
- Watchlist and dev-fallback candidates do not receive a fabricated primary hint.
- Scanner hints remain advisory; Manager classification, Risk approval, Execution validation, and Database persistence remain mandatory.

# Strategy Bucket Hint Contract

Scanner_Agent emits non-binding evidence to help Manager_Agent classify candidates into the controlled strategy buckets:

- `core_dividend`
- `value_rebound`
- `news_momentum`

Scanner never assigns the final portfolio bucket.

## Versions

```text
contract: scanner-bucket-hints-v2
policy:   scanner-bucket-hint-policy-v3
```

The contract version remains `v2` so Manager_Agent compatibility is preserved. Policy v3 changes scoring, ambiguity handling, and generic-tag isolation.

Every `CandidateResult` and `ScannerCandidateContract` contains a typed `bucket_hint` object. The same fields are mirrored into candidate `metadata` for backward compatibility.

## Output fields

- `bucket_hint_version`
- `bucket_hint_policy_version`
- `bucket_hint_status`
- `primary_strategy_bucket_hint`
- `primary_strategy_bucket_confidence`
- `strategy_bucket_confidence`
- `strategy_bucket_hints`
- `bucket_hint_scores`
- `bucket_hint_margin`
- `bucket_hint_evidence`
- `bucket_hint_defining_evidence`
- `bucket_hint_supporting_evidence`
- `bucket_hint_dominance_rule`
- `bucket_hint_reasons`
- `bucket_hint_tags`
- `bucket_hint_is_binding=false`
- `manager_decision_required=true`
- `controlled_strategy_buckets`

## Defining versus supporting evidence

Policy v3 separates bucket identity from broad quality support.

### Bucket-defining evidence

Examples:

- Core: dividend yield or defensive/income sector context
- Value: valuation score, low PE, or low PB
- Momentum: strong growth, strong momentum, volume expansion, or confirmed breakout

### Supporting evidence

Examples:

- quality score
- positive free cash flow
- low leverage
- relative strength below the defining threshold
- modest growth or breakout proximity

Quality, positive cash flow, and low debt alone do not create a `core_dividend` identity. Financial Services is not treated as defensive/income evidence by sector name alone.

## Status policy

```text
suggested             strong primary identity or a documented dominance rule
review                advisory ambiguity that Manager should resolve
conflict              two very strong defining identities are nearly identical
insufficient_evidence no bucket has enough identity evidence
```

Normal close scores now return `review`, not `conflict`. `conflict` is reserved for genuinely strong, near-equal bucket identities. This prevents Scanner's advisory uncertainty from blocking Manager before Fundamental and Technical evidence is available.

Only `suggested` emits a single item in `strategy_bucket_hints`. Review and conflict may expose multiple candidates for audit, but no primary hint is emitted.

## Dominance rules

Policy v3 may resolve narrow overlaps when evidence is explicit:

- `deep_value_without_income_dominance`
- `quality_income_dominance`
- `growth_momentum_dominance`

Dominance rules remain non-binding and are recorded in `bucket_hint_dominance_rule` and `bucket_hint_reasons`.

## Generic tag isolation

Typed bucket metadata is never copied into `ScannerCandidateContract.tags`.

This prevents strings such as:

```text
bucket-candidate:core_dividend
bucket-candidate:value_rebound
bucket-candidate:news_momentum
```

from being reinterpreted by Manager as separate human tag evidence. Existing business tags remain untouched.

## Growth normalization

Broad-universe sources may express small growth as percentage points, for example `1.1711` for 1.1711%. Policy v3 normalizes magnitudes above one before scoring so they are not mistaken for 117.11% growth.

## Safety properties

- No ticker-specific classification rules.
- No unknown bucket names.
- Watchlist and dev-fallback candidates do not receive fabricated primary hints.
- Scanner hints remain advisory.
- Manager classification, Risk approval, Execution validation, and Database persistence remain mandatory.

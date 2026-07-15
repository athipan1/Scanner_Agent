# Fundamental Discovery Reliability

This document records the Scanner coverage audit prompted by Hourly Auto Trading run `29429954262`.

## Observed production symptoms

The hourly report showed:

```text
selected_universe_count = 1000
analyzed_count = 42
error_count = 958
sp500_count = 0
nasdaq100_count = 0
```

The successful symbols were concentrated near the beginning of the alphabet. Walk-forward and execution gates behaved correctly, but Scanner coverage was too narrow to search the market effectively.

## Root causes

### Eager yfinance fallbacks

Financial statement helpers passed already-evaluated properties and method calls into a fallback selector. Python evaluated every fallback before the selector ran, even when the first source already contained data. A single symbol could therefore trigger many redundant Yahoo Finance requests.

The selector is now lazy and stops after the first non-empty statement.

### Duplicate market metadata requests

Financial statement retrieval already loaded `stock.info`, but market-data retrieval created another ticker and loaded the same metadata again. The existing information is now reused.

### One Alpaca client per symbol

The market-data function created a new Alpaca historical data client for every symbol. Scanner now reuses one cached client within the process.

### Overly strict optional valuation requirements

A symbol was rejected unless P/E, PEG and P/B were all present. PEG is legitimately absent for many companies. Scanner now requires:

- a positive current price
- at least one core valuation metric

Missing valuation metrics remain `None` and receive no valuation points. They are not imputed and do not receive free score.

### Alphabetical universe truncation

When Wikipedia sources failed, broad discovery used the alphabetically ordered NASDAQ-listed file and truncated the first 1,000 entries. This over-sampled symbols beginning with A and B.

The bounded universe now uses:

1. live S&P 500 and Nasdaq-100 symbols when available
2. deterministic large-cap fallbacks when either source is unavailable
3. a round-robin NASDAQ-listed fill across symbol initials

The ordering remains deterministic between runs.

## Provider pressure controls

Broad fundamental discovery caps provider concurrency at four workers, even when the caller requests more. Metadata reports both requested and effective worker counts.

This cap affects only data collection. It does not change candidate scoring, Manager thresholds, Backtest criteria, Walk-forward gates, Risk approval, or Execution behavior.

## Diagnostics contract

Discovery metadata now includes:

- `attempted_count`
- `analyzed_count`
- `error_count`
- `success_rate`
- `requested_max_workers`
- `effective_max_workers`
- `provider_worker_cap`
- `error_categories`
- `error_samples`
- `provider_pressure_detected`
- source fallback flags
- selected initial-letter coverage
- evidence coverage for top candidates
- valuation metric completeness for top candidates

Current error categories are:

```text
provider_rate_limited
provider_timeout
missing_financial_statements
missing_market_data
insufficient_scoring_evidence
non_tradable_symbol
analysis_error
```

## Safety properties

- Missing prices are still rejected.
- Symbols with zero valuation evidence are still rejected.
- Missing ratios are not imputed.
- Candidate score thresholds are unchanged.
- Backtest and Walk-forward thresholds are unchanged.
- No Scanner result can bypass Manager, Risk or Execution gates.

## Validation target

After merge, rerun Hourly Auto Trading and compare the new Scanner metadata with run `29429954262`.

The primary target is a materially higher `analyzed_count` and a lower error rate. If provider-pressure categories remain dominant, the next step should be a persistent data cache or batch fundamentals ingestion rather than loosening any trading gate.

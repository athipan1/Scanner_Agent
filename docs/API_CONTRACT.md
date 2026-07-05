# Scanner_Agent API Contract

This document defines the baseline API contract for `Scanner_Agent` in the multi-agent trading system.

`Scanner_Agent` discovers candidate symbols for downstream analysis. It should not make final trading decisions, approve risk, or submit orders.

## Standard Headers

```http
Content-Type: application/json
X-Correlation-ID: <uuid>
X-API-KEY: <scanner-agent-api-key>
```

## Standard Response Envelope

```json
{
  "status": "success",
  "agent_type": "scanner",
  "version": "1.0.0",
  "schema_version": "1.0",
  "timestamp": "2026-07-04T00:00:00Z",
  "correlation_id": "00000000-0000-0000-0000-000000000000",
  "data": {},
  "metadata": {},
  "error": null,
  "confidence_score": null
}
```

## Operational Endpoints

```http
GET /health
GET /ready
GET /version
```

## Discovery Endpoints

```http
POST /scan
POST /scan/fundamental
POST /discover-best-fundamentals
```

## Safety Rules

1. `Scanner_Agent` only discovers candidates.
2. `Scanner_Agent` must not approve risk or submit orders.
3. Dev fallback is forbidden in LIVE mode.
4. Watchlist fallback must be labeled clearly as non-trading-signal metadata.
5. Manager remains responsible for synthesis and orchestration.
6. Risk approval is required before execution.

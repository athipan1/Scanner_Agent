"""Production Scanner runtime with persistent discovery and adaptive backfill.

The FastAPI routes remain defined in ``app.main`` so API contracts stay unchanged.
This runtime keeps slow fundamental cache reuse isolated from live execution evidence,
widens only the candidate enrichment pool, retries stale regular-session quotes in a
bounded way, and lets strategy-specific opportunity evidence qualify candidates
without relaxing hard quote/spread safety.
"""

from app import main as _main
from app.services import production_enrichment as _production_enrichment
from app.services.adaptive_production_discovery import (
    adaptive_build_opportunity_profile,
    adaptive_get_market_snapshot,
    discover_best_fundamentals,
    reuse_pre_enriched_candidates,
)

# ``production_enrichment`` imported these functions into its module namespace.
# Replace those references only for the production cached runtime. The adaptive
# wrappers capture the original implementations before these assignments, so there
# is no recursion and the normal app.main module remains unchanged for unit tests.
_production_enrichment.build_opportunity_profile = adaptive_build_opportunity_profile
_production_enrichment.get_market_snapshot = adaptive_get_market_snapshot
_production_enrichment.enrich_fundamental_candidates_for_production = (
    reuse_pre_enriched_candidates
)

_main.discover_best_fundamentals = discover_best_fundamentals
app = _main.app

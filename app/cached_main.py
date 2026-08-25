"""Production Scanner runtime with cached broad fundamental discovery enabled by env.

The FastAPI routes remain defined in ``app.main`` so API contracts stay unchanged.
This module swaps only the broad-fundamental discovery callable used by that route.
The cached implementation itself is fail-safe and becomes a no-op cache when
SCANNER_FUNDAMENTAL_CACHE_ENABLED is not explicitly true.
"""

from app import main as _main
from app.services.cached_fundamental_discovery import discover_best_fundamentals

_main.discover_best_fundamentals = discover_best_fundamentals
app = _main.app

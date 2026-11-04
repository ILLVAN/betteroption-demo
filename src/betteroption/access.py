"""Product access defaults shared by result presentation and future subscriptions."""

from pydantic import Field

from .profile import StrictModel


DEFAULT_FREE_MATCH_RESULT_LIMIT = 25
DEFAULT_MAX_STORED_JOBS = 25
DEFAULT_EXACT_ROUTE_MATCH_LIMIT = 25


class ProductAccessPolicy(StrictModel):
    free_match_result_limit: int = Field(default=DEFAULT_FREE_MATCH_RESULT_LIMIT, ge=1)
    max_stored_jobs: int = Field(default=DEFAULT_MAX_STORED_JOBS, ge=1)
    exact_route_match_limit: int = Field(default=DEFAULT_EXACT_ROUTE_MATCH_LIMIT, ge=1, le=25)
    explore_exact_routing_enabled: bool = False

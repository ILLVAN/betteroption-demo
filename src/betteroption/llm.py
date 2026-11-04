"""Provider-neutral language-model contracts and routing policy."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from typing import TYPE_CHECKING, Literal, Protocol
from uuid import UUID, uuid4

from pydantic import Field

from .profile import StrictModel

if TYPE_CHECKING:
    from .extraction import SectionExtraction
    from .jobs import JobPosting
    from .profile import ProfileFact, ProfileSection


class ProfileExtractorPort(Protocol):
    model: str

    def extract(self, section: ProfileSection, user_text: str) -> SectionExtraction: ...


class JobExtractorPort(Protocol):
    model: str

    def extract(
        self,
        source_text: str,
        *,
        source_name: str,
        source_url: str,
        requested_url: str,
        url_http_status: int,
        url_checked_at: datetime,
    ) -> JobPosting: ...


class ApplicationDrafterPort(Protocol):
    model: str

    def draft(
        self,
        *,
        job: JobPosting,
        confirmed_facts: list[ProfileFact],
        action: Literal["create", "recreate", "longer", "shorter"],
        existing_text: str | None = None,
    ) -> str: ...


class LLMTask(StrEnum):
    PROFILE_EXTRACTION = "profile_extraction"
    JOB_EXTRACTION = "job_extraction"
    MATCH_EXPLANATION = "match_explanation"
    APPLICATION_DRAFT = "application_draft"
    SALARY_RESEARCH = "salary_research"


class InvocationOutcome(StrEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class ModelRoute(StrictModel):
    task: LLMTask
    provider: str
    model: str
    prompt_version: str
    input_cost_per_million_usd: float | None = Field(default=None, ge=0)
    output_cost_per_million_usd: float | None = Field(default=None, ge=0)


class ModelPolicy:
    """Select a provider/model route by task without leaking it into domain code."""

    def __init__(self, routes: list[ModelRoute] | tuple[ModelRoute, ...]) -> None:
        self._routes = {route.task: route for route in routes}
        if len(self._routes) != len(routes):
            raise ValueError("model policy contains duplicate task routes")

    def route(self, task: LLMTask) -> ModelRoute:
        try:
            return self._routes[task]
        except KeyError as exc:
            raise LookupError(f"no model route is configured for {task.value}") from exc


class TokenUsage(StrictModel):
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    total_tokens: int | None = Field(default=None, ge=0)


class ModelInvocation(StrictModel):
    id: UUID = Field(default_factory=uuid4)
    task: LLMTask
    provider: str
    model: str
    prompt_version: str
    attempt: int = Field(default=1, ge=1)
    outcome: InvocationOutcome
    started_at: datetime
    finished_at: datetime
    latency_ms: int = Field(ge=0)
    usage: TokenUsage = Field(default_factory=TokenUsage)
    estimated_cost_usd: float | None = Field(default=None, ge=0)
    error_type: str | None = None


class InvocationRecorder(Protocol):
    def record(self, invocation: ModelInvocation) -> None: ...


class InvocationBudgetAuthorizationError(RuntimeError):
    """An LLM attempt could not obtain its durable pre-call reservation."""


def reserve_model_invocation(
    recorder: InvocationRecorder,
    *,
    route: ModelRoute,
    started_at: datetime,
    request_payload: object,
    max_output_tokens: int,
    attempt: int = 1,
) -> UUID:
    """Reserve one real model attempt when the recorder supports authorization.

    The UTF-8 byte length is a conservative ceiling for tokenizer input units:
    a token cannot encode less than one byte. Non-database test recorders remain
    valid and simply skip deployment-budget authorization.
    """

    invocation_id = uuid4()
    authorize = getattr(recorder, "reserve", None)
    if not callable(authorize):
        return invocation_id
    try:
        allowed = authorize(
            invocation_id=invocation_id,
            route=route,
            attempt=attempt,
            started_at=started_at,
            input_token_ceiling=max(1, len(repr(request_payload).encode("utf-8"))),
            output_token_ceiling=max(1, int(max_output_tokens)),
        )
    except Exception as exc:
        raise InvocationBudgetAuthorizationError(
            "The provider budget authorization could not be stored; no OpenAI request was sent."
        ) from exc
    if not allowed:
        raise InvocationBudgetAuthorizationError(
            "The configured provider operation or cost limit was reached; no OpenAI request was sent."
        )
    return invocation_id


class NullInvocationRecorder:
    def record(self, invocation: ModelInvocation) -> None:
        del invocation


class InMemoryInvocationRecorder:
    def __init__(self) -> None:
        self.invocations: list[ModelInvocation] = []

    def record(self, invocation: ModelInvocation) -> None:
        self.invocations.append(invocation)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def token_usage_from_response(response: object) -> TokenUsage:
    """Read usage defensively because SDK and test response shapes can differ."""

    usage = getattr(response, "usage", None)
    if usage is None:
        return TokenUsage()
    input_tokens = getattr(usage, "input_tokens", None)
    output_tokens = getattr(usage, "output_tokens", None)
    total_tokens = getattr(usage, "total_tokens", None)
    if total_tokens is None and input_tokens is not None and output_tokens is not None:
        total_tokens = input_tokens + output_tokens
    return TokenUsage(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
    )


def estimate_cost(route: ModelRoute, usage: TokenUsage) -> float | None:
    if (
        route.input_cost_per_million_usd is None
        or route.output_cost_per_million_usd is None
        or route.input_cost_per_million_usd == 0
        or route.output_cost_per_million_usd == 0
    ):
        return None
    if usage.input_tokens is None or usage.output_tokens is None:
        return None
    return round(
        usage.input_tokens * route.input_cost_per_million_usd / 1_000_000
        + usage.output_tokens * route.output_cost_per_million_usd / 1_000_000,
        8,
    )

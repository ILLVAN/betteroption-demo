"""Provider adapter registry used by the application composition root."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from .llm import (
    ApplicationDrafterPort,
    InvocationRecorder,
    JobExtractorPort,
    LLMTask,
    ModelPolicy,
    ProfileExtractorPort,
)
from .match_evidence import MatchEvidenceResolverPort


ProfileProviderBuilder = Callable[..., ProfileExtractorPort]
JobProviderBuilder = Callable[..., JobExtractorPort]
ApplicationProviderBuilder = Callable[..., ApplicationDrafterPort]
MatchEvidenceProviderBuilder = Callable[..., MatchEvidenceResolverPort]


class ProviderRegistry:
    def __init__(self) -> None:
        self._profile_builders: dict[str, ProfileProviderBuilder] = {}
        self._job_builders: dict[str, JobProviderBuilder] = {}
        self._application_builders: dict[str, ApplicationProviderBuilder] = {}
        self._match_evidence_builders: dict[str, MatchEvidenceProviderBuilder] = {}

    def register_profile(self, provider: str, builder: ProfileProviderBuilder) -> None:
        self._profile_builders[provider.casefold()] = builder

    def register_job(self, provider: str, builder: JobProviderBuilder) -> None:
        self._job_builders[provider.casefold()] = builder

    def register_application(
        self,
        provider: str,
        builder: ApplicationProviderBuilder,
    ) -> None:
        self._application_builders[provider.casefold()] = builder

    def register_match_evidence(
        self,
        provider: str,
        builder: MatchEvidenceProviderBuilder,
    ) -> None:
        self._match_evidence_builders[provider.casefold()] = builder

    def build_profile(
        self,
        policy: ModelPolicy,
        recorder: InvocationRecorder,
        *,
        provider_options: dict[str, object] | None = None,
    ) -> ProfileExtractorPort:
        route = policy.route(LLMTask.PROFILE_EXTRACTION)
        builder = self._resolve(self._profile_builders, route.provider, LLMTask.PROFILE_EXTRACTION)
        return builder(route=route, recorder=recorder, **(provider_options or {}))

    def build_job(
        self,
        policy: ModelPolicy,
        recorder: InvocationRecorder,
        *,
        provider_options: dict[str, object] | None = None,
    ) -> JobExtractorPort:
        route = policy.route(LLMTask.JOB_EXTRACTION)
        builder = self._resolve(self._job_builders, route.provider, LLMTask.JOB_EXTRACTION)
        return builder(route=route, recorder=recorder, **(provider_options or {}))

    def build_application(
        self,
        policy: ModelPolicy,
        recorder: InvocationRecorder,
        *,
        provider_options: dict[str, object] | None = None,
    ) -> ApplicationDrafterPort:
        route = policy.route(LLMTask.APPLICATION_DRAFT)
        builder = self._resolve(
            self._application_builders,
            route.provider,
            LLMTask.APPLICATION_DRAFT,
        )
        return builder(route=route, recorder=recorder, **(provider_options or {}))

    def build_match_evidence(
        self,
        policy: ModelPolicy,
        recorder: InvocationRecorder,
        *,
        provider_options: dict[str, object] | None = None,
    ) -> MatchEvidenceResolverPort:
        route = policy.route(LLMTask.MATCH_EXPLANATION)
        builder = self._resolve(
            self._match_evidence_builders,
            route.provider,
            LLMTask.MATCH_EXPLANATION,
        )
        return builder(route=route, recorder=recorder, **(provider_options or {}))

    @staticmethod
    def _resolve(
        builders: dict[str, Any],
        provider: str,
        task: LLMTask,
    ) -> Any:
        try:
            return builders[provider.casefold()]
        except KeyError as exc:
            raise LookupError(f"provider {provider!r} is not registered for {task.value}") from exc


def default_provider_registry() -> ProviderRegistry:
    from .providers.openai import OpenAIProfileExtractor
    from .providers.openai_application import OpenAIApplicationDrafter
    from .providers.openai_job import OpenAIJobExtractor
    from .providers.openai_match_evidence import OpenAIMatchEvidenceResolver

    registry = ProviderRegistry()
    registry.register_profile(
        "openai",
        lambda *, route, recorder, api_key=None: OpenAIProfileExtractor(
            route=route,
            recorder=recorder,
            api_key=api_key,
        ),
    )
    registry.register_job(
        "openai",
        lambda *, route, recorder, api_key=None, application_guidance_enabled=True: (
            OpenAIJobExtractor(
                route=route,
                recorder=recorder,
                api_key=api_key,
                application_guidance_enabled=application_guidance_enabled,
            )
        ),
    )
    registry.register_application(
        "openai",
        lambda *, route, recorder, api_key=None, application_guidance_enabled=True: (
            OpenAIApplicationDrafter(
                route=route,
                recorder=recorder,
                api_key=api_key,
                application_guidance_enabled=application_guidance_enabled,
            )
        ),
    )
    registry.register_match_evidence(
        "openai",
        lambda *, route, recorder, api_key=None, max_jobs=25: OpenAIMatchEvidenceResolver(
            route=route,
            recorder=recorder,
            api_key=api_key,
            max_jobs=max_jobs,
        ),
    )
    return registry

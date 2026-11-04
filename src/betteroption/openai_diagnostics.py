"""Secret-safe manual OpenAI authentication and model-access check."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from openai import OpenAI

from .profile_workflow import safe_profile_extraction_diagnostic
from .settings import Settings


@dataclass(frozen=True)
class OpenAIDiagnostic:
    success: bool
    model: str
    message: str


def check_openai_model_access(
    settings: Settings,
    *,
    client: Any | None = None,
) -> OpenAIDiagnostic:
    """Check authentication and configured-model visibility without sending user text."""

    model = settings.profile_extraction_model or settings.openai_model
    api_key = settings.openai_api_key_value
    if not api_key:
        return OpenAIDiagnostic(
            success=False,
            model=model,
            message=safe_profile_extraction_diagnostic(None),
        )
    try:
        provider = client or OpenAI(api_key=api_key)
        provider.models.retrieve(model)
    except Exception as exc:
        return OpenAIDiagnostic(
            success=False,
            model=model,
            message=safe_profile_extraction_diagnostic(exc),
        )
    return OpenAIDiagnostic(
        success=True,
        model=model,
        message=(
            "OpenAI authentication succeeded and the configured profile model is accessible. "
            "No Compass or CV text was sent."
        ),
    )

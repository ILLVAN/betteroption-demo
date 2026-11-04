"""Action-aware, conservative integrity checks for one active Compass.

The report is deliberately deterministic.  It never calls a provider while a
page is being opened, and it distinguishes a Compass that needs a decision from
one that is merely broad or unfinished.  Page and POST handlers consume the
same capability flags so the UI cannot promise an action the server will run.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import re
import unicodedata
from uuid import UUID

from .profile import CandidateProfile, ProfileFact, ProfileSection, RequirementLevel
from .profile_consistency import ProfileConsistencyIssue, inspect_profile_consistency
from .session import ProfileSession, SectionStatus


class CompassIntegritySeverity(StrEnum):
    BLOCKING = "blocking"
    WARNING = "warning"
    INFO = "info"


class CompassAction(StrEnum):
    ADD = "add"
    EXPLORE_MANUAL = "explore_manual"
    EXPLORE_COMPASS = "explore_compass"
    MATCH = "match"
    APPLY_NEW = "apply_new"
    ARCHIVE = "archive"


_SEARCH_CONSUMERS = frozenset(
    {
        CompassAction.EXPLORE_COMPASS,
        CompassAction.MATCH,
        CompassAction.APPLY_NEW,
    }
)


@dataclass(frozen=True, slots=True)
class CompassIntegrityIssue:
    code: str
    severity: CompassIntegritySeverity
    title: str
    explanation: str
    statements: tuple[str, ...] = ()
    fact_ids: tuple[UUID, ...] = ()
    section: ProfileSection | None = None
    blocked_actions: frozenset[CompassAction] = frozenset()
    suggest_second_persona: bool = False


@dataclass(frozen=True, slots=True)
class CompassIntegrityReport:
    issues: tuple[CompassIntegrityIssue, ...]

    @property
    def blocking_issues(self) -> tuple[CompassIntegrityIssue, ...]:
        return tuple(
            issue for issue in self.issues if issue.severity == CompassIntegritySeverity.BLOCKING
        )

    def allows(self, action: CompassAction) -> bool:
        return not any(action in issue.blocked_actions for issue in self.issues)

    def primary_issue(self, action: CompassAction | None = None) -> CompassIntegrityIssue | None:
        if not self.issues:
            return None
        ranked = sorted(
            self.issues,
            key=lambda issue: (
                0 if action is not None and action in issue.blocked_actions else 1,
                {
                    CompassIntegritySeverity.BLOCKING: 0,
                    CompassIntegritySeverity.WARNING: 1,
                    CompassIntegritySeverity.INFO: 2,
                }[issue.severity],
                issue.code,
            ),
        )
        return ranked[0]

    def blocked_reason(self, action: CompassAction) -> str | None:
        issue = next(
            (candidate for candidate in self.issues if action in candidate.blocked_actions),
            None,
        )
        if issue is None:
            return None
        return f"{issue.title}. {issue.explanation}"


_SEARCH_DIRECTION_KEYS = {
    "role.family",
    "role.responsibility",
    "career.direction",
    "industry.sector",
    "skill.desired",
    "skill.name",
}


def _plain(value: object) -> str:
    material = unicodedata.normalize("NFKD", str(value).casefold())
    material = "".join(character for character in material if not unicodedata.combining(character))
    return " ".join(re.findall(r"[a-z0-9]+", material))


def _mentions_remote_only(fact: ProfileFact) -> bool:
    text = _plain(f"{fact.key} {fact.value}")
    return any(
        marker in text
        for marker in (
            "fully remote",
            "remote only",
            "100 remote",
            "only remote",
            "vollstandig remote",
            "nur remote",
        )
    )


def _mentions_onsite_only(fact: ProfileFact) -> bool:
    text = _plain(f"{fact.key} {fact.value}")
    return any(
        marker in text
        for marker in (
            "fully onsite",
            "fully on site",
            "on site only",
            "onsite only",
            "office only",
            "only onsite",
            "nur vor ort",
            "vollstandig vor ort",
            "nur im buro",
        )
    )


def _issue_section(
    issue: ProfileConsistencyIssue,
    facts_by_id: dict[UUID, ProfileFact],
) -> ProfileSection | None:
    return next(
        (
            facts_by_id[fact_id].source.section
            for fact_id in issue.fact_ids
            if fact_id in facts_by_id
        ),
        None,
    )


def _from_consistency_issue(
    issue: ProfileConsistencyIssue,
    facts_by_id: dict[UUID, ProfileFact],
) -> CompassIntegrityIssue:
    facts = [facts_by_id[fact_id] for fact_id in issue.fact_ids if fact_id in facts_by_id]
    section = _issue_section(issue, facts_by_id)

    if issue.code.startswith("opposite-level:"):
        return CompassIntegrityIssue(
            code=issue.code,
            severity=CompassIntegritySeverity.BLOCKING,
            title="The same condition is both wanted and excluded",
            explanation=(
                "Choose which statement should guide this persona before using the whole "
                "Compass for search, Matching, or a new application draft."
            ),
            statements=issue.statements,
            fact_ids=issue.fact_ids,
            section=section,
            blocked_actions=_SEARCH_CONSUMERS,
        )

    if issue.code.startswith("incompatible-bounds:"):
        return CompassIntegrityIssue(
            code=issue.code,
            severity=CompassIntegritySeverity.BLOCKING,
            title="Two numeric boundaries cannot both be satisfied",
            explanation=(
                "Choose the active minimum or maximum that should guide this persona before "
                "using the whole Compass for search, Matching, or a new application draft."
            ),
            statements=issue.statements,
            fact_ids=issue.fact_ids,
            section=section,
            blocked_actions=_SEARCH_CONSUMERS,
        )

    if issue.code == "workplace-extremes":
        remote_hard = any(
            _mentions_remote_only(fact)
            and fact.level in {RequirementLevel.MUST_HAVE, RequirementLevel.EXCLUSION}
            for fact in facts
        )
        onsite_hard = any(
            _mentions_onsite_only(fact)
            and fact.level in {RequirementLevel.MUST_HAVE, RequirementLevel.EXCLUSION}
            for fact in facts
        )
        blocking = remote_hard and onsite_hard
        return CompassIntegrityIssue(
            code=issue.code,
            severity=(
                CompassIntegritySeverity.BLOCKING if blocking else CompassIntegritySeverity.WARNING
            ),
            title=(
                "Remote-only and on-site-only boundaries cannot guide one search"
                if blocking
                else "Remote-only and on-site-only directions are both active"
            ),
            explanation=(
                "Choose one boundary, or keep the directions in separate personas."
                if blocking
                else "You can keep the breadth, though separate personas usually produce cleaner results."
            ),
            statements=issue.statements,
            fact_ids=issue.fact_ids,
            section=section,
            blocked_actions=_SEARCH_CONSUMERS if blocking else frozenset(),
            suggest_second_persona=True,
        )

    if issue.code == "seniority-extremes":
        return CompassIntegrityIssue(
            code=issue.code,
            severity=CompassIntegritySeverity.WARNING,
            title="This Compass may contain two career-level searches",
            explanation=(
                "Junior and senior targets can stay together, but a second persona will usually "
                "make discovery and ranking easier to read."
            ),
            statements=issue.statements,
            fact_ids=issue.fact_ids,
            section=section,
            suggest_second_persona=True,
        )

    if issue.code == "conflicting-mobility-origins":
        return CompassIntegrityIssue(
            code=issue.code,
            severity=CompassIntegritySeverity.WARNING,
            title="This Compass has distant starting points",
            explanation=(
                "Keep them only when they are real alternatives. A second persona gives each "
                "location its own route evidence."
            ),
            statements=issue.statements,
            fact_ids=issue.fact_ids,
            section=ProfileSection.LOCATION_MOBILITY,
            suggest_second_persona=True,
        )

    return CompassIntegrityIssue(
        code=issue.code,
        severity=CompassIntegritySeverity.INFO,
        title=issue.title,
        explanation=issue.explanation,
        statements=issue.statements,
        fact_ids=issue.fact_ids,
        section=section,
    )


def inspect_compass_integrity(session: ProfileSession | None) -> CompassIntegrityReport:
    """Build one report for UI hints and server-side action decisions."""

    if session is None:
        return CompassIntegrityReport(
            issues=(
                CompassIntegrityIssue(
                    code="missing-compass",
                    severity=CompassIntegritySeverity.BLOCKING,
                    title="Start a Compass before using Compass-based actions",
                    explanation=(
                        "Guided setup creates the search direction used by Explore, Matching, "
                        "and new application drafts."
                    ),
                    section=ProfileSection.DIRECTION,
                    blocked_actions=_SEARCH_CONSUMERS,
                ),
            )
        )

    profile: CandidateProfile = session.profile
    facts = profile.confirmed_facts
    facts_by_id = {fact.id: fact for fact in facts}
    issues = [
        _from_consistency_issue(issue, facts_by_id)
        for issue in inspect_profile_consistency(profile)
    ]

    active_search_facts = [
        fact for fact in profile.confirmed_search_facts if fact.level != RequirementLevel.OPEN
    ]
    if not active_search_facts:
        issues.append(
            CompassIntegrityIssue(
                code="missing-match-criteria",
                severity=CompassIntegritySeverity.BLOCKING,
                title="Add one active search criterion",
                explanation=(
                    "Confirm a preference, must-have, or exclusion before Matching or creating "
                    "a new application draft."
                ),
                section=ProfileSection.DIRECTION,
                blocked_actions=frozenset({CompassAction.MATCH, CompassAction.APPLY_NEW}),
            )
        )

    has_search_direction = any(
        fact.key in _SEARCH_DIRECTION_KEYS
        and fact.level != RequirementLevel.EXCLUSION
        and str(fact.value).strip()
        for fact in profile.confirmed_search_facts
    )
    if not has_search_direction:
        issues.append(
            CompassIntegrityIssue(
                code="missing-search-direction",
                severity=CompassIntegritySeverity.BLOCKING,
                title="Add one role, responsibility, industry, or desired skill",
                explanation=(
                    "Explore needs one concrete direction before it can search from this Compass. "
                    "You can still use your own phrase in Explore."
                ),
                section=ProfileSection.DIRECTION,
                blocked_actions=frozenset({CompassAction.EXPLORE_COMPASS}),
            )
        )

    skipped = [
        progress for progress in session.sections if progress.status == SectionStatus.SKIPPED
    ]
    open_questions = [
        progress
        for progress in session.sections
        if progress.follow_up_question
        and progress.follow_up_question in profile.unresolved_questions
    ]
    if skipped or open_questions:
        count = len(skipped) + len(open_questions)
        section = (skipped or open_questions)[0].section
        issues.append(
            CompassIntegrityIssue(
                code="guided-points-open",
                severity=CompassIntegritySeverity.INFO,
                title=f"{count} guided point{'s are' if count != 1 else ' is'} still open",
                explanation=(
                    "Only confirmed statements guide search and matching. The open points stay "
                    "visible for your next Guided Setup review."
                ),
                section=section,
            )
        )

    unique: dict[str, CompassIntegrityIssue] = {}
    for issue in issues:
        unique.setdefault(issue.code, issue)
    return CompassIntegrityReport(issues=tuple(unique.values()))


def integrity_report_for_profile(profile: CandidateProfile) -> CompassIntegrityReport:
    """Compatibility helper for domain callers that do not own session progress."""

    from .session import new_session

    session = new_session()
    session.profile = profile
    return inspect_compass_integrity(session)

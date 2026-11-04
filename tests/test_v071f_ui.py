from pathlib import Path


STATIC = Path("src/betteroption/web/static")
TEMPLATES = Path("src/betteroption/web/templates")


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_apply_picker_has_a_stable_responsive_two_column_contract() -> None:
    template = read(TEMPLATES / "apply.html")
    css = read(STATIC / "app.css")

    assert 'class="apply-candidate-copy"' in template
    assert "grid-template-columns: 1.2rem minmax(0, 1fr);" in css
    assert ".apply-candidate input {" in css
    assert "width: 1.1rem;" in css
    assert "@media (max-width: 520px)" in css


def test_job_detail_keeps_cover_letter_creation_separate_from_state_tracking() -> None:
    template = read(TEMPLATES / "job_detail.html")

    draft_panel = template.index('class="panel application-draft-launcher"')
    state_panel = template.index('class="panel application-state-panel"')
    assert draft_panel < state_panel
    assert "Application materials" in template[draft_panel:state_panel]
    assert "Create cover letter" in template[draft_panel:state_panel]
    assert "Current state" not in template[draft_panel:state_panel]
    assert "Current state" in template[state_panel:]


def test_primary_navigation_places_add_before_explore() -> None:
    template = read(TEMPLATES / "base.html")

    assert template.index(">Add</a>") < template.index(">Explore</a>")


def test_job_detail_progressively_discloses_long_evidence_and_compacts_controls() -> None:
    template = read(TEMPLATES / "job_detail.html")
    css = read(STATIC / "app.css")

    assert template.count('class="evidence-details"') >= 6
    assert "Explanation, evidence and sources" in template
    assert "Route assumptions, samples and provider details" in template
    assert 'id="required-skills"' in template
    assert "Also update my Compass from skill changes" in template
    assert "skill-comparison {{ 'satisfied' if effective_matched else 'unknown' }}" in template
    assert ".evidence-inline-form .secondary-button" in css
    assert ".skill-compass-bulk-option" in css
    assert 'name="postal_address"' in template
    assert "application_guidance.postal_address" in template
    assert "Your private employer context<input" in template
    assert "<label>{{ label }}<input" in template
    assert "label == 'Product summary'" not in template


def test_ended_card_pattern_preserves_content_and_updates_optimistically() -> None:
    css = read(STATIC / "app.css")
    script = read(STATIC / "app.js")
    opportunity = read(TEMPLATES / "opportunity_card.html")
    result = read(TEMPLATES / "result_card.html")

    ended_selector = (
        '[data-application-state-card="rejected"], [data-application-state-card="withdrawn"]'
    )
    assert ended_selector in css
    ended_rule = css.split(ended_selector, 1)[1].split("}", 1)[0]
    assert "repeating-linear-gradient" in ended_rule
    assert "opacity:" not in ended_rule
    # Every card now has one semantic article wrapper so its rating buttons can
    # sit beside, rather than inside, the destination link.
    assert opportunity.count("data-application-state-card") == 1
    assert result.count("data-application-state-card") == 1
    assert 'class="card-body-link card-link"' in opportunity
    assert 'class="card-body-link card-link"' in result

    optimistic_update = "card.dataset.applicationStateCard = select.value;"
    rollback = "card.dataset.applicationStateCard = previous;"
    state_handler = script.split(
        'for (const select of document.querySelectorAll("[data-application-state]"))',
        1,
    )[1].split(
        'for (const control of document.querySelectorAll("[data-job-rating-control]"))',
        1,
    )[0]
    assert state_handler.index(optimistic_update) < state_handler.index("await fetch")
    assert rollback in state_handler


def test_application_state_watermarks_are_larger_clearer_and_clear_of_card_controls() -> None:
    css = read(STATIC / "app.css")
    watermark_rule = css.split("[data-application-state-card]::after", 1)[1].split("}", 1)[0]

    assert "bottom: 34%" in watermark_rule
    assert "clamp(5.2rem,9vw,8rem)" in watermark_rule
    assert "opacity: .075" in watermark_rule


def test_job_and_employer_ratings_remain_visually_distinct_and_accessible() -> None:
    css = read(STATIC / "app.css")
    script = read(STATIC / "app.js")
    rating = read(TEMPLATES / "job_rating_control.html")

    assert ".job-star-button.is-active { color: var(--teal); }" in css
    assert ".employer-star-rating .star-rating-button.is-active { color: #76529a; }" in css
    assert "#d69b1b" not in css
    assert "0 of 5 job stars; strongest compatibility reduction" in rating
    assert "private to this persona" in rating
    assert "data-job-rating-control" in script
    assert "data-employer-rating-control" in script
    assert "saved.score_updates" in script
    assert "saved.match_layout" in script
    assert "saved.opportunity_layout" in script
    assert "syncRatingControls(kind, saved.rating_record_ids, savedStars);" in script
    assert "data-rating-record-id" in rating
    assert "Apply it to this Match" not in rating
    assert 'headers: { Accept: "application/json" }' in script


def test_job_cards_pair_job_and_employer_ratings_and_use_short_age_badges() -> None:
    opportunity = read(TEMPLATES / "opportunity_card.html")
    result = read(TEMPLATES / "result_card.html")
    rating = read(TEMPLATES / "job_rating_control.html")
    css = read(STATIC / "app.css")

    for template in (opportunity, result):
        assert "employer_ratings_by_record" in template
        assert "employer_rating_available_by_record" in template
        assert "> Fresh</span>" in template
        assert "> Old</span>" in template
        assert "Old posting" not in template
    assert "Your ratings" in rating
    assert "'Job' if compact_include_employer" in rating
    assert ">Employer</span>" in rating
    assert "0 of 5 employer stars; strongest compatibility reduction" in rating
    assert ".compact-ratings.has-employer-rating" in css
    assert ".posting-age-badge.fresh" in css
    assert 'data-match-record-id="{{ item.record.id }}"' in result
    assert "data-match-score" in result


def test_score_explanation_uses_plain_language_with_traceable_rules() -> None:
    template = read(TEMPLATES / "job_detail.html")

    assert "How this compatibility score is calculated" in template
    assert "Starting point:" in template
    assert "Evidence coverage" in template
    assert "The point rules are fixed and published" in template
    assert " base</strong>" not in template
    assert "evidence-confidence multiplier" not in template
    assert "positive adjustment capacity" not in template


def test_home_carousel_stacks_each_rating_label_above_its_star_controls() -> None:
    css = read(STATIC / "app.css")

    assert ".opportunity-carousel .compact-job-rating," in css
    assert ".opportunity-carousel .compact-employer-rating {\n  display: grid;" in css
    assert "grid-template-columns: minmax(0, 1fr) auto;" in css
    assert ".opportunity-carousel .compact-rating-label," in css
    assert ".opportunity-carousel .compact-star-buttons { grid-column: 1; grid-row: 2; }" in css


def test_salary_sources_and_currency_conversion_are_visible_and_clickable() -> None:
    template = read(TEMPLATES / "job_detail.html")

    assert 'class="salary-source-list"' in template
    assert "evidence.source_currency" in template
    assert "evidence.source_period.value" in template
    assert 'href="{{ evidence.source_url }}"' in template
    assert 'href="{{ evidence.exchange_source_url }}"' in template
    assert "ECB conversion evidence" in template
    assert "{% else %}" in template
    assert 'href="{{ automatic_salary.source_url }}"' in template

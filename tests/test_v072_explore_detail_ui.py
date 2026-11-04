from pathlib import Path

from jinja2 import Environment


STATIC = Path("src/betteroption/web/static")
TEMPLATES = Path("src/betteroption/web/templates")


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_explore_uses_native_disclosures_for_secondary_controls_and_source_facts() -> None:
    template = read(TEMPLATES / "explore.html")

    assert template.count("explore-control-disclosure") == 2
    assert "<summary>Filters</summary>" in template
    assert "<summary>Info</summary>" in template
    info = template.split("<summary>Info</summary>", 1)[1].split("</details>", 1)[0]
    assert "This query came from your confirmed role" in info
    assert 'class="explore-control-disclosure explore-info-disclosure"' in template
    assert "Cost guard:" not in template
    assert "Source mesh:" not in template

    assert '<details class="panel explore-source-disclosure">' in template
    source_disclosure = template.split('<details class="panel explore-source-disclosure">', 1)[
        1
    ].split("</details>", 1)[0]
    assert "What the last source run contributed" in source_disclosure
    assert 'class="readiness-list"' in source_disclosure
    assert "data-provider-filter-all" in source_disclosure
    assert "data-provider-filter" in source_disclosure
    assert "item.filterable" in source_disclosure


def test_explore_results_are_compact_rows_and_portal_links_are_collapsed() -> None:
    template = read(TEMPLATES / "explore.html")
    css = read(STATIC / "app.css")

    assert '<details class="portal-links-disclosure">' in template
    portal_links = template.split('<details class="portal-links-disclosure">', 1)[1].split(
        "</details>", 1
    )[0]
    assert "<summary>Portal Links</summary>" in portal_links
    assert "provider_attributions" in portal_links

    assert 'class="explore-grid explore-results-list"' in template
    assert 'class="panel explore-card explore-result-row"' in template
    assert 'class="explore-result-primary"' in template
    assert 'class="explore-result-evidence"' in template
    assert 'class="explore-result-context"' in template
    assert "{{ job.location }}" in template
    assert "job.search_score" in template
    assert "job.compass_relevance" in template
    assert "job.seniority_relevance" in template
    assert "job.distance_km" in template
    assert "job.exclusion_signals" in template
    assert "explore-exclusion-badge" in template
    assert "Compass conflict:" in template
    assert "job.summary" in template
    assert "job.tags" in template
    assert "job.published_at" in template
    assert "Inspect source" in template
    assert "job.effective_source_providers|join('|')" in template
    assert "job.source_readiness.value" in template
    assert 'class="explore-provider-badge"' in template
    assert "Source checked" in template
    assert "Verify on save" in template
    assert "Needs pasted text" in template
    assert "explore_hidden_source_tags" in template
    assert "tag.startswith('Source:')" in template
    assert "tag.startswith('Published via ')" in template
    metadata = template.split('class="explore-result-meta"', 1)[1].split(
        'class="explore-result-title"', 1
    )[0]
    assert "discovery-source" not in metadata

    assert ".explore-results-list {" in css
    assert ".explore-results-list .explore-result-row {" in css
    assert ".explore-result-primary {" in css
    assert ".explore-result-evidence {" in css
    assert ".explore-result-context {" in css
    assert ".explore-provider-badge {" in css
    assert ".explore-provider-master" in css


def test_route_duration_leads_with_one_value_and_keeps_range_secondary() -> None:
    job_detail = read(TEMPLATES / "job_detail.html")
    match_detail = read(TEMPLATES / "match_detail.html")
    css = read(STATIC / "app.css")

    for template in (job_detail, match_detail):
        # Job Detail may append the override-only original-value marker while
        # retaining the route-duration base class at render time.
        assert 'class="route-duration' in template
        assert 'class="route-duration-range"' in template
        assert "Range {{ commute.estimate.duration_low_minutes|duration }}" in template
        assert "median" not in template.lower()
        assert template.index("commute.estimate.duration_minutes|duration") < template.index(
            'class="route-duration-range"'
        )

    assert ".route-duration-range {" in css
    range_rule = css.split(".route-duration-range {", 1)[1].split("}", 1)[0]
    assert "color: var(--ink-soft);" in range_rule
    assert "font-size: 0.7rem;" in range_rule


def test_employer_relationship_editor_has_a_scoped_readable_layout() -> None:
    template = read(TEMPLATES / "job_detail.html")
    css = read(STATIC / "app.css")

    assert "employer-relationship-comparison" in template
    assert "Multiple types can apply." not in template
    assert ".employer-relationship-comparison {" in css
    assert ".employer-relationship-comparison .evidence-user[data-evidence-edit]" in css
    assert ".employer-relationship-comparison .evidence-column-label b" in css
    assert (
        "white-space: nowrap;"
        in css.split(".employer-relationship-comparison .evidence-column-label b", 1)[1].split(
            "}", 1
        )[0]
    )


def test_changed_web_templates_remain_valid_jinja() -> None:
    environment = Environment()

    for name in ("explore.html", "job_detail.html", "match_detail.html"):
        environment.parse(read(TEMPLATES / name))

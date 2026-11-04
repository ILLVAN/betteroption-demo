from pathlib import Path


ROOT = Path(__file__).parents[1]
TEMPLATES = ROOT / "src/betteroption/web/templates"
STATIC = ROOT / "src/betteroption/web/static"
PACKAGE = ROOT / "src/betteroption"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_explore_uses_known_dates_for_fresh_or_older_badges_only() -> None:
    template = read(TEMPLATES / "explore.html")
    javascript = read(STATIC / "app.js")
    discovery = read(PACKAGE / "discovery.py")
    sources = read(PACKAGE / "discovery_sources.py")
    web_app = read(PACKAGE / "web/app.py")

    assert "data-explore-published-at" in template
    dated_badge = template.split("data-explore-published-at", 1)[0].rsplit(
        "{% if job.published_at %}", 1
    )[1]
    assert "explore-posting-age-badge" in dated_badge
    assert 'badge.textContent = fresh ? "Fresh" : "Older";' in javascript
    assert "if (!published || published > todayUtc) continue;" in javascript
    assert "explore_hidden_source_tags" in template
    assert '"Web discovery"' in web_app
    assert '"Semantic web fallback"' in web_app
    assert 'tags = ["Web discovery",' not in discovery
    assert 'tags = ["Web discovery",' not in sources
    assert 'tags = ["Semantic web fallback",' not in sources


def test_footer_is_one_short_internal_only_line() -> None:
    template = read(TEMPLATES / "base.html")
    footer = template.split('<footer class="site-footer">', 1)[1].split("</footer>", 1)[0]

    assert footer.count("<span>") == 1
    assert "Private workspace" in footer
    assert "http://" not in footer
    assert "https://" not in footer
    assert "<br" not in footer
    assert "GeoNames" not in footer
    assert "OpenStreetMap" not in footer

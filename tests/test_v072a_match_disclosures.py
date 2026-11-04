from pathlib import Path

from bs4 import BeautifulSoup
from jinja2 import Environment


STATIC = Path("src/betteroption/web/static")
TEMPLATES = Path("src/betteroption/web/templates")


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_match_run_context_is_grouped_into_closed_native_disclosures() -> None:
    template = read(TEMPLATES / "matches.html")
    soup = BeautifulSoup(template, "html.parser")

    info = soup.select_one("details.match-info-disclosure")
    facts = soup.select_one("details.match-run-facts-disclosure")

    assert info is not None and not info.has_attr("open")
    assert facts is not None and not facts.has_attr("open")
    assert info.find("summary").find("strong").get_text(strip=True) == "Info"
    assert facts.find("summary").find("strong").get_text(strip=True) == "Run facts"
    assert "How matching works and the state of this saved result set" in info.get_text(" ")
    assert "Your compass changed after this result set was created" in info.get_text(" ")
    assert "This result set uses an earlier evidence model" in info.get_text(" ")
    assert "provider operations" in facts.get_text(" ")
    assert "Estimated provider cost" in facts.get_text(" ")


def test_match_delete_controls_are_folded_accessible_and_safe_by_default() -> None:
    template = read(TEMPLATES / "matches.html")
    soup = BeautifulSoup(template, "html.parser")
    form = soup.select_one("form[data-selection-form][data-delete-confirm]")

    assert form is not None
    disclosure = form.select_one("details.match-delete-disclosure")
    assert disclosure is not None and not disclosure.has_attr("open")
    assert disclosure.find("summary").find("strong").get_text(strip=True) == (
        "Select jobs to delete"
    )

    count = disclosure.select_one("summary [data-selection-count]")
    assert count is not None
    assert count.get("role") == "status"
    assert count.get("aria-live") == "polite"
    assert count.get("aria-atomic") == "true"

    select_all = disclosure.select_one('input[type="checkbox"][data-select-all]')
    assert select_all is not None
    assert select_all.get("aria-describedby") == "match-delete-help"
    assert disclosure.select_one("#match-delete-help") is not None

    delete = disclosure.select_one('button.danger-button[type="submit"]')
    assert delete is not None and delete.has_attr("disabled")
    assert "Delete selected and free slots" in delete.get_text(" ", strip=True)


def test_match_disclosures_have_compact_responsive_scoped_styles() -> None:
    css = read(STATIC / "app.css")

    assert ".match-run-disclosures {" in css
    assert ".match-top-disclosure > summary," in css
    assert ".match-delete-disclosure > summary {" in css
    assert "min-height: 3.5rem;" in css
    assert ".match-delete-disclosure-body {" in css
    assert "@media (max-width: 650px)" in css
    assert ".explore-control-disclosure" in css


def test_changed_match_template_remains_valid_jinja() -> None:
    Environment().parse(read(TEMPLATES / "matches.html"))

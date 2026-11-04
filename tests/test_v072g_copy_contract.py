from __future__ import annotations

from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]


def _array_strings(source: str, name: str) -> list[str]:
    block = source.split(f"const {name} = [", 1)[1].split("];", 1)[0]
    return re.findall(r'^\s*"([^"]*)",?$', block, flags=re.MULTILINE)


def test_waiting_copy_is_slow_single_line_and_single_sentence() -> None:
    source = (ROOT / "src/betteroption/web/static/task_progress.js").read_text(encoding="utf-8")
    phrases = [
        *_array_strings(source, "COMMON_WAITING_COPY"),
        *_array_strings(source, "EXPLORE_WAITING_COPY"),
        *_array_strings(source, "MATCH_WAITING_COPY"),
    ]

    assert len(phrases) >= 100
    assert "24000 + Math.floor(randomUnit() * 60001)" in source
    for phrase in phrases:
        assert ";" not in phrase
        assert "\n" not in phrase and "\r" not in phrase
        assert "thorough" not in phrase.casefold()
        assert len(re.findall(r"[.!?](?=\s|$)", phrase)) <= 1, phrase


def test_candidate_ui_uses_only_the_worklifebalance_name() -> None:
    template_root = ROOT / "src/betteroption/web/templates"
    operator_only_templates = {"operations.html"}
    offenders = [
        path.relative_to(ROOT)
        for path in template_root.rglob("*.html")
        if path.name not in operator_only_templates
        and "betteroption"
        in re.sub(
            r"{[%{].*?[}%]}",
            "",
            path.read_text(encoding="utf-8"),
            flags=re.DOTALL,
        ).casefold()
    ]
    assert offenders == []

    app_source = (ROOT / "src/betteroption/web/app.py").read_text(encoding="utf-8")
    account_source = (ROOT / "src/betteroption/accounts.py").read_text(encoding="utf-8")
    assert 'filename="worklifebalance-profile-export.json"' in app_source
    assert '"format": "worklifebalance-portable-profile-v1"' in account_source
    assert 'AUTH_COOKIE = "betteroption_session"' in app_source


def test_explore_badge_labels_are_candidate_friendly() -> None:
    source = (ROOT / "src/betteroption/web/app.py").read_text(encoding="utf-8")
    labels = source.split("EXPLORE_PROVIDER_LABELS", 1)[1].split("}", 1)[0]

    assert '"betteroption-posted": "Own"' in labels
    assert "scrap" not in labels.casefold()

"""A second hard-coded industry list silently drifts from the catalog (see migration 071)."""
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
_ID = r"(?:restaurant|clinic|tuition_center|general)"
_SEP = r"[\"'\s,|\[\]]+"
HARD_CODED_LIST = re.compile(_ID + _SEP + _ID + _SEP + _ID)


def test_guard_pattern_catches_a_json_schema_enum():
    assert HARD_CODED_LIST.search('{"enum": ["restaurant", "clinic", "tuition_center", "general", None]}')
    assert not HARD_CODED_LIST.search("booking includes restaurant reservations, clinic appointments")


def test_industry_ids_are_listed_only_in_the_catalog():
    offenders = [
        path.relative_to(ROOT).as_posix()
        for path in (ROOT / "app").rglob("*.py")
        if path.name != "industry_template_catalog.py"
        and HARD_CODED_LIST.search(path.read_text(encoding="utf-8"))
    ]
    assert offenders == [], "Build industry lists from industry_template_catalog.template_ids(): " + ", ".join(offenders)

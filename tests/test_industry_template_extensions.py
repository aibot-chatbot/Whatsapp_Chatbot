"""Data-only industry templates added by industry-template-mcp PRs (app/services/industry_templates/)."""
import json
import logging

import pytest

from app.services import industry_template_catalog as catalog
from app.services.industry_template_catalog import (
    EXTENSION_DIR,
    load_extensions,
    merge_extensions,
    template_ids,
    validate_extension,
)

VALID_TEMPLATE = {
    "id": "dental_clinic",
    "version": "1.0.0",
    "name": "Dental clinic",
    "description": "Answer dental service, price and appointment policy questions.",
    "questions": ["Which branch are you asking about?", "Which dental service do you need?"],
    "required_information": ["Clinic name and branches", "Dental services and prices"],
    "unavailable_actions": ["Booking or changing appointments", "Diagnosis or treatment advice"],
    "classification_hint": "Needs dental services such as scaling, fillings, braces or dentures.",
    "lead_rule": "The customer wants a dental appointment or a treatment quotation.",
}
VALID_RULES = ("Dental clinic: answer supported questions about published dental services, prices and "
               "policies. Do not diagnose, give treatment advice or confirm appointment slots.")
VALID_SAMPLES = ["Our dental clinic offers scaling and braces.",
                 "Klinik gigi kami menawarkan cabutan dan pendakap.",
                 "本牙科诊所提供洗牙和矫正服务。"]


def write_extension(directory, file_id="dental_clinic", template=None, rules=VALID_RULES, samples=None):
    body = (f'"""Industry template: {file_id}. Data only."""\n'
            f"TEMPLATE = {json.dumps(template or VALID_TEMPLATE, ensure_ascii=False, indent=4)}\n"
            f"RULES = {json.dumps(rules, ensure_ascii=False)}\n"
            f"SAMPLES = {json.dumps(samples or VALID_SAMPLES, ensure_ascii=False)}\n")
    (directory / f"{file_id}.py").write_text(body, encoding="utf-8")


def test_loader_reads_a_data_only_file(tmp_path):
    write_extension(tmp_path)
    [(template, rules, samples)] = load_extensions(tmp_path)
    assert template == VALID_TEMPLATE and rules == VALID_RULES and samples == VALID_SAMPLES


def test_missing_directory_means_no_extensions(tmp_path):
    assert load_extensions(tmp_path / "absent") == []


def test_runtime_loading_skips_a_broken_file_and_keeps_the_rest(tmp_path, caplog):
    write_extension(tmp_path)
    (tmp_path / "broken_one.py").write_text("import os\n", encoding="utf-8")
    (tmp_path / "not_a_file.py").mkdir()
    with caplog.at_level(logging.ERROR):
        found = load_extensions(tmp_path, strict=False)
    assert [template["id"] for template, _rules, _samples in found] == ["dental_clinic"]
    assert "broken_one.py" in caplog.text and "not_a_file.py" in caplog.text


def test_strict_loading_fails_on_a_broken_file(tmp_path):
    write_extension(tmp_path)
    (tmp_path / "broken_one.py").write_text("import os\n", encoding="utf-8")
    with pytest.raises(ValueError):
        load_extensions(tmp_path)


@pytest.mark.parametrize("code", [
    "import os\nTEMPLATE = {}\nRULES = ''\nSAMPLES = []\n",
    "TEMPLATE = dict(id='x')\nRULES = ''\nSAMPLES = []\n",
    "TEMPLATE = {}\nRULES = __import__('os').getcwd()\nSAMPLES = []\n",
    "def TEMPLATE():\n    pass\nRULES = ''\nSAMPLES = []\n",
    "TEMPLATE = {}\nRULES = ''\nSAMPLES = []\nEXTRA = 1\n",
    "TEMPLATE, RULES = {}, ''\nSAMPLES = []\n",
])
def test_files_with_code_or_unexpected_names_are_rejected(tmp_path, code):
    (tmp_path / "dental_clinic.py").write_text(code, encoding="utf-8")
    with pytest.raises(ValueError):
        load_extensions(tmp_path)


def _bad(**changes):
    return {**VALID_TEMPLATE, **changes}


@pytest.mark.parametrize("file_id,template,rules,samples", [
    ("dental_clinic", _bad(id="Dental"), VALID_RULES, VALID_SAMPLES),
    ("other_name", VALID_TEMPLATE, VALID_RULES, VALID_SAMPLES),
    ("clinic", _bad(id="clinic"), VALID_RULES, VALID_SAMPLES),
    ("dental_clinic", _bad(version="2.0.0"), VALID_RULES, VALID_SAMPLES),
    ("dental_clinic", {**VALID_TEMPLATE, "tools": ["execute_sql"]}, VALID_RULES, VALID_SAMPLES),
    ("dental_clinic", {k: v for k, v in VALID_TEMPLATE.items() if k != "lead_rule"}, VALID_RULES, VALID_SAMPLES),
    ("dental_clinic", _bad(questions=["Only one question?"]), VALID_RULES, VALID_SAMPLES),
    ("dental_clinic", _bad(questions=["ok question?", 5]), VALID_RULES, VALID_SAMPLES),
    ("dental_clinic", _bad(name="X"), VALID_RULES, VALID_SAMPLES),
    ("dental_clinic", _bad(classification_hint="short"), VALID_RULES, VALID_SAMPLES),
    ("dental_clinic", VALID_TEMPLATE, "Too short.", VALID_SAMPLES),
    ("dental_clinic", VALID_TEMPLATE, "x" * 1501, VALID_SAMPLES),
    ("dental_clinic", VALID_TEMPLATE, VALID_RULES, VALID_SAMPLES[:2]),
    ("dental_clinic", VALID_TEMPLATE, VALID_RULES, VALID_SAMPLES[:2] + ["x" * 241]),
])
def test_invalid_extensions_are_rejected(file_id, template, rules, samples):
    with pytest.raises(ValueError):
        validate_extension(file_id, template, rules, samples)


# Same table as mcp/industry-template-mcp/src/industry.test.ts: one character rule on both sides.
@pytest.mark.parametrize("template,rules,samples", [
    (_bad(name="\u0085Dental\u0085"), VALID_RULES, VALID_SAMPLES),  # Python strips NEL, JS trim does not
    (_bad(name="\u001cDental clinic"), VALID_RULES, VALID_SAMPLES),
    (_bad(name="Dental\u0000clinic"), VALID_RULES, VALID_SAMPLES),
    (_bad(name="Dental\n\nCo-authored-by: X <x@y.z>"), VALID_RULES, VALID_SAMPLES),
    (_bad(description="Answer dental questions ‮ for the clinic."), VALID_RULES, VALID_SAMPLES),
    (_bad(lead_rule="Wants an appointment today."), VALID_RULES, VALID_SAMPLES),
    (_bad(classification_hint="Needs dental services \ud800 such as scaling."), VALID_RULES, VALID_SAMPLES),
    (_bad(name="﻿Dental clinic"), VALID_RULES, VALID_SAMPLES),
    (VALID_TEMPLATE, VALID_RULES.replace(". ", ".\r\n", 1), VALID_SAMPLES),
    (VALID_TEMPLATE, VALID_RULES, VALID_SAMPLES[:2] + ["本牙科诊所⁦提供洗牙和矫正服务。"]),
])
def test_control_bidi_and_line_break_characters_are_rejected(template, rules, samples):
    with pytest.raises(ValueError):
        validate_extension("dental_clinic", template, rules, samples)


def test_rules_may_span_lines_and_text_may_use_any_script():
    validate_extension("dental_clinic", _bad(name="牙科诊所 Klinik 🦷"),
                       VALID_RULES.replace(". ", ".\n", 1), VALID_SAMPLES)


def test_merge_appends_extensions_in_id_order_and_refuses_collisions():
    templates = {"general": {"id": "general"}}
    rules = {"general": "general rules"}
    later = {**VALID_TEMPLATE, "id": "zoo_park"}
    merged_templates, merged_rules = merge_extensions(
        [(later, "zoo rules", VALID_SAMPLES), (VALID_TEMPLATE, VALID_RULES, VALID_SAMPLES)], templates, rules)
    assert list(merged_templates) == ["general", "dental_clinic", "zoo_park"]
    assert merged_rules["dental_clinic"] == VALID_RULES and templates == {"general": {"id": "general"}}
    with pytest.raises(ValueError):
        merge_extensions([({**VALID_TEMPLATE, "id": "general"}, VALID_RULES, VALID_SAMPLES)], templates, rules)


def test_every_repository_extension_is_registered_everywhere():
    for template, _rules, _samples in load_extensions(EXTENSION_DIR):
        assert template["id"] in template_ids()
        assert template["classification_hint"] in catalog.CLASSIFICATION_INSTRUCTIONS
        assert catalog.industry_prompt({"template_id": template["id"], "template_version": template["version"]})

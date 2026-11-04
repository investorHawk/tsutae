"""D4 レジメン — フォーム（正本）と SKILL.md の描画（spec 9.1・architecture 9c）。

- form.py: `RegimenForm`（pydantic）・欄の id・出どころ（`FieldSources`）・form JSON の読み込み
- validate.py: 値の検査（`validate_form`・`missing_fields`。欄の id と理由を返す）
- text_checks.py: 文の欄の検査（薬の量・H1・改行・「|」・YAML の読み戻し）
- schedule.py: 投与スケジュールから §1 の箇条と日付の言い方の表を作る
- render.py: `render_regimen_skill(form, version)`（Jinja2。純関数）
"""

from tsutae.regimen.form import (
    BUILTIN_FORMS_DIR,
    BasicInfo,
    ContradictionExample,
    DayRange,
    DrugRow,
    FieldSource,
    FieldSources,
    QuestionRow,
    RegimenForm,
    RegimenProse,
    Route,
    SideEffectRow,
    builtin_form_path,
    field_ids,
    load_builtin_form,
    load_form_json,
    prune_sources,
    unknown_source_ids,
)
from tsutae.regimen.render import (
    expected_frontmatter,
    render_regimen_skill,
    skill_name_for,
    term_keys_for_form,
)
from tsutae.regimen.text_checks import FieldIssue, RegimenFormError, has_dose
from tsutae.regimen.validate import (
    key_yaml_checks,
    missing_fields,
    validate_complete_form,
    validate_form,
)

__all__ = [
    "BUILTIN_FORMS_DIR",
    "BasicInfo",
    "ContradictionExample",
    "DayRange",
    "DrugRow",
    "FieldIssue",
    "FieldSource",
    "FieldSources",
    "QuestionRow",
    "RegimenForm",
    "RegimenFormError",
    "RegimenProse",
    "Route",
    "SideEffectRow",
    "builtin_form_path",
    "expected_frontmatter",
    "field_ids",
    "has_dose",
    "key_yaml_checks",
    "load_builtin_form",
    "load_form_json",
    "missing_fields",
    "prune_sources",
    "render_regimen_skill",
    "skill_name_for",
    "term_keys_for_form",
    "unknown_source_ids",
    "validate_complete_form",
    "validate_form",
]

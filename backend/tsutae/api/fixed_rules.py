"""緊急時の固定規則（患者画面の案内）。判定はコードの閾値比較だけ。

記録はスマホに置くので、案内を出すのは画面のコード（plan-device-records §5.3。規則は
`GET /questions` の fixed_rules）。ここは同じ判定の Python の側で、同じ表でテストする。

- 対象はクローズ回答の体温（value=measured）だけ。自由記載は読まない
- 体温 >= threshold_celsius なら、その規則の patient_string_key を返す
- 規則の順に並べ、同じキーは1回だけ。引数は書き換えない
"""

from __future__ import annotations

from tsutae.schemas import ClosedAnswer, EntryCreate, FixedRule, RegimenSkill

__all__ = ["notices_for"]


def _temperature(entry: EntryCreate, question_key: str) -> float | None:
    for answer in entry.answers:
        if answer.question_key == question_key:
            return _measured(answer)
    return None


def _measured(answer: ClosedAnswer) -> float | None:
    if answer.value != "measured" or answer.temperature is None:
        return None
    return answer.temperature


def _fires(entry: EntryCreate, rule: FixedRule) -> bool:
    temperature = _temperature(entry, rule.question_key)
    return temperature is not None and temperature >= rule.threshold_celsius


def notices_for(entry: EntryCreate, skill: RegimenSkill) -> list[str]:
    """記録が当てはまる固定規則の patient_strings のキー（例 `fixed_rule.fever_38`）。"""
    if entry.too_sick:
        return []
    keys: list[str] = []
    for rule in skill.fixed_rules:
        if _fires(entry, rule) and rule.patient_string_key not in keys:
            keys.append(rule.patient_string_key)
    return keys

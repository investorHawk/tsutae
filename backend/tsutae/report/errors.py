"""レポートを組み立てられない入力の例外。"""

from __future__ import annotations


class ReportBuildError(ValueError):
    """入力が食い違っていてレポートを組み立てられない。`code` は短い英字。

    - patient_mismatch: 引数の patient_id と courses・entries の患者が合わない
    - schedule_mismatch: PreparedInput の日程・レジメンが courses・受診日と合わない
    - entry_mismatch: PreparedInput の記録が entries と対応しない（id の重複も含む）
    - skill_mismatch: PreparedInput の Skill の版・質問集が渡された Skill と違う
    - answer_mismatch: 記録の回答の値が、その版の質問の型（3択・体温）と合わない
    - unknown_skill_version: 記録の版の質問集が無く、未設問か入力なしかを決められない
    """

    def __init__(self, code: str, message: str = "") -> None:
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}" if message else code)

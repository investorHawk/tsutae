"""合成3人（デモ患者・評価用2人）とそのコース・記録を DB に入れる。症例は全て合成。

    .venv/bin/python scripts/seed_demo.py [--db PATH] [--skills-dir DIR]

- 既定の DB は設定の `TSUTAE_DB`（無ければ data/tsutae.db）。表が無ければ作る
- 今の SKILL.md を skill_versions に登録する（`ensure_skill_versions`）
- 既にいる患者（仮名IDが同じ）は飛ばす。**DB を消さない・上書きしない**（何度流してもよい）
- 記録は合成データの seq の順に入れる（空の DB ならデモ患者の entries.id は seq と同じ）
- 1人分（患者・コース・記録）は `db.seed_patient` で1つのトランザクションで入れる。
  途中で失敗すればその患者は丸ごと残らないので、次に流せば入れ直せる
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from collections.abc import Sequence
from pathlib import Path

from tsutae import db
from tsutae.config import get_settings, load_env_file
from tsutae.dataset import to_courses, to_entries
from tsutae.pipeline.service import ensure_skill_versions
from tsutae.schemas import SyntheticPatient
from tsutae.synthetic import all_patients


def _seed_one(conn: sqlite3.Connection, patient: SyntheticPatient) -> bool:
    """まだいなければ1人分を1つのトランザクションで入れる。入れたら True。"""
    entries = sorted(to_entries(patient), key=lambda e: e.id)  # seq の順
    return db.seed_patient(
        conn,
        patient_id=patient.patient_id,
        regimen=patient.regimen,
        courses=to_courses(patient),
        entries=entries,
    )


def seed(
    conn: sqlite3.Connection,
    *,
    skills_dir: Path | None = None,
    synthetic_dir: Path | None = None,
) -> list[str]:
    """表を作り Skill の版を登録し、まだいない合成患者を入れる。入れた仮名IDを返す。"""
    db.init_db(conn)
    ensure_skill_versions(conn, skills_dir or get_settings().skills_dir)
    added: list[str] = []
    for patient, _labels in all_patients(synthetic_dir):
        if _seed_one(conn, patient):
            added.append(patient.patient_id)
    return added


def _parse(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--db", type=Path, default=None, help="SQLite のファイル")
    parser.add_argument(
        "--skills-dir", type=Path, default=None, help="Skill の置き場所（既定は設定）"
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    load_env_file()
    args = _parse(argv)
    settings = get_settings()
    path = args.db or settings.db_path
    conn = db.connect(path)
    try:
        added = seed(conn, skills_dir=args.skills_dir or settings.skills_dir)
        existing = [p["id"] for p in db.list_patients(conn) if p["id"] not in added]
    finally:
        conn.close()
    print(f"DB: {path}")
    print(f"追加した患者: {', '.join(added) if added else 'なし'}")
    print(f"既にいた患者: {', '.join(existing) if existing else 'なし'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

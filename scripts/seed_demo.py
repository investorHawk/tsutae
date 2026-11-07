"""合成3人（デモ患者・評価用2人）とそのコース・記録を DB に入れる。症例は全て合成。

    .venv/bin/python scripts/seed_demo.py [--db PATH] [--skills-dir DIR] [--device-records]

- 既定の DB は設定の `TSUTAE_DB`（無ければ data/tsutae.db）。表が無ければ作る
- 今の SKILL.md を skill_versions に登録する（`ensure_skill_versions`）
- 既にいる患者（仮名IDが同じ）は飛ばす。**DB を消さない・上書きしない**（何度流してもよい）
- 記録は合成データの seq の順に入れる（空の DB ならデモ患者の entries.id は seq と同じ）
- 1人分（患者・コース・記録）は `db.seed_patient` で1つのトランザクションで入れる。
  途中で失敗すればその患者は丸ごと残らないので、次に流せば入れ直せる
- `--device-records`: スマホ保存の撮影用（plan-device-records §5.10）。患者・コース・日付の印
  だけを入れ、entries を入れない（入れると受付で二重に数える）。既定の動きは変えない
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


def _seed_one(
    conn: sqlite3.Connection, patient: SyntheticPatient, device_records: bool = False
) -> bool:
    """まだいなければ1人分を1つのトランザクションで入れる。入れたら True。"""
    entries = sorted(to_entries(patient), key=lambda e: e.id)  # seq の順
    return db.seed_patient(
        conn,
        patient_id=patient.patient_id,
        regimen=patient.regimen,
        courses=to_courses(patient),
        entries=[] if device_records else entries,
        marks=[e.recorded_at for e in entries] if device_records else (),
    )


def seed(
    conn: sqlite3.Connection,
    *,
    skills_dir: Path | None = None,
    synthetic_dir: Path | None = None,
    device_records: bool = False,
) -> list[str]:
    """表を作り Skill の版を登録し、まだいない合成患者を入れる。入れた仮名IDを返す。

    device_records なら記録を入れず、日付の印だけを付ける。
    """
    db.init_db(conn)
    ensure_skill_versions(conn, skills_dir or get_settings().skills_dir)
    added: list[str] = []
    for patient, _labels in all_patients(synthetic_dir):
        if _seed_one(conn, patient, device_records):
            added.append(patient.patient_id)
    return added


def _parse(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--db", type=Path, default=None, help="SQLite のファイル")
    parser.add_argument(
        "--skills-dir", type=Path, default=None, help="Skill の置き場所（既定は設定）"
    )
    parser.add_argument(
        "--device-records",
        action="store_true",
        help="記録を入れず、患者・コース・日付の印だけを入れる（スマホ保存の撮影用）",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    load_env_file()
    args = _parse(argv)
    settings = get_settings()
    path = args.db or settings.db_path
    conn = db.connect(path)
    try:
        added = seed(
            conn,
            skills_dir=args.skills_dir or settings.skills_dir,
            device_records=args.device_records,
        )
        existing = [p["id"] for p in db.list_patients(conn) if p["id"] not in added]
    finally:
        conn.close()
    print(f"DB: {path}")
    print(f"追加した患者: {', '.join(added) if added else 'なし'}")
    print(f"既にいた患者: {', '.join(existing) if existing else 'なし'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

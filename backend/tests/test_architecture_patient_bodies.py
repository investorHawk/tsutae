"""受付以外の患者 API に、記録の中身が入らないこと（plan-device-records §9）。

記録はスマホに置く。サーバーへ届くのは受付（`POST /api/visit`）のときだけで、記録のときに届くのは
本文なしの印だけ。アプリに載った全ての経路の本文の形（`app.openapi()`。公開はしていない）を
たどるので、患者の経路を足せば自動で検査の対象になる。
"""

from __future__ import annotations

import ast
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from api_helpers import make_app
from fastapi import FastAPI

from tsutae.config import PACKAGE_ROOT

RECORD_FIELDS = frozenset(
    {"free_text", "answers", "answer", "temperature", "value", "text", "too_sick"}
)
RECEPTION = ("post", "/api/visit")
PATIENT_PREFIX = "/api/patient"
NO_BODY_ROUTES = (
    ("post", "/api/patient/{pid}/record-marks"),
    ("get", "/api/patient/{pid}/visit-window"),
    ("get", "/api/patient/{pid}/visit-days"),
    ("get", "/api/patient/{pid}/demo-config"),
    ("get", "/api/patient/{pid}/demo-entries"),
)
REMOVED_ROUTES = (
    ("post", "/api/patient/{pid}/entries"),
    ("get", "/api/patient/{pid}/entries"),
    ("post", "/api/patient/{pid}/entries/{entry_id}/undo"),
)
HANDLER_MODULES = tuple(
    PACKAGE_ROOT / "api" / name
    for name in (
        "patient.py",
        "patient_device.py",
        "patient_demo.py",
        "patient_push.py",
    )
)
BODY_READERS = frozenset({"json", "body", "form", "stream"})


def field_names(schema: Any, components: dict[str, Any]) -> set[str]:
    """JSON Schema の中の全ての欄の名前（`$ref`・配列・`anyOf` の中も）。"""
    names: set[str] = set()
    todo = [schema]
    seen: set[str] = set()
    while todo:
        node = todo.pop()
        if isinstance(node, list):
            todo.extend(node)
        elif isinstance(node, dict):
            ref = node.get("$ref")
            if isinstance(ref, str) and ref not in seen:
                seen.add(ref)
                todo.append(components[ref.rsplit("/", 1)[-1]])
            names.update(node.get("properties", {}))
            todo.extend(node.values())
    return names


def _operations(app: FastAPI) -> Iterator[tuple[str, str, dict[str, Any]]]:
    for path, methods in app.openapi()["paths"].items():
        for method, operation in methods.items():
            yield method, path, operation


def _body_fields(app: FastAPI, operation: dict[str, Any]) -> set[str]:
    components = app.openapi()["components"]["schemas"]
    return field_names(operation.get("requestBody", {}), components)


@pytest.fixture
def app(tmp_path: Path) -> FastAPI:
    return make_app(tmp_path)


def test_reception_is_the_one_with_record_fields(app: FastAPI) -> None:
    """検査に意味があること（受付の本文では見つかる）。"""
    operations = {(m, p): o for m, p, o in _operations(app)}
    fields = _body_fields(app, operations[RECEPTION])
    assert {"free_text", "answers", "temperature", "value"} <= fields


def test_no_other_patient_route_takes_record_fields(app: FastAPI) -> None:
    leaks = {
        (method, path): sorted(_body_fields(app, operation) & RECORD_FIELDS)
        for method, path, operation in _operations(app)
        if path.startswith(PATIENT_PREFIX)
        and _body_fields(app, operation) & RECORD_FIELDS
    }
    assert leaks == {}


@pytest.mark.parametrize("key", NO_BODY_ROUTES, ids=str)
def test_routes_without_a_body(app: FastAPI, key: tuple[str, str]) -> None:
    operations = {(m, p): o for m, p, o in _operations(app)}
    assert "requestBody" not in operations[key]


def test_entries_routes_are_removed(app: FastAPI) -> None:
    routes = {(m, p) for m, p, _o in _operations(app)}
    assert routes.isdisjoint(REMOVED_ROUTES)


def _reads_raw_body(path: Path) -> list[str]:
    """`request.json()` のように、モデルを通さず本文を読む呼び出し。"""
    found = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if (
            isinstance(node, ast.Attribute)
            and node.attr in BODY_READERS
            and isinstance(node.value, ast.Name)
            and node.value.id == "request"
        ):
            found.append(f"{path.name}:{node.lineno}")
    return found


@pytest.mark.parametrize("path", HANDLER_MODULES, ids=lambda p: p.name)
def test_handlers_do_not_read_the_raw_body(path: Path) -> None:
    assert _reads_raw_body(path) == []

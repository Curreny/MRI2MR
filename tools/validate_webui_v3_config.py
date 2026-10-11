from __future__ import annotations

import ast
import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def read_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def route_set(path: Path) -> set[tuple[str, str]]:
    tree = ast.parse(read_text(path), filename=str(path))
    routes: set[tuple[str, str]] = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for decorator in node.decorator_list:
            if not isinstance(decorator, ast.Call):
                continue
            if not isinstance(decorator.func, ast.Attribute):
                continue
            method = decorator.func.attr.upper()
            if method not in {"GET", "POST", "PUT", "PATCH", "DELETE"}:
                continue
            if decorator.args and isinstance(decorator.args[0], ast.Constant):
                value = decorator.args[0].value
                if isinstance(value, str):
                    routes.add((method, value))
    return routes


def iter_fields(mode: dict[str, Any]) -> list[dict[str, Any]]:
    fields = mode.get("fields", [])
    return fields if isinstance(fields, list) else []


def find_mode(modes: list[dict[str, Any]], name: str) -> dict[str, Any]:
    for mode in modes:
        if mode.get("mode") == name:
            return mode
    raise AssertionError(f"Missing mode: {name}")


def check_routes() -> None:
    routes = route_set(ROOT / "app" / "backend" / "main.py")
    required = {
        ("POST", "/api/select-path"),
        ("POST", "/api/inspect-path"),
        ("POST", "/api/detect-dicom-series"),
    }
    missing = sorted(required - routes)
    require(not missing, f"Missing V3 API routes: {missing}")
    print("OK V3 API routes")


def check_backend_modules() -> None:
    inspectors = ROOT / "app" / "backend" / "inspectors.py"
    require(inspectors.exists(), "Missing app/backend/inspectors.py")
    for path in sorted((ROOT / "app" / "backend").glob("*.py")):
        ast.parse(read_text(path), filename=str(path))
    print("OK backend syntax")


def check_dicom_mode_fields() -> None:
    data = read_json(ROOT / "config" / "modes.json")
    modes = data.get("modes") if isinstance(data, dict) else data
    require(isinstance(modes, list), "modes.json must contain a mode list")
    dicom = find_mode(modes, "dicom_convert")
    fields = {field.get("name"): field for field in iter_fields(dicom)}
    expected = {
        "dicom_t1_source": "--dicom-t1-source",
        "dicom_mra_source": "--dicom-mra-source",
        "dicom_mrv_source": "--dicom-mrv-source",
        "dicom_dti_source": "--dicom-dti-source",
    }
    for name, cli in expected.items():
        require(name in fields, f"Missing DICOM source field: {name}")
        require(fields[name].get("cli") == cli, f"{name} cli mismatch")
        require(fields[name].get("advanced") is not True, f"{name} must be visible in basic fields")
        require(fields[name].get("type") == "directory", f"{name} must use directory path input")
        label = str(fields[name].get("label") or "")
        help_text = str(fields[name].get("help") or "")
        require("手动源" not in label and "手动源路径" not in label, f"{name} label still uses manual-source wording")
        require(
            "手动源" not in help_text and "手动源路径" not in help_text,
            f"{name} help still uses manual-source wording",
        )
    print("OK DICOM sequence folder source fields")


def check_main_cmd_contract() -> None:
    text = read_text(ROOT / "scripts" / "Main_cmd.py")
    for marker in [
        "dicom_t1_source",
        "dicom_mra_source",
        "dicom_mrv_source",
        "dicom_dti_source",
        "--dicom-t1-source",
        "--dicom-mra-source",
        "--dicom-mrv-source",
        "--dicom-dti-source",
        "dicom_candidates.json",
        "dicom_selection.json",
        "bval/bvec count matches DTI volumes",
    ]:
        require(marker in text, f"Main_cmd.py missing marker: {marker}")
    ast.parse(text, filename=str(ROOT / "scripts" / "Main_cmd.py"))
    print("OK Main_cmd V3 markers")


def check_frontend_markers() -> None:
    app_js = read_text(ROOT / "app" / "static" / "app.js")
    style_css = read_text(ROOT / "app" / "static" / "style.css")
    for marker in [
        "/api/select-path",
        "/api/inspect-path",
        "/api/detect-dicom-series",
        "field-note",
        "path-input-group",
    ]:
        require(marker in app_js or marker in style_css, f"Missing frontend marker: {marker}")
    print("OK frontend V3 markers")


def main() -> int:
    check_backend_modules()
    check_routes()
    check_dicom_mode_fields()
    check_main_cmd_contract()
    check_frontend_markers()
    print("OK WebUI V3 config validation completed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

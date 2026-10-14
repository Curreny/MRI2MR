"""Shared MCP schemas, defaults and validation for the existing vascular pipeline."""
from __future__ import annotations

import math
from typing import Any


TARGETS = {"artery": ("artery",), "vein": ("vein",), "both": ("artery", "vein")}
MODALITIES = {"artery": ("mra",), "vein": ("mrv",), "vessel": ("mra", "mrv")}
PARAMETERS: dict[str, dict[str, Any]] = {
    "vessel_threshold": {"type": "number", "minimum": 0, "default": 800, "description": "Artery intensity threshold."},
    "vessel_min_object_size": {"type": "integer", "minimum": 1, "default": 1000},
    "vessel_decimation_fraction": {"type": "number", "exclusiveMinimum": 0, "maximum": 1, "default": 0.5},
    "marching_cubes_level": {"type": "number", "exclusiveMinimum": 0, "exclusiveMaximum": 1, "default": 0.7},
    "min_object_size": {"type": "integer", "minimum": 1, "default": 14500, "description": "Final vein component minimum size, in voxels."},
    "mesh_decimation_fraction": {"type": "number", "exclusiveMinimum": 0, "maximum": 1, "default": 0.08, "description": "Vein mesh retained-face fraction."},
    "mrv_frangi_sigmas_start": {"type": "integer", "minimum": 1, "default": 1},
    "mrv_frangi_sigmas_end": {"type": "integer", "minimum": 2, "default": 12, "description": "Exclusive end of Frangi scales."},
    "mrv_frangi_sigmas_step": {"type": "integer", "minimum": 1, "default": 1},
    "mrv_strong_seed_percentile": {"type": "number", "minimum": 0, "exclusiveMaximum": 100, "default": 99.9},
    "mrv_strong_grow_tolerance": {"type": "number", "exclusiveMinimum": 0, "maximum": 1, "default": 0.95},
    "mrv_weak_seed_percentile": {"type": "number", "minimum": 0, "exclusiveMaximum": 100, "default": 99.8},
    "mrv_weak_grow_tolerance": {"type": "number", "exclusiveMinimum": 0, "maximum": 1, "default": 0.85},
    "mrv_post_process_min_size": {"type": "integer", "minimum": 1, "default": 1000},
}
ARTERY_PARAMETERS = {"vessel_threshold", "vessel_min_object_size", "vessel_decimation_fraction", "marching_cubes_level"}
VEIN_PARAMETERS = set(PARAMETERS) - (ARTERY_PARAMETERS - {"marching_cubes_level"})


def target_vessels(target: str) -> tuple[str, ...]:
    if target not in TARGETS:
        raise ValueError("target must be artery, vein or both")
    return TARGETS[target]


def parameter_names(target: str) -> set[str]:
    target_vessels(target)
    return ARTERY_PARAMETERS if target == "artery" else VEIN_PARAMETERS if target == "vein" else set(PARAMETERS)


def validate_parameter(name: str, value: Any) -> None:
    if name not in PARAMETERS:
        raise ValueError(f"Unknown reconstruction parameter: {name}")
    schema = PARAMETERS[name]
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{name} must be a finite number")
    if schema["type"] == "integer" and not isinstance(value, int):
        raise ValueError(f"{name} must be an integer")
    for key, invalid in (
        ("minimum", lambda limit: value < limit),
        ("maximum", lambda limit: value > limit),
        ("exclusiveMinimum", lambda limit: value <= limit),
        ("exclusiveMaximum", lambda limit: value >= limit),
    ):
        if key in schema and invalid(schema[key]):
            raise ValueError(f"{name} requires {key} {schema[key]}")


def normalize_parameters(target: str, supplied: dict[str, Any] | None = None) -> dict[str, Any]:
    names = parameter_names(target)
    if supplied is not None and not isinstance(supplied, dict):
        raise ValueError("parameters must be an object")
    supplied = supplied or {}
    for name, value in supplied.items():
        validate_parameter(name, value)
        if name not in names:
            raise ValueError(f"{name} does not apply to target={target}")
    result = {name: supplied.get(name, schema["default"]) for name, schema in PARAMETERS.items() if name in names}
    if "vein" in target_vessels(target):
        if result["mrv_frangi_sigmas_end"] <= result["mrv_frangi_sigmas_start"]:
            raise ValueError("mrv_frangi_sigmas_end must exceed mrv_frangi_sigmas_start")
        if result["mrv_weak_seed_percentile"] > result["mrv_strong_seed_percentile"]:
            raise ValueError("mrv_weak_seed_percentile must not exceed mrv_strong_seed_percentile")
    return result


def parameter_schema() -> dict[str, Any]:
    return {"type": "object", "properties": PARAMETERS, "additionalProperties": False}


def search_space_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            name: {"type": "array", "minItems": 1, "maxItems": 25, "items": {key: value for key, value in schema.items() if key not in {"default", "description"}}}
            for name, schema in PARAMETERS.items()
        },
        "additionalProperties": False,
    }

"""Bounded candidate proposals; visual comparison and execution remain agent decisions."""
from __future__ import annotations

import hashlib
import json
from typing import Any

from parameters import normalize_parameters, parameter_names, target_vessels, validate_parameter


def recommend(
    target: str, base: dict[str, Any], tried: list[dict[str, Any]],
    artery_assessment: str | None, vein_assessment: str | None,
    search_space: dict[str, list[Any]] | None, locked_parameters: list[str] | None,
    max_candidates: int,
) -> dict[str, Any]:
    base = normalize_parameters(target, base)
    allowed = parameter_names(target)
    if isinstance(max_candidates, bool) or not isinstance(max_candidates, int) or not 1 <= max_candidates <= 100:
        raise ValueError("max_candidates must be an integer from 1 to 100")
    locked_parameters = [] if locked_parameters is None else locked_parameters
    if not isinstance(locked_parameters, list) or any(not isinstance(name, str) or name not in allowed for name in locked_parameters):
        raise ValueError("locked_parameters must name parameters applicable to this target")
    locked = set(locked_parameters)
    assessments = {"artery": artery_assessment, "vein": vein_assessment}
    common = {"good", "too_dense", "too_sparse", "uncertain"}
    for vessel in target_vessels(target):
        options = common | ({"scalp_dominant", "intracranial_sparse"} if vessel == "vein" else set())
        if assessments[vessel] not in options:
            raise ValueError(f"{vessel}_assessment is required for target={target}; expected {sorted(options)}")
    if search_space is not None:
        if not isinstance(search_space, dict):
            raise ValueError("search_space must be an object")
        for name, values in search_space.items():
            if name not in allowed or not isinstance(values, list) or not 1 <= len(values) <= 25:
                raise ValueError(f"search_space.{name} must provide 1-25 values for this target")
            for value in values:
                validate_parameter(name, value)
    else:
        search_space = {}
        if "artery" in target_vessels(target):
            value = base["vessel_threshold"]
            search_space["vessel_threshold"] = [max(0, value - 100), value, value + 100]
        if "vein" in target_vessels(target):
            value = base["mrv_weak_grow_tolerance"]
            search_space["mrv_weak_grow_tolerance"] = [max(0.001, round(value - 0.02, 6)), value, min(1, round(value + 0.03, 6))]
            size = base["mrv_post_process_min_size"]
            search_space["mrv_post_process_min_size"] = [max(1, int(size * 0.8)), size, max(size + 1, int(size * 1.5))]
    active = [assessments[name] for name in target_vessels(target)]
    if "uncertain" in active:
        return {"status": "needs_human_review", "reason": "The requested vessel's visual assessment is uncertain."}
    if all(value == "good" for value in active):
        return {"status": "no_change", "reason": "All requested vessel previews were assessed as good."}
    if len(tried) >= max_candidates:
        return {"status": "budget_exhausted", "candidate_count": len(tried), "max_candidates": max_candidates}

    for name, values in search_space.items():
        if name in locked:
            continue
        applicable = [vessel for vessel in target_vessels(target) if name in parameter_names(vessel)]
        assessment = next((assessments[v] for v in applicable if assessments[v] != "good"), "good")
        if assessment == "good":
            continue
        direction = 1 if assessment in {"too_dense", "scalp_dominant"} else -1
        if name in {"mesh_decimation_fraction", "vessel_decimation_fraction"}:
            direction *= -1
        # Scale and isosurface settings have no assumed monotonic anatomical quality relation.
        exploratory = name.startswith("mrv_frangi_sigmas_") or name == "marching_cubes_level"
        alternatives = [value for value in values if value != base[name] and (exploratory or (value - base[name]) * direction > 0)]
        for value in sorted(alternatives, key=lambda item: abs(item - base[name])):
            try:
                proposal = normalize_parameters(target, {**base, name: value})
            except ValueError:
                continue  # A combination may violate cross-parameter constraints.
            if proposal in tried:
                continue
            signature = hashlib.sha256(json.dumps(proposal, sort_keys=True).encode()).hexdigest()[:12]
            return {
                "status": "recommended", "target": target, "parameters": proposal,
                "changed_parameter": name, "changed_parameter_count": 1,
                "candidate_id_suggestion": f"auto-{target}-{signature}",
                "reason": ("compare a user-supplied scale/mesh setting" if exploratory else
                           "reduce scalp/peripheral vein proxy while reviewing branch retention" if assessment == "scalp_dominant" else
                           "recover missing branches" if assessment in {"too_sparse", "intracranial_sparse"} else
                           "reduce density/noise"),
                "candidate_count": len(tried), "max_candidates": max_candidates,
                "selection_scope": "best among evaluated candidates, not a guaranteed global optimum",
            }
    return {"status": "needs_human_review", "reason": "No untried change remains within the requested search space and parameter locks."}

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import nibabel as nib
import numpy as np
import trimesh

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[2] / "scripts"))

from job_runner import PipelineFailure, candidate_commands, clear_conversion_outputs, conversion_result  # noqa: E402
from parameters import normalize_parameters  # noqa: E402
from service import Settings, VesselPilotInputError, VesselPilotService, atomic_json, sha256_file  # noqa: E402
from Vascular_cmd import DicomConverter  # noqa: E402


class VesselPilotServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.inputs = self.root / "inputs"
        self.inputs.mkdir()
        self.cases = self.root / "cases"
        discovered = Settings.discover(HERE / "server.py", self.cases, [self.inputs])
        self.service = VesselPilotService(discovered)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def create_case(self) -> str:
        dicom = self.inputs / "dicom"
        dicom.mkdir()
        (dicom / "image001.dcm").write_bytes(b"synthetic-not-real-dicom")
        result = self.service.inspect_dicom_case(str(dicom), True, "case-test")
        return result["case_id"]

    def test_runtime_discovery_uses_available_portable_python(self) -> None:
        self.assertTrue(self.service.settings.python_exe.is_file())
        self.assertEqual(self.service.settings.python_exe.name, "python.exe")

    def test_rejects_path_outside_allowlist(self) -> None:
        outside = self.root / "outside"
        outside.mkdir()
        (outside / "one.dcm").write_bytes(b"x")
        with self.assertRaisesRegex(ValueError, "outside configured input roots"):
            self.service.inspect_dicom_case(str(outside), True)

    def test_allow_any_input_accepts_explicit_external_directory(self) -> None:
        outside = self.root / "outside"
        outside.mkdir()
        (outside / "one.dcm").write_bytes(b"x")
        settings = Settings.discover(
            HERE / "server.py", self.cases / "any", [self.inputs], allow_any_input=True
        )
        service = VesselPilotService(settings)
        inspected = service.inspect_dicom_case(str(outside), True, "case-external")
        self.assertEqual(inspected["case_id"], "case-external")
        with patch(
            "service.subprocess.run",
            return_value=SimpleNamespace(returncode=0, stdout=str(outside)),
        ):
            selected = service.choose_dicom_folder()
        self.assertEqual(selected, {"status": "selected", "input_path": str(outside.resolve())})

    def test_requires_deidentification_confirmation(self) -> None:
        with self.assertRaisesRegex(ValueError, "confirm_deidentified"):
            self.service.inspect_dicom_case(str(self.inputs), False)

    def test_rejects_empty_or_non_dicom_input_before_registration(self) -> None:
        empty = self.inputs / "empty"
        empty.mkdir()
        text_only = self.inputs / "text-only"
        text_only.mkdir()
        (text_only / "notes.txt").write_text("not imaging data", encoding="utf-8")
        zero_only = self.inputs / "zero-only"
        zero_only.mkdir()
        (zero_only / "empty.dcm").write_bytes(b"")
        for path, expected_code in (
            (empty, "INPUT_EMPTY"),
            (text_only, "INPUT_NO_DICOM_FILES"),
            (zero_only, "INPUT_NO_DICOM_FILES"),
        ):
            with self.subTest(path=path.name):
                with self.assertRaises(VesselPilotInputError) as raised:
                    self.service.inspect_dicom_case(str(path), True)
                self.assertEqual(raised.exception.code, expected_code)

    def test_preflight_accepts_mixed_folder_and_reports_ignored_files(self) -> None:
        mixed = self.inputs / "mixed"
        mixed.mkdir()
        (mixed / "image001").write_bytes(b"\0" * 128 + b"DICM" + b"payload")
        (mixed / "image002.dcm").write_bytes(b"dicom-without-preamble")
        (mixed / "notes.txt").write_text("ignore me", encoding="utf-8")
        (mixed / "empty.bin").write_bytes(b"")
        inspected = self.service.inspect_dicom_case(str(mixed), True, "case-mixed")
        preflight = inspected["input_preflight"]
        self.assertEqual(preflight["likely_dicom_file_count"], 2)
        self.assertEqual(preflight["standard_preamble_file_count"], 1)
        self.assertEqual(preflight["non_dicom_file_count"], 2)
        self.assertEqual(preflight["empty_file_count"], 1)
        self.assertEqual(
            set(preflight["warnings"]),
            {
                "mixed_non_dicom_files_ignored_by_converter",
                "dicom_suffix_without_standard_preamble",
            },
        )

    def test_dicom_candidate_ranking_ignores_unsupported_series(self) -> None:
        converter = object.__new__(DicomConverter)

        def candidate(
            name: str,
            desc: str,
            *,
            shape: list[int],
            size: int = 100,
            load_error: str | None = None,
        ) -> dict:
            return {
                "nii": Path(name),
                "json": Path(name).with_suffix(".json"),
                "desc": desc,
                "series_description": desc,
                "protocol_name": "",
                "sequence_name": "",
                "series_number": None,
                "image_type": ["ORIGINAL", "PRIMARY"],
                "is_original_image_type": True,
                "is_derived_image_type": False,
                "has_bval_bvec": False,
                "shape": shape,
                "voxel_size": [1.0, 1.0, 1.0],
                "nifti_load_error": load_error,
                "size": size,
            }

        usable = candidate("tof.nii", "3d tof mra", shape=[64, 64, 32], size=200)
        unrelated = candidate("t1.nii", "t1 mprage", shape=[64, 64, 32])
        mip = candidate("mip.nii", "mra batchmip", shape=[64, 64, 8])
        corrupt = candidate("broken.nii", "mra", shape=[], load_error="bad header")
        selected, report = converter._rank_candidate(
            [unrelated, mip, corrupt, usable], ("mra", "tof"), "MRA"
        )
        self.assertIs(selected, usable)
        self.assertEqual(report["eligible_candidate_count"], 1)
        self.assertEqual(report["ignored_candidate_count"], 3)
        self.assertIn("nonmatching_or_unsupported_series_ignored", report["warnings"])
        reasons = {row["name"]: row["reason"] for row in report["candidates"]}
        self.assertIn("derived/localizer", reasons["mip.nii"])
        self.assertIn("unreadable", reasons["broken.nii"])

        selected, derived_only = converter._rank_candidate([mip], ("mra", "tof"), "MRA")
        self.assertIsNone(selected)
        self.assertEqual(derived_only["eligible_candidate_count"], 0)

        second = candidate("tof-second.nii", "3d tof mra", shape=[64, 64, 32], size=300)
        selected, multiple = converter._rank_candidate([usable, second], ("mra", "tof"), "MRA")
        self.assertIs(selected, second)
        self.assertIn("multiple_matching_candidates_ranked_deterministically", multiple["warnings"])

    def test_conversion_result_requires_both_modalities_and_preserves_evidence(self) -> None:
        case_dir = self.cases / "conversion-boundaries"
        patient = case_dir / "patient_input"
        patient.mkdir(parents=True)
        selection = {"records": [{"modality": "MRA", "selected_candidate": {"name": "tof.nii"}}]}
        atomic_json(patient / "dicom_selection.json", selection)
        for available, missing in (("MRA.nii", "mrv"), ("MRV.nii", "mra")):
            with self.subTest(available=available):
                for path in (patient / "MRA.nii", patient / "MRV.nii"):
                    path.unlink(missing_ok=True)
                nib.save(
                    nib.Nifti1Image(np.zeros((2, 2, 2), dtype=np.float32), np.eye(4)),
                    patient / available,
                )
                with self.assertRaises(PipelineFailure) as raised:
                    conversion_result(case_dir)
                self.assertEqual(raised.exception.code, "MISSING_REQUIRED_MODALITY")
                self.assertEqual(raised.exception.details["missing_modalities"], [missing])
                self.assertEqual(raised.exception.details["selection"], selection)
                single = conversion_result(case_dir, "artery" if available == "MRA.nii" else "vein")
                self.assertEqual(list(single["outputs"]), [available[:3].lower()])

        for name in ("MRA.nii", "MRV.nii"):
            nib.save(
                nib.Nifti1Image(np.zeros((2, 2, 2), dtype=np.float32), np.eye(4)),
                patient / name,
            )
        result = conversion_result(case_dir)
        self.assertEqual(set(result["outputs"]), {"mra", "mrv"})
        self.assertEqual(set(result["artifacts"]), {"mra", "mrv"})
        self.assertTrue(all(len(item["sha256"]) == 64 for item in result["artifacts"].values()))
        self.assertEqual(result["selection"], selection)

        # Format-only conversion succeeds with an arbitrary single 4D series, no MRA/MRV pair.
        nifti_dir = patient / "nifti"
        nifti_dir.mkdir()
        output = nifti_dir / "series-01.nii"
        nib.save(nib.Nifti1Image(np.zeros((2, 2, 2, 3), dtype=np.float32), np.eye(4)), output)
        for path in (patient / "MRA.nii", patient / "MRV.nii"):
            path.unlink()
        result = conversion_result(case_dir, "nifti")
        self.assertEqual(result["outputs"], {output.name: str(output)})
        self.assertEqual(result["validation"][output.name]["shape"], [2, 2, 2, 3])
        output.write_bytes(output.read_bytes()[:352])
        with self.assertRaises(PipelineFailure) as raised:
            conversion_result(case_dir, "nifti")
        self.assertEqual(raised.exception.code, "INVALID_CONVERTED_NIFTI")
        output.unlink()
        with self.assertRaises(PipelineFailure) as raised:
            conversion_result(case_dir, "nifti")
        self.assertEqual(raised.exception.code, "NO_NIFTI_OUTPUT")

    def test_nifti_mode_is_persisted_and_cannot_start_reconstruction(self) -> None:
        case_id = self.create_case()
        with patch.object(self.service, "_create_job", return_value={"job_id": "job-nifti", "status": "queued"}) as create:
            self.service.start_conversion(case_id, conversion_mode="nifti")
        self.assertEqual(create.call_args.args[2]["conversion_mode"], "nifti")
        self.assertEqual(self.service.case_status(case_id)["conversion_mode"], "nifti")
        self.assertFalse(self.service.case_status(case_id)["conversion_ready"])
        with self.assertRaisesRegex(ValueError, "NIfTI-only"):
            self.service.start_candidate(case_id, "baseline", 800, 0.85, 1000)
        case_dir = self.cases / case_id
        output = case_dir / "series.nii"
        output.write_bytes(b"test output")
        manifest = json.loads((case_dir / "case.json").read_text(encoding="utf-8"))
        manifest.update(conversion_status="succeeded", nifti_outputs={"series": str(output)})
        atomic_json(case_dir / "case.json", manifest)
        completed = self.service.start_conversion(case_id, conversion_mode="nifti")
        self.assertEqual(completed["status"], "already_succeeded")
        self.assertEqual(completed["outputs"], {"series": str(output)})
        # Before candidates exist, a format-only case can prepare single-vessel inputs on request.
        with patch.object(self.service, "_create_job", return_value={"job_id": "job-artery", "status": "queued"}) as create:
            self.service.start_conversion(case_id, conversion_mode="artery")
        self.assertEqual(create.call_args.args[2]["conversion_mode"], "artery")

    def test_conversion_rejects_same_source_invalid_nifti_and_clears_stale_outputs(self) -> None:
        case_dir = self.cases / "conversion-safety"
        patient = case_dir / "patient_input"
        patient.mkdir(parents=True)
        source = str(case_dir / "temp" / "shared.nii")
        atomic_json(
            patient / "dicom_selection.json",
            {
                "records": [
                    {"modality": "MRA", "selected_candidate": {"path": source}},
                    {"modality": "MRV", "selected_candidate": {"path": source}},
                ]
            },
        )
        for name in ("MRA.nii", "MRV.nii"):
            nib.save(
                nib.Nifti1Image(np.zeros((2, 2, 2), dtype=np.float32), np.eye(4)),
                patient / name,
            )
        with self.assertRaises(PipelineFailure) as raised:
            conversion_result(case_dir)
        self.assertEqual(raised.exception.code, "AMBIGUOUS_MODALITY_SELECTION")

        atomic_json(patient / "dicom_selection.json", {"records": []})
        (patient / "MRV.nii").write_bytes(b"not-a-nifti")
        with self.assertRaises(PipelineFailure) as raised:
            conversion_result(case_dir)
        self.assertEqual(raised.exception.code, "INVALID_CONVERTED_NIFTI")
        self.assertEqual(raised.exception.details["modality"], "mrv")

        for shape in ((2, 2), (2, 2, 1), (2, 2, 2, 2)):
            with self.subTest(shape=shape):
                for name in ("MRA.nii", "MRV.nii"):
                    nib.save(
                        nib.Nifti1Image(np.zeros((2, 2, 2), dtype=np.float32), np.eye(4)),
                        patient / name,
                    )
                nib.save(
                    nib.Nifti1Image(np.zeros(shape, dtype=np.float32), np.eye(4)),
                    patient / "MRV.nii",
                )
                with self.assertRaises(PipelineFailure) as raised:
                    conversion_result(case_dir)
                self.assertEqual(raised.exception.code, "INVALID_CONVERTED_NIFTI")

        clear_conversion_outputs(case_dir)
        for name in ("MRA.nii", "MRV.nii", "dicom_selection.json"):
            self.assertFalse((patient / name).exists())

    def test_conversion_rejects_changed_input_and_duplicate_active_job(self) -> None:
        case_id = self.create_case()
        source = self.inputs / "dicom"
        (source / "added.dcm").write_bytes(b"changed")
        with self.assertRaises(VesselPilotInputError) as raised:
            self.service.start_conversion(case_id)
        self.assertEqual(raised.exception.code, "INPUT_CHANGED_SINCE_INSPECTION")

        (source / "added.dcm").unlink()
        case_dir = self.cases / case_id
        manifest_path = case_dir / "case.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["conversion_status"] = "queued"
        manifest["conversion_job_id"] = "job-active"
        atomic_json(manifest_path, manifest)
        job_dir = case_dir / "jobs" / "job-active"
        job_dir.mkdir(parents=True)
        atomic_json(
            job_dir / "state.json",
            {
                "schema_version": 1,
                "job_id": "job-active",
                "case_id": case_id,
                "kind": "conversion",
                "status": "running",
                "created_at": "2026-10-13T00:00:00+00:00",
            },
        )
        duplicate = self.service.start_conversion(case_id)
        self.assertTrue(duplicate["already_running"])
        self.assertEqual(duplicate["job_id"], "job-active")

    def test_candidate_requires_successful_conversion_manifest(self) -> None:
        case_id = self.create_case()
        patient = self.cases / case_id / "patient_input"
        patient.mkdir()
        (patient / "MRA.nii").write_bytes(b"stale-mra")
        (patient / "MRV.nii").write_bytes(b"stale-mrv")
        with self.assertRaisesRegex(ValueError, "conversion must succeed"):
            self.service.start_candidate(case_id, "baseline", 800, 0.85, 1000)

        manifest_path = self.cases / case_id / "case.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["conversion_status"] = "succeeded"
        manifest["conversion_outputs"] = {
            "mra": {"size": len(b"stale-mra"), "sha256": "0" * 64},
            "mrv": {"size": len(b"stale-mrv"), "sha256": "0" * 64},
        }
        atomic_json(manifest_path, manifest)
        with self.assertRaisesRegex(ValueError, "changed after validation"):
            self.service.start_candidate(case_id, "baseline", 800, 0.85, 1000)

    def test_folder_picker_returns_only_allowed_directory(self) -> None:
        dicom = self.inputs / "chosen"
        dicom.mkdir()
        with patch(
            "service.subprocess.run",
            return_value=SimpleNamespace(returncode=0, stdout=str(dicom)),
        ) as run_picker:
            selected = self.service.choose_dicom_folder()
        self.assertEqual(selected, {"status": "selected", "input_path": str(dicom.resolve())})
        picker_script = run_picker.call_args.args[0][-1]
        self.assertIn("$owner.TopMost = $true", picker_script)
        self.assertIn("[VesselPilotNativeWindow]::SetWindowPos", picker_script)
        self.assertIn("[VesselPilotNativeWindow]::SetForegroundWindow", picker_script)
        self.assertIn("$dialog.ShowDialog($owner)", picker_script)
        outside = self.root / "outside"
        outside.mkdir()
        with patch(
            "service.subprocess.run",
            return_value=SimpleNamespace(returncode=0, stdout=str(outside)),
        ):
            refused = self.service.choose_dicom_folder()
        self.assertEqual(refused["status"], "outside_input_roots")

    def test_validates_custom_parameters_and_builds_only_requested_stage(self) -> None:
        case_id = self.create_case()
        patient = self.cases / case_id / "patient_input"
        patient.mkdir()
        for name in ("MRA", "MRV"):
            nib.save(nib.Nifti1Image(np.ones((4, 4, 4), dtype=np.float32), np.eye(4)), patient / f"{name}.nii")
        manifest_path = self.cases / case_id / "case.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest.update(conversion_status="succeeded", conversion_outputs={
            name.lower(): {"size": (patient / f"{name}.nii").stat().st_size, "sha256": sha256_file(patient / f"{name}.nii")}
            for name in ("MRA", "MRV")
        })
        atomic_json(manifest_path, manifest)
        for target, supplied in (("artery", {"vessel_threshold": 750.5}), ("vein", {"mrv_weak_grow_tolerance": 0.87})):
            with self.subTest(target=target), patch.object(self.service, "_create_job", return_value={"status": "queued"}) as create:
                self.service.start_candidate(case_id, target, target=target, parameters=supplied)
                payload = create.call_args.args[2]
                self.assertEqual(payload["target"], target)
                for key, value in supplied.items():
                    self.assertEqual(payload["parameters"][key], value)
                commands = candidate_commands({"case_dir": str(self.cases / case_id), "payload": payload,
                                               "python_exe": "python", "vascular_script": "script"})
                self.assertEqual(len(commands), 1)
                self.assertEqual(commands[0][0], f"{target}_reconstruction")
                self.assertEqual(commands[0][2].name, f"{target}.glb")
                if target == "vein":
                    self.assertIn(str(patient / "MRV.nii"), commands[0][1])
                    self.assertNotIn(str(patient / "MRA.nii"), commands[0][1])
                    prior = commands[0][1][-1]
                    payload["parameters"]["mrv_frangi_sigmas_end"] = 8
                    changed = candidate_commands({"case_dir": str(self.cases / case_id), "payload": payload,
                                                  "python_exe": "python", "vascular_script": "script"})
                    self.assertNotEqual(prior, changed[0][1][-1])
        for target, invalid in (("artery", {"vessel_threshold": -1}), ("artery", {"vessel_threshold": float("nan")}),
                                ("artery", {"vessel_threshold": True}), ("artery", {"mrv_weak_grow_tolerance": 0.8}),
                                ("both", {"vessel_min_object_size": 1.5}), ("both", {"marching_cubes_level": 1}),
                                ("both", {"shell": "bad"}), ("both", {"mrv_frangi_sigmas_start": 12})):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                self.service.start_candidate(case_id, "invalid", target=target, parameters=invalid)
        with self.assertRaisesRegex(ValueError, "Conflicting"):
            self.service.start_candidate(case_id, "invalid", vessel_threshold=750, parameters={"vessel_threshold": 850})
        with self.assertRaisesRegex(ValueError, "immutable"):
            self.service.start_candidate(case_id, "artery", target="artery")
        with self.assertRaisesRegex(ValueError, "existing candidates"):
            self.service.start_conversion(case_id, conversion_mode="vein")

    def test_job_returns_authoritative_elapsed_time_and_polling_guidance(self) -> None:
        case_id = self.create_case()
        job_dir = self.cases / case_id / "jobs" / "job-test"
        job_dir.mkdir(parents=True)
        atomic_json(
            job_dir / "state.json",
            {
                "schema_version": 1,
                "job_id": "job-test",
                "case_id": case_id,
                "kind": "candidate",
                "status": "running",
                "phase": "vein_reconstruction",
                "started_at": "2026-10-12T11:27:52+00:00",
            },
        )
        running = self.service._job_snapshot("job-test", case_id)
        self.assertEqual(running["recommended_poll_after_seconds"], 55)
        self.assertEqual(running["recommended_status_update_after_seconds"], 180)
        self.assertEqual(running["typical_duration_minutes"], 20)
        self.assertGreater(running["elapsed_seconds"], 0)
        atomic_json(
            job_dir / "state.json",
            {
                "schema_version": 1,
                "job_id": "job-test",
                "case_id": case_id,
                "kind": "candidate",
                "status": "succeeded",
                "phase": "complete",
                "started_at": "2026-10-12T11:27:52+00:00",
                "finished_at": "2026-10-12T11:41:30+00:00",
            },
        )
        terminal = self.service.get_job("job-test", case_id)
        self.assertEqual(terminal["recommended_poll_after_seconds"], 0)
        self.assertEqual(terminal["elapsed_seconds"], 818.0)
        self.assertEqual(terminal["elapsed_minutes"], 13.63)

    def test_evaluates_and_finalizes_two_valid_glbs(self) -> None:
        case_id = self.create_case()
        candidate = self.cases / case_id / "candidates" / "baseline"
        candidate.mkdir(parents=True)
        atomic_json(
            candidate / "parameters.json",
            {
                "vessel_threshold": 800,
                "mrv_weak_grow_tolerance": 0.85,
                "mrv_post_process_min_size": 1000,
            },
        )
        trimesh.creation.icosphere(subdivisions=1).export(candidate / "artery.glb")
        trimesh.creation.cylinder(radius=0.4, height=2.0).export(candidate / "vein.glb")
        report = self.service.evaluate_candidate(case_id, "baseline")
        self.assertEqual(report["conclusion"], "pass")
        self.assertEqual(set(report["metrics"]), {"artery", "vein"})
        distribution = report["vein_distribution_proxy"]
        self.assertEqual(distribution["method"], "expanded_artery_aabb_v1")
        self.assertAlmostEqual(
            distribution["intracranial_proxy_area_ratio"]
            + distribution["scalp_peripheral_proxy_area_ratio"],
            1.0,
            places=5,
        )
        self.assertEqual(len(list((candidate / "previews" / "artery").glob("*.png"))), 7)
        self.assertTrue((candidate / "previews" / "artery" / "montage.png").is_file())
        self.assertTrue((candidate / "previews" / "vein" / "montage.png").is_file())
        self.assertLess((candidate / "previews" / "artery" / "montage.png").stat().st_size, 2 * 1024 * 1024)
        self.assertLess((candidate / "previews" / "vein" / "montage.png").stat().st_size, 2 * 1024 * 1024)
        final = self.service.finalize_case(case_id, "baseline")
        self.assertTrue(Path(final["artifacts"]["artery_glb"]).is_file())
        self.assertTrue(Path(final["artifacts"]["vein_glb"]).is_file())
        for target in ("artery", "vein"):
            with self.subTest(target=target):
                single = candidate.parent / target
                single.mkdir()
                atomic_json(single / "candidate.json", {"target": target})
                atomic_json(single / "parameters.json", normalize_parameters(target))
                trimesh.creation.icosphere(subdivisions=1).export(single / f"{target}.glb")
                report = self.service.evaluate_candidate(case_id, target)
                self.assertEqual(report["conclusion"], "pass")
                self.assertEqual(set(report["metrics"]), {target})
                self.assertEqual(set(report["preview_montages"]), {target})
                self.assertIsNone(report["vein_distribution_proxy"])
                final = self.service.finalize_case(case_id, target)
                self.assertEqual(final["target"], target)
                self.assertEqual(set(final["checksums"]), {f"{target}_glb"})
                other = "vein" if target == "artery" else "artery"
                self.assertNotIn(f"{other}_glb", final["artifacts"])
                (single / f"{target}.glb").write_bytes(b"changed")
                with self.assertRaisesRegex(ValueError, "changed after evaluation"):
                    self.service.finalize_case(case_id, target)

    def test_suggests_one_untried_parameter_change(self) -> None:
        case_id = self.create_case()
        candidate = self.cases / case_id / "candidates" / "baseline"
        candidate.mkdir(parents=True)
        atomic_json(
            candidate / "parameters.json",
            {
                "vessel_threshold": 800,
                "mrv_weak_grow_tolerance": 0.85,
                "mrv_post_process_min_size": 1000,
            },
        )
        atomic_json(candidate / "report.json", {"conclusion": "pass"})
        suggestion = self.service.suggest_parameters(
            case_id, "baseline", "too_dense", "good"
        )
        self.assertEqual(suggestion["status"], "recommended")
        self.assertEqual(suggestion["parameters"]["vessel_threshold"], 900)
        self.assertEqual(suggestion["changed_parameter_count"], 1)
        scalp = self.service.suggest_parameters(
            case_id, "baseline", "good", "scalp_dominant"
        )
        self.assertEqual(scalp["status"], "recommended")
        self.assertEqual(scalp["parameters"]["mrv_weak_grow_tolerance"], 0.88)
        self.assertIn("scalp/peripheral", scalp["reason"])
        uncertain = self.service.suggest_parameters(case_id, "baseline", "too_dense", "uncertain")
        self.assertEqual(uncertain["status"], "needs_human_review")
        limited = self.service.suggest_parameters(case_id, "baseline", "too_dense", "good", max_candidates=1)
        self.assertEqual(limited["status"], "budget_exhausted")
        custom = self.service.suggest_parameters(case_id, "baseline", "too_dense", "good",
                                                search_space={"vessel_threshold": [800, 850, 875]})
        self.assertEqual(custom["parameters"]["vessel_threshold"], 850)
        locked = self.service.suggest_parameters(case_id, "baseline", "too_dense", "good",
                                                locked_parameters=["vessel_threshold"])
        self.assertEqual(locked["status"], "needs_human_review")
        # An arbitrary user threshold can be a baseline, and the absent vessel needs no assessment.
        atomic_json(candidate / "candidate.json", {"target": "artery"})
        atomic_json(candidate / "parameters.json", {"vessel_threshold": 750})
        single = self.service.suggest_parameters(case_id, "baseline", artery_assessment="too_dense")
        self.assertEqual(single["target"], "artery")
        self.assertEqual(single["parameters"]["vessel_threshold"], 850)
        self.assertNotIn("mrv_weak_grow_tolerance", single["parameters"])
        trial = candidate.parent / "tried"
        trial.mkdir()
        atomic_json(trial / "candidate.json", {"target": "artery"})
        atomic_json(trial / "parameters.json", single["parameters"])
        exhausted = self.service.suggest_parameters(case_id, "baseline", artery_assessment="too_dense")
        self.assertEqual(exhausted["status"], "needs_human_review")


class McpProtocolTest(unittest.TestCase):
    @unittest.skipUnless(
        os.environ.get("VESSELPILOT_RUN_RECONSTRUCTION_TESTS") == "1",
        "Real reconstruction requires explicit opt-in; default tests only verify flow and contracts",
    )
    def test_real_single_and_both_vessel_jobs_with_synthetic_volumes(self) -> None:
        # Exercise the job runner and actual reconstruction script without patient data or long jobs.
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            settings = Settings.discover(HERE / "server.py", root / "cases", [root])
            service = VesselPilotService(settings)
            x, y, z = np.indices((24, 24, 24))
            data = (1000 * np.exp(-((x - 12) ** 2 + (y - 12) ** 2) / 12) * (1 + 0.1 * np.sin(z))).astype(np.float32)
            for target in ("artery", "vein", "both"):
                with self.subTest(target=target):
                    source = root / target
                    source.mkdir()
                    (source / "synthetic.dcm").write_bytes(b"synthetic registration fixture")
                    service.inspect_dicom_case(str(source), True, target)
                    case_dir = settings.case_root / target
                    patient = case_dir / "patient_input"
                    patient.mkdir()
                    modalities = ("MRA",) if target == "artery" else ("MRV",) if target == "vein" else ("MRA", "MRV")
                    for name in modalities:
                        nib.save(nib.Nifti1Image(data, np.eye(4)), patient / f"{name}.nii")
                    manifest_path = case_dir / "case.json"
                    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                    manifest.update(conversion_status="succeeded", conversion_mode="vessel" if target == "both" else target,
                                    conversion_outputs={name.lower(): {"size": (patient / f"{name}.nii").stat().st_size,
                                    "sha256": sha256_file(patient / f"{name}.nii")} for name in modalities})
                    atomic_json(manifest_path, manifest)
                    supplied = {}
                    if target != "vein":
                        supplied.update(vessel_threshold=650, vessel_min_object_size=1, vessel_decimation_fraction=1)
                    if target != "artery":
                        supplied.update(mrv_frangi_sigmas_end=3, mrv_strong_seed_percentile=80,
                                        mrv_weak_seed_percentile=60, mrv_strong_grow_tolerance=0.7,
                                        mrv_weak_grow_tolerance=0.5, mrv_post_process_min_size=1,
                                        min_object_size=1, mesh_decimation_fraction=1)
                    # Capture the service's public execution payload, then run it synchronously for bounded cleanup.
                    with patch.object(service, "_create_job", return_value={"job_id": "synthetic"}) as create:
                        service.start_candidate(target, "run", target=target, parameters=supplied)
                    job_dir = case_dir / "jobs" / "synthetic"
                    job_dir.mkdir(parents=True)
                    atomic_json(job_dir / "spec.json", {"kind": "candidate", "case_id": target,
                                "case_dir": str(case_dir), "python_exe": sys.executable,
                                "vascular_script": str(settings.vascular_script), "payload": create.call_args.args[2]})
                    atomic_json(job_dir / "state.json", {"job_id": "synthetic", "case_id": target, "status": "queued"})
                    process = subprocess.run([sys.executable, str(HERE / "job_runner.py"), "--spec", str(job_dir / "spec.json")],
                                             capture_output=True, text=True, encoding="utf-8", timeout=45,
                                             env={**os.environ, "PYTHONUTF8": "1"})
                    state = json.loads((job_dir / "state.json").read_text(encoding="utf-8"))
                    self.assertEqual(process.returncode, 0, state.get("error", process.stderr))
                    self.assertEqual(state["status"], "succeeded")
                    expected = {"artery", "vein"} if target == "both" else {target}
                    self.assertEqual({key[:-4] for key in state["result"] if key.endswith("_glb")}, expected)
                    report = service.evaluate_candidate(target, "run")
                    self.assertEqual(report["conclusion"], "pass")
                    self.assertEqual(set(report["metrics"]), expected)
                    final = service.finalize_case(target, "run")
                    self.assertEqual(final["target"], target)

    def test_stdio_initialize_list_and_call(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "输出_🧠"
            root.mkdir()
            inputs = root / "inputs"
            inputs.mkdir()
            dicom = inputs / "数据集_病例"
            dicom.mkdir()
            (dicom / "one.dcm").write_bytes(b"synthetic")
            process = subprocess.Popen(
                [
                    sys.executable,
                    str(HERE / "server.py"),
                    "--case-root",
                    str(root / "cases"),
                    "--input-root",
                    str(inputs),
                ],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                env={**os.environ, "PYTHONUTF8": "0", "PYTHONIOENCODING": "gbk"},
            )

            def call(request: dict) -> dict:
                assert process.stdin is not None
                assert process.stdout is not None
                process.stdin.write(json.dumps(request, ensure_ascii=False) + "\n")
                process.stdin.flush()
                response = json.loads(process.stdout.readline())
                self.assertEqual(response.get("id"), request["id"])
                return response

            try:
                initialized = call(
                    {
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "initialize",
                        "params": {"protocolVersion": "2025-03-26", "capabilities": {}},
                    }
                )
                self.assertEqual(initialized["result"]["serverInfo"]["name"], "vessel-pilot")
                listed = call({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
                names = {tool["name"] for tool in listed["result"]["tools"]}
                self.assertIn("start_vessel_candidate", names)
                self.assertIn("choose_dicom_folder", names)
                self.assertIn("suggest_vessel_parameters", names)
                job_tool = next(
                    tool for tool in listed["result"]["tools"] if tool["name"] == "get_vessel_job"
                )
                self.assertTrue(job_tool["annotations"]["readOnlyHint"])
                inspected = call(
                    {
                        "jsonrpc": "2.0",
                        "id": 3,
                        "method": "tools/call",
                        "params": {
                            "name": "inspect_dicom_case",
                            "arguments": {
                                "input_path": str(dicom),
                                "confirm_deidentified": True,
                                "case_id": "case-protocol",
                            },
                        },
                    }
                )
                self.assertFalse(inspected["result"]["isError"])
                self.assertEqual(
                    inspected["result"]["structuredContent"]["case_id"], "case-protocol"
                )
                invalid = inputs / "not-dicom"
                invalid.mkdir()
                (invalid / "notes.txt").write_text("not imaging data", encoding="utf-8")
                refused = call(
                    {
                        "jsonrpc": "2.0",
                        "id": 7,
                        "method": "tools/call",
                        "params": {
                            "name": "inspect_dicom_case",
                            "arguments": {
                                "input_path": str(invalid),
                                "confirm_deidentified": True,
                            },
                        },
                    }
                )
                self.assertTrue(refused["result"]["isError"])
                self.assertEqual(
                    refused["result"]["structuredContent"]["error"]["code"],
                    "INPUT_NO_DICOM_FILES",
                )
                candidate = root / "cases" / "case-protocol" / "candidates" / "baseline"
                candidate.mkdir(parents=True)
                atomic_json(
                    candidate / "parameters.json",
                    {
                        "vessel_threshold": 800,
                        "mrv_weak_grow_tolerance": 0.85,
                        "mrv_post_process_min_size": 1000,
                    },
                )
                trimesh.creation.icosphere(subdivisions=1).export(candidate / "artery.glb")
                trimesh.creation.cylinder(radius=0.4, height=2.0).export(candidate / "vein.glb")
                evaluated = call(
                    {
                        "jsonrpc": "2.0",
                        "id": 4,
                        "method": "tools/call",
                        "params": {
                            "name": "evaluate_vessel_candidate",
                            "arguments": {
                                "case_id": "case-protocol",
                                "candidate_id": "baseline",
                            },
                        },
                    }
                )
                self.assertFalse(evaluated["result"]["isError"])
                self.assertEqual(
                    [block["type"] for block in evaluated["result"]["content"]],
                    ["text", "image", "image"],
                )
                preview = json.loads(evaluated["result"]["content"][0]["text"])["visualization"]
                self.assertEqual(preview["candidate_id"], "baseline")
                self.assertEqual(len(preview["images"]), 2)
                self.assertEqual(
                    evaluated["result"]["structuredContent"]["conclusion"], "pass"
                )
                job_dir = root / "cases" / "case-protocol" / "jobs" / "job-wait"
                job_dir.mkdir(parents=True)
                atomic_json(
                    job_dir / "state.json",
                    {
                        "schema_version": 1,
                        "job_id": "job-wait",
                        "case_id": "case-protocol",
                        "kind": "candidate",
                        "status": "running",
                        "phase": "artery_reconstruction",
                        "started_at": "2026-10-12T11:27:52+00:00",
                    },
                )
                assert process.stdin is not None
                assert process.stdout is not None
                started = time.monotonic()
                for request in (
                    {
                        "jsonrpc": "2.0",
                        "id": 5,
                        "method": "tools/call",
                        "params": {
                            "name": "get_vessel_job",
                            "arguments": {
                                "case_id": "case-protocol",
                                "job_id": "job-wait",
                                "wait_seconds": 5,
                            },
                        },
                    },
                    {
                        "jsonrpc": "2.0",
                        "id": 6,
                        "method": "tools/call",
                        "params": {
                            "name": "cancel_vessel_job",
                            "arguments": {"case_id": "case-protocol", "job_id": "job-wait"},
                        },
                    },
                ):
                    process.stdin.write(json.dumps(request) + "\n")
                process.stdin.flush()
                replies = [json.loads(process.stdout.readline()) for _ in range(2)]
                self.assertEqual({item["id"] for item in replies}, {5, 6})
                self.assertLess(time.monotonic() - started, 4)
                self.assertTrue(
                    all(item["result"]["structuredContent"]["status"] == "cancelled" for item in replies)
                )
            finally:
                process.terminate()
                process.wait(timeout=10)
                if process.stdin is not None:
                    process.stdin.close()
                if process.stdout is not None:
                    process.stdout.close()
                if process.stderr is not None:
                    process.stderr.close()


if __name__ == "__main__":
    unittest.main()

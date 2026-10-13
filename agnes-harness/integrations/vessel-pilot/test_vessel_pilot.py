from __future__ import annotations

import json
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

from job_runner import PipelineFailure, clear_conversion_outputs, conversion_result  # noqa: E402
from service import Settings, VesselPilotInputError, VesselPilotService, atomic_json  # noqa: E402
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

    def test_rejects_candidate_outside_parameter_allowlist(self) -> None:
        case_id = self.create_case()
        patient = self.cases / case_id / "patient_input"
        patient.mkdir()
        (patient / "MRA.nii").write_bytes(b"placeholder")
        (patient / "MRV.nii").write_bytes(b"placeholder")
        with self.assertRaisesRegex(ValueError, "vessel_threshold"):
            self.service.start_candidate(case_id, "bad", 750, 0.85, 1000)

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


class McpProtocolTest(unittest.TestCase):
    def test_stdio_initialize_list_and_call(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            inputs = root / "inputs"
            inputs.mkdir()
            dicom = inputs / "dicom"
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
            )

            def call(request: dict) -> dict:
                assert process.stdin is not None
                assert process.stdout is not None
                process.stdin.write(json.dumps(request) + "\n")
                process.stdin.flush()
                return json.loads(process.stdout.readline())

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

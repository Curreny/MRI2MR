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

import trimesh

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from service import Settings, VesselPilotService, atomic_json  # noqa: E402


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

    def test_requires_deidentification_confirmation(self) -> None:
        with self.assertRaisesRegex(ValueError, "confirm_deidentified"):
            self.service.inspect_dicom_case(str(self.inputs), False)

    def test_folder_picker_returns_only_allowed_directory(self) -> None:
        dicom = self.inputs / "chosen"
        dicom.mkdir()
        with patch(
            "service.subprocess.run",
            return_value=SimpleNamespace(returncode=0, stdout=str(dicom)),
        ):
            selected = self.service.choose_dicom_folder()
        self.assertEqual(selected, {"status": "selected", "input_path": str(dicom.resolve())})
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

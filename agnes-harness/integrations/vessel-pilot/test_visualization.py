from __future__ import annotations

import base64
import hashlib
import json
import sys
import tempfile
import unittest
from io import BytesIO
from pathlib import Path

import nibabel as nib
import numpy as np
from PIL import Image
from pydicom.dataset import FileDataset, FileMetaDataset
from pydicom.uid import ExplicitVRLittleEndian, MRImageStorage, generate_uid

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from service import Settings, VesselPilotService, atomic_json
from visualization import tool_visualization


class VisualizationTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source = self.root / "input"
        self.source.mkdir()
        uid = generate_uid()
        for index in range(3):
            meta = FileMetaDataset()
            meta.TransferSyntaxUID = ExplicitVRLittleEndian
            meta.MediaStorageSOPClassUID = MRImageStorage
            meta.MediaStorageSOPInstanceUID = generate_uid()
            ds = FileDataset(str(self.source / f"{index}.dcm"), {}, file_meta=meta, preamble=b"\0" * 128)
            ds.is_little_endian, ds.is_implicit_VR = True, False
            ds.PatientName = "PRIVATE_NAME"
            ds.SeriesInstanceUID = uid
            ds.InstanceNumber = index
            ds.Rows, ds.Columns = 24, 32
            ds.SamplesPerPixel = 1
            ds.PhotometricInterpretation = "MONOCHROME2"
            ds.BitsAllocated, ds.BitsStored, ds.HighBit, ds.PixelRepresentation = 16, 16, 15, 0
            ds.PixelSpacing = [2, 1]
            ds.PixelData = (np.arange(24 * 32, dtype=np.uint16).reshape(24, 32) + index).tobytes()
            ds.save_as(str(self.source / f"{index}.dcm"), write_like_original=False)
        self.service = VesselPilotService(Settings.discover(HERE / "server.py", self.root / "cases", [self.root]))
        self.case = self.service.inspect_dicom_case(str(self.source), True, "case-preview")
        self.case_dir = self.root / "cases" / "case-preview"

    def tearDown(self):
        self.temp.cleanup()

    def check_images(self, visualization, blocks):
        self.assertEqual(len(visualization["images"]), len(blocks))
        for descriptor, block in zip(visualization["images"], blocks):
            raw = base64.b64decode(block["data"])
            self.assertEqual(descriptor["sha256"], hashlib.sha256(raw).hexdigest())
            self.assertEqual(descriptor["size"], len(raw))
            self.assertLessEqual(len(raw), 1024 * 1024)
            with Image.open(BytesIO(raw)) as image:
                image.verify()

    def test_dicom_pixels_without_header_overlays_and_unreadable_fallback(self):
        value, blocks = tool_visualization(self.service, "inspect_dicom_case", {"case_id": "case-preview"}, self.case)
        self.assertEqual(value["stage"], "dicom")
        self.assertEqual(len(blocks), 1)
        self.check_images(value, blocks)
        self.assertNotIn("PRIVATE_NAME", json.dumps(value))
        # Invalid/compressed pixels are a preview warning, not a pipeline failure.
        (self.case_dir / "previews" / "dicom.png").unlink()
        for file in self.source.iterdir():
            file.write_bytes(b"invalid DICOM")
        value, blocks = tool_visualization(self.service, "inspect_dicom_case", {"case_id": "case-preview"}, self.case)
        self.assertEqual(blocks, [])
        self.assertTrue(value["warnings"])

    def test_converted_4d_nifti_and_output_boundary(self):
        output = self.case_dir / "patient_input" / "MRA.nii"
        output.parent.mkdir()
        nib.save(nib.Nifti1Image(np.arange(8 * 9 * 10 * 2, dtype=np.float32).reshape(8, 9, 10, 2), np.diag([1, 2, 3, 1])), str(output))
        result = {"case_id": "case-preview", "kind": "conversion", "status": "succeeded", "result": {"outputs": {"mra": str(output)}}}
        value, blocks = tool_visualization(self.service, "get_vessel_job", {"case_id": "case-preview"}, result)
        self.assertEqual(value["stage"], "nifti")
        self.assertEqual(len(blocks), 1)
        self.check_images(value, blocks)
        result["result"]["outputs"]["outside"] = str(self.source / "0.dcm")
        value, blocks = tool_visualization(self.service, "get_vessel_job", {"case_id": "case-preview"}, result)
        self.assertEqual(len(blocks), 1)
        self.assertTrue(value["warnings"])
        # Three successful volume previews used to exceed the production MCP limit of two.
        result["result"]["outputs"] = {name: str(output) for name in ("mra", "mrv", "t1")}
        value, blocks = tool_visualization(self.service, "get_vessel_job", {"case_id": "case-preview"}, result)
        self.assertEqual(len(blocks), 1)
        self.assertTrue(all(name in value["images"][0]["label"] for name in ("mra", "mrv", "t1")))
        self.check_images(value, blocks)
        with Image.open(BytesIO(base64.b64decode(blocks[0]["data"]))) as image:
            self.assertLessEqual(image.width * image.height, 1456 * 1456)
        result["status"] = "running"
        self.assertEqual(tool_visualization(self.service, "get_vessel_job", {"case_id": "case-preview"}, result), (None, []))

    def test_only_initial_candidate_evaluation_carries_the_six_view_image(self):
        candidate = self.case_dir / "candidates" / "round-1"
        candidate.mkdir(parents=True)
        path = candidate / "montage.png"
        Image.new("RGB", (1440, 960), (200, 30, 30)).save(path)
        report = {"parameters": {"vessel_threshold": 800}, "metrics": {"artery": {"file_bytes": 100, "vertices": 20, "faces": 30}}, "conclusion": "pass", "preview_montages": {"artery": str(path)}}
        atomic_json(candidate / "report.json", report)
        stages = (
            ("evaluate_vessel_candidate", "candidate", report, {}),
            ("evaluate_vessel_candidate", "visual_qc", report, {"assessments": [{"label": "good", "reason": "visible"}]}),
            ("finalize_vessel_case", "final", {"parameters": {"vessel_threshold": 850}}, {}),
            ("suggest_vessel_parameters", "tuning", {"parameters": {"vessel_threshold": 850}, "reason": "Reduce noise", "status": "suggested"}, {}),
        )
        for name, stage, data, extra_arguments in stages:
            arguments = {"case_id": "case-preview", "candidate_id": "round-1", "artery_assessment": "too_dense", **extra_arguments}
            value, blocks = tool_visualization(self.service, name, arguments, data)
            self.assertEqual((value["stage"], value["case_id"], value["candidate_id"]), (stage, "case-preview", "round-1"))
            self.assertEqual(value["parameters"]["vessel_threshold"], 800)
            self.check_images(value, blocks)
            self.assertEqual(len(blocks), 1 if stage == "candidate" else 0)
            if stage == "tuning":
                self.assertEqual(value["decision"]["next_parameters"]["vessel_threshold"], 850)


if __name__ == "__main__":
    unittest.main()

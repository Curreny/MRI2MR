from __future__ import annotations

import argparse
import base64
import json
import sys
import threading
import traceback
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable

from service import Settings, VesselPilotService


PROTOCOL_VERSION = "2025-03-26"


def object_schema(properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }


TOOLS = [
    {
        "name": "choose_dicom_folder",
        "description": "Open a native Windows folder dialog so the user can select a deidentified DICOM directory under an allowed input root.",
        "inputSchema": object_schema({}, []),
        "annotations": {"readOnlyHint": True},
    },
    {
        "name": "inspect_dicom_case",
        "description": "Register and preflight a user-confirmed deidentified DICOM directory.",
        "inputSchema": object_schema(
            {
                "input_path": {"type": "string", "minLength": 1, "maxLength": 1024},
                "confirm_deidentified": {"type": "boolean", "const": True},
                "case_id": {
                    "type": "string",
                    "pattern": "^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$",
                },
            },
            ["input_path", "confirm_deidentified"],
        ),
    },
    {
        "name": "get_vessel_case",
        "description": "Read conversion and candidate status for a registered case.",
        "inputSchema": object_schema(
            {"case_id": {"type": "string", "pattern": "^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$"}},
            ["case_id"],
        ),
        "annotations": {"readOnlyHint": True},
    },
    {
        "name": "start_dicom_conversion",
        "description": "Start asynchronous DICOM to MRA/MRV NIfTI conversion.",
        "inputSchema": object_schema(
            {
                "case_id": {"type": "string", "pattern": "^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$"},
                "decompress_with_dcmtk": {"type": "boolean", "default": True},
            },
            ["case_id"],
        ),
    },
    {
        "name": "start_vessel_candidate",
        "description": "Start one immutable artery/vein reconstruction candidate using only the three allowed tuning parameters.",
        "inputSchema": object_schema(
            {
                "case_id": {"type": "string", "pattern": "^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$"},
                "candidate_id": {"type": "string", "pattern": "^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$"},
                "vessel_threshold": {"type": "number", "enum": [700, 800, 900]},
                "mrv_weak_grow_tolerance": {"type": "number", "enum": [0.83, 0.85, 0.88]},
                "mrv_post_process_min_size": {"type": "integer", "enum": [800, 1000, 1500]},
            },
            [
                "case_id",
                "candidate_id",
                "vessel_threshold",
                "mrv_weak_grow_tolerance",
                "mrv_post_process_min_size",
            ],
        ),
    },
    {
        "name": "get_vessel_job",
        "description": "Long-poll an asynchronous job. The server waits up to 55 seconds or until status/phase changes and returns authoritative elapsed time; never calculate elapsed time from timestamps.",
        "inputSchema": object_schema(
            {
                "case_id": {"type": "string", "pattern": "^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$"},
                "job_id": {"type": "string", "pattern": "^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$"},
                "wait_seconds": {"type": "integer", "minimum": 1, "maximum": 55, "default": 55},
            },
            ["case_id", "job_id"],
        ),
        "annotations": {"readOnlyHint": True},
    },
    {
        "name": "cancel_vessel_job",
        "description": "Cancel a running VesselPilot job and its child process tree.",
        "inputSchema": object_schema(
            {
                "case_id": {"type": "string", "pattern": "^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$"},
                "job_id": {"type": "string", "pattern": "^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$"},
            },
            ["case_id", "job_id"],
        ),
    },
    {
        "name": "list_vessel_candidates",
        "description": "List immutable candidates and any existing quality reports for a case.",
        "inputSchema": object_schema(
            {"case_id": {"type": "string", "pattern": "^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$"}},
            ["case_id"],
        ),
        "annotations": {"readOnlyHint": True},
    },
    {
        "name": "evaluate_vessel_candidate",
        "description": "Validate both GLBs, compute technical mesh metrics, and return artery/vein six-view montage images for visual parameter assessment.",
        "inputSchema": object_schema(
            {
                "case_id": {"type": "string", "pattern": "^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$"},
                "candidate_id": {"type": "string", "pattern": "^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$"},
            },
            ["case_id", "candidate_id"],
        ),
    },
    {
        "name": "suggest_vessel_parameters",
        "description": "Recommend one untried one-parameter change from an evaluated candidate and the model's artery/vein montage assessments.",
        "inputSchema": object_schema(
            {
                "case_id": {"type": "string", "pattern": "^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$"},
                "based_on_candidate_id": {"type": "string", "pattern": "^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$"},
                "artery_assessment": {"type": "string", "enum": ["good", "too_dense", "too_sparse", "uncertain"]},
                "vein_assessment": {"type": "string", "enum": ["good", "too_dense", "too_sparse", "uncertain"]},
            },
            ["case_id", "based_on_candidate_id", "artery_assessment", "vein_assessment"],
        ),
        "annotations": {"readOnlyHint": True},
    },
    {
        "name": "finalize_vessel_case",
        "description": "Finalize an evaluated technical-QC-passing candidate and create a manifest.",
        "inputSchema": object_schema(
            {
                "case_id": {"type": "string", "pattern": "^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$"},
                "candidate_id": {"type": "string", "pattern": "^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$"},
            },
            ["case_id", "candidate_id"],
        ),
    },
]


class McpServer:
    def __init__(self, service: VesselPilotService):
        self.service = service
        self.reply_lock = threading.Lock()
        self.wait_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="vessel-wait")
        self.tool_map: dict[str, Callable[..., dict[str, Any]]] = {
            "choose_dicom_folder": service.choose_dicom_folder,
            "inspect_dicom_case": service.inspect_dicom_case,
            "get_vessel_case": service.case_status,
            "start_dicom_conversion": service.start_conversion,
            "start_vessel_candidate": service.start_candidate,
            "get_vessel_job": service.get_job,
            "cancel_vessel_job": service.cancel_job,
            "list_vessel_candidates": service.list_candidates,
            "evaluate_vessel_candidate": service.evaluate_candidate,
            "suggest_vessel_parameters": service.suggest_parameters,
            "finalize_vessel_case": service.finalize_case,
        }

    def reply(self, request_id: Any, result: dict[str, Any] | None = None, error: dict[str, Any] | None = None) -> None:
        response: dict[str, Any] = {"jsonrpc": "2.0", "id": request_id}
        if error is not None:
            response["error"] = error
        else:
            response["result"] = result or {}
        with self.reply_lock:
            sys.stdout.write(json.dumps(response, ensure_ascii=False, separators=(",", ":")) + "\n")
            sys.stdout.flush()

    def call_tool(self, request_id: Any, name: Any, arguments: Any) -> None:
        try:
            if name not in self.tool_map:
                raise ValueError(f"Unknown tool: {name}")
            if not isinstance(arguments, dict):
                raise ValueError("Tool arguments must be an object")
            data = self.tool_map[name](**arguments)
            content: list[dict[str, Any]] = [
                {
                    "type": "text",
                    "text": json.dumps(data, ensure_ascii=False, separators=(",", ":")),
                }
            ]
            if name == "evaluate_vessel_candidate":
                for vessel, path_value in data.get("preview_montages", {}).items():
                    path = Path(path_value)
                    if path.is_file():
                        content.append(
                            {
                                "type": "image",
                                "data": base64.b64encode(path.read_bytes()).decode("ascii"),
                                "mimeType": "image/png",
                                "_meta": {"vessel": vessel},
                            }
                        )
            self.reply(
                request_id,
                {"content": content, "structuredContent": data, "isError": False},
            )
        except (TypeError, ValueError, OSError, RuntimeError) as exc:
            self.reply(
                request_id,
                {
                    "content": [{"type": "text", "text": str(exc)}],
                    "structuredContent": {
                        "error": {"code": type(exc).__name__.upper(), "message": str(exc)}
                    },
                    "isError": True,
                },
            )

    def handle(self, request: dict[str, Any]) -> None:
        method = request.get("method")
        request_id = request.get("id")
        if method == "initialize":
            self.reply(
                request_id,
                {
                    "protocolVersion": PROTOCOL_VERSION,
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "vessel-pilot", "version": "0.2.0"},
                },
            )
            return
        if method in {"notifications/initialized", "notifications/cancelled"}:
            return
        if method == "ping":
            self.reply(request_id, {})
            return
        if method == "tools/list":
            self.reply(request_id, {"tools": TOOLS})
            return
        if method == "tools/call":
            params = request.get("params") or {}
            name = params.get("name")
            arguments = params.get("arguments") or {}
            if name == "get_vessel_job":
                self.wait_executor.submit(self.call_tool, request_id, name, arguments)
            else:
                self.call_tool(request_id, name, arguments)
            return
        if request_id is not None:
            self.reply(request_id, error={"code": -32601, "message": f"Method not found: {method}"})

    def run(self) -> None:
        self.service.startup_check()
        try:
            for line in sys.stdin:
                if not line.strip():
                    continue
                try:
                    request = json.loads(line)
                    if not isinstance(request, dict):
                        raise ValueError("JSON-RPC request must be an object")
                    self.handle(request)
                except Exception as exc:
                    traceback.print_exc(file=sys.stderr)
                    self.reply(None, error={"code": -32700, "message": str(exc)})
        finally:
            self.wait_executor.shutdown(wait=False, cancel_futures=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="VesselPilot MCP stdio server")
    parser.add_argument("--case-root", type=Path)
    parser.add_argument("--input-root", action="append", type=Path, default=[])
    args = parser.parse_args()
    settings = Settings.discover(Path(__file__), args.case_root, args.input_root)
    McpServer(VesselPilotService(settings)).run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""In-memory fake of the SerialHop agent API for hermetic tests. No hardware, no network."""

from __future__ import annotations

import json
from typing import Any

import httpx

# Commands that start a job (immediate result is {"job": {...}}).
JOB_COMMANDS = {
    "dispense",
    "set_position",
    "measure",
    "measure_blank",
    "start_calibration",
    "read_raw",
}

# Canned "succeeded" job results per command.
JOB_RESULTS: dict[str, dict[str, Any]] = {
    "dispense": {"dispensed_ml": 10.0, "duration_s": 199.4, "mean_speed_ml_min": 3.01},
    "set_position": {"position": 4, "from_position": 1, "direction": "increasing"},
    "measure": {"absorbance": 0.523, "temperature_c": 36.98, "seq": 43},
    "measure_blank": {"slope": 123.45, "temperature_c": 36.9},
    "start_calibration": {"steps": 48000, "duration_s": 118.7},
    "read_raw": {"intensities": [1, 2, 3], "temperature_c": 36.9},
}


class FakeJob:
    def __init__(self, job_id: str, cmd: str) -> None:
        self.job_id = job_id
        self.cmd = cmd
        self.device = ""  # set by _command when the job is started
        self.state = "running"
        self.polls = 0
        self.result: dict[str, Any] | None = None
        self.error: dict[str, Any] | None = None


class FakeLab:
    def __init__(self) -> None:
        self.devices: dict[str, dict[str, Any]] = {}
        self.jobs: dict[str, FakeJob] = {}
        self.unreachable: set[str] = set()
        self.polls_to_complete = 1
        self.fail_job = False
        self._job_counter = 0
        # ---- Increment-4 executor test surface (default-inert) ----
        self.calls: list[tuple[str, str, dict[str, Any]]] = []
        self.record_polls = False
        self.fail_jobs: set[str] = set()
        self.cancel_jobs: set[str] = set()  # jobs of this cmd report state "cancelled"
        self.held_jobs: set[str] = set()
        self.polls_to_complete_by_cmd: dict[str, int] = {}
        self._injected: dict[tuple[str, str], list[tuple[str, str]]] = {}

    # ---- setup helpers ----
    def add_device(
        self, device_id: str, type_: str, identify: dict[str, Any] | None = None, **canned: Any
    ) -> None:
        self.devices[device_id] = {
            "id": device_id,
            "type": type_,
            "port": f"COM-{device_id}",
            "identify": identify,
            "_canned": canned,
        }

    def inject_error(
        self, device_id: str, cmd: str, code: str, message: str, *, times: int = 1
    ) -> None:
        """Queue an envelope error for the next `times` matching commands."""
        self._injected.setdefault((device_id, cmd), []).extend([(code, message)] * times)

    def hold_job(self, cmd: str) -> None:
        """Jobs of this command never advance by polling; use complete_job()."""
        self.held_jobs.add(cmd)

    def complete_job(self, job_id: str, *, error: dict[str, Any] | None = None) -> None:
        """Manually finish a (typically held) job."""
        job = self.jobs[job_id]
        if error is not None:
            job.state, job.error = "failed", error
        else:
            job.state, job.result = "succeeded", JOB_RESULTS.get(job.cmd, {})

    # ---- request routing ----
    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/api/v1/devices":
            return self._devices_list()
        if path == "/api/v1/discover":
            return self._devices_list()
        if path == "/devices/disconnect":
            return httpx.Response(200, json={"released": len(self.devices)})
        if path == "/agent/info":
            return httpx.Response(200, json={"version": "2.0.0+test", "hostname": "FAKE"})
        if path.startswith("/api/v1/devices/") and path.endswith("/command"):
            device_id = path[len("/api/v1/devices/") : -len("/command")]
            return self._command(device_id, json.loads(request.read()))
        return httpx.Response(404, json={"error": "not found"})

    def _devices_list(self) -> httpx.Response:
        devices = [
            {
                **{k: v for k, v in d.items() if not k.startswith("_")},
                "connected": d["id"] not in self.unreachable,
            }
            for d in self.devices.values()
        ]
        return httpx.Response(
            200, json={"devices": devices, "discovered_at": "2026-07-06T12:00:00Z"}
        )

    def _command(self, device_id: str, env: dict[str, Any]) -> httpx.Response:
        req_id = env.get("id", "")
        cmd = env.get("cmd")
        params = env.get("params") or {}

        def ok(result: Any) -> httpx.Response:
            return httpx.Response(200, json={"id": req_id, "status": "ok", "result": result})

        def err(status: int, code: str, message: str) -> httpx.Response:
            return httpx.Response(
                status,
                json={"id": req_id, "status": "error", "error": {"code": code, "message": message}},
            )

        # Unknown device must 404 before any memory-served branches.
        if device_id not in self.devices:
            return err(404, "unknown_device", f"no device with id {device_id}")

        if cmd != "get_job" or self.record_polls:
            self.calls.append((device_id, cmd or "", dict(params)))
        queue = self._injected.get((device_id, cmd or ""))
        if queue:
            code, message = queue.pop(0)
            return err(409 if code == "busy" else 500, code, message)

        # get_job / identify are memory-served (200 even if unreachable).
        if cmd == "get_job":
            job = self.jobs.get(params.get("job_id", ""))
            if job is None:
                return err(200, "invalid_params", "unknown job_id")
            self._advance(job)
            return ok(self._job_object(job))
        if cmd == "identify":
            ident = self.devices[device_id].get("identify")
            if ident is None:
                return err(503, "device_unreachable", "never attached")
            return ok(ident)

        if device_id in self.unreachable:
            return err(503, "device_unreachable", "device is not responding")

        if cmd == "ping":
            return ok({"uptime_ms": 8123456})
        if cmd == "status":
            return ok(self.devices[device_id].get("_canned", {}).get("status", {"state": "idle"}))
        if cmd == "stop":
            # A real agent's stop cancels whatever job that device is running.
            for job in self.jobs.values():
                if job.device == device_id and job.state == "running":
                    job.state = "cancelled"
            return ok({"state": "idle"})
        if cmd in JOB_COMMANDS:
            started = self._start_job(cmd)
            self.jobs[started["job_id"]].device = device_id
            return ok({"job": started})
        # other commands: return canned result or an empty ok.
        return ok(self.devices[device_id].get("_canned", {}).get(cmd, {}))

    # ---- job engine ----
    def _start_job(self, cmd: str) -> dict[str, Any]:
        self._job_counter += 1
        job = FakeJob(f"j-{self._job_counter}", cmd)
        self.jobs[job.job_id] = job
        return {"job_id": job.job_id, "state": "running", "estimated_duration_s": 1.0}

    def _advance(self, job: FakeJob) -> None:
        if job.state != "running" or job.cmd in self.held_jobs:
            return
        job.polls += 1
        threshold = self.polls_to_complete_by_cmd.get(job.cmd, self.polls_to_complete)
        if job.polls >= threshold:
            if job.cmd in self.cancel_jobs:  # someone stopped the device out of band
                job.state = "cancelled"
            elif self.fail_job or job.cmd in self.fail_jobs:
                job.state = "failed"
                job.error = {"code": "hardware_error", "message": "device became unreachable"}
            else:
                job.state = "succeeded"
                job.result = JOB_RESULTS.get(job.cmd, {})

    def _job_object(self, job: FakeJob) -> dict[str, Any]:
        progress = 1.0 if job.state == "succeeded" else (0.0 if job.state == "running" else 0.5)
        return {
            "job_id": job.job_id,
            "state": job.state,
            "progress": progress,
            "estimated_duration_s": 1.0,
            "elapsed_s": float(job.polls),
            "result": job.result,
            "error": job.error,
        }

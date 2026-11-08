"""Deploy guest scripts and run long jobs inside the Cua VM.

``cua sb exec`` has a transport-level cap of roughly two minutes, while an
Everygen generation or a platform upload can take 10-20 minutes.  Jobs are
therefore spawned detached on the guest and the host short-polls an exit file,
mirroring the proven v2-automation protocol.
"""

from __future__ import annotations

import fcntl
import json
import os
import shlex
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from pipeline.config import PipelineSettings
from pipeline.cua_sandbox import CuaError, CuaSandbox

GUEST_SCRIPTS = (
    "guest_accounts.py",
    "guest_everygen.py",
    "guest_open_logins.py",
    "upload_yt.py",
    "upload_tiktok.py",
)


class GuestError(RuntimeError):
    """Raised when the guest environment is incomplete or a job cannot start."""


@dataclass
class JobResult:
    ok: bool
    label: str
    exit_code: int | None = None
    payload: dict[str, Any] | None = None
    stdout: str = ""
    stderr: str = ""
    error: str | None = None
    run_dir: str = ""
    duration_s: float = 0.0
    evidence_dir: str = ""
    timed_out: bool = False
    raw: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "label": self.label,
            "exit_code": self.exit_code,
            "payload": self.payload,
            "stdout": self.stdout[-4000:],
            "stderr": self.stderr[-4000:],
            "error": self.error,
            "run_dir": self.run_dir,
            "duration_s": round(self.duration_s, 2),
            "evidence_dir": self.evidence_dir,
            "timed_out": self.timed_out,
        }


class GuestRunner:
    """Deploy and execute the self-contained guest scripts."""

    def __init__(
        self,
        settings: PipelineSettings,
        sandbox: CuaSandbox,
        *,
        poll_interval: int = 15,
    ) -> None:
        self.settings = settings
        self.sandbox = sandbox
        self.poll_interval = max(2, int(poll_interval))
        self.local_guest_dir = Path(__file__).resolve().parent / "guest"
        self._lock_path = Path(settings.data_dir) / ".guest.lock"

    # --------------------------------------------------------------- lifecycle
    @contextmanager
    def _browser_lock(self, timeout: int = 3600) -> Iterator[None]:
        """Serialize browser jobs: one Firefox launch per VM at a time."""
        self._lock_path.parent.mkdir(parents=True, exist_ok=True)
        handle = self._lock_path.open("w")
        deadline = time.monotonic() + timeout
        try:
            while True:
                try:
                    fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except (BlockingIOError, OSError):
                    if time.monotonic() > deadline:
                        raise GuestError("another guest browser job holds the lock")
                    time.sleep(5)
            handle.seek(0)
            handle.truncate()
            handle.write(f"pid={os.getpid()} at={datetime.now(timezone.utc).isoformat()}\n")
            handle.flush()
            yield
        finally:
            try:
                fcntl.flock(handle, fcntl.LOCK_UN)
            finally:
                handle.close()

    def ensure(self) -> dict[str, Any]:
        """Create guest directories and verify the browser automation runtime."""
        if not self.sandbox.enabled():
            raise GuestError("cua disabled")
        command = (
            f"mkdir -p {shlex.quote(self.settings.guest_script_dir)} "
            f"{shlex.quote(self.settings.guest_runs_dir)} "
            f"{shlex.quote(self.settings.guest_media_dir)}/gta_pipeline "
            f"{shlex.quote(self.settings.guest_download_dir)} && "
            f"test -x {shlex.quote(self.settings.guest_venv)} && "
            f"{shlex.quote(self.settings.guest_venv)} -c 'import selenium' && "
            f"test -d {shlex.quote(self.settings.guest_media_dir)}"
        )
        proc = self.sandbox.exec_raw(command, timeout=120)
        if proc.returncode != 0:
            detail = (proc.stderr or proc.stdout or "").strip()
            raise GuestError(
                "guest environment is incomplete "
                f"({detail or 'unknown error'}). Fix with: cua sb exec "
                f"{self.sandbox.name} \"mkdir -p {self.settings.guest_media_dir} "
                f"{self.settings.guest_download_dir} && "
                f"{self.settings.guest_venv} -m pip install selenium\""
            )
        return {"ok": True, "guest_profile": self.settings.guest_profile}

    def deploy(self) -> dict[str, Any]:
        """Copy the guest scripts to the VM (idempotent)."""
        missing = [
            str(self.local_guest_dir / name)
            for name in GUEST_SCRIPTS
            if not (self.local_guest_dir / name).is_file()
        ]
        if missing:
            raise GuestError(f"missing guest scripts: {', '.join(missing)}")
        for name in GUEST_SCRIPTS:
            self.sandbox.copy_to_guest(
                self.local_guest_dir / name,
                f"{self.settings.guest_script_dir}/{name}",
            )
        return {"ok": True, "scripts": list(GUEST_SCRIPTS)}

    # ------------------------------------------------------------------- jobs
    def _parse_payload(self, stdout: str) -> dict[str, Any] | None:
        text = (stdout or "").strip()
        if not text:
            return None
        try:
            whole = json.loads(text)
            return whole if isinstance(whole, dict) else None
        except ValueError:
            pass
        for line in reversed(text.splitlines()):
            line = line.strip()
            if not line.startswith("{"):
                continue
            try:
                value = json.loads(line)
            except ValueError:
                continue
            if isinstance(value, dict):
                return value
        return None

    def _write_job_log(self, label: str, result: JobResult) -> None:
        try:
            self.settings.logs_dir.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
            path = self.settings.logs_dir / f"{label}-{stamp}.json"
            path.write_text(
                json.dumps(result.to_dict(), indent=2, sort_keys=True, default=str),
                encoding="utf-8",
            )
        except OSError:
            pass

    def _collect_evidence(self, label: str, remote_run_dir: str) -> str:
        host_dir = (
            self.settings.evidence_dir
            / f"{label}-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}"
        )
        host_dir.mkdir(parents=True, exist_ok=True)
        for name in (
            "screenshot.png",
            "page.html",
            "result.json",
            "console.log",
            "youtube.html",
            "tiktok.html",
            "everygen.html",
        ):
            try:
                self.sandbox.copy_from_guest(
                    f"{remote_run_dir}/{name}", host_dir / name
                )
            except CuaError:
                continue
        return str(host_dir)

    def run(
        self,
        script: str,
        args: list[str] | None = None,
        *,
        label: str | None = None,
        timeout: int | None = None,
        poll_interval: int | None = None,
        collect_evidence: bool = True,
    ) -> JobResult:
        """Run one guest script detached and poll its exit file."""
        if script not in GUEST_SCRIPTS:
            raise GuestError(f"unknown guest script: {script}")
        label = label or Path(script).stem
        timeout = int(timeout or self.settings.everygen_timeout)
        poll = max(2, int(poll_interval or self.poll_interval))
        run_token = f"{label}-{uuid.uuid4().hex[:10]}"
        remote_run_dir = f"{self.settings.guest_runs_dir}/{run_token}"
        remote_script = f"{self.settings.guest_script_dir}/{script}"
        quoted_args = " ".join(shlex.quote(str(arg)) for arg in (args or []))
        command = (
            f"{shlex.quote(self.settings.guest_venv)} "
            f"{shlex.quote(remote_script)} {quoted_args}"
        ).strip()
        out_file = f"{remote_run_dir}/out.json"
        err_file = f"{remote_run_dir}/err.log"
        exit_file = f"{remote_run_dir}/exit"
        pid_file = f"{remote_run_dir}/pid"
        spawn = (
            f"mkdir -p {shlex.quote(remote_run_dir)} && "
            f"rm -f {shlex.quote(out_file)} {shlex.quote(err_file)} "
            f"{shlex.quote(exit_file)} {shlex.quote(pid_file)} && "
            f"( nohup env DISPLAY={shlex.quote(self.settings.guest_display)} "
            f"GTA_JOB_DIR={shlex.quote(remote_run_dir)} "
            f"{command} > {shlex.quote(out_file)} 2> {shlex.quote(err_file)}; "
            f"echo $? > {shlex.quote(exit_file)}; "
            f"rm -f {shlex.quote(pid_file)} ) &"
        )
        started = time.monotonic()
        with self._browser_lock():
            try:
                self.sandbox.exec_raw(spawn, timeout=90)
            except CuaError as error:
                result = JobResult(
                    ok=False,
                    label=label,
                    error=f"could not spawn guest job: {error}",
                    run_dir=remote_run_dir,
                )
                self._write_job_log(label, result)
                return result

            exit_code: int | None = None
            deadline = time.monotonic() + timeout
            while exit_code is None:
                try:
                    poll_proc = self.sandbox.exec_raw(
                        f"cat {shlex.quote(exit_file)} 2>/dev/null || echo -1",
                        timeout=30,
                    )
                    text = (poll_proc.stdout or "").strip()
                except CuaError as error:
                    result = JobResult(
                        ok=False,
                        label=label,
                        error=f"guest poll failed: {error}",
                        run_dir=remote_run_dir,
                        duration_s=time.monotonic() - started,
                    )
                    self._write_job_log(label, result)
                    return result
                if text and text != "-1":
                    try:
                        exit_code = int(text)
                    except ValueError:
                        exit_code = -1
                    break
                if time.monotonic() > deadline:
                    self._kill_guest_script(script)
                    result = JobResult(
                        ok=False,
                        label=label,
                        error=f"guest job timed out after {timeout}s",
                        run_dir=remote_run_dir,
                        duration_s=time.monotonic() - started,
                        timed_out=True,
                    )
                    if collect_evidence:
                        result.evidence_dir = self._collect_evidence(
                            label, remote_run_dir
                        )
                    self._write_job_log(label, result)
                    return result
                time.sleep(poll)

            stdout = ""
            stderr = ""
            try:
                stdout = (
                    self.sandbox.exec_raw(
                        f"cat {shlex.quote(out_file)} 2>/dev/null || true", timeout=30
                    ).stdout
                    or ""
                )
                stderr = (
                    self.sandbox.exec_raw(
                        f"cat {shlex.quote(err_file)} 2>/dev/null || true", timeout=30
                    ).stdout
                    or ""
                )
            except CuaError:
                pass
            payload = self._parse_payload(stdout)
            duration = time.monotonic() - started
            ok = exit_code == 0 and not (
                isinstance(payload, dict) and payload.get("ok") is False
            )
            error = None
            if isinstance(payload, dict):
                error = payload.get("error") or payload.get("message")
            elif stderr.strip():
                error = stderr.strip()[-1000:]
            elif exit_code != 0:
                error = f"guest exit {exit_code}"
            result = JobResult(
                ok=ok,
                label=label,
                exit_code=exit_code,
                payload=payload,
                stdout=stdout,
                stderr=stderr,
                error=str(error).strip() if error else None,
                run_dir=remote_run_dir,
                duration_s=duration,
            )
            if collect_evidence:
                result.evidence_dir = self._collect_evidence(label, remote_run_dir)
            # Best-effort cleanup of the guest artifacts after collection.
            try:
                self.sandbox.exec_raw(
                    f"rm -f {shlex.quote(out_file)} {shlex.quote(err_file)} "
                    f"{shlex.quote(exit_file)}",
                    timeout=30,
                )
            except CuaError:
                pass
            self._write_job_log(label, result)
            return result

    def _kill_guest_script(self, script: str) -> None:
        # [g]uest_... prevents pkill from matching the wrapper shell that
        # contains the literal pattern in its own command line.
        stem = Path(script).stem
        pattern = f"[{stem[0]}]{stem[1:]}.py"
        try:
            self.sandbox.exec_raw(
                f'pkill -f "{pattern}" 2>/dev/null || true', timeout=30
            )
        except CuaError:
            pass

    # ------------------------------------------------------------- operations
    def check_accounts(self) -> JobResult:
        return self.run(
            "guest_accounts.py",
            ["--profile", self.settings.guest_profile],
            label="accounts",
            timeout=300,
            poll_interval=10,
        )

    def open_logins(self) -> JobResult:
        return self.run(
            "guest_open_logins.py",
            ["--profile", self.settings.guest_profile],
            label="open-logins",
            timeout=120,
            poll_interval=5,
        )

    def generate_video(
        self,
        *,
        link: str,
        direction: str,
        title: str,
        variant: int,
        budget_credits: float | None = None,
    ) -> JobResult:
        budget = (
            self.settings.everygen_budget_credits
            if budget_credits is None
            else budget_credits
        )
        return self.run(
            "guest_everygen.py",
            [
                "--profile",
                self.settings.guest_profile,
                "--url",
                self.settings.everygen_url,
                "--login-check",
                "--format",
                self.settings.everygen_format,
                "--model",
                self.settings.everygen_model,
                "--quality",
                self.settings.everygen_quality,
                "--duration",
                self.settings.everygen_duration,
                "--source-url",
                link,
                "--title",
                title,
                "--direction",
                direction,
                "--variant",
                str(variant),
                "--download-dir",
                self.settings.guest_download_dir,
                "--budget-credits",
                str(budget or 0),
                *([] if self.settings.everygen_auto_approve else ["--manual-approval"]),
            ],
            label=f"everygen-v{variant}",
            timeout=self.settings.everygen_timeout,
            poll_interval=15,
        )

    def publish_youtube(
        self, *, video: str, title: str, description: str, live: bool
    ) -> JobResult:
        args = [
            "--profile",
            self.settings.guest_profile,
            "--video",
            video,
            "--title",
            title,
            "--description",
            description,
        ]
        if live:
            args.append("--live")
        return self.run(
            "upload_yt.py",
            args,
            label="youtube-upload",
            timeout=self.settings.publish_timeout,
            poll_interval=15,
        )

    def publish_tiktok(self, *, video: str, caption: str, live: bool) -> JobResult:
        args = [
            "--profile",
            self.settings.guest_profile,
            "--video",
            video,
            "--caption",
            caption,
        ]
        if live:
            args.append("--live")
        return self.run(
            "upload_tiktok.py",
            args,
            label="tiktok-upload",
            timeout=self.settings.publish_timeout,
            poll_interval=15,
        )

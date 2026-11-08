"""Drive the Cua CLI (cua.dev local VM) from the pipeline.

The VM is the only place the owner's YouTube, TikTok and Everygen browser
sessions live.  This module is deliberately a subprocess wrapper (the Cua
Python SDK does not support this project's Python 3.14 venv) and it never
deletes the VM automatically: a lost login costs the owner time, a destroyed
disk costs the owner everything.

A stopped QEMU sandbox (for example after a host shutdown) cannot be started
with ``cua sb restart``; :meth:`CuaSandbox.recover` relaunches the saved QEMU
cmdline and waits for SSH, exactly like the v2-automation pipeline does.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pipeline.config import PipelineSettings

NAME_RE = re.compile(r"^[a-zA-Z0-9_-]{1,32}$")
CREATE_TIMEOUT = 300
CREATE_RETRY_TIMEOUT = 3600
RECOVER_PIDFILE_TIMEOUT = 15
RECOVER_SSH_TIMEOUT = 90
RECOVER_SSH_POLL_INTERVAL = 5.0
RECOVER_SSH_PORT_DEFAULT = 39987
MIN_SCREENSHOT_BYTES = 20 * 1024


class CuaError(RuntimeError):
    """Raised when the Cua CLI is missing, times out, or a command fails."""


class CuaSandbox:
    """One named Cua VM sandbox."""

    def __init__(self, settings: PipelineSettings) -> None:
        self.settings = settings
        self.name = settings.cua_name
        self.kind = settings.cua_kind
        self.image = settings.cua_image or None
        self.timeout = CREATE_TIMEOUT
        self._cli_bin = settings.cua_cli or None

    # ------------------------------------------------------------------ basics
    def enabled(self) -> bool:
        return bool(self.settings.cua_enabled)

    def _log(self, message: str) -> None:
        try:
            self.settings.logs_dir.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now(timezone.utc).isoformat()
            with (self.settings.logs_dir / "cua.log").open("a", encoding="utf-8") as fh:
                fh.write(f"{stamp} [cua] {message}\n")
        except OSError:
            pass

    def _cli(
        self, args: list[str], timeout: int | None = None
    ) -> subprocess.CompletedProcess[str]:
        binary = self._cli_bin or shutil.which("cua")
        if not binary:
            raise CuaError("cua CLI not found; install cua or set CUA_CLI")
        effective_timeout = timeout if timeout is not None else self.timeout
        try:
            return subprocess.run(
                [binary, *args],
                capture_output=True,
                text=True,
                timeout=effective_timeout,
            )
        except subprocess.TimeoutExpired as error:
            raise CuaError(
                f"cua timed out after {effective_timeout}s: {' '.join(args)}"
            ) from error
        except FileNotFoundError as error:
            raise CuaError(f"cua CLI not found: {binary}") from error

    def _checked(
        self, args: list[str], timeout: int | None = None
    ) -> subprocess.CompletedProcess[str]:
        proc = self._cli(args, timeout=timeout)
        if proc.returncode != 0:
            detail = (proc.stderr or proc.stdout or "").strip()
            raise CuaError(f"cua {' '.join(args)} failed ({proc.returncode}): {detail}")
        return proc

    # ------------------------------------------------------------- inventory
    def list_sandboxes(self) -> list[dict[str, Any]]:
        if not self.enabled():
            return []
        try:
            proc = self._checked(["sb", "ls", "--json"], timeout=60)
            data = json.loads(proc.stdout or "[]")
        except (CuaError, ValueError, TypeError) as error:
            self._log(f"ls --json failed: {error}")
            return []
        if isinstance(data, dict):
            data = data.get("sandboxes") or data.get("items") or []
        if not isinstance(data, list):
            return []
        normalized: list[dict[str, Any]] = []
        for sandbox in data:
            if not isinstance(sandbox, dict):
                continue
            normalized.append(
                {
                    "id": sandbox.get("id") or sandbox.get("name"),
                    "name": sandbox.get("name") or "",
                    "state": sandbox.get("state") or sandbox.get("status") or "",
                    "status": sandbox.get("status") or sandbox.get("state") or "",
                    "kind": sandbox.get("kind") or "",
                    "runtime": sandbox.get("runtime") or "",
                }
            )
        return normalized

    def find(self) -> dict[str, Any] | None:
        return next(
            (sandbox for sandbox in self.list_sandboxes() if sandbox["name"] == self.name),
            None,
        )

    def status(self) -> dict[str, Any]:
        if not self.enabled():
            return {"ok": False, "error": "cua disabled"}
        match = self.find()
        return {
            "ok": True,
            "enabled": True,
            "exists": match is not None,
            "name": self.name,
            "kind": self.kind,
            "state": match.get("state") if match else "not_created",
            "status": match.get("status") if match else "",
            "view": self.view_url() if match else "",
        }

    # ------------------------------------------------------------ lifecycle
    def start(self) -> dict[str, Any]:
        """Create the sandbox if missing; reuse it if it already exists."""
        if not self.enabled():
            return {"ok": False, "error": "cua disabled"}
        if not NAME_RE.fullmatch(self.name):
            return {"ok": False, "error": f"invalid sandbox name: {self.name!r}"}
        existing = self.find()
        if existing:
            self._log(f"start: {self.name!r} already exists ({existing.get('state')})")
            return {
                "ok": True,
                "reused": True,
                "name": self.name,
                "kind": self.kind,
                "state": existing.get("state"),
            }
        args = ["sb", "create", "linux", "--kind", self.kind, "--name", self.name]
        if self.image:
            args += ["--image", self.image]
        first_boot = False
        try:
            self._checked(args, timeout=CREATE_TIMEOUT)
        except CuaError as error:
            if "timed out" not in str(error).lower():
                return {"ok": False, "error": f"create failed: {error}"}
            self._log(
                f"start: create timed out ({CREATE_TIMEOUT}s); retrying with "
                f"{CREATE_RETRY_TIMEOUT}s for image pull"
            )
            first_boot = True
            try:
                self._checked(args, timeout=CREATE_RETRY_TIMEOUT)
            except CuaError as retry_error:
                return {"ok": False, "error": f"create failed: {retry_error}"}
        self._log(f"start: created {self.name!r} (first_boot={first_boot})")
        return {
            "ok": True,
            "reused": False,
            "first_boot": first_boot,
            "name": self.name,
            "kind": self.kind,
            "state": "running",
        }

    def suspend(self) -> dict[str, Any]:
        if not self.enabled():
            return {"ok": False, "error": "cua disabled"}
        try:
            self._checked(["sb", "suspend", self.name], timeout=180)
        except CuaError as error:
            return {"ok": False, "error": str(error)}
        self._log(f"suspend: {self.name!r}")
        return {"ok": True, "suspended": True, "name": self.name}

    def resume(self) -> dict[str, Any]:
        if not self.enabled():
            return {"ok": False, "error": "cua disabled"}
        try:
            self._checked(["sb", "resume", self.name], timeout=300)
        except CuaError as error:
            return {"ok": False, "error": str(error)}
        self._log(f"resume: {self.name!r}")
        return {"ok": True, "resumed": True, "name": self.name}

    def recover(self) -> dict[str, Any]:
        """Recover a QEMU VM left ``stopped`` by a host shutdown.

        Refuses unless the sandbox is verifiably stopped (or its pid is already
        alive) and refuses when the saved cmdline/disk is missing.  Never
        destroys the disk.
        """
        if not self.enabled():
            return {"ok": False, "error": "cua disabled"}
        if not NAME_RE.fullmatch(self.name):
            return {"ok": False, "error": f"invalid sandbox name: {self.name!r}"}
        try:
            sandbox_dir = Path(self.settings.cua_home) / "vmm" / "qemu" / self.name
            state_path = sandbox_dir / "state.json"
            state: dict[str, Any] = {}
            if state_path.exists():
                try:
                    state = json.loads(state_path.read_text())
                except (OSError, ValueError) as error:
                    return {
                        "ok": False,
                        "error": f"cannot read state.json at {state_path}: {error}",
                    }
            pid = state.get("pid")
            if pid and Path(f"/proc/{pid}").exists():
                return {
                    "ok": True,
                    "recovered": False,
                    "already_running": True,
                    "name": self.name,
                    "pid": pid,
                }
            match = self.find()
            listed = match.get("state") if match else None
            if listed != "stopped":
                return {
                    "ok": False,
                    "error": (
                        f"sandbox is {listed or 'unknown'!r}, not 'stopped' — "
                        "nothing to recover"
                    ),
                }
            cmdline_path = sandbox_dir / "cmdline"
            if not cmdline_path.exists():
                return {
                    "ok": False,
                    "error": (
                        f"no saved cmdline at {cmdline_path}; the VM cannot be "
                        "recovered (recreate it with `cua sb create`)"
                    ),
                }
            disk = state.get("disk")
            if disk and not Path(disk).exists():
                return {
                    "ok": False,
                    "error": f"disk missing at {disk}; refusing to pretend to recover",
                }
            cmdline = cmdline_path.read_text().strip()
            if not cmdline:
                return {"ok": False, "error": f"empty cmdline at {cmdline_path}"}
            proc = subprocess.Popen(
                shlex.split(cmdline),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            self._log(f"recover: relaunched QEMU for {self.name!r} (pid {proc.pid})")
            pidfile = self._pidfile_from_cmdline(cmdline, str(sandbox_dir))
            deadline = time.monotonic() + RECOVER_PIDFILE_TIMEOUT
            while time.monotonic() < deadline:
                if Path(pidfile).exists():
                    break
                if proc.poll() is not None:
                    return {
                        "ok": False,
                        "error": f"qemu exited early (rc={proc.returncode})",
                    }
                time.sleep(0.5)
            else:
                return {
                    "ok": False,
                    "error": f"timed out waiting for pidfile {pidfile}",
                }
            ports = state.get("ports") or {}
            port = ports.get("22", ports.get(22, RECOVER_SSH_PORT_DEFAULT))
            key = (state.get("ssh") or {}).get("private_key") or str(
                sandbox_dir / "id_ed25519"
            )
            if not self._ssh_ready(int(port), key):
                return {
                    "ok": False,
                    "error": (
                        f"qemu relaunched (pid {proc.pid}) but SSH not ready on "
                        f"port {port}"
                    ),
                }
            state["pid"] = proc.pid
            state.setdefault("name", self.name)
            try:
                state_path.write_text(json.dumps(state, indent=2))
            except OSError as error:
                return {
                    "ok": False,
                    "error": f"launched but failed to update state.json: {error}",
                }
            self._log(f"recover: recovered {self.name!r} (pid {proc.pid})")
            return {"ok": True, "recovered": True, "name": self.name, "pid": proc.pid}
        except Exception as error:  # noqa: BLE001 - recovery is best-effort but reported
            self._log(f"recover: unexpected error: {error}")
            return {"ok": False, "error": str(error)}

    @staticmethod
    def _pidfile_from_cmdline(cmdline: str, sandbox_dir: str) -> str:
        match = re.search(r"-pidfile\s+(\S+)", cmdline)
        return match.group(1) if match else os.path.join(sandbox_dir, "qemu.pid")

    @staticmethod
    def _ssh_ready(
        port: int, key: str, timeout: float = RECOVER_SSH_TIMEOUT
    ) -> bool:
        deadline = time.monotonic() + timeout
        command = [
            "ssh",
            "-i",
            key,
            "-p",
            str(port),
            "-o",
            "BatchMode=yes",
            "-o",
            "StrictHostKeyChecking=no",
            "-o",
            "ConnectTimeout=5",
            "cua@127.0.0.1",
            "echo ok",
        ]
        while time.monotonic() < deadline:
            try:
                proc = subprocess.run(
                    command,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=10,
                )
                if proc.returncode == 0:
                    return True
            except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
                pass
            time.sleep(RECOVER_SSH_POLL_INTERVAL)
        return False

    def ensure_running(self, timeout: int = 300) -> dict[str, Any]:
        """Start, resume, or recover the VM and wait until it accepts exec."""
        if not self.enabled():
            return {"ok": False, "error": "cua disabled"}
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            match = self.find()
            if match is None:
                result = self.start()
                if not result.get("ok"):
                    return result
            else:
                state = (match.get("state") or "").lower()
                if state in {"running", "ready"}:
                    return {"ok": True, "state": state, "name": self.name}
                if state in {"suspended", "paused"}:
                    result = self.resume()
                    if not result.get("ok"):
                        return result
                elif state == "stopped":
                    result = self.recover()
                    if not result.get("ok"):
                        return result
                else:
                    return {
                        "ok": False,
                        "error": f"sandbox is in an unsupported state: {state}",
                    }
            # Verify the guest answers after the lifecycle action.
            try:
                proc = self.exec_raw("uname -a", timeout=60)
                if proc.returncode == 0:
                    return {"ok": True, "state": "running", "name": self.name}
            except CuaError:
                pass
            time.sleep(5)
        return {"ok": False, "error": f"sandbox did not become ready within {timeout}s"}

    # ------------------------------------------------------------- commands
    def exec_raw(
        self, command: str, timeout: int = 120, check: bool = False
    ) -> subprocess.CompletedProcess[str]:
        """Run a trusted, internally-built shell command in the guest."""
        if not self.enabled():
            raise CuaError("cua disabled")
        proc = self._cli(["sb", "exec", self.name, command], timeout=timeout)
        if check and proc.returncode != 0:
            detail = (proc.stderr or proc.stdout or "").strip()
            raise CuaError(
                f"guest command failed ({proc.returncode}): {detail}"
            )
        return proc

    def exec_text(self, command: str, timeout: int = 120) -> str:
        return self.exec_raw(command, timeout=timeout, check=True).stdout or ""

    def copy_to_guest(self, local_path: str | Path, remote_path: str) -> None:
        self._checked(
            ["sb", "cp", str(local_path), f"{self.name}:{remote_path}"],
            timeout=600,
        )

    def copy_from_guest(self, remote_path: str, local_path: str | Path) -> None:
        Path(local_path).parent.mkdir(parents=True, exist_ok=True)
        self._checked(
            ["sb", "cp", f"{self.name}:{remote_path}", str(local_path)],
            timeout=900,
        )

    def screenshot(self, out_path: str | Path | None = None) -> str | dict[str, Any]:
        if not self.enabled():
            return {"ok": False, "error": "cua disabled"}
        path = Path(out_path or self.settings.screenshots_dir / f"{self.name}.png")
        path = path.expanduser().resolve()
        allowed = self.settings.screenshots_dir.resolve()
        if allowed not in path.parents and path.parent != allowed:
            return {"ok": False, "error": "screenshot path outside data/screenshots"}
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self._checked(
                ["sb", "screenshot", self.name, "-o", str(path)], timeout=120
            )
        except CuaError as error:
            return {"ok": False, "error": str(error)}
        size = path.stat().st_size if path.exists() else 0
        if size < MIN_SCREENSHOT_BYTES:
            self._log(f"WARN: screenshot looks blank ({size} bytes): {path}")
        return str(path)

    def view_url(self) -> str:
        if not self.enabled():
            return ""
        try:
            proc = self._cli(["sb", "view", self.name], timeout=60)
        except CuaError as error:
            self._log(f"view_url failed: {error}")
            return ""
        match = re.search(r"https?://\S+", proc.stdout or "")
        return match.group(0).rstrip(".,;)]") if match else ""

    def info(self) -> dict[str, Any]:
        if not self.enabled():
            return {"ok": False, "error": "cua disabled"}
        try:
            proc = self._checked(["sb", "info", self.name, "--json"], timeout=60)
            return {"ok": True, **json.loads(proc.stdout or "{}")}
        except (CuaError, ValueError) as error:
            return {"ok": False, "error": str(error)}

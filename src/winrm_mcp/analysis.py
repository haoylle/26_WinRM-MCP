from __future__ import annotations

import os
import re
import time
from pathlib import Path, PureWindowsPath
from typing import Any

from .config import load_config
from .encoding import ps_quote
from .file_transfer import copy_from_guest, copy_to_guest
from .process import start_process
from .session import run_cmd_raw, run_ps_raw


def _analysis_cfg():
    return load_config().analysis


def _require_configured_path(value: str | None, field_name: str) -> str:
    if value:
        return value
    raise RuntimeError(f"Missing analysis.{field_name} in config.yaml")


def _sysinternals_tool_path(tool: str) -> str:
    cfg = _analysis_cfg()
    root = _require_configured_path(cfg.sysinternals_dir, "sysinternals_dir")
    exe = tool if tool.lower().endswith(".exe") else f"{tool}.exe"
    return str(PureWindowsPath(root) / exe)


def _run_sysinternals(tool: str, arguments: str = "") -> dict[str, Any]:
    tool_path = _sysinternals_tool_path(tool)
    cmd = f'"{tool_path}" -accepteula'
    if arguments.strip():
        cmd += f" {arguments}"
    res = run_cmd_raw(cmd)
    res["tool_path"] = tool_path
    return res


def _parse_pslist_pids(output: str, process_name: str) -> list[int]:
    pids: list[int] = []
    targets = {process_name.lower()}
    if not process_name.lower().endswith(".exe"):
        targets.add(f"{process_name.lower()}.exe")
    for line in output.splitlines():
        text = line.strip()
        if not text or text.lower().startswith("process") or text.lower().startswith("pslist"):
            continue
        cols = re.split(r"\s+", text)
        if len(cols) < 2:
            continue
        if cols[0].lower() not in targets:
            continue
        for token in cols[1:]:
            if token.isdigit():
                pids.append(int(token))
                break
    return pids


def get_processes() -> dict[str, Any]:
    """Get a process list using Sysinternals PsList."""
    return _run_sysinternals("pslist")


def get_dlls(process_name: str | None = None) -> dict[str, Any]:
    """Get loaded DLLs using Sysinternals ListDLLs."""
    args = process_name or ""
    return _run_sysinternals("Listdlls", args)


def get_system_info() -> dict[str, Any]:
    """Get system information using Sysinternals PsInfo."""
    return _run_sysinternals("PsInfo", "-nobanner")


def run_sysinternals(tool: str, arguments: str = "") -> dict[str, Any]:
    """Run an arbitrary Sysinternals tool on the guest."""
    return _run_sysinternals(tool, arguments)


def find_processes_by_dll(dll_name: str) -> dict[str, Any]:
    """List processes that loaded a specific DLL using ListDLLs -d."""
    return _run_sysinternals("Listdlls", f"-d {dll_name}")


def list_dlls_of_process(process_name: str) -> dict[str, Any]:
    """List DLLs loaded by a specific process using ListDLLs."""
    return _run_sysinternals("Listdlls", process_name)


def check_process(process_name: str) -> dict[str, Any]:
    """Check whether a process exists and return matching PIDs."""
    res = _run_sysinternals("pslist", process_name)
    pids = _parse_pslist_pids(res.get("stdout", ""), process_name)
    res["process_name"] = process_name
    res["pids"] = pids
    res["found"] = bool(pids)
    return res


def is_litecov_running() -> dict[str, Any]:
    """Check whether litecov is running using PsList."""
    res = _run_sysinternals("pslist", "litecov")
    pids = _parse_pslist_pids(res.get("stdout", ""), "litecov")
    res["pids"] = pids
    res["running"] = bool(pids)
    return res


def file_exists(absolute_path: str) -> dict[str, Any]:
    """Check whether a file exists on the guest and return basic metadata when present."""
    ps = (
        f"$p={ps_quote(absolute_path)}; "
        "if (Test-Path -LiteralPath $p) { "
        "$item=Get-Item -LiteralPath $p; "
        "$item | Select-Object FullName,Length,PSIsContainer,LastWriteTime | ConvertTo-Json -Compress "
        "} else { exit 3 }"
    )
    res = run_ps_raw(ps)
    if res["ok"]:
        res["exists"] = True
        res["path"] = absolute_path
        return res
    if res.get("status_code") == 3:
        return {"ok": True, "exists": False, "path": absolute_path, "stdout": "", "stderr": ""}
    res["exists"] = False
    res["path"] = absolute_path
    return res


def litecov_spawn(
    dll_name: str,
    program_path: str,
    wait_seconds: int = 30,
    arguments: str = "",
    cwd: str | None = None,
) -> dict[str, Any]:
    """Run litecov with a new process."""
    litecov_path = _require_configured_path(_analysis_cfg().litecov_path, "litecov_path")
    wait = int(wait_seconds)
    arg_list = f"-instrument_module {dll_name} -wait {wait}"
    if arguments.strip():
        arg_list += f" {arguments.strip()}"
    arg_list += f' -- "{program_path}"'
    res = start_process(litecov_path, arguments=arg_list, wait=wait > 0, cwd=cwd)
    res["litecov_path"] = litecov_path
    return res


def litecov_attach(dll_name: str, pid: int, wait_seconds: int = 30) -> dict[str, Any]:
    """Attach litecov to an existing PID."""
    litecov_path = _require_configured_path(_analysis_cfg().litecov_path, "litecov_path")
    wait = int(wait_seconds)
    arg_list = f"-instrument_module {dll_name} -wait {wait} -pid {int(pid)}"
    res = start_process(litecov_path, arguments=arg_list, wait=wait > 0)
    res["litecov_path"] = litecov_path
    return res


def download_coverage(local_path: str) -> dict[str, Any]:
    """Download the configured coverage file from the guest."""
    remote_path = _analysis_cfg().coverage_file
    return copy_from_guest(remote_path, local_path, overwrite=True, verify_hash=True)


def upload_build_file(local_path: str, remote_basename: str = "") -> dict[str, Any]:
    """Upload a file into the configured guest build directory with a unique name."""
    remote_dir = _analysis_cfg().build_files_dir
    src = Path(local_path)
    if not src.is_file():
        raise RuntimeError(f"Local file not found: {local_path}")
    base = (remote_basename or src.name).strip() or src.name
    root, ext = os.path.splitext(base)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    unique = f"{root}__{stamp}_{int(time.time())}{ext}"
    remote_path = str(PureWindowsPath(remote_dir) / unique)
    res = copy_to_guest(local_path, remote_path, overwrite=True, verify_hash=True)
    res["remote_basename"] = unique
    return res

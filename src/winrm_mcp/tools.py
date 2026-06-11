from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from .analysis import (
    check_process,
    download_coverage,
    file_exists,
    find_processes_by_dll,
    get_dlls,
    get_processes,
    get_system_info,
    is_litecov_running,
    list_dlls_of_process,
    litecov_attach,
    litecov_spawn,
    run_sysinternals,
    upload_build_file,
)
from .config import load_config
from .file_transfer import copy_from_guest, copy_to_guest, test_file_copy
from .kdnet import configure_kdnet, query_debug_settings, reboot, reboot_and_wait, wait_for_winrm
from .process import start_process
from .session import clear_session_cache, endpoint, run_cmd_raw, run_ps_raw
from .shell import close_shell, open_shell, session_run


def health_check() -> dict[str, Any]:
    cfg = load_config()
    clear_session_cache()
    res = run_ps_raw("$PSVersionTable.PSVersion.ToString(); whoami; hostname")
    res["endpoint"] = endpoint(cfg)
    res["guest"] = {"host": cfg.guest.host, "username": cfg.guest.username, "transport": cfg.guest.transport}
    res["limits"] = {"copy_chunk_bytes": cfg.limits.copy_chunk_bytes, "max_stdout_chars": cfg.limits.max_stdout_chars}
    res["recovery"] = {
        "reconnect_timeout_sec": cfg.recovery.reconnect_timeout_sec,
        "reconnect_interval_sec": cfg.recovery.reconnect_interval_sec,
        "reconnect_settle_sec": cfg.recovery.reconnect_settle_sec,
        "reboot_offline_timeout_sec": cfg.recovery.reboot_offline_timeout_sec,
    }
    res["analysis"] = {
        "sysinternals_dir": cfg.analysis.sysinternals_dir,
        "litecov_path": cfg.analysis.litecov_path,
        "coverage_file": cfg.analysis.coverage_file,
        "build_files_dir": cfg.analysis.build_files_dir,
    }
    return res


def register_all_tools(mcp: FastMCP) -> None:
    mcp.tool()(health_check)
    mcp.tool()(run_ps)
    mcp.tool()(run_cmd)
    mcp.tool()(open_shell)
    mcp.tool()(session_run)
    mcp.tool()(close_shell)
    mcp.tool()(copy_to_guest)
    mcp.tool()(copy_from_guest)
    mcp.tool()(test_file_copy)
    mcp.tool()(start_process)
    mcp.tool()(get_processes)
    mcp.tool()(get_dlls)
    mcp.tool()(get_system_info)
    mcp.tool()(run_sysinternals)
    mcp.tool()(find_processes_by_dll)
    mcp.tool()(list_dlls_of_process)
    mcp.tool()(check_process)
    mcp.tool()(is_litecov_running)
    mcp.tool()(file_exists)
    mcp.tool()(litecov_spawn)
    mcp.tool()(litecov_attach)
    mcp.tool()(download_coverage)
    mcp.tool()(upload_build_file)
    mcp.tool()(reboot)
    mcp.tool()(wait_for_winrm)
    mcp.tool()(reboot_and_wait)
    mcp.tool()(query_debug_settings)
    mcp.tool()(configure_kdnet)


def run_ps(script: str) -> dict[str, Any]:
    """Run a PowerShell script on the guest through WinRM."""
    return run_ps_raw(script)


def run_cmd(command: str) -> dict[str, Any]:
    """Run a cmd.exe command on the guest through WinRM."""
    return run_cmd_raw(command)

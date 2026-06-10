from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from .config import load_config
from .file_transfer import copy_from_guest, copy_to_guest, test_file_copy
from .kdnet import configure_kdnet, query_debug_settings, reboot
from .process import start_process
from .session import endpoint, run_cmd_raw, run_ps_raw
from .shell import close_shell, open_shell, session_run


def health_check() -> dict[str, Any]:
    cfg = load_config()
    res = run_ps_raw("$PSVersionTable.PSVersion.ToString(); whoami; hostname")
    res["endpoint"] = endpoint(cfg)
    res["guest"] = {"host": cfg.guest.host, "username": cfg.guest.username, "transport": cfg.guest.transport}
    res["limits"] = {"copy_chunk_bytes": cfg.limits.copy_chunk_bytes, "max_stdout_chars": cfg.limits.max_stdout_chars}
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
    mcp.tool()(reboot)
    mcp.tool()(query_debug_settings)
    mcp.tool()(configure_kdnet)


def run_ps(script: str) -> dict[str, Any]:
    """Run a PowerShell script on the guest through WinRM."""
    return run_ps_raw(script)


def run_cmd(command: str) -> dict[str, Any]:
    """Run a cmd.exe command on the guest through WinRM."""
    return run_cmd_raw(command)

from __future__ import annotations

import base64
import json
import os
import re
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path, PureWindowsPath
from typing import Any

import winrm
import yaml
from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, Field, ValidationError

APP_NAME = "winrm-mcp"
mcp = FastMCP(APP_NAME)


class GuestConfig(BaseModel):
    host: str
    username: str
    password: str | None = None
    transport: str = "ntlm"
    scheme: str = "http"
    port: int = 5985
    server_cert_validation: str = "ignore"
    operation_timeout_sec: int = 60
    read_timeout_sec: int = 90
    allow_unencrypted: bool = True
    path: str = "/wsman"


class LimitsConfig(BaseModel):
    max_stdout_chars: int = 200000
    copy_chunk_bytes: int = 49152
    command_timeout_sec: int = 300


class SecurityConfig(BaseModel):
    allowed_command_prefixes: list[str] = Field(default_factory=list)
    denied_patterns: list[str] = Field(default_factory=list)


class KdnetConfig(BaseModel):
    host_ip: str
    port: int = 50000
    key: str
    state_file: str = r"C:\mcp-state\kd-session.json"
    bcdedit_path: str = "bcdedit.exe"


class Config(BaseModel):
    guest: GuestConfig
    limits: LimitsConfig = Field(default_factory=LimitsConfig)
    security: SecurityConfig = Field(default_factory=SecurityConfig)
    kdnet: KdnetConfig | None = None


@dataclass
class ShellState:
    cwd: str = "C:\\"
    env: dict[str, str] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    last_used: float = field(default_factory=time.time)


_shells: dict[str, ShellState] = {}
_config_cache: Config | None = None
_session_cache: winrm.Session | None = None


def _load_config() -> Config:
    global _config_cache
    if _config_cache is not None:
        return _config_cache
    cfg_path = os.environ.get("WINRM_MCP_CONFIG") or "config.yaml"
    with open(cfg_path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    try:
        cfg = Config.model_validate(raw)
    except ValidationError as e:
        raise RuntimeError(f"Invalid config file {cfg_path}: {e}") from e
    if not cfg.guest.password:
        cfg.guest.password = os.environ.get("WINRM_PASSWORD")
    if not cfg.guest.password:
        raise RuntimeError("Missing guest password. Set guest.password in config.yaml or WINRM_PASSWORD env var.")
    _config_cache = cfg
    return cfg


def _endpoint(cfg: Config) -> str:
    return f"{cfg.guest.scheme}://{cfg.guest.host}:{cfg.guest.port}{cfg.guest.path}"


def _session() -> winrm.Session:
    global _session_cache
    cfg = _load_config()
    if _session_cache is None:
        _session_cache = winrm.Session(
            _endpoint(cfg),
            auth=(cfg.guest.username, cfg.guest.password),
            transport=cfg.guest.transport,
            server_cert_validation=cfg.guest.server_cert_validation,
            operation_timeout_sec=cfg.guest.operation_timeout_sec,
            read_timeout_sec=cfg.guest.read_timeout_sec,
        )
    return _session_cache


def _decode(data: bytes) -> str:
    for enc in ("utf-8-sig", "utf-16-le", "cp949", "cp932", "latin-1"):
        try:
            return data.decode(enc)
        except Exception:
            continue
    return data.decode("utf-8", errors="replace")


def _check_command_allowed(command: str) -> None:
    cfg = _load_config()
    low = command.lower().strip()
    for pat in cfg.security.denied_patterns:
        if pat.lower() in low:
            raise RuntimeError(f"Command denied by policy: contains pattern {pat!r}")
    prefixes = cfg.security.allowed_command_prefixes
    if prefixes and not any(low.startswith(p.lower()) for p in prefixes):
        raise RuntimeError("Command denied by policy: not in allowed_command_prefixes")


def _trim(text: str) -> str:
    limit = _load_config().limits.max_stdout_chars
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n... <truncated at {limit} chars>"


def _result(status_code: int, stdout: bytes, stderr: bytes) -> dict[str, Any]:
    return {
        "status_code": status_code,
        "stdout": _trim(_decode(stdout)),
        "stderr": _trim(_decode(stderr)),
        "ok": status_code == 0,
    }


def _run_ps_raw(script: str) -> dict[str, Any]:
    _check_command_allowed(script)
    r = _session().run_ps(script)
    return _result(r.status_code, r.std_out, r.std_err)


def _ps_quote(s: str) -> str:
    return "'" + s.replace("'", "''") + "'"


@mcp.tool()
def health_check() -> dict[str, Any]:
    """Verify config loading and WinRM connectivity by running a harmless command on the guest."""
    cfg = _load_config()
    res = _run_ps_raw("$PSVersionTable.PSVersion.ToString(); whoami; hostname")
    res["endpoint"] = _endpoint(cfg)
    res["guest"] = {"host": cfg.guest.host, "username": cfg.guest.username, "transport": cfg.guest.transport}
    return res


@mcp.tool()
def run_ps(script: str) -> dict[str, Any]:
    """Run a PowerShell script on the guest through WinRM."""
    return _run_ps_raw(script)


@mcp.tool()
def run_cmd(command: str) -> dict[str, Any]:
    """Run a cmd.exe command on the guest through WinRM."""
    _check_command_allowed(command)
    r = _session().run_cmd("cmd.exe", ["/d", "/s", "/c", command])
    return _result(r.status_code, r.std_out, r.std_err)


@mcp.tool()
def open_shell(cwd: str = "C:\\") -> dict[str, Any]:
    """Create a logical shell session. It preserves cwd and environment between session_run calls."""
    sid = uuid.uuid4().hex
    _shells[sid] = ShellState(cwd=cwd)
    return {"shell_id": sid, "cwd": cwd}


@mcp.tool()
def session_run(shell_id: str, command: str, shell: str = "powershell") -> dict[str, Any]:
    """Run a command in a logical shell session preserving cwd. shell must be powershell or cmd."""
    if shell_id not in _shells:
        raise RuntimeError("Unknown shell_id")
    st = _shells[shell_id]
    st.last_used = time.time()
    if shell.lower() == "powershell":
        env_lines = "\n".join(f"$env:{k}={_ps_quote(v)}" for k, v in st.env.items())
        ps = f"Set-Location -LiteralPath {_ps_quote(st.cwd)}\n{env_lines}\n{command}\n'__MCP_CWD__=' + (Get-Location).Path"
        res = _run_ps_raw(ps)
        m = re.search(r"__MCP_CWD__=(.*)", res.get("stdout", ""))
        if m:
            st.cwd = m.group(1).strip()
            res["stdout"] = res["stdout"].replace(m.group(0), "").rstrip()
        res["cwd"] = st.cwd
        return res
    if shell.lower() == "cmd":
        safe_cwd = st.cwd.replace('\"', '')
        res = run_cmd(f'cd /d "{safe_cwd}" && {command} && cd')
        lines = res.get("stdout", "").splitlines()
        if lines:
            maybe = lines[-1].strip()
            if re.match(r"^[A-Za-z]:\\", maybe):
                st.cwd = maybe
                res["stdout"] = "\n".join(lines[:-1])
        res["cwd"] = st.cwd
        return res
    raise RuntimeError("shell must be 'powershell' or 'cmd'")


@mcp.tool()
def close_shell(shell_id: str) -> dict[str, Any]:
    """Close a logical shell session."""
    existed = _shells.pop(shell_id, None) is not None
    return {"closed": existed}


@mcp.tool()
def copy_to_guest(local_path: str, remote_path: str, overwrite: bool = True) -> dict[str, Any]:
    """Copy a file from the host running this MCP server to the Windows guest."""
    src = Path(local_path)
    if not src.is_file():
        raise RuntimeError(f"Local file not found: {local_path}")
    cfg = _load_config()
    total = src.stat().st_size
    remote_parent = str(PureWindowsPath(remote_path).parent)
    init = f"New-Item -ItemType Directory -Force -Path {_ps_quote(remote_parent)} | Out-Null; "
    init += f"if ((Test-Path -LiteralPath {_ps_quote(remote_path)}) -and -not ${str(overwrite).lower()}) {{ throw 'Remote file exists' }}; "
    init += f"Remove-Item -LiteralPath {_ps_quote(remote_path)} -Force -ErrorAction SilentlyContinue"
    r = _run_ps_raw(init)
    if not r["ok"]:
        return r
    chunks = 0
    with src.open("rb") as f:
        while True:
            data = f.read(cfg.limits.copy_chunk_bytes)
            if not data:
                break
            b64 = base64.b64encode(data).decode("ascii")
            ps = f"$b=[Convert]::FromBase64String({_ps_quote(b64)}); [IO.File]::Open({_ps_quote(remote_path)}, [IO.FileMode]::Append, [IO.FileAccess]::Write).Dispose(); [IO.File]::WriteAllBytes($env:TEMP+'\\mcp_chunk.bin',$b); $fs=[IO.File]::Open({_ps_quote(remote_path)},[IO.FileMode]::Append,[IO.FileAccess]::Write); $fs.Write($b,0,$b.Length); $fs.Close()"
            rr = _run_ps_raw(ps)
            if not rr["ok"]:
                rr["chunks_completed"] = chunks
                return rr
            chunks += 1
    verify = _run_ps_raw(f"(Get-Item -LiteralPath {_ps_quote(remote_path)}).Length")
    return {"ok": verify["ok"], "local_path": local_path, "remote_path": remote_path, "bytes": total, "chunks": chunks, "remote_size_stdout": verify.get("stdout", "")}


@mcp.tool()
def copy_from_guest(remote_path: str, local_path: str, overwrite: bool = True) -> dict[str, Any]:
    """Copy a file from the Windows guest to the host running this MCP server."""
    dst = Path(local_path)
    if dst.exists() and not overwrite:
        raise RuntimeError(f"Local file exists: {local_path}")
    dst.parent.mkdir(parents=True, exist_ok=True)
    cfg = _load_config()
    size_res = _run_ps_raw(f"if (!(Test-Path -LiteralPath {_ps_quote(remote_path)})) {{ throw 'Remote file not found' }}; (Get-Item -LiteralPath {_ps_quote(remote_path)}).Length")
    if not size_res["ok"]:
        return size_res
    total = int(size_res["stdout"].strip().splitlines()[-1])
    offset = 0
    chunks = 0
    mode = "wb"
    with dst.open(mode) as out:
        while offset < total:
            take = min(cfg.limits.copy_chunk_bytes, total - offset)
            ps = f"$fs=[IO.File]::OpenRead({_ps_quote(remote_path)}); $fs.Seek({offset},[IO.SeekOrigin]::Begin) | Out-Null; $b=New-Object byte[] {take}; $n=$fs.Read($b,0,$b.Length); $fs.Close(); [Convert]::ToBase64String($b,0,$n)"
            rr = _run_ps_raw(ps)
            if not rr["ok"]:
                return rr
            out.write(base64.b64decode(rr["stdout"].strip()))
            offset += take
            chunks += 1
    return {"ok": True, "remote_path": remote_path, "local_path": local_path, "bytes": total, "chunks": chunks}


@mcp.tool()
def start_process(file_path: str, arguments: str = "", wait: bool = True, cwd: str | None = None) -> dict[str, Any]:
    """Start a process on the guest. Use wait=true to wait for exit code."""
    work = f"-WorkingDirectory {_ps_quote(cwd)} " if cwd else ""
    wait_flag = "-Wait -PassThru" if wait else "-PassThru"
    ps = f"$p=Start-Process -FilePath {_ps_quote(file_path)} -ArgumentList {_ps_quote(arguments)} {work}{wait_flag}; if ($p) {{ $p | Select-Object Id,ExitCode,HasExited | ConvertTo-Json -Compress }}"
    return _run_ps_raw(ps)


@mcp.tool()
def reboot(force: bool = True) -> dict[str, Any]:
    """Reboot the guest VM via WinRM."""
    flag = "-Force" if force else ""
    return _run_ps_raw(f"Restart-Computer {flag}")


@mcp.tool()
def query_debug_settings() -> dict[str, Any]:
    """Return bcdedit debug settings from the guest."""
    return _run_ps_raw("bcdedit /enum '{current}'; bcdedit /dbgsettings")


@mcp.tool()
def configure_kdnet(host_ip: str | None = None, port: int | None = None, key: str | None = None, write_state: bool = True) -> dict[str, Any]:
    """Configure guest boot settings for KDNET kernel debugging and optionally write a shared state file for kd-mcp."""
    cfg = _load_config()
    if cfg.kdnet is None and (not host_ip or not port or not key):
        raise RuntimeError("kdnet config is missing. Provide host_ip, port, and key or set kdnet in config.yaml.")
    host_ip = host_ip or cfg.kdnet.host_ip
    port = port or cfg.kdnet.port
    key = key or cfg.kdnet.key
    bcd = cfg.kdnet.bcdedit_path if cfg.kdnet else "bcdedit.exe"
    ps = f"""
& {bcd} /debug on
if ($LASTEXITCODE -ne 0) {{ exit $LASTEXITCODE }}
& {bcd} /dbgsettings net hostip:{host_ip} port:{port} key:{key}
if ($LASTEXITCODE -ne 0) {{ exit $LASTEXITCODE }}
& {bcd} /enum '{{current}}'
& {bcd} /dbgsettings
"""
    res = _run_ps_raw(ps)
    if write_state and res["ok"] and cfg.kdnet:
        state_path = Path(cfg.kdnet.state_file)
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state = {
            "schema": "winrm-kd-session-v1",
            "guest_host": cfg.guest.host,
            "host_ip": host_ip,
            "port": port,
            "key": key,
            "created_by": APP_NAME,
            "created_at_unix": time.time(),
        }
        state_path.write_text(json.dumps(state, indent=2), encoding="utf-8")
        res["state_file"] = str(state_path)
    return res


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()

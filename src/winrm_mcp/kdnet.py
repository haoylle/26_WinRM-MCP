from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from .config import load_config
from .session import run_ps_raw

APP_NAME = "winrm-mcp"


def reboot(force: bool = True) -> dict[str, Any]:
    flag = "-Force" if force else ""
    return run_ps_raw(f"Restart-Computer {flag}")


def query_debug_settings() -> dict[str, Any]:
    return run_ps_raw("bcdedit /enum '{current}'; bcdedit /dbgsettings")


def configure_kdnet(host_ip: str | None = None, port: int | None = None, key: str | None = None, write_state: bool = True) -> dict[str, Any]:
    cfg = load_config()
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
    res = run_ps_raw(ps)
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

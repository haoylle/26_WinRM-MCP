from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from .config import load_config
from .encoding import make_result
from .session import build_session, clear_session_cache, run_ps_raw

APP_NAME = "winrm-mcp"
PROBE_SCRIPT = "$PSVersionTable.PSVersion.ToString(); whoami; hostname"


def reboot(force: bool = True) -> dict[str, Any]:
    flag = "-Force" if force else ""
    try:
        res = run_ps_raw(f"Restart-Computer {flag}")
    finally:
        clear_session_cache()
    res["note"] = "WinRM is expected to disconnect during reboot. Use reboot_and_wait() to wait for the guest to come back."
    return res


def _probe_winrm_once() -> dict[str, Any]:
    clear_session_cache()
    try:
        session = build_session()
        res = session.run_ps(PROBE_SCRIPT)
        result = make_result(res.status_code, res.std_out, res.std_err)
        result["connected"] = result["ok"]
        return result
    except Exception as exc:
        return {"ok": False, "connected": False, "error": str(exc), "stdout": "", "stderr": str(exc)}


def _looks_like_disconnect_error(text: str) -> bool:
    low = text.lower()
    patterns = (
        "connection aborted",
        "connection reset",
        "connection refused",
        "connectionerror",
        "connection reset by peer",
        "connection was forcibly closed",
        "max retries exceeded",
        "read timed out",
        "remote end closed connection",
        "transport error",
        "unreachable",
        "wsmanfault",
    )
    return any(pattern in low for pattern in patterns)


def wait_for_winrm(
    timeout_sec: float | None = None,
    interval_sec: float | None = None,
    settle_sec: float | None = None,
) -> dict[str, Any]:
    cfg = load_config()
    timeout = cfg.recovery.reconnect_timeout_sec if timeout_sec is None else timeout_sec
    interval = cfg.recovery.reconnect_interval_sec if interval_sec is None else interval_sec
    settle = cfg.recovery.reconnect_settle_sec if settle_sec is None else settle_sec

    started = time.time()
    deadline = started + timeout
    attempts = 0
    last_probe: dict[str, Any] | None = None

    while True:
        attempts += 1
        last_probe = _probe_winrm_once()
        if last_probe.get("connected"):
            if settle > 0:
                time.sleep(settle)
            result = dict(last_probe)
            result.update(
                {
                    "attempts": attempts,
                    "waited_sec": round(time.time() - started, 3),
                    "settle_sec": settle,
                    "timeout_sec": timeout,
                    "interval_sec": interval,
                }
            )
            return result

        now = time.time()
        if now >= deadline:
            break
        time.sleep(min(interval, max(0.0, deadline - now)))

    result = dict(last_probe or {})
    result.update(
        {
            "ok": False,
            "attempts": attempts,
            "waited_sec": round(time.time() - started, 3),
            "timeout_sec": timeout,
            "interval_sec": interval,
        }
    )
    return result


def reboot_and_wait(
    force: bool = True,
    offline_timeout_sec: float | None = None,
    reconnect_timeout_sec: float | None = None,
    interval_sec: float | None = None,
    settle_sec: float | None = None,
) -> dict[str, Any]:
    cfg = load_config()
    offline_timeout = cfg.recovery.reboot_offline_timeout_sec if offline_timeout_sec is None else offline_timeout_sec
    reconnect_timeout = cfg.recovery.reconnect_timeout_sec if reconnect_timeout_sec is None else reconnect_timeout_sec
    interval = cfg.recovery.reconnect_interval_sec if interval_sec is None else interval_sec
    settle = cfg.recovery.reconnect_settle_sec if settle_sec is None else settle_sec

    reboot_result: dict[str, Any]
    try:
        reboot_result = run_ps_raw(f"Restart-Computer {'-Force' if force else ''}".strip())
    except Exception as exc:
        if not _looks_like_disconnect_error(str(exc)):
            return {
                "ok": False,
                "reboot_sent": False,
                "error": str(exc),
                "stderr": str(exc),
                "stdout": "",
            }
        reboot_result = {
            "ok": True,
            "status_code": None,
            "stdout": "",
            "stderr": str(exc),
            "note": "The reboot command disconnected the WinRM transport before a normal response. This is expected during reboot.",
        }
    finally:
        clear_session_cache()

    offline_observed = False
    offline_started = time.time()
    while time.time() - offline_started < offline_timeout:
        probe = _probe_winrm_once()
        if not probe.get("connected"):
            offline_observed = True
            break
        time.sleep(interval)

    wait_result = wait_for_winrm(timeout_sec=reconnect_timeout, interval_sec=interval, settle_sec=settle)
    wait_result["reboot_sent"] = True
    wait_result["offline_observed"] = offline_observed
    wait_result["offline_timeout_sec"] = offline_timeout
    wait_result["reboot_result"] = reboot_result
    if not offline_observed:
        wait_result["note"] = (
            "WinRM never appeared offline during the observation window. The guest may have rebooted too quickly, "
            "or the reboot request may not have taken effect."
        )
    return wait_result


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

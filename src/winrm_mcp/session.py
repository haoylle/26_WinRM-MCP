from __future__ import annotations

import winrm

from .config import Config, load_config
from .encoding import make_result
from .security import check_command_allowed

_session_cache: winrm.Session | None = None


def endpoint(cfg: Config | None = None) -> str:
    cfg = cfg or load_config()
    return f"{cfg.guest.scheme}://{cfg.guest.host}:{cfg.guest.port}{cfg.guest.path}"


def build_session(cfg: Config | None = None) -> winrm.Session:
    cfg = cfg or load_config()
    return winrm.Session(
        endpoint(cfg),
        auth=(cfg.guest.username, cfg.guest.password),
        transport=cfg.guest.transport,
        server_cert_validation=cfg.guest.server_cert_validation,
        operation_timeout_sec=cfg.guest.operation_timeout_sec,
        read_timeout_sec=cfg.guest.read_timeout_sec,
    )


def get_session() -> winrm.Session:
    global _session_cache
    if _session_cache is None:
        _session_cache = build_session()
    return _session_cache


def clear_session_cache() -> None:
    global _session_cache
    _session_cache = None


def run_ps_raw(script: str) -> dict:
    check_command_allowed(script)
    r = get_session().run_ps(script)
    return make_result(r.status_code, r.std_out, r.std_err)


def run_cmd_raw(command: str) -> dict:
    check_command_allowed(command)
    r = get_session().run_cmd("cmd.exe", ["/d", "/s", "/c", command])
    return make_result(r.status_code, r.std_out, r.std_err)

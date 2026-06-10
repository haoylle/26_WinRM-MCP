from __future__ import annotations

from .config import load_config


def check_command_allowed(command: str) -> None:
    cfg = load_config()
    low = command.lower().strip()
    for pat in cfg.security.denied_patterns:
        if pat.lower() in low:
            raise RuntimeError(f"Command denied by policy: contains pattern {pat!r}")
    prefixes = cfg.security.allowed_command_prefixes
    if prefixes and not any(low.startswith(p.lower()) for p in prefixes):
        raise RuntimeError("Command denied by policy: not in allowed_command_prefixes")

from __future__ import annotations

import re
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from .encoding import ps_quote
from .session import run_cmd_raw, run_ps_raw


@dataclass
class ShellState:
    cwd: str = "C:\\"
    env: dict[str, str] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    last_used: float = field(default_factory=time.time)


_shells: dict[str, ShellState] = {}


def open_shell(cwd: str = "C:\\") -> dict[str, Any]:
    sid = uuid.uuid4().hex
    _shells[sid] = ShellState(cwd=cwd)
    return {"shell_id": sid, "cwd": cwd}


def session_run(shell_id: str, command: str, shell: str = "powershell") -> dict[str, Any]:
    if shell_id not in _shells:
        raise RuntimeError("Unknown shell_id")
    st = _shells[shell_id]
    st.last_used = time.time()

    if shell.lower() == "powershell":
        env_lines = "\n".join(f"$env:{k}={ps_quote(v)}" for k, v in st.env.items())
        ps = f"Set-Location -LiteralPath {ps_quote(st.cwd)}\n{env_lines}\n{command}\n'__MCP_CWD__=' + (Get-Location).Path"
        res = run_ps_raw(ps)
        m = re.search(r"__MCP_CWD__=(.*)", res.get("stdout", ""))
        if m:
            st.cwd = m.group(1).strip()
            res["stdout"] = res["stdout"].replace(m.group(0), "").rstrip()
        res["cwd"] = st.cwd
        return res

    if shell.lower() == "cmd":
        safe_cwd = st.cwd.replace('"', '')
        res = run_cmd_raw(f'cd /d "{safe_cwd}" && {command} && cd')
        lines = res.get("stdout", "").splitlines()
        if lines:
            maybe = lines[-1].strip()
            if re.match(r"^[A-Za-z]:\\", maybe):
                st.cwd = maybe
                res["stdout"] = "\n".join(lines[:-1])
        res["cwd"] = st.cwd
        return res

    raise RuntimeError("shell must be 'powershell' or 'cmd'")


def close_shell(shell_id: str) -> dict[str, Any]:
    existed = _shells.pop(shell_id, None) is not None
    return {"closed": existed}

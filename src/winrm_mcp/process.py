from __future__ import annotations

from .encoding import ps_quote
from .session import run_ps_raw


def start_process(file_path: str, arguments: str = "", wait: bool = True, cwd: str | None = None) -> dict:
    work = f"-WorkingDirectory {ps_quote(cwd)} " if cwd else ""
    wait_flag = "-Wait -PassThru" if wait else "-PassThru"
    ps = f"$p=Start-Process -FilePath {ps_quote(file_path)} -ArgumentList {ps_quote(arguments)} {work}{wait_flag}; if ($p) {{ $p | Select-Object Id,ExitCode,HasExited | ConvertTo-Json -Compress }}"
    return run_ps_raw(ps)

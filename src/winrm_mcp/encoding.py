from __future__ import annotations

from .config import load_config


def decode_bytes(data: bytes) -> str:
    for enc in ("utf-8-sig", "utf-16-le", "cp949", "cp932", "latin-1"):
        try:
            return data.decode(enc)
        except Exception:
            continue
    return data.decode("utf-8", errors="replace")


def trim_output(text: str) -> str:
    limit = load_config().limits.max_stdout_chars
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n... <truncated at {limit} chars>"


def make_result(status_code: int, stdout: bytes, stderr: bytes) -> dict:
    return {
        "status_code": status_code,
        "stdout": trim_output(decode_bytes(stdout)),
        "stderr": trim_output(decode_bytes(stderr)),
        "ok": status_code == 0,
    }


def ps_quote(s: str) -> str:
    return "'" + s.replace("'", "''") + "'"

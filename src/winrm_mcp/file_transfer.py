from __future__ import annotations

import base64
import hashlib
import tempfile
import uuid
from pathlib import Path, PureWindowsPath
from typing import Any

from .config import load_config
from .encoding import ps_quote
from .session import run_ps_raw


def sha256_local(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest().lower()


def sha256_remote(remote_path: str) -> tuple[bool, str]:
    r = run_ps_raw(f"(Get-FileHash -LiteralPath {ps_quote(remote_path)} -Algorithm SHA256).Hash.ToLower()")
    if not r["ok"]:
        return False, ""
    lines = [line.strip() for line in r.get("stdout", "").splitlines() if line.strip()]
    return (True, lines[-1].lower()) if lines else (False, "")


def copy_to_guest(local_path: str, remote_path: str, overwrite: bool = True, verify_hash: bool = True) -> dict[str, Any]:
    """Copy a local host file to the guest atomically.

    Data is written to a remote temporary file first. The temporary file is moved
    into place only after size and optional SHA256 verification succeed. This
    prevents corrupted partial files from being left at the final path.
    """
    src = Path(local_path)
    if not src.is_file():
        raise RuntimeError(f"Local file not found: {local_path}")

    cfg = load_config()
    total = src.stat().st_size
    chunk_size = cfg.limits.copy_chunk_bytes
    remote_parent = str(PureWindowsPath(remote_path).parent)
    remote_tmp = f"{remote_path}.mcp_tmp_{uuid.uuid4().hex}"

    local_hash = sha256_local(src) if verify_hash else None

    init = (
        f"New-Item -ItemType Directory -Force -Path {ps_quote(remote_parent)} | Out-Null; "
        f"if ((Test-Path -LiteralPath {ps_quote(remote_path)}) -and -not ${str(overwrite).lower()}) "
        f"{{ throw 'Remote file exists' }}; "
        f"Remove-Item -LiteralPath {ps_quote(remote_tmp)} -Force -ErrorAction SilentlyContinue; "
        f"[IO.File]::WriteAllBytes({ps_quote(remote_tmp)}, [byte[]]@()); 'ok'"
    )
    r = run_ps_raw(init)
    if not r["ok"]:
        return r

    chunks = 0
    try:
        with src.open("rb") as f:
            while True:
                data = f.read(chunk_size)
                if not data:
                    break
                b64 = base64.b64encode(data).decode("ascii")
                ps = (
                    f"$b=[Convert]::FromBase64String({ps_quote(b64)}); "
                    f"$fs=[IO.File]::Open({ps_quote(remote_tmp)},[IO.FileMode]::Append,[IO.FileAccess]::Write,[IO.FileShare]::Read); "
                    f"try{{$fs.Write($b,0,$b.Length)}}finally{{$fs.Close()}}"
                )
                rr = run_ps_raw(ps)
                if not rr["ok"]:
                    rr["chunks_completed"] = chunks
                    rr["remote_tmp"] = remote_tmp
                    run_ps_raw(f"Remove-Item -LiteralPath {ps_quote(remote_tmp)} -Force -ErrorAction SilentlyContinue")
                    return rr
                chunks += 1

        size_check = run_ps_raw(f"(Get-Item -LiteralPath {ps_quote(remote_tmp)}).Length")
        if not size_check["ok"]:
            run_ps_raw(f"Remove-Item -LiteralPath {ps_quote(remote_tmp)} -Force -ErrorAction SilentlyContinue")
            return size_check
        remote_size = int(size_check["stdout"].strip().splitlines()[-1])
        if remote_size != total:
            run_ps_raw(f"Remove-Item -LiteralPath {ps_quote(remote_tmp)} -Force -ErrorAction SilentlyContinue")
            return {
                "ok": False,
                "error": "remote size mismatch",
                "local_path": local_path,
                "remote_path": remote_path,
                "remote_tmp": remote_tmp,
                "local_size": total,
                "remote_size": remote_size,
                "chunks": chunks,
            }

        result: dict[str, Any] = {
            "ok": True,
            "local_path": local_path,
            "remote_path": remote_path,
            "remote_tmp": remote_tmp,
            "bytes": total,
            "chunks": chunks,
            "chunk_size": chunk_size,
        }

        if verify_hash:
            ok, remote_hash = sha256_remote(remote_tmp)
            result["hash_ok"] = ok and (local_hash == remote_hash)
            result["local_sha256"] = local_hash
            result["remote_sha256"] = remote_hash if ok else "error"
            if not result["hash_ok"]:
                result["ok"] = False
                run_ps_raw(f"Remove-Item -LiteralPath {ps_quote(remote_tmp)} -Force -ErrorAction SilentlyContinue")
                return result

        finalize = (
            f"if ((Test-Path -LiteralPath {ps_quote(remote_path)}) -and -not ${str(overwrite).lower()}) "
            f"{{ Remove-Item -LiteralPath {ps_quote(remote_tmp)} -Force -ErrorAction SilentlyContinue; throw 'Remote file exists' }}; "
            f"Move-Item -LiteralPath {ps_quote(remote_tmp)} -Destination {ps_quote(remote_path)} -Force; 'ok'"
        )
        final = run_ps_raw(finalize)
        if not final["ok"]:
            final["remote_tmp"] = remote_tmp
            return final
        result["remote_tmp"] = None
        return result
    except Exception:
        run_ps_raw(f"Remove-Item -LiteralPath {ps_quote(remote_tmp)} -Force -ErrorAction SilentlyContinue")
        raise


def test_file_copy() -> dict[str, Any]:
    data = bytes(range(256)) * 128
    with tempfile.NamedTemporaryFile(delete=False, suffix=".bin") as tf:
        tf.write(data)
        tmp_local = tf.name
    remote_tmp = r"C:\Windows\Temp\winrm_mcp_test.bin"
    try:
        res = copy_to_guest(tmp_local, remote_tmp, overwrite=True, verify_hash=True)
    finally:
        Path(tmp_local).unlink(missing_ok=True)
        run_ps_raw(f"Remove-Item -LiteralPath {ps_quote(remote_tmp)} -Force -ErrorAction SilentlyContinue")
    return {"ok": res.get("ok", False), "hash_ok": res.get("hash_ok", False), "bytes": res.get("bytes"), "chunks": res.get("chunks"), "detail": res}


def copy_from_guest(remote_path: str, local_path: str, overwrite: bool = True, verify_hash: bool = True) -> dict[str, Any]:
    dst = Path(local_path)
    if dst.exists() and not overwrite:
        raise RuntimeError(f"Local file exists: {local_path}")
    dst.parent.mkdir(parents=True, exist_ok=True)

    cfg = load_config()
    size_res = run_ps_raw(
        f"if (!(Test-Path -LiteralPath {ps_quote(remote_path)})) {{ throw 'Remote file not found' }}; "
        f"(Get-Item -LiteralPath {ps_quote(remote_path)}).Length"
    )
    if not size_res["ok"]:
        return size_res
    total = int(size_res["stdout"].strip().splitlines()[-1])

    remote_hash = None
    if verify_hash:
        ok, remote_hash_value = sha256_remote(remote_path)
        if not ok:
            return {"ok": False, "error": "failed to hash remote file", "remote_path": remote_path}
        remote_hash = remote_hash_value

    offset = 0
    chunks = 0
    tmp_dst = dst.with_name(dst.name + f".mcp_tmp_{uuid.uuid4().hex}")
    try:
        with tmp_dst.open("wb") as out:
            while offset < total:
                take = min(cfg.limits.copy_chunk_bytes, total - offset)
                ps = (
                    f"$fs=[IO.File]::OpenRead({ps_quote(remote_path)}); "
                    f"try{{$fs.Seek({offset},[IO.SeekOrigin]::Begin) | Out-Null; "
                    f"$b=New-Object byte[] {take}; $n=$fs.Read($b,0,$b.Length); "
                    f"[Convert]::ToBase64String($b,0,$n)}}finally{{$fs.Close()}}"
                )
                rr = run_ps_raw(ps)
                if not rr["ok"]:
                    return rr
                out.write(base64.b64decode(rr["stdout"].strip()))
                offset += take
                chunks += 1

        local_size = tmp_dst.stat().st_size
        if local_size != total:
            tmp_dst.unlink(missing_ok=True)
            return {"ok": False, "error": "local size mismatch", "remote_path": remote_path, "local_path": local_path, "remote_size": total, "local_size": local_size, "chunks": chunks}

        result: dict[str, Any] = {"ok": True, "remote_path": remote_path, "local_path": local_path, "bytes": total, "chunks": chunks, "chunk_size": cfg.limits.copy_chunk_bytes}
        if verify_hash:
            local_hash = sha256_local(tmp_dst)
            result["hash_ok"] = local_hash == remote_hash
            result["local_sha256"] = local_hash
            result["remote_sha256"] = remote_hash
            if not result["hash_ok"]:
                result["ok"] = False
                tmp_dst.unlink(missing_ok=True)
                return result

        if dst.exists():
            dst.unlink()
        tmp_dst.replace(dst)
        return result
    except Exception:
        tmp_dst.unlink(missing_ok=True)
        raise

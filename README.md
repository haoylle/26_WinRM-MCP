# winrm-mcp

`winrm-mcp` is an MCP server for controlling a Windows guest VM from a Windows host over WinRM.
It is designed to work alongside a separate `kd-mcp` server for KDNET kernel-debugging workflows.

## Features

- Run PowerShell commands on the guest.
- Run cmd.exe commands on the guest.
- Copy files from host to guest.
- Copy files from guest to host.
- SHA256 verification after file copy.
- Built-in `test_file_copy()` validation tool.
- Start executables or scripts inside the guest.
- Maintain lightweight shell sessions with working-directory state.
- Reboot the guest.
- Configure KDNET and generate a shared state file for `kd-mcp`.

## Host / Guest Layout

Host:

- Codex / MCP Client
- winrm-mcp
- kd-mcp
- WinDbg / kd.exe

Guest:

- Windows VM
- WinRM Service
- Analysis target
- KDNET target configuration

## File Copy Behavior

`copy_to_guest()` transfers files using Base64 chunks over WinRM.

Server defaults:

```yaml
limits:
  copy_chunk_bytes: 8192
```

Example configuration:

```yaml
limits:
  max_stdout_chars: 200000
  copy_chunk_bytes: 2048
  command_timeout_sec: 300
```

The value from `config.yaml` overrides the server default.

After transfer, SHA256 hashes are compared when `verify_hash=true`.

Example result:

```json
{
  "ok": true,
  "hash_ok": true
}
```

## Copy Validation

Use:

```text
test_file_copy()
```

This creates a temporary 32 KB file, copies it to the guest, verifies SHA256, and removes the test file.

Expected result:

```json
{
  "ok": true,
  "hash_ok": true
}
```

## KDNET Workflow

```text
1. configure_kdnet
2. reboot
3. kd-mcp start_from_state
4. kd_command
```

Both repositories must use the same state file, host IP, port, and key.

## WinRM Setup

Run inside the guest:

```powershell
Enable-PSRemoting -Force
```

Verify from the host:

```powershell
Test-WSMan <guest-ip>
```

## Security Notes

- Prefer HTTPS outside lab environments.
- Store passwords in WINRM_PASSWORD.
- Restrict firewall access.
- Review commands before execution.

# winrm-mcp

`winrm-mcp` is an MCP server for controlling a Windows guest VM from a Windows host over WinRM.
It is designed to pair with a separate [`kd-mcp`](../kd-mcp) server for Windows kernel-debugging workflows.

## Features

- Run PowerShell commands on the guest.
- Run `cmd.exe` commands on the guest.
- Copy files from host to guest.
- Copy files from guest to host.
- Start executables or scripts inside the guest.
- Maintain lightweight logical shell sessions with current-directory state.
- Reboot the guest.
- Query guest boot debug settings.
- Configure KDNET boot debugging with `bcdedit`.
- Write a shared KD session state file that `kd-mcp` can read.
- Optional command allowlist/denylist policy.

## How it works with kd-mcp

`winrm-mcp` and `kd-mcp` are intentionally separate MCP servers.
They do **not** communicate over the network with each other. Instead, they coordinate through a shared state file.

Typical flow:

```text
1. winrm-mcp: configure_kdnet
   - runs bcdedit inside the guest
   - writes C:\mcp-state\kd-session.json on the host

2. winrm-mcp: reboot
   - reboots the guest so debug boot settings take effect

3. kd-mcp: start_from_state
   - reads C:\mcp-state\kd-session.json
   - starts kd.exe on the host with the same port/key

4. kd-mcp: kd_command
   - runs commands such as lm, k, !analyze -v
```

Both repos must use the same `state_file`, `port`, and `key` values.

## Requirements

Host:

- Windows 10/11 or Windows Server.
- Python 3.10+.
- Network access to the guest VM's WinRM endpoint.

Guest:

- Windows guest OS.
- WinRM enabled.
- Administrator credentials.
- Firewall allows WinRM from the host.

For KDNET setup, the guest must support Windows network kernel debugging and the selected host IP must be reachable from the guest.

## Enable WinRM on the guest

Run inside the guest as Administrator:

```powershell
Enable-PSRemoting -Force
Set-Item WSMan:\localhost\Service\AllowUnencrypted $true
Set-Item WSMan:\localhost\Service\Auth\Basic $true
```

For safer non-lab usage, configure WinRM over HTTPS instead of using unencrypted HTTP.

## Install

```powershell
git clone https://github.com/<you>/winrm-mcp.git
cd winrm-mcp
.\scripts\install.ps1
```

Edit `config.yaml` after installation.

Set the password through an environment variable rather than storing it in YAML:

```powershell
$env:WINRM_PASSWORD = "guest-admin-password"
$env:WINRM_MCP_CONFIG = "$PWD\config.yaml"
```

## MCP client configuration

Example:

```json
{
  "mcpServers": {
    "winrm": {
      "command": "C:\\tools\\winrm-mcp\\.venv\\Scripts\\winrm-mcp.exe",
      "env": {
        "WINRM_MCP_CONFIG": "C:\\tools\\winrm-mcp\\config.yaml",
        "WINRM_PASSWORD": "replace-with-guest-admin-password"
      }
    }
  }
}
```

## Tools

### `health_check`

Checks config loading and WinRM connectivity.

### `run_ps(script)`

Runs a PowerShell script on the guest.

Example:

```powershell
Get-ComputerInfo | Select-Object WindowsProductName, WindowsVersion
```

### `run_cmd(command)`

Runs a `cmd.exe /c` command on the guest.

Example:

```cmd
whoami && hostname
```

### `open_shell(cwd)` / `session_run(shell_id, command, shell)` / `close_shell(shell_id)`

Provides a lightweight logical shell session that preserves current directory between calls.
This is not a raw interactive terminal; it is safer and better suited to MCP request/response execution.

### `copy_to_guest(local_path, remote_path, overwrite)`

Copies a host file to the guest using base64 chunks over WinRM.

### `copy_from_guest(remote_path, local_path, overwrite)`

Copies a guest file to the host using base64 chunks over WinRM.

### `start_process(file_path, arguments, wait, cwd)`

Starts an executable or script on the guest.

### `reboot(force)`

Reboots the guest.

### `query_debug_settings()`

Runs `bcdedit /enum {current}` and `bcdedit /dbgsettings` on the guest.

### `configure_kdnet(host_ip, port, key, write_state)`

Configures KDNET boot debugging on the guest:

```cmd
bcdedit /debug on
bcdedit /dbgsettings net hostip:<HOST_IP> port:<PORT> key:<KEY>
```

When `write_state=true`, it writes a host-side JSON file such as:

```json
{
  "schema": "winrm-kd-session-v1",
  "guest_host": "192.168.122.50",
  "host_ip": "192.168.122.1",
  "port": 50000,
  "key": "1.2.3.4",
  "created_by": "winrm-mcp"
}
```

`kd-mcp` uses this file with `start_from_state`.

## Security notes

This project is meant for lab VMs and controlled debugging networks.

Avoid exposing WinRM to untrusted networks. Prefer:

- WinRM over HTTPS.
- NTLM/Kerberos/CredSSP only where appropriate.
- Password via environment variable or a secret manager.
- Tight firewall rules.
- Non-empty `allowed_command_prefixes` for shared environments.
- Review of all commands before execution.

## Troubleshooting

### WinRM connection fails

Check from the host:

```powershell
Test-WSMan <guest-ip>
```

### Access denied

Use an Administrator account on the guest and verify UAC/remote admin policy.

### KD does not connect after reboot

Run `query_debug_settings`, confirm `host_ip`, `port`, and `key`, and verify that `kd-mcp` uses the same state file.

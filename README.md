# WinRM-MCP

`winrm-mcp`는 Windows 호스트에서 Windows 게스트 VM을 WinRM으로 제어하기 위한 MCP(Model Context Protocol) 서버입니다.

이 서버는 Codex 또는 MCP Client에서 호출되며, 게스트 VM에 파일을 복사하거나, PowerShell/CMD 명령을 실행하거나, 분석 대상 프로그램을 실행하고, KDNET 커널 디버깅 준비 작업을 자동화하는 데 사용됩니다.

## Features

이 프로젝트는 다음 기능을 제공합니다.

- 게스트 VM에서 PowerShell 스크립트 실행
- 게스트 VM에서 CMD 명령 실행
- 호스트에서 게스트로 파일 복사
- 게스트에서 호스트로 파일 복사
- SHA256 기반 파일 무결성 검증
- 파일 복사 검증용 `test_file_copy()` 도구
- 게스트에서 실행 파일 또는 스크립트 실행
- 현재 디렉터리를 유지하는 논리 쉘 세션
- Sysinternals 기반 분석 편의 도구
- litecov 실행 및 attach helper
- coverage 파일 다운로드 helper
- build 파일 업로드 helper
- 게스트 VM 재부팅
- KDNET 설정 자동화
- KD-MCP와 연동하기 위한 상태 파일 생성

## Architecture

WinRM-MCP는 게스트 VM 안에서 실행하는 프로그램이 아닙니다.

WinRM-MCP는 호스트 Windows에서 실행되고, 게스트 Windows는 WinRM 서비스로 요청을 받는 구조입니다.

```text
Host Windows
  ├─ Claude Code / Codex CLI / MCP Client
  ├─ winrm-mcp
  ├─ kd-mcp
  └─ kd.exe / WinDbg

Guest Windows VM
  ├─ WinRM Service
  ├─ Analysis Target
  └─ KDNET Target Configuration
```

즉, 게스트에서는 WinRM 서비스를 활성화해야 하고, 호스트에서는 이 MCP 서버를 실행해야 합니다.

## Requirements

호스트에는 다음이 필요합니다.

- Windows 10/11 또는 Windows Server
- Python 3.10 이상
- Claude Code, Codex CLI 또는 MCP Client
- 게스트 WinRM 엔드포인트에 접근 가능한 네트워크 연결

게스트에는 다음이 필요합니다.

- Windows 10/11 또는 Windows Server
- 관리자 계정
- WinRM 서비스 활성화
- 호스트에서 접근 가능한 방화벽 규칙

KDNET까지 사용할 경우, 게스트가 Windows 네트워크 커널 디버깅을 지원해야 합니다.

## Enable WinRM on Guest

게스트 VM에서 관리자 PowerShell을 열고 다음 명령을 실행합니다.

```powershell
Enable-PSRemoting -Force
```

네트워크 프로필이 Public이면 WinRM 방화벽 예외가 실패할 수 있습니다. 이 경우 게스트에서 네트워크 프로필을 Private으로 변경한 뒤 다시 실행합니다.

```powershell
Get-NetConnectionProfile
Set-NetConnectionProfile -NetworkCategory Private
Enable-PSRemoting -Force
```

호스트에서 연결을 확인합니다.

```powershell
Test-WSMan <guest-ip>
```

정상이라면 WSMan 응답 정보가 출력됩니다.

## Install

호스트 Windows에서 레포지토리를 클론한 뒤 설치합니다.

```powershell
git clone https://github.com/haoylle/26_WinRM-MCP.git
cd 26_WinRM-MCP
.\scripts\install.ps1
```

설치 후 `examples/config.yaml`을 복사하여 실제 설정 파일을 만듭니다.

```powershell
Copy-Item .\examples\config.yaml .\config.yaml
```

## Configuration

`config.yaml`은 WinRM 연결 정보, 출력 제한, 파일 복사 청크 크기, 재연결 대기 정책, 분석 도구 경로, KDNET 설정을 포함합니다.

예시는 다음과 같습니다.

```yaml
guest:
  host: "192.168.122.50"
  username: "Administrator"
  password: null
  transport: "ntlm"
  scheme: "http"
  port: 5985
  server_cert_validation: "ignore"
  operation_timeout_sec: 60
  read_timeout_sec: 90
  allow_unencrypted: true
  path: "/wsman"

limits:
  max_stdout_chars: 200000
  copy_chunk_bytes: 2048
  command_timeout_sec: 300

recovery:
  reconnect_timeout_sec: 300
  reconnect_interval_sec: 5
  reconnect_settle_sec: 10
  reboot_offline_timeout_sec: 60

analysis:
  sysinternals_dir: "C:\\Users\\Administrator\\Desktop\\SysinternalsSuite"
  litecov_path: "C:\\Users\\Administrator\\Desktop\\covcheck\\litecov.exe"
  coverage_file: "C:\\Users\\Administrator\\Desktop\\covcheck\\sym_cov.txt"
  build_files_dir: "C:\\Users\\Administrator\\Desktop\\build_files"

kdnet:
  host_ip: "192.168.122.1"
  port: 50000
  key: "1.2.3.4"
  state_file: "C:\\mcp-state\\kd-session.json"
  bcdedit_path: "bcdedit.exe"
```

`server.py`의 기본 `copy_chunk_bytes` 값은 8192입니다. 하지만 `config.yaml`에 값이 있으면 설정 파일 값이 우선 적용됩니다.

파일 복사가 불안정하거나 `The command line is too long` 오류가 발생하면 2048 또는 1024처럼 작은 값으로 낮추는 것이 좋습니다.

`recovery` 설정은 재부팅 또는 KD break 해제 후 WinRM이 다시 살아날 때까지 얼마나 기다릴지 결정합니다.

- `reconnect_timeout_sec`: WinRM 재연결 최대 대기 시간
- `reconnect_interval_sec`: 재시도 간격
- `reconnect_settle_sec`: 연결 직후 추가 안정화 대기 시간
- `reboot_offline_timeout_sec`: 재부팅 후 WinRM down 상태를 관찰하는 최대 시간

`analysis` 설정은 기존 분석 환경에서 쓰던 Sysinternals/litecov helper가 사용할 guest 경로를 정의합니다.

- `sysinternals_dir`: `pslist.exe`, `Listdlls.exe`, `PsInfo.exe`가 있는 디렉터리
- `litecov_path`: guest에서 실행할 `litecov.exe` 경로
- `coverage_file`: `download_coverage`가 가져올 guest coverage 파일
- `build_files_dir`: `upload_build_file`가 업로드할 guest 디렉터리

비밀번호는 `config.yaml`에 직접 저장하는 것보다 환경 변수로 지정하는 방식을 권장합니다.

```powershell
$env:WINRM_PASSWORD = "guest-admin-password"
$env:WINRM_MCP_CONFIG = "C:\\tools\\26_WinRM-MCP\\config.yaml"
```

## MCP Client Setup

이 MCP 서버는 stdio 기반 로컬 MCP 서버로 실행됩니다.

아래 예시는 레포지토리를 `C:\tools\26_WinRM-MCP`에 설치했다고 가정합니다. 실제 경로에 맞게 수정해야 합니다.

### Claude Code

Claude Code에서 프로젝트 단위로 등록하려면 프로젝트 루트에서 다음 명령을 실행합니다.

```powershell
claude mcp add winrm `
  --env WINRM_MCP_CONFIG="C:\tools\26_WinRM-MCP\config.yaml" `
  --env WINRM_PASSWORD="guest-admin-password" `
  -- "C:\tools\26_WinRM-MCP\.venv\Scripts\winrm-mcp.exe"
```

사용자 전체 설정으로 등록하고 싶다면 Claude Code의 MCP scope 옵션을 사용하여 user scope로 추가합니다.

```powershell
claude mcp add winrm `
  --scope user `
  --env WINRM_MCP_CONFIG="C:\tools\26_WinRM-MCP\config.yaml" `
  --env WINRM_PASSWORD="guest-admin-password" `
  -- "C:\tools\26_WinRM-MCP\.venv\Scripts\winrm-mcp.exe"
```

수동으로 `.mcp.json`을 사용하는 경우에는 다음처럼 작성할 수 있습니다.

```json
{
  "mcpServers": {
    "winrm": {
      "command": "C:\\tools\\26_WinRM-MCP\\.venv\\Scripts\\winrm-mcp.exe",
      "env": {
        "WINRM_MCP_CONFIG": "C:\\tools\\26_WinRM-MCP\\config.yaml",
        "WINRM_PASSWORD": "guest-admin-password"
      }
    }
  }
}
```

등록 후 Claude Code를 다시 시작하거나 MCP 서버 목록을 갱신한 뒤 `winrm.health_check`를 호출해 연결을 확인합니다.

### Codex CLI

Codex CLI에서는 사용자 설정 파일에 MCP 서버를 추가합니다.

Windows 기준 설정 파일 위치 예시는 다음과 같습니다.

```text
%USERPROFILE%\.codex\config.toml
```

다음 항목을 추가합니다.

```toml
[mcp_servers.winrm]
command = "C:\\tools\\26_WinRM-MCP\\.venv\\Scripts\\winrm-mcp.exe"
env = { WINRM_MCP_CONFIG = "C:\\tools\\26_WinRM-MCP\\config.yaml", WINRM_PASSWORD = "guest-admin-password" }
```

Codex CLI를 다시 시작한 뒤 MCP tool 목록에서 `winrm` 서버가 보이는지 확인합니다.

WinRM 연결 확인은 다음 tool을 먼저 호출하는 방식으로 진행합니다.

```text
winrm.health_check
```

### Using WinRM-MCP and KD-MCP Together

WinRM-MCP와 KD-MCP를 둘 다 사용하는 경우 Claude Code 또는 Codex CLI에 두 MCP 서버를 모두 등록해야 합니다.

WinRM-MCP는 게스트 파일 복사, 명령 실행, KDNET 설정을 담당하고 KD-MCP는 `kd.exe` 연결과 커널 디버거 명령 실행을 담당합니다.

## Tools

### health_check

설정 파일을 읽고 게스트 VM에 WinRM 연결이 가능한지 확인합니다.

내부적으로 PowerShell 버전, 사용자 이름, 호스트 이름을 조회합니다.

### run_ps

게스트 VM에서 PowerShell 스크립트를 실행합니다.

예시는 다음과 같습니다.

```powershell
Get-ComputerInfo | Select-Object WindowsProductName, WindowsVersion
```

### run_cmd

게스트 VM에서 `cmd.exe /c` 명령을 실행합니다.

예시는 다음과 같습니다.

```cmd
whoami && hostname
```

### open_shell / session_run / close_shell

MCP 요청/응답 방식에 맞춘 논리 쉘 세션을 제공합니다.

완전한 대화형 터미널은 아니지만, 현재 디렉터리를 유지하면서 여러 명령을 순차적으로 실행할 수 있습니다.

### copy_to_guest

호스트 파일을 게스트 VM으로 복사합니다.

파일은 Base64 청크로 나누어 WinRM을 통해 전송됩니다. 복사 후 `verify_hash=true`이면 로컬 파일과 원격 파일의 SHA256 해시를 비교합니다.

정상 결과 예시는 다음과 같습니다.

```json
{
  "ok": true,
  "hash_ok": true
}
```

`hash_ok`가 `false`이면 파일이 손상되었을 수 있으므로 실행하지 않는 것이 좋습니다.

### test_file_copy

파일 복사 기능을 검증하는 테스트 도구입니다.

32KB 임시 파일을 생성하여 게스트에 복사하고, SHA256 검증 후 임시 파일을 삭제합니다.

정상 결과 예시는 다음과 같습니다.

```json
{
  "ok": true,
  "hash_ok": true
}
```

### copy_from_guest

게스트 VM의 파일을 호스트로 복사합니다.

이 기능도 `copy_chunk_bytes` 설정을 사용하여 파일을 청크 단위로 읽어옵니다.

### start_process

게스트 VM에서 실행 파일 또는 스크립트를 시작합니다.

`wait=true`이면 프로세스 종료까지 기다리고, 가능한 경우 ExitCode를 반환합니다.

### get_processes / get_dlls / get_system_info / run_sysinternals

Sysinternals 기반 분석 보조 도구입니다.

`analysis.sysinternals_dir`가 설정되어 있어야 합니다.

### find_processes_by_dll / list_dlls_of_process / check_process / is_litecov_running / file_exists

분석 중 자주 필요한 helper입니다.

- `find_processes_by_dll`: 특정 DLL을 로드한 프로세스 찾기
- `list_dlls_of_process`: 특정 프로세스의 DLL 목록 조회
- `check_process`: 프로세스 존재 여부와 PID 확인
- `is_litecov_running`: litecov 실행 여부 확인
- `file_exists`: guest 경로 존재 여부와 기본 metadata 확인

### litecov_spawn / litecov_attach

`litecov.exe`를 새 프로세스로 실행하거나 기존 PID에 attach합니다.

`analysis.litecov_path`가 설정되어 있어야 합니다.

### download_coverage / upload_build_file

분석 산출물 전송 helper입니다.

- `download_coverage`: `analysis.coverage_file`을 호스트로 다운로드
- `upload_build_file`: 로컬 빌드 파일을 guest의 `analysis.build_files_dir` 아래에 unique name으로 업로드

### reboot

게스트 VM을 WinRM을 통해 재부팅합니다.

재부팅 후에는 WinRM 연결이 잠시 끊길 수 있습니다.

단순히 재부팅 요청만 보내므로, 실제로 부팅이 끝날 때까지 기다리려면 `reboot_and_wait`를 사용하는 것이 좋습니다.

### wait_for_winrm

게스트가 재부팅 중이거나 KD break에서 복귀한 뒤 WinRM이 다시 응답할 때까지 polling합니다.

각 시도마다 새 WinRM 세션을 만들어 stale connection을 재사용하지 않습니다.

### reboot_and_wait

게스트에 재부팅을 요청한 뒤 WinRM이 한 번 끊기는지 관찰하고, 부팅 후 다시 응답할 때까지 기다립니다.

재부팅 중 연결이 끊겨 예외가 발생해도 expected disconnect로 처리하고 재접속 단계로 넘어갑니다.

### query_debug_settings

게스트 VM에서 현재 부팅 디버깅 설정을 조회합니다.

내부적으로 `bcdedit /enum {current}` 및 `bcdedit /dbgsettings`를 실행합니다.

### configure_kdnet

게스트 VM에서 KDNET 커널 디버깅 설정을 적용합니다.

성공하면 호스트에 `state_file`을 생성합니다. 이 파일은 KD-MCP의 `start_from_state`가 읽어 커널 디버거 연결에 사용합니다.

## KD-MCP Workflow

WinRM-MCP와 KD-MCP를 함께 사용할 때의 일반적인 순서는 다음과 같습니다.

```text
1. winrm-mcp: configure_kdnet
2. winrm-mcp: reboot_and_wait
3. kd-mcp: start_from_state
4. kd-mcp: kd_command
5. KD가 break 상태면 kd-mcp: resume_for_winrm
6. winrm-mcp: wait_for_winrm
```

두 레포지토리는 동일한 `state_file`, `port`, `key` 값을 사용해야 합니다.

## Troubleshooting

### WinRM connection fails

호스트에서 다음 명령으로 게스트 WinRM 연결을 확인합니다.

```powershell
Test-WSMan <guest-ip>
```

게스트 네트워크가 Public이면 방화벽 예외가 적용되지 않을 수 있습니다.

게스트가 재부팅 중이거나 KD break에서 막 풀린 직후라면 `wait_for_winrm` 또는 `reboot_and_wait`를 먼저 호출하는 편이 낫습니다.

### File hash mismatch

파일 복사 후 호스트와 게스트의 SHA256이 다르면 복사 중 손상된 것입니다.

이 경우 다음을 확인합니다.

- `copy_to_guest` 결과의 `hash_ok`
- 호스트/게스트 파일 크기
- `copy_chunk_bytes` 설정
- MCP 서버 재시작 여부

복사 결과가 `hash_ok=true`가 아니면 파일을 실행하지 않는 것이 좋습니다.

### Executable is not valid for this OS platform

실행 파일이 손상되었거나 현재 OS와 맞지 않는 형식일 때 발생할 수 있습니다.

먼저 호스트 파일과 게스트 파일의 SHA256을 비교해야 합니다.

```powershell
Get-FileHash .\target.exe -Algorithm SHA256
```

## Security Notes

이 프로젝트는 실험실 VM, 취약점 분석 환경, 커널 디버깅 환경을 대상으로 합니다.

신뢰할 수 없는 네트워크에 WinRM을 노출하지 않는 것이 좋습니다.

가능하면 다음 방식을 사용합니다.

- WinRM over HTTPS
- 비밀번호 환경 변수 사용
- 방화벽 접근 제한
- 명령 실행 전 검토
- 공유 환경에서는 `allowed_command_prefixes` 설정

## License

MIT License

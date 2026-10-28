# chainproxy test VM - one-time bootstrap (runs INSIDE the Windows VM, as Administrator or SYSTEM).
#
# Served by `vmtest.py bootstrap` from the host with the placeholders filled in, and run either
# automatically through the QEMU guest agent or by pasting the printed one-liner into an
# elevated PowerShell. Safe to run again.
#
#   1. OpenSSH server (Windows optional feature; falls back to the MSI served by the host)
#   2. firewall rule for TCP 22
#   3. the host's public key for key-only login (admin and per-user key files, strict ACLs)
#   4. no sleep / hibernation (tests must not find the VM asleep)
#   5. optional automatic logon of the test user (needed for the GUI test)
#
# Keep this file ASCII-only.

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

$PubKey   = '__PUBKEY__'
$WinUser  = '__WIN_USER__'
$MsiUrl   = '__MSI_URL__'
$AutoLogonPassword = '__AUTOLOGON_PASSWORD__'

function Say([string]$m) { Write-Host "[bootstrap] $m" }

function Add-Key([string]$file) {
    $dir = Split-Path $file
    if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
    $lines = @()
    if (Test-Path $file) { $lines = @(Get-Content $file -ErrorAction SilentlyContinue) }
    if ($lines -notcontains $PubKey) {
        $lines += $PubKey
        [IO.File]::WriteAllLines($file, [string[]]$lines, (New-Object Text.ASCIIEncoding))
    }
}

try {
    $id = [Security.Principal.WindowsIdentity]::GetCurrent()
    $admin = (New-Object Security.Principal.WindowsPrincipal $id).IsInRole(
        [Security.Principal.WindowsBuiltInRole]::Administrator)
    if (-not ($admin -or $id.IsSystem)) { throw 'run this in an elevated PowerShell (Run as administrator)' }

    # 1. OpenSSH server ---------------------------------------------------------------
    if (-not (Get-Service sshd -ErrorAction SilentlyContinue)) {
        try {
            $cap = Get-WindowsCapability -Online | Where-Object Name -like 'OpenSSH.Server*' | Select-Object -First 1
            if ($cap) {
                Say "installing $($cap.Name) (Windows optional feature, can take several minutes) ..."
                Add-WindowsCapability -Online -Name $cap.Name | Out-Null
            }
        } catch { Say "optional feature install failed: $($_.Exception.Message)" }
        if (-not (Get-Service sshd -ErrorAction SilentlyContinue)) {
            if (-not $MsiUrl) { throw 'OpenSSH feature unavailable and no MSI offered (run: vmtest.py fetch, then bootstrap again)' }
            Say "installing OpenSSH from the host ($MsiUrl) ..."
            $msi = Join-Path $env:TEMP 'OpenSSH-Win64.msi'
            Invoke-WebRequest -Uri $MsiUrl -OutFile $msi -UseBasicParsing
            $p = Start-Process msiexec.exe -Wait -PassThru -ArgumentList "/i `"$msi`" ADDLOCAL=Server /qn /norestart"
            if ($p.ExitCode -ne 0 -and $p.ExitCode -ne 3010) { throw "msiexec failed with $($p.ExitCode)" }
        }
        if (-not (Get-Service sshd -ErrorAction SilentlyContinue)) { throw 'OpenSSH server could not be installed' }
    }
    Set-Service sshd -StartupType Automatic
    Start-Service sshd
    Say 'sshd running'

    # 2. firewall ---------------------------------------------------------------------
    if (-not (Get-NetFirewallRule -Name 'chainproxy-sshd' -ErrorAction SilentlyContinue)) {
        New-NetFirewallRule -Name 'chainproxy-sshd' -DisplayName 'OpenSSH (chainproxy tests)' `
            -Direction Inbound -Protocol TCP -LocalPort 22 -Action Allow -Profile Any | Out-Null
    }

    # 3. keys -------------------------------------------------------------------------
    # administrators read C:\ProgramData\ssh\administrators_authorized_keys (default sshd_config);
    # other users read %USERPROFILE%\.ssh\authorized_keys. Write both; SIDs keep it language-neutral.
    $adminKeys = Join-Path $env:ProgramData 'ssh\administrators_authorized_keys'
    Add-Key $adminKeys
    icacls $adminKeys /inheritance:r /grant '*S-1-5-32-544:F' /grant '*S-1-5-18:F' | Out-Null

    $prof = Get-CimInstance Win32_UserProfile |
        Where-Object { $_.LocalPath -and ((Split-Path $_.LocalPath -Leaf) -ieq $WinUser) } |
        Select-Object -First 1 -ExpandProperty LocalPath
    if (-not $prof) { $prof = Join-Path (Split-Path $env:PUBLIC) $WinUser }
    $userKeys = Join-Path $prof '.ssh\authorized_keys'
    Add-Key $userKeys
    icacls $userKeys /inheritance:r /grant "${WinUser}:F" /grant '*S-1-5-18:F' /grant '*S-1-5-32-544:F' | Out-Null
    Say "key installed for $WinUser"

    # 4. power ------------------------------------------------------------------------
    powercfg /change standby-timeout-ac 0 | Out-Null
    powercfg /change hibernate-timeout-ac 0 | Out-Null
    powercfg /change monitor-timeout-ac 0 | Out-Null
    powercfg /hibernate off | Out-Null

    # 5. automatic logon (optional) ----------------------------------------------------
    if ($AutoLogonPassword) {
        $wl = 'HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Winlogon'
        Set-ItemProperty $wl -Name AutoAdminLogon -Value '1'
        Set-ItemProperty $wl -Name DefaultUserName -Value $WinUser
        Set-ItemProperty $wl -Name DefaultPassword -Value $AutoLogonPassword
        Set-ItemProperty $wl -Name DefaultDomainName -Value $env:COMPUTERNAME
        $pl = 'HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\PasswordLess\Device'
        if (Test-Path $pl) { Set-ItemProperty $pl -Name DevicePasswordLessBuildVersion -Value 0 }
        Say "automatic logon enabled for $WinUser (takes effect after the next restart)"
    }

    Set-Content -Path (Join-Path $env:ProgramData 'chainproxy-vm-bootstrap.txt') -Value (Get-Date -Format s)
    Say 'done - the host can now connect with ssh'
} catch {
    Write-Host "[bootstrap] ERROR: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}

# Helpers shared by the guest-side test scripts (dot-sourced). ASCII only.
# Native programs are called WITHOUT redirection so their output streams straight to ssh
# and PowerShell 5.1 does not wrap stderr lines into error records.

$ErrorActionPreference = 'Continue'
$ProgressPreference = 'SilentlyContinue'

$script:Failures = 0

function Check([bool]$ok, [string]$msg) {
    if ($ok) { Write-Host "PASS  $msg" } else { Write-Host "FAIL  $msg"; $script:Failures++ }
}

function Find-Python {
    # a fresh per-user install is not on this session's PATH yet: look in the usual place first
    $c = Get-ChildItem "$env:LOCALAPPDATA\Programs\Python\Python3*\python.exe" -ErrorAction SilentlyContinue |
        Sort-Object FullName -Descending | Select-Object -First 1
    if ($c) { return $c.FullName }
    foreach ($name in 'python', 'python3') {
        $cmd = Get-Command $name -ErrorAction SilentlyContinue |
            Where-Object { $_.Source -notlike '*\WindowsApps\*' } | Select-Object -First 1
        if ($cmd) { return $cmd.Source }
    }
    $py = Get-Command py -ErrorAction SilentlyContinue
    if ($py) {
        $exe = & py -3 -c "import sys; print(sys.executable)" 2>$null
        if ($LASTEXITCODE -eq 0 -and $exe) { return ($exe | Select-Object -Last 1).Trim() }
    }
    return $null
}

function Get-Pythonw([string]$py) {
    $w = Join-Path (Split-Path $py) 'pythonw.exe'
    if (Test-Path $w) { return $w }
    return $py
}

function Test-InteractiveUser {
    # true when this user has a desktop session (explorer.exe running as this user)
    foreach ($p in Get-CimInstance Win32_Process -Filter "Name='explorer.exe'") {
        $o = Invoke-CimMethod -InputObject $p -MethodName GetOwner
        if ($o.User -ieq $env:USERNAME) { return $true }
    }
    return $false
}

function Start-Interactive([string]$Name, [string]$Exe, [string]$Arguments, [string]$WorkDir) {
    # run a program on this user's desktop (an ssh session itself has no visible desktop)
    Unregister-ScheduledTask -TaskName $Name -Confirm:$false -ErrorAction SilentlyContinue
    $a = New-ScheduledTaskAction -Execute $Exe -Argument $Arguments -WorkingDirectory $WorkDir
    $p = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Limited
    $s = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
        -ExecutionTimeLimit (New-TimeSpan -Hours 2) -MultipleInstances IgnoreNew
    Register-ScheduledTask -TaskName $Name -Action $a -Principal $p -Settings $s -Force | Out-Null
    Start-ScheduledTask -TaskName $Name
    Start-Sleep -Seconds 2
}

function Wait-Interactive([string]$Name, [int]$TimeoutSec = 300) {
    # returns the task's exit code, or $null on timeout
    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    while ((Get-Date) -lt $deadline) {
        $t = Get-ScheduledTask -TaskName $Name -ErrorAction SilentlyContinue
        if (-not $t) { return $null }
        if ($t.State -ne 'Running') { return (Get-ScheduledTaskInfo -TaskName $Name).LastTaskResult }
        Start-Sleep -Seconds 1
    }
    return $null
}

function Stop-Interactive([string]$Name) {
    Stop-ScheduledTask -TaskName $Name -ErrorAction SilentlyContinue
    Unregister-ScheduledTask -TaskName $Name -Confirm:$false -ErrorAction SilentlyContinue
}

function Stop-TestProcesses([string]$Under) {
    # kill python / sing-box processes started from the test folder (not this shell)
    Get-CimInstance Win32_Process | Where-Object {
        $_.ProcessId -ne $PID -and (
            ($_.CommandLine -and $_.CommandLine -like "*$Under*" -and $_.Name -match '^(python|pythonw)\.exe$') -or
            ($_.ExecutablePath -and $_.ExecutablePath -like "$Under*")
        )
    } | ForEach-Object { try { Invoke-CimMethod -InputObject $_ -MethodName Terminate | Out-Null } catch { } }
}

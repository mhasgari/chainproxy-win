# Put the test VM back to "before chainproxy": run by `vmtest.py clean` (the script text is sent
# over ssh, it does not need anything deployed). ASCII only, Windows PowerShell 5.1.
# Always removed : deployed test copy, installed Chain Proxy, installers, shortcuts, tasks,
#                  leftover processes, the proxy settings the app set.
# Also with -Full : Python (the per-user install made by setup.ps1) and Inno Setup.
# Never touched  : OpenSSH / sshd, the authorized key, the firewall rule, autologon, the user.
param([bool]$Full = $true)
$ErrorActionPreference = 'Continue'
$ProgressPreference = 'SilentlyContinue'
$script:Failures = 0
function Say($m) { Write-Host "[clean] $m" }
function Check([bool]$ok, [string]$msg) {
    if ($ok) { Write-Host "PASS  $msg" } else { Write-Host "FAIL  $msg"; $script:Failures++ }
}
$lp = $env:LOCALAPPDATA
$app = "$lp\Programs\ChainProxy"
$test = "$HOME\chainproxy-test"
$ie = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Internet Settings'

# 1. give the Windows proxy settings back and stop everything that belongs to the project
$py = Get-ChildItem "$lp\Programs\Python\Python3*\python.exe" -ErrorAction SilentlyContinue | Select-Object -First 1
foreach ($d in @("$test\repo", $app)) {
    if ($py -and (Test-Path "$d\chain.py")) { Say "chain.py off in $d"; & $py.FullName "$d\chain.py" off | Out-Null }
}
Get-ScheduledTask -TaskName 'chainproxy-*' -ErrorAction SilentlyContinue | ForEach-Object {
    Stop-ScheduledTask -TaskName $_.TaskName -ErrorAction SilentlyContinue
    Unregister-ScheduledTask -TaskName $_.TaskName -Confirm:$false -ErrorAction SilentlyContinue
}
$mine = @("$lp\Programs\", "$HOME\chainproxy")
Get-Process python, pythonw, sing-box, ISCC, Compil32, ChainProxy-Setup* -ErrorAction SilentlyContinue |
    Where-Object { $p = $_.Path; $p -and ($mine | Where-Object { $p -like "$_*" }) } |
    Stop-Process -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 1

# 2. uninstall Chain Proxy the way a user would, then sweep what is left
if (Test-Path "$app\unins000.exe") {
    Say "uninstalling Chain Proxy"
    Start-Process "$app\unins000.exe" -ArgumentList '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART' -Wait
    Start-Sleep -Seconds 2
}
foreach ($p in @($app, $test, "$HOME\chainproxy-installer")) {
    if (Test-Path $p) { Remove-Item $p -Recurse -Force -ErrorAction SilentlyContinue }
}
Get-ChildItem $HOME -Force -ErrorAction SilentlyContinue |
    Where-Object { $_.Name -match '^(ChainProxy-Setup.*\.exe|chainproxy.*\.tar\.gz|inst.*\.log|installer-.*\.log)$' -or
        ($_.Name -match '^vmtest-.*\.ps1$' -and $_.LastWriteTime -lt (Get-Date).AddMinutes(-30)) } |   # not the file that runs us
    Remove-Item -Force -ErrorAction SilentlyContinue
Get-ChildItem $env:TEMP -Force -ErrorAction SilentlyContinue |
    Where-Object { $_.Name -match '^(chainproxy|innosetup)' } |
    Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
Get-ChildItem ([Environment]::GetFolderPath('Desktop')), "$env:APPDATA\Microsoft\Windows\Start Menu\Programs" -Filter 'Chain Proxy*' -ErrorAction SilentlyContinue |
    Remove-Item -Recurse -Force -ErrorAction SilentlyContinue

# 3. the proxy settings must not point at our port any more
$cur = Get-ItemProperty $ie
if ($cur.ProxyServer -like '127.0.0.1:*') {
    Set-ItemProperty $ie -Name ProxyEnable -Value 0
    Remove-ItemProperty $ie -Name ProxyServer -ErrorAction SilentlyContinue
}

# 4. tools that the project's first run / the installer build put there
if ($Full) {
    $k = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\*'
    $bundle = Get-ItemProperty $k -ErrorAction SilentlyContinue |
        Where-Object { $_.DisplayName -match '^Python 3\.\d+\.\d+ \(64-bit\)$' -and $_.QuietUninstallString }
    foreach ($b in $bundle) {
        Say "uninstalling $($b.DisplayName)"
        Start-Process cmd.exe -ArgumentList '/c', "`"$($b.QuietUninstallString)`"" -Wait -WindowStyle Hidden
    }
    $inno = "$lp\Programs\Inno Setup 6\unins000.exe"
    if (Test-Path $inno) {
        Say "uninstalling Inno Setup"
        Start-Process $inno -ArgumentList '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART' -Wait
    }
    foreach ($p in @("$lp\Programs\Python", "$lp\Programs\Inno Setup 6", "$lp\pip")) {
        if (Test-Path $p) { Remove-Item $p -Recurse -Force -ErrorAction SilentlyContinue }
    }
    $up = [Environment]::GetEnvironmentVariable('Path', 'User')
    if ($up) {
        $kept = ($up -split ';' | Where-Object { $_ -and $_ -notmatch '\\Programs\\Python\\' }) -join ';'
        if ($kept -ne $up) { [Environment]::SetEnvironmentVariable('Path', $kept, 'User') }
    }
    Get-ChildItem $env:TEMP -Filter 'Python 3*.log' -ErrorAction SilentlyContinue | Remove-Item -Force -ErrorAction SilentlyContinue
}

# 5. verdict
$left = @(Get-Process python, pythonw, sing-box -ErrorAction SilentlyContinue)
Check (-not (Test-Path $app)) 'Chain Proxy is not installed'
Check (-not (Test-Path $test)) 'test copy (chainproxy-test) is gone'
Check ($left.Count -eq 0) 'no python / sing-box processes'
Check ((Get-ItemProperty $ie).ProxyServer -notlike '127.0.0.1:*') 'Windows proxy does not point at 127.0.0.1'
Check (-not (Get-ScheduledTask -TaskName 'chainproxy-*' -ErrorAction SilentlyContinue)) 'no chainproxy scheduled tasks'
if ($Full) {
    Check (-not (Get-ChildItem "$lp\Programs\Python\Python3*\python.exe" -ErrorAction SilentlyContinue)) 'Python is removed'
    Check (-not (Test-Path "$lp\Programs\Inno Setup 6")) 'Inno Setup is removed'
}
Check ((Get-Service sshd -ErrorAction SilentlyContinue).Status -eq 'Running') 'sshd still running (the test link stays usable)'
Write-Host ('CLEAN RESULT: ' + $(if ($script:Failures -eq 0) { 'PASS' } else { 'FAIL' }))
exit $script:Failures

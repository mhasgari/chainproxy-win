# Test of a built installer inside the VM: run by `vmtest.py installer`. ASCII only.
#   $Setup : file name of the installer in the user's home directory
#   $Full  : the "Full" installer (Python + sing-box inside)
#   $PrePython : '' (clean machine), 'full' (a working Python exists first) or 'notk' (a Python
#                WITHOUT tkinter exists first: setup.ps1 must still end up with a working one)
param([string]$Setup, [bool]$Full = $false, [string]$PrePython = '')
$ErrorActionPreference = 'Continue'
$ProgressPreference = 'SilentlyContinue'
$script:Failures = 0
function Check([bool]$ok, [string]$msg) {
    if ($ok) { Write-Host "PASS  $msg" } else { Write-Host "FAIL  $msg"; $script:Failures++ }
}
function Say($m) { Write-Host "== $m ==" }
$s = Join-Path $HOME $Setup
$app = "$env:LOCALAPPDATA\Programs\ChainProxy"
$lnk = "$env:APPDATA\Microsoft\Windows\Start Menu\Programs\Chain Proxy.lnk"
$desk = [Environment]::GetFolderPath('Desktop') + '\Chain Proxy.lnk'
$ie = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Internet Settings'
$proxyBefore = (Get-ItemProperty $ie).ProxyEnable

if ($PrePython) {
    Say "pre-existing Python ($PrePython)"
    $tk = if ($PrePython -eq 'notk') { 'Include_tcltk=0' } else { 'Include_tcltk=1' }
    $pp = Start-Process "$HOME\python-pre.exe" -ArgumentList '/quiet', 'InstallAllUsers=0', 'PrependPath=1', $tk, 'Include_launcher=0', 'Include_test=0', 'Include_doc=0', 'Shortcuts=0' -Wait -PassThru
    Check ($pp.ExitCode -eq 0) "pre-existing Python installed ($($pp.ExitCode))"
    $pre = Get-ChildItem "$env:LOCALAPPDATA\Programs\Python\Python3*\python.exe" | Select-Object -First 1
    & $pre.FullName -c "import tkinter" 2>$null
    Check (($LASTEXITCODE -eq 0) -eq ($PrePython -eq 'full')) "pre-existing Python has tkinter: $($LASTEXITCODE -eq 0)"
}
Say "install ($Setup)"
$p = Start-Process $s -ArgumentList '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', '/TASKS=desktopicon', "/LOG=$HOME\installer-inno.log" -Wait -PassThru
Check ($p.ExitCode -eq 0) "installer exit code ($($p.ExitCode))"
foreach ($f in 'chain.py', 'gui.py', 'tray.py', 'quit.bat', 'assets\chainproxy-48.png', 'assets\chainproxy-256.png', 'Run.bat', 'setup.ps1', 'stop.bat', 'LICENSE', 'chainproxy.ico', 'subs.txt', 'config.json',
              'docs\Chain-Proxy-Quick-Start-fa.pdf', 'docs\QUICKSTART.md', 'unins000.exe') {
    Check (Test-Path "$app\$f") "installed: $f"
}
Check (@(Get-Content "$app\subs.txt" | Where-Object { $_ -match 'GeminiRoute/sub/best.txt' }).Count -eq 1) 'subs.txt is the template (second link = GeminiRoute best)'
Check ((Test-Path $lnk) -and (Test-Path $desk)) 'Start Menu and desktop shortcuts exist'
$bytes = [IO.File]::ReadAllBytes("$app\Run.bat")
Check (($bytes | Where-Object { $_ -eq 13 }).Count -gt 0) 'Run.bat has CRLF line endings'
if ($Full) {
    Check (Test-Path "$app\THIRD-PARTY-NOTICES.txt") 'third-party notices installed'
    Check ((Get-ChildItem "$app\offline\chainlantern-*-windows-amd64.zip").Count -eq 1) 'the Lantern engine package is inside'
    Check ((Get-ChildItem "$app\offline\python-*.exe").Count -eq 1 -and (Get-ChildItem "$app\offline\sing-box-*windows*.zip").Count -eq 1) 'Python installer and sing-box zip are inside'
} else {
    Check (-not (Get-ChildItem "$app\offline\*.exe", "$app\offline\*.zip" -ErrorAction SilentlyContinue)) 'light installer carries no Python / sing-box'
}

Say "first run (setup.ps1 shortcut: installs Python and sing-box when missing)"
$sw = [Diagnostics.Stopwatch]::StartNew()
powershell -NoProfile -ExecutionPolicy Bypass -File "$app\setup.ps1" shortcut
Check ($LASTEXITCODE -eq 0) "setup.ps1 exit code ($LASTEXITCODE, $([int]$sw.Elapsed.TotalSeconds)s)"
$py = Get-ChildItem "$env:LOCALAPPDATA\Programs\Python\Python3*\python.exe" -ErrorAction SilentlyContinue | Select-Object -First 1
Check ([bool]$py) 'Python is installed'
$pyCount = @(Get-ChildItem "$env:LOCALAPPDATA\Programs\Python\Python3*\python.exe" -ErrorAction SilentlyContinue).Count
if ($PrePython -eq 'full') { Check ($pyCount -eq 1) 'the existing Python was reused (no second Python)' }
Check (Test-Path "$app\core\sing-box.exe") 'sing-box is installed'
if ($py) {
    $v = & $py.FullName "$app\chain.py" ensure
    Check ($LASTEXITCODE -eq 0) "chain.py ensure ($($v | Select-Object -Last 1))"
    & $py.FullName -c "import tkinter" 2>$null
    Check ($LASTEXITCODE -eq 0) 'tkinter works'
}

$o = cmd /c "`"$app\stop.bat`" 2>&1"
Check ($LASTEXITCODE -eq 0 -and ($o -join ' ') -match 'not running') "stop.bat finds Python and reports not running ($($o -join ' '))"
$o = cmd /c "`"$app\next.bat`" 2>&1"
Check ($LASTEXITCODE -eq 0 -and ($o -join ' ') -match 'not running') 'next.bat finds Python and reports not running'

Say "upgrade keeps user data"
Set-Content "$app\subs.txt" 'https://my.real.link/x' -Encoding ASCII
$p = Start-Process $s -ArgumentList '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART' -Wait -PassThru
Check ($p.ExitCode -eq 0) 'upgrade exit code'
Check ((Get-Content "$app\subs.txt") -eq 'https://my.real.link/x') 'subs.txt survived the upgrade'

Say "uninstall"
$p = Start-Process "$app\unins000.exe" -ArgumentList '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART' -Wait -PassThru
Start-Sleep -Seconds 3
Check ($p.ExitCode -eq 0) 'uninstaller exit code'
Check (-not (Test-Path $app)) 'program folder removed'
Check (-not ((Test-Path $lnk) -or (Test-Path $desk))) 'shortcuts removed'
Check ((Get-ItemProperty $ie).ProxyEnable -eq $proxyBefore) 'Windows proxy setting unchanged'
Write-Host ('INSTALLER RESULT: ' + $(if ($script:Failures -eq 0) { 'PASS' } else { 'FAIL' }))
exit $script:Failures

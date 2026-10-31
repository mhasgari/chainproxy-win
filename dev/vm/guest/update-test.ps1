# Self-update test inside the VM: run by `vmtest.py update`. ASCII only.
#   $OldInstaller : file name (in the home directory) of the CURRENT installer
#   $Api          : URL of the fake "releases/latest" JSON served by the host (offers a newer version)
#   $NewVersion   : the version that the fake release announces
param([string]$OldInstaller, [string]$Api, [string]$NewVersion)
. "$PSScriptRoot\common.ps1"
$app = "$env:LOCALAPPDATA\Programs\ChainProxy"
$ie = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Internet Settings'

Write-Host '== install the current version =='
$p = Start-Process "$HOME\$OldInstaller" -ArgumentList '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART' -Wait -PassThru
Check ($p.ExitCode -eq 0) 'installer exit code'
powershell -NoProfile -ExecutionPolicy Bypass -File "$app\setup.ps1" shortcut | Out-Null
$py = Find-Python
$before = (Select-String -Path "$app\chain.py" -Pattern '^__version__ = "(.+)"').Matches[0].Groups[1].Value
Write-Host "installed version: $before"
Check ($before -ne $NewVersion) 'the installed version is older than the announced one'
# the user's own data must survive the update
Set-Content "$app\profiles_first.txt" 'vless://11111111-2222-3333-4444-555555555555@keep.test:443?security=tls&type=ws#keep' -Encoding ASCII
Set-Content "$app\config.json" ('{"lantern_enabled": false, "update_api": "' + $Api + '", "update_first_check_seconds": 20, "auto_update": true, "update_check_hours": 1}') -Encoding ASCII

Write-Host '== start the window on the desktop (it checks for updates 20 s later) =='
Start-Interactive 'chainproxy-update' (Get-Pythonw $py) "`"$app\gui.py`"" $app
$seen = $false
for ($i = 0; $i -lt 12 -and -not $seen; $i++) {
    Start-Sleep -Seconds 1
    $seen = [bool](Get-CimInstance Win32_Process | Where-Object { $_.Name -eq 'pythonw.exe' -and $_.CommandLine -like '*gui.py*' })
}
Check $seen 'the window runs (in the tray)'
Write-Host '== wait for the automatic update =='
$deadline = (Get-Date).AddSeconds(150); $after = $before
while ((Get-Date) -lt $deadline) {
    Start-Sleep -Seconds 4
    try { $after = (Select-String -Path "$app\chain.py" -Pattern '^__version__ = "(.+)"').Matches[0].Groups[1].Value } catch { }
    if ($after -eq $NewVersion) { break }
}
Write-Host "version after: $after"
Check ($after -eq $NewVersion) "the app updated itself to $NewVersion"
$t0 = Get-Date; $guis = @()
while (((Get-Date) - $t0).TotalSeconds -lt 60) {
    $guis = @(Get-CimInstance Win32_Process | Where-Object { $_.Name -eq 'pythonw.exe' -and $_.CommandLine -like '*gui.py*' })
    if ($guis.Count -ge 1) { break }
    Start-Sleep -Seconds 2
}
Write-Host ("window back after {0:N0} s" -f ((Get-Date) - $t0).TotalSeconds)
Start-Sleep -Seconds 4
$guis = @(Get-CimInstance Win32_Process | Where-Object { $_.Name -eq 'pythonw.exe' -and $_.CommandLine -like '*gui.py*' })
Check ($guis.Count -eq 1) "exactly one window is running again after the update ($($guis.Count))"
Check ((Get-Content "$app\profiles_first.txt" -ErrorAction SilentlyContinue) -match 'keep.test') 'user data (profiles) survived the update'
Check ((Get-Content "$app\config.json" -Raw) -match 'update_api') 'config.json survived the update'
Check (Test-Path "$app\unins000.exe") 'uninstaller still present'
Check ((Get-ItemProperty $ie).ProxyEnable -eq 0) 'Windows proxy untouched'
Check (-not (Test-Path "$app\.quit_request")) 'no stale quit request left behind'

Write-Host '== uninstall closes the window in the tray =='
$p = Start-Process "$app\unins000.exe" -ArgumentList '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART' -Wait -PassThru
Start-Sleep -Seconds 3
Check ($p.ExitCode -eq 0) 'uninstaller exit code'
Check (-not (Get-CimInstance Win32_Process | Where-Object { $_.Name -eq 'pythonw.exe' -and $_.CommandLine -like '*gui.py*' })) 'the window in the tray was closed by the uninstaller'
for ($i = 0; $i -lt 15 -and (Test-Path $app); $i++) { Start-Sleep -Seconds 1 }     # the uninstaller removes itself last
Check (-not (Test-Path $app)) 'program folder removed'
if (Test-Path $app) { try { Remove-Item $app -Force -ErrorAction Stop; Write-Host 'manual removal worked (nothing was holding it)' } catch { Write-Host ('manual removal failed: ' + $_.Exception.Message) }; Write-Host ('left in the folder: ' + ((Get-ChildItem $app -Recurse -Force | Select-Object -First 12 | ForEach-Object { $_.FullName.Substring($app.Length) }) -join ', ')); Write-Host ('processes: ' + ((Get-Process pythonw, python, chainlantern -ErrorAction SilentlyContinue | ForEach-Object { $_.Name + ':' + $_.Id }) -join ' ')) }
Stop-Interactive 'chainproxy-update'
Write-Host ('UPDATE RESULT: ' + $(if ($script:Failures -eq 0) { 'PASS' } else { 'FAIL' }))
exit $script:Failures

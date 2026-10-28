# Install test: runs the real first-run path (setup.ps1) and checks what it left behind.
# Usage (inside the VM): powershell -File install.ps1 -Repo <deployed project folder>
param([Parameter(Mandatory = $true)][string]$Repo)
. (Join-Path $PSScriptRoot 'common.ps1')

$setup = Join-Path $Repo 'setup.ps1'
Write-Host "== setup.ps1 shortcut (first run) =="
& powershell -NoProfile -ExecutionPolicy Bypass -File $setup shortcut
Check ($LASTEXITCODE -eq 0) "setup.ps1 first run exit code ($LASTEXITCODE)"

$py = Find-Python
Check ([bool]$py) "Python found ($py)"
if ($py) {
    $tk = & $py -c "import tkinter, sys; print(sys.version.split()[0], tkinter.TkVersion)"
    Check ($LASTEXITCODE -eq 0) "Python + tkinter work ($tk)"
}

$core = Join-Path $Repo 'core\sing-box.exe'
Check (Test-Path $core) 'sing-box.exe installed into core\'
if (Test-Path $core) {
    $vout = @(& $core version)          # read it all: Select-Object -First 1 can kill the pipe and set a non-zero exit code
    $rc = $LASTEXITCODE
    $v = $vout | Select-Object -First 1
    Check ($rc -eq 0) "sing-box runs ($v)"
    $tags = ($vout | Select-String 'Tags') -join ' '
    Check ($tags -match 'with_clash_api') "sing-box build has the Clash API ($tags)"
}

$runBat = Join-Path $Repo 'Run.bat'
$ws = New-Object -ComObject WScript.Shell
$links = @(
    (Join-Path ([Environment]::GetFolderPath('Desktop')) 'Chain Proxy.lnk'),
    (Join-Path ([Environment]::GetFolderPath('Programs')) 'Chain Proxy.lnk')
)
foreach ($lnk in $links) {
    $exists = Test-Path $lnk
    Check $exists "shortcut exists: $lnk"
    if ($exists) {
        $s = $ws.CreateShortcut($lnk)
        Check ($s.TargetPath -ieq $runBat) "shortcut target is Run.bat ($($s.TargetPath))"
        Check ($s.IconLocation -like '*chainproxy.ico*') "shortcut icon ($($s.IconLocation))"
    }
}
Check (Test-Path (Join-Path $Repo '.shortcuts_done')) 'first-run marker written'

Write-Host "== setup.ps1 shortcut (second run must be quick and clean) =="
$sw = [Diagnostics.Stopwatch]::StartNew()
& powershell -NoProfile -ExecutionPolicy Bypass -File $setup shortcut
Check ($LASTEXITCODE -eq 0) ("second run exit code ($LASTEXITCODE), {0:N1}s" -f $sw.Elapsed.TotalSeconds)

if ($py) {
    Write-Host "== chain.py ensure =="
    Push-Location $Repo
    & $py -X utf8 chain.py ensure
    Check ($LASTEXITCODE -eq 0) 'chain.py ensure'
    Pop-Location
}

Write-Host ("INSTALL RESULT: " + $(if ($script:Failures) { "FAIL ($script:Failures)" } else { 'PASS' }))
exit $script:Failures

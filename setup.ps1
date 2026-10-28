# chainproxy bootstrap: make sure Python (with tkinter) and sing-box exist, then start.
param([string]$Mode = "gui")
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
Set-Location $PSScriptRoot
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$PyVersion = '3.12.10'

function Say($m) { Write-Host "[setup] $m" }

function Test-Py([string]$exe, [string[]]$pre) {
    try {
        $out = & $exe @pre -c "import sys, tkinter; assert sys.version_info >= (3, 9); print(sys.executable)" 2>$null
        if ($LASTEXITCODE -eq 0 -and $out) { return ($out | Select-Object -Last 1).Trim() }
    } catch { }
    return $null
}

function Find-Python {
    $cands = @(
        @{ exe = 'py';      pre = @('-3') },
        @{ exe = 'python';  pre = @() },
        @{ exe = 'python3'; pre = @() }
    )
    foreach ($c in $cands) {
        if (Get-Command $c.exe -ErrorAction SilentlyContinue) {
            $p = Test-Py $c.exe $c.pre
            if ($p) { return $p }
        }
    }
    $dirs = @("$env:LOCALAPPDATA\Programs\Python", "$env:ProgramFiles\Python*", "${env:ProgramFiles(x86)}\Python*")
    foreach ($d in $dirs) {
        $files = Get-ChildItem -Path $d -Filter python.exe -Recurse -Depth 2 -ErrorAction SilentlyContinue |
            Sort-Object FullName -Descending
        foreach ($f in $files) {
            $p = Test-Py $f.FullName @()
            if ($p) { return $p }
        }
    }
    return $null
}

function Download([string]$url, [string]$dest) {
    for ($i = 1; $i -le 3; $i++) {
        try { Invoke-WebRequest -Uri $url -OutFile $dest -UseBasicParsing -TimeoutSec 180; return }
        catch { Say "download attempt $i failed: $($_.Exception.Message)"; Start-Sleep -Seconds (2 * $i) }
    }
    throw "could not download $url"
}

function Install-Python {
    $arch = if ($env:PROCESSOR_ARCHITECTURE -eq 'ARM64') { 'arm64' } else { 'amd64' }
    $installer = $null
    if (Test-Path "$PSScriptRoot\offline") {
        $installer = Get-ChildItem "$PSScriptRoot\offline\python-*.exe" -ErrorAction SilentlyContinue |
            Select-Object -Last 1 -ExpandProperty FullName
        if ($installer) { Say "using offline installer $installer" }
    }
    if (-not $installer) {
        $installer = Join-Path $env:TEMP "python-$PyVersion-$arch.exe"
        Say "Python not found - downloading $PyVersion ($arch) from python.org ..."
        try { Download "https://www.python.org/ftp/python/$PyVersion/python-$PyVersion-$arch.exe" $installer }
        catch {
            if (Get-Command winget -ErrorAction SilentlyContinue) {
                Say "falling back to winget ..."
                winget install -e --id Python.Python.3.12 --silent --accept-package-agreements --accept-source-agreements | Out-Host
                return
            }
            throw
        }
    }
    $sig = Get-AuthenticodeSignature $installer
    if ($sig.Status -ne 'Valid' -or $sig.SignerCertificate.Subject -notmatch 'Python Software Foundation') {
        throw "installer signature check failed ($($sig.Status)) - refusing to run it"
    }
    Say "signature OK, installing Python for the current user (no admin needed) ..."
    $p = Start-Process -FilePath $installer -Wait -PassThru -ArgumentList @(
        '/quiet', 'InstallAllUsers=0', 'PrependPath=1', 'Include_tcltk=1', 'Include_launcher=0',
        'Include_test=0', 'Include_doc=0', 'Shortcuts=0')
    if ($p.ExitCode -ne 0 -and $p.ExitCode -ne 3010) { throw "Python installer exited with code $($p.ExitCode)" }
}

function Ensure-Shortcuts([bool]$Force) {
    # Desktop + Start Menu shortcut to Run.bat. Created on the first run; afterwards only repaired
    # (e.g. if the folder was moved). If the user deleted it on purpose it is NOT recreated.
    try {
        $marker = Join-Path $PSScriptRoot '.shortcuts_done'
        $target = Join-Path $PSScriptRoot 'Run.bat'
        $icon   = Join-Path $PSScriptRoot 'chainproxy.ico'
        $places = @(
            (Join-Path ([Environment]::GetFolderPath('Desktop')) 'Chain Proxy.lnk'),
            (Join-Path ([Environment]::GetFolderPath('Programs')) 'Chain Proxy.lnk')
        )
        $first = -not (Test-Path $marker)
        $ws = New-Object -ComObject WScript.Shell
        foreach ($lnk in $places) {
            $exists = Test-Path $lnk
            $stale = $false
            if ($exists) {
                try { $stale = ($ws.CreateShortcut($lnk).TargetPath -ne $target) } catch { $stale = $true }
            }
            if ($Force -or $first -or ($exists -and $stale)) {
                $s = $ws.CreateShortcut($lnk)
                $s.TargetPath       = $target
                $s.WorkingDirectory = $PSScriptRoot
                $s.WindowStyle      = 7          # minimized console: it closes by itself on success
                $s.Description      = 'Chain Proxy'
                if (Test-Path $icon) { $s.IconLocation = $icon }
                $s.Save()
                Say "shortcut: $lnk"
            }
        }
        Set-Content -Path $marker -Value (Get-Date -Format s)
    } catch {
        Say "could not create shortcuts (not critical): $($_.Exception.Message)"
    }
}

try {
    $py = Find-Python
    if (-not $py) {
        Install-Python
        $py = Find-Python
        if (-not $py) { throw "Python was installed but could not be located; reopen Run.bat" }
    }
    Say "Python: $py"

    # sing-box (verified download) - also repaired automatically if broken
    & $py chain.py ensure
    if ($LASTEXITCODE -ne 0) { throw "could not set up sing-box (see message above)" }

    Ensure-Shortcuts ($Mode -eq 'shortcut')
    if ($Mode -eq 'shortcut') { Say "shortcuts (re)created"; exit 0 }

    if ($Mode -eq 'cli') {
        & $py chain.py
    } else {
        $pyw = Join-Path (Split-Path $py) 'pythonw.exe'
        if (-not (Test-Path $pyw)) { $pyw = $py }
        Say "starting the window ..."
        Start-Process -FilePath $pyw -ArgumentList 'gui.py'
    }
} catch {
    Write-Host ""
    Write-Host "[setup] ERROR: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host "[setup] If a download is blocked, put the file into the 'offline' folder:"
    Write-Host "         python-$PyVersion-amd64.exe  and/or  sing-box-*-windows-amd64.zip  (see offline\README.txt)"
    exit 1
}

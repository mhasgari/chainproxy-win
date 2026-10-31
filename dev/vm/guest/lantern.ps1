# Real Lantern end-to-end test inside the VM (needs the internet): the engine from offline\, the
# real GeminiRoute list as exit hop, chain Lantern -> B. Run by `vmtest.py lantern`. ASCII only.
param([string]$Repo)
. "$PSScriptRoot\common.ps1"
$py = Find-Python
Set-Location $Repo
$ie = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Internet Settings'

Write-Host '== engine package =='
Check ((Get-ChildItem "$Repo\offline\chainlantern-*-windows-amd64.zip" -ErrorAction SilentlyContinue).Count -eq 1) 'engine zip is in offline\'
Remove-Item "$Repo\engine" -Recurse -Force -ErrorAction SilentlyContinue

Set-Content "$Repo\config.json" '{"lantern_enabled": true, "strict_urls": ["gemini.google.com"], "watchdog_seconds": 0}' -Encoding ASCII
Set-Content "$Repo\subs.txt" "https://example.com/sub/first`r`nhttps://alizn7.github.io/GeminiRoute/sub/best.txt" -Encoding ASCII
Remove-Item "$Repo\profiles_first.txt", "$Repo\profiles_exit.txt" -ErrorAction SilentlyContinue
$direct = (curl.exe -sS -m 20 https://api.ipify.org)
Write-Host "direct IP: $direct"

Write-Host '== serve with Lantern as first hop =='
$log = "$Repo\runtime\lantern-serve.log"
New-Item -ItemType Directory -Force "$Repo\runtime" | Out-Null
$p = Start-Process $py -ArgumentList '-X', 'utf8', 'chain.py', 'serve' -RedirectStandardOutput $log -RedirectStandardError "$log.err" -WindowStyle Hidden -PassThru
try {
    $st = ''
    $deadline = (Get-Date).AddSeconds(300)
    while ((Get-Date) -lt $deadline) {
        Start-Sleep -Seconds 5
        $st = (& $py -X utf8 chain.py status 2>&1 | Out-String).Trim()
        if ($st.StartsWith('[') -or $p.HasExited) { break }
    }
    Write-Host "status: $st"
    Check ($st.StartsWith('[')) 'the session is serving'
    Check ($st -match 'A0:Lantern') 'the best route starts with Lantern (first hop, priority 1)'
    Check (Test-Path "$Repo\engine\chainlantern.exe") 'engine unpacked from the offline zip (sha256 verified)'
    Check ([bool](Get-Process chainlantern -ErrorAction SilentlyContinue)) 'engine process is running'
    $list = (& $py -X utf8 chain.py list 2>&1 | Out-String)
    Check ($list -match 'Lantern \+ Subscription') 'route list shows the Lantern chains with their source'
    $via = (curl.exe -sS -m 40 -x http://127.0.0.1:42815 https://api.ipify.org)
    Write-Host "IP through the chain: $via"
    Check ($via -match '^\d+\.\d+\.\d+\.\d+$' -and $via -ne $direct) 'traffic leaves through the chain (exit IP differs from the direct one)'
    $code = (curl.exe -sS -m 40 -o NUL -w '%{http_code}' -x http://127.0.0.1:42815 https://gemini.google.com/)
    Check ($code -eq '200') "gemini.google.com answers 200 through the chain ($code)"
    Check ((Get-ItemProperty $ie).ProxyEnable -eq 1) 'Windows proxy is set'
    Write-Host '== stop =='
    & $py -X utf8 chain.py off | Out-Null
    Start-Sleep -Seconds 6
    Check (-not (Get-Process chainlantern -ErrorAction SilentlyContinue)) 'engine stopped with the session'
    Check ((Get-ItemProperty $ie).ProxyEnable -eq 0) 'Windows proxy restored'
} finally {
    & $py -X utf8 chain.py off | Out-Null
    if (-not $p.HasExited) { $p.Kill() }
    Get-Process chainlantern -ErrorAction SilentlyContinue | Stop-Process -Force
    Write-Host '--- serve log tail'
    Get-Content $log -Tail 14 | ForEach-Object { $_.Substring(0, [Math]::Min(150, $_.Length)) }
}
Write-Host ('LANTERN RESULT: ' + $(if ($script:Failures -eq 0) { 'PASS' } else { 'FAIL' }))
exit $script:Failures

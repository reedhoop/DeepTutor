# stop-prod.ps1 - stop DeepTutor production environment
#   (frontend :3800 / backend :8002)
# Usage:
#   powershell -ExecutionPolicy Bypass -File .\scripts\stop-prod.ps1          # stop prod only
#   powershell -ExecutionPolicy Bypass -File .\scripts\stop-prod.ps1 -All     # stop prod + dev (all 4 ports)
param([switch]$All)

$ports = if ($All) { @(8101, 3782, 8002, 3800) } else { @(3800, 8002) }

Write-Host "Stopping DeepTutor ports: $($ports -join ', ')"
foreach ($p in $ports) {
    $line = netstat -ano | Select-String ":$p " | Select-String LISTENING
    if ($line) {
        $pid = ($line.Line -split '\s+')[-1]
        Write-Host "  killing :$p (PID $pid)"
        taskkill /F /PID $pid | Out-Null
        if ($LASTEXITCODE -eq 0) { Write-Host "    stopped" } else { Write-Host "    failed" }
    } else {
        Write-Host "  :$p not listening (already stopped?)"
    }
}
Write-Host "done."

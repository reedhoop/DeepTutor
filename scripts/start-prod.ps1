# start-prod.ps1 - DeepTutor production launcher (Windows / PowerShell)
#
# Run from anywhere:
#   powershell -ExecutionPolicy Bypass -File .\scripts\start-prod.ps1 [-Pull]
#                                             [-K12DataDir <path>] [-K12CacheDir <path>]
#
#   -Pull         : run `git pull` in the repo before building (after pushing from dev)
#   -EnableAuth   : turn on multi-user login (writes data/user/settings/auth.json enabled=true)
#   -SecureCookies: with -EnableAuth, set cookie_secure=true (use ONLY behind HTTPS; for
#                  http://localhost keep this OFF or logins won't persist)
#   -K12DataDir   : path to the K12-KGraph dataset clone (env: K12_KGRAPH_DATA_DIR)
#   -K12CacheDir  : where to store/build the node_vectors.json cache (env: K12_KGRAPH_CACHE_DIR)
#
# NOTE: This script is SELF-CONTAINED. Nothing is hard-coded to the dev environment.
#       K12 paths default to the production repo's own layout and can be overridden.

param(
    [switch]$Pull,
    [switch]$EnableAuth,
    [switch]$SecureCookies,
    [string]$K12DataDir  = "",
    [string]$K12CacheDir = ""
)

$ErrorActionPreference = "Stop"

# Repo root = parent of this script's directory (.../DeepTutor-prod)
$Repo   = (Split-Path -Parent $PSScriptRoot)
$WebDir = Join-Path $Repo "web"
$DataDir = Join-Path $Repo "data"

# ---- Deployment configuration (edit for your machine if needed) ----
$BackendPort  = 8002
$FrontendPort = 3800

# ---- Resolve K12_KGRAPH_DATA_DIR ----
# precedence: -K12DataDir > $env:K12_KGRAPH_DATA_DIR > sibling "K12-KGraph-data"
if (-not $K12DataDir) { $K12DataDir = $env:K12_KGRAPH_DATA_DIR }
if (-not $K12DataDir) {
    # default: a sibling directory next to the repo (e.g. ../K12-KGraph-data)
    $K12DataDir = Join-Path (Split-Path -Parent $Repo) "K12-KGraph-data"
}
# Normalize MSYS/Git-Bash style paths (/d/foo -> D:/foo) so Windows Python can read them
if ($K12DataDir -match '^/([a-zA-Z])/(.*)$') { $K12DataDir = $Matches[1] + ':/' + $Matches[2] }
$K12DataDir = Resolve-Path -Path $K12DataDir -ErrorAction SilentlyContinue
if ($K12DataDir) { $K12DataDir = $K12DataDir.Path }
else             { $K12DataDir = "" }

# ---- Resolve K12_KGRAPH_CACHE_DIR ----
# precedence: -K12CacheDir > $env:K12_KGRAPH_CACHE_DIR > prod-local data dir
if (-not $K12CacheDir) { $K12CacheDir = $env:K12_KGRAPH_CACHE_DIR }
if (-not $K12CacheDir) {
    # prod owns its cache: <repo>/data/knowledge_bases/k12_kg
    $K12CacheDir = Join-Path $DataDir "knowledge_bases\k12_kg"
}
# Normalize MSYS/Git-Bash style paths (/d/foo -> D:/foo) so Windows Python can read them
if ($K12CacheDir -match '^/([a-zA-Z])/(.*)$') { $K12CacheDir = $Matches[1] + ':/' + $Matches[2] }

# ---- Python venv ----
# Prefer a prod-local venv. Fall back to the dev venv ONLY as a convenience on a
# single machine, with a visible warning (no hidden coupling to dev).
$DevVenvPy  = Join-Path (Split-Path -Parent $Repo) "DeepTutor\.venv\Scripts\python.exe"
$ProdVenvPy = Join-Path $Repo ".venv\Scripts\python.exe"
if (Test-Path $ProdVenvPy) {
    $Python = $ProdVenvPy
}
elseif (Test-Path $DevVenvPy) {
    $Python = $DevVenvPy
    Write-Warning "Prod-local .venv not found; falling back to the DEV venv at: $Python"
    Write-Warning "For a clean production setup, create one: cd $Repo ; python -m venv .venv ; .venv\Scripts\pip install -e ."
}
else {
    Write-Error "No Python venv found. Create a prod venv: cd $Repo ; python -m venv .venv ; .venv\Scripts\pip install -e ."
    exit 1
}

# node/npm must be on PATH. If not, uncomment and set the path:
# $env:PATH = "C:\Users\17822\.workbuddy\binaries\node\versions\22.22.2;" + $env:PATH
if (-not (Get-Command node -ErrorAction SilentlyContinue)) {
    Write-Error "'node' not found on PATH. Install Node.js 22+ or set `$env:PATH."
    exit 1
}

# ---- Show resolved configuration ----
Write-Host "=============================================="
Write-Host " DeepTutor PRODUCTION launcher"
Write-Host "=============================================="
Write-Host " Repo root        : $Repo"
Write-Host " Backend port     : $BackendPort"
Write-Host " Frontend port    : $FrontendPort"
Write-Host " Python (venv)    : $Python"
if ($K12DataDir) {
    Write-Host " K12 data dir     : $K12DataDir"
} else {
    Write-Warning " K12 data dir NOT set/found -> K12 features will be disabled (graceful)."
    Write-Warning "   Provide it via -K12DataDir or `$env:K12_KGRAPH_DATA_DIR."
}
Write-Host " K12 cache dir    : $K12CacheDir"

# ---- Optional: enable multi-user auth (writes auth.json) ----
$AuthFile = Join-Path $DataDir "user\settings\auth.json"
if ($EnableAuth) {
    if (-not (Test-Path $AuthFile)) {
        Write-Warning "auth.json not found at $AuthFile; cannot enable auth automatically."
    } else {
        try {
            $auth = Get-Content $AuthFile -Raw | ConvertFrom-Json
            $auth.enabled = $true
            $auth.cookie_secure = [bool]$SecureCookies
            $auth | ConvertTo-Json -Depth 4 | Set-Content -Path $AuthFile -Encoding utf8
            Write-Host "==> Auth ENABLED (cookie_secure=$($auth.cookie_secure)). Visit /login to register the first admin."
        } catch {
            Write-Warning "Failed to update $AuthFile : $_"
        }
    }
}
$AuthEnabledNow = $false
if (Test-Path $AuthFile) {
    try { $AuthEnabledNow = [bool]((Get-Content $AuthFile -Raw | ConvertFrom-Json).enabled) } catch {}
}

Write-Host " Auth enabled     : $AuthEnabledNow"
Write-Host "=============================================="

# ---- Optional: pull latest from origin ----
if ($Pull) {
    Write-Host "==> git pull --ff-only"
    git -C $Repo pull --ff-only
}

# ---- Frontend build (bakes NEXT_PUBLIC_API_BASE = http://localhost:BACKEND_PORT) ----
Write-Host "==> npm install"
Push-Location $WebDir
npm install
Write-Host "==> next build (BACKEND_PORT=$BackendPort)"
$env:BACKEND_PORT            = "$BackendPort"
$env:DEEPTUTOR_API_BASE_URL = "http://localhost:$BackendPort"
npm run build
# For standalone output, copy static assets into the standalone dir (canonical prod layout)
$standaloneDir = Join-Path $WebDir ".next\standalone"
if (Test-Path $standaloneDir) {
    Write-Host "==> copying static assets into standalone dir"
    Copy-Item -Recurse -Force (Join-Path $WebDir "public") (Join-Path $standaloneDir "public") -ErrorAction SilentlyContinue
    Copy-Item -Recurse -Force (Join-Path $WebDir ".next\static") (Join-Path $standaloneDir ".next\static") -ErrorAction SilentlyContinue
}
Pop-Location

# ---- Launch backend (uvicorn) ----
if ($K12DataDir)  { $env:K12_KGRAPH_DATA_DIR  = $K12DataDir }
$env:K12_KGRAPH_CACHE_DIR   = $K12CacheDir
$env:BACKEND_PORT           = "$BackendPort"
$env:DEEPTUTOR_API_BASE_URL = "http://localhost:$BackendPort"

$backendLog = Join-Path $Repo "prod-backend.log"
Write-Host "==> starting backend on :$BackendPort  (log: $backendLog)"
Start-Process -WindowStyle Hidden -FilePath $Python `
    -ArgumentList @("-m","uvicorn","deeptutor.api.main:app","--host","0.0.0.0","--port",$BackendPort,"--log-level","info","--no-access-log","--ws-max-size","43341141") `
    -WorkingDirectory $Repo `
    -RedirectStandardOutput $backendLog -RedirectStandardError $backendLog

# ---- Launch frontend (standalone server.js if available, else next start) ----
$frontendLog = Join-Path $Repo "prod-frontend.log"
Write-Host "==> starting frontend on :$FrontendPort  (log: $frontendLog)"
Push-Location $WebDir
$env:PORT                    = "$FrontendPort"
$env:HOSTNAME               = "0.0.0.0"
$env:BACKEND_PORT           = "$BackendPort"
$env:DEEPTUTOR_API_BASE_URL = "http://localhost:$BackendPort"

$standaloneServer = Join-Path $WebDir ".next\standalone\server.js"
if (Test-Path $standaloneServer) {
    Write-Host "==> using standalone server (.next/standalone/server.js)"
    Start-Process -WindowStyle Hidden -FilePath "node" `
        -ArgumentList @($standaloneServer) `
        -WorkingDirectory $WebDir `
        -RedirectStandardOutput $frontendLog -RedirectStandardError $frontendLog
} else {
    Write-Host "==> using 'next start'"
    Start-Process -WindowStyle Hidden -FilePath "node" `
        -ArgumentList @("node_modules/next/dist/bin/next","start","-p",$FrontendPort) `
        -WorkingDirectory $WebDir `
        -RedirectStandardOutput $frontendLog -RedirectStandardError $frontendLog
}
Pop-Location

Write-Host ""
Write-Host "DeepTutor production is starting..."
Write-Host "  Frontend : http://localhost:$FrontendPort"
Write-Host "  Backend  : http://localhost:$BackendPort"
Write-Host "  Logs     : $backendLog"
Write-Host "            $frontendLog"
Write-Host ""
Write-Host "Tip: after pushing changes from dev, re-run with -Pull to update + rebuild."
Write-Host "     To point at your K12 dataset: -K12DataDir 'D:\path\to\K12-KGraph-data'"

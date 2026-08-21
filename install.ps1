# Clipper-Flash one-command installer (Windows)
# Usage:  powershell -c "irm https://raw.githubusercontent.com/tahacore/Clipper-Flash/main/install.ps1 | iex"
$ErrorActionPreference = "Stop"

function Info($msg) { Write-Host "==> $msg" -ForegroundColor Cyan }
function Ok($msg)   { Write-Host "  OK $msg" -ForegroundColor Green }
function Warn($msg) { Write-Host "  !! $msg" -ForegroundColor Yellow }

Info "Clipper-Flash installer for Windows"

# --- 1. uv (installs/manages Python for us) -----------------------------------
$env:Path += ";$env:USERPROFILE\.local\bin"
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Info "Installing uv..."
    powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex" | Out-Null
    $env:Path += ";$env:USERPROFILE\.local\bin"
}
Ok "uv $(uv --version | ForEach-Object { $_.split(' ')[1] })"

# --- 2. Python 3.12 (managed by uv, no system Python needed) ------------------
Info "Ensuring Python 3.12..."
# NOTE: no stderr redirection here - PS 5.1 turns redirected native stderr
# into a terminating error under $ErrorActionPreference='Stop'.
uv python install 3.12 | Out-Null
Ok "python ready"

# --- 3. FFmpeg ----------------------------------------------------------------
if (-not (Get-Command ffmpeg -ErrorAction SilentlyContinue)) {
    Info "Installing FFmpeg..."
    $wingetOk = $false
    if (Get-Command winget -ErrorAction SilentlyContinue) {
        try {
            winget install --id Gyan.FFmpeg -e --accept-source-agreements --accept-package-agreements | Out-Null
            $wingetOk = $true
        } catch { Warn "winget install failed, falling back to direct download" }
    }
    if (-not $wingetOk) {
        # Static build into ~/.clipper-flash\ffmpeg + user PATH (no admin needed)
        $dest = "$env:USERPROFILE\.clipper-flash\ffmpeg"
        New-Item -ItemType Directory -Force -Path $dest | Out-Null
        $zip = "$env:TEMP\cf-ffmpeg.zip"
        Info "Downloading FFmpeg (~80MB, one time)..."
        Invoke-WebRequest -Uri "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip" -OutFile $zip
        Expand-Archive -Path $zip -DestinationPath $dest -Force
        $bin = (Get-ChildItem "$dest" -Directory | Where-Object { Test-Path "$($_.FullName)\bin\ffmpeg.exe" } |
                Select-Object -First 1).FullName + "\bin"
        $userPath = [Environment]::GetEnvironmentVariable("Path", "User")
        if ($userPath -notlike "*$bin*") {
            [Environment]::SetEnvironmentVariable("Path", "$userPath;$bin", "User")
        }
        $env:Path += ";$bin"
    }
    # refresh session PATH so ffmpeg is visible now
    foreach ($p in @(
        "$env:LOCALAPPDATA\Microsoft\WinGet\Links",
        "$env:USERPROFILE\.clipper-flash\ffmpeg"
    )) { if (Test-Path $p) { $env:Path += ";$p" } }
    $ffdir = Get-ChildItem "$env:LOCALAPPDATA\Microsoft\WinGet\Packages" -Filter "Gyan.FFmpeg*" -Directory -ErrorAction SilentlyContinue |
             Get-ChildItem -Directory -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($ffdir) { $env:Path += ";$($ffdir.FullName)\bin" }
}
if (Get-Command ffmpeg -ErrorAction SilentlyContinue) { Ok "ffmpeg available" }
else { Warn "ffmpeg still missing - 'cf doctor' will tell you; may need terminal restart" }

# --- 4. Clipper-Flash ----------------------------------------------------------
Info "Installing Clipper-Flash (this can take a minute)..."
uv tool install --force "clipper-flash[vision,web] @ git+https://github.com/tahacore/Clipper-Flash" | Out-Null
$userPath = [Environment]::GetEnvironmentVariable("Path", "User")
$toolsBin = "$env:USERPROFILE\.local\bin"
if ($userPath -notlike "*$toolsBin*") {
    [Environment]::SetEnvironmentVariable("Path", "$userPath;$toolsBin", "User")
}
$env:Path += ";$toolsBin"
Ok "clipper-flash installed"

# --- 5. Agent skill -------------------------------------------------------------
Info "Installing skill for Claude Code / Codex..."
cf install-skill

# --- 6. Verify ------------------------------------------------------------------
Info "Running doctor..."
cf doctor

Write-Host ""
Write-Host "Done! Open Claude Code or Codex and say:" -ForegroundColor Magenta
Write-Host '   "Check my channel and clip anything new."' -ForegroundColor White
Write-Host "(If ffmpeg was flagged, restart your terminal first.)" -ForegroundColor DarkGray

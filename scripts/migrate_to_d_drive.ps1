# ============================================================
# ArmillaryLab — Migrate project off OneDrive to D:\Projects\Python
# ============================================================
# Run from PowerShell:
#   .\scripts\migrate_to_d_drive.ps1
#
# What this does:
#   1. Copies the project (minus venv, __pycache__, corrupt/backup DB files)
#   2. Restores the known-good database
#   3. Creates a fresh venv on D: and installs dependencies
#   4. Prints next steps (including workspace fixup)
# ============================================================

$ErrorActionPreference = "Stop"

# --- Configuration ---
$SRC       = "C:\Users\SalehRam\OneDrive\Desktop\Python\astroplanner"
$DEST      = "D:\Projects\Python\astroplanner"
$GOOD_DB   = "armillarylab copy.db"

# --- Pre-flight checks ---
Write-Host ("=" * 60)
Write-Host "ArmillaryLab Migration: OneDrive -> D:\Projects\Python"
Write-Host ("=" * 60)
Write-Host ""

if (Test-Path $DEST) {
    Write-Host "Destination already exists: $DEST" -ForegroundColor Yellow
    $overwrite = Read-Host "Overwrite? (y/N)"
    if ($overwrite -ne "y") { exit 1 }
    Remove-Item $DEST -Recurse -Force
}

# --- Step 1: Copy project (excluding junk) ---
Write-Host ""
Write-Host "[1/4] Copying project files..." -ForegroundColor Cyan

New-Item -ItemType Directory -Path $DEST -Force | Out-Null

$excludeDirs = @("venv", "__pycache__", ".pytest_cache", "node_modules")
$excludeFiles = @(
    "*.db.corrupt_*", "*.db.backup_*",
    "nonexistent_test_db.db", "old-astroplanner.db",
    "armillarylab copy.db"
)

$robocopyArgs = @($SRC, $DEST, "/E", "/NFL", "/NDL", "/NJH", "/NP", "/XD") +
    $excludeDirs + @("/XF") + $excludeFiles

& robocopy @robocopyArgs | Out-Null
if ($LASTEXITCODE -gt 7) {
    Write-Host "ERROR: robocopy failed with exit code $LASTEXITCODE" -ForegroundColor Red
    exit 1
}

Write-Host "  Project files copied (excluding venv, caches, corrupt/backup DB files)." -ForegroundColor Green

# --- Step 2: Restore known-good database ---
Write-Host ""
Write-Host "[2/4] Restoring database from known-good copy..." -ForegroundColor Cyan

$goodDbSrc = Join-Path $SRC $GOOD_DB
$destDb    = Join-Path $DEST "armillarylab.db"

if (Test-Path $goodDbSrc) {
    Copy-Item $goodDbSrc $destDb -Force
    Write-Host "  Restored from '$GOOD_DB'." -ForegroundColor Green
} else {
    Write-Host "  WARNING: '$GOOD_DB' not found. armillarylab.db copied as-is." -ForegroundColor Yellow
}

foreach ($ext in @("-wal", "-shm", "-journal")) {
    $sidecar = "${destDb}${ext}"
    if (Test-Path $sidecar) { Remove-Item $sidecar -Force }
}

# --- Step 3: Create fresh venv ---
Write-Host ""
Write-Host "[3/4] Creating fresh virtual environment on D:..." -ForegroundColor Cyan

$reqFile = Join-Path $DEST "requirements.txt"
if (Test-Path $reqFile) {
    Push-Location $DEST
    python -m venv venv
    & "$DEST\venv\Scripts\pip.exe" install -r requirements.txt --quiet 2>&1 | Out-Null
    Pop-Location
    Write-Host "  venv created and dependencies installed." -ForegroundColor Green
} else {
    Write-Host "  WARNING: requirements.txt not found. Create venv manually." -ForegroundColor Yellow
}

# --- Step 4: Verify DB ---
Write-Host ""
Write-Host "[4/4] Verifying database..." -ForegroundColor Cyan

$checkScript = @"
import sqlite3, sys
conn = sqlite3.connect(sys.argv[1], timeout=5)
cur = conn.cursor()
cur.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table'")
tables = cur.fetchone()[0]
targets = sessions = cal = -1
try:
    cur.execute("SELECT COUNT(*) FROM targets"); targets = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM imaging_sessions"); sessions = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM calibration_captures"); cal = cur.fetchone()[0]
except: pass
conn.close()
print(f"  {tables} tables, {targets} targets, {sessions} sessions, {cal} calibration logs")
"@

python -c $checkScript "$destDb"

# --- Summary ---
Write-Host ""
Write-Host ("=" * 60)
Write-Host "FILE MIGRATION COMPLETE" -ForegroundColor Green
Write-Host ("=" * 60)
Write-Host ""
Write-Host "New project location: $DEST"
Write-Host ""
Write-Host "NEXT STEPS:" -ForegroundColor Cyan
Write-Host "  1. Open the new folder in Cursor:"
Write-Host "       File > Open Folder > D:\Projects\Python\astroplanner" -ForegroundColor White
Write-Host ""
Write-Host "  2. Once Cursor opens it, run the workspace fixup script to"
Write-Host "     transfer your chat history. Open a terminal in the NEW project and run:"
Write-Host "       python scripts\fix_cursor_workspace.py" -ForegroundColor White
Write-Host ""
Write-Host "  3. Activate venv and start Flask:"
Write-Host "       .\venv\Scripts\Activate.ps1"
Write-Host "       flask migrate-db"
Write-Host "       flask run" -ForegroundColor White
Write-Host ""
Write-Host "  4. Verify at http://127.0.0.1:8080"
Write-Host ""
Write-Host "Keep the OneDrive copy until you're sure everything works."
Write-Host ""

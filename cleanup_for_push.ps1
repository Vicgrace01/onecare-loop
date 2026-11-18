# OneCare Loop — Pre-Push Cleanup
# Removes generated dumps, one-off patch scripts, and the local DB.
# Run from the project root BEFORE git init / git add.

Write-Host "`n=== OneCare Loop — Pre-Push Cleanup ===" -ForegroundColor Cyan

$root = (Get-Location).Path
Write-Host "Root: $root`n"

$patterns = @(
    "fix_*.py",
    "apply_fixes.py",
    "god_tier_*.py",
    "*_patch.py",
    "*_polish.py",
    "final_polish.py",
    "snapshot.py",
    "verify_all.py",
    "codebase.txt",
    "project_snapshot.txt",
    "templates_dump.txt",
    "*_copy.txt",
    "*.db",
    "*.db-shm",
    "*.db-wal"
)

$deleted = 0
$bytes_freed = 0

Write-Host "Removing junk files:" -ForegroundColor Yellow
foreach ($pattern in $patterns) {
    Get-ChildItem -Path $root -Filter $pattern -File -ErrorAction SilentlyContinue | ForEach-Object {
        $size = $_.Length
        $name = $_.Name
        Remove-Item $_.FullName -Force -ErrorAction SilentlyContinue
        Write-Host ("  - {0}  ({1} KB)" -f $name, [math]::Round($size/1KB)) -ForegroundColor DarkGray
        $deleted++
        $bytes_freed += $size
    }
}

Write-Host "`nRemoving cache directories:" -ForegroundColor Yellow
foreach ($dirName in @(".pytest_cache", "__pycache__")) {
    Get-ChildItem -Path $root -Filter $dirName -Directory -Recurse -ErrorAction SilentlyContinue | ForEach-Object {
        Remove-Item $_.FullName -Recurse -Force -ErrorAction SilentlyContinue
        Write-Host ("  - {0}" -f $_.FullName.Replace($root, "")) -ForegroundColor DarkGray
        $deleted++
    }
}

Write-Host "`n=== Summary ===" -ForegroundColor Cyan
Write-Host "Files/dirs removed: $deleted"
Write-Host "Space freed: $([math]::Round($bytes_freed/1MB, 2)) MB"
Write-Host ""

Write-Host "Next steps:" -ForegroundColor Yellow
Write-Host "  1. Delete the old GitHub repo in your browser"
Write-Host "  2. Create a new empty repo (no README, no .gitignore, no license)"
Write-Host "  3. In this terminal, run:"
Write-Host ""
Write-Host "     Remove-Item .git -Recurse -Force"
Write-Host "     git init"
Write-Host "     git add ."
Write-Host "     git commit -m 'OneCare Loop — Future Health Digital Innovation Challenge submission'"
Write-Host "     git branch -M main"
Write-Host "     git remote add origin https://github.com/YOUR_USERNAME/YOUR_NEW_REPO.git"
Write-Host "     git push -u origin main"
Write-Host ""
Write-Host "  4. Verify the push landed with only intended files:"
Write-Host "     git ls-files | Measure-Object -Line"
Write-Host ""
Write-Host "  5. Regenerate the DB so your local demo still works:"
Write-Host "     python -c 'import app; print(\"OK\")'"
Write-Host ""
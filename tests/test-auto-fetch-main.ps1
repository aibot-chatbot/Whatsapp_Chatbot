# Self-check for auto-fetch-main.ps1's "merge only when safe" guard.
# Run:  .\tests\test-auto-fetch-main.ps1
#
# Builds a throwaway origin + checkout, then asserts the three branches:
#   A. clean tree, conflict-free  -> merges
#   B. tracked file edited        -> skips, working tree untouched
#   C. conflicting change         -> skips, working tree untouched
# LOCALAPPDATA is redirected so the real last-seen.txt / auto-update.log are
# never touched.
#
# NOTE: every git invocation uses git.exe. A bare `git` would resolve to the
# RunGit function below (PowerShell prefers functions over external commands,
# case-insensitively) and recurse until the call depth blows.

$ErrorActionPreference = 'Stop'
$root = Join-Path $env:TEMP 'autofetch-selfcheck'
$sourceScript = Join-Path $PSScriptRoot '..\scripts\auto-fetch-main.ps1'

if (Test-Path $root) { Remove-Item -Recurse -Force $root }
New-Item -ItemType Directory -Path $root -Force | Out-Null

$failures = @()
function Assert($condition, $message) {
    if ($condition) { Write-Host "  PASS: $message" }
    else { Write-Host "  FAIL: $message" -ForegroundColor Red; $script:failures += $message }
}

function RunGit { param([string]$Dir, [string[]]$Arguments)
    & git.exe -C $Dir @Arguments 2>&1 | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "git $($Arguments -join ' ') failed in $Dir" }
}

# --- build origin + two checkouts -------------------------------------------
$originPath = Join-Path $root 'origin.git'
$work = Join-Path $root 'work'
$team = Join-Path $root 'team'

& git.exe init --bare -q $originPath
& git.exe clone -q $originPath $work 2>&1 | Out-Null
RunGit $work @('config','user.email','t@t'); RunGit $work @('config','user.name','T')
Set-Content (Join-Path $work 'base.txt') "base"
Set-Content (Join-Path $work 'shared.txt') "line1"
RunGit $work @('add','-A'); RunGit $work @('commit','-qm','base')
RunGit $work @('branch','-M','main'); RunGit $work @('push','-qu','origin','main')

# local-only personal branch with its own commit, mirroring 'vince'
RunGit $work @('checkout','-qb','vince')
Set-Content (Join-Path $work 'mine.txt') "mine"
RunGit $work @('add','-A'); RunGit $work @('commit','-qm','my work')

# -b main is required: `git init --bare` left origin's HEAD on refs/heads/master,
# so a plain clone would check out an unrelated 'master' and fail to push main.
& git.exe clone -q -b main $originPath $team 2>&1 | Out-Null
RunGit $team @('config','user.email','m@m'); RunGit $team @('config','user.name','M')

New-Item -ItemType Directory -Path (Join-Path $work 'scripts') -Force | Out-Null
Copy-Item $sourceScript (Join-Path $work 'scripts\auto-fetch-main.ps1') -Force

function Invoke-AutoFetch {
    $isolated = Join-Path $root 'appdata'
    New-Item -ItemType Directory -Path $isolated -Force | Out-Null
    $saved = $env:LOCALAPPDATA
    $env:LOCALAPPDATA = $isolated
    try { & (Join-Path $work 'scripts\auto-fetch-main.ps1') -NoToast 2>&1 | Out-Null }
    finally { $env:LOCALAPPDATA = $saved }
}

# --- Case A: clean tree, conflict-free -> should merge -----------------------
# The copied script above is untracked, so this also pins the rule that
# untracked files must NOT count as "dirty" and block the merge.
Write-Host "`nCase A: clean tree, conflict-free"
Set-Content (Join-Path $team 'teammate-a.txt') "from teammate"
RunGit $team @('add','-A'); RunGit $team @('commit','-qm','teammate A'); RunGit $team @('push','-q','origin','main')
Invoke-AutoFetch
Assert (Test-Path (Join-Path $work 'teammate-a.txt')) "teammate's file was auto-merged into vince"
Assert (Test-Path (Join-Path $work 'mine.txt'))        "my own commit survived the merge"

# --- Case B: tracked file edited -> should skip -------------------------------
Write-Host "`nCase B: uncommitted local edit"
Set-Content (Join-Path $work 'base.txt') "EDITED IN PROGRESS"
Set-Content (Join-Path $team 'teammate-b.txt') "second push"
RunGit $team @('add','-A'); RunGit $team @('commit','-qm','teammate B'); RunGit $team @('push','-q','origin','main')
Invoke-AutoFetch
Assert (-not (Test-Path (Join-Path $work 'teammate-b.txt'))) "auto-merge skipped while tree was dirty"
Assert ((Get-Content (Join-Path $work 'base.txt') -Raw).Trim() -eq 'EDITED IN PROGRESS') "in-progress edit was NOT clobbered"

# clean up the edit so Case C starts from a clean tree
RunGit $work @('checkout','--','base.txt')

# --- Case C: conflicting change -> should skip -------------------------------
Write-Host "`nCase C: conflicting change"
Set-Content (Join-Path $work 'shared.txt') "vince version"
RunGit $work @('add','-A'); RunGit $work @('commit','-qm','my edit to shared')
Set-Content (Join-Path $team 'shared.txt') "teammate version"
RunGit $team @('add','-A'); RunGit $team @('commit','-qm','teammate edit to shared'); RunGit $team @('push','-q','origin','main')
Invoke-AutoFetch
Assert ((Get-Content (Join-Path $work 'shared.txt') -Raw).Trim() -eq 'vince version') "conflicting merge skipped, my version intact"
$status = (& git.exe -C $work status --porcelain) -join ''
Assert ([string]::IsNullOrWhiteSpace($status)) "no conflict markers left in the working tree"

Write-Host ""
if ($failures.Count -eq 0) { Write-Host "ALL CHECKS PASSED" -ForegroundColor Green; exit 0 }
else { Write-Host "$($failures.Count) CHECK(S) FAILED" -ForegroundColor Red; exit 1 }

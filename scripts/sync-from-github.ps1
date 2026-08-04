[CmdletBinding()]
param(
    [string]$Remote = "origin",
    # Integration branch teammates push into. This checkout's own branch
    # (e.g. 'vince') is local-only, so 'origin/<current-branch>' does not exist
    # and must never be used as the update source.
    [string]$Branch = "main",
    [switch]$NoStash
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$safeRepoRoot = $repoRoot.Replace("\", "/")

function Invoke-Git {
    param([Parameter(Mandatory)][string[]]$Arguments, [switch]$AllowFailure)

    $previousErrorActionPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        $output = & git -c "safe.directory=$safeRepoRoot" @Arguments 2>&1
        $exitCode = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $previousErrorActionPreference
    }

    $text = ($output -join [Environment]::NewLine).Trim()
    if ($exitCode -ne 0 -and -not $AllowFailure) {
        throw "git $($Arguments -join ' ') failed:`n$text"
    }
    return [pscustomobject]@{ ExitCode = $exitCode; Text = $text }
}

if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    throw "Git is not installed or is not available on PATH."
}

Push-Location $repoRoot
try {
    $currentBranch = (Invoke-Git -Arguments @("branch", "--show-current")).Text
    if ([string]::IsNullOrWhiteSpace($currentBranch)) {
        throw "The repository is in detached HEAD state. Check out a branch before updating."
    }

    # start-with-update.ps1 passes -Branch "" by default; fall back to the
    # integration branch rather than the (local-only) current branch.
    if ([string]::IsNullOrWhiteSpace($Branch)) {
        $Branch = "main"
    }

    if ($Remote -notmatch '^[A-Za-z0-9][A-Za-z0-9._/-]*$') {
        throw "Remote name '$Remote' contains unsupported characters."
    }
    Invoke-Git -Arguments @("check-ref-format", "--branch", $Branch) | Out-Null

    Write-Host "Checking $Remote/$Branch for teammate updates..."
    $fetchRefspec = "+refs/heads/${Branch}:refs/remotes/${Remote}/${Branch}"
    $fetch = Invoke-Git -Arguments @("fetch", "--prune", "--", $Remote, $fetchRefspec)
    if ($fetch.Text) { Write-Host $fetch.Text }

    $remoteRef = "refs/remotes/$Remote/$Branch"
    $verify = Invoke-Git -Arguments @("show-ref", "--verify", "--quiet", $remoteRef) -AllowFailure
    if ($verify.ExitCode -ne 0) {
        throw "Remote branch '$Remote/$Branch' does not exist."
    }

    # Nothing new upstream: the remote tip is already an ancestor of HEAD.
    $contains = Invoke-Git -Arguments @("merge-base", "--is-ancestor", $remoteRef, "HEAD") -AllowFailure
    if ($contains.ExitCode -eq 0) {
        Write-Host "Already up to date with $Remote/$Branch."
        return
    }

    $behind = (Invoke-Git -Arguments @("rev-list", "--count", "HEAD..$remoteRef")).Text
    Write-Host "Receiving $behind new commit(s) from $Remote/$Branch into '$currentBranch'..."

    # Stash first so an in-progress edit never blocks or gets clobbered by the
    # merge. -u includes untracked files; they are restored by the pop below.
    $stashed = $false
    $dirty = (Invoke-Git -Arguments @("status", "--porcelain")).Text
    if (-not [string]::IsNullOrWhiteSpace($dirty)) {
        if ($NoStash) {
            throw "Local changes are present and -NoStash was set. Commit or stash them first.`n$dirty"
        }
        Invoke-Git -Arguments @("stash", "push", "-u", "-m", "auto-sync before $Remote/$Branch") | Out-Null
        $stashed = $true
        Write-Host "Local changes stashed."
    }

    $merge = Invoke-Git -Arguments @("merge", "--no-edit", $remoteRef) -AllowFailure
    if ($merge.ExitCode -ne 0) {
        Invoke-Git -Arguments @("merge", "--abort") -AllowFailure | Out-Null
        if ($stashed) {
            Invoke-Git -Arguments @("stash", "pop") -AllowFailure | Out-Null
        }
        throw "Merge from $Remote/$Branch conflicts with '$currentBranch'. The working tree was left untouched; resolve manually with 'git merge $Remote/$Branch'.`n$($merge.Text)"
    }
    Write-Host $merge.Text

    if ($stashed) {
        $pop = Invoke-Git -Arguments @("stash", "pop") -AllowFailure
        if ($pop.ExitCode -ne 0) {
            Write-Warning "Update applied, but your stashed changes conflict with it. They are preserved - run 'git stash pop' and resolve.`n$($pop.Text)"
        }
        else {
            Write-Host "Local changes restored."
        }
    }

    Write-Host "GitHub update completed."
}
finally {
    Pop-Location
}

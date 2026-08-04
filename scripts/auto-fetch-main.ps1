<#
.SYNOPSIS
    Keeps this checkout aware of teammate pushes without touching the working tree.

.DESCRIPTION
    Fetches the remote, fast-forwards the local integration branch (default: main)
    through a ref-only update that checks nothing out, and raises a Windows toast
    when the current branch falls behind. Working-tree files and uncommitted edits
    are never modified, so this is safe to run on a timer while you are working.

    Intended to run unattended from Task Scheduler via auto-fetch-main.vbs.
#>
[CmdletBinding()]
param(
    [string]$Remote = 'origin',
    [string]$TrackBranch = 'main',
    [switch]$NoToast,
    [switch]$NoAutoMerge
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$safeRepoRoot = $repoRoot.Replace('\', '/')
$stateDir = Join-Path $env:LOCALAPPDATA 'WhatsappChatbotSync'
$logPath = Join-Path $stateDir 'auto-update.log'
$statePath = Join-Path $stateDir 'last-seen.txt'

# Rotate at 512 KB so an unattended timer cannot grow the log without bound.
$maxLogBytes = 512KB

if (-not (Test-Path -LiteralPath $stateDir)) {
    New-Item -ItemType Directory -Path $stateDir -Force | Out-Null
}

function Write-Log {
    param([string]$Message, [string]$Level = 'INFO')

    $line = '{0} [{1}] {2}' -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $Level, $Message
    Write-Host $line

    if ((Test-Path -LiteralPath $logPath) -and ((Get-Item -LiteralPath $logPath).Length -gt $maxLogBytes)) {
        Move-Item -LiteralPath $logPath -Destination "$logPath.1" -Force
    }
    Add-Content -LiteralPath $logPath -Value $line -Encoding UTF8
}

function Resolve-GitPath {
    $command = Get-Command git -ErrorAction SilentlyContinue
    if ($command) { return $command.Source }

    $candidates = @(
        (Join-Path $env:ProgramFiles 'Git\cmd\git.exe'),
        (Join-Path ${env:ProgramFiles(x86)} 'Git\cmd\git.exe'),
        (Join-Path $env:LOCALAPPDATA 'Programs\Git\cmd\git.exe')
    )
    foreach ($candidate in $candidates) {
        if (Test-Path -LiteralPath $candidate) { return $candidate }
    }
    throw 'Git was not found on PATH or in the standard installation folders.'
}

$gitExe = Resolve-GitPath

function Invoke-Git {
    param([Parameter(Mandatory)][string[]]$Arguments, [switch]$AllowFailure)

    $previous = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        $output = & $gitExe -c "safe.directory=$safeRepoRoot" @Arguments 2>&1
        $exitCode = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $previous
    }

    $text = ($output -join [Environment]::NewLine).Trim()
    if ($exitCode -ne 0 -and -not $AllowFailure) {
        throw "git $($Arguments -join ' ') failed:`n$text"
    }
    return [pscustomobject]@{ ExitCode = $exitCode; Text = $text }
}

function Show-Toast {
    param([string]$Title, [string]$Message)

    if ($NoToast) { return }
    try {
        [void][Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime]
        [void][Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom, ContentType = WindowsRuntime]

        $template = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent(
            [Windows.UI.Notifications.ToastTemplateType]::ToastText02)
        $nodes = $template.GetElementsByTagName('text')
        [void]$nodes.Item(0).AppendChild($template.CreateTextNode($Title))
        [void]$nodes.Item(1).AppendChild($template.CreateTextNode($Message))

        $appId = '{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\WindowsPowerShell\v1.0\powershell.exe'
        $toast = New-Object Windows.UI.Notifications.ToastNotification $template
        [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($appId).Show($toast)
    }
    catch {
        # A missing toast must never fail the sync; the log is the durable record.
        Write-Log "Toast notification unavailable: $($_.Exception.Message)" 'WARN'
    }
}

Push-Location $repoRoot
try {
    $fetch = Invoke-Git -Arguments @('fetch', '--prune', '--', $Remote) -AllowFailure
    if ($fetch.ExitCode -ne 0) {
        Write-Log "Fetch from '$Remote' failed: $($fetch.Text)" 'ERROR'
        exit 1
    }
    if ($fetch.Text) { Write-Log "Fetched: $($fetch.Text)" }

    $remoteRef = "refs/remotes/$Remote/$TrackBranch"
    $verify = Invoke-Git -Arguments @('show-ref', '--verify', '--quiet', $remoteRef) -AllowFailure
    if ($verify.ExitCode -ne 0) {
        Write-Log "Remote branch '$Remote/$TrackBranch' does not exist." 'ERROR'
        exit 1
    }

    $currentBranch = (Invoke-Git -Arguments @('branch', '--show-current')).Text

    # Update the local integration branch. When it is not checked out, a ref-only
    # fetch fast-forwards it without touching a single file in the working tree.
    if ($currentBranch -eq $TrackBranch) {
        $ff = Invoke-Git -Arguments @('merge', '--ff-only', $remoteRef) -AllowFailure
        if ($ff.ExitCode -ne 0) {
            Write-Log "Could not fast-forward checked-out '$TrackBranch': $($ff.Text)" 'WARN'
        }
    }
    else {
        $refspec = "refs/heads/${TrackBranch}:refs/heads/${TrackBranch}"
        $update = Invoke-Git -Arguments @('fetch', '--', $Remote, $refspec) -AllowFailure
        if ($update.ExitCode -ne 0) {
            Write-Log "Local '$TrackBranch' diverged from $Remote/$TrackBranch and was left untouched." 'WARN'
        }
        elseif ($update.Text) {
            Write-Log "Local '$TrackBranch' updated: $($update.Text)"
        }
    }

    $remoteCommit = (Invoke-Git -Arguments @('rev-parse', $remoteRef)).Text
    $shortCommit = (Invoke-Git -Arguments @('rev-parse', '--short', $remoteRef)).Text

    if ([string]::IsNullOrWhiteSpace($currentBranch)) {
        Write-Log "Detached HEAD; reporting only. $Remote/$TrackBranch is at $shortCommit." 'WARN'
        exit 0
    }

    $behind = [int](Invoke-Git -Arguments @('rev-list', '--count', "HEAD..$remoteRef")).Text
    $ahead = [int](Invoke-Git -Arguments @('rev-list', '--count', "$remoteRef..HEAD")).Text

    $lastSeen = ''
    if (Test-Path -LiteralPath $statePath) {
        $raw = Get-Content -LiteralPath $statePath -Raw -ErrorAction SilentlyContinue
        if ($raw) { $lastSeen = $raw.Trim() }
    }

    if ($behind -eq 0) {
        Write-Log "Up to date with $Remote/$TrackBranch ($shortCommit); '$currentBranch' is $ahead ahead."
    }
    else {
        Write-Log "'$currentBranch' is $behind behind and $ahead ahead of $Remote/$TrackBranch ($shortCommit)."

        # Only touch the working tree when it is provably safe: a clean tree and
        # a merge that applies without conflict. Anything else falls through to
        # the toast, so an unattended timer can never interrupt work in progress.
        $merged = $false
        if (-not $NoAutoMerge) {
            # Tracked changes only. This repo always carries untracked scratch
            # files (error_log.txt, .understand-anything churn), and counting
            # those would disable auto-merge permanently. A merge cannot clobber
            # an untracked file anyway: git refuses, and the abort below rolls
            # the attempt back.
            $dirty = (Invoke-Git -Arguments @('status', '--porcelain', '--untracked-files=no')).Text
            if (-not [string]::IsNullOrWhiteSpace($dirty)) {
                Write-Log 'Working tree has local changes; skipping auto-merge.'
            }
            else {
                # merge-tree resolves the merge in memory and writes nothing;
                # a non-zero exit means it would conflict.
                $dry = Invoke-Git -Arguments @('merge-tree', '--write-tree', 'HEAD', $remoteRef) -AllowFailure
                if ($dry.ExitCode -ne 0) {
                    Write-Log "Merging $Remote/$TrackBranch would conflict; skipping auto-merge." 'WARN'
                }
                else {
                    $merge = Invoke-Git -Arguments @('merge', '--no-edit', $remoteRef) -AllowFailure
                    if ($merge.ExitCode -ne 0) {
                        Invoke-Git -Arguments @('merge', '--abort') -AllowFailure | Out-Null
                        Write-Log "Auto-merge failed and was rolled back: $($merge.Text)" 'WARN'
                    }
                    else {
                        $merged = $true
                        Write-Log "Auto-merged $behind commit(s) from $Remote/$TrackBranch into '$currentBranch'."
                    }
                }
            }
        }

        # Notify once per new remote commit rather than on every timed run.
        if ($remoteCommit -ne $lastSeen) {
            $plural = 'commits'
            if ($behind -eq 1) { $plural = 'commit' }
            if ($merged) {
                Show-Toast -Title "Whatsapp_Chatbot: $behind new $plural merged" `
                    -Message "$Remote/$TrackBranch moved to $shortCommit and was merged into '$currentBranch'. Restart the app to load it."
            }
            else {
                Show-Toast -Title "Whatsapp_Chatbot: $behind new $plural" `
                    -Message "$Remote/$TrackBranch moved to $shortCommit. Your branch '$currentBranch' is behind - merge when ready."
            }
        }
    }

    Set-Content -LiteralPath $statePath -Value $remoteCommit -Encoding ASCII
}
catch {
    Write-Log $_.Exception.Message 'ERROR'
    exit 1
}
finally {
    Pop-Location
}

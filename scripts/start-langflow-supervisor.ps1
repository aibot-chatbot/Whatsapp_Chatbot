param(
    [string]$Executable = "$env:LOCALAPPDATA\hermes\hermes-agent\venv\Scripts\langflow.exe",
    [ValidateRange(1024, 65535)][int]$Port = 7860,
    [ValidateRange(1, 300)][int]$RetrySeconds = 30,
    [string]$LogPath = "$env:LOCALAPPDATA\langflow\supervisor.log"
)

$ErrorActionPreference = 'Stop'
if (-not (Test-Path -LiteralPath $Executable -PathType Leaf)) {
    throw 'Langflow executable is missing.'
}
$LogPath = [IO.Path]::GetFullPath($LogPath)
[IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($LogPath)) | Out-Null
$userSid = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value
$mutex = [Threading.Mutex]::new($false, "Local\LangflowSupervisor-$userSid-$Port")
$locked = $false

function Write-State([string]$Message) {
    if ((Test-Path -LiteralPath $LogPath) -and (Get-Item -LiteralPath $LogPath).Length -gt 1MB) {
        Move-Item -LiteralPath $LogPath -Destination "$LogPath.1" -Force
    }
    Add-Content -LiteralPath $LogPath -Encoding UTF8 -Value "$(Get-Date -Format o) $Message"
}

try {
    try { $locked = $mutex.WaitOne(0) }
    catch [Threading.AbandonedMutexException] { $locked = $true }
    if (-not $locked) { exit 0 }
    Write-State 'Supervisor started.'
    $waitingForPort = $false
    while ($true) {
        # Langflow itself can choose the next port even with --port supplied.
        # Observe an existing listener instead of launching a second instance.
        $occupied = [Net.NetworkInformation.IPGlobalProperties]::GetIPGlobalProperties().GetActiveTcpListeners() |
            Where-Object Port -EQ $Port
        if ($occupied) {
            if (-not $waitingForPort) { Write-State "Port $Port occupied; waiting without starting another server." }
            $waitingForPort = $true
            Start-Sleep -Seconds $RetrySeconds
            continue
        }
        $waitingForPort = $false
        try {
            Write-State "Starting Langflow on 127.0.0.1:$Port."
            $process = Start-Process -FilePath $Executable -ArgumentList 'run', '--host', '127.0.0.1', '--port', $Port, '--no-open-browser' -WindowStyle Hidden -PassThru
            $process.WaitForExit()
            Write-State "Langflow exited with code $($process.ExitCode); retrying in $RetrySeconds seconds."
        } catch {
            Write-State "Launch failed; retrying in $RetrySeconds seconds."
        }
        Start-Sleep -Seconds $RetrySeconds
    }
} finally {
    if ($locked) { $mutex.ReleaseMutex() }
    $mutex.Dispose()
}

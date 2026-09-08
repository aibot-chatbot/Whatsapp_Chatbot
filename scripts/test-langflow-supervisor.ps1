$ErrorActionPreference = 'Stop'
$testRoot = Join-Path ([IO.Path]::GetTempPath()) ("langflow-supervisor-test-" + [guid]::NewGuid().ToString('N'))
[IO.Directory]::CreateDirectory($testRoot) | Out-Null
$fakeExecutable = Join-Path $testRoot 'fake-langflow.exe'
$supervisor = Join-Path $PSScriptRoot 'start-langflow-supervisor.ps1'
$logPath = Join-Path $testRoot 'supervisor.log'
$portReservation = [Net.Sockets.TcpListener]::new([Net.IPAddress]::Loopback, 0)
$portReservation.Start()
$port = $portReservation.LocalEndpoint.Port
$children = @()
$userSid = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value
$globalMutex = [Threading.Mutex]::new($false, "Global\LangflowSupervisor-$userSid-$port")
$globalLocked = $globalMutex.WaitOne(0)

Add-Type -OutputAssembly $fakeExecutable -OutputType ConsoleApplication -TypeDefinition @'
using System;
using System.IO;
using System.Net;
using System.Net.Sockets;
using System.Diagnostics;
using System.Threading;
public class FakeLangflow {
    public static int Main(string[] args) {
        string root = AppDomain.CurrentDomain.BaseDirectory;
        string attempts = Path.Combine(root, "attempts.txt");
        File.AppendAllText(attempts, Process.GetCurrentProcess().Id + Environment.NewLine);
        if (File.ReadAllLines(attempts).Length == 1) return 7;
        int port = int.Parse(args[Array.IndexOf(args, "--port") + 1]);
        TcpListener listener = new TcpListener(IPAddress.Loopback, port);
        listener.Start();
        Thread.Sleep(60000);
        return 0;
    }
}
'@

function Start-TestSupervisor {
    Start-Process -FilePath powershell.exe -ArgumentList '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', "`"$supervisor`"", '-Executable', "`"$fakeExecutable`"", '-Port', $port, '-RetrySeconds', 1, '-LogPath', "`"$logPath`"" -WindowStyle Hidden -PassThru
}
function Wait-Attempts([int]$Count) {
    $deadline = (Get-Date).AddSeconds(25)
    do {
        Start-Sleep -Milliseconds 200
        $attempts = @(Get-Content -LiteralPath (Join-Path $testRoot 'attempts.txt') -ErrorAction SilentlyContinue)
        if ($attempts.Count -ge $Count) { return $attempts }
    } while ((Get-Date) -lt $deadline)
    throw "Expected $Count launch attempts."
}
try {
    if (-not $globalLocked) { throw 'Unexpected pre-existing test mutex.' }
    $primary = Start-TestSupervisor
    $children += $primary
    Start-Sleep -Seconds 3
    if (Test-Path -LiteralPath (Join-Path $testRoot 'attempts.txt')) { throw 'Occupied port started a duplicate server.' }
    $duplicate = Start-TestSupervisor
    $children += $duplicate
    if (-not $duplicate.WaitForExit(10000) -or $duplicate.ExitCode -ne 0) { throw 'Duplicate supervisor did not exit cleanly.' }
    $portReservation.Stop()
    $attempts = Wait-Attempts 2
    $fake = Get-Process -Id ([int]$attempts[-1])
    if ($fake.Path -ne $fakeExecutable) { throw 'Unexpected test process identity.' }
    Stop-Process -InputObject $fake -Force
    $attempts = Wait-Attempts 3
    'PASS: Global mutex isolation, occupied-port guard, duplicate supervisor, failed-launch retry, child crash recovery.'
} finally {
    if ($globalLocked) { $globalMutex.ReleaseMutex() }
    $globalMutex.Dispose()
    $portReservation.Stop()
    foreach ($child in $children) {
        if (-not $child.HasExited) { Stop-Process -InputObject $child -Force }
    }
    foreach ($processId in @(Get-Content -LiteralPath (Join-Path $testRoot 'attempts.txt') -ErrorAction SilentlyContinue)) {
        $candidate = Get-Process -Id ([int]$processId) -ErrorAction SilentlyContinue
        if ($candidate -and $candidate.Path -eq $fakeExecutable) { Stop-Process -InputObject $candidate -Force }
    }
    # Retain this isolated fixture and log for inspection; never touch live Langflow.
    "Evidence: $testRoot"
}

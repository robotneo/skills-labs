param([Parameter(Mandatory=$true)][string]$HostName)
$ErrorActionPreference = 'Stop'
try {
    $Timer = [System.Diagnostics.Stopwatch]::StartNew()
    $Resolved = [System.Net.Dns]::GetHostAddresses($HostName)
    $Timer.Stop()
    $Addresses = @($Resolved | ForEach-Object { $_.IPAddressToString })
    $Result = @{addresses=$Addresses;latency_ms=[Math]::Round($Timer.Elapsed.TotalMilliseconds, 2)}
    [Console]::WriteLine(($Result | ConvertTo-Json -Compress))
} catch {
    [Console]::Error.WriteLine('DNS lookup failed')
    exit 1
}

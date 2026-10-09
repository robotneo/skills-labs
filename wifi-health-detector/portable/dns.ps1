param([Parameter(Mandatory=$true)][string]$HostName)
$ErrorActionPreference = 'Stop'
try {
    foreach ($Address in [System.Net.Dns]::GetHostAddresses($HostName)) {
        [Console]::WriteLine($Address.IPAddressToString)
    }
} catch {
    [Console]::Error.WriteLine('DNS lookup failed')
    exit 1
}

$ErrorActionPreference='Stop'
$capacityOwner=Get-Content -LiteralPath (Join-Path $PSScriptRoot 'results\server_owner.json') -Raw | ConvertFrom-Json
$capacityPid=[int]$capacityOwner.pid
$capacityProcess=Get-CimInstance Win32_Process -Filter "ProcessId=$capacityPid"
$capacityListener=@(Get-NetTCPConnection -State Listen -LocalPort ([int]$capacityOwner.port) -ErrorAction SilentlyContinue)
if($null -eq $capacityProcess){throw 'Owned test server not found; will not stop another process.'}
if($capacityProcess.ExecutablePath -ne $capacityOwner.args[0]){throw 'Unexpected executable; stop cancelled.'}
if($capacityProcess.CommandLine -notlike '*center_app.py*--port*8791*'){throw 'Unexpected test command line; stop cancelled.'}
if($capacityListener.Count -ne 1 -or $capacityListener[0].OwningProcess -ne $capacityPid){throw 'Port owner does not match; stop cancelled.'}
Stop-Process -Id $capacityPid
Wait-Process -Id $capacityPid -Timeout 10 -ErrorAction SilentlyContinue
$capacityRemaining=@(Get-Process -Id $capacityPid -ErrorAction SilentlyContinue)
$capacityReport=[pscustomobject]@{
 stopped_owned_pid=$capacityPid
 only_owned_test_server_stopped=$true
 process_absent=($capacityRemaining.Count -eq 0)
 ended_utc=[DateTime]::UtcNow.ToString('o')
 nvidia_smi_global_after=(& nvidia-smi --query-gpu=name,memory.total,memory.used,driver_version --format=csv,noheader,nounits)
 user_server_port_8765_touched=$false
}
$capacityReport | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Join-Path $PSScriptRoot 'results\cleanup.json') -Encoding utf8
$capacityReport | ConvertTo-Json -Depth 4

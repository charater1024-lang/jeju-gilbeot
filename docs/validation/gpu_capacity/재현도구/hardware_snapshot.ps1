$ErrorActionPreference='Stop'
$capacityCpu=Get-CimInstance Win32_Processor
$capacityMachine=Get-CimInstance Win32_ComputerSystem
$capacityOs=Get-CimInstance Win32_OperatingSystem
$capacitySnapshot=[pscustomobject]@{
 captured_utc=[DateTime]::UtcNow.ToString('o')
 cpu=$capacityCpu.Name
 physical_cores=$capacityCpu.NumberOfCores
 logical_processors=$capacityCpu.NumberOfLogicalProcessors
 ram_bytes=[uint64]$capacityMachine.TotalPhysicalMemory
 os_caption=$capacityOs.Caption
 os_version=$capacityOs.Version
 system_free_ram_bytes=[uint64]$capacityOs.FreePhysicalMemory*1024
 nvidia_smi_global=(& nvidia-smi --query-gpu=name,memory.total,memory.used,driver_version --format=csv,noheader,nounits)
 power_scheme=(& powercfg /getactivescheme)
 note='GPU totals include all processes. Do not label global memory.used as serviceVRAM.'
}
$capacitySnapshot | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Join-Path $PSScriptRoot 'results\hardware.json') -Encoding utf8
$capacitySnapshot | ConvertTo-Json -Depth 4

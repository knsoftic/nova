# NOVA system discovery probe (read-only). Emits one JSON object on stdout.
$ErrorActionPreference = 'SilentlyContinue'
$ProgressPreference = 'SilentlyContinue'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$r = [ordered]@{}
$r.cpu = @(Get-CimInstance Win32_Processor | Select-Object Name, Manufacturer, NumberOfCores, NumberOfLogicalProcessors, MaxClockSpeed)
$r.os = Get-CimInstance Win32_OperatingSystem | Select-Object Caption, Version, BuildNumber, OSArchitecture
$r.computer = Get-CimInstance Win32_ComputerSystem | Select-Object Manufacturer, Model, TotalPhysicalMemory
$r.gpu = @(Get-CimInstance Win32_VideoController | Select-Object Name, AdapterRAM, DriverVersion, PNPDeviceID)
$r.disks = @(Get-CimInstance Win32_DiskDrive | Select-Object Model, Size, MediaType, InterfaceType)
$r.cameras = @(Get-PnpDevice -PresentOnly -Class Camera, Image | Select-Object FriendlyName, Status)
try {
    Add-Type -AssemblyName System.Windows.Forms
    $r.displays = @([System.Windows.Forms.Screen]::AllScreens | ForEach-Object {
        [ordered]@{ name = $_.DeviceName; primary = $_.Primary; width = $_.Bounds.Width; height = $_.Bounds.Height }
    })
} catch { $r.displays = @() }
$r.start_apps = @(Get-StartApps | Select-Object Name, AppID)
$r.display_version = (Get-ItemProperty 'HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion').DisplayVersion

$r | ConvertTo-Json -Depth 4 -Compress

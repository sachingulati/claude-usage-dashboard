<#
.SYNOPSIS
  Stop the Claude usage dashboard server and remove its logon auto-start,
  whichever way it was installed (scheduled task or Run key).

  Leaves project files, config, and generated output untouched — this only
  disables the auto-start. Delete the folder if you want it fully gone.

.EXAMPLE
  pwsh -File uninstall.ps1
#>
param(
    [string]$TaskName = "ClaudeUsageDashboard"
)

$ErrorActionPreference = "Stop"
$RunKey = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run"
$removed = $false

# 1. Scheduled task (Stop first so restart-on-failure can't re-launch it).
$task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($task) {
    try { Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue } catch {}
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Host "Removed scheduled task '$TaskName'."
    $removed = $true
}

# 2. Per-user logon Run key.
if (Get-ItemProperty -Path $RunKey -Name $TaskName -ErrorAction SilentlyContinue) {
    Remove-ItemProperty -Path $RunKey -Name $TaskName
    Write-Host "Removed logon Run key '$TaskName'."
    $removed = $true
}

# 3. Stop any running server process (covers the Run-key case; harmless otherwise).
$procs = Get-CimInstance Win32_Process `
    -Filter "Name = 'pythonw.exe' OR Name = 'python.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -like '*serve.py*' -and $_.CommandLine -like '*claude-usage-dashboard*' }
foreach ($p in $procs) {
    try {
        Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue
        Write-Host "Stopped server (PID $($p.ProcessId))."
        $removed = $true
    } catch {}
}

if ($removed) {
    Write-Host "Auto-start disabled and the server stopped. Project files are untouched."
    Write-Host "To reinstall: pwsh -File install.ps1"
} else {
    Write-Host "No auto-start (task or Run key) and no running server found - nothing to remove."
}

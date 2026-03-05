param(
  [string]$TaskName = "JobTrackerDailySync",
  [string]$PythonPath = "python",
  [string]$WorkingDir = (Resolve-Path "..").Path,
  [string]$Time = "08:00"
)

$action = New-ScheduledTaskAction -Execute $PythonPath -Argument "main.py sync --config config.yml" -WorkingDirectory $WorkingDir
$trigger = New-ScheduledTaskTrigger -Daily -At $Time
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -Description "Daily Yahoo inbox sync for jobs.xlsx" -Force
Write-Host "Registered scheduled task $TaskName at $Time"

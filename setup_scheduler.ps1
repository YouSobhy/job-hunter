# Setup daily Task Scheduler job for job_search.py
# Run this script once as Administrator

$pythonPath = (Get-Command python).Source
$scriptPath = "D:\Joe\JobHunter\job_search.py"
$taskName   = "YousefJobSearch"
$logPath    = "D:\Joe\JobHunter\scheduler_run.log"

$action  = New-ScheduledTaskAction `
    -Execute $pythonPath `
    -Argument "-X utf8 `"$scriptPath`" >> `"$logPath`" 2>&1"

$trigger1 = New-ScheduledTaskTrigger -Daily -At "18:00"

$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -RunOnlyIfNetworkAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 10)

Register-ScheduledTask `
    -TaskName  $taskName `
    -Action    $action `
    -Trigger   $trigger1 `
    -Settings  $settings `
    -RunLevel  Highest `
    -Force

Write-Host "Task '$taskName' registered. Runs at 18:00 daily."
Write-Host "To run it immediately: Start-ScheduledTask -TaskName '$taskName'"
Write-Host "To remove it:          Unregister-ScheduledTask -TaskName '$taskName' -Confirm:`$false"

# JobHunter scheduler setup. Run once as Administrator.
# Unregisters all legacy tasks and registers one canonical "JobHunter" task.

$oldTasks = @(
    "JobHunter Daily Search",
    "JobHunter-DailySearch",
    "YousefJobSearch",
    "YousefJobSearch_PM"
)
foreach ($name in $oldTasks) {
    try {
        Unregister-ScheduledTask -TaskName $name -Confirm:$false -ErrorAction Stop
        Write-Host "Removed old task: $name"
    } catch {
        Write-Host "Not found (ok): $name"
    }
}

$taskName = "JobHunter"
$batPath  = "D:\Joe\JobHunter\run_job_search.bat"

# No shell redirection in the action: Task Scheduler does not interpret >>,
# so redirection args would be passed to the program and break it.
# Python writes its own logs.
$action = New-ScheduledTaskAction -Execute $batPath -WorkingDirectory "D:\Joe\JobHunter"

$trigger = New-ScheduledTaskTrigger -Daily -At "18:00"

$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -RunOnlyIfNetworkAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 20)

Register-ScheduledTask `
    -TaskName $taskName `
    -Action   $action `
    -Trigger  $trigger `
    -Settings $settings `
    -Force

Write-Host ""
Write-Host "Task '$taskName' registered. Runs daily at 18:00."
Write-Host "Run now :  Start-ScheduledTask -TaskName '$taskName'"
Write-Host "Check   :  Get-Content D:\Joe\JobHunter\status.json"

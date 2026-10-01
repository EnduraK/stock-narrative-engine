# Stock Narrative Engine — Windows Task Scheduler Setup
# Run this script ONCE in PowerShell (as Administrator) to register the daily task.
# After that, the engine runs automatically every morning at 7:30 AM.
#
# To run this script:
#   1. Right-click PowerShell → "Run as Administrator"
#   2. Type:  cd "C:\Users\User\Desktop\stock_narrative_engine"
#   3. Type:  .\setup_scheduler.ps1

$TaskName    = "StockNarrativeEngine"
$ScriptDir   = "C:\Users\User\Desktop\stock_narrative_engine"
$BatchFile   = "$ScriptDir\run_engine.bat"
$RunTime     = "07:30"   # Change this to whatever time you prefer (24-hour format)

# Remove any existing task with the same name
Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue

# Define the action: run the batch file
$Action = New-ScheduledTaskAction `
    -Execute "cmd.exe" `
    -Argument "/c `"$BatchFile`"" `
    -WorkingDirectory $ScriptDir

# Define the trigger: daily at chosen time
$Trigger = New-ScheduledTaskTrigger -Daily -At $RunTime

# Define settings: run even if on battery, don't stop if it takes a while
$Settings = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 10) `
    -DisallowStartIfOnBatteries $false `
    -StopIfGoingOnBatteries $false `
    -StartWhenAvailable $true

# Register the task under the current user
Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $Action `
    -Trigger $Trigger `
    -Settings $Settings `
    -RunLevel Limited `
    -Force

Write-Host ""
Write-Host "SUCCESS: Task '$TaskName' registered." -ForegroundColor Green
Write-Host "The engine will run automatically every day at $RunTime." -ForegroundColor Green
Write-Host ""
Write-Host "Useful commands:"
Write-Host "  Run it right now:   Start-ScheduledTask -TaskName '$TaskName'"
Write-Host "  Check status:       Get-ScheduledTask -TaskName '$TaskName'"
Write-Host "  Remove the task:    Unregister-ScheduledTask -TaskName '$TaskName' -Confirm:`$false"
Write-Host ""
Write-Host "Logs are saved to: $ScriptDir\logs\scheduler.log"

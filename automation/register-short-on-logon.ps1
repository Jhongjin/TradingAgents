# Registers "AgentTrust Daily Short on logon": runs daily-short-on-logon.cmd
# two minutes after this user logs on. Re-running replaces the task.
# A logon trigger needs an elevated PowerShell (Run as administrator).
$ErrorActionPreference = 'Stop'
$name = 'AgentTrust Daily Short on logon'
$action = New-ScheduledTaskAction -Execute 'D:\Codex\TradingAgents\automation\daily-short-on-logon.cmd'
$trigger = New-ScheduledTaskTrigger -AtLogOn -User "$env:USERDOMAIN\$env:USERNAME"
$trigger.Delay = 'PT2M'
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Hours 2)
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Limited
Register-ScheduledTask -TaskName $name -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Force | Out-Null
$t = Get-ScheduledTask -TaskName $name
'{0} | {1} | trigger={2} delay={3}' -f $t.TaskName, $t.State, $t.Triggers[0].CimClass.CimClassName, $t.Triggers[0].Delay

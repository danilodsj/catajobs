# Cria a tarefa diária no Agendador de Tarefas do Windows (roda com o usuário logado, navegador visível).
param([string]$Hora = "08:00")
$script = Join-Path $PSScriptRoot "rodar_diario.ps1"
$acao = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$script`""
$gatilho = New-ScheduledTaskTrigger -Daily -At $Hora
$config = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Hours 10) -DontStopIfGoingOnBatteries
Register-ScheduledTask -TaskName "Catajobs diario" -Action $acao -Trigger $gatilho -Settings $config -Force | Out-Null
Write-Host "Tarefa 'Catajobs diario' agendada para $Hora todos os dias."

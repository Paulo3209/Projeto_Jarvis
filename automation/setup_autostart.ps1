<#
.SYNOPSIS
    Configura JARVIS para iniciar automaticamente no login do Windows.

.DESCRIPTION
    Cria uma tarefa agendada no Windows Task Scheduler que executa o JARVIS
    em modo de voz (--voice) quando o usuário faz login.

.NOTES
    Execute como Administrador para funcionar corretamente.
#>

param(
    [string]$JarvisPath = "C:\Users\paulo\jarvis",
    [string]$UserName = $env:USERNAME
)

# Verificar se está rodando como Admin
$isAdmin = ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    Write-Warning "Este script precisa ser executado como Administrador."
    Write-Host "Clique com botão direito no PowerShell e escolha 'Executar como administrador'."
    exit 1
}

$taskName = "JARVIS Auto-Start"
$vbsPath = Join-Path $JarvisPath "automation\start_jarvis_silent.vbs"
$pythonPath = Join-Path $JarvisPath ".venv\Scripts\python.exe"
$mainPath = Join-Path $JarvisPath "main.py"

# Verificar arquivos
if (-not (Test-Path $vbsPath)) {
    Write-Error "Arquivo start_jarvis_silent.vbs não encontrado em: $vbsPath"
    exit 1
}

if (-not (Test-Path $pythonPath)) {
    Write-Warning "Virtual environment não encontrado em: $pythonPath"
    Write-Host "Tentando usar python do sistema..."
    $pythonPath = "python"
}

# Remover tarefa existente se houver
if (Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue) {
    Write-Host "Removendo tarefa existente..."
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
}

# Criar ação da tarefa (usa VBScript para rodar silenciosamente)
$action = New-ScheduledTaskAction `
    -Execute "wscript.exe" `
    -Argument "`"$vbsPath`"" `
    -WorkingDirectory $JarvisPath

# Trigger: No logon do usuário
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $UserName

# Configurações
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -RunOnlyIfNetworkAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Hours 2)

# Principal: Executar com maior privilégio
$principal = New-ScheduledTaskPrincipal -UserId $UserName -LogonType Interactive -RunLevel Highest

# Registrar tarefa
try {
    Register-ScheduledTask `
        -TaskName $taskName `
        -Action $action `
        -Trigger $trigger `
        -Settings $settings `
        -Principal $principal `
        -Description "Inicia JARVIS em modo de voz automaticamente no login do Windows." `
        -Force

    Write-Host "`n✅ Tarefa '$taskName' criada com sucesso!" -ForegroundColor Green
    Write-Host "O JARVIS iniciará automaticamente na próxima vez que você fizer login no Windows."
}
catch {
    Write-Error "Erro ao criar tarefa: $_"
    exit 1
}

# Opcional: Executar agora para testar
$testNow = Read-Host "`nDeseja testar agora? (s/n)"
if ($testNow -eq 's') {
    Write-Host "Iniciando JARVIS para teste..."
    Start-Process -FilePath $pythonPath -ArgumentList "`"$mainPath`" --voice" -WorkingDirectory $JarvisPath
}
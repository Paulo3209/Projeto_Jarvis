<#
.SYNOPSIS
    Instala TUDO que o JARVIS precisa: Python deps + System deps (via winget)
.DESCRIPTION
    - Python packages (requirements.txt)
    - Ollama (LLM local)
    - Tesseract OCR (visao)
    - FFmpeg (audio)
    - ADB (Android)
    - Docker Desktop (MQTT broker)
    - Modelos Ollama (gemma3:4b)
#>

param(
    [switch]$SkipOllamaModels,
    [switch]$SkipDocker,
    [switch]$NoAdminCheck
)

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "       JARVIS LEVEL 5 - INSTALADOR COMPLETO                " -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""

# Verifica Admin
if (-not $NoAdminCheck) {
    $principal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
    if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        Write-Host "[AVISO]  Recomendado rodar como Administrador (winget precisa)" -ForegroundColor Yellow
        Write-Host "        Re-execute com: powershell -Command \"Start-Process powershell -Verb RunAs -ArgumentList '-File install_all.ps1'\"" -ForegroundColor Gray
        Write-Host ""
    }
}

$ErrorActionPreference = "Continue"
$wingetAvailable = (Get-Command winget -ErrorAction SilentlyContinue) -ne $null

function Install-WingetPackage {
    param([string]$Id, [string]$Name)
    if (-not $wingetAvailable) {
        Write-Host "[SKIP]  winget nao disponivel - instale $Name manualmente" -ForegroundColor Yellow
        return
    }
    Write-Host "[WINGET] Instalando $Name ($Id)..." -ForegroundColor Green
    winget install --id $Id --accept-source-agreements --accept-package-agreements --silent 2>&1 | Out-Null
    if ($LASTEXITCODE -eq 0) {
        Write-Host "        [OK] $Name instalado" -ForegroundColor Green
    } else {
        Write-Host "        [ERRO] Falha ao instalar $Name (codigo: $LASTEXITCODE)" -ForegroundColor Red
    }
}

# ==================== 1. PYTHON DEPENDENCIES ====================
Write-Host ""
Write-Host "=== 1/6 - DEPENDENCIAS PYTHON ===" -ForegroundColor Cyan
Write-Host ""

if (Test-Path "requirements.txt") {
    Write-Host "[PIP] Instalando requirements.txt..." -ForegroundColor Green
    pip install -r requirements.txt --quiet 2>&1 | Out-Null
    if ($LASTEXITCODE -eq 0) {
        Write-Host "        [OK] Python dependencies instaladas" -ForegroundColor Green
    } else {
        Write-Host "        [ERRO] Falha no pip install" -ForegroundColor Red
        Write-Host "        Tente: pip install -r requirements.txt" -ForegroundColor Gray
    }
} else {
    Write-Host "[ERRO] requirements.txt nao encontrado" -ForegroundColor Red
}

# ==================== 2. OLLAMA ====================
Write-Host ""
Write-Host "=== 2/6 - OLLAMA (LLM LOCAL) ===" -ForegroundColor Cyan
Write-Host ""

Install-WingetPackage "Ollama.Ollama" "Ollama"

# Inicia servico Ollama se nao estiver rodando
Write-Host "[OLLAMA] Verificando servico..." -ForegroundColor Green
$ollamaRunning = Get-Process "ollama" -ErrorAction SilentlyContinue
if (-not $ollamaRunning) {
    Write-Host "[OLLAMA] Iniciando ollama serve em background..." -ForegroundColor Yellow
    Start-Process "ollama" -ArgumentList "serve" -WindowStyle Hidden
    Start-Sleep 3
}

# Pull modelo padrao
if (-not $SkipOllamaModels) {
    Write-Host "[OLLAMA] Baixando modelo gemma3:4b (padrao)..." -ForegroundColor Green
    ollama pull gemma3:4b 2>&1 | ForEach-Object { Write-Host "        $_" -ForegroundColor Gray }
    Write-Host "[OLLAMA] Modelo gemma3:4b pronto" -ForegroundColor Green

    # Opcional: modelos extras leves
    Write-Host "[OLLAMA] Baixando phi3:mini (backup leve)..." -ForegroundColor Green
    ollama pull phi3:mini 2>&1 | ForEach-Object { Write-Host "        $_" -ForegroundColor Gray }
}

# ==================== 3. TESSERACT OCR ====================
Write-Host ""
Write-Host "=== 3/6 - TESSERACT OCR (VISAO) ===" -ForegroundColor Cyan
Write-Host ""
Install-WingetPackage "UB-Mannheim.TesseractOCR" "Tesseract OCR"

# Verifica se tessdata pt-BR existe, se nao avisa
$tessPath = "$env:TESSDATA_PREFIX"
if (-not $tessPath) { $tessPath = "C:\Program Files\Tesseract-OCR\tessdata" }
if (Test-Path "$tessPath\por.traineddata") {
    Write-Host "        [OK] Portugues (por.traineddata) ja presente" -ForegroundColor Green
} else {
    Write-Host "[AVISO]  Portugues (por.traineddata) NAO encontrado em $tessPath" -ForegroundColor Yellow
    Write-Host "        Baixe em: https://github.com/tesseract-ocr/tessdata_best/raw/main/por.traineddata" -ForegroundColor Gray
    Write-Host "        Salve em: $tessPath\por.traineddata" -ForegroundColor Gray
}

# ==================== 4. FFMPEG ====================
Write-Host ""
Write-Host "=== 4/6 - FFMPEG (AUDIO) ===" -ForegroundColor Cyan
Write-Host ""
Install-WingetPackage "Gyan.FFmpeg" "FFmpeg"

# ==================== 5. ADB (ANDROID) ====================
Write-Host ""
Write-Host "=== 5/6 - ADB (ANDROID) ===" -ForegroundColor Cyan
Write-Host ""
Install-WingetPackage "Google.ADB" "Android ADB"

# ==================== 6. DOCKER DESKTOP (MQTT) ====================
if (-not $SkipDocker) {
    Write-Host ""
    Write-Host "=== 6/6 - DOCKER DESKTOP (MQTT BROKER) ===" -ForegroundColor Cyan
    Write-Host ""
    Install-WingetPackage "Docker.DockerDesktop" "Docker Desktop"
    Write-Host "[INFO]   Docker Desktop precisa de reinicializacao e login" -ForegroundColor Yellow
    Write-Host "        apos instalar: reinicie o PC, abra Docker Desktop, faca login" -ForegroundColor Gray
    Write-Host "        depois: docker-compose -f automation/docker-compose.yml up -d" -ForegroundColor Gray
}

# ==================== VERIFICACAO FINAL ====================
Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "                   VERIFICACAO FINAL                        " -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""

$checks = @(
    @{Cmd="python --version"; Name="Python"},
    @{Cmd="ollama --version"; Name="Ollama"},
    @{Cmd="tesseract --version"; Name="Tesseract"},
    @{Cmd="ffmpeg -version"; Name="FFmpeg"},
    @{Cmd="adb version"; Name="ADB"},
    @{Cmd="docker --version"; Name="Docker"}
)

foreach ($c in $checks) {
    $out = Invoke-Expression $c.Cmd 2>$null
    if ($LASTEXITCODE -eq 0) {
        $ver = ($out -split "`n")[0]
        Write-Host "  [OK] $($c.Name): $ver" -ForegroundColor Green
    } else {
        Write-Host "  [FALTA] $($c.Name) - nao encontrado no PATH" -ForegroundColor Red
    }
}

Write-Host ""
Write-Host "=== PROXIMOS PASSOS ===" -ForegroundColor Cyan
Write-Host ""
Write-Host "  1. Reinicie o terminal (para PATH atualizar)" -ForegroundColor Yellow
Write-Host "  2. Teste: python cli.py doctor" -ForegroundColor Green
Write-Host "  3. Rode:  python main.py          (CLI)" -ForegroundColor Green
Write-Host "  4. Ou:    python main.py --voice  (Voz + Wake word 'jarvis')" -ForegroundColor Green
Write-Host "  5. Ou:    python cli.py start     (Web UI porta 8000)" -ForegroundColor Green
Write-Host ""
Write-Host "  Configuracao: edite config.yaml ou .env" -ForegroundColor Gray
Write-Host ""

# Pausa se rodou clicando no arquivo
if ($MyInvocation.InvocationName -like "*.ps1") {
    Write-Host "Pressione Enter para sair..."
    Read-Host | Out-Null
}
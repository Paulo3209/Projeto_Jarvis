# JARVIS Controle Total - Desktop + Android + Cross-Device

> ⚠️ **AVISO DE SEGURANÇA**: Este sistema concede controle administrativo total sobre seus dispositivos. Use com responsabilidade. Mantenha o broker MQTT seguro (senhas fortes, firewall, VPN).

---

## 📦 Visão Geral da Arquitetura

```
┌─────────────────┐     MQTT (1883/9001)      ┌─────────────────┐
│   JARVIS PC     │ ◄────────────────────────► │  JARVIS Phone   │
│  (Windows)      │      Cross-Device          │   (Android)     │
│                 │                            │   (Termux/ADB)  │
│  - Admin Master │                            │                 │
│  - Desktop Ctrl │                            │  - ADB/Shell    │
│  - Services     │                            │  - Termux API   │
│  - Registry     │                            │  - Sensors      │
└────────┬────────┘                            └────────┬────────┘
         │                                                │
         ▼                                                ▼
┌─────────────────┐                            ┌─────────────────┐
│   Mosquitto     │                            │  Termux:API     │
│   MQTT Broker   │                            │  (F-Droid)      │
│   (Docker)      │                            │                 │
└─────────────────┘                            └─────────────────┘
```

---

## 🛠️ Ferramentas Disponíveis

### 🖥️ Desktop Control (Windows Admin Master)
| Ferramenta | Descrição | Perigo |
|------------|-----------|--------|
| `list_processes` | Lista processos (CPU, RAM, usuário) | Baixo |
| `kill_process` | Mata processo por PID/nome | **Alto** |
| `manage_service` | Inicia/para/reinicia serviços Windows | **Alto** |
| `network_info` | Adaptadores, IPs, conexões ativas | Baixo |
| `network_test` | Ping, porta TCP, DNS, traceroute | Baixo |
| `power_control` | Desligar, reiniciar, hibernar, suspender, bloquear | **Alto** |
| `run_powershell` | Executa **qualquer** comando PowerShell (com admin opcional) | **MÁXIMO** |
| `search_files` | Busca arquivos no sistema todo (precisa admin) | Médio |
| `registry_edit` | Lê/Escreve/Deleta/Lista chaves do Registro | **Alto** |
| `hardware_info` | CPU, RAM, Disco, GPU, Temperaturas | Baixo |
| `simulate_input` | Teclado/mouse (pyautogui) | Médio |
| `window_control` | Foca, move, redimensiona, fecha janelas | Médio |

### 📱 Android Control (ADB + Termux)
| Ferramenta | Descrição | Requisito |
|------------|-----------|-----------|
| `android_devices` | Lista dispositivos ADB conectados | ADB |
| `android_connect_wifi` | Conecta via Wi-Fi (após `adb tcpip 5555`) | ADB + USB inicial |
| `android_list_packages` | Lista apps instalados (sistema/usuário) | ADB |
| `android_open_app` | Abre app por package/activity | ADB |
| `android_close_app` | Força parada do app | ADB |
| `android_package_manager` | Install/uninstall/clear/permissões | ADB |
| `android_shell` | Executa shell command (opcional `su` para root) | ADB (+root) |
| `android_screencap` | Captura tela do celular | ADB |
| `android_screenrecord` | Grava tela (máx 3 min) | ADB |
| `android_input` | Tap, swipe, long_press, text, keyevent | ADB |
| `android_communication` | SMS, ligação (via intent) | ADB + permissão |
| `android_file` | Push/pull/list/delete/mkdir no Android | ADB |
| `android_system_info` | Bateria, storage, CPU, props, sensores | ADB |
| `android_settings` | Wi-Fi, BT, GPS, avião, brilho, volume, rotação | ADB |
| `android_notifications` | Lista/limpa notificações (precisa Notification Listener) | ADB |
| `termux_exec` | Executa comandos no Termux (Linux no Android) | Termux + Termux:API |

### 🔗 Cross-Device (MQTT)
| Ferramenta | Descrição |
|------------|-----------|
| `cross_device_connect` | Conecta ao broker MQTT |
| `cross_device_send_command` | Envia comando para device específico ou broadcast |
| `cross_device_list` | Lista devices JARVIS online |
| `cross_device_sync` | Sincroniza variáveis (key-value) entre devices |
| `cross_device_heartbeat` | Inicia heartbeat automático (30s) |
| `cross_device_disconnect` | Desconecta do broker |

---

## 🚀 Instalação Completa

### 1. Pré-requisitos no PC (Windows)

```powershell
# 1. Instale Docker Desktop
# https://docs.docker.com/desktop/install/windows-install/

# 2. Instale ADB (Android Platform Tools)
# https://developer.android.com/studio/releases/platform-tools
# Adicione ao PATH do Windows

# 3. Python 3.10+ com venv
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt

# 4. Dependências extras para desktop control
pip install psutil pyautogui pygetwindow paho-mqtt
```

### 2. Inicie o Broker MQTT

```powershell
cd C:\Users\paulo\jarvis\automation

# Opção A: Docker Compose (recomendado)
docker-compose up -d

# Opção B: Apenas Mosquitto
docker run -d --name jarvis-mqtt \
  -p 1883:1883 -p 9001:9001 \
  -v ${PWD}/mosquitto/config:/mosquitto/config \
  -v ${PWD}/mosquitto/data:/mosquitto/data \
  -v ${PWD}/mosquitto/log:/mosquitto/log \
  eclipse-mosquitto:2
```

**Crie senha para o broker:**
```powershell
# Gera hash bcrypt
docker run --rm -it eclipse-mosquitto:2 mosquitto_passwd -c /tmp/passwd jarvis
# Copia o hash para automation/mosquitto/config/passwd
# Edite mosquitto.conf: allow_anonymous false
# Reinicie: docker restart jarvis-mqtt
```

### 3. Configure o Android

#### No Celular:
1. **Ative Opções do Desenvolvedor**: Configurações → Sobre o telefone → Toque 7x em "Número da versão"
2. **Ative Depuração USB**: Opções do desenvolvedor → Depuração USB
3. **Instale Termux** (F-Droid recomendado): https://f-droid.org/packages/com.termux/
4. **Instale Termux:API** (F-Droid): https://f-droid.org/packages/com.termux.api/
5. **Instale Termux:Boot** (para auto-start): https://f-droid.org/packages/com.termux.boot/

#### No Termux (execute no celular):
```bash
# Baixe e execute o setup
curl -fsSL https://raw.githubusercontent.com/seu-repo/jarvis/main/automation/android_termux_setup.sh | bash

# Ou copie o arquivo android_termux_setup.sh para o celular e execute:
bash android_termux_setup.sh
```

#### Configure IP do PC:
Edite `~/jarvis/start_jarvis.sh` no Termux:
```bash
export JARVIS_MQTT_HOST=192.168.1.XXX  # IP do seu PC na rede local
export JARVIS_MQTT_PORT=1883
export JARVIS_DEVICE_NAME=JARVIS-Phone
```

#### Teste conexão ADB (no PC):
```powershell
# USB
adb devices

# Wi-Fi (após USB conectado)
adb tcpip 5555
adb connect 192.168.1.YYY:5555  # IP do celular
```

### 4. Inicie o JARVIS no PC

```powershell
cd C:\Users\paulo\jarvis
.\.venv\Scripts\activate
python main.py --voice
```

### 5. Inicie o JARVIS no Celular (Termux)

```bash
cd ~/jarvis
./start_jarvis.sh
```

---

## 🎤 Comandos de Voz Exemplos

### Desktop (PC)
> **"jarvis liste processos"** → Lista top processos
> **"jarvis mate o processo chrome"** → Mata Chrome
> **"jarvis reinicie o serviço spooler"** → Reinicia Print Spooler
> **"jarvis desligue o PC em 60 segundos"** → Agenda desligamento
> **"jarvis execute powershell get-service wuauserv"** → Qualquer PowerShell
> **"jarvis abra o registro HKCU Software Microsoft Windows CurrentVersion Run"** → Lê registry
> **"jarvis tire screenshot"** → Captura tela
> **"jarvis foque na janela Chrome"** → Foca janela
> **"jarvis info hardware"** → CPU, RAM, Disco, GPU

### Android (Celular)
> **"jarvis liste dispositivos android"** → Mostra celulares conectados
> **"jarvis abra whatsapp no celular"** → Abre WhatsApp
> **"jarvis capture tela do celular"** → Screenshot do Android
> **"jarvis grave tela do celular 30 segundos"** → Grava vídeo
> **"jarvis toque no celular x 500 y 1000"** → Simula toque
> **"jarvis deslize no celular de 500 1500 para 500 500"** → Swipe up
> **"jarvis digite no celular olá mundo"** → Digita texto
> **"jarvis configure wifi ligado no celular"** → Liga Wi-Fi
> **"jarvis configure brilho 128 no celular"** → Brilho 50%
> **"jarvis notifique celular título JARVIS mensagem Teste"** → Notificação local
> **"jarvis fale no celular olá do jarvis"** → TTS no celular
> **"jarvis info bateria celular"** → Status bateria
> **"jarvis execute termux no celular ls -la /sdcard"** → Comando Linux no Termux

### Cross-Device (Entre PC e Celular)
> **"jarvis conecte mqtt broker 192.168.1.100"** → Conecta ao broker
> **"jarvis liste dispositivos jarvis"** → Mostra PC e celular online
> **"jarvis envie comando para celular abra configurações"** → Comando remoto
> **"jarvis broadcast diga olá em todos dispositivos"** → Broadcast
> **"jarvis sincronize variável usuario_logado true"** → Sync estado
> **"jarvis inicie heartbeat"** → Mantém presença online

---

## 🔐 Segurança e Boas Práticas

### Broker MQTT
```yaml
# docker-compose.yml - Use senhas fortes
# Gere com: docker run --rm eclipse-mosquitto:2 mosquitto_passwd -c /tmp/pw usuario
# mosquitto.conf:
allow_anonymous false
password_file /mosquitto/config/passwd
listener 1883
listener 9001 websockets
```

### Firewall Windows
```powershell
# Permite apenas rede local (ajuste sua subnet)
New-NetFirewallRule -DisplayName "JARVIS MQTT" -Direction Inbound -LocalPort 1883,9001 -Protocol TCP -RemoteAddress 192.168.1.0/24 -Action Allow
```

### ADB Seguro
```powershell
# Apenas USB (não habilite tcpip permanente)
# Para Wi-Fi temporário:
adb tcpip 5555
adb connect IP:5555
# Depois: adb usb (volta para USB only)
```

### Termux Permissões
```bash
# No Termux, conceda permissões necessárias:
termux-api # Testa se Termux:API funciona
# Para notificações: termux-notification -t "Teste" -c "OK"
# Para TTS: termux-tts-speak "Teste"
```

---

## 🔧 Configurações Avançadas

### Variáveis de Ambiente (.env)
```bash
# PC
JARVIS_MQTT_HOST=192.168.1.100
JARVIS_MQTT_PORT=1883
JARVIS_MQTT_USER=jarvis
JARVIS_MQTT_PASS=sua_senha_forte
JARVIS_DEVICE_NAME=JARVIS-Desktop
JARVIS_GEMINI_API_KEY=sua_chave_gemini

# Celular (Termux) - adicione ao ~/.bashrc ou start_jarvis.sh
export JARVIS_MQTT_HOST=192.168.1.100
export JARVIS_MQTT_PORT=1883
export JARVIS_DEVICE_NAME=JARVIS-Phone
```

### Auto-Start Completo (PC + Celular)

#### PC (Task Scheduler - já configurado)
```powershell
# Executa setup_autostart.ps1 como Admin
.\automation\setup_autostart.ps1
```

#### Celular (Termux:Boot)
```bash
# Já criado pelo setup script em ~/.termux/boot/start_jarvis
# Instale termux-boot e termux:boot no F-Droid
# Reinicie o celular para testar
```

---

## 🐛 Solução de Problemas

### MQTT não conecta
```bash
# Teste conexão
mosquitto_sub -h 192.168.1.100 -t "jarvis/#" -v

# Verifique logs
docker logs jarvis-mqtt
```

### ADB não vê celular
```bash
# Verifique depuração USB ativa
adb kill-server
adb start-server
adb devices

# Drivers USB (Windows): instale "Universal ADB Driver"
```

### Termux:API não funciona
```bash
# No celular: abra app Termux:API → Permissões → Todas
# No Termux: termux-reload-settings
# Teste: termux-battery-status
```

### PowerShell admin falha
```powershell
# Verifique se Task Scheduler roda com "Run with highest privileges"
# O script start_jarvis_silent.vbs roda como usuário logado
# Para admin real: configure scheduled task com "Run as SYSTEM" (cuidado!)
```

---

## 📁 Estrutura de Arquivos

```
jarvis/
├── automation/
│   ├── start_jarvis.bat              # Launcher console
│   ├── start_jarvis_silent.vbs       # Launcher silencioso (Task Scheduler)
│   ├── setup_autostart.ps1           # Configura auto-start Windows
│   ├── android_termux_setup.sh       # Setup completo Android/Termux
│   ├── docker-compose.yml            # MQTT + Home Assistant
│   ├── mosquitto/
│   │   ├── config/mosquitto.conf     # Config broker
│   │   ├── config/passwd             # Senhas (bcrypt)
│   │   ├── data/                     # Persistência
│   │   └── log/                      # Logs
│   ├── README_AUTOSTART.md           # Guia auto-start
│   └── README_FULL_CONTROL.md        # Este arquivo
├── tools/
│   ├── startup.py                    # Saudação horário + unlock PC
│   ├── desktop_control.py            # Controle total Windows (Admin)
│   ├── android_control.py            # ADB + Termux controle Android
│   ├── cross_device.py               # MQTT cross-device sync
│   └── system.py                     # Router compatibilidade (exporta todos)
├── main.py                           # Entry point (voz + saudação)
└── core/                             # Brain, personality, event_bus, plugins
```

---

## ⚡ Início Rápido (Resumo)

```powershell
# 1. PC: Inicie broker
cd automation
docker-compose up -d

# 2. PC: Inicie JARVIS
cd ..
.\.venv\Scripts\activate
python main.py --voice

# 3. Celular: Configure (uma vez)
# - Instale Termux + Termux:API + Termux:Boot (F-Droid)
# - Execute android_termux_setup.sh
# - Edite ~/jarvis/start_jarvis.sh com IP do PC
# - ./start_jarvis.sh

# 4. Teste comandos:
# "jarvis conecte mqtt broker 192.168.1.100"
# "jarvis liste dispositivos jarvis"
# "jarvis envie comando para celular capture tela"
# "jarvis desligue o pc em 10 segundos"
```

---

## 📜 Licença e Responsabilidade

**USE POR SUA CONTA E RISCO.** Este software concede controle administrativo total sobre seus dispositivos. O autor não se responsabiliza por:
- Perda de dados por comandos destrutivos
- Danos ao sistema por edição de registro/serviços
- Segurança comprometida por broker MQTT exposto
- Bricking do Android por comandos root/ADB inadequados
- Cobranças por SMS/ligações automatizadas

**SEMPRE TESTE EM AMBIENTE CONTROLADO ANTES DE USAR EM PRODUÇÃO.**
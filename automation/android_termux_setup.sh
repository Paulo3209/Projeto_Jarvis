#!/data/data/com.termux/files/usr/bin/bash
# JARVIS Android Termux Setup Script
# Execute no Termux no celular: bash android_termux_setup.sh

set -e

echo "🤖 JARVIS Android Termux Setup"
echo "=============================="

# Atualiza pacotes
echo "📦 Atualizando pacotes..."
pkg update -y && pkg upgrade -y

# Instala dependências essenciais
echo "📦 Instalando dependências..."
pkg install -y \
    python \
    python-pip \
    git \
    openssh \
    termux-api \
    termux-tools \
    procps \
    net-tools \
    iproute2 \
    jq \
    curl \
    wget \
    ffmpeg \
    imagemagick \
    vim \
    nano \
    htop \
    tree \
    fzf \
    ripgrep \
    fd

# Python packages
echo "🐍 Instalando pacotes Python..."
pip install --upgrade pip
pip install \
    paho-mqtt \
    requests \
    websockets \
    psutil \
    numpy \
    opencv-python-headless \
    pillow \
    python-dotenv \
    aiohttp \
    asyncssh \
    pyyaml

# Configura Termux:API (precisa app F-Droid/Play Store)
echo "📱 Verificando Termux:API..."
if ! command -v termux-battery-status &> /dev/null; then
    echo "⚠️  Termux:API não encontrado. Instale o app 'Termux:API' no F-Droid ou Play Store"
    echo "   Depois execute: termux-reload-settings"
fi

# Permissões de armazenamento
echo "📂 Configurando armazenamento..."
termux-setup-storage

# Cria diretório JARVIS
JARVIS_DIR="$HOME/jarvis"
mkdir -p "$JARVIS_DIR"
cd "$JARVIS_DIR"

# Clone ou copia arquivos do JARVIS (ajuste conforme necessário)
if [ ! -f "main.py" ]; then
    echo "📥 Baixando JARVIS Android Client..."
    # Se tiver repo git:
    # git clone https://github.com/seu-usuario/jarvis.git .
    # Ou copie manualmente os arquivos necessários
    cat > main.py << 'EOF'
#!/usr/bin/env python3
"""
JARVIS Android Client - Roda no Termux no celular.
Conecta ao broker MQTT e executa comandos locais.
"""
import asyncio
import json
import os
import sys
import uuid
import subprocess
import shlex
from datetime import datetime
from pathlib import Path

# Adiciona paths
sys.path.insert(0, str(Path(__file__).parent))

# Configurações
BROKER_HOST = os.getenv("JARVIS_MQTT_HOST", "192.168.1.100")  # IP do PC
BROKER_PORT = int(os.getenv("JARVIS_MQTT_PORT", "1883"))
DEVICE_NAME = os.getenv("JARVIS_DEVICE_NAME", "JARVIS-Phone")
DEVICE_ID = f"jarvis-android-{uuid.uuid4().hex[:8]}"

try:
    import paho.mqtt.client as mqtt
except ImportError:
    print("Instalando paho-mqtt...")
    subprocess.run([sys.executable, "-m", "pip", "install", "paho-mqtt"], check=True)
    import paho.mqtt.client as mqtt

class JarvisAndroidClient:
    def __init__(self):
        self.client = mqtt.Client(client_id=DEVICE_ID, protocol=mqtt.MQTTv5)
        self.connected = False
        self.running = True
        self.pending_commands = {}

    def on_connect(self, client, userdata, flags, rc, properties=None):
        if rc == 0:
            self.connected = True
            print(f"✅ Conectado ao broker {BROKER_HOST}:{BROKER_PORT}")
            # Subscreve
            client.subscribe(f"jarvis/commands/{DEVICE_ID}", qos=1)
            client.subscribe("jarvis/broadcast", qos=1)
            client.subscribe("jarvis/sync", qos=1)
            # Anuncia online
            self.announce_online()
        else:
            print(f"❌ Falha na conexão: {rc}")

    def on_message(self, client, userdata, msg):
        try:
            payload = json.loads(msg.payload.decode())
            topic = msg.topic

            if topic == f"jarvis/commands/{DEVICE_ID}":
                asyncio.create_task(self.handle_command(payload))
            elif topic == "jarvis/broadcast":
                asyncio.create_task(self.handle_broadcast(payload))
            elif topic == "jarvis/sync":
                asyncio.create_task(self.handle_sync(payload))
        except Exception as e:
            print(f"Erro processando msg: {e}")

    def on_disconnect(self, client, userdata, rc, properties=None):
        self.connected = False
        print(f"Desconectado: {rc}")

    async def handle_command(self, payload):
        cmd = payload.get("command")
        args = payload.get("args", {})
        corr_id = payload.get("correlation_id")
        source = payload.get("source_device")

        print(f"📨 Comando recebido: {cmd} {args}")

        result = await self.execute_local_command(cmd, args)

        # Envia resposta
        response = {
            "id": str(uuid.uuid4()),
            "type": "response",
            "source_device": DEVICE_ID,
            "target_device": source,
            "payload": result,
            "correlation_id": corr_id,
            "timestamp": datetime.now().isoformat()
        }
        self.client.publish(f"jarvis/commands/{source}", json.dumps(response), qos=1)

    async def handle_broadcast(self, payload):
        cmd = payload.get("command")
        args = payload.get("args", {})
        target_type = payload.get("target_type")

        # Filtra por tipo se especificado
        if target_type and target_type != "android":
            return

        print(f"📢 Broadcast: {cmd} {args}")
        result = await self.execute_local_command(cmd, args)
        print(f"   Resultado: {result.get('success')}")

    async def handle_sync(self, payload):
        key = payload.get("key")
        value = payload.get("value")
        action = payload.get("action", "set")

        if action == "set":
            os.environ[f"JARVIS_SYNC_{key.upper()}"] = str(value)
            print(f"🔄 Sync: {key} = {value}")

    async def execute_local_command(self, cmd: str, args: dict) -> dict:
        """Executa comando local no Android via Termux."""
        try:
            if cmd == "shell":
                # Executa shell command
                command = args.get("command", "")
                as_root = args.get("as_root", False)
                if as_root:
                    full_cmd = ["su", "-c", command]
                else:
                    full_cmd = ["sh", "-c", command]
                proc = await asyncio.create_subprocess_exec(
                    *full_cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                stdout, stderr = await proc.communicate()
                return {
                    "success": proc.returncode == 0,
                    "stdout": stdout.decode()[:5000],
                    "stderr": stderr.decode()[:2000],
                    "returncode": proc.returncode
                }

            elif cmd == "termux_api":
                # Usa termux-api
                api = args.get("api", "")
                api_args = args.get("args", [])
                full_cmd = ["termux-" + api] + api_args
                proc = await asyncio.create_subprocess_exec(
                    *full_cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                stdout, stderr = await proc.communicate()
                return {
                    "success": proc.returncode == 0,
                    "stdout": stdout.decode(),
                    "stderr": stderr.decode()
                }

            elif cmd == "screencap":
                # Captura tela
                save_path = args.get("path", "/sdcard/screen.png")
                proc = await asyncio.create_subprocess_exec(
                    "screencap", "-p", save_path,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                await proc.communicate()
                return {"success": proc.returncode == 0, "path": save_path}

            elif cmd == "input":
                # Simula input
                action = args.get("action", "tap")
                if action == "tap":
                    x, y = args.get("x", 0), args.get("y", 0)
                    proc = await asyncio.create_subprocess_exec("input", "tap", str(x), str(y))
                elif action == "swipe":
                    x1, y1, x2, y2 = args.get("x1"), args.get("y1"), args.get("x2"), args.get("y2")
                    duration = args.get("duration", 300)
                    proc = await asyncio.create_subprocess_exec("input", "swipe", str(x1), str(y1), str(x2), str(y2), str(duration))
                elif action == "text":
                    text = args.get("text", "").replace(" ", "%s")
                    proc = await asyncio.create_subprocess_exec("input", "text", text)
                elif action == "keyevent":
                    key = args.get("keycode", "KEYCODE_HOME")
                    proc = await asyncio.create_subprocess_exec("input", "keyevent", key)
                await proc.communicate()
                return {"success": proc.returncode == 0}

            elif cmd == "open_app":
                package = args.get("package", "")
                activity = args.get("activity", "")
                if activity:
                    proc = await asyncio.create_subprocess_exec("am", "start", "-n", f"{package}/{activity}")
                else:
                    proc = await asyncio.create_subprocess_exec("monkey", "-p", package, "-c", "android.intent.category.LAUNCHER", "1")
                await proc.communicate()
                return {"success": proc.returncode == 0}

            elif cmd == "settings":
                setting = args.get("setting", "")
                value = args.get("value", "")
                settings_map = {
                    "wifi": ["svc", "wifi", "enable" if value == "on" else "disable"],
                    "bluetooth": ["service", "call", "bluetooth_manager", "8" if value == "on" else "9"],
                    "airplane": ["settings", "put", "global", "airplane_mode_on", "1" if value == "on" else "0"],
                    "brightness": ["settings", "put", "system", "screen_brightness", value],
                }
                if setting in settings_map:
                    proc = await asyncio.create_subprocess_exec(*settings_map[setting])
                    await proc.communicate()
                    return {"success": proc.returncode == 0}
                return {"success": False, "error": "Setting desconhecido"}

            elif cmd == "get_info":
                # Retorna info do dispositivo
                info = {}
                # Bateria
                try:
                    bat = subprocess.run(["termux-battery-status"], capture_output=True, text=True)
                    info["battery"] = json.loads(bat.stdout) if bat.returncode == 0 else {}
                except:
                    pass
                # WiFi
                try:
                    wifi = subprocess.run(["termux-wifi-connectioninfo"], capture_output=True, text=True)
                    info["wifi"] = json.loads(wifi.stdout) if wifi.returncode == 0 else {}
                except:
                    pass
                # Sensores
                try:
                    sensors = subprocess.run(["termux-sensor", "-s", "all", "-d", "100"], capture_output=True, text=True, timeout=2)
                    info["sensors"] = sensors.stdout[:2000]
                except:
                    pass
                return {"success": True, "info": info}

            elif cmd == "notify":
                # Envia notificação local
                title = args.get("title", "JARVIS")
                content = args.get("content", "")
                subprocess.run(["termux-notification", "--title", title, "--content", content])
                return {"success": True}

            elif cmd == "vibrate":
                duration = args.get("duration", 500)
                subprocess.run(["termux-vibrate", "-d", str(duration)])
                return {"success": True}

            elif cmd == "tts":
                # Text-to-speech
                text = args.get("text", "")
                subprocess.run(["termux-tts-speak", text])
                return {"success": True}

            elif cmd == "camera":
                # Foto
                save_path = args.get("path", "/sdcard/jarvis_photo.jpg")
                subprocess.run(["termux-camera-photo", "-c", "0", save_path])
                return {"success": True, "path": save_path}

            else:
                return {"success": False, "error": f"Comando não suportado: {cmd}"}

        except Exception as e:
            return {"success": False, "error": str(e)}

    def announce_online(self):
        payload = {
            "type": "event",
            "event": "device_online",
            "device_id": DEVICE_ID,
            "timestamp": datetime.now().isoformat(),
            "device": {
                "id": DEVICE_ID,
                "name": DEVICE_NAME,
                "type": "android",
                "capabilities": ["shell", "termux_api", "screencap", "input", "open_app", "settings", "notify", "camera", "tts", "vibrate"],
                "status": "online"
            }
        }
        self.client.publish("jarvis/events", json.dumps(payload), qos=1)

    def send_heartbeat(self):
        if self.connected:
            payload = {
                "type": "event",
                "event": "heartbeat",
                "device_id": DEVICE_ID,
                "timestamp": datetime.now().isoformat(),
                "device": {
                    "id": DEVICE_ID,
                    "name": DEVICE_NAME,
                    "type": "android",
                    "status": "online"
                }
            }
            self.client.publish("jarvis/events", json.dumps(payload), qos=1)

    def run(self):
        self.client.on_connect = self.on_connect
        self.client.on_message = self.on_message
        self.client.on_disconnect = self.on_disconnect

        # Last will
        will = {"type": "event", "event": "device_offline", "device_id": DEVICE_ID}
        self.client.will_set("jarvis/events", json.dumps(will), qos=1)

        try:
            print(f"🔌 Conectando a {BROKER_HOST}:{BROKER_PORT}...")
            self.client.connect(BROKER_HOST, BROKER_PORT, 60)
            self.client.loop_start()

            # Loop principal
            while self.running:
                if self.connected:
                    self.send_heartbeat()
                import time
                time.sleep(30)

        except KeyboardInterrupt:
            print("\n🛑 Parando...")
        except Exception as e:
            print(f"Erro: {e}")
        finally:
            self.client.loop_stop()
            self.client.disconnect()

if __name__ == "__main__":
    client = JarvisAndroidClient()
    client.run()
EOF
    chmod +x main.py
fi

# Cria script de inicialização
cat > start_jarvis.sh << 'EOF'
#!/data/data/com.termux/files/usr/bin/bash
# Inicia JARVIS Android Client

cd ~/jarvis
export JARVIS_MQTT_HOST="${JARVIS_MQTT_HOST:-192.168.1.100}"
export JARVIS_MQTT_PORT="${JARVIS_MQTT_PORT:-1883}"
export JARVIS_DEVICE_NAME="${JARVIS_DEVICE_NAME:-JARVIS-Phone}"

echo "🚀 Iniciando JARVIS Android Client..."
echo "   Broker: $JARVIS_MQTT_HOST:$JARVIS_MQTT_PORT"
echo "   Device: $JARVIS_DEVICE_NAME"

python main.py
EOF
chmod +x start_jarvis.sh

# Cria serviço systemd-like para Termux (termux-services)
mkdir -p ~/.termux/boot
cat > ~/.termux/boot/start_jarvis << 'EOF'
#!/data/data/com.termux/files/usr/bin/bash
# Auto-start no boot do Android (precisa termux-boot e termux:boot instalados)
sleep 30  # Aguarda rede
cd ~/jarvis
./start_jarvis.sh >> jarvis.log 2>&1 &
EOF
chmod +x ~/.termux/boot/start_jarvis

echo ""
echo "✅ Setup concluído!"
echo ""
echo "📋 Próximos passos:"
echo "1. Instale o app 'Termux:API' no F-Droid (recomendado) ou Play Store"
echo "2. Execute: termux-reload-settings"
echo "3. Configure o IP do PC no arquivo start_jarvis.sh ou variável de ambiente:"
echo "   export JARVIS_MQTT_HOST=192.168.1.XXX"
echo "4. Inicie o broker MQTT no PC (mosquitto ou docker)"
echo "5. Execute: ./start_jarvis.sh"
echo ""
echo "🔧 Para auto-start no boot do Android:"
echo "   pkg install termux-boot termux:boot"
echo "   (O script já foi criado em ~/.termux/boot/)"
echo ""
echo "📱 Comandos Termux úteis:"
echo "   termux-battery-status"
echo "   termux-wifi-connectioninfo"
echo "   termux-notification -t 'Teste' -c 'Funcionando!'"
echo "   termux-tts-speak 'Olá do JARVIS'"
echo "   termux-vibrate -d 1000"
echo "   termux-camera-photo -c 0 /sdcard/foto.jpg"
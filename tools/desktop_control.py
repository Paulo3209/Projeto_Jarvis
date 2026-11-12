"""
Controle Total do Desktop - Windows Admin Master
Ferramentas avançadas para controle completo do sistema.
"""
import os
import platform
import subprocess
import ctypes
import psutil
import winreg
import json
import time
from pathlib import Path
from datetime import datetime
from typing import Optional, List, Dict, Any
from core.plugin_system import tool, ToolCategory

ROOT = Path(__file__).resolve().parents[1]


# ==================== UTILITÁRIOS WINDOWS ====================

def _run_powershell(cmd: str, admin: bool = False) -> dict:
    """Executa comando PowerShell, opcionalmente como admin."""
    try:
        if admin:
            # Usa Start-Process com -Verb RunAs
            ps_cmd = f'Start-Process powershell -ArgumentList "-NoProfile -ExecutionPolicy Bypass -Command {cmd}" -Verb RunAs -Wait'
            result = subprocess.run(["powershell", "-Command", ps_cmd], capture_output=True, text=True, timeout=30)
        else:
            result = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", cmd], capture_output=True, text=True, timeout=30)

        return {
            "success": result.returncode == 0,
            "stdout": result.stdout.strip(),
            "stderr": result.stderr.strip(),
            "returncode": result.returncode
        }
    except subprocess.TimeoutExpired:
        return {"success": False, "error": "Timeout (30s)"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _run_cmd(cmd: list, admin: bool = False) -> dict:
    """Executa comando CMD."""
    try:
        if admin:
            # PowerShell para elevar
            ps_cmd = ' '.join([f'"{c}"' if ' ' in c else c for c in cmd])
            return _run_powershell(f'Start-Process cmd -ArgumentList "/c {ps_cmd}" -Verb RunAs -Wait', admin=True)
        else:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            return {"success": result.returncode == 0, "stdout": result.stdout, "stderr": result.stderr}
    except Exception as e:
        return {"success": False, "error": str(e)}


# ==================== PROCESSOS E SERVIÇOS ====================

@tool(description="Lista processos em execução com detalhes.", category=ToolCategory.SYSTEM)
def list_processes(filter_name: str = "", limit: int = 50) -> dict:
    """Lista processos (opcionalmente filtrados por nome)."""
    try:
        procs = []
        for proc in psutil.process_iter(['pid', 'name', 'cpu_percent', 'memory_percent', 'status', 'username', 'create_time']):
            try:
                info = proc.info
                if filter_name and filter_name.lower() not in info['name'].lower():
                    continue
                info['create_time'] = datetime.fromtimestamp(info['create_time']).isoformat()
                procs.append(info)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

        procs.sort(key=lambda x: x.get('cpu_percent', 0), reverse=True)
        return {"success": True, "count": len(procs), "processes": procs[:limit]}
    except Exception as e:
        return {"success": False, "message": str(e)}


@tool(description="Mata um processo por PID ou nome.", category=ToolCategory.SYSTEM, dangerous=True, confirmation_message="Isso vai encerrar o processo à força. Confirmar?")
def kill_process(pid: int = None, name: str = None) -> dict:
    """Encerra processo por PID ou nome."""
    if not pid and not name:
        return {"success": False, "message": "Forneça PID ou nome do processo."}

    killed = []
    errors = []

    for proc in psutil.process_iter(['pid', 'name']):
        try:
            if (pid and proc.info['pid'] == pid) or (name and name.lower() in proc.info['name'].lower()):
                proc.kill()
                killed.append({"pid": proc.info['pid'], "name": proc.info['name']})
        except (psutil.NoSuchProcess, psutil.AccessDenied) as e:
            errors.append(str(e))

    return {"success": len(killed) > 0, "killed": killed, "errors": errors}


@tool(description="Gerencia serviços Windows (iniciar, parar, reiniciar, status).", category=ToolCategory.SYSTEM)
def manage_service(action: str, service_name: str) -> dict:
    """Controla serviços: start, stop, restart, status, enable, disable."""
    valid_actions = ["start", "stop", "restart", "status", "enable", "disable"]
    if action not in valid_actions:
        return {"success": False, "message": f"Ação inválida. Use: {', '.join(valid_actions)}"}

    cmd_map = {
        "start": f"Start-Service -Name '{service_name}'",
        "stop": f"Stop-Service -Name '{service_name}' -Force",
        "restart": f"Restart-Service -Name '{service_name}' -Force",
        "status": f"Get-Service -Name '{service_name}' | Select-Object Name, Status, StartType",
        "enable": f"Set-Service -Name '{service_name}' -StartupType Automatic",
        "disable": f"Set-Service -Name '{service_name}' -StartupType Disabled",
    }

    result = _run_powershell(cmd_map[action], admin=True)
    return {"success": result["success"], "message": result.get("stdout") or result.get("stderr") or "OK"}


# ==================== REDE E CONECTIVIDADE ====================

@tool(description="Mostra adaptadores de rede e IPs.", category=ToolCategory.SYSTEM)
def network_info() -> dict:
    """Informações completas de rede."""
    try:
        addrs = psutil.net_if_addrs()
        stats = psutil.net_if_stats()
        io = psutil.net_io_counters(pernic=True)

        interfaces = []
        for name, addr_list in addrs.items():
            iface = {"name": name, "addresses": [], "stats": {}, "io": {}}
            for addr in addr_list:
                iface["addresses"].append({
                    "family": str(addr.family),
                    "address": addr.address,
                    "netmask": addr.netmask,
                    "broadcast": addr.broadcast
                })
            if name in stats:
                s = stats[name]
                iface["stats"] = {"is_up": s.isup, "speed": s.speed, "mtu": s.mtu}
            if name in io:
                i = io[name]
                iface["io"] = {"bytes_sent": i.bytes_sent, "bytes_recv": i.bytes_recv}
            interfaces.append(iface)

        # Conexões ativas
        conns = []
        for conn in psutil.net_connections(kind='inet'):
            if conn.status == 'ESTABLISHED':
                conns.append({
                    "local": f"{conn.laddr.ip}:{conn.laddr.port}" if conn.laddr else "N/A",
                    "remote": f"{conn.raddr.ip}:{conn.raddr.port}" if conn.raddr else "N/A",
                    "status": conn.status,
                    "pid": conn.pid
                })

        return {"success": True, "interfaces": interfaces, "connections": conns[:20]}
    except Exception as e:
        return {"success": False, "message": str(e)}


@tool(description="Testa conectividade (ping, porta, DNS).", category=ToolCategory.SYSTEM)
def network_test(target: str, port: int = None, test_type: str = "ping") -> dict:
    """Testa rede: ping, tcp_port, dns, trace."""
    if test_type == "ping":
        result = _run_cmd(["ping", "-n", "4", target])
    elif test_type == "tcp_port":
        if not port:
            return {"success": False, "message": "Porta obrigatória para tcp_port"}
        ps_cmd = f"Test-NetConnection -ComputerName '{target}' -Port {port}"
        result = _run_powershell(ps_cmd)
    elif test_type == "dns":
        result = _run_powershell(f"Resolve-DnsName '{target}'")
    elif test_type == "trace":
        result = _run_cmd(["tracert", target])
    else:
        return {"success": False, "message": "Tipos: ping, tcp_port, dns, trace"}

    return {"success": result["success"], "output": result.get("stdout") or result.get("stderr")}


# ==================== ENERGIA E SISTEMA ====================

@tool(description="Controla energia: desligar, reiniciar, hibernar, suspender, bloquear.", category=ToolCategory.SYSTEM, dangerous=True, confirmation_message="Isso vai alterar o estado de energia do PC. Confirmar?")
def power_control(action: str, delay_seconds: int = 0) -> dict:
    """Ações: shutdown, restart, hibernate, sleep, lock, logoff."""
    actions = {
        "shutdown": f"shutdown /s /t {delay_seconds} /f",
        "restart": f"shutdown /r /t {delay_seconds} /f",
        "hibernate": "shutdown /h",
        "sleep": "rundll32.exe powrprof.dll,SetSuspendState 0,1,0",
        "lock": "rundll32.exe user32.dll,LockWorkStation",
        "logoff": "shutdown /l",
        "cancel": "shutdown /a",
    }

    if action not in actions:
        return {"success": False, "message": f"Ações válidas: {', '.join(actions.keys())}"}

    if action in ["sleep", "hibernate", "lock", "logoff"]:
        result = _run_cmd(actions[action].split())
    else:
        result = _run_cmd(["cmd", "/c", actions[action]])

    return {"success": result["success"], "message": f"Comando {action} enviado"}


@tool(description="Executa comando PowerShell arbitrário (com ou sem admin).", category=ToolCategory.SYSTEM, dangerous=True, confirmation_message="Executar comando PowerShell arbitrário? CUIDADO: poder total sobre o sistema.")
def run_powershell(command: str, as_admin: bool = False) -> dict:
    """Executa qualquer comando PowerShell. Use com extrema cautela."""
    result = _run_powershell(command, admin=as_admin)
    return {
        "success": result["success"],
        "stdout": result.get("stdout", "")[:5000],
        "stderr": result.get("stderr", "")[:2000],
        "returncode": result.get("returncode")
    }


# ==================== ARQUIVOS E REGISTRO ====================

@tool(description="Busca arquivos no sistema (fora do projeto JARVIS). Requer admin para pastas protegidas.", category=ToolCategory.FILESYSTEM)
def search_files(pattern: str, path: str = "C:\\", max_results: int = 100) -> dict:
    """Busca arquivos por padrão (wildcard *)."""
    try:
        results = []
        search_path = Path(path)
        if not search_path.exists():
            return {"success": False, "message": "Caminho não existe"}

        # Usa PowerShell para busca rápida
        ps_cmd = f"Get-ChildItem -Path '{path}' -Recurse -Filter '{pattern}' -ErrorAction SilentlyContinue | Select-Object -First {max_results} FullName, Length, LastWriteTime, Attributes | ConvertTo-Json -Compress"
        result = _run_powershell(ps_cmd, admin=True)

        if result["success"] and result["stdout"]:
            import json
            files = json.loads(result["stdout"])
            if isinstance(files, dict):
                files = [files]
            return {"success": True, "count": len(files), "files": files}

        return {"success": False, "message": "Nenhum arquivo encontrado ou erro na busca"}
    except Exception as e:
        return {"success": False, "message": str(e)}


@tool(description="Lê/Escreve chave do Registro do Windows.", category=ToolCategory.SYSTEM, dangerous=True, confirmation_message="Modificar o Registro do Windows pode afetar a estabilidade do sistema. Confirmar?")
def registry_edit(action: str, path: str, name: str = "", value: str = "", reg_type: str = "REG_SZ") -> dict:
    """Registro: read, write, delete, list. Path ex: HKLM\\Software\\MinhasChaves"""
    try:
        # Parse hive
        hives = {
            "HKLM": winreg.HKEY_LOCAL_MACHINE,
            "HKCU": winreg.HKEY_CURRENT_USER,
            "HKCR": winreg.HKEY_CLASSES_ROOT,
            "HKU": winreg.HKEY_USERS,
            "HKCC": winreg.HKEY_CURRENT_CONFIG,
        }

        parts = path.split("\\", 1)
        if len(parts) != 2 or parts[0] not in hives:
            return {"success": False, "message": "Path inválido. Use HKLM\\Software\\..."}

        hive = hives[parts[0]]
        subkey = parts[1]

        if action == "read":
            with winreg.OpenKey(hive, subkey, 0, winreg.KEY_READ) as key:
                val, vtype = winreg.QueryValueEx(key, name) if name else (None, None)
                return {"success": True, "value": val, "type": vtype}

        elif action == "write":
            with winreg.CreateKey(hive, subkey) as key:
                if reg_type == "REG_DWORD":
                    winreg.SetValueEx(key, name, 0, winreg.REG_DWORD, int(value))
                elif reg_type == "REG_QWORD":
                    winreg.SetValueEx(key, name, 0, winreg.REG_QWORD, int(value))
                elif reg_type == "REG_MULTI_SZ":
                    winreg.SetValueEx(key, name, 0, winreg.REG_MULTI_SZ, value.split("\n"))
                elif reg_type == "REG_EXPAND_SZ":
                    winreg.SetValueEx(key, name, 0, winreg.REG_EXPAND_SZ, value)
                else:
                    winreg.SetValueEx(key, name, 0, winreg.REG_SZ, value)
            return {"success": True, "message": "Valor escrito"}

        elif action == "delete":
            with winreg.OpenKey(hive, subkey, 0, winreg.KEY_WRITE) as key:
                winreg.DeleteValue(key, name)
            return {"success": True, "message": "Valor deletado"}

        elif action == "list":
            with winreg.OpenKey(hive, subkey, 0, winreg.KEY_READ) as key:
                values = []
                i = 0
                while True:
                    try:
                        n, v, t = winreg.EnumValue(key, i)
                        values.append({"name": n, "value": v, "type": t})
                        i += 1
                    except OSError:
                        break
            return {"success": True, "values": values}

        else:
            return {"success": False, "message": "Ações: read, write, delete, list"}

    except Exception as e:
        return {"success": False, "message": str(e)}


# ==================== HARDWARE E MONITORAMENTO ====================

@tool(description="Informações detalhadas de hardware (CPU, RAM, Disco, GPU).", category=ToolCategory.SYSTEM)
def hardware_info() -> dict:
    """Info completa de hardware."""
    try:
        # CPU
        cpu_info = {
            "physical_cores": psutil.cpu_count(logical=False),
            "logical_cores": psutil.cpu_count(logical=True),
            "frequency": psutil.cpu_freq()._asdict() if psutil.cpu_freq() else {},
            "usage_percent": psutil.cpu_percent(interval=1, percpu=True),
            "load_avg": os.getloadavg() if hasattr(os, 'getloadavg') else None,
        }

        # Memória
        mem = psutil.virtual_memory()
        swap = psutil.swap_memory()
        memory_info = {
            "total_gb": round(mem.total / (1024**3), 2),
            "available_gb": round(mem.available / (1024**3), 2),
            "used_percent": mem.percent,
            "swap_total_gb": round(swap.total / (1024**3), 2),
            "swap_used_percent": swap.percent,
        }

        # Discos
        disks = []
        for part in psutil.disk_partitions():
            try:
                usage = psutil.disk_usage(part.mountpoint)
                disks.append({
                    "device": part.device,
                    "mountpoint": part.mountpoint,
                    "fstype": part.fstype,
                    "total_gb": round(usage.total / (1024**3), 2),
                    "used_gb": round(usage.used / (1024**3), 2),
                    "free_gb": round(usage.free / (1024**3), 2),
                    "percent": round(usage.used / usage.total * 100, 1)
                })
            except PermissionError:
                continue

        # GPU (via WMI)
        gpu_result = _run_powershell("Get-CimInstance Win32_VideoController | Select-Object Name, AdapterRAM, DriverVersion, VideoProcessor | ConvertTo-Json")
        gpus = []
        if gpu_result["success"] and gpu_result["stdout"]:
            import json
            gpu_data = json.loads(gpu_result["stdout"])
            if isinstance(gpu_data, dict):
                gpu_data = [gpu_data]
            for g in gpu_data:
                gpus.append({
                    "name": g.get("Name"),
                    "vram_gb": round(g.get("AdapterRAM", 0) / (1024**3), 2) if g.get("AdapterRAM") else None,
                    "driver": g.get("DriverVersion"),
                    "processor": g.get("VideoProcessor")
                })

        # Temperaturas (se disponível)
        temps = {}
        try:
            for name, entries in psutil.sensors_temperatures().items():
                temps[name] = [{"label": e.label, "current": e.current, "high": e.high, "critical": e.critical} for e in entries]
        except:
            pass

        return {
            "success": True,
            "cpu": cpu_info,
            "memory": memory_info,
            "disks": disks,
            "gpus": gpus,
            "temperatures": temps
        }
    except Exception as e:
        return {"success": False, "message": str(e)}


# ==================== AUTOMAÇÃO AVANÇADA ====================

@tool(description="Simula teclas/mouse (via pyautogui).", category=ToolCategory.SYSTEM)
def simulate_input(action: str, **kwargs) -> dict:
    """Ações: click, double_click, right_click, type, key, hotkey, move, scroll, screenshot."""
    try:
        import pyautogui
        pyautogui.FAILSAFE = True

        if action == "click":
            pyautogui.click(kwargs.get("x"), kwargs.get("y"), button=kwargs.get("button", "left"))
        elif action == "double_click":
            pyautogui.doubleClick(kwargs.get("x"), kwargs.get("y"))
        elif action == "right_click":
            pyautogui.rightClick(kwargs.get("x"), kwargs.get("y"))
        elif action == "type":
            pyautogui.write(kwargs.get("text", ""), interval=kwargs.get("interval", 0.01))
        elif action == "key":
            pyautogui.press(kwargs.get("key"))
        elif action == "hotkey":
            pyautogui.hotkey(*kwargs.get("keys", []))
        elif action == "move":
            pyautogui.moveTo(kwargs.get("x"), kwargs.get("y"), duration=kwargs.get("duration", 0.25))
        elif action == "scroll":
            pyautogui.scroll(kwargs.get("clicks", 3), x=kwargs.get("x"), y=kwargs.get("y"))
        elif action == "screenshot":
            path = kwargs.get("path", "screenshot.png")
            pyautogui.screenshot(path)
            return {"success": True, "message": f"Screenshot salvo em {path}"}
        elif action == "position":
            x, y = pyautogui.position()
            return {"success": True, "x": x, "y": y}
        else:
            return {"success": False, "message": "Ações: click, double_click, right_click, type, key, hotkey, move, scroll, screenshot, position"}

        return {"success": True, "message": f"Ação {action} executada"}
    except Exception as e:
        return {"success": False, "message": str(e)}


@tool(description="Gerencia janelas (listar, focar, minimizar, maximizar, fechar, mover, redimensionar).", category=ToolCategory.SYSTEM)
def window_control(action: str, title: str = "", **kwargs) -> dict:
    """Controla janelas por título."""
    try:
        import pygetwindow as gw

        windows = gw.getWindowsWithTitle(title) if title else gw.getAllWindows()
        if not windows:
            return {"success": False, "message": "Nenhuma janela encontrada"}

        win = windows[0]
        results = []

        for w in windows[:5]:  # Limita a 5 janelas
            try:
                if action == "list":
                    results.append({"title": w.title, "left": w.left, "top": w.top, "width": w.width, "height": w.height, "visible": w.visible, "minimized": w.isMinimized, "maximized": w.isMaximized})
                elif action == "focus":
                    w.activate()
                    results.append({"title": w.title, "action": "focused"})
                elif action == "minimize":
                    w.minimize()
                    results.append({"title": w.title, "action": "minimized"})
                elif action == "maximize":
                    w.maximize()
                    results.append({"title": w.title, "action": "maximized"})
                elif action == "restore":
                    w.restore()
                    results.append({"title": w.title, "action": "restored"})
                elif action == "close":
                    w.close()
                    results.append({"title": w.title, "action": "closed"})
                elif action == "move":
                    w.moveTo(kwargs.get("x", 0), kwargs.get("y", 0))
                    results.append({"title": w.title, "action": "moved"})
                elif action == "resize":
                    w.resizeTo(kwargs.get("width", 800), kwargs.get("height", 600))
                    results.append({"title": w.title, "action": "resized"})
                else:
                    return {"success": False, "message": "Ações: list, focus, minimize, maximize, restore, close, move, resize"}
            except Exception as e:
                results.append({"title": w.title, "error": str(e)})

        return {"success": True, "windows": results}
    except Exception as e:
        return {"success": False, "message": str(e)}


# ==================== EXPORT ====================

AVAILABLE_FUNCTIONS = {
    "list_processes": list_processes,
    "kill_process": kill_process,
    "manage_service": manage_service,
    "network_info": network_info,
    "network_test": network_test,
    "power_control": power_control,
    "run_powershell": run_powershell,
    "search_files": search_files,
    "registry_edit": registry_edit,
    "hardware_info": hardware_info,
    "simulate_input": simulate_input,
    "window_control": window_control,
}

DANGEROUS = {"kill_process", "power_control", "run_powershell", "registry_edit"}
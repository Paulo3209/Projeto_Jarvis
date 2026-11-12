"""
Descoberta de aparelhos na rede Wi-Fi/local (somente a sua sub-rede).

1. Ping rápido em paralelo na sub-rede /24 do PC (popula a tabela ARP)
2. Lê a tabela ARP do Windows (IP + MAC)
3. Resolve nomes (DNS reverso / NetBIOS) e testa portas de controle conhecidas:
   5555 = ADB (Android com depuração Wi-Fi), 22 = SSH, 8123 = Home Assistant, 8009 = Chromecast
"""
from __future__ import annotations

import asyncio
import ipaddress
import re
import socket
import subprocess

from core.plugin_system import tool, ToolCategory

CONTROL_PORTS = {5555: "adb", 22: "ssh", 8123: "home_assistant", 8009: "chromecast", 80: "web"}


def _local_ip() -> str:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))  # não envia nada; só escolhe a interface
        return s.getsockname()[0]
    finally:
        s.close()


async def _ping(ip: str, sem: asyncio.Semaphore) -> None:
    async with sem:
        try:
            proc = await asyncio.create_subprocess_exec(
                "ping", "-n", "1", "-w", "350", ip,
                stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            await asyncio.wait_for(proc.wait(), timeout=2)
        except Exception:
            pass


def _gateway() -> str:
    try:
        out = subprocess.run(
            ["powershell.exe", "-NoProfile", "-Command",
             "(Get-NetRoute -DestinationPrefix 0.0.0.0/0 | Sort-Object RouteMetric | Select-Object -First 1).NextHop"],
            capture_output=True, text=True, timeout=10,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout.strip()
        return out.splitlines()[0] if out else ""
    except Exception:
        return ""


def _arp_table(net: ipaddress.IPv4Network) -> dict[str, str]:
    out = subprocess.run(["arp", "-a"], capture_output=True, text=True, encoding="latin-1",
                         creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout
    table = {}
    for ip, mac in re.findall(r"(\d+\.\d+\.\d+\.\d+)\s+([0-9a-f]{2}(?:-[0-9a-f]{2}){5})", out, re.I):
        try:
            addr = ipaddress.ip_address(ip)
        except ValueError:
            continue
        if addr in net and not mac.lower().startswith(("ff-ff", "01-00-5e")) and ip != str(net.broadcast_address):
            table[ip] = mac.upper()
    return table


def _hostname(ip: str) -> str:
    try:
        return socket.gethostbyaddr(ip)[0].split(".")[0]
    except Exception:
        return ""


async def _open_ports(ip: str) -> list[str]:
    found = []

    async def probe(port, label):
        try:
            _, w = await asyncio.wait_for(asyncio.open_connection(ip, port), timeout=0.6)
            w.close()
            found.append(label)
        except Exception:
            pass
    await asyncio.gather(*(probe(p, l) for p, l in CONTROL_PORTS.items()))
    return sorted(found)


@tool(description="Lista os aparelhos conectados na rede Wi-Fi/local (IP, nome, MAC e se aceitam ADB/SSH).",
      category=ToolCategory.SYSTEM)
async def lan_devices() -> dict:
    my_ip = _local_ip()
    net = ipaddress.ip_network(f"{my_ip}/24", strict=False)
    sem = asyncio.Semaphore(64)
    await asyncio.gather(*(_ping(str(h), sem) for h in net.hosts() if str(h) != my_ip))
    table = _arp_table(net)

    loop = asyncio.get_running_loop()
    ips = sorted(table, key=lambda x: ipaddress.ip_address(x))
    names = await asyncio.gather(*(loop.run_in_executor(None, _hostname, ip) for ip in ips))
    ports = await asyncio.gather(*(_open_ports(ip) for ip in ips))
    gateway = _gateway()

    devices = []
    for ip, name, prt in zip(ips, names, ports):
        mac = table[ip]
        if ip == gateway:
            kind = "roteador"
        elif "adb" in prt:
            kind = "android (ADB ativo)"
        elif name.upper().startswith(("DESKTOP-", "LAPTOP-", "PC-", "NOTEBOOK")):
            kind = "computador"
        elif mac[1].upper() in "26AE":
            # MAC "localmente administrado" = endereço privado/aleatório (Android 10+, iOS 14+)
            kind = "provável celular/tablet"
        else:
            kind = ""
        devices.append({"ip": ip, "name": name or "", "mac": mac, "control": prt, "kind": kind})
    return {
        "success": True,
        "network": str(net),
        "this_pc": my_ip,
        "count": len(devices),
        "devices": devices,
        "message": f"{len(devices)} aparelho(s) encontrados em {net}.",
    }

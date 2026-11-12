"""
Android Device Manager - ADB control for Android devices.
Handles shell commands, file transfer, app control, screen capture, input simulation.
"""
from __future__ import annotations
import asyncio
import logging
import os
import re
import subprocess
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Optional, List, Dict

from .manager import Device, DeviceType, ConnectionProtocol, DeviceStatus, DeviceCapability

logger = logging.getLogger(__name__)


@dataclass
class AndroidDevice:
    """Represents an Android device connected via ADB."""
    serial: str
    model: str = ""
    manufacturer: str = ""
    android_version: str = ""
    sdk_version: str = ""
    status: str = "unknown"
    last_seen: datetime = field(default_factory=datetime.now)


class ADBManager:
    """
    Manages ADB connections to Android devices.
    Provides high-level interface for device control.
    """

    def __init__(self, adb_path: str = "adb"):
        self.adb_path = adb_path
        self._devices_cache: Dict[str, AndroidDevice] = {}
        self._server_started = False

    async def _run_adb(self, args: List[str], serial: str = None, timeout: float = 30.0) -> Dict:
        """Run ADB command and return result."""
        cmd = [self.adb_path]
        if serial:
            cmd.extend(['-s', serial])
        cmd.extend(args)

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)

            return {
                "success": proc.returncode == 0,
                "returncode": proc.returncode,
                "stdout": stdout.decode('utf-8', errors='ignore').strip(),
                "stderr": stderr.decode('utf-8', errors='ignore').strip()
            }
        except asyncio.TimeoutError:
            return {"success": False, "error": "ADB command timeout"}
        except Exception as e:
            return {"success": False, "error": f"ADB error: {e}"}

    async def start_server(self) -> bool:
        """Start ADB server."""
        if self._server_started:
            return True

        result = await self._run_adb(['start-server'])
        if result['success']:
            self._server_started = True
        return result['success']

    async def kill_server(self) -> bool:
        """Kill ADB server."""
        result = await self._run_adb(['kill-server'])
        self._server_started = False
        return result['success']

    async def list_devices(self) -> List[AndroidDevice]:
        """List all connected ADB devices."""
        result = await self._run_adb(['devices', '-l'])
        if not result['success']:
            return []

        devices = []
        for line in result['stdout'].split('\n')[1:]:  # Skip header
            line = line.strip()
            if not line:
                continue

            # Parse: serial status key=value ...
            parts = line.split()
            if len(parts) < 2:
                continue

            serial = parts[0]
            status = parts[1]

            # Parse properties
            props = {}
            for part in parts[2:]:
                if ':' in part:
                    k, v = part.split(':', 1)
                    props[k] = v

            device = AndroidDevice(
                serial=serial,
                model=props.get('model', ''),
                manufacturer=props.get('product', ''),
                status=status
            )
            devices.append(device)
            self._devices_cache[serial] = device

        return devices

    async def get_device_info(self, serial: str) -> Optional[AndroidDevice]:
        """Get detailed device information."""
        device = self._devices_cache.get(serial)
        if not device:
            devices = await self.list_devices()
            device = next((d for d in devices if d.serial == serial), None)

        if not device:
            return None

        # Get additional properties
        props_result = await self._run_adb(['shell', 'getprop'], serial=serial)
        if props_result['success']:
            for line in props_result['stdout'].split('\n'):
                line = line.strip()
                if line.startswith('[') and ']:' in line:
                    key = line[1:line.index(']')]
                    value = line[line.index(']:')+2:].strip('"')
                    if key == 'ro.product.model':
                        device.model = value
                    elif key == 'ro.product.manufacturer':
                        device.manufacturer = value
                    elif key == 'ro.build.version.release':
                        device.android_version = value
                    elif key == 'ro.build.version.sdk':
                        device.sdk_version = value

        device.last_seen = datetime.now()
        return device

    # ===== Shell Commands =====

    async def shell(self, serial: str, command: str, timeout: float = 30.0) -> Dict:
        """Execute shell command on device."""
        return await self._run_adb(['shell', command], serial=serial, timeout=timeout)

    async def shell_stream(self, serial: str, command: str) -> asyncio.subprocess.Process:
        """Start streaming shell command."""
        cmd = [self.adb_path, '-s', serial, 'shell', command]
        return await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )

    # ===== File Transfer =====

    async def push(self, serial: str, local_path: str, remote_path: str) -> Dict:
        """Push file to device."""
        return await self._run_adb(['push', local_path, remote_path], serial=serial)

    async def pull(self, serial: str, remote_path: str, local_path: str) -> Dict:
        """Pull file from device."""
        return await self._run_adb(['pull', remote_path, local_path], serial=serial)

    async def list_files(self, serial: str, path: str = "/sdcard") -> Dict:
        """List files on device."""
        result = await self._run_adb(['shell', f'ls -la "{path}"'], serial=serial)
        if result['success']:
            files = []
            for line in result['stdout'].split('\n')[1:]:
                parts = line.split()
                if len(parts) >= 9:
                    files.append({
                        'permissions': parts[0],
                        'owner': parts[2],
                        'group': parts[3],
                        'size': parts[4],
                        'date': f"{parts[5]} {parts[6]}",
                        'name': ' '.join(parts[8:])
                    })
            result['files'] = files
        return result

    # ===== App Management =====

    async def install_app(self, serial: str, apk_path: str, options: List[str] = None) -> Dict:
        """Install APK on device."""
        args = ['install']
        if options:
            args.extend(options)
        args.append(apk_path)
        return await self._run_adb(args, serial=serial, timeout=120.0)

    async def uninstall_app(self, serial: str, package_name: str, keep_data: bool = False) -> Dict:
        """Uninstall app from device."""
        args = ['uninstall']
        if keep_data:
            args.append('-k')
        args.append(package_name)
        return await self._run_adb(args, serial=serial)

    async def list_packages(self, serial: str, filter_str: str = None) -> Dict:
        """List installed packages."""
        args = ['shell', 'pm', 'list', 'packages']
        if filter_str:
            args.append(filter_str)
        result = await self._run_adb(args, serial=serial)
        if result['success']:
            packages = []
            for line in result['stdout'].split('\n'):
                if line.startswith('package:'):
                    packages.append(line[8:])
            result['packages'] = packages
        return result

    async def start_app(self, serial: str, package_name: str, activity: str = None) -> Dict:
        """Start an app."""
        if activity:
            component = f"{package_name}/{activity}"
        else:
            # Try to get main activity
            result = await self._run_adb(
                ['shell', 'cmd', 'package', 'resolve-activity', '--brief', package_name],
                serial=serial
            )
            if result['success'] and result['stdout']:
                component = result['stdout'].strip()
            else:
                component = package_name

        return await self._run_adb(['shell', 'am', 'start', '-n', component], serial=serial)

    async def stop_app(self, serial: str, package_name: str) -> Dict:
        """Force stop an app."""
        return await self._run_adb(['shell', 'am', 'force-stop', package_name], serial=serial)

    async def clear_app_data(self, serial: str, package_name: str) -> Dict:
        """Clear app data."""
        return await self._run_adb(['shell', 'pm', 'clear', package_name], serial=serial)

    # ===== Screen & Input =====

    async def screencap(self, serial: str, local_path: str = None) -> Dict:
        """Capture screen to file."""
        remote_path = "/sdcard/screencap.png"
        result = await self._run_adb(['shell', 'screencap', '-p', remote_path], serial=serial)
        if not result['success']:
            return result

        if local_path:
            pull_result = await self.pull(serial, remote_path, local_path)
            await self._run_adb(['shell', 'rm', remote_path], serial=serial)
            return pull_result

        return {"success": True, "remote_path": remote_path}

    async def screenrecord(
        self,
        serial: str,
        local_path: str,
        duration: int = 30,
        bit_rate: int = 4000000,
        size: str = None
    ) -> Dict:
        """Record screen video."""
        remote_path = "/sdcard/screenrecord.mp4"
        args = ['shell', 'screenrecord', '--time-limit', str(duration), '--bit-rate', str(bit_rate)]
        if size:
            args.extend(['--size', size])
        args.append(remote_path)

        result = await self._run_adb(args, serial=serial, timeout=duration + 10)
        if not result['success']:
            return result

        pull_result = await self.pull(serial, remote_path, local_path)
        await self._run_adb(['shell', 'rm', remote_path], serial=serial)
        return pull_result

    async def input_tap(self, serial: str, x: int, y: int) -> Dict:
        """Simulate tap at coordinates."""
        return await self._run_adb(['shell', 'input', 'tap', str(x), str(y)], serial=serial)

    async def input_swipe(
        self,
        serial: str,
        x1: int, y1: int,
        x2: int, y2: int,
        duration: int = 300
    ) -> Dict:
        """Simulate swipe gesture."""
        return await self._run_adb(
            ['shell', 'input', 'swipe', str(x1), str(y1), str(x2), str(y2), str(duration)],
            serial=serial
        )

    async def input_text(self, serial: str, text: str) -> Dict:
        """Input text (escapes spaces and special chars)."""
        # Escape for shell
        escaped = text.replace(' ', '%s').replace("'", "'\\''")
        return await self._run_adb(['shell', 'input', 'text', escaped], serial=serial)

    async def input_keyevent(self, serial: str, keycode: int) -> Dict:
        """Send key event."""
        return await self._run_adb(['shell', 'input', 'keyevent', str(keycode)], serial=serial)

    # Keycode constants
    KEYCODE_HOME = 3
    KEYCODE_BACK = 4
    KEYCODE_MENU = 82
    KEYCODE_POWER = 26
    KEYCODE_VOLUME_UP = 24
    KEYCODE_VOLUME_DOWN = 25
    KEYCODE_ENTER = 66
    KEYCODE_DPAD_UP = 19
    KEYCODE_DPAD_DOWN = 20
    KEYCODE_DPAD_LEFT = 21
    KEYCODE_DPAD_RIGHT = 22
    KEYCODE_DPAD_CENTER = 23

    # ===== System Info =====

    async def get_battery(self, serial: str) -> Dict:
        """Get battery info."""
        result = await self._run_adb(['shell', 'dumpsys', 'battery'], serial=serial)
        if result['success']:
            info = {}
            for line in result['stdout'].split('\n'):
                line = line.strip()
                if ':' in line:
                    key, value = line.split(':', 1)
                    info[key.strip().lower()] = value.strip()
            result['battery'] = info
        return result

    async def get_wifi_info(self, serial: str) -> Dict:
        """Get WiFi info."""
        return await self._run_adb(['shell', 'dumpsys', 'wifi'], serial=serial)

    async def get_memory_info(self, serial: str) -> Dict:
        """Get memory info."""
        return await self._run_adb(['shell', 'cat', '/proc/meminfo'], serial=serial)

    async def get_cpu_info(self, serial: str) -> Dict:
        """Get CPU info."""
        return await self._run_adb(['shell', 'cat', '/proc/cpuinfo'], serial=serial)

    # ===== Settings & Config =====

    async def set_setting(self, serial: str, namespace: str, key: str, value: str) -> Dict:
        """Set system setting (system, secure, global)."""
        return await self._run_adb(
            ['shell', 'settings', 'put', namespace, key, value],
            serial=serial
        )

    async def get_setting(self, serial: str, namespace: str, key: str) -> Dict:
        """Get system setting."""
        return await self._run_adb(
            ['shell', 'settings', 'get', namespace, key],
            serial=serial
        )

    # ===== Notifications =====

    async def send_notification(
        self,
        serial: str,
        title: str,
        text: str,
        package: str = "com.android.systemui"
    ) -> Dict:
        """Send notification via ADB."""
        cmd = [
            'shell', 'cmd', 'notification', 'post',
            '-t', title,
            'jarvis_notification', text
        ]
        return await self._run_adb(cmd, serial=serial)

    # ===== Device Control =====

    async def reboot(self, serial: str, mode: str = None) -> Dict:
        """Reboot device (normal, recovery, bootloader)."""
        args = ['reboot']
        if mode:
            args.append(mode)
        return await self._run_adb(args, serial=serial)

    async def root(self, serial: str) -> Dict:
        """Restart ADB as root (requires rooted device)."""
        return await self._run_adb(['root'], serial=serial)

    async def remount(self, serial: str) -> Dict:
        """Remount system partition as writable."""
        return await self._run_adb(['remount'], serial=serial)


# Global instance
_adb_manager: Optional[ADBManager] = None


def get_adb_manager(adb_path: str = "adb") -> ADBManager:
    """Get or create global ADBManager instance."""
    global _adb_manager
    if _adb_manager is None:
        _adb_manager = ADBManager(adb_path)
    return _adb_manager


# High-level async functions for tool integration
async def adb_list_devices() -> Dict:
    """List all connected ADB devices."""
    manager = get_adb_manager()
    devices = await manager.list_devices()
    return {
        "success": True,
        "devices": [
            {
                "serial": d.serial,
                "model": d.model,
                "manufacturer": d.manufacturer,
                "android_version": d.android_version,
                "sdk_version": d.sdk_version,
                "status": d.status
            }
            for d in devices
        ]
    }


async def adb_shell(serial: str, command: str) -> Dict:
    """Execute shell command on Android device."""
    manager = get_adb_manager()
    return await manager.shell(serial, command)


async def adb_install(serial: str, apk_path: str) -> Dict:
    """Install APK on device."""
    manager = get_adb_manager()
    return await manager.install_app(serial, apk_path)


async def adb_uninstall(serial: str, package_name: str) -> Dict:
    """Uninstall app."""
    manager = get_adb_manager()
    return await manager.uninstall_app(serial, package_name)


async def adb_screencap(serial: str, local_path: str = None) -> Dict:
    """Capture screen."""
    manager = get_adb_manager()
    return await manager.screencap(serial, local_path)


async def adb_input_tap(serial: str, x: int, y: int) -> Dict:
    """Tap screen."""
    manager = get_adb_manager()
    return await manager.input_tap(serial, x, y)


async def adb_input_swipe(serial: str, x1: int, y1: int, x2: int, y2: int, duration: int = 300) -> Dict:
    """Swipe screen."""
    manager = get_adb_manager()
    return await manager.input_swipe(serial, x1, y1, x2, y2, duration)


async def adb_input_text(serial: str, text: str) -> Dict:
    """Input text."""
    manager = get_adb_manager()
    return await manager.input_text(serial, text)


async def adb_input_key(serial: str, keycode: int) -> Dict:
    """Send key event."""
    manager = get_adb_manager()
    return await manager.input_keyevent(serial, keycode)


async def adb_start_app(serial: str, package_name: str, activity: str = None) -> Dict:
    """Start app."""
    manager = get_adb_manager()
    return await manager.start_app(serial, package_name, activity)


async def adb_stop_app(serial: str, package_name: str) -> Dict:
    """Stop app."""
    manager = get_adb_manager()
    return await manager.stop_app(serial, package_name)


async def adb_get_battery(serial: str) -> Dict:
    """Get battery info."""
    manager = get_adb_manager()
    return await manager.get_battery(serial)


async def adb_reboot(serial: str, mode: str = None) -> Dict:
    """Reboot device."""
    manager = get_adb_manager()
    return await manager.reboot(serial, mode)
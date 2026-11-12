"""
Network Agent - Agent that runs on remote devices to execute tasks.
Can be installed on computers, phones, TVs, and IoT devices.
"""
from __future__ import annotations
import asyncio
import json
import logging
import platform
import secrets
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

import websockets

logger = logging.getLogger(__name__)


class AgentStatus(Enum):
    """Agent status."""
    STARTING = "starting"
    RUNNING = "running"
    BUSY = "busy"
    STOPPING = "stopping"
    STOPPED = "stopped"
    ERROR = "error"


@dataclass
class AgentConfig:
    """Agent configuration."""
    controller_host: str = "localhost"
    controller_port: int = 8766
    device_name: str = ""
    device_type: str = "computer"
    role: str = "agent"
    capabilities: List[str] = field(default_factory=list)
    auto_reconnect: bool = True
    reconnect_interval: int = 5
    heartbeat_interval: int = 10
    ssl_enabled: bool = False
    auth_token: Optional[str] = None
    device_id: Optional[str] = None


@dataclass
class Task:
    """Task to execute."""
    task_id: str
    task_type: str
    payload: Dict
    request_id: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.now)


class NetworkAgent:
    """
    Agent that runs on remote devices.
    Connects to controller, executes tasks, reports status.
    """

    def __init__(self, config: Optional[AgentConfig] = None):
        self.config = config or AgentConfig()
        if not self.config.device_name:
            self.config.device_name = f"{platform.node()}-{self.config.device_type}"

        self._status = AgentStatus.STOPPED
        self._websocket: Optional[websockets.WebSocketClientProtocol] = None
        self._running = False
        self._task_handlers: Dict[str, Callable] = {}
        self._current_task: Optional[Task] = None
        self._task_queue: asyncio.Queue = asyncio.Queue()
        self._register_default_handlers()

    def _register_default_handlers(self) -> None:
        """Register default task handlers."""
        self._task_handlers = {
            "execute_tool": self._handle_execute_tool,
            "shell_command": self._handle_shell_command,
            "screen_capture": self._handle_screen_capture,
            "camera_capture": self._handle_camera_capture,
            "get_system_info": self._handle_get_system_info,
            "list_files": self._handle_list_files,
            "read_file": self._handle_read_file,
            "write_file": self._handle_write_file,
            "run_automation": self._handle_run_automation,
            "device_control": self._handle_device_control,
            "voice_input": self._handle_voice_input,
        }

    def register_handler(self, task_type: str, handler: Callable) -> None:
        """Register custom task handler."""
        self._task_handlers[task_type] = handler

    async def start(self) -> None:
        """Start the agent and connect to controller."""
        if self._running:
            return

        self._running = True
        self._status = AgentStatus.STARTING
        await self._connect()

    async def _connect(self) -> None:
        """Connect to controller."""
        uri = f"ws://{self.config.controller_host}:{self.config.controller_port}"
        if self.config.ssl_enabled:
            uri = f"wss://{self.config.controller_host}:{self.config.controller_port}"

        while self._running:
            try:
                logger.info(f"Connecting to controller at {uri}...")
                self._websocket = await websockets.connect(
                    uri,
                    max_size=10 * 1024 * 1024,
                    ping_interval=self.config.heartbeat_interval,
                    ping_timeout=10,
                )

                # Register with controller
                await self._register()

                self._status = AgentStatus.RUNNING
                logger.info("Connected to controller")

                # Start message loop
                await self._message_loop()

            except Exception as e:
                logger.error(f"Connection error: {e}")
                self._status = AgentStatus.ERROR

                if not self._running:
                    break

                if self.config.auto_reconnect:
                    logger.info(f"Reconnecting in {self.config.reconnect_interval}s...")
                    await asyncio.sleep(self.config.reconnect_interval)
                else:
                    break

    async def _register(self) -> None:
        """Register with controller."""
        import platform

        # Get system capabilities
        capabilities = self.config.capabilities.copy()
        capabilities.extend(self._detect_capabilities())

        device_id = self.config.device_id or str(uuid.uuid4())[:8]
        self.config.device_id = device_id

        await self._send_message({
            "type": "register",
            "device_id": device_id,
            "name": self.config.device_name,
            "role": self.config.role,
            "device_type": self.config.device_type,
            "platform": platform.system().lower(),
            "capabilities": capabilities,
            "auth_token": self.config.auth_token,
        })

    def _detect_capabilities(self) -> List[str]:
        """Detect device capabilities."""
        caps = []

        # Check for common capabilities
        try:
            import cv2
            caps.append("opencv")
        except ImportError:
            pass

        try:
            import mss
            caps.append("screen_capture")
        except ImportError:
            pass

        try:
            import pytesseract
            caps.append("ocr")
        except ImportError:
            pass

        try:
            import ultralytics
            caps.append("yolo")
        except ImportError:
            pass

        # Platform-specific
        if platform.system() == "Windows":
            caps.append("windows_automation")
        elif platform.system() == "Linux":
            caps.append("linux_automation")
        elif platform.system() == "Darwin":
            caps.append("macos_automation")

        return caps

    async def _message_loop(self) -> None:
        """Main message processing loop."""
        async for message in self._websocket:
            try:
                data = json.loads(message)
                await self._process_message(data)
            except json.JSONDecodeError:
                logger.error("Invalid JSON from controller")
            except Exception as e:
                logger.error(f"Message processing error: {e}")

    async def _process_message(self, data: Dict) -> None:
        """Process message from controller."""
        msg_type = data.get("type")

        if msg_type == "register_response":
            if data.get("success"):
                logger.info(f"Registered as {data.get('device_id')}")
            else:
                logger.error(f"Registration failed: {data.get('error')}")

        elif msg_type == "command":
            await self._handle_command(data)

        elif msg_type == "task_request":
            await self._handle_task_request(data)

        elif msg_type == "heartbeat":
            await self._handle_heartbeat()

        elif msg_type == "sync_response":
            # Handle sync if needed
            pass

        elif msg_type == "error":
            logger.error(f"Controller error: {data.get('error')}")

    async def _handle_command(self, data: Dict) -> None:
        """Handle direct command."""
        command = data.get("command")
        params = data.get("params", {})
        request_id = data.get("request_id")

        # Route to task handler if it's a task
        if command in self._task_handlers:
            await self._execute_task(command, params, request_id)
        else:
            # Generic command
            result = {"success": False, "error": f"Unknown command: {command}"}
            await self._send_result(request_id, result)

    async def _handle_task_request(self, data: Dict) -> None:
        """Handle task request."""
        task = Task(
            task_id=data.get("task_id"),
            task_type=data.get("task_type"),
            payload=data.get("payload", {}),
            request_id=data.get("request_id"),
        )
        await self._task_queue.put(task)

    async def _handle_heartbeat(self) -> None:
        """Respond to heartbeat."""
        await self._send_message({
            "type": "heartbeat",
            "device_id": self.config.device_id,
            "status": self._status.value,
            "assigned_tasks": [self._current_task.task_id] if self._current_task else [],
            "capabilities": self._detect_capabilities(),
        })

    async def _execute_task(self, task_type: str, params: Dict, request_id: Optional[str]) -> None:
        """Execute a task."""
        if self._status == AgentStatus.BUSY:
            await self._send_result(request_id, {"success": False, "error": "Agent busy"})
            return

        handler = self._task_handlers.get(task_type)
        if not handler:
            await self._send_result(request_id, {"success": False, "error": f"No handler for {task_type}"})
            return

        self._status = AgentStatus.BUSY
        self._current_task = Task(task_id=request_id or secrets.token_hex(8), task_type=task_type, payload=params)

        try:
            result = await handler(params)
            await self._send_result(request_id, result)
        except Exception as e:
            logger.error(f"Task execution error: {e}")
            await self._send_result(request_id, {"success": False, "error": str(e)})
        finally:
            self._status = AgentStatus.RUNNING
            self._current_task = None

    async def _send_result(self, request_id: Optional[str], result: Dict) -> None:
        """Send task result to controller."""
        if request_id:
            await self._send_message({
                "type": "task_result",
                "task_id": request_id,
                "result": result,
            })

    async def _send_message(self, message: Dict) -> None:
        """Send message to controller."""
        if self._websocket:
            try:
                await self._websocket.send(json.dumps(message))
            except Exception as e:
                logger.error(f"Send error: {e}")

    # Default task handlers
    async def _handle_execute_tool(self, params: Dict) -> Dict:
        """Execute a JARVIS tool."""
        tool_name = params.get("tool")
        arguments = params.get("arguments", {})

        # Try to import and execute tool
        try:
            from core.plugin_system import get_tool
            tool = get_tool(tool_name)
            if not tool:
                return {"success": False, "error": f"Tool not found: {tool_name}"}

            if tool.is_async:
                result = await tool.function(**arguments)
            else:
                result = tool.function(**arguments)
            return result
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def _handle_shell_command(self, params: Dict) -> Dict:
        """Execute shell command."""
        cmd = params.get("command")
        if not cmd:
            return {"success": False, "error": "Command required"}

        try:
            proc = await asyncio.create_subprocess_shell(
                cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()
            return {
                "success": proc.returncode == 0,
                "returncode": proc.returncode,
                "stdout": stdout.decode() if stdout else "",
                "stderr": stderr.decode() if stderr else "",
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def _handle_screen_capture(self, params: Dict) -> Dict:
        """Capture screen."""
        try:
            import mss
            import base64

            monitor = params.get("monitor", 0)
            with mss.mss() as sct:
                screenshot = sct.grab(sct.monitors[monitor])
                img_bytes = mss.tools.to_png(screenshot.rgb, screenshot.size)
                img_base64 = base64.b64encode(img_bytes).decode()

            return {
                "success": True,
                "image": img_base64,
                "width": screenshot.width,
                "height": screenshot.height,
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def _handle_camera_capture(self, params: Dict) -> Dict:
        """Capture from camera."""
        try:
            import cv2
            import base64

            camera_index = params.get("camera", 0)
            cap = cv2.VideoCapture(camera_index)
            ret, frame = cap.read()
            cap.release()

            if not ret:
                return {"success": False, "error": "Failed to capture frame"}

            _, buffer = cv2.imencode('.jpg', frame)
            img_base64 = base64.b64encode(buffer).decode()

            return {
                "success": True,
                "image": img_base64,
                "format": "jpg",
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def _handle_get_system_info(self, params: Dict) -> Dict:
        """Get system information."""
        import platform
        import psutil

        return {
            "success": True,
            "system": platform.system(),
            "version": platform.version(),
            "machine": platform.machine(),
            "processor": platform.processor(),
            "cpu_count": psutil.cpu_count(),
            "memory_total": psutil.virtual_memory().total,
            "memory_available": psutil.virtual_memory().available,
            "disk_usage": psutil.disk_usage('/').percent if platform.system() != "Windows" else psutil.disk_usage('C:').percent,
        }

    async def _handle_list_files(self, params: Dict) -> Dict:
        """List files in directory."""
        import os

        path = params.get("path", ".")
        try:
            files = []
            for entry in os.scandir(path):
                files.append({
                    "name": entry.name,
                    "is_dir": entry.is_dir(),
                    "size": entry.stat().st_size if entry.is_file() else 0,
                })
            return {"success": True, "files": files}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def _handle_read_file(self, params: Dict) -> Dict:
        """Read file content."""
        path = params.get("path")
        if not path:
            return {"success": False, "error": "Path required"}

        try:
            with open(path, 'r', encoding='utf-8') as f:
                content = f.read()
            return {"success": True, "content": content}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def _handle_write_file(self, params: Dict) -> Dict:
        """Write file content."""
        path = params.get("path")
        content = params.get("content", "")
        if not path:
            return {"success": False, "error": "Path required"}

        try:
            with open(path, 'w', encoding='utf-8') as f:
                f.write(content)
            return {"success": True}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def _handle_run_automation(self, params: Dict) -> Dict:
        """Run automation workflow."""
        # This would integrate with agents.executor
        return {"success": False, "error": "Automation execution not implemented in agent"}

    async def _handle_device_control(self, params: Dict) -> Dict:
        """Control local device hardware."""
        action = params.get("action")
        if action == "volume":
            # Platform-specific volume control
            return {"success": False, "error": "Not implemented"}
        elif action == "brightness":
            return {"success": False, "error": "Not implemented"}
        elif action == "power":
            return {"success": False, "error": "Not implemented"}
        return {"success": False, "error": f"Unknown action: {action}"}

    async def _handle_voice_input(self, params: Dict) -> Dict:
        """Process voice input locally."""
        # This would use local STT if available
        return {"success": False, "error": "Local voice processing not implemented"}

    async def stop(self) -> None:
        """Stop the agent."""
        self._running = False
        self._status = AgentStatus.STOPPING

        if self._websocket:
            await self._websocket.close()

        self._status = AgentStatus.STOPPED
        logger.info("Agent stopped")

    @property
    def status(self) -> AgentStatus:
        return self._status

    @property
    def is_running(self) -> bool:
        return self._running


async def run_agent(config: Optional[AgentConfig] = None) -> NetworkAgent:
    """Create and start agent."""
    agent = NetworkAgent(config)
    await agent.start()
    return agent
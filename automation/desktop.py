"""
Desktop Automation - pyautogui-based window, keyboard, mouse control.
Cross-platform desktop automation for Windows/Linux/Mac.
"""
from __future__ import annotations
import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple, Union
from pathlib import Path

import pyautogui
import pygetwindow as gw

# Configure pyautogui
pyautogui.FAILSAFE = True  # Move mouse to corner to abort
pyautogui.PAUSE = 0.1  # Small delay between actions

logger = logging.getLogger(__name__)


@dataclass
class WindowInfo:
    """Window information."""
    title: str
    left: int
    top: int
    width: int
    height: int
    handle: int = 0
    is_active: bool = False
    is_maximized: bool = False
    is_minimized: bool = False


@dataclass
class Point:
    """Screen coordinate."""
    x: int
    y: int


@dataclass
class Region:
    """Screen region."""
    left: int
    top: int
    width: int
    height: int

    def to_tuple(self) -> Tuple[int, int, int, int]:
        return (self.left, self.top, self.width, self.height)

    def contains(self, x: int, y: int) -> bool:
        return (self.left <= x < self.left + self.width and
                self.top <= y < self.top + self.height)


class DesktopAutomation:
    """
    High-level desktop automation.
    Wraps pyautogui with async interface and safety features.
    """

    def __init__(self):
        self._screen_size = pyautogui.size()
        self._original_mouse_pos = None

    @property
    def screen_size(self) -> Tuple[int, int]:
        """Get screen resolution."""
        return self._screen_size

    # ===== Window Management =====

    def get_all_windows(self) -> List[WindowInfo]:
        """Get all visible windows."""
        windows = []
        for win in gw.getAllWindows():
            if win.visible and win.title.strip():
                windows.append(WindowInfo(
                    title=win.title,
                    left=win.left,
                    top=win.top,
                    width=win.width,
                    height=win.height,
                    handle=win._hWnd if hasattr(win, '_hWnd') else 0,
                    is_active=win.isActive,
                    is_maximized=win.isMaximized,
                    is_minimized=win.isMinimized
                ))
        return windows

    def get_window(self, title: str, exact: bool = False) -> Optional[WindowInfo]:
        """Find window by title."""
        for win in gw.getWindowsWithTitle(title):
            if win.visible:
                if exact and win.title != title:
                    continue
                return WindowInfo(
                    title=win.title,
                    left=win.left,
                    top=win.top,
                    width=win.width,
                    height=win.height,
                    handle=win._hWnd if hasattr(win, '_hWnd') else 0,
                    is_active=win.isActive,
                    is_maximized=win.isMaximized,
                    is_minimized=win.isMinimized
                )
        return None

    def activate_window(self, title: str) -> bool:
        """Activate window by title."""
        win = self.get_window(title)
        if win:
            try:
                gw.getWindowsWithTitle(title)[0].activate()
                return True
            except Exception as e:
                logger.error(f"Activate window error: {e}")
        return False

    def get_active_window(self) -> Optional[WindowInfo]:
        """Get currently active window."""
        try:
            win = gw.getActiveWindow()
            if win:
                return WindowInfo(
                    title=win.title,
                    left=win.left,
                    top=win.top,
                    width=win.width,
                    height=win.height,
                    is_active=True
                )
        except Exception:
            pass
        return None

    def move_window(self, title: str, x: int, y: int, width: int = None, height: int = None) -> bool:
        """Move and optionally resize window."""
        wins = gw.getWindowsWithTitle(title)
        if wins:
            try:
                win = wins[0]
                if width and height:
                    win.moveTo(x, y)
                    win.resizeTo(width, height)
                else:
                    win.moveTo(x, y)
                return True
            except Exception as e:
                logger.error(f"Move window error: {e}")
        return False

    def minimize_window(self, title: str) -> bool:
        wins = gw.getWindowsWithTitle(title)
        if wins:
            try:
                wins[0].minimize()
                return True
            except Exception:
                pass
        return False

    def maximize_window(self, title: str) -> bool:
        wins = gw.getWindowsWithTitle(title)
        if wins:
            try:
                wins[0].maximize()
                return True
            except Exception:
                pass
        return False

    def close_window(self, title: str) -> bool:
        wins = gw.getWindowsWithTitle(title)
        if wins:
            try:
                wins[0].close()
                return True
            except Exception:
                pass
        return False

    # ===== Mouse Control =====

    def get_mouse_position(self) -> Point:
        """Get current mouse position."""
        x, y = pyautogui.position()
        return Point(x, y)

    def move_mouse(self, x: int, y: int, duration: float = 0.25) -> bool:
        """Move mouse to absolute position."""
        try:
            pyautogui.moveTo(x, y, duration=duration)
            return True
        except Exception as e:
            logger.error(f"Move mouse error: {e}")
            return False

    def move_mouse_relative(self, dx: int, dy: int, duration: float = 0.25) -> bool:
        """Move mouse relative to current position."""
        try:
            pyautogui.moveRel(dx, dy, duration=duration)
            return True
        except Exception as e:
            logger.error(f"Move mouse relative error: {e}")
            return False

    def click(self, x: int = None, y: int = None, button: str = 'left', clicks: int = 1, interval: float = 0.1) -> bool:
        """Click at position (current if not specified)."""
        try:
            if x is not None and y is not None:
                pyautogui.click(x, y, button=button, clicks=clicks, interval=interval)
            else:
                pyautogui.click(button=button, clicks=clicks, interval=interval)
            return True
        except Exception as e:
            logger.error(f"Click error: {e}")
            return False

    def double_click(self, x: int = None, y: int = None, button: str = 'left') -> bool:
        return self.click(x, y, button=button, clicks=2)

    def right_click(self, x: int = None, y: int = None) -> bool:
        return self.click(x, y, button='right')

    def drag(self, x1: int, y1: int, x2: int, y2: int, duration: float = 0.5, button: str = 'left') -> bool:
        """Drag from (x1,y1) to (x2,y2)."""
        try:
            pyautogui.moveTo(x1, y1)
            pyautogui.dragTo(x2, y2, duration=duration, button=button)
            return True
        except Exception as e:
            logger.error(f"Drag error: {e}")
            return False

    def scroll(self, clicks: int, x: int = None, y: int = None) -> bool:
        """Scroll mouse wheel."""
        try:
            if x is not None and y is not None:
                pyautogui.moveTo(x, y)
            pyautogui.scroll(clicks)
            return True
        except Exception as e:
            logger.error(f"Scroll error: {e}")
            return False

    # ===== Keyboard Control =====

    def type_text(self, text: str, interval: float = 0.01) -> bool:
        """Type text."""
        try:
            pyautogui.write(text, interval=interval)
            return True
        except Exception as e:
            logger.error(f"Type text error: {e}")
            return False

    def press_key(self, key: str, presses: int = 1, interval: float = 0.0) -> bool:
        """Press key."""
        try:
            pyautogui.press(key, presses=presses, interval=interval)
            return True
        except Exception as e:
            logger.error(f"Press key error: {e}")
            return False

    def key_down(self, key: str) -> bool:
        try:
            pyautogui.keyDown(key)
            return True
        except Exception as e:
            logger.error(f"Key down error: {e}")
            return False

    def key_up(self, key: str) -> bool:
        try:
            pyautogui.keyUp(key)
            return True
        except Exception as e:
            logger.error(f"Key up error: {e}")
            return False

    def hotkey(self, *keys: str) -> bool:
        """Press key combination (e.g., 'ctrl', 'c')."""
        try:
            pyautogui.hotkey(*keys)
            return True
        except Exception as e:
            logger.error(f"Hotkey error: {e}")
            return False

    def hold_keys(self, keys: List[str], action: callable) -> bool:
        """Hold keys while executing action."""
        try:
            for key in keys:
                pyautogui.keyDown(key)
            try:
                action()
            finally:
                for key in reversed(keys):
                    pyautogui.keyUp(key)
            return True
        except Exception as e:
            logger.error(f"Hold keys error: {e}")
            return False

    # ===== Screen Capture =====

    def screenshot(self, region: Region = None, save_path: str = None) -> Any:
        """Take screenshot."""
        try:
            if region:
                img = pyautogui.screenshot(region=region.to_tuple())
            else:
                img = pyautogui.screenshot()

            if save_path:
                img.save(save_path)

            return img
        except Exception as e:
            logger.error(f"Screenshot error: {e}")
            return None

    def locate_on_screen(
        self,
        image_path: str,
        confidence: float = 0.8,
        region: Region = None,
        grayscale: bool = False
    ) -> Optional[Region]:
        """Find image on screen."""
        try:
            location = pyautogui.locateOnScreen(
                image_path,
                confidence=confidence,
                region=region.to_tuple() if region else None,
                grayscale=grayscale
            )
            if location:
                return Region(location.left, location.top, location.width, location.height)
        except Exception as e:
            logger.error(f"Locate on screen error: {e}")
        return None

    def locate_all_on_screen(
        self,
        image_path: str,
        confidence: float = 0.8,
        region: Region = None,
        grayscale: bool = False
    ) -> List[Region]:
        """Find all occurrences of image on screen."""
        try:
            locations = pyautogui.locateAllOnScreen(
                image_path,
                confidence=confidence,
                region=region.to_tuple() if region else None,
                grayscale=grayscale
            )
            return [Region(l.left, l.top, l.width, l.height) for l in locations]
        except Exception as e:
            logger.error(f"Locate all on screen error: {e}")
        return []

    def locate_center_on_screen(
        self,
        image_path: str,
        confidence: float = 0.8,
        region: Region = None,
        grayscale: bool = False
    ) -> Optional[Point]:
        """Find center of image on screen."""
        try:
            point = pyautogui.locateCenterOnScreen(
                image_path,
                confidence=confidence,
                region=region.to_tuple() if region else None,
                grayscale=grayscale
            )
            if point:
                return Point(point.x, point.y)
        except Exception as e:
            logger.error(f"Locate center on screen error: {e}")
        return None

    # ===== Pixel/Color =====

    def get_pixel_color(self, x: int, y: int) -> Tuple[int, int, int]:
        """Get pixel color at position."""
        return pyautogui.pixel(x, y)

    def pixel_matches_color(self, x: int, y: int, expected_color: Tuple[int, int, int], tolerance: int = 0) -> bool:
        """Check if pixel matches color."""
        return pyautogui.pixelMatchesColor(x, y, expected_color, tolerance=tolerance)

    # ===== Async Wrappers =====

    async def async_move_mouse(self, x: int, y: int, duration: float = 0.25) -> bool:
        return await asyncio.to_thread(self.move_mouse, x, y, duration)

    async def async_click(self, x: int = None, y: int = None, button: str = 'left', clicks: int = 1) -> bool:
        return await asyncio.to_thread(self.click, x, y, button, clicks)

    async def async_type_text(self, text: str, interval: float = 0.01) -> bool:
        return await asyncio.to_thread(self.type_text, text, interval)

    async def async_hotkey(self, *keys: str) -> bool:
        return await asyncio.to_thread(self.hotkey, *keys)

    async def async_screenshot(self, region: Region = None, save_path: str = None) -> Any:
        return await asyncio.to_thread(self.screenshot, region, save_path)

    async def async_locate(self, image_path: str, confidence: float = 0.8, region: Region = None) -> Optional[Region]:
        return await asyncio.to_thread(self.locate_on_screen, image_path, confidence, region)

    # ===== High-level Actions =====

    async def click_image(self, image_path: str, confidence: float = 0.8, button: str = 'left') -> bool:
        """Find and click image."""
        region = await self.async_locate(image_path, confidence)
        if region:
            center_x = region.left + region.width // 2
            center_y = region.top + region.height // 2
            return await self.async_click(center_x, center_y, button)
        return False

    async def wait_for_image(
        self,
        image_path: str,
        timeout: float = 10.0,
        confidence: float = 0.8,
        region: Region = None,
        interval: float = 0.5
    ) -> Optional[Region]:
        """Wait for image to appear on screen."""
        start = time.time()
        while time.time() - start < timeout:
            result = await self.async_locate(image_path, confidence, region)
            if result:
                return result
            await asyncio.sleep(interval)
        return None

    async def type_and_enter(self, text: str) -> bool:
        """Type text and press Enter."""
        await self.async_type_text(text)
        await asyncio.sleep(0.1)
        return await self.async_press_key('enter')

    async def async_press_key(self, key: str) -> bool:
        return await asyncio.to_thread(self.press_key, key)

    # ===== Safety =====

    def enable_failsafe(self, enabled: bool = True) -> None:
        """Enable/disable failsafe (move mouse to corner to abort)."""
        pyautogui.FAILSAFE = enabled

    def set_pause(self, pause: float) -> None:
        """Set delay between pyautogui actions."""
        pyautogui.PAUSE = pause

    def get_failsafe_status(self) -> bool:
        return pyautogui.FAILSAFE


# Global instance
_desktop_automation: Optional[DesktopAutomation] = None


def get_desktop_automation() -> DesktopAutomation:
    """Get or create global DesktopAutomation instance."""
    global _desktop_automation
    if _desktop_automation is None:
        _desktop_automation = DesktopAutomation()
    return _desktop_automation


# High-level async functions for tool integration
async def desk_list_windows() -> Dict:
    """List all visible windows."""
    auto = get_desktop_automation()
    windows = auto.get_all_windows()
    return {
        "success": True,
        "windows": [
            {
                "title": w.title,
                "position": {"x": w.left, "y": w.top},
                "size": {"width": w.width, "height": w.height},
                "active": w.is_active,
                "maximized": w.is_maximized,
                "minimized": w.is_minimized
            }
            for w in windows
        ]
    }


async def desk_activate_window(title: str) -> Dict:
    auto = get_desktop_automation()
    success = auto.activate_window(title)
    return {"success": success, "title": title}


async def desk_get_mouse_position() -> Dict:
    auto = get_desktop_automation()
    pos = auto.get_mouse_position()
    return {"success": True, "x": pos.x, "y": pos.y}


async def desk_move_mouse(x: int, y: int, duration: float = 0.25) -> Dict:
    auto = get_desktop_automation()
    success = await auto.async_move_mouse(x, y, duration)
    return {"success": success, "x": x, "y": y}


async def desk_click(x: int = None, y: int = None, button: str = 'left', clicks: int = 1) -> Dict:
    auto = get_desktop_automation()
    success = await auto.async_click(x, y, button, clicks)
    return {"success": success}


async def desk_type_text(text: str, interval: float = 0.01) -> Dict:
    auto = get_desktop_automation()
    success = await auto.async_type_text(text, interval)
    return {"success": success, "text": text}


async def desk_hotkey(*keys: str) -> Dict:
    auto = get_desktop_automation()
    success = await auto.async_hotkey(*keys)
    return {"success": success, "keys": list(keys)}


async def desk_screenshot(region: Dict = None, save_path: str = None) -> Dict:
    auto = get_desktop_automation()
    reg = Region(**region) if region else None
    img = await auto.async_screenshot(reg, save_path)
    return {
        "success": img is not None,
        "path": save_path,
        "size": {"width": img.width, "height": img.height} if img else None
    }


async def desk_locate_image(image_path: str, confidence: float = 0.8, region: Dict = None) -> Dict:
    auto = get_desktop_automation()
    reg = Region(**region) if region else None
    result = await auto.async_locate(image_path, confidence, reg)
    return {
        "success": result is not None,
        "found": result is not None,
        "region": {"left": result.left, "top": result.top, "width": result.width, "height": result.height} if result else None
    }


async def desk_click_image(image_path: str, confidence: float = 0.8) -> Dict:
    auto = get_desktop_automation()
    success = await auto.click_image(image_path, confidence)
    return {"success": success}


async def desk_wait_for_image(image_path: str, timeout: float = 10.0, confidence: float = 0.8) -> Dict:
    auto = get_desktop_automation()
    result = await auto.wait_for_image(image_path, timeout, confidence)
    return {
        "success": result is not None,
        "found": result is not None,
        "region": {"left": result.left, "top": result.top, "width": result.width, "height": result.height} if result else None
    }


async def desk_press_key(key: str) -> Dict:
    auto = get_desktop_automation()
    success = await auto.async_press_key(key)
    return {"success": success, "key": key}


async def desk_drag(x1: int, y1: int, x2: int, y2: int, duration: float = 0.5) -> Dict:
    auto = get_desktop_automation()
    success = await asyncio.to_thread(auto.drag, x1, y1, x2, y2, duration)
    return {"success": success}
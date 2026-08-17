"""System utility tools for automated display captures and OS accessibility scanning."""

import os
import sys
import time
import subprocess
import webbrowser
import concurrent.futures
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Tuple, Union
import pyautogui
from PIL import Image, ImageDraw, ImageFont

# ============================================================================
# DPI AWARENESS & SCREEN METRICS
# ============================================================================
if sys.platform == "win32":
    import ctypes
    try:
        # Per-Monitor DPI Aware v2
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            # Fallback for older Windows builds
            ctypes.windll.user32.SetProcessDpiAwarenessContext(-4)
        except Exception:
            pass

# Safety configuration for PyAutoGUI
pyautogui.FAILSAFE = True  # Move mouse to top-left corner to abort
pyautogui.PAUSE = 0.05


def _draw_precision_grid(image: Image.Image, step: int = 100) -> Image.Image:
    """Overlays a 0-1000 grid on screenshots to give Vision LLMs exact visual spatial anchors."""
    img_copy = image.copy().convert("RGBA")
    overlay = Image.new("RGBA", img_copy.size, (255, 255, 255, 0))
    draw = ImageDraw.Draw(overlay)
    w, h = img_copy.size

    # Red transparent lines for coordinate grid
    grid_color = (255, 0, 0, 90)
    text_color = (255, 255, 255, 230)

    for norm_x in range(0, 1000, step):
        pixel_x = int((norm_x / 1000.0) * w)
        draw.line([(pixel_x, 0), (pixel_x, h)], fill=grid_color, width=1)
        draw.text((pixel_x + 3, 5), str(norm_x), fill=text_color)

    for norm_y in range(0, 1000, step):
        pixel_y = int((norm_y / 1000.0) * h)
        draw.line([(0, pixel_y), (w, pixel_y)], fill=grid_color, width=1)
        draw.text((5, pixel_y + 3), str(norm_y), fill=text_color)

    return Image.alpha_composite(img_copy, overlay).convert("RGB")


# ============================================================================
# TOOL 1: SCREENSHOT CAPTURE
# ============================================================================

def execute_take_screenshot(
    save_directory: str = "./screenshots",
    filename_prefix: str = "screen",
    region: Optional[List[int]] = None,
    target_max_dim: Optional[int] = 1024,
    draw_grid: bool = True,
) -> str:
    """Captures a screenshot with grid overlay for high-precision vision target detection."""
    try:
        os.makedirs(save_directory, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:19]
        filename = f"{filename_prefix}_{timestamp}.png"
        filepath = os.path.abspath(os.path.join(save_directory, filename))

        crop_region = tuple(region) if region and len(region) == 4 else None
        screenshot = pyautogui.screenshot(region=crop_region)

        # Apply precision grid overlay
        if draw_grid:
            screenshot = _draw_precision_grid(screenshot)

        orig_w, orig_h = screenshot.size

        # Resize preserving aspect ratio
        if target_max_dim and (orig_w > target_max_dim or orig_h > target_max_dim):
            scale = min(target_max_dim / orig_w, target_max_dim / orig_h)
            new_w, new_h = int(orig_w * scale), int(orig_h * scale)
            screenshot = screenshot.resize((new_w, new_h), Image.Resampling.LANCZOS)

        screenshot.save(filepath)
        return f"Screenshot successfully saved to: {filepath}"

    except Exception as err:
        return f"Error capturing screenshot: {err}"


# ============================================================================
# TOOL 2: TARGETED ACCESSIBILITY SCANNER WITH SCREENSHOT FALLBACK & TASKBAR INTEGRATION
# ============================================================================

def _scan_accessibility_tree_internal(
    target_query: str = "", max_elements: int = 250, scan_taskbar_only: bool = False
) -> Tuple[List[Dict[str, Any]], Optional[Dict[str, Any]]]:
    """Internal implementation for OS Accessibility traversal including Taskbar support."""
    elements = []
    found_target = None
    screen_w, screen_h = pyautogui.size()
    target_lower = target_query.lower().strip() if target_query else None

    if sys.platform == "win32":
        try:
            from pywinauto import Desktop
            import win32gui
        except ImportError:
            return [], None

        desktop = Desktop(backend="uia")
        candidates = []

        if scan_taskbar_only or (target_lower and any(kw in target_lower for kw in ["taskbar", "dock", "pin", "tray"])):
            try:
                taskbar_win = desktop.window(class_name="Shell_TrayWnd")
                if taskbar_win.exists():
                    candidates = taskbar_win.descendants()
            except Exception:
                pass
        else:
            hwnd = win32gui.GetForegroundWindow()
            if hwnd:
                try:
                    active_win = desktop.window(handle=hwnd)
                    if active_win and active_win.is_visible() and not active_win.is_minimized():
                        candidates = list(active_win.children())
                        if target_lower and not any(
                            target_lower in (c.texts()[0].lower() if c.texts() else "") for c in candidates
                        ):
                            try:
                                candidates = active_win.descendants()
                            except Exception:
                                pass
                except Exception:
                    pass

            # Fallback scan to Taskbar if not found in active window search
            if not candidates and target_lower:
                try:
                    taskbar_win = desktop.window(class_name="Shell_TrayWnd")
                    if taskbar_win.exists():
                        candidates = taskbar_win.descendants()
                except Exception:
                    pass

        for child in candidates:
            if len(elements) >= max_elements:
                break
            try:
                control_type = child.friendly_class_name()
                name = child.texts()[0].strip() if child.texts() else ""

                if not name:
                    continue

                if not scan_taskbar_only and control_type in ["Pane", "Group", "Custom", "TitleBar"] and len(candidates) > 50:
                    continue

                rect = child.rectangle()
                if rect.width() <= 0 or rect.height() <= 0:
                    continue

                cx, cy = rect.mid_point().x, rect.mid_point().y
                if cx < 0 or cy < 0 or cx > screen_w or cy > screen_h:
                    continue

                norm_x = int((cx / screen_w) * 1000)
                norm_y = int((cy / screen_h) * 1000)

                item = {
                    "name": name,
                    "type": control_type,
                    "pixels": (cx, cy),
                    "norm": (norm_x, norm_y),
                }

                if target_lower:
                    if target_lower in name.lower():
                        elements.append(item)
                        return elements, item
                else:
                    elements.append(item)

            except Exception:
                continue

    elif sys.platform == "darwin":
        try:
            from ApplicationServices import (
                AXUIElementCreateSystemWide,
                AXUIElementCopyAttributeValue,
                AXValueGetValue,
                kAXWindowsAttribute,
                kAXChildrenAttribute,
                kAXTitleAttribute,
                kAXRoleAttribute,
                kAXPositionAttribute,
                kAXSizeAttribute,
                kAXValueCGPointType,
                kAXValueCGSizeType,
            )
            import ctypes
        except ImportError:
            return [], None

        def _get_ax(elem, attr):
            err, val = AXUIElementCopyAttributeValue(elem, attr, None)
            return val if err == 0 else None

        system_wide = AXUIElementCreateSystemWide()
        windows = _get_ax(system_wide, kAXWindowsAttribute) or []

        class CGPoint(ctypes.Structure):
            _fields_ = [("x", ctypes.c_double), ("y", ctypes.c_double)]

        class CGSize(ctypes.Structure):
            _fields_ = [("width", ctypes.c_double), ("height", ctypes.c_double)]

        for win in windows:
            if len(elements) >= max_elements:
                break
            children = _get_ax(win, kAXChildrenAttribute) or []
            for child in children:
                if len(elements) >= max_elements:
                    break
                role = _get_ax(child, kAXRoleAttribute)
                title = _get_ax(child, kAXTitleAttribute)
                pos_val = _get_ax(child, kAXPositionAttribute)
                size_val = _get_ax(child, kAXSizeAttribute)

                if title and pos_val and size_val:
                    pt = CGPoint()
                    sz = CGSize()
                    if AXValueGetValue(pos_val, kAXValueCGPointType, ctypes.byref(pt)) and \
                       AXValueGetValue(size_val, kAXValueCGSizeType, ctypes.byref(sz)):
                        cx = int(pt.x + sz.width / 2)
                        cy = int(pt.y + sz.height / 2)
                        norm_x = int((cx / screen_w) * 1000)
                        norm_y = int((cy / screen_h) * 1000)

                        item = {
                            "name": str(title),
                            "type": str(role).replace("AX", ""),
                            "pixels": (cx, cy),
                            "norm": (norm_x, norm_y),
                        }

                        if target_lower:
                            if target_lower in str(title).lower():
                                elements.append(item)
                                return elements, item
                        else:
                            elements.append(item)

    return elements, found_target


def execute_scan_screen_elements(
    target_query: str = "",
    max_elements: int = 250,
    timeout_sec: float = 3.0,
    scan_taskbar_only: bool = False,
    fallback_to_screenshot: bool = True,
) -> str:
    """Scans active windows or Taskbar for specific or general UI elements with timeout caps and fallback."""
    try:
        elements = []
        target_item = None

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(_scan_accessibility_tree_internal, target_query, max_elements, scan_taskbar_only)
            try:
                elements, target_item = future.result(timeout=timeout_sec)
            except concurrent.futures.TimeoutError:
                if fallback_to_screenshot:
                    shot_res = execute_take_screenshot(filename_prefix="fallback_timeout")
                    return f"Accessibility scan timed out after {timeout_sec}s. Fallback screenshot triggered:\n{shot_res}"
                return f"Error: Accessibility scan timed out after {timeout_sec}s."

        if target_item:
            px, py = target_item["pixels"]
            nx, ny = target_item["norm"]
            return f"Found target element '{target_item['name']}' [{target_item['type']}] -> Pixels: ({px}, {py}) | Normalized: ({nx}, {ny})"

        if elements:
            scope_label = "Taskbar" if scan_taskbar_only else "Active Window/Screen"
            output = [f"Visible UI Elements in {scope_label} (Scanned {len(elements)} elements):"]
            for idx, el in enumerate(elements):
                px, py = el["pixels"]
                nx, ny = el["norm"]
                output.append(
                    f"{idx + 1}. [{el['type']}] \"{el['name']}\" -> Pixels: ({px}, {py}) | Normalized: ({nx}, {ny})"
                )
            return "\n".join(output)

        if fallback_to_screenshot:
            shot_res = execute_take_screenshot(filename_prefix="fallback_notfound")
            return f"Target element '{target_query}' was NOT found in the UI tree. Fallback screenshot saved for visual grounding:\n{shot_res}"

        return f"Target element '{target_query}' not found."

    except Exception as err:
        if fallback_to_screenshot:
            shot_res = execute_take_screenshot(filename_prefix="fallback_error")
            return f"Error scanning UI tree: {err}. Fallback screenshot saved:\n{shot_res}"
        return f"Error scanning accessibility tree: {err}"


# ============================================================================
# TOOL 3: CLICK ACCESSIBILITY ELEMENT WITH FALLBACK & TASKBAR SUPPORT
# ============================================================================

def execute_click_element_by_name(
    element_name: str, max_elements: int = 250, timeout_sec: float = 3.0, scan_taskbar_only: bool = False
) -> str:
    """Finds an element in active windows or Taskbar by explicit label name and clicks its center position directly."""
    scan_res = execute_scan_screen_elements(
        target_query=element_name,
        max_elements=max_elements,
        timeout_sec=timeout_sec,
        scan_taskbar_only=scan_taskbar_only,
        fallback_to_screenshot=True,
    )

    if "Found target element" in scan_res or "Pixels:" in scan_res:
        for line in scan_res.splitlines():
            if "Pixels:" in line:
                try:
                    pixel_str = line.split("Pixels:")[1].split("|")[0].strip().strip("()")
                    cx, cy = map(int, pixel_str.split(","))
                    pyautogui.click(cx, cy)
                    return f"Successfully clicked element '{element_name}' at pixel position ({cx}, {cy})."
                except Exception as parse_err:
                    return f"Found element '{element_name}', but failed to execute click: {parse_err}"

    return f"Target element '{element_name}' could not be located via Accessibility APIs. Fallback screenshot triggered:\n{scan_res}"


# ============================================================================
# SCHEMAS & REGISTRY
# ============================================================================

SYSTEM_TOOLS_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "take_screenshot",
            "description": "Captures a screenshot with a spatial coordinate grid overlay for precision visual analysis.",
            "parameters": {
                "type": "object",
                "properties": {
                    "save_directory": {
                        "type": "string",
                        "default": "./screenshots",
                        "description": "Target folder path.",
                    },
                    "filename_prefix": {
                        "type": "string",
                        "default": "screen",
                        "description": "Custom prefix for screenshot filename.",
                    },
                    "region": {
                        "type": "array",
                        "items": {"type": "integer"},
                        "minItems": 4,
                        "maxItems": 4,
                        "description": "Optional bounding box region [x_min, y_min, width, height].",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "scan_screen_elements",
            "description": "Inspects active window or Taskbar UI controls. Pass 'scan_taskbar_only=True' to search taskbar icons explicitly.",
            "parameters": {
                "type": "object",
                "properties": {
                    "target_query": {
                        "type": "string",
                        "default": "",
                        "description": "Specific text label or file name query to search for.",
                    },
                    "max_elements": {
                        "type": "integer",
                        "default": 250,
                        "description": "Maximum number of visible UI controls to scan.",
                    },
                    "timeout_sec": {
                        "type": "number",
                        "default": 3.0,
                        "description": "Maximum time in seconds allowed for scanning before timing out.",
                    },
                    "scan_taskbar_only": {
                        "type": "boolean",
                        "default": False,
                        "description": "If True, limits scanning exclusively to Taskbar/Dock icons without fetching general window elements.",
                    },
                    "fallback_to_screenshot": {
                        "type": "boolean",
                        "default": True,
                        "description": "Whether to capture a screenshot if the target element is missing.",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "click_element_by_name",
            "description": "Searches visible UI controls or Taskbar icons by precise label or app name and clicks its center position directly.",
            "parameters": {
                "type": "object",
                "properties": {
                    "element_name": {
                        "type": "string",
                        "description": "The exact or partial target label, taskbar app icon name, or file name to click.",
                    },
                    "max_elements": {
                        "type": "integer",
                        "default": 250,
                        "description": "Maximum UI element tree scan limit.",
                    },
                    "timeout_sec": {
                        "type": "number",
                        "default": 3.0,
                        "description": "Timeout threshold before falling back to screenshot.",
                    },
                    "scan_taskbar_only": {
                        "type": "boolean",
                        "default": False,
                        "description": "If True, restricts search specifically to Taskbar icons.",
                    },
                },
                "required": ["element_name"],
            },
        },
    },
]

SYSTEM_TOOLS_MAP = {
    "take_screenshot": execute_take_screenshot,
    "scan_screen_elements": execute_scan_screen_elements,
    "click_element_by_name": execute_click_element_by_name,
}
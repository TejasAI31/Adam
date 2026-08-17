import os
import time
import string
import shutil
import tempfile
import zipfile
import io
from typing import List, Dict, Any, Optional

# Conditional Windows Imports for GUI controls
try:
    import os
    import sys
    if os.name == 'nt':
        utils_dir = os.path.dirname(os.path.abspath(__file__))
        src_dir = os.path.dirname(utils_dir)
        backend_dir = os.path.dirname(src_dir)
        
        candidates_pkgs = [
            os.path.join(backend_dir, 'env', 'Lib', 'site-packages'),
            os.path.join(os.path.dirname(backend_dir), 'env', 'Lib', 'site-packages'),
            os.path.join(backend_dir, 'Lib', 'site-packages')
        ]
        
        site_pkgs = None
        for cand in candidates_pkgs:
            if os.path.exists(cand):
                site_pkgs = cand
                break
                
        if site_pkgs:
            # 1. Manually add pywin32 directories to sys.path since .pth files in PYTHONPATH are ignored
            for subdir in ['win32', 'win32\\lib', 'Pythonwin']:
                p = os.path.join(site_pkgs, subdir)
                if os.path.exists(p) and p not in sys.path:
                    sys.path.append(p)
                    
            # 2. Add pywin32_system32 to DLL search path for Python 3.8+
            pywin32_dll_dir = os.path.join(site_pkgs, 'pywin32_system32')
            if os.path.exists(pywin32_dll_dir):
                try:
                    os.add_dll_directory(pywin32_dll_dir)
                except Exception:
                    pass

    import win32api
    import win32con
    import win32gui
    WINDOWS_API_AVAILABLE = True
except ImportError:
    WINDOWS_API_AVAILABLE = False

# Import Pillow components (always available via requirements.txt)
try:
    from PIL import Image, ImageDraw, ImageGrab
    PILLOW_AVAILABLE = True
except ImportError:
    PILLOW_AVAILABLE = False

KEY_MAPPING = {}
if WINDOWS_API_AVAILABLE:
    KEY_MAPPING = {
        "enter": win32con.VK_RETURN,
        "backspace": win32con.VK_BACK,
        "tab": win32con.VK_TAB,
        "escape": win32con.VK_ESCAPE,
        "space": win32con.VK_SPACE,
        "up": win32con.VK_UP,
        "down": win32con.VK_DOWN,
        "left": win32con.VK_LEFT,
        "right": win32con.VK_RIGHT,
        "delete": win32con.VK_DELETE,
        "pgup": win32con.VK_PRIOR,
        "pgdn": win32con.VK_NEXT,
        "home": win32con.VK_HOME,
        "end": win32con.VK_END,
    }

def get_drives() -> List[str]:
    """Get list of logical drives on Windows, or root on Unix."""
    drives = []
    if os.name == 'nt':
        try:
            import win32api
            drives = [d for d in win32api.GetLogicalDriveStrings().split('\000') if d]
        except Exception:
            for letter in string.ascii_uppercase:
                drive = f"{letter}:\\"
                if os.path.exists(drive):
                    drives.append(drive)
    else:
        drives = ["/"]
    return drives

def list_directory(path: str) -> Dict[str, Any]:
    """List subdirectories and files in a path. Handles errors gracefully."""
    # Normalize path
    if not path:
        return {
            "current_path": "",
            "parent_path": "",
            "drives": get_drives(),
            "items": []
        }

    path = os.path.abspath(path)
    
    # Keep path clean
    if not path.endswith(os.path.sep) and os.path.isdir(path):
        path += os.path.sep

    parent_path = os.path.dirname(path.rstrip(os.path.sep))
    if parent_path == path.rstrip(os.path.sep):
        # We are at drive root
        parent_path = ""
        
    items = []
    try:
        for entry in os.scandir(path):
            try:
                stat = entry.stat()
                is_dir = entry.is_dir()
                items.append({
                    "name": entry.name,
                    "path": entry.path,
                    "is_dir": is_dir,
                    "size": 0 if is_dir else stat.st_size,
                    "modified": stat.st_mtime
                })
            except (PermissionError, FileNotFoundError):
                # Skip items we can't access
                continue
    except PermissionError:
        raise PermissionError(f"Permission denied to access directory: {path}")
    except FileNotFoundError:
        raise FileNotFoundError(f"Directory not found: {path}")
        
    # Sort: folders first, then files (case-insensitive name sorting)
    items.sort(key=lambda x: (not x["is_dir"], x["name"].lower()))
    
    return {
        "current_path": path,
        "parent_path": parent_path,
        "drives": get_drives(),
        "items": items
    }

def capture_screenshot(quality: int = 75) -> bytes:
    """Capture the primary screen and return compressed JPEG bytes."""
    if not PILLOW_AVAILABLE:
        raise ImportError("Pillow library is not available in the Python environment.")
        
    try:
        screenshot = ImageGrab.grab()
        buf = io.BytesIO()
        screenshot.save(buf, format='JPEG', quality=quality)
        return buf.getvalue()
    except Exception as pillow_err:
        print(f"[Screen Grab] Pillow ImageGrab failed: {pillow_err}")
        # Return fallback error image
        img = Image.new('RGB', (800, 600), color=(150, 0, 0))
        try:
            d = ImageDraw.Draw(img)
            d.text((200, 300), f"Error grabbing screenshot: {str(pillow_err)}", fill=(255, 255, 255))
        except Exception:
            pass
        buf = io.BytesIO()
        img.save(buf, format='JPEG', quality=quality)
        return buf.getvalue()

def execute_mouse_action(action: str, x: float, y: float, drag_to_x: Optional[float] = None, drag_to_y: Optional[float] = None) -> bool:
    """Simulate mouse events (click, double click, right click, drag, hover). Coordinates are normalized 0.0 - 1.0."""
    if not WINDOWS_API_AVAILABLE:
        print("win32api not available. Cannot execute mouse action.")
        return False
        
    try:
        # Get screen metrics
        screen_w = win32api.GetSystemMetrics(win32con.SM_CXSCREEN)
        screen_h = win32api.GetSystemMetrics(win32con.SM_CYSCREEN)
        
        px_x = max(0, min(screen_w - 1, int(x * screen_w)))
        px_y = max(0, min(screen_h - 1, int(y * screen_h)))
        
        if action == "move":
            win32api.SetCursorPos((px_x, px_y))
            return True
            
        elif action in ["click", "left_click"]:
            win32api.SetCursorPos((px_x, px_y))
            time.sleep(0.05)
            win32api.mouse_event(win32con.MOUSEEVENTF_LEFTDOWN, px_x, px_y, 0, 0)
            time.sleep(0.01)
            win32api.mouse_event(win32con.MOUSEEVENTF_LEFTUP, px_x, px_y, 0, 0)
            return True
            
        elif action == "double_click":
            win32api.SetCursorPos((px_x, px_y))
            time.sleep(0.05)
            # Click 1
            win32api.mouse_event(win32con.MOUSEEVENTF_LEFTDOWN, px_x, px_y, 0, 0)
            time.sleep(0.01)
            win32api.mouse_event(win32con.MOUSEEVENTF_LEFTUP, px_x, px_y, 0, 0)
            time.sleep(0.08)
            # Click 2
            win32api.mouse_event(win32con.MOUSEEVENTF_LEFTDOWN, px_x, px_y, 0, 0)
            time.sleep(0.01)
            win32api.mouse_event(win32con.MOUSEEVENTF_LEFTUP, px_x, px_y, 0, 0)
            return True
            
        elif action == "right_click":
            win32api.SetCursorPos((px_x, px_y))
            time.sleep(0.05)
            win32api.mouse_event(win32con.MOUSEEVENTF_RIGHTDOWN, px_x, px_y, 0, 0)
            time.sleep(0.01)
            win32api.mouse_event(win32con.MOUSEEVENTF_RIGHTUP, px_x, px_y, 0, 0)
            return True
            
        elif action == "drag":
            if drag_to_x is None or drag_to_y is None:
                return False
            px_to_x = max(0, min(screen_w - 1, int(drag_to_x * screen_w)))
            px_to_y = max(0, min(screen_h - 1, int(drag_to_y * screen_h)))
            
            # 1. Move to start position
            win32api.SetCursorPos((px_x, px_y))
            time.sleep(0.1)
            
            # 2. Press left mouse button down (click & hold)
            win32api.mouse_event(win32con.MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
            time.sleep(0.2) # Give OS time to register click & hold
            
            # 3. Drag in steps to the destination with actual mouse move events
            steps = 20
            for i in range(steps + 1):
                t = i / steps
                curr_x = int(px_x + (px_to_x - px_x) * t)
                curr_y = int(px_y + (px_to_y - px_y) * t)
                
                # Move cursor position
                win32api.SetCursorPos((curr_x, curr_y))
                # Send mouse move event to simulate actual dragging
                abs_x = int(curr_x * 65535 / (screen_w - 1))
                abs_y = int(curr_y * 65535 / (screen_h - 1))
                win32api.mouse_event(win32con.MOUSEEVENTF_MOVE | win32con.MOUSEEVENTF_ABSOLUTE, abs_x, abs_y, 0, 0)
                time.sleep(0.015)
                
            # 4. Wait at destination to ensure drag target moves
            time.sleep(0.2)
            # 5. Release left mouse button
            win32api.mouse_event(win32con.MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
            time.sleep(0.1)
            return True
            
        return False
    except Exception as e:
        print(f"Error executing mouse action {action}: {e}")
        return False

def execute_keyboard_action(action: str, text: Optional[str] = None, key: Optional[str] = None) -> bool:
    """Simulate key presses or text input."""
    if not WINDOWS_API_AVAILABLE:
        print("win32api not available. Cannot execute keyboard action.")
        return False
        
    try:
        if action == "type" and text:
            # Clipboard paste mechanism
            try:
                import pyperclip
                old_clipboard = pyperclip.paste()
                pyperclip.copy(text)
                time.sleep(0.05)
                # Press Ctrl+V
                win32api.keybd_event(win32con.VK_CONTROL, 0, 0, 0)
                win32api.keybd_event(ord('V'), 0, 0, 0)
                time.sleep(0.02)
                win32api.keybd_event(ord('V'), 0, win32con.KEYEVENTF_KEYUP, 0)
                win32api.keybd_event(win32con.VK_CONTROL, 0, win32con.KEYEVENTF_KEYUP, 0)
                time.sleep(0.05)
                # Restore old clipboard
                if old_clipboard:
                    pyperclip.copy(old_clipboard)
                return True
            except Exception as e:
                # Key by key fallback for ASCII characters
                print(f"Clipboard copy-paste failed: {e}. Falling back to keyboard events.")
                for char in text:
                    vk = win32api.VkKeyScan(char)
                    if vk != -1:
                        shift = (vk >> 8) & 1
                        vk_code = vk & 0xFF
                        if shift:
                            win32api.keybd_event(win32con.VK_SHIFT, 0, 0, 0)
                        win32api.keybd_event(vk_code, 0, 0, 0)
                        win32api.keybd_event(vk_code, 0, win32con.KEYEVENTF_KEYUP, 0)
                        if shift:
                            win32api.keybd_event(win32con.VK_SHIFT, 0, win32con.KEYEVENTF_KEYUP, 0)
                        time.sleep(0.01)
                return True
                
        elif action == "press_key" and key:
            k = key.lower().strip()
            if k in KEY_MAPPING:
                vk_code = KEY_MAPPING[k]
                win32api.keybd_event(vk_code, 0, 0, 0)
                time.sleep(0.01)
                win32api.keybd_event(vk_code, 0, win32con.KEYEVENTF_KEYUP, 0)
                return True
            else:
                # Try single character
                if len(k) == 1:
                    vk = win32api.VkKeyScan(k)
                    if vk != -1:
                        shift = (vk >> 8) & 1
                        vk_code = vk & 0xFF
                        if shift:
                            win32api.keybd_event(win32con.VK_SHIFT, 0, 0, 0)
                        win32api.keybd_event(vk_code, 0, 0, 0)
                        win32api.keybd_event(vk_code, 0, win32con.KEYEVENTF_KEYUP, 0)
                        if shift:
                            win32api.keybd_event(win32con.VK_SHIFT, 0, win32con.KEYEVENTF_KEYUP, 0)
                        return True
                        
        return False
    except Exception as e:
        print(f"Error executing keyboard action: {e}")
        return False

def create_zip_archive(paths: List[str]) -> str:
    """Create a zip file containing the selected file paths and return the temp zip path."""
    temp_dir = tempfile.gettempdir()
    zip_filename = f"adam_transfer_{int(time.time())}.zip"
    zip_path = os.path.join(temp_dir, zip_filename)
    
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zip_file:
        for file_path in paths:
            file_path = os.path.abspath(file_path)
            if os.path.exists(file_path):
                if os.path.isfile(file_path):
                    # Store file inside the zip, using its name
                    zip_file.write(file_path, os.path.basename(file_path))
                elif os.path.isdir(file_path):
                    # Recursively add directory structure
                    base_dir = os.path.dirname(file_path)
                    for root, dirs, files in os.walk(file_path):
                        for file in files:
                            full_file_path = os.path.join(root, file)
                            rel_path = os.path.relpath(full_file_path, base_dir)
                            zip_file.write(full_file_path, rel_path)
    return zip_path

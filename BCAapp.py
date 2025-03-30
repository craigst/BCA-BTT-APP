#!/usr/bin/env python3
"""
BCA App Automation Tool

This script provides functionality for:
1. Screen capture and image recognition from Android device
2. Macro recording and playback
3. User management and authentication
4. GUI interface for monitoring and control
5. Database integration with SQL.db
"""

import os
import sys
import time
import json
import logging
import asyncio
import subprocess
import configparser
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from enum import Enum
import threading

# Third-party imports
import cv2
import numpy as np
from PIL import Image
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
                           QHBoxLayout, QPushButton, QLabel, QComboBox,
                           QSpinBox, QCheckBox, QMessageBox, QTabWidget,
                           QLineEdit, QFileDialog, QTextEdit, QGroupBox,
                           QDoubleSpinBox, QListWidget, QDialog, QStatusBar,
                           QFrame, QSplitter)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QThread
from PyQt6.QtGui import QImage, QPixmap
from rich.console import Console
from rich.logging import RichHandler
from rich.progress import Progress
from cryptography.fernet import Fernet
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
import sqlite3
import aiosqlite
import pyautogui
import keyboard
import warnings

# Suppress PyQt6 deprecation warnings
warnings.filterwarnings("ignore", category=DeprecationWarning)

# Local imports
from ADB import run_adb_command, check_adb_devices

# Initialize rich console
console = Console()

# Constants
SCRIPT_DIR = Path(__file__).parent
IMAGES_DIR = SCRIPT_DIR / "images"
MACROS_DIR = SCRIPT_DIR / "macros"
LOGS_DIR = SCRIPT_DIR / "logs"
CONFIG_DIR = SCRIPT_DIR / "config"
SQL_DIR = SCRIPT_DIR / "SQL"

# Ensure directories exist
for directory in [IMAGES_DIR, MACROS_DIR, LOGS_DIR, CONFIG_DIR, SQL_DIR]:
    directory.mkdir(exist_ok=True)

# Setup logging
LOG_FILE = LOGS_DIR / f"bca_app_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
logging.basicConfig(
    level=logging.DEBUG,  # Set to DEBUG level
    format="%(asctime)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        RichHandler(rich_tracebacks=True, show_time=False, show_path=False),
        logging.FileHandler(LOG_FILE, encoding='utf-8')  # Use UTF-8 encoding
    ]
)

# Create a logger instance
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

class AppMode(Enum):
    """Application modes for different update rates."""
    FAST = 30  # 30 seconds
    NORMAL = 60  # 1 minute
    SLOW = 300  # 5 minutes
    EXTRA_SLOW = 600  # 10 minutes

@dataclass
class User:
    """User data structure."""
    username: str
    password: str
    is_default: bool = False

@dataclass
class Macro:
    """Macro data structure."""
    name: str
    description: str
    actions: List[Dict]
    trigger_image: Optional[str] = None
    is_active: bool = True
    users: Optional[List[Dict]] = None
    confidence_threshold: float = 0.8  # Default threshold if not specified

class ScreenCapture(QThread):
    """Thread for capturing screenshots"""
    screenshot_ready = pyqtSignal(QImage)
    error_occurred = pyqtSignal(str)
    match_found = pyqtSignal(str, float, tuple)  # macro_name, confidence, position
    no_match = pyqtSignal()
    
    def __init__(self, device_id, refresh_rate=30):  # Default to 30 seconds
        QThread.__init__(self)
        self.device_id = device_id
        self.refresh_rate = refresh_rate
        self.running = True
        self.tmp_dir = Path('tmp')
        self.tmp_dir.mkdir(exist_ok=True)
        self.last_screenshot = None
        self.last_screenshot_time = 0
        self.adb_path = self._get_adb_path()
        self._cleanup_tmp_files()
        self.is_processing = False
        self.current_screenshot = None
        self.current_screenshot_time = 0
        self.macro_manager = None  # Initialize macro_manager as None
        
        # Timing system
        self.timing_mode = AppMode.FAST  # Default to fast mode (30 seconds)
        self.last_check_time = time.time()  # Initialize to current time
        self.check_interval = 30  # Default 30 seconds
        self.processing_start_time = 0
        self.processing_end_time = 0
        
        # Debug counters
        self.screenshot_count = 0
        self.match_count = 0
        self.error_count = 0
        self.last_error_time = 0
        self.last_error_message = ""
        
        # Lock for thread safety
        self.lock = threading.Lock()
        
        # Processing state
        self.is_processing_screenshot = False
        self.last_processing_time = 0
        
    def _cleanup_tmp_files(self):
        """Clean up any existing temporary files."""
        try:
            for file in self.tmp_dir.glob("*"):
                try:
                    file.unlink()
                except Exception as e:
                    logging.warning(f"Failed to remove temporary file {file}: {e}")
        except Exception as e:
            logging.warning(f"Failed to clean up temporary directory: {e}")
    
    def _get_adb_path(self):
        """Get the path to the ADB executable in platform-tools."""
        if os.name == 'nt':  # Windows
            adb_path = os.path.join(SCRIPT_DIR, "platform-tools", "adb.exe")
        else:  # Linux/Mac
            adb_path = os.path.join(SCRIPT_DIR, "platform-tools", "adb")
        
        if not os.path.exists(adb_path):
            raise Exception(f"ADB executable not found at {adb_path}")
        
        return adb_path
        
    def _run_adb_command(self, command, check_output=True):
        """Run an ADB command with proper path."""
        try:
            if isinstance(command, str):
                cmd_str = command
                command = command.split()
            
            # Replace 'adb' with the full path
            if isinstance(command, str):
                command = command.replace('adb ', f'"{self.adb_path}" ')
            else:
                command = [self.adb_path if cmd == 'adb' else cmd for cmd in command]
            
            # Use shell=True for Windows compatibility
            if check_output:
                result = subprocess.run(command, capture_output=True, text=True, shell=True)
                if result.returncode != 0:
                    # Don't raise error for cleanup commands
                    if "rm" in cmd_str and "No such file" in result.stderr:
                        return True
                    raise Exception(f"ADB command failed: {result.stderr}")
                return result.stdout.strip()
            else:
                result = subprocess.run(command, capture_output=True, text=True, shell=True)
                # Don't raise error for cleanup commands
                if "rm" in cmd_str and "No such file" in result.stderr:
                    return True
                if result.returncode != 0:
                    raise Exception(f"ADB command failed: {result.stderr}")
                return True
        except Exception as e:
            # Don't log errors for cleanup commands
            if "rm" in cmd_str and "No such file" in str(e):
                return True
            logging.error(f"ADB command error: {e}")
            raise
    
    def save_screenshot(self, filename: str) -> bool:
        """Save current screenshot to file."""
        try:
            if self.last_screenshot is None:
                return False
                
            # Ensure filename has extension
            if not filename.lower().endswith(('.png', '.jpg', '.jpeg')):
                filename += '.png'
                
            # Save to images directory
            save_path = IMAGES_DIR / filename
            self.last_screenshot.save(str(save_path))
            logging.info(f"Screenshot saved as {filename}")
            return True
            
        except Exception as e:
            logging.error(f"Error saving screenshot: {e}")
            return False
            
    def _method2_file_based(self):
        """Method 2: File-based (most reliable)"""
        try:
            # Generate unique filenames
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            tmp_file = self.tmp_dir / f"screenshot_{timestamp}.png"
            device_file = f"/sdcard/screenshot_{timestamp}.png"
            
            # Check if tmp directory exists
            if not self.tmp_dir.exists():
                self.tmp_dir.mkdir(exist_ok=True)
            
            # Clean up any existing files first
            try:
                self._run_adb_command(f"adb -s {self.device_id} shell rm {device_file}", check_output=False)
            except Exception:
                pass
            
            # Capture to device
            logger.debug(f"Capturing screenshot to device: {device_file}")
            self._run_adb_command(f"adb -s {self.device_id} shell screencap -p {device_file}", check_output=False)
            time.sleep(0.5)  # Wait for file to be written
            
            # Pull from device
            logger.debug(f"Pulling screenshot from device to: {tmp_file}")
            self._run_adb_command(f"adb -s {self.device_id} pull {device_file} {tmp_file}", check_output=False)
            
            # Verify local file exists
            if not tmp_file.exists():
                raise Exception(f"Failed to pull screenshot to: {tmp_file}")
            
            # Read image with OpenCV
            img = cv2.imread(str(tmp_file))
            if img is None:
                raise Exception(f"OpenCV failed to read image: {tmp_file}")
            
            # Clean up
            try:
                self._run_adb_command(f"adb -s {self.device_id} shell rm {device_file}", check_output=False)
                if tmp_file.exists():
                    tmp_file.unlink()
            except Exception:
                pass
            
            return img
            
        except Exception as e:
            logger.error(f"File-based method failed: {e}")
            return None
    
    def capture_screenshot(self):
        """Capture screenshot using multiple methods"""
        try:
            current_time = time.time()
            if current_time - self.last_screenshot_time < self.refresh_rate:
                return self.last_screenshot
            
            # Try file-based method first (most reliable)
            img = self._method2_file_based()
            if img is None:
                raise Exception("Failed to capture screenshot")
            
            # Convert to RGB
            img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
            
            # Convert to QImage
            height, width, channel = img.shape
            bytes_per_line = 3 * width
            q_img = QImage(img.data, width, height, bytes_per_line, QImage.Format.Format_RGB888)
            
            # Store last screenshot
            self.last_screenshot = q_img
            self.last_screenshot_time = current_time
            
            return q_img
            
        except Exception as e:
            self.error_occurred.emit(str(e))
            return None
    
    def _create_macro_for_image(self, image_name: str):
        """Create a basic macro file for an image that doesn't have one."""
        try:
            # Create macro name from image name (remove extension)
            macro_name = Path(image_name).stem
            
            # Check if macro already exists
            if macro_name in self.macro_manager.macros:
                return
            
            # Create basic macro with high confidence threshold
            macro = Macro(
                name=macro_name,
                description=f"Auto-generated macro for {image_name}",
                trigger_image=image_name,
                actions=[],  # Empty actions list
                is_active=True,
                confidence_threshold=0.95  # High threshold for new macros
            )
            
            # Save macro
            self.macro_manager.save_macro(macro)
            logging.info(f"Created macro file for {image_name} with confidence threshold: 0.95")
            
        except Exception as e:
            logging.error(f"Error creating macro for {image_name}: {e}")
    
    def set_timing_mode(self, mode: AppMode):
        """Set the timing mode for screenshot checks."""
        try:
            with self.lock:
                self.timing_mode = mode
                self.check_interval = mode.value
                self.last_check_time = time.time()  # Reset the last check time
                logger.info(f"Timing mode changed to: {mode.name}")
                logger.info(f"Check interval set to: {self.check_interval} seconds")
        except Exception as e:
            logger.error(f"Error setting timing mode: {e}")
            self.error_occurred.emit(f"Error setting timing mode: {e}")
    
    def process_screenshot(self, macro_manager=None):
        """Process current screenshot with image matching."""
        try:
            if not self.current_screenshot or self.is_processing:
                return
                
            # Use provided macro_manager or fall back to instance variable
            manager = macro_manager or self.macro_manager
            if not manager:
                logger.error("No macro manager available")
                return
                
            start_time = time.time()
            
            # Convert QImage to numpy array for OpenCV
            width = self.current_screenshot.width()
            height = self.current_screenshot.height()
            ptr = self.current_screenshot.bits()
            ptr.setsize(height * width * 3)  # RGB format
            arr = np.frombuffer(ptr, np.uint8).reshape((height, width, 3))
            
            # Convert RGB to BGR for OpenCV
            screenshot = cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)
            
            # Process each image file
            for image_file in os.listdir(IMAGES_DIR):
                if not image_file.endswith('.png'):
                    continue
                    
                try:
                    template_path = os.path.join(IMAGES_DIR, image_file)
                    template = cv2.imread(str(template_path))
                    
                    if template is None:
                        continue
                        
                    # Convert template to grayscale
                    gray_template = cv2.cvtColor(template, cv2.COLOR_BGR2GRAY)
                    gray_screenshot = cv2.cvtColor(screenshot, cv2.COLOR_BGR2GRAY)
                    
                    # Perform template matching
                    result = cv2.matchTemplate(gray_screenshot, gray_template, cv2.TM_CCOEFF_NORMED)
                    min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(result)
                    
                    # Get macro name without extension
                    macro_name = Path(image_file).stem
                    
                    # Check if macro exists and is active
                    macro_exists = macro_name in manager.macros
                    macro_active = False
                    if macro_exists:
                        macro = manager.macros[macro_name]
                        macro_active = macro.is_active
                    
                    if max_val >= manager.match_threshold:
                        logger.info(f"Match found: {image_file} (Confidence: {max_val:.3f})")
                        if macro_exists and macro_active:
                            logger.info(f"Executing macro: {macro_name}")
                        elif macro_exists and not macro_active:
                            logger.info(f"Macro {macro_name} is inactive")
                        else:
                            logger.info(f"No macro configured for {image_file}")
                        
                        try:
                            self.match_found.emit(image_file, max_val, max_loc)
                        except Exception as e:
                            logger.error(f"Error emitting match signal: {e}")
                            continue
                            
                except Exception as e:
                    logger.error(f"Error processing image {image_file}: {e}")
                    continue
                    
            # Emit no match signal if no matches found
            try:
                self.no_match.emit()
            except Exception as e:
                logger.error(f"Error emitting no match signal: {e}")
                
            processing_time = time.time() - start_time
            next_check = self.check_interval - processing_time
            logger.info(f"Next check in {next_check:.1f} seconds")
            
        except Exception as e:
            logger.error(f"Error processing screenshot: {e}")
        finally:
            self.is_processing = False
            self.current_screenshot = None
            self.current_screenshot_time = None

    def run(self):
        """Main thread loop."""
        while self.running:
            try:
                current_time = time.time()
                
                # Only process if we're not already processing and enough time has passed
                if (not self.is_processing_screenshot and 
                    (not self.last_processing_time or 
                     current_time - self.last_processing_time >= self.check_interval)):
                    
                    # Take new screenshot
                    screenshot = self.capture_screenshot()
                    if screenshot:
                        self.is_processing_screenshot = True
                        self.current_screenshot = screenshot
                        self.current_screenshot_time = current_time
                        self.screenshot_ready.emit(screenshot)
                        logger.info(f"\nCapturing new screenshot at {datetime.now().strftime('%H:%M:%S')}")
                        
                        # Process the new screenshot
                        self.process_screenshot(self.macro_manager)
                        
                        # Update processing time
                        self.last_processing_time = current_time
                        self.is_processing_screenshot = False
                        
                # Sleep for a short time to prevent CPU overuse
                time.sleep(0.1)
                
            except Exception as e:
                logger.error(f"Error in main loop: {e}")
                self.error_occurred.emit(str(e))
                # Clear any partial screenshot data
                self.current_screenshot = None
                self.current_screenshot_time = None
                self.is_processing_screenshot = False
                time.sleep(1)  # Wait before retrying

    def set_macro_manager(self, macro_manager):
        """Set the macro manager instance."""
        try:
            with self.lock:
                self.macro_manager = macro_manager
                logger.info("Macro manager set successfully")
        except Exception as e:
            logger.error(f"Error setting macro manager: {e}")
            self.error_occurred.emit(f"Error setting macro manager: {e}")

class UserManager:
    """Manages user authentication and storage."""
    
    def __init__(self):
        self.users: List[User] = []
        self.config_file = CONFIG_DIR / "users.ini"
        self.key_file = CONFIG_DIR / "key.key"
        self._load_key()
        self._load_users()
    
    def _load_key(self):
        """Load or create encryption key."""
        try:
            if self.key_file.exists():
                with open(self.key_file, 'rb') as f:
                    self.key = f.read()
            else:
                self.key = Fernet.generate_key()
                with open(self.key_file, 'wb') as f:
                    f.write(self.key)
        except Exception as e:
            logging.error(f"Key loading error: {e}")
            raise
    
    def _load_users(self):
        """Load users from config file."""
        try:
            if not self.config_file.exists():
                return
            
            config = configparser.ConfigParser()
            config.read(self.config_file)
            
            for username in config.sections():
                password = self._decrypt_password(config[username]['password'])
                is_default = config[username].getboolean('is_default', False)
                self.users.append(User(username, password, is_default))
                
        except Exception as e:
            logging.error(f"User loading error: {e}")
    
    def _encrypt_password(self, password: str) -> str:
        """Encrypt password using Fernet."""
        f = Fernet(self.key)
        return f.encrypt(password.encode()).decode()
    
    def _decrypt_password(self, encrypted: str) -> str:
        """Decrypt password using Fernet."""
        f = Fernet(self.key)
        return f.decrypt(encrypted.encode()).decode()
    
    def add_user(self, username: str, password: str, is_default: bool = False):
        """Add new user."""
        try:
            if any(u.username == username for u in self.users):
                raise ValueError("Username already exists")
            
            encrypted = self._encrypt_password(password)
            user = User(username, password, is_default)
            self.users.append(user)
            
            # Save to config
            config = configparser.ConfigParser()
            config.read(self.config_file)
            config[username] = {
                'password': encrypted,
                'is_default': str(is_default)
            }
            with open(self.config_file, 'w') as f:
                config.write(f)
            
            logging.info(f"User added: {username}")
            
        except Exception as e:
            logging.error(f"Add user error: {e}")
            raise
    
    def get_default_user(self) -> Optional[User]:
        """Get default user if exists."""
        return next((u for u in self.users if u.is_default), None)
    
    def authenticate(self, username: str, password: str) -> bool:
        """Authenticate user."""
        user = next((u for u in self.users if u.username == username), None)
        return user and user.password == password

class MacroManager:
    """Manages macro recording and playback."""
    
    def __init__(self, screen_capture: ScreenCapture):
        self.macros = {}
        self.screen_capture = screen_capture
        self.match_threshold = 0.8
        self.test_mode = False
        self.test_results = []
        self.show_matches = False
        self.save_failed_matches = False
        self.load_macros()
    
    def reload_macros(self):
        """Reload all macros from disk."""
        try:
            logger.info("\n==================================================")
            logger.info("RELOADING MACROS")
            logger.info("==================================================")
            
            # Clear existing macros
            self.macros.clear()
            
            # Reload macros
            self.load_macros()
            
            logger.info("Macros reloaded successfully")
            logger.info("==================================================\n")
            
        except Exception as e:
            logger.error(f"Error reloading macros: {e}")
            raise
    
    def load_macros(self):
        """Load all macros from the macros directory."""
        try:
            self.macros.clear()
            macro_files = [f for f in os.listdir(MACROS_DIR) if f.endswith('.json')]
            
            logger.info(f"Found {len(macro_files)} macro files:")
            for macro_file in macro_files:
                try:
                    with open(os.path.join(MACROS_DIR, macro_file), 'r') as f:
                        data = json.load(f)
                        macro = Macro(
                            name=data['name'],
                            description=data.get('description', ''),
                            actions=data.get('actions', []),
                            trigger_image=data.get('trigger_image'),
                            is_active=data.get('is_active', True),
                            users=data.get('users'),
                            confidence_threshold=data.get('confidence_threshold', 0.8)
                        )
                        self.macros[macro.name] = macro
                        
                        # Log detailed macro information
                        logger.info(f"Loaded macro: {macro.name}")
                        logger.info(f"  - Trigger image: {macro.trigger_image}")
                        logger.info(f"  - Active: {macro.is_active}")
                        logger.info(f"  - Confidence threshold: {macro.confidence_threshold}")
                        logger.info(f"  - Number of actions: {len(macro.actions)}")
                        if macro.users:
                            logger.info(f"  - Number of users: {len(macro.users)}")
                        
                except Exception as e:
                    logger.error(f"Error loading macro {macro_file}: {str(e)}")
            
            logger.info(f"\nTotal macros loaded: {len(self.macros)}")
            logger.info("=" * 50)
            
        except Exception as e:
            logger.error(f"Error loading macros: {str(e)}")
            raise
    
    def save_macro(self, macro: Macro):
        """Save macro to file."""
        try:
            file = MACROS_DIR / f"{macro.name}.json"
            with open(file, 'w') as f:
                json.dump(macro.__dict__, f, indent=4)
            self.macros[macro.name] = macro
            logging.info(f"Macro saved: {macro.name}")
        except Exception as e:
            logging.error(f"Save macro error: {e}")
    
    def find_image_match(self, screenshot: np.ndarray, template_path: str) -> Tuple[bool, float, Tuple[int, int]]:
        """
        Find template image in screenshot.
        Returns: (found, confidence, position)
        """
        try:
            # Validate template path
            template_path = Path(template_path)
            if not template_path.exists():
                logger.error(f"Template image not found: {template_path}")
                return False, 0.0, (0, 0)
            
            # Read template with error checking
            template = cv2.imread(str(template_path))
            if template is None:
                logger.error(f"Failed to load template image: {template_path}")
                return False, 0.0, (0, 0)
            
            # Convert images to grayscale
            gray_screenshot = cv2.cvtColor(screenshot, cv2.COLOR_BGR2GRAY)
            gray_template = cv2.cvtColor(template, cv2.COLOR_BGR2GRAY)
            
            # Perform template matching
            result = cv2.matchTemplate(gray_screenshot, gray_template, cv2.TM_CCOEFF_NORMED)
            min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(result)
            
            # Log match details
            logger.debug(f"Match details for {template_path.name}:")
            logger.debug(f"Confidence: {max_val:.3f}")
            logger.debug(f"Position: {max_loc}")
            
            return max_val >= self.match_threshold, max_val, max_loc
            
        except Exception as e:
            logger.error(f"Image matching error: {e}")
            return False, 0.0, (0, 0)
    
    def check_trigger_image(self, screenshot: np.ndarray, macro: Macro) -> bool:
        """Check if trigger image is present in screenshot."""
        if not macro.trigger_image:
            return True
            
        trigger_path = IMAGES_DIR / macro.trigger_image
        if not trigger_path.exists():
            logging.error(f"Trigger image not found: {trigger_path}")
            return False
            
        logging.info(f"Checking trigger image for macro: {macro.name}")
        logging.info(f"Trigger image path: {trigger_path}")
        
        found, confidence, position = self.find_image_match(screenshot, str(trigger_path))
        
        if found:
            logging.info(f"Trigger image found for macro: {macro.name}")
            logging.info(f"Confidence: {confidence:.3f}")
            logging.info(f"Position: {position}")
        else:
            logging.info(f"Trigger image not found for macro: {macro.name}")
            logging.info(f"Best confidence: {confidence:.3f}")
            logging.info(f"Best position: {position}")
        
        return found
    
    def test_image_matching(self, screenshot: np.ndarray):
        """Test all trigger images against current screenshot."""
        if not self.test_mode:
            return
            
        self.test_results = []
        logging.info("Starting image matching test")
        
        for macro_name, macro in self.macros.items():
            if macro.is_active and macro.trigger_image:
                logging.info(f"Testing macro: {macro_name}")
                logging.info(f"Trigger image: {macro.trigger_image}")
                self.check_trigger_image(screenshot, macro)
        
        # Log test results
        logging.info("\nTest Results:")
        for result in self.test_results:
            logging.info(f"Template: {result['template']}")
            logging.info(f"Confidence: {result['confidence']:.3f}")
            logging.info(f"Position: {result['position']}")
            logging.info(f"Threshold: {result['threshold']}")
            logging.info(f"Timestamp: {result['timestamp']}")
            logging.info("---")
    
    def execute_macro(self, macro_name: str, device: Optional[str] = None, screenshot: Optional[np.ndarray] = None):
        """Execute macro actions if trigger image is found."""
        if macro_name not in self.macros:
            logging.error(f"Macro not found: {macro_name}")
            return False
        
        macro = self.macros[macro_name]
        if not macro.is_active:
            logging.warning(f"Macro is inactive: {macro_name}")
            return False
        
        try:
            # Check trigger image if specified
            if macro.trigger_image and screenshot is not None:
                if not self.check_trigger_image(screenshot, macro):
                    logging.info(f"Trigger image not found for macro: {macro_name}")
                    return False
                logging.info(f"Trigger image found for macro: {macro_name}")
            
            # Execute actions
            for action in macro.actions:
                self._execute_action(action, device)
            return True
            
        except Exception as e:
            logging.error(f"Macro execution error: {e}")
            return False
    
    def _execute_action(self, action: Dict, device: Optional[str] = None):
        """Execute a single macro action."""
        action_type = action.get('type')
        if not action_type:
            return
        
        try:
            # Get ADB path from ScreenCapture
            adb_path = self.screen_capture.adb_path
            
            # Build ADB command with device if specified
            cmd = f'"{adb_path}"'
            if device:
                cmd += f" -s {device}"
            
            # Execute action based on type
            if action_type == 'tap':
                x, y = action['x'], action['y']
                cmd_str = f"{cmd} shell input tap {x} {y}"
                logging.info(f"\nExecuting ADB command: {cmd_str}")
                result = subprocess.run(cmd_str, shell=True, capture_output=True, text=True)
                if result.returncode == 0:
                    logging.info("Command executed successfully")
                else:
                    logging.error(f"Command failed: {result.stderr}")
                time.sleep(1)  # Wait for tap to complete
                
            elif action_type == 'swipe':
                x1, y1, x2, y2 = action['x1'], action['y1'], action['x2'], action['y2']
                duration = action.get('duration', 500)  # Default to 500ms if not specified
                cmd_str = f"{cmd} shell input swipe {x1} {y1} {x2} {y2} {duration}"
                logging.info(f"\nExecuting ADB command: {cmd_str}")
                result = subprocess.run(cmd_str, shell=True, capture_output=True, text=True)
                if result.returncode == 0:
                    logging.info("Command executed successfully")
                else:
                    logging.error(f"Command failed: {result.stderr}")
                time.sleep(1)  # Wait for swipe to complete
                
            elif action_type == 'key':
                key = action['key']
                cmd_str = f"{cmd} shell input keyevent {key}"
                logging.info(f"\nExecuting ADB command: {cmd_str}")
                result = subprocess.run(cmd_str, shell=True, capture_output=True, text=True)
                if result.returncode == 0:
                    logging.info("Command executed successfully")
                else:
                    logging.error(f"Command failed: {result.stderr}")
                time.sleep(1)  # Wait for key press to complete
                
            elif action_type == 'text':
                text = action['text']
                # Escape special characters in text
                text = text.replace("'", "\\'")
                cmd_str = f"{cmd} shell input text '{text}'"
                result = subprocess.run(cmd_str, shell=True, capture_output=True, text=True)
                if result.returncode == 0:
                    logging.info("Command executed successfully")
                else:
                    logging.error(f"Command failed: {result.stderr}")
                time.sleep(1)  # Wait for text input to complete
                
            elif action_type == 'wait':
                seconds = action['seconds']
                logging.info(f"Waiting: {seconds} seconds")
                time.sleep(seconds)
                
        except Exception as e:
            logging.error(f"Action execution error: {e}")
            raise

class MainWindow(QMainWindow):
    """Main GUI window."""
    
    def __init__(self, screen_capture: ScreenCapture, user_manager: UserManager, macro_manager: MacroManager):
        QMainWindow.__init__(self)
        self.screen_capture = screen_capture
        self.user_manager = user_manager
        self.macro_manager = macro_manager
        
        # Set macro_manager in screen_capture if not already set
        if not hasattr(self.screen_capture, 'macro_manager') or self.screen_capture.macro_manager is None:
            self.screen_capture.macro_manager = self.macro_manager
            logger.info("Set macro manager in screen capture")
        
        self.setup_ui()
        self.setup_timer()
        
        # Connect new signals
        self.screen_capture.match_found.connect(self.handle_match_found)
        self.screen_capture.no_match.connect(self.handle_no_match)
    
    def setup_ui(self):
        """Setup the main window UI."""
        self.setWindowTitle("BCA Macro Manager")
        self.setMinimumSize(800, 600)
        
        # Create main widget and layout
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        layout = QVBoxLayout(main_widget)
        
        # Create top section with device selection and controls
        top_section = QHBoxLayout()
        
        # Device selection
        device_layout = QHBoxLayout()
        device_layout.addWidget(QLabel("Device:"))
        self.device_combo = QComboBox()
        self.device_combo.setMinimumWidth(200)
        device_layout.addWidget(self.device_combo)
        top_section.addLayout(device_layout)
        
        # Add spacing
        top_section.addSpacing(20)
        
        # Timing mode selection
        timing_layout = QHBoxLayout()
        timing_layout.addWidget(QLabel("Timing Mode:"))
        self.timing_combo = QComboBox()
        self.timing_combo.addItems([mode.name for mode in AppMode])
        self.timing_combo.currentTextChanged.connect(self.update_timing_mode)
        timing_layout.addWidget(self.timing_combo)
        top_section.addLayout(timing_layout)
        
        # Add spacing
        top_section.addSpacing(20)
        
        # Capture toggle checkbox
        self.capture_toggle = QCheckBox("Enable Capture")
        self.capture_toggle.setChecked(True)
        self.capture_toggle.stateChanged.connect(self.toggle_capture)
        top_section.addWidget(self.capture_toggle)
        
        # Add spacing
        top_section.addSpacing(20)
        
        # Auto-execute checkbox
        self.auto_execute = QCheckBox("Auto-execute Macros")
        top_section.addWidget(self.auto_execute)
        
        # Add spacing
        top_section.addSpacing(20)
        
        # Reload macros button
        self.reload_button = QPushButton("Reload Macros")
        self.reload_button.clicked.connect(self.reload_macros)
        top_section.addWidget(self.reload_button)
        
        # Add spacing
        top_section.addSpacing(20)
        
        # Play macro button
        self.play_button = QPushButton("Play Macro")
        self.play_button.clicked.connect(self.play_macro)
        top_section.addWidget(self.play_button)
        
        # Add top section to main layout
        layout.addLayout(top_section)
        
        # Add separator
        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.HLine)
        separator.setFrameShadow(QFrame.Shadow.Sunken)
        layout.addWidget(separator)
        
        # Create split view for macro list and preview
        splitter = QSplitter(Qt.Orientation.Horizontal)
        
        # Left side: Macro list
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        
        # Macro list header
        macro_header = QHBoxLayout()
        macro_header.addWidget(QLabel("Macros"))
        macro_header.addStretch()
        
        # Add macro button
        add_macro_btn = QPushButton("Add Macro")
        add_macro_btn.clicked.connect(self.add_macro)
        macro_header.addWidget(add_macro_btn)
        
        left_layout.addLayout(macro_header)
        
        # Macro list
        self.macro_list = QListWidget()
        self.macro_list.currentItemChanged.connect(self.on_macro_selected)
        left_layout.addWidget(self.macro_list)
        
        splitter.addWidget(left_widget)
        
        # Right side: Preview and settings
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        
        # Preview section
        preview_layout = QVBoxLayout()
        preview_layout.addWidget(QLabel("Preview"))
        
        # Preview image
        self.preview_label = QLabel()
        self.preview_label.setMinimumSize(400, 300)
        self.preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_label.setStyleSheet("border: 1px solid #ccc;")
        preview_layout.addWidget(self.preview_label)
        
        right_layout.addLayout(preview_layout)
        
        # Add separator
        separator2 = QFrame()
        separator2.setFrameShape(QFrame.Shape.HLine)
        separator2.setFrameShadow(QFrame.Shadow.Sunken)
        right_layout.addWidget(separator2)
        
        # Match display section
        match_layout = QVBoxLayout()
        match_layout.addWidget(QLabel("Current Match"))
        
        # Match info display
        self.match_display = QTextEdit()
        self.match_display.setReadOnly(True)
        self.match_display.setMinimumHeight(100)
        self.match_display.setStyleSheet("background-color: #f0f0f0; border: 1px solid #ccc;")
        match_layout.addWidget(self.match_display)
        
        right_layout.addLayout(match_layout)
        
        # Add separator
        separator3 = QFrame()
        separator3.setFrameShape(QFrame.Shape.HLine)
        separator3.setFrameShadow(QFrame.Shadow.Sunken)
        right_layout.addWidget(separator3)
        
        # Settings section
        settings_layout = QVBoxLayout()
        settings_layout.addWidget(QLabel("Settings"))
        
        # Confidence threshold
        threshold_layout = QHBoxLayout()
        threshold_layout.addWidget(QLabel("Confidence Threshold:"))
        self.confidence_threshold = QDoubleSpinBox()
        self.confidence_threshold.setRange(0.1, 1.0)
        self.confidence_threshold.setSingleStep(0.1)
        self.confidence_threshold.setValue(0.8)
        threshold_layout.addWidget(self.confidence_threshold)
        settings_layout.addLayout(threshold_layout)
        
        # Active checkbox
        self.active_checkbox = QCheckBox("Active")
        self.active_checkbox.setChecked(True)
        settings_layout.addWidget(self.active_checkbox)
        
        # Actions list
        actions_layout = QVBoxLayout()
        actions_layout.addWidget(QLabel("Actions"))
        
        self.actions_list = QListWidget()
        self.actions_list.setDragDropMode(QListWidget.DragDropMode.InternalMove)
        self.actions_list.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        self.actions_list.setDragEnabled(True)
        self.actions_list.setAcceptDrops(True)
        self.actions_list.setDropIndicatorShown(True)
        self.actions_list.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.actions_list.model().rowsMoved.connect(self.reorder_actions)
        actions_layout.addWidget(self.actions_list)
        
        # Action buttons
        action_buttons = QHBoxLayout()
        add_key_btn = QPushButton("Add Key")
        add_key_btn.clicked.connect(self.add_key_action)
        add_text_btn = QPushButton("Add Text")
        add_text_btn.clicked.connect(self.add_text_action)
        add_tap_btn = QPushButton("Add Tap")
        add_tap_btn.clicked.connect(self.add_tap_action)
        add_swipe_btn = QPushButton("Add Swipe")
        add_swipe_btn.clicked.connect(self.add_swipe_action)
        add_wait_btn = QPushButton("Add Wait")
        add_wait_btn.clicked.connect(self.add_wait_action)
        edit_action_btn = QPushButton("Edit Action")
        edit_action_btn.clicked.connect(self.edit_action)
        remove_action_btn = QPushButton("Remove Action")
        remove_action_btn.clicked.connect(self.remove_action)
        
        action_buttons.addWidget(add_key_btn)
        action_buttons.addWidget(add_text_btn)
        action_buttons.addWidget(add_tap_btn)
        action_buttons.addWidget(add_swipe_btn)
        action_buttons.addWidget(add_wait_btn)
        action_buttons.addWidget(edit_action_btn)
        action_buttons.addWidget(remove_action_btn)
        
        actions_layout.addLayout(action_buttons)
        settings_layout.addLayout(actions_layout)
        
        right_layout.addLayout(settings_layout)
        
        splitter.addWidget(right_widget)
        
        # Add splitter to main layout
        layout.addWidget(splitter)
        
        # Status bar
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        
        # Add countdown label to status bar
        self.countdown_label = QLabel()
        self.status_bar.addPermanentWidget(self.countdown_label)
        
        # Setup countdown timer
        self.countdown_timer = QTimer()
        self.countdown_timer.timeout.connect(self.update_countdown)
        self.countdown_timer.start(1000)  # Update every second
        
        # Initialize UI state
        self.update_device_list()
        self.update_macro_list()
        
    def setup_timer(self):
        """Setup update timer."""
        # Remove the timer setup since we're using the ScreenCapture thread timing
        # Connect screen capture signals
        self.screen_capture.screenshot_ready.connect(self.handle_screenshot)
        self.screen_capture.error_occurred.connect(self.handle_error)
        
        # Start screen capture thread
        self.screen_capture.start()
    
    def handle_screenshot(self, q_img):
        """Handle new screenshot."""
        if not self.capture_toggle.isChecked():
            return
            
        try:
            if q_img is None:
                logger.error("Received null screenshot")
                return
                
            # Scale to fit label while maintaining aspect ratio
            pixmap = QPixmap.fromImage(q_img)
            scaled_pixmap = pixmap.scaled(
                self.preview_label.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation
            )
            self.preview_label.setPixmap(scaled_pixmap)
            
            # Update status bar
            self.status_bar.showMessage(f"Last update: {datetime.now().strftime('%H:%M:%S')}")
            
        except Exception as e:
            logger.error(f"Error displaying screenshot: {e}")
            self.handle_error(f"Error processing screenshot: {e}")
    
    def handle_error(self, error_msg):
        """Handle screenshot error."""
        logging.error(f"Screenshot error: {error_msg}")
        # Show error in GUI
        self.preview_label.setText(f"Error: {error_msg}")
        self.preview_label.setStyleSheet("color: red;")
        self.status_bar.showMessage(f"Error: {error_msg}")
    
    def handle_match_found(self, macro_name: str, confidence: float, position: tuple):
        """Handle when a match is found for a macro's trigger image."""
        try:
            # Get current time
            current_time = time.strftime("%H:%M:%S")
            
            # Strip the extension from macro_name for comparison
            image_name = Path(macro_name).stem
            
            # Check if macro exists and is active
            macro_exists = False
            macro_active = False
            matching_macro = None
            
            # Log all available macros for debugging
            logger.info(f"Available macros: {list(self.macro_manager.macros.keys())}")
            logger.info(f"Looking for macro with trigger image: {image_name}")
            
            # Find macro by matching trigger image
            for macro in self.macro_manager.macros.values():
                if macro.trigger_image:
                    trigger_name = Path(macro.trigger_image).stem
                    logger.info(f"Checking macro '{macro.name}' with trigger image '{trigger_name}'")
                    if trigger_name == image_name:
                        macro_exists = True
                        macro_active = macro.is_active
                        matching_macro = macro
                        logger.info(f"Found matching macro: {macro.name}")
                        break
            
            # Update UI with match information
            self.match_display.setText(f"Image: {macro_name}\n"
                                   f"Confidence: {confidence:.3f}\n"
                                   f"Position: {position}\n"
                                   f"Time: {current_time}\n"
                                   f"Has Macro: {'Yes' if macro_exists else 'No'}\n"
                                   f"Macro Active: {'Yes' if macro_active else 'No'}")
            
            # Log detailed information
            if macro_exists:
                logger.info(f"Found macro '{matching_macro.name}' with trigger image '{macro_name}'")
                logger.info(f"Macro status: Active={macro_active}, Confidence={confidence:.3f}")
                if macro_active:
                    logger.info(f"Macro '{matching_macro.name}' is active and will be executed")
                else:
                    logger.info(f"Macro '{matching_macro.name}' is inactive and will not be executed")
            else:
                logger.info(f"No macro found for image '{macro_name}'")
            
            # Execute macro if it exists, is active, and auto-execute is enabled
            if macro_exists and macro_active and self.auto_execute.isChecked():
                logger.info(f"Auto-executing macro '{matching_macro.name}'")
                self.macro_manager.execute_macro(matching_macro.name, self.screen_capture.device_id)
            elif macro_exists and macro_active and not self.auto_execute.isChecked():
                logger.info(f"Macro '{matching_macro.name}' found and active but auto-execute is disabled")
            elif macro_exists and not macro_active:
                logger.info(f"Macro '{matching_macro.name}' found but is inactive")
            else:
                logger.info(f"No valid macro configuration for '{macro_name}'")
                
        except Exception as e:
            logger.error(f"Error handling match: {str(e)}")
            self.handle_error(f"Error handling match: {str(e)}")
    
    def handle_no_match(self):
        """Handle when no matches are found."""
        try:
            # Update status bar
            self.status_bar.showMessage("No matches found")
            
        except Exception as e:
            logging.error(f"Error handling no match: {e}")
    
    def update_screenshot(self):
        """Update screenshot display."""
        try:
            if not self.capture_toggle.isChecked():
                return
            
            # Get current screenshot
            screenshot = self.screen_capture.capture_screenshot()
            if screenshot:
                # Scale to fit preview label while maintaining aspect ratio
                pixmap = QPixmap.fromImage(screenshot)
                scaled_pixmap = pixmap.scaled(
                    self.preview_label.size(),
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation
                )
                self.preview_label.setPixmap(scaled_pixmap)
                
                # Update status bar
                self.status_bar.showMessage(f"Last update: {datetime.now().strftime('%H:%M:%S')}")
                
        except Exception as e:
            logger.error(f"Error updating screenshot: {e}")
            self.status_bar.showMessage(f"Error: {e}")
    
    def save_screenshot(self):
        """Save current screenshot."""
        filename = f"screenshot_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
        if self.screen_capture.save_screenshot(filename):
            QMessageBox.information(self, "Success", f"Screenshot saved as {filename}")
        else:
            QMessageBox.warning(self, "Error", "Failed to save screenshot")
    
    def update_macro_list(self):
        """Update macro list in combo box."""
        self.macro_list.clear()
        for name in self.macro_manager.macros:
            self.macro_list.addItem(name)
    
    def record_macro(self):
        """Start macro recording."""
        dialog = MacroEditor(self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            macro = dialog.get_macro()
            self.macro_manager.save_macro(macro)
            self.update_macro_list()
            QMessageBox.information(self, "Success", "Macro saved successfully")
    
    def play_macro(self):
        """Play the selected macro."""
        try:
            if not self.macro_list.currentItem():
                QMessageBox.warning(self, "Warning", "Please select a macro first")
                return
                
            macro_name = self.macro_list.currentItem().text()
            if macro_name not in self.macro_manager.macros:
                QMessageBox.warning(self, "Warning", "Selected macro not found")
                return
                
            # Get current screenshot for image matching
            screenshot = self.screen_capture.capture_screenshot()
            if screenshot is None:
                QMessageBox.warning(self, "Error", "Failed to capture screenshot")
                return
            
            # Convert QImage to numpy array
            width = screenshot.width()
            height = screenshot.height()
            ptr = screenshot.bits()
            ptr.setsize(height * width * 3)
            arr = np.frombuffer(ptr, np.uint8).reshape((height, width, 3))
            
            # Execute macro
            if self.macro_manager.execute_macro(macro_name, self.screen_capture.device_id, arr):
                self.status_bar.showMessage(f"Macro '{macro_name}' executed successfully")
                logger.info(f"Executed macro: {macro_name}")
            else:
                self.status_bar.showMessage(f"Failed to execute macro '{macro_name}'")
                logger.error(f"Failed to execute macro: {macro_name}")
                
        except Exception as e:
            logger.error(f"Error playing macro: {e}")
            self.status_bar.showMessage(f"Error playing macro: {e}")
            QMessageBox.warning(self, "Error", f"Failed to play macro: {e}")
    
    def update_macro_details(self, macro_name):
        """Update macro details display."""
        if macro_name and macro_name in self.macro_manager.macros:
            macro = self.macro_manager.macros[macro_name]
            self.macro_description.setText(f"Description: {macro.description}")
            self.macro_trigger.setText(f"Trigger Image: {macro.trigger_image or 'None'}")
            self.macro_status.setText(f"Status: {'Active' if macro.is_active else 'Inactive'}")
        else:
            self.macro_description.setText("")
            self.macro_trigger.setText("")
            self.macro_status.setText("")
            
    def edit_macro(self):
        """Edit selected macro."""
        macro_name = self.macro_list.currentText()
        if macro_name and macro_name in self.macro_manager.macros:
            dialog = MacroEditor(self, self.macro_manager.macros[macro_name])
            if dialog.exec() == QDialog.DialogCode.Accepted:
                new_macro = dialog.get_macro()
                self.macro_manager.macros[macro_name] = new_macro
                self.update_macro_list()
            
    def delete_macro(self):
        """Delete selected macro."""
        macro_name = self.macro_list.currentText()
        if macro_name and macro_name in self.macro_manager.macros:
            reply = QMessageBox.question(
                self, 'Delete Macro',
                f'Are you sure you want to delete macro "{macro_name}"?',
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if reply == QMessageBox.StandardButton.Yes:
                # TODO: Implement macro deletion
                pass
    
    def toggle_test_mode(self, state):
        """Toggle test mode and update macro manager."""
        self.macro_manager.test_mode = state == Qt.CheckState.Checked.value
        if self.macro_manager.test_mode:
            self.test_results.setText("Test mode enabled. Results will be displayed here.")
        else:
            self.test_results.setText("Test mode disabled.")
    
    def update_test_results(self):
        """Update test results display."""
        if not self.macro_manager.test_mode:
            return
            
        results_text = "Test Results:\n\n"
        for result in self.macro_manager.test_results:
            results_text += f"Template: {result['template']}\n"
            results_text += f"Confidence: {result['confidence']:.3f}\n"
            results_text += f"Position: {result['position']}\n"
            results_text += f"Threshold: {result['threshold']}\n"
            results_text += f"Timestamp: {result['timestamp']}\n"
            results_text += f"Scale: {result['scale']:.2f}\n"
            results_text += f"Method: {result['method']}\n"
            results_text += f"Direct Match: {result['direct_match']:.3f}\n"
            results_text += f"Edge Match: {result['edge_match']:.3f}\n"
            results_text += f"Feature Match: {result['feature_match']:.3f}\n"
            results_text += "---\n"
        
        self.test_results.setText(results_text)
    
    def reload_macros(self):
        """Reload macros and update UI."""
        try:
            # Reload macros
            self.macro_manager.reload_macros()
            
            # Update UI
            self.update_macro_list()
            
            # Show success message
            self.status_bar.showMessage("Macros reloaded successfully")
            logger.info("Macros reloaded and UI updated")
            
        except Exception as e:
            logger.error(f"Error reloading macros: {e}")
            self.status_bar.showMessage(f"Error reloading macros: {e}")

    def toggle_capture(self, state):
        """Toggle screen capture on/off."""
        try:
            if state == Qt.CheckState.Checked.value:
                # Start capture
                self.screen_capture.running = True
                self.screen_capture.start()
                self.countdown_timer.start()  # Start countdown timer
                self.status_bar.showMessage("Screen capture started")
                logger.info("Screen capture started")
            else:
                # Stop capture
                self.screen_capture.running = False
                self.screen_capture.wait()
                self.countdown_timer.stop()  # Stop countdown timer
                self.status_bar.showMessage("Screen capture stopped")
                logger.info("Screen capture stopped")
                
        except Exception as e:
            logger.error(f"Error toggling capture: {e}")
            self.status_bar.showMessage(f"Error: {e}")
            # Reset checkbox state on error
            self.capture_toggle.setChecked(not state)

    def add_macro(self):
        """Add a new macro."""
        try:
            # Create and show macro editor dialog
            dialog = MacroEditor(self)
            if dialog.exec() == QDialog.DialogCode.Accepted:
                # Get macro data from dialog
                macro = dialog.get_macro()
                
                # Save macro
                self.macro_manager.save_macro(macro)
                
                # Update UI
                self.update_macro_list()
                
                # Show success message
                self.status_bar.showMessage(f"Macro '{macro.name}' created successfully")
                logger.info(f"Created new macro: {macro.name}")
                
        except Exception as e:
            logger.error(f"Error adding macro: {e}")
            self.status_bar.showMessage(f"Error adding macro: {e}")
            QMessageBox.warning(self, "Error", f"Failed to add macro: {e}")

    def on_macro_selected(self, current, previous):
        """Handle macro selection in the list."""
        try:
            if current and current.text() in self.macro_manager.macros:
                macro = self.macro_manager.macros[current.text()]
                
                # Update settings
                self.confidence_threshold.setValue(macro.confidence_threshold)
                self.active_checkbox.setChecked(macro.is_active)
                
                # Update actions list
                self.actions_list.clear()
                for action in macro.actions:
                    self.actions_list.addItem(self.format_action(action))
                
                # Update status bar
                self.status_bar.showMessage(f"Selected macro: {macro.name}")
                logger.info(f"Selected macro: {macro.name}")
                
        except Exception as e:
            logger.error(f"Error handling macro selection: {e}")
            self.status_bar.showMessage(f"Error: {e}")
    
    def format_action(self, action: Dict) -> str:
        """Format action for display in list."""
        action_type = action.get('type', '')
        if action_type == 'tap':
            return f"Tap at ({action['x']}, {action['y']})"
        elif action_type == 'swipe':
            return f"Swipe from ({action['x1']}, {action['y1']}) to ({action['x2']}, {action['y2']})"
        elif action_type == 'key':
            return f"Key press: {action['key']}"
        elif action_type == 'text':
            return f"Text input: {action['text']}"
        elif action_type == 'wait':
            return f"Wait {action['seconds']} seconds"
        return str(action)
    
    def add_action(self, action_type: str):
        """Add new action to list."""
        dialog = ActionDialog(action_type, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            action = dialog.get_action()
            self.actions_list.addItem(self.format_action(action))
    
    def get_macro(self) -> Macro:
        """Get macro data from dialog."""
        actions = []
        for i in range(self.actions_list.count()):
            item = self.actions_list.item(i)
            # TODO: Parse action from item text
            actions.append({})  # Placeholder
        
        return Macro(
            name=self.name_edit.text(),
            description=self.desc_edit.text(),
            trigger_image=self.trigger_combo.currentText() if self.trigger_combo.currentText() != "None" else None,
            actions=actions,
            is_active=True
        )

    def update_device_list(self):
        """Update the device list in the combo box."""
        try:
            self.device_combo.clear()
            devices = check_adb_devices()
            for device in devices:
                self.device_combo.addItem(device)
            
            # Select the current device if it exists
            if self.screen_capture and self.screen_capture.device_id:
                index = self.device_combo.findText(self.screen_capture.device_id)
                if index >= 0:
                    self.device_combo.setCurrentIndex(index)
                    
        except Exception as e:
            logger.error(f"Error updating device list: {e}")
            self.status_bar.showMessage(f"Error: {e}")

    def update_timing_mode(self, mode_name):
        """Update the timing mode for screen capture."""
        try:
            mode = AppMode[mode_name]
            self.screen_capture.set_timing_mode(mode)
            self.status_bar.showMessage(f"Timing mode set to {mode_name} ({mode.value} seconds)")
            logger.info(f"Timing mode updated to {mode_name}")
        except Exception as e:
            logger.error(f"Error updating timing mode: {e}")
            self.status_bar.showMessage(f"Error updating timing mode: {e}")

    def reorder_actions(self, parent, start, end, destination, row):
        """Handle reordering of actions in the list."""
        try:
            if not self.macro_list.currentItem():
                return
                
            macro_name = self.macro_list.currentItem().text()
            macro = self.macro_manager.macros[macro_name]
            
            # Move action in the actions list
            action = macro.actions.pop(start)
            macro.actions.insert(row, action)
            
            # Save changes
            self.macro_manager.save_macro(macro)
            self.status_bar.showMessage(f"Reordered actions in {macro_name}")
            logger.info(f"Reordered actions in macro: {macro_name}")
            
        except Exception as e:
            logger.error(f"Error reordering actions: {e}")
            self.status_bar.showMessage(f"Error: {e}")

    def update_countdown(self):
        """Update the countdown display."""
        if not self.capture_toggle.isChecked():
            self.countdown_label.setText("Capture stopped")
            return
            
        if not self.screen_capture.current_screenshot_time:
            self.countdown_label.setText("Waiting for first capture...")
            return
            
        current_time = time.time()
        time_until_next = self.screen_capture.check_interval - (current_time - self.screen_capture.current_screenshot_time)
        
        if time_until_next <= 0:
            self.countdown_label.setText("Taking screenshot...")
        else:
            minutes = int(time_until_next // 60)
            seconds = int(time_until_next % 60)
            self.countdown_label.setText(f"Next capture in: {minutes:02d}:{seconds:02d}")

    def add_key_action(self):
        """Add a key press action to the current macro."""
        try:
            if not self.macro_list.currentItem():
                QMessageBox.warning(self, "Warning", "Please select a macro first")
                return
                
            dialog = ActionDialog("key", self)
            if dialog.exec() == QDialog.DialogCode.Accepted:
                action = dialog.get_action()
                macro_name = self.macro_list.currentItem().text()
                macro = self.macro_manager.macros[macro_name]
                macro.actions.append(action)
                self.actions_list.addItem(self.format_action(action))
                self.macro_manager.save_macro(macro)
                self.status_bar.showMessage(f"Added key action to {macro_name}")
                logger.info(f"Added key action to macro: {macro_name}")
                
        except Exception as e:
            logger.error(f"Error adding key action: {e}")
            self.status_bar.showMessage(f"Error: {e}")

    def add_text_action(self):
        """Add a text input action to the current macro."""
        try:
            if not self.macro_list.currentItem():
                QMessageBox.warning(self, "Warning", "Please select a macro first")
                return
                
            dialog = ActionDialog("text", self)
            if dialog.exec() == QDialog.DialogCode.Accepted:
                action = dialog.get_action()
                macro_name = self.macro_list.currentItem().text()
                macro = self.macro_manager.macros[macro_name]
                macro.actions.append(action)
                self.actions_list.addItem(self.format_action(action))
                self.macro_manager.save_macro(macro)
                self.status_bar.showMessage(f"Added text action to {macro_name}")
                logger.info(f"Added text action to macro: {macro_name}")
                
        except Exception as e:
            logger.error(f"Error adding text action: {e}")
            self.status_bar.showMessage(f"Error: {e}")

    def add_tap_action(self):
        """Add a tap action to the current macro."""
        try:
            if not self.macro_list.currentItem():
                QMessageBox.warning(self, "Warning", "Please select a macro first")
                return
                
            dialog = ActionDialog("tap", self)
            if dialog.exec() == QDialog.DialogCode.Accepted:
                action = dialog.get_action()
                macro_name = self.macro_list.currentItem().text()
                macro = self.macro_manager.macros[macro_name]
                macro.actions.append(action)
                self.actions_list.addItem(self.format_action(action))
                self.macro_manager.save_macro(macro)
                self.status_bar.showMessage(f"Added tap action to {macro_name}")
                logger.info(f"Added tap action to macro: {macro_name}")
                
        except Exception as e:
            logger.error(f"Error adding tap action: {e}")
            self.status_bar.showMessage(f"Error: {e}")

    def add_swipe_action(self):
        """Add a swipe action to the current macro."""
        try:
            if not self.macro_list.currentItem():
                QMessageBox.warning(self, "Warning", "Please select a macro first")
                return
                
            dialog = ActionDialog("swipe", self)
            if dialog.exec() == QDialog.DialogCode.Accepted:
                action = dialog.get_action()
                macro_name = self.macro_list.currentItem().text()
                macro = self.macro_manager.macros[macro_name]
                macro.actions.append(action)
                self.actions_list.addItem(self.format_action(action))
                self.macro_manager.save_macro(macro)
                self.status_bar.showMessage(f"Added swipe action to {macro_name}")
                logger.info(f"Added swipe action to macro: {macro_name}")
                
        except Exception as e:
            logger.error(f"Error adding swipe action: {e}")
            self.status_bar.showMessage(f"Error: {e}")

    def add_wait_action(self):
        """Add a wait action to the current macro."""
        try:
            if not self.macro_list.currentItem():
                QMessageBox.warning(self, "Warning", "Please select a macro first")
                return
                
            dialog = ActionDialog("wait", self)
            if dialog.exec() == QDialog.DialogCode.Accepted:
                action = dialog.get_action()
                macro_name = self.macro_list.currentItem().text()
                macro = self.macro_manager.macros[macro_name]
                macro.actions.append(action)
                self.actions_list.addItem(self.format_action(action))
                self.macro_manager.save_macro(macro)
                self.status_bar.showMessage(f"Added wait action to {macro_name}")
                logger.info(f"Added wait action to macro: {macro_name}")
                
        except Exception as e:
            logger.error(f"Error adding wait action: {e}")
            self.status_bar.showMessage(f"Error: {e}")

    def edit_action(self):
        """Edit the selected action in the current macro."""
        try:
            if not self.macro_list.currentItem() or not self.actions_list.currentItem():
                QMessageBox.warning(self, "Warning", "Please select a macro and action")
                return
                
            current_row = self.actions_list.currentRow()
            macro_name = self.macro_list.currentItem().text()
            macro = self.macro_manager.macros[macro_name]
            action = macro.actions[current_row]
            
            # Create dialog with current action values
            dialog = ActionDialog(action['type'], self)
            if dialog.exec() == QDialog.DialogCode.Accepted:
                # Update action with new values
                new_action = dialog.get_action()
                macro.actions[current_row] = new_action
                
                # Update list item
                self.actions_list.takeItem(current_row)
                self.actions_list.insertItem(current_row, self.format_action(new_action))
                
                # Save changes
                self.macro_manager.save_macro(macro)
                self.status_bar.showMessage(f"Updated action in {macro_name}")
                logger.info(f"Updated action in macro: {macro_name}")
                
        except Exception as e:
            logger.error(f"Error editing action: {e}")
            self.status_bar.showMessage(f"Error: {e}")

    def remove_action(self):
        """Remove selected action(s) from the current macro."""
        try:
            if not self.macro_list.currentItem():
                QMessageBox.warning(self, "Warning", "Please select a macro first")
                return
                
            # Get selected items
            selected_items = self.actions_list.selectedItems()
            if not selected_items:
                QMessageBox.warning(self, "Warning", "Please select one or more actions to remove")
                return
                
            # Get current macro
            macro_name = self.macro_list.currentItem().text()
            macro = self.macro_manager.macros[macro_name]
            
            # Remove selected actions in reverse order to maintain correct indices
            for item in reversed(selected_items):
                row = self.actions_list.row(item)
                macro.actions.pop(row)
                self.actions_list.takeItem(row)
            
            # Save changes
            self.macro_manager.save_macro(macro)
            self.status_bar.showMessage(f"Removed {len(selected_items)} action(s) from {macro_name}")
            logger.info(f"Removed {len(selected_items)} action(s) from macro: {macro_name}")
            
        except Exception as e:
            logger.error(f"Error removing action(s): {e}")
            self.status_bar.showMessage(f"Error: {e}")

class ActionDialog(QDialog):
    """Dialog for adding macro actions."""
    
    def __init__(self, action_type: str, parent=None):
        super().__init__(parent)
        self.action_type = action_type
        self.setup_ui()
        
    def setup_ui(self):
        """Setup the dialog UI."""
        self.setWindowTitle(f"Add {self.action_type.title()} Action")
        
        layout = QVBoxLayout(self)
        
        if self.action_type == 'tap':
            # Tap coordinates
            coords_layout = QHBoxLayout()
            coords_layout.addWidget(QLabel("X:"))
            self.x_edit = QSpinBox()
            self.x_edit.setRange(0, 9999)  # Allow 4-digit numbers
            coords_layout.addWidget(self.x_edit)
            
            coords_layout.addWidget(QLabel("Y:"))
            self.y_edit = QSpinBox()
            self.y_edit.setRange(0, 9999)  # Allow 4-digit numbers
            coords_layout.addWidget(self.y_edit)
            
            layout.addLayout(coords_layout)
            
        elif self.action_type == 'swipe':
            # Swipe coordinates
            start_layout = QHBoxLayout()
            start_layout.addWidget(QLabel("Start X:"))
            self.x1_edit = QSpinBox()
            self.x1_edit.setRange(0, 9999)  # Allow 4-digit numbers
            start_layout.addWidget(self.x1_edit)
            
            start_layout.addWidget(QLabel("Start Y:"))
            self.y1_edit = QSpinBox()
            self.y1_edit.setRange(0, 9999)  # Allow 4-digit numbers
            start_layout.addWidget(self.y1_edit)
            
            layout.addLayout(start_layout)
            
            end_layout = QHBoxLayout()
            end_layout.addWidget(QLabel("End X:"))
            self.x2_edit = QSpinBox()
            self.x2_edit.setRange(0, 9999)  # Allow 4-digit numbers
            end_layout.addWidget(self.x2_edit)
            
            end_layout.addWidget(QLabel("End Y:"))
            self.y2_edit = QSpinBox()
            self.y2_edit.setRange(0, 9999)  # Allow 4-digit numbers
            end_layout.addWidget(self.y2_edit)
            
            layout.addLayout(end_layout)
            
            # Add duration for swipe
            duration_layout = QHBoxLayout()
            duration_layout.addWidget(QLabel("Duration (ms):"))
            self.duration_edit = QSpinBox()
            self.duration_edit.setRange(100, 5000)  # 100ms to 5000ms
            self.duration_edit.setValue(500)  # Default to 500ms
            self.duration_edit.setSingleStep(100)
            duration_layout.addWidget(self.duration_edit)
            
            layout.addLayout(duration_layout)
            
        elif self.action_type == 'key':
            # Key input
            key_layout = QHBoxLayout()
            key_layout.addWidget(QLabel("Key:"))
            self.key_edit = QLineEdit()
            key_layout.addWidget(self.key_edit)
            layout.addLayout(key_layout)
            
        elif self.action_type == 'wait':
            # Wait duration
            wait_layout = QHBoxLayout()
            wait_layout.addWidget(QLabel("Seconds:"))
            self.seconds_edit = QDoubleSpinBox()
            self.seconds_edit.setRange(0.1, 60.0)
            self.seconds_edit.setSingleStep(0.1)
            wait_layout.addWidget(self.seconds_edit)
            layout.addLayout(wait_layout)
        
        # Dialog buttons
        button_box = QHBoxLayout()
        
        ok_btn = QPushButton("OK")
        ok_btn.clicked.connect(self.accept)
        button_box.addWidget(ok_btn)
        
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        button_box.addWidget(cancel_btn)
        
        layout.addLayout(button_box)
    
    def get_action(self) -> Dict:
        """Get action data from dialog."""
        if self.action_type == 'tap':
            return {
                'type': 'tap',
                'x': self.x_edit.value(),
                'y': self.y_edit.value()
            }
        elif self.action_type == 'swipe':
            return {
                'type': 'swipe',
                'x1': self.x1_edit.value(),
                'y1': self.y1_edit.value(),
                'x2': self.x2_edit.value(),
                'y2': self.y2_edit.value(),
                'duration': self.duration_edit.value()
            }
        elif self.action_type == 'key':
            return {
                'type': 'key',
                'key': self.key_edit.text()
            }
        elif self.action_type == 'wait':
            return {
                'type': 'wait',
                'seconds': self.seconds_edit.value()
            }
        return {}

class BCAApp:
    """Main application class."""
    
    def __init__(self):
        # Initialize with None device_id, will be set in setup()
        self.screen_capture = None
        self.user_manager = UserManager()
        self.macro_manager = None  # Will be initialized in setup()
        self.app = None
        self.window = None
    
    def setup(self):
        """Setup the application."""
        try:
            # Check for device
            devices = check_adb_devices()
            if not devices:
                logging.error("No devices found")
                return False
            
            # Use first device or let user select
            device_id = None
            if len(devices) == 1:
                device_id = devices[0]
            else:
                print("\nSelect a device:")
                for i, device in enumerate(devices, 1):
                    print(f"{i}. {device}")
                choice = int(input("\nEnter device number: ")) - 1
                if 0 <= choice < len(devices):
                    device_id = devices[choice]
                else:
                    logging.error("Invalid device selection")
                    return False
            
            if device_id:
                logging.info(f"Selected device: {device_id}")
                # Initialize ScreenCapture with selected device
                self.screen_capture = ScreenCapture(device_id=device_id)
                # Initialize MacroManager with ScreenCapture instance
                self.macro_manager = MacroManager(screen_capture=self.screen_capture)
                return True
            else:
                logging.error("No device selected")
                return False
            
        except Exception as e:
            logging.error(f"Setup error: {e}")
            return False
    
    def run(self):
        """Run the application."""
        if not self.setup():
            return
        
        try:
            # Initialize Qt application
            self.app = QApplication(sys.argv)
            self.window = MainWindow(self.screen_capture, self.user_manager, self.macro_manager)
            self.window.show()
            
            # Run event loop
            sys.exit(self.app.exec())
            
        except Exception as e:
            logging.error(f"Application error: {e}")
        finally:
            self.cleanup()
    
    def cleanup(self):
        """Cleanup resources."""
        try:
            if self.window:
                self.window.close()
            if self.app:
                self.app.quit()
            if self.screen_capture:
                self.screen_capture.running = False
                self.screen_capture.wait()
        except Exception as e:
            logging.error(f"Cleanup error: {e}")

def main():
    """Main entry point."""
    try:
        app = BCAApp()
        app.run()
    except KeyboardInterrupt:
        logging.info("Application terminated by user")
    except Exception as e:
        logging.error(f"Unexpected error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main() 
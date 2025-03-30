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
                           QFrame, QSplitter, QInputDialog)
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
                        macro_active = macro.get('is_active', True)
                    
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
        self.credentials_file = CONFIG_DIR / "credentials.json"
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
        """Load users from config file and credentials.json."""
        try:
            # First try to load from credentials.json
            if self.credentials_file.exists():
                with open(self.credentials_file, 'r') as f:
                    credentials = json.load(f)
                    
                    if 'users' in credentials:
                        logger.info(f"Loaded {len(credentials['users'])} users from credentials.json")
                        # Track if we've found a default user
                        found_default = False
                        for user_data in credentials['users']:
                            # If this user is marked as default and we already found one,
                            # set this one to not default
                            if user_data.get('is_default', False) and found_default:
                                user_data['is_default'] = False
                                logger.warning(f"Multiple default users found. Setting {user_data['username']} as non-default.")
                            elif user_data.get('is_default', False):
                                found_default = True
                            
                            user = User(
                                username=user_data['username'],
                                password=user_data['password'],
                                is_default=user_data.get('is_default', False)
                            )
                            self.users.append(user)
                        return
                    else:
                        logger.warning("No 'users' key found in credentials.json")
            
            # Fall back to users.ini if credentials.json doesn't exist or has no users
            if not self.config_file.exists():
                logger.warning(f"Neither credentials.json nor {self.config_file} found")
                return
            
            config = configparser.ConfigParser()
            config.read(self.config_file)
            
            # Track if we've found a default user
            found_default = False
            for username in config.sections():
                is_default = config[username].getboolean('is_default', False)
                # If this user is marked as default and we already found one,
                # set this one to not default
                if is_default and found_default:
                    is_default = False
                    logger.warning(f"Multiple default users found. Setting {username} as non-default.")
                elif is_default:
                    found_default = True
                
                password = self._decrypt_password(config[username]['password'])
                self.users.append(User(username, password, is_default))
                
        except Exception as e:
            logger.error(f"User loading error: {e}")

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
            
            # If this user is default, remove default from other users
            if is_default:
                for user in self.users:
                    user.is_default = False
            
            # Create new user with plain password
            user = User(username, password, is_default)
            self.users.append(user)
            
            # Save to config with encrypted password
            config = configparser.ConfigParser()
            config.read(self.config_file)
            config[username] = {
                'password': self._encrypt_password(password),
                'is_default': str(is_default)
            }
            with open(self.config_file, 'w') as f:
                config.write(f)
            
            # Update credentials.json with plain password
            self._update_credentials_file()
            
            logging.info(f"User added: {username}")
            
        except Exception as e:
            logging.error(f"Add user error: {e}")
            raise
    
    def save_users(self):
        """Save all users to config file."""
        try:
            config = configparser.ConfigParser()
            
            for user in self.users:
                config[user.username] = {
                    'password': self._encrypt_password(user.password),
                    'is_default': str(user.is_default)
                }
            
            with open(self.config_file, 'w') as f:
                config.write(f)
            
            # Update credentials.json with plain passwords
            self._update_credentials_file()
            
            logging.info("Users saved successfully")
            
        except Exception as e:
            logging.error(f"Save users error: {e}")
            raise
    
    def _update_credentials_file(self):
        """Update the credentials.json file with current users."""
        try:
            credentials = {
                'users': [
                    {
                        'username': user.username,
                        'password': user.password,  # Store plain password
                        'is_default': user.is_default
                    }
                    for user in self.users
                ]
            }
            
            with open(self.credentials_file, 'w') as f:
                json.dump(credentials, f, indent=4)
            
            logging.info("Credentials file updated")
            
        except Exception as e:
            logging.error(f"Update credentials error: {e}")
            raise
    
    def get_default_user(self) -> Optional[User]:
        """Get default user if exists."""
        return next((u for u in self.users if u.is_default), None)
    
    def authenticate(self, username: str, password: str) -> bool:
        """Authenticate user."""
        try:
            user = next((u for u in self.users if u.username == username), None)
            if not user:
                return False
            return user.password == password
        except Exception as e:
            logger.error(f"Authentication error: {e}")
            return False

    def delete_user(self, username: str) -> bool:
        """Delete a user by username."""
        try:
            user = next((u for u in self.users if u.username == username), None)
            if not user:
                logger.warning(f"User not found for deletion: {username}")
                return False
                
            # Don't allow deleting the last user
            if len(self.users) <= 1:
                logger.warning("Cannot delete the last user")
                return False
                
            # If deleting default user, set another user as default
            if user.is_default and len(self.users) > 1:
                next_user = next((u for u in self.users if u.username != username), None)
                if next_user:
                    next_user.is_default = True
                    
            # Remove user from list
            self.users.remove(user)
            
            # Save changes
            self.save_users()
            logger.info(f"Deleted user: {username}")
            return True
                
        except Exception as e:
            logger.error(f"Error deleting user: {e}")
            return False

    def edit_user(self, username: str) -> bool:
        """Edit a user by username."""
        try:
            user = next((u for u in self.users if u.username == username), None)
            if not user:
                logger.warning(f"User not found for editing: {username}")
                return False
                
            dialog = UserDialog(None, user)
            if dialog.exec() == QDialog.DialogCode.Accepted:
                new_username, new_password, is_default = dialog.get_user_data()
                
                # If username changed, check if new username exists
                if new_username != user.username and any(u.username == new_username for u in self.users):
                    logger.warning(f"Username already exists: {new_username}")
                    return False
                
                # Update user
                user.username = new_username
                user.password = new_password
                user.is_default = is_default
                
                # Handle default user change
                if is_default and not user.is_default:
                    # Remove default from other users
                    for u in self.users:
                        if u.username != new_username:
                            u.is_default = False
                    user.is_default = True
                elif not is_default and user.is_default:
                    # Find another user to set as default
                    next_user = next((u for u in self.users if u.username != new_username), None)
                    if next_user:
                        next_user.is_default = True
                
                # Save changes
                self.save_users()
                logger.info(f"Updated user: {new_username}")
                return True
                
        except Exception as e:
            logger.error(f"Error editing user: {e}")
            return False

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

class UserDialog(QDialog):
    """Dialog for adding/editing users."""
    
    def __init__(self, parent=None, user=None):
        super().__init__(parent)
        self.user = user
        self.setup_ui()
        
    def setup_ui(self):
        """Setup the dialog UI."""
        self.setWindowTitle("Add User" if not self.user else "Edit User")
        
        layout = QVBoxLayout(self)
        
        # Username
        username_layout = QHBoxLayout()
        username_layout.addWidget(QLabel("Username:"))
        self.username_edit = QLineEdit()
        if self.user:
            self.username_edit.setText(self.user.username)
        username_layout.addWidget(self.username_edit)
        layout.addLayout(username_layout)
        
        # Password
        password_layout = QHBoxLayout()
        password_layout.addWidget(QLabel("Password:"))
        self.password_edit = QLineEdit()
        self.password_edit.setEchoMode(QLineEdit.EchoMode.Password)
        if self.user:
            self.password_edit.setText(self.user.password)
        password_layout.addWidget(self.password_edit)
        layout.addLayout(password_layout)
        
        # Default user checkbox
        self.default_checkbox = QCheckBox("Set as default user")
        if self.user:
            self.default_checkbox.setChecked(self.user.is_default)
        layout.addWidget(self.default_checkbox)
        
        # Dialog buttons
        button_box = QHBoxLayout()
        
        ok_btn = QPushButton("OK")
        ok_btn.clicked.connect(self.accept)
        button_box.addWidget(ok_btn)
        
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        button_box.addWidget(cancel_btn)
        
        layout.addLayout(button_box)
    
    def get_user_data(self) -> Tuple[str, str, bool]:
        """Get user data from dialog."""
        return (
            self.username_edit.text(),
            self.password_edit.text(),
            self.default_checkbox.isChecked()
        )

class MacroManager:
    """Manages macro operations and storage."""
    
    def __init__(self, screen_capture=None):
        self.macros_dir = MACROS_DIR
        self.macros = {}
        self.screen_capture = screen_capture
        self.match_threshold = 0.8  # Default confidence threshold
        self._load_macros()
    
    def _load_macros(self):
        """Load all macros from the macros directory."""
        try:
            self.macros.clear()
            for file_path in self.macros_dir.glob("*.json"):
                try:
                    with open(file_path, 'r') as f:
                        macro_data = json.load(f)
                        macro_name = file_path.stem
                        self.macros[macro_name] = macro_data
                except Exception as e:
                    logger.error(f"Error loading macro {file_path}: {e}")
            
            logger.info(f"Loaded {len(self.macros)} macros")
            
        except Exception as e:
            logger.error(f"Error loading macros: {e}")
    
    def save_macro(self, macro: Dict):
        """Save a macro to file."""
        try:
            macro_name = macro['name']
            file_path = self.macros_dir / f"{macro_name}.json"
            
            with open(file_path, 'w') as f:
                json.dump(macro, f, indent=4)
            
            # Update in-memory macros
            self.macros[macro_name] = macro
            logger.info(f"Saved macro: {macro_name}")
            
        except Exception as e:
            logger.error(f"Error saving macro: {e}")
            raise
    
    def delete_macro(self, macro_name: str):
        """Delete a macro file."""
        try:
            file_path = self.macros_dir / f"{macro_name}.json"
            if file_path.exists():
                file_path.unlink()
                if macro_name in self.macros:
                    del self.macros[macro_name]
                logger.info(f"Deleted macro: {macro_name}")
            
        except Exception as e:
            logger.error(f"Error deleting macro: {e}")
            raise
    
    def execute_macro(self, macro_name: str, device_id: str = None):
        """Execute a macro's actions."""
        try:
            if macro_name not in self.macros:
                raise ValueError(f"Macro not found: {macro_name}")
            
            macro = self.macros[macro_name]
            actions = macro.get('actions', [])
            
            # Get the current selected user from MainWindow if available
            current_user = None
            try:
                for window in QApplication.topLevelWidgets():
                    if isinstance(window, MainWindow):
                        selected_user_idx = window.user_combo.currentIndex()
                        if selected_user_idx >= 0:
                            selected_username = window.user_combo.currentText()
                            logger.info(f"Using selected user: {selected_username}")
                            for user in window.user_manager.users:
                                if user.username == selected_username:
                                    current_user = user
                                    break
                        break
            except Exception as e:
                logger.error(f"Error getting selected user: {e}")
            
            for action in actions:
                action_type = action.get('type')
                
                if action_type == 'tap':
                    x, y = action.get('x', 0), action.get('y', 0)
                    self._run_adb_command(f"adb -s {device_id} shell input tap {x} {y}")
                    
                elif action_type == 'swipe':
                    x1, y1 = action.get('x1', 0), action.get('y1', 0)
                    x2, y2 = action.get('x2', 0), action.get('y2', 0)
                    duration = action.get('duration', 500)
                    self._run_adb_command(f"adb -s {device_id} shell input swipe {x1} {y1} {x2} {y2} {duration}")
                    
                elif action_type == 'key':
                    key = action.get('key')
                    if key:
                        self._run_adb_command(f"adb -s {device_id} shell input keyevent {key}")
                        
                elif action_type == 'text':
                    text = action.get('text')
                    if text and current_user:
                        # Replace variables with user data
                        text = text.replace("${username}", current_user.username)
                        text = text.replace("${password}", current_user.password)
                        logger.info(f"Substituted text: {text}")
                        
                    if text:
                        # Escape single quotes in text
                        text = text.replace("'", "\\'")
                        self._run_adb_command(f"adb -s {device_id} shell input text '{text}'")
                        
                elif action_type == 'wait':
                    seconds = action.get('seconds', 1)
                    time.sleep(seconds)
            
            logger.info(f"Executed macro: {macro_name}")
            
        except Exception as e:
            logger.error(f"Error executing macro: {e}")
            raise
    
    def _run_adb_command(self, command: str):
        """Run an ADB command."""
        try:
            if not self.screen_capture or not hasattr(self.screen_capture, '_run_adb_command'):
                # Fall back to subprocess if screen_capture is not available
                result = subprocess.run(command, shell=True, capture_output=True, text=True)
                if result.returncode != 0:
                    raise Exception(f"ADB command failed: {result.stderr}")
                return result.stdout.strip()
            else:
                # Use screen_capture's ADB command runner
                return self.screen_capture._run_adb_command(command)
        except Exception as e:
            logger.error(f"ADB command error: {e}")
            raise

class MainWindow(QMainWindow):
    """Main window of the application."""
    
    def __init__(self, screen_capture, user_manager, macro_manager):
        super().__init__()
        self.screen_capture = screen_capture
        self.user_manager = user_manager
        self.macro_manager = macro_manager
        self.current_macro = None
        self.setup_ui()
        
        # Connect signals
        self.screen_capture.screenshot_ready.connect(self.update_preview)
        self.screen_capture.match_found.connect(self.handle_match_found)
        self.screen_capture.error_occurred.connect(self.handle_error)
        
        # Start screen capture
        self.screen_capture.start()
        
        # Load macros
        self.update_macro_list()
        
        # Set default values
        self.user_combo.setCurrentIndex(0)
        self.timing_combo.setCurrentText(AppMode.FAST.name)
        self.device_combo.setCurrentText(self.screen_capture.device_id)
        self.confidence_threshold.setValue(0.8)
        
        logger.info("Initialized MainWindow and updated user list")

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
        
        # User selection with default indicator
        user_layout = QHBoxLayout()
        user_layout.addWidget(QLabel("User:"))
        self.user_combo = QComboBox()
        self.user_combo.setMinimumWidth(150)
        user_layout.addWidget(self.user_combo)
        
        # Add user management buttons
        add_user_btn = QPushButton("Add User")
        add_user_btn.clicked.connect(self.add_user)
        user_layout.addWidget(add_user_btn)
        
        edit_user_btn = QPushButton("Edit User")
        edit_user_btn.clicked.connect(self.edit_user)
        user_layout.addWidget(edit_user_btn)
        
        delete_user_btn = QPushButton("Delete User")
        delete_user_btn.clicked.connect(self.delete_user)
        user_layout.addWidget(delete_user_btn)
        
        top_section.addLayout(user_layout)
        
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
        
        # Add countdown label to status bar (right side)
        self.countdown_label = QLabel()
        self.status_bar.addPermanentWidget(self.countdown_label)
        
        # Setup countdown timer
        self.countdown_timer = QTimer()
        self.countdown_timer.timeout.connect(self.update_countdown)
        self.countdown_timer.start(1000)  # Update every second
        
        # Initialize UI state
        self.update_device_list()
        self.update_macro_list()
        self.update_user_list()  # Make sure user list is updated after UI setup

    def add_user(self):
        """Add a new user."""
        try:
            dialog = UserDialog(self)
            if dialog.exec() == QDialog.DialogCode.Accepted:
                username, password, is_default = dialog.get_user_data()
                
                # Check if username already exists
                if any(u.username == username for u in self.user_manager.users):
                    QMessageBox.warning(self, "Warning", "Username already exists")
                    return
                
                # Add user
                self.user_manager.add_user(username, password, is_default)
                self.update_user_list()
                self.status_bar.showMessage(f"Added user: {username}")
                logger.info(f"Added user: {username}")
                
        except Exception as e:
            logger.error(f"Error adding user: {e}")
            self.status_bar.showMessage(f"Error: {e}")
            QMessageBox.warning(self, "Error", f"Failed to add user: {e}")

    def delete_user(self):
        """Delete selected user."""
        try:
            current_data = self.user_combo.currentData()
            if not current_data:
                QMessageBox.warning(self, "Warning", "Please select a user to delete")
                return
                
            user = next((u for u in self.user_manager.users if u.username == current_data), None)
            if not user:
                QMessageBox.warning(self, "Warning", "Selected user not found")
                return
                
            # Don't allow deleting the last user
            if len(self.user_manager.users) <= 1:
                QMessageBox.warning(self, "Warning", "Cannot delete the last user")
                return
                
            reply = QMessageBox.question(
                self, 'Delete User',
                f'Are you sure you want to delete user "{current_data}"?',
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            
            if reply == QMessageBox.StandardButton.Yes:
                success = self.user_manager.delete_user(current_data)
                if success:
                    self.update_user_list()
                    self.status_bar.showMessage(f"Deleted user: {current_data}")
                    logger.info(f"Deleted user: {current_data}")
                else:
                    QMessageBox.warning(self, "Error", f"Failed to delete user: {current_data}")
                
        except Exception as e:
            logger.error(f"Error deleting user: {e}")
            self.status_bar.showMessage(f"Error: {e}")
            QMessageBox.warning(self, "Error", f"Failed to delete user: {e}")

    def edit_user(self):
        """Edit selected user."""
        try:
            current_data = self.user_combo.currentData()
            if not current_data:
                QMessageBox.warning(self, "Warning", "Please select a user to edit")
                return
                
            user = next((u for u in self.user_manager.users if u.username == current_data), None)
            if not user:
                QMessageBox.warning(self, "Warning", "Selected user not found")
                return
                
            dialog = UserDialog(self, user)
            if dialog.exec() == QDialog.DialogCode.Accepted:
                username, password, is_default = dialog.get_user_data()
                
                # If username changed, check if new username exists
                if username != current_data and any(u.username == username for u in self.user_manager.users):
                    QMessageBox.warning(self, "Warning", "Username already exists")
                    return
                
                # Update user
                user.username = username
                user.password = password
                
                # Handle default user change
                if is_default and not user.is_default:
                    # Remove default from other users
                    for u in self.user_manager.users:
                        if u.username != username:
                            u.is_default = False
                    user.is_default = True
                elif not is_default and user.is_default:
                    # Find another user to set as default
                    next_user = next((u for u in self.user_manager.users if u.username != username), None)
                    if next_user:
                        next_user.is_default = True
                
                # Save changes
                self.user_manager.save_users()
                self.update_user_list()
                self.status_bar.showMessage(f"Updated user: {username}")
                logger.info(f"Updated user: {username}")
                
        except Exception as e:
            logger.error(f"Error editing user: {e}")
            self.status_bar.showMessage(f"Error: {e}")

    def update_preview(self, image: QImage):
        """Update the preview label with the latest screenshot."""
        try:
            # Scale image to fit preview label while maintaining aspect ratio
            scaled_pixmap = QPixmap.fromImage(image).scaled(
                self.preview_label.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation
            )
            self.preview_label.setPixmap(scaled_pixmap)
        except Exception as e:
            logger.error(f"Error updating preview: {e}")

    def handle_match_found(self, image_name: str, confidence: float, position: tuple):
        """Handle when a match is found."""
        try:
            # Update match display
            match_text = f"Match found: {image_name}\nConfidence: {confidence:.3f}\nPosition: {position}"
            self.match_display.setText(match_text)
            
            # Check if auto-execute is enabled
            if self.auto_execute.isChecked():
                macro_name = Path(image_name).stem
                if macro_name in self.macro_manager.macros:
                    self.macro_manager.execute_macro(macro_name, self.screen_capture.device_id)
                    
        except Exception as e:
            logger.error(f"Error handling match: {e}")

    def handle_error(self, error_message: str):
        """Handle errors from screen capture."""
        try:
            self.status_bar.showMessage(f"Error: {error_message}")
            logger.error(f"Screen capture error: {error_message}")
        except Exception as e:
            logger.error(f"Error handling error: {e}")

    def toggle_capture(self, state: int):
        """Toggle screen capture on/off."""
        try:
            if state == Qt.CheckState.Checked.value:
                self.screen_capture.running = True
                self.status_bar.showMessage("Screen capture enabled")
                logger.info("Screen capture enabled")
            else:
                self.screen_capture.running = False
                self.status_bar.showMessage("Screen capture disabled")
                logger.info("Screen capture disabled")
        except Exception as e:
            logger.error(f"Error toggling capture: {e}")
            self.status_bar.showMessage(f"Error: {e}")

    def reload_macros(self):
        """Reload macros from disk."""
        try:
            self.macro_manager._load_macros()
            self.update_macro_list()
            self.status_bar.showMessage("Macros reloaded")
            logger.info("Macros reloaded")
        except Exception as e:
            logger.error(f"Error reloading macros: {e}")
            self.status_bar.showMessage(f"Error: {e}")

    def update_macro_list(self):
        """Update the macro list widget."""
        try:
            self.macro_list.clear()
            for macro_name in self.macro_manager.macros:
                self.macro_list.addItem(macro_name)
            logger.info(f"Updated macro list with {len(self.macro_manager.macros)} macros")
        except Exception as e:
            logger.error(f"Error updating macro list: {e}")
            self.status_bar.showMessage(f"Error: {e}")

    def on_macro_selected(self, current, previous):
        """Handle macro selection change."""
        try:
            if not current:
                return
                
            macro_name = current.text()
            if macro_name in self.macro_manager.macros:
                self.current_macro = self.macro_manager.macros[macro_name]
                
                # Update settings
                self.confidence_threshold.setValue(self.current_macro.get('confidence_threshold', 0.8))
                self.active_checkbox.setChecked(self.current_macro.get('is_active', True))
                
                # Update actions list
                self.actions_list.clear()
                for action in self.current_macro.get('actions', []):
                    self.actions_list.addItem(str(action))
                    
                self.status_bar.showMessage(f"Selected macro: {macro_name}")
                logger.info(f"Selected macro: {macro_name}")
                
        except Exception as e:
            logger.error(f"Error selecting macro: {e}")
            self.status_bar.showMessage(f"Error: {e}")

    def play_macro(self):
        """Play the selected macro."""
        try:
            if not self.current_macro:
                QMessageBox.warning(self, "Warning", "Please select a macro first")
                return
                
            macro_name = self.macro_list.currentItem().text()
            self.macro_manager.execute_macro(macro_name, self.screen_capture.device_id)
            self.status_bar.showMessage(f"Executed macro: {macro_name}")
            logger.info(f"Executed macro: {macro_name}")
            
        except Exception as e:
            logger.error(f"Error playing macro: {e}")
            self.status_bar.showMessage(f"Error: {e}")

    def add_macro(self):
        """Add a new macro."""
        try:
            name, ok = QInputDialog.getText(self, "Add Macro", "Enter macro name:")
            if ok and name:
                if name in self.macro_manager.macros:
                    QMessageBox.warning(self, "Warning", "Macro name already exists")
                    return
                    
                # Create new macro
                macro = {
                    'name': name,
                    'description': '',
                    'actions': [],
                    'is_active': True,
                    'confidence_threshold': 0.8
                }
                
                self.macro_manager.save_macro(macro)
                self.update_macro_list()
                self.status_bar.showMessage(f"Added macro: {name}")
                logger.info(f"Added macro: {name}")
                
        except Exception as e:
            logger.error(f"Error adding macro: {e}")
            self.status_bar.showMessage(f"Error: {e}")

    def add_key_action(self):
        """Add a key action to the current macro."""
        try:
            if not self.current_macro:
                QMessageBox.warning(self, "Warning", "Please select a macro first")
                return
                
            dialog = ActionDialog('key', self)
            if dialog.exec() == QDialog.DialogCode.Accepted:
                action = dialog.get_action()
                self.current_macro['actions'].append(action)
                self.macro_manager.save_macro(self.current_macro)
                self.actions_list.addItem(str(action))
                self.status_bar.showMessage("Added key action")
                logger.info("Added key action")
                
        except Exception as e:
            logger.error(f"Error adding key action: {e}")
            self.status_bar.showMessage(f"Error: {e}")

    def add_text_action(self):
        """Add a text action to the current macro."""
        try:
            if not self.current_macro:
                QMessageBox.warning(self, "Warning", "Please select a macro first")
                return
                
            text, ok = QInputDialog.getText(self, "Add Text Action", "Enter text:")
            if ok and text:
                action = {'type': 'text', 'text': text}
                self.current_macro['actions'].append(action)
                self.macro_manager.save_macro(self.current_macro)
                self.actions_list.addItem(str(action))
                self.status_bar.showMessage("Added text action")
                logger.info("Added text action")
                
        except Exception as e:
            logger.error(f"Error adding text action: {e}")
            self.status_bar.showMessage(f"Error: {e}")

    def add_tap_action(self):
        """Add a tap action to the current macro."""
        try:
            if not self.current_macro:
                QMessageBox.warning(self, "Warning", "Please select a macro first")
                return
                
            dialog = ActionDialog('tap', self)
            if dialog.exec() == QDialog.DialogCode.Accepted:
                action = dialog.get_action()
                self.current_macro['actions'].append(action)
                self.macro_manager.save_macro(self.current_macro)
                self.actions_list.addItem(str(action))
                self.status_bar.showMessage("Added tap action")
                logger.info("Added tap action")
                
        except Exception as e:
            logger.error(f"Error adding tap action: {e}")
            self.status_bar.showMessage(f"Error: {e}")

    def add_swipe_action(self):
        """Add a swipe action to the current macro."""
        try:
            if not self.current_macro:
                QMessageBox.warning(self, "Warning", "Please select a macro first")
                return
                
            dialog = ActionDialog('swipe', self)
            if dialog.exec() == QDialog.DialogCode.Accepted:
                action = dialog.get_action()
                self.current_macro['actions'].append(action)
                self.macro_manager.save_macro(self.current_macro)
                self.actions_list.addItem(str(action))
                self.status_bar.showMessage("Added swipe action")
                logger.info("Added swipe action")
                
        except Exception as e:
            logger.error(f"Error adding swipe action: {e}")
            self.status_bar.showMessage(f"Error: {e}")

    def add_wait_action(self):
        """Add a wait action to the current macro."""
        try:
            if not self.current_macro:
                QMessageBox.warning(self, "Warning", "Please select a macro first")
                return
                
            dialog = ActionDialog('wait', self)
            if dialog.exec() == QDialog.DialogCode.Accepted:
                action = dialog.get_action()
                self.current_macro['actions'].append(action)
                self.macro_manager.save_macro(self.current_macro)
                self.actions_list.addItem(str(action))
                self.status_bar.showMessage("Added wait action")
                logger.info("Added wait action")
                
        except Exception as e:
            logger.error(f"Error adding wait action: {e}")
            self.status_bar.showMessage(f"Error: {e}")

    def edit_action(self):
        """Edit the selected action."""
        try:
            if not self.current_macro or not self.actions_list.currentItem():
                QMessageBox.warning(self, "Warning", "Please select an action to edit")
                return
                
            current_row = self.actions_list.currentRow()
            action = self.current_macro['actions'][current_row]
            
            dialog = ActionDialog(action['type'], self)
            if dialog.exec() == QDialog.DialogCode.Accepted:
                new_action = dialog.get_action()
                self.current_macro['actions'][current_row] = new_action
                self.macro_manager.save_macro(self.current_macro)
                self.actions_list.takeItem(current_row)
                self.actions_list.insertItem(current_row, str(new_action))
                self.status_bar.showMessage("Edited action")
                logger.info("Edited action")
                
        except Exception as e:
            logger.error(f"Error editing action: {e}")
            self.status_bar.showMessage(f"Error: {e}")

    def remove_action(self):
        """Remove the selected action."""
        try:
            if not self.current_macro or not self.actions_list.currentItem():
                QMessageBox.warning(self, "Warning", "Please select an action to remove")
                return
                
            current_row = self.actions_list.currentRow()
            self.current_macro['actions'].pop(current_row)
            self.macro_manager.save_macro(self.current_macro)
            self.actions_list.takeItem(current_row)
            self.status_bar.showMessage("Removed action")
            logger.info("Removed action")
            
        except Exception as e:
            logger.error(f"Error removing action: {e}")
            self.status_bar.showMessage(f"Error: {e}")

    def update_countdown(self):
        """Update the countdown display."""
        try:
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
                
        except Exception as e:
            logger.error(f"Error updating countdown: {e}")
            self.countdown_label.setText("Error updating countdown")

    def update_user_list(self):
        """Update the user list in the combo box."""
        try:
            # Clear current list
            self.user_combo.clear()
            
            # Add users to combo box with default indicator
            for user in self.user_manager.users:
                display_text = f"{user.username} {'(Default)' if user.is_default else ''}"
                self.user_combo.addItem(display_text, user.username)
            
            # Select default user if exists
            default_user = self.user_manager.get_default_user()
            if default_user:
                index = self.user_combo.findData(default_user.username)
                if index >= 0:
                    self.user_combo.setCurrentIndex(index)
                    logger.info(f"Default user selected: {default_user.username}")
                    
        except Exception as e:
            logger.error(f"Error updating user list: {e}")
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

    def reorder_actions(self, parent, start, end, destination, row):
        """Handle reordering of actions in the list."""
        try:
            if not self.macro_list.currentItem():
                return
                
            macro_name = self.macro_list.currentItem().text()
            macro = self.macro_manager.macros[macro_name]
            
            # Move action in the actions list
            actions = macro.get('actions', [])
            action = actions.pop(start)
            actions.insert(row, action)
            macro['actions'] = actions
            
            # Save changes
            self.macro_manager.save_macro(macro)
            self.status_bar.showMessage(f"Reordered actions in {macro_name}")
            logger.info(f"Reordered actions in macro: {macro_name}")
            
        except Exception as e:
            logger.error(f"Error reordering actions: {e}")
            self.status_bar.showMessage(f"Error: {e}")

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
                # Set macro_manager in screen_capture to establish bidirectional reference
                self.screen_capture.set_macro_manager(self.macro_manager)
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
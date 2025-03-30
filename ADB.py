6
#!/usr/bin/env python3
import os
import subprocess
import time
import sys
import re
from colorama import Fore, Style, init

# Initialize colorama
init(autoreset=True)

# Directory structure
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
APK_DIR = os.path.join(SCRIPT_DIR, "apk")
DB_DIR = os.path.join(SCRIPT_DIR, "db")
LOG_DIR = os.path.join(SCRIPT_DIR, "logs")
PLATFORM_TOOLS_DIR = os.path.join(SCRIPT_DIR, "platform-tools")

# File paths
APK_PATH = os.path.join(APK_DIR, "BCA.apk")
DB_PATH = os.path.join(DB_DIR, "sql.db")
LOG_FILE = os.path.join(LOG_DIR, f"adb_manager_{time.strftime('%Y%m%d_%H%M%S')}.log")

# App package info
APP_PACKAGE = "com.bca.bcatrack"
APP_ACTIVITY = "com.lansa.ui.Activity"

# Wi-Fi connection IPs for devices
DEVICE_IPS = [
    "192.168.1.96:5555",
    "100.72.140.60:5555",
    # Add more IPs as needed
]

def get_adb_path():
    """Get the path to the ADB executable in platform-tools."""
    if os.name == 'nt':  # Windows
        adb_path = os.path.join(PLATFORM_TOOLS_DIR, "adb.exe")
    else:  # Linux/Mac
        adb_path = os.path.join(PLATFORM_TOOLS_DIR, "adb")
    
    if not os.path.exists(adb_path):
        log_message(f"ADB executable not found at {adb_path}", "ERROR")
        sys.exit(1)
    
    return adb_path

def ensure_directories_exist():
    """Create necessary directories if they don't exist."""
    for directory in [APK_DIR, DB_DIR, LOG_DIR]:
        if not os.path.exists(directory):
            os.makedirs(directory)
            log_message(f"Created directory: {directory}")

def log_message(message, level="INFO"):
    """Log a message to both console and log file."""
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    formatted_message = f"[{timestamp}] [{level}] {message}"
    
    # Print to console with color based on level
    if level == "ERROR":
        print(f"{Fore.RED}{message}{Style.RESET_ALL}")
    elif level == "WARNING":
        print(f"{Fore.YELLOW}{message}{Style.RESET_ALL}")
    elif level == "SUCCESS":
        print(f"{Fore.GREEN}{message}{Style.RESET_ALL}")
    else:
        # Don't print INFO messages to console unless they're important
        if "Running ADB command" not in message:
            print(message)
    
    # Write to log file
    with open(LOG_FILE, 'a') as log_file:
        log_file.write(formatted_message + "\n")

def run_adb_command(command, check_output=True, shell=False):
    """
    Run an ADB command and return the output or status.
    
    Args:
        command: The command to run (list or string)
        check_output: Whether to capture and return output
        shell: Whether to use shell=True for subprocess
    
    Returns:
        Output of the command or True/False if check_output is False
    """
    try:
        adb_path = get_adb_path()
        
        if isinstance(command, str):
            cmd_str = command
            if not shell:
                command = command.split()
        else:
            cmd_str = " ".join(command)
        
        # Replace 'adb' with the full path to the platform-tools adb
        if isinstance(command, str):
            command = command.replace('adb ', f'"{adb_path}" ')
        else:
            command = [adb_path if cmd == 'adb' else cmd for cmd in command]
        
        log_message(f"Running ADB command: {cmd_str}", "INFO")
        
        if check_output:
            result = subprocess.run(command, capture_output=True, text=True, shell=shell)
            if result.returncode != 0:
                log_message(f"Command failed with error: {result.stderr}", "ERROR")
                return ""
            return result.stdout.strip()
        else:
            result = subprocess.run(command, capture_output=True, text=True, shell=shell)
            if result.returncode != 0:
                log_message(f"Command failed with error: {result.stderr}", "ERROR")
                return False
            return True
            
    except Exception as e:
        log_message(f"ADB command error: {str(e)}", "ERROR")
        if check_output:
            return ""
        return False

def check_adb_devices():
    """
    Check for connected ADB devices and attempt to reconnect offline ones.
    
    Returns:
        List of connected device serials/IPs
    """
    log_message("Checking for connected ADB devices...")
    
    # Start ADB server if not running
    run_adb_command(["adb", "start-server"], check_output=False)
    
    # Get device list
    devices_output = run_adb_command(["adb", "devices", "-l"])
    connected_devices = []
    offline_devices = []
    
    # Parse device list
    for line in devices_output.splitlines():
        if "device" in line and not line.startswith("List"):
            parts = line.split()
            device_id = parts[0]
            
            if "offline" in line:
                offline_devices.append(device_id)
                log_message(f"Device {device_id} is offline, will attempt reconnection", "WARNING")
            else:
                connected_devices.append(device_id)
                log_message(f"Device connected: {device_id}", "SUCCESS")
    
    # Try to reconnect offline devices
    for device in offline_devices:
        log_message(f"Attempting to reconnect {device}...")
        run_adb_command(["adb", "disconnect", device], check_output=False)
        time.sleep(1)
        run_adb_command(["adb", "connect", device], check_output=False)
    
    # If no devices, try connecting to predefined IPs
    if not connected_devices and not offline_devices:
        log_message("No devices found. Attempting to connect to known IPs...", "WARNING")
        for ip in DEVICE_IPS:
            log_message(f"Attempting to connect to {ip}...")
            result = run_adb_command(["adb", "connect", ip])
            if "connected" in result.lower() and "cannot" not in result.lower():
                connected_devices.append(ip)
                log_message(f"Successfully connected to {ip}", "SUCCESS")
    
    # If still no devices, try to start an emulator
    if not connected_devices:
        log_message("No physical devices found. Checking for emulators...", "INFO")
        emulators = run_adb_command(["emulator", "-list-avds"])
        
        if emulators:
            emulator_name = emulators.splitlines()[0]
            log_message(f"Found emulator: {emulator_name}. Attempting to start...", "INFO")
            # Start emulator in a separate process
            subprocess.Popen(["emulator", "-avd", emulator_name, "-no-snapshot-load"])
            
            # Wait for emulator to start
            for _ in range(10):
                time.sleep(3)
                devices_output = run_adb_command(["adb", "devices"])
                if "emulator" in devices_output:
                    connected_devices.append([d.split()[0] for d in devices_output.splitlines() 
                                            if "emulator" in d][0])
                    log_message(f"Emulator started successfully", "SUCCESS")
                    break
    
    # Check if we have any connected devices now
    if connected_devices:
        log_message(f"Total connected devices: {len(connected_devices)}", "SUCCESS")
    else:
        log_message("No devices connected. Please connect a device and try again.", "ERROR")
    
    return connected_devices

def is_app_installed(device=None):
    """Check if BCA Track app is installed on the device."""
    cmd = "adb "
    if device:
        cmd += f"-s {device} "
    cmd += f"shell pm list packages {APP_PACKAGE}"
    
    result = run_adb_command(cmd, shell=True)
    return APP_PACKAGE in result

def install_app(device=None):
    """Install BCA Track app on the device."""
    if not os.path.exists(APK_PATH):
        log_message(f"APK file not found at {APK_PATH}", "ERROR")
        return False
    
    cmd = "adb "
    if device:
        cmd += f"-s {device} "
    cmd += f"install -r \"{APK_PATH}\""
    
    log_message(f"Installing {APP_PACKAGE} from {APK_PATH}...", "INFO")
    success = run_adb_command(cmd, check_output=False, shell=True)
    
    if success:
        log_message(f"Successfully installed {APP_PACKAGE}", "SUCCESS")
        # Grant necessary permissions
        grant_permissions(device)
        # Verify installation
        if is_app_installed(device):
            return True
        else:
            log_message("Installation verification failed", "ERROR")
            return False
    else:
        log_message(f"Failed to install {APP_PACKAGE}", "ERROR")
        return False

def uninstall_app(device=None):
    """Uninstall BCA Track app from the device."""
    cmd = "adb "
    if device:
        cmd += f"-s {device} "
    cmd += f"shell pm uninstall {APP_PACKAGE}"
    
    log_message(f"Uninstalling {APP_PACKAGE}...", "INFO")
    success = run_adb_command(cmd, check_output=False, shell=True)
    
    if success:
        log_message(f"Successfully uninstalled {APP_PACKAGE}", "SUCCESS")
        return True
    else:
        log_message(f"Failed to uninstall {APP_PACKAGE}", "ERROR")
        return False

def is_app_running(device=None):
    """Check if BCA Track app is running using multiple methods."""
    cmd = "adb "
    if device:
        cmd += f"-s {device} "
    
    # Try multiple methods to check if app is running
    methods = [
        # Method 1: Check process without grep
        f"{cmd}shell ps",
        # Method 2: Check package state without grep
        f"{cmd}shell dumpsys package {APP_PACKAGE}",
        # Method 3: Check if app is in foreground without grep
        f"{cmd}shell dumpsys window windows",
        # Method 4: Check activity manager without grep
        f"{cmd}shell dumpsys activity activities"
    ]
    
    for method in methods:
        try:
            result = run_adb_command(method, shell=True)
            if result and APP_PACKAGE in result:
                return True
        except:
            continue
    
    # If none of the above methods work, try a simpler approach
    try:
        # Check if app is in the foreground
        simple_cmd = f"{cmd}shell dumpsys window | findstr mCurrentFocus"
        result = run_adb_command(simple_cmd, shell=True)
        if result and APP_PACKAGE in result:
            return True
    except:
        pass
    
    # Final check using a basic process list
    try:
        basic_cmd = f"{cmd}shell ps"
        result = run_adb_command(basic_cmd, shell=True)
        if result and APP_PACKAGE in result:
            return True
    except:
        pass
    
    return False

def grant_permissions(device=None):
    """Grant necessary permissions to the app."""
    permissions = [
        "android.permission.READ_EXTERNAL_STORAGE",
        "android.permission.WRITE_EXTERNAL_STORAGE"
    ]
    
    cmd = "adb "
    if device:
        cmd += f"-s {device} "
    
    for permission in permissions:
        # First try to grant normally
        grant_cmd = f"{cmd}shell pm grant {APP_PACKAGE} {permission}"
        if run_adb_command(grant_cmd, check_output=False, shell=True):
            log_message(f"Granted permission: {permission}", "SUCCESS")
        else:
            # If normal grant fails, try with root
            root_cmd = f"{cmd}shell su 0 pm grant {APP_PACKAGE} {permission}"
            if run_adb_command(root_cmd, check_output=False, shell=True):
                log_message(f"Granted permission with root: {permission}", "SUCCESS")
            else:
                log_message(f"Failed to grant permission: {permission}", "WARNING")
    
    # For Android 11+, we need to request MANAGE_EXTERNAL_STORAGE through settings
    try:
        # Open app settings
        settings_cmd = f"{cmd}shell am start -a android.settings.APPLICATION_DETAILS_SETTINGS -d package:{APP_PACKAGE}"
        run_adb_command(settings_cmd, check_output=False, shell=True)
        time.sleep(2)  # Give time for settings to open
        
        # Try to enable storage access through settings
        storage_cmd = f"{cmd}shell am start -a android.settings.MANAGE_APP_ALL_FILES_ACCESS_PERMISSION"
        run_adb_command(storage_cmd, check_output=False, shell=True)
        
        log_message("Please enable storage access in device settings if prompted", "INFO")
    except:
        log_message("Could not open storage settings automatically", "WARNING")

def start_app(device=None):
    """Start the BCA Track app with improved error handling."""
    if not is_app_installed(device):
        log_message(f"{APP_PACKAGE} is not installed", "ERROR")
        return False

    cmd = "adb "
    if device:
        cmd += f"-s {device} "
    
    # Start the app
    start_cmd = f"{cmd}shell am start -n {APP_PACKAGE}/{APP_ACTIVITY}"
    log_message(f"Starting {APP_PACKAGE}...", "INFO")
    result = run_adb_command(start_cmd, check_output=True, shell=True)
    
    if "Error" in result:
        log_message(f"Failed to start app: {result}", "ERROR")
        return False
    
    # Give app more time to start (10 seconds)
    log_message("Waiting for app to start...", "INFO")
    time.sleep(10)
    
    # Verify app is running with multiple checks
    verify_methods = [
        # Method 1: Check package state
        f"{cmd}shell dumpsys package {APP_PACKAGE} | findstr state=",
        # Method 2: Check process list
        f"{cmd}shell ps | findstr {APP_PACKAGE}",
        # Method 3: Check window focus
        f"{cmd}shell dumpsys window | findstr mCurrentFocus"
    ]
    
    for verify_cmd in verify_methods:
        try:
            result = run_adb_command(verify_cmd, shell=True)
            if result and APP_PACKAGE in result:
                log_message(f"Successfully started {APP_PACKAGE}", "SUCCESS")
                return True
        except:
            continue
    
    # If first verification fails, try one more time with a longer delay
    log_message("App may be starting, waiting additional time...", "INFO")
    time.sleep(5)
    
    for verify_cmd in verify_methods:
        try:
            result = run_adb_command(verify_cmd, shell=True)
            if result and APP_PACKAGE in result:
                log_message(f"App started after additional delay", "SUCCESS")
                return True
        except:
            continue
    
    log_message("App may not have started properly", "WARNING")
    return False

def manage_bca_track(device=None):
    """Manage the BCA Track app installation with improved error handling."""
    clear_screen()
    display_header(device)
    
    if is_app_installed(device):
        log_message(f"{APP_PACKAGE} is already installed", "INFO")
        
        print(f"\n{Fore.CYAN}App Management Options:{Style.RESET_ALL}")
        print(f"1. {Fore.GREEN}Start app{Style.RESET_ALL}")
        print(f"2. {Fore.YELLOW}Reinstall app{Style.RESET_ALL}")
        print(f"3. {Fore.RED}Uninstall app{Style.RESET_ALL}")
        print(f"4. {Fore.CYAN}Back to main menu{Style.RESET_ALL}")
        
        choice = input("\nSelect an option (1-4): ").strip()
        
        if choice == "1":
            if start_app(device):
                input("\nPress Enter to continue...")
        elif choice == "2":
            if confirm_action("reinstall"):
                if uninstall_app(device):
                    if install_app(device):
                        if start_app(device):
                            log_message("App successfully reinstalled and started", "SUCCESS")
                        else:
                            log_message("App reinstalled but failed to start", "WARNING")
                    else:
                        log_message("Failed to reinstall app", "ERROR")
                input("\nPress Enter to continue...")
        elif choice == "3":
            if confirm_action("uninstall"):
                if uninstall_app(device):
                    log_message("App successfully uninstalled", "SUCCESS")
                else:
                    log_message("Failed to uninstall app", "ERROR")
                input("\nPress Enter to continue...")
        elif choice != "4":
            log_message("Invalid option selected", "WARNING")
    else:
        log_message(f"{APP_PACKAGE} is not installed", "WARNING")
        if confirm_action("install"):
            if install_app(device):
                if start_app(device):
                    log_message("App successfully installed and started", "SUCCESS")
                else:
                    log_message("App installed but failed to start", "WARNING")
            else:
                log_message("Failed to install app", "ERROR")
            input("\nPress Enter to continue...")

def confirm_action(action):
    """Confirm an action with the user."""
    confirmation = input(f"\n{Fore.YELLOW}Are you sure you want to {action} the app? (y/n): {Style.RESET_ALL}").lower()
    return confirmation == 'y' or confirmation == 'yes'

def test_root_access(device=None):
    """
    Test root access with multiple methods.
    Returns True if any root method works.
    """
    adb_prefix = "adb "
    if device:
        adb_prefix += f"-s {device} "
    
    # Different root test commands, prioritizing su 0 which works
    root_tests = [
        f"{adb_prefix}shell su 0 whoami",  # This one works in logs
        f"{adb_prefix}shell su 0 id",
        f"{adb_prefix}shell su 0 echo root",
        f"{adb_prefix}shell su -c whoami",
        f"{adb_prefix}shell su -c id",
        f"{adb_prefix}shell su -c echo root"
    ]
    
    for test in root_tests:
        try:
            result = run_adb_command(test, shell=True)
            if "root" in result.lower() or "uid=0" in result.lower():
                log_message(f"Root access verified with command: {test}", "SUCCESS")
                return True
        except:
            continue
    
    log_message("All root access tests failed", "ERROR")
    return False

def test_database_access(device=None):
    """
    Test database access and permissions with improved root handling.
    """
    if not is_app_installed(device):
        log_message(f"{APP_PACKAGE} must be installed to test database access", "ERROR")
        return False
    
    adb_prefix = "adb "
    if device:
        adb_prefix += f"-s {device} "
    
    device_db_path = f"/data/data/{APP_PACKAGE}/cache/cache/data/sql.db"
    sdcard_path = "/sdcard/sql.db"
    
    # Test root access with multiple methods
    log_message("Testing root access...", "INFO")
    if not test_root_access(device):
        log_message("Root access not available", "ERROR")
        return False
    
    # Test file existence with root - using su 0 which works
    log_message("Testing database file existence...", "INFO")
    root_ls_commands = [
        f"{adb_prefix}shell su 0 ls {device_db_path}",  # This one works in logs
        f"{adb_prefix}shell su 0 '[ -f {device_db_path} ] && echo exists'",
        f"{adb_prefix}shell su -c ls {device_db_path}"
    ]
    
    file_exists = False
    for cmd in root_ls_commands:
        try:
            if run_adb_command(cmd, shell=True):
                file_exists = True
                break
        except:
            continue
    
    if not file_exists:
        log_message("Database file not found", "ERROR")
        return False
    
    # Test file permissions with root - using su 0 which works
    log_message("Testing file permissions...", "INFO")
    perms_commands = [
        f"{adb_prefix}shell su 0 ls -l {device_db_path}",  # This one works in logs
        f"{adb_prefix}shell su -c ls -l {device_db_path}"
    ]
    
    for cmd in perms_commands:
        try:
            perms = run_adb_command(cmd, shell=True)
            if perms:
                log_message(f"File permissions: {perms}", "INFO")
                break
        except:
            continue
    
    # Test file size with root - using su 0 which works
    log_message("Testing file size...", "INFO")
    size_commands = [
        f"{adb_prefix}shell su 0 stat -c%s {device_db_path}",  # This one works in logs
        f"{adb_prefix}shell su 0 ls -l {device_db_path} | awk '{{print $5}}'",
        f"{adb_prefix}shell su -c stat -c%s {device_db_path}"
    ]
    
    for cmd in size_commands:
        try:
            size = run_adb_command(cmd, shell=True)
            if size:
                log_message(f"File size: {size} bytes", "INFO")
                break
        except:
            continue
    
    # Test direct file transfer
    log_message("Testing direct file transfer...", "INFO")
    try:
        # Try to copy file directly to sdcard with root
        copy_cmd = f"{adb_prefix}shell su 0 cp {device_db_path} {sdcard_path}"
        if run_adb_command(copy_cmd, check_output=False, shell=True):
            log_message("Successfully copied file to sdcard", "SUCCESS")
            
            # Check sdcard file
            check_cmd = f"{adb_prefix}shell su 0 ls -l {sdcard_path}"
            result = run_adb_command(check_cmd, shell=True)
            log_message(f"SD card file info: {result}", "INFO")
            
            # Clean up
            run_adb_command(f"{adb_prefix}shell su 0 rm {sdcard_path}", check_output=False, shell=True)
            log_message("Cleaned up test file", "SUCCESS")
            return True
        else:
            log_message("Failed to copy file to sdcard", "ERROR")
            return False
    except Exception as e:
        log_message(f"Direct file transfer test failed: {str(e)}", "ERROR")
        return False

def handle_sql_db(action="pull", device=None):
    """
    Handle SQL database file operations with improved root access methods and error handling.
    """
    if not is_app_installed(device):
        log_message(f"{APP_PACKAGE} must be installed to handle its database", "ERROR")
        return False
    
    if not test_root_access(device):
        log_message("Root access required for database operations", "ERROR")
        return False
    
    adb_prefix = "adb "
    if device:
        adb_prefix += f"-s {device} "
    
    # Database paths
    device_db_path = f"/data/data/{APP_PACKAGE}/cache/cache/data/sql.db"
    sdcard_path = "/sdcard/sql.db"
    
    # Ensure DB directory exists
    if not os.path.exists(DB_DIR):
        os.makedirs(DB_DIR)
        log_message(f"Created database directory: {DB_DIR}", "INFO")
    
    if action == "pull":
        log_message("Pulling SQL database from device...", "INFO")
        log_message(f"Target path: {DB_PATH}", "INFO")
        
        # Try different root methods, prioritizing su 0 which works
        root_methods = [
            f"{adb_prefix}shell su 0 cp {device_db_path} {sdcard_path}",  # Try su 0 first
            f"{adb_prefix}shell su 0 dd if={device_db_path} of={sdcard_path}",
            f"{adb_prefix}shell su 0 cat {device_db_path} > {sdcard_path}",
            f"{adb_prefix}shell su -c cp {device_db_path} {sdcard_path}",
            f"{adb_prefix}shell su -c dd if={device_db_path} of={sdcard_path}",
            f"{adb_prefix}shell su -c cat {device_db_path} > {sdcard_path}"
        ]
        
        success = False
        for method in root_methods:
            log_message(f"Trying root method: {method}", "INFO")
            if run_adb_command(method, check_output=False, shell=True):
                success = True
                break
        
        if not success:
            log_message("All root methods failed. Trying alternative approach...", "WARNING")
            # Try to pull directly with root using su 0
            direct_pull = f"{adb_prefix}shell su 0 cat {device_db_path} > {DB_PATH}"
            if not run_adb_command(direct_pull, check_output=False, shell=True):
                log_message("Failed to access database file", "ERROR")
                return False
        
        # Verify file exists on sdcard
        check_file = f"{adb_prefix}shell su 0 ls {sdcard_path}"
        if not run_adb_command(check_file, shell=True):
            log_message("Database file not found on sdcard", "ERROR")
            return False
        
        # Try direct pull with proper path handling
        log_message("Attempting direct pull...", "INFO")
        # Convert Windows path to forward slashes and wrap in quotes
        db_path_forward = DB_PATH.replace("\\", "/")
        db_path_quoted = f'"{db_path_forward}"'
        pull_cmd = f"{adb_prefix}pull {sdcard_path} {db_path_quoted}"
        if run_adb_command(pull_cmd, check_output=False, shell=True):
            if os.path.exists(DB_PATH):
                file_size = os.path.getsize(DB_PATH)
                log_message(f"Database successfully pulled to {DB_PATH}", "SUCCESS")
                log_message(f"File size: {file_size} bytes", "INFO")
                # Clean up temp file
                run_adb_command(f"{adb_prefix}shell su 0 rm {sdcard_path}", check_output=False, shell=True)
                return True
            else:
                log_message("Pulled file is missing", "ERROR")
                return False
        else:
            log_message("Failed to pull database", "ERROR")
            return False
            
    elif action == "push":
        if not os.path.exists(DB_PATH):
            log_message(f"Database file not found at {DB_PATH}", "ERROR")
            return False
            
        log_message("Pushing SQL database to device...", "INFO")
        log_message(f"Source path: {DB_PATH}", "INFO")
        
        # Stop the app first
        log_message("Stopping BCA Track app...", "INFO")
        stop_cmd = f"{adb_prefix}shell am force-stop {APP_PACKAGE}"
        run_adb_command(stop_cmd, check_output=False, shell=True)
        time.sleep(2)  # Give it time to stop
        
        # Try direct push method first
        log_message("Attempting direct push method...", "INFO")
        try:
            # Convert Windows path to forward slashes and wrap in quotes
            db_path_forward = DB_PATH.replace("\\", "/")
            db_path_quoted = f'"{db_path_forward}"'
            # Push to sdcard first
            push_cmd = f"{adb_prefix}push {db_path_quoted} {sdcard_path}"
            if run_adb_command(push_cmd, check_output=False, shell=True):
                # Set permissions on sdcard file
                run_adb_command(f"{adb_prefix}shell su 0 chmod 666 {sdcard_path}", check_output=False, shell=True)
                
                # Copy to app directory with root
                copy_cmd = f"{adb_prefix}shell su 0 cp {sdcard_path} {device_db_path}"
                if run_adb_command(copy_cmd, check_output=False, shell=True):
                    # Set correct permissions
                    run_adb_command(f"{adb_prefix}shell su 0 chmod 600 {device_db_path}", check_output=False, shell=True)
                    # Clean up sdcard file
                    run_adb_command(f"{adb_prefix}shell su 0 rm {sdcard_path}", check_output=False, shell=True)
                    log_message("Database successfully pushed using direct method", "SUCCESS")
                    
                    # Restart the app
                    log_message("Restarting BCA Track app...", "INFO")
                    start_app(device)
                    return True
        except Exception as e:
            log_message(f"Direct push method failed: {str(e)}", "WARNING")
        
        # If direct method fails, try root copy method
        log_message("Attempting root copy method...", "INFO")
        try:
            # Convert Windows path to forward slashes and wrap in quotes
            db_path_forward = DB_PATH.replace("\\", "/")
            db_path_quoted = f'"{db_path_forward}"'
            # Copy directly to app directory with root
            copy_cmd = f"{adb_prefix}shell su 0 cp {db_path_quoted} {device_db_path}"
            if run_adb_command(copy_cmd, check_output=False, shell=True):
                # Set correct permissions
                run_adb_command(f"{adb_prefix}shell su 0 chmod 600 {device_db_path}", check_output=False, shell=True)
                log_message("Database successfully pushed using root copy method", "SUCCESS")
                
                # Restart the app
                log_message("Restarting BCA Track app...", "INFO")
                start_app(device)
                return True
        except Exception as e:
            log_message(f"Root copy method failed: {str(e)}", "ERROR")
            return False
            
        log_message("All push methods failed", "ERROR")
        return False
    else:
        log_message(f"Invalid action: {action}", "ERROR")
        return False

def test_database_replacement(device=None):
    """
    Test different methods to replace the SQL database file.
    """
    if not is_app_installed(device):
        log_message(f"{APP_PACKAGE} must be installed to test database replacement", "ERROR")
        return False
    
    if not test_root_access(device):
        log_message("Root access required for database operations", "ERROR")
        return False
    
    if not os.path.exists(DB_PATH):
        log_message(f"Local database file not found at {DB_PATH}", "ERROR")
        return False
    
    adb_prefix = "adb "
    if device:
        adb_prefix += f"-s {device} "
    
    sdcard_path = "/sdcard/sql.db"
    
    # Stop the app first
    log_message("Stopping BCA Track app...", "INFO")
    stop_cmd = f"{adb_prefix}shell am force-stop {APP_PACKAGE}"
    run_adb_command(stop_cmd, check_output=False, shell=True)
    time.sleep(2)
    
    # Test methods for copying to SD card
    methods = [
        {
            "name": "Direct push with quotes",
            "steps": [
                f'{adb_prefix}push "{DB_PATH}" {sdcard_path}',
                f"{adb_prefix}shell su 0 ls -l {sdcard_path}"
            ]
        },
        {
            "name": "Direct push without quotes",
            "steps": [
                f"{adb_prefix}push {DB_PATH} {sdcard_path}",
                f"{adb_prefix}shell su 0 ls -l {sdcard_path}"
            ]
        },
        {
            "name": "Root copy to sdcard",
            "steps": [
                f"{adb_prefix}shell su 0 cp {DB_PATH} {sdcard_path}",
                f"{adb_prefix}shell su 0 ls -l {sdcard_path}"
            ]
        }
    ]
    
    for method in methods:
        log_message(f"\nTesting method: {method['name']}", "INFO")
        success = True
        
        for step in method['steps']:
            log_message(f"Executing: {step}", "INFO")
            try:
                if not run_adb_command(step, check_output=False, shell=True):
                    log_message(f"Step failed: {step}", "ERROR")
                    success = False
                    break
            except Exception as e:
                log_message(f"Error in step: {str(e)}", "ERROR")
                success = False
                break
        
        if success:
            # Verify file exists and has correct permissions
            check_cmd = f"{adb_prefix}shell su 0 ls -l {sdcard_path}"
            result = run_adb_command(check_cmd, shell=True)
            log_message(f"File verification: {result}", "INFO")
            
            if "sql.db" in result:
                log_message(f"Method '{method['name']}' succeeded!", "SUCCESS")
                # Clean up
                run_adb_command(f"{adb_prefix}shell su 0 rm {sdcard_path}", check_output=False, shell=True)
                return True
            else:
                log_message(f"Method '{method['name']}' failed verification", "ERROR")
        else:
            log_message(f"Method '{method['name']}' failed", "ERROR")
    
    log_message("All methods failed", "ERROR")
    return False

def clear_screen():
    """Clear the terminal screen."""
    os.system('cls' if os.name == 'nt' else 'clear')

def display_header(device=None):
    """Display a header for the application with status bar."""
    clear_screen()
    
    # Main header
    print(f"\n{Fore.CYAN}{'=' * 60}{Style.RESET_ALL}")
    print(f"{Fore.CYAN}{'ADB Device Manager & App Handler':^60}{Style.RESET_ALL}")
    print(f"{Fore.CYAN}{'=' * 60}{Style.RESET_ALL}")
    
    # Status bar
    if device:
        print(f"\n{Fore.CYAN}Status Bar:{Style.RESET_ALL}")
        print(f"{Fore.CYAN}{'-' * 60}{Style.RESET_ALL}")
        
        # Device status
        print(f"{Fore.WHITE}Device:{Style.RESET_ALL} {Fore.GREEN}{device}{Style.RESET_ALL}")
        
        # App installation status
        is_installed = is_app_installed(device)
        install_status = f"{Fore.GREEN}Installed{Style.RESET_ALL}" if is_installed else f"{Fore.RED}Not Installed{Style.RESET_ALL}"
        print(f"{Fore.WHITE}App Status:{Style.RESET_ALL} {install_status}")
        
        # App running status
        if is_installed:
            is_running = is_app_running(device)
            run_status = f"{Fore.GREEN}Running{Style.RESET_ALL}" if is_running else f"{Fore.YELLOW}Not Running{Style.RESET_ALL}"
            print(f"{Fore.WHITE}Running Status:{Style.RESET_ALL} {run_status}")
        
        print(f"{Fore.CYAN}{'-' * 60}{Style.RESET_ALL}\n")
    else:
        print(f"\n{Fore.YELLOW}No device selected{Style.RESET_ALL}\n")

def display_device_selection(devices):
    """Display device selection menu."""
    if not devices:
        return None
    
    if len(devices) == 1:
        return devices[0]
    
    print(f"\n{Fore.CYAN}Select a device:{Style.RESET_ALL}")
    for i, device in enumerate(devices, 1):
        print(f"{i}. {device}")
    
    while True:
        try:
            selection = int(input("\nEnter device number: "))
            if 1 <= selection <= len(devices):
                return devices[selection - 1]
            print(f"{Fore.RED}Invalid selection. Please try again.{Style.RESET_ALL}")
        except ValueError:
            print(f"{Fore.RED}Please enter a number.{Style.RESET_ALL}")

def main_menu():
    """Display and handle the main menu."""
    selected_device = None  # Track the selected device
    
    while True:
        display_header(selected_device)  # Pass the selected device to header
        
        print(f"{Fore.CYAN}Main Menu:{Style.RESET_ALL}")
        print(f"1. {Fore.GREEN}Check ADB devices{Style.RESET_ALL}")
        print(f"2. {Fore.YELLOW}Manage BCA Track app{Style.RESET_ALL}")
        print(f"3. {Fore.BLUE}Pull SQL database from device{Style.RESET_ALL}")
        print(f"4. {Fore.BLUE}Push SQL database to device{Style.RESET_ALL}")
        print(f"5. {Fore.RED}Exit{Style.RESET_ALL}")
        
        choice = input("\nSelect an option (1-5): ").strip()
        
        if choice == "1":
            devices = check_adb_devices()
            if devices:
                print(f"\n{Fore.GREEN}Connected devices:{Style.RESET_ALL}")
                for i, device in enumerate(devices, 1):
                    print(f"{i}. {device}")
                # Update selected device if only one device is connected
                if len(devices) == 1:
                    selected_device = devices[0]
                    log_message(f"Auto-selected device: {selected_device}", "INFO")
            input("\nPress Enter to continue...")
            
        elif choice == "2":
            devices = check_adb_devices()
            if devices:
                if not selected_device or selected_device not in devices:
                    selected_device = display_device_selection(devices)
                manage_bca_track(selected_device)
            input("\nPress Enter to continue...")
            
        elif choice == "3":
            devices = check_adb_devices()
            if devices:
                if not selected_device or selected_device not in devices:
                    selected_device = display_device_selection(devices)
                if test_database_access(selected_device):
                    handle_sql_db("pull", selected_device)
                else:
                    log_message("Database access test failed", "ERROR")
            input("\nPress Enter to continue...")
            
        elif choice == "4":
            devices = check_adb_devices()
            if devices:
                if not selected_device or selected_device not in devices:
                    selected_device = display_device_selection(devices)
                if test_database_access(selected_device):
                    handle_sql_db("push", selected_device)
                else:
                    log_message("Database access test failed", "ERROR")
            input("\nPress Enter to continue...")
            
        elif choice == "5":
            log_message("Exiting program", "INFO")
            print(f"\n{Fore.GREEN}Thank you for using ADB Device Manager!{Style.RESET_ALL}")
            sys.exit(0)
            
        else:
            print(f"{Fore.RED}Invalid option. Please try again.{Style.RESET_ALL}")
            time.sleep(1)

if __name__ == "__main__":
    try:
        # Ensure directories exist
        ensure_directories_exist()
        
        # Initialize log file
        log_message("Starting ADB Device Manager", "INFO")
        
        # Display main menu
        main_menu()
        
    except KeyboardInterrupt:
        print(f"\n\n{Fore.YELLOW}Program interrupted by user{Style.RESET_ALL}")
        log_message("Program interrupted by user", "WARNING")
        sys.exit(1)
    except Exception as e:
        print(f"\n{Fore.RED}An unexpected error occurred: {str(e)}{Style.RESET_ALL}")
        log_message(f"Unexpected error: {str(e)}", "ERROR")
        sys.exit(1)
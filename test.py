#!/usr/bin/env python3
"""
Signature Placement Test Tool

This script is designed to test and debug signature placement in Excel files.
It provides a terminal interface for testing different signature configurations
and immediately seeing the results.
"""

import os
import random
import logging
from datetime import datetime
import colorama
from colorama import Fore, Back, Style
from openpyxl import load_workbook
from openpyxl.drawing.image import Image as OpenpyxlImage
from openpyxl.drawing.spreadsheet_drawing import OneCellAnchor, AnchorMarker
from openpyxl.utils.units import pixels_to_EMU, cm_to_EMU, EMU_to_pixels
from openpyxl.utils.cell import coordinate_from_string, column_index_from_string

# Initialize colorama for cross-platform terminal colors
colorama.init(autoreset=True)

# -------- Logging Setup --------
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_DIR = os.path.join(SCRIPT_DIR, "logs")
os.makedirs(LOG_DIR, exist_ok=True)

# Setup logging configuration
LOG_FILE = os.path.join(LOG_DIR, f"sig_test_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log")
logging.basicConfig(
    level=logging.DEBUG,  # Set to DEBUG for maximum information
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler()
    ]
)

class SignatureConfig:
    """Configuration for signature placement and appearance."""
    def __init__(self):
        # Base scale (1.0 = original size)
        self.scale = 1.0
        
        # Fine-tuning offsets (in pixels)
        self.sig1_offset_x = 0
        self.sig1_offset_y = -30
        self.sig2_offset_x = 0
        self.sig2_offset_y = -30
        
        # Random movement ranges (in pixels)
        # Increased ranges for more variation
        self.random_x_range = (-20, 20)  # Allow more horizontal movement
        self.random_y_range = (-40, 0)   # Allow more vertical movement up
        
        # Random rotation range (in degrees)
        self.random_rotation_range = (-5, 5)  # Slightly increased rotation
        
        # Base cell positions
        self.sig1_cell = 'C44'
        self.sig2_cell = 'H44'
        
        # Cell dimensions (approximate)
        self.cell_width_px = 8
        self.cell_height_px = 15
        
        # Allow cell overlap
        self.allow_overlap = True
        
        # Debug mode
        self.debug_mode = True
        
        # Random position mode
        self.random_position_mode = True
        
        # Alternative cell positions for random mode
        self.alt_cells = [
            ('C44', 'H44'),  # Original positions
            ('C43', 'H43'),  # One row up
            ('C45', 'H45'),  # One row down
            ('B44', 'G44'),  # One column left
            ('D44', 'I44'),  # One column right
            ('B43', 'G43'),  # Up and left
            ('D43', 'I43'),  # Up and right
            ('B45', 'G45'),  # Down and left
            ('D45', 'I45'),  # Down and right
        ]
    
    def get_random_offset(self):
        """Get random X and Y offsets within configured ranges."""
        x_offset = random.uniform(self.random_x_range[0], self.random_x_range[1])
        y_offset = random.uniform(self.random_y_range[0], self.random_y_range[1])
        rotation = random.uniform(self.random_rotation_range[0], self.random_rotation_range[1])
        return x_offset, y_offset, rotation
    
    def get_random_cell_position(self):
        """Get random cell positions from the alternative positions list."""
        return random.choice(self.alt_cells)
    
    def get_sig1_position(self):
        """Get final position for signature 1 with all offsets applied."""
        x_offset, y_offset, rotation = self.get_random_offset()
        
        # Get cell position
        if self.random_position_mode:
            cell1, _ = self.get_random_cell_position()
        else:
            cell1 = self.sig1_cell
        
        return {
            'cell': cell1,
            'offset_x': self.sig1_offset_x + x_offset,
            'offset_y': self.sig1_offset_y + y_offset,
            'rotation': rotation,
            'allow_overlap': self.allow_overlap,
            'cell_width': self.cell_width_px,
            'cell_height': self.cell_height_px
        }
    
    def get_sig2_position(self):
        """Get final position for signature 2 with all offsets applied."""
        x_offset, y_offset, rotation = self.get_random_offset()
        
        # Get cell position
        if self.random_position_mode:
            _, cell2 = self.get_random_cell_position()
        else:
            cell2 = self.sig2_cell
        
        return {
            'cell': cell2,
            'offset_x': self.sig2_offset_x + x_offset,
            'offset_y': self.sig2_offset_y + y_offset,
            'rotation': rotation,
            'allow_overlap': self.allow_overlap,
            'cell_width': self.cell_width_px,
            'cell_height': self.cell_height_px
        }

class SignatureTester:
    def __init__(self):
        """Initialize the signature tester."""
        self.config = SignatureConfig()
        self.test_file = os.path.join(SCRIPT_DIR, "test", "testsig.xlsx")
        self.template_file = os.path.join(SCRIPT_DIR, "templates", "loadsheet.xlsx")
        self.sig1_dir = os.path.join(SCRIPT_DIR, "signature", "sig1")
        self.sig2_dir = os.path.join(SCRIPT_DIR, "signature", "sig2")
        
        # Create test directory if it doesn't exist
        os.makedirs(os.path.dirname(self.test_file), exist_ok=True)
        
        logging.info("SignatureTester initialized")
        logging.info(f"Template file: {self.template_file}")
        logging.info(f"Test file: {self.test_file}")
        logging.info(f"Signature directories:")
        logging.info(f"  sig1: {self.sig1_dir}")
        logging.info(f"  sig2: {self.sig2_dir}")
    
    def check_required_files(self):
        """Check if all required files and directories exist."""
        required_files = {
            'Template': self.template_file,
            'Signature 1 Directory': self.sig1_dir,
            'Signature 2 Directory': self.sig2_dir
        }
        
        missing_files = []
        for name, path in required_files.items():
            if not os.path.exists(path):
                missing_files.append(f"{name}: {path}")
        
        if missing_files:
            print(f"\n{Fore.RED}Missing required files:{Style.RESET_ALL}")
            for file in missing_files:
                print(f"{Fore.YELLOW}- {file}{Style.RESET_ALL}")
            return False
        
        # Check for signature files
        sig1_files = [f for f in os.listdir(self.sig1_dir) if f.lower().endswith('.png')]
        sig2_files = [f for f in os.listdir(self.sig2_dir) if f.lower().endswith('.png')]
        
        if not sig1_files or not sig2_files:
            print(f"\n{Fore.RED}Missing signature files:{Style.RESET_ALL}")
            if not sig1_files:
                print(f"{Fore.YELLOW}- No PNG files in sig1 directory{Style.RESET_ALL}")
            if not sig2_files:
                print(f"{Fore.YELLOW}- No PNG files in sig2 directory{Style.RESET_ALL}")
            return False
        
        print(f"{Fore.GREEN}All required files are present.{Style.RESET_ALL}")
        return True
    
    def add_signatures(self, ws):
        """Add signatures to the worksheet with fine-tuned positioning."""
        try:
            # Get signature files
            sig1_files = [f for f in os.listdir(self.sig1_dir) if f.lower().endswith('.png')]
            sig2_files = [f for f in os.listdir(self.sig2_dir) if f.lower().endswith('.png')]
            
            if not sig1_files or not sig2_files:
                print(f"{Fore.YELLOW}Warning: Missing signature files{Style.RESET_ALL}")
                return False
            
            # Select signature files
            sig1_path = os.path.join(self.sig1_dir, random.choice(sig1_files))
            sig2_path = os.path.join(self.sig2_dir, random.choice(sig2_files))
            
            logging.info(f"Selected signature files:")
            logging.info(f"sig1: {sig1_path}")
            logging.info(f"sig2: {sig2_path}")
            
            # Create and scale images
            img1 = OpenpyxlImage(sig1_path)
            img2 = OpenpyxlImage(sig2_path)
            
            img1.width = int(img1.width * self.config.scale)
            img1.height = int(img1.height * self.config.scale)
            img2.width = int(img2.width * self.config.scale)
            img2.height = int(img2.height * self.config.scale)
            
            logging.info(f"Image dimensions after scaling:")
            logging.info(f"img1: {img1.width}x{img1.height}")
            logging.info(f"img2: {img2.width}x{img2.height}")
            
            # Get positions
            pos1 = self.config.get_sig1_position()
            pos2 = self.config.get_sig2_position()
            
            logging.info(f"Signature positions:")
            logging.info(f"pos1: {pos1}")
            logging.info(f"pos2: {pos2}")
            
            # Convert cell references
            col1, row1 = coordinate_from_string(pos1['cell'])
            col2, row2 = coordinate_from_string(pos2['cell'])
            
            col1_num = column_index_from_string(col1)
            col2_num = column_index_from_string(col2)
            
            logging.info(f"Converted cell references:")
            logging.info(f"col1: {col1} -> {col1_num}, row1: {row1}")
            logging.info(f"col2: {col2} -> {col2_num}, row2: {row2}")
            
            # Create anchors
            marker1 = AnchorMarker(col=col1_num, colOff=0, row=row1, rowOff=0)
            marker2 = AnchorMarker(col=col2_num, colOff=0, row=row2, rowOff=0)
            
            img1.anchor = OneCellAnchor(_from=marker1)
            img2.anchor = OneCellAnchor(_from=marker2)
            
            # Apply offsets (in EMU units - 9525 EMUs per pixel)
            EMU_PER_PIXEL = 9525
            
            # Calculate cell dimensions in EMU
            CELL_WIDTH_EMU = pos1['cell_width'] * EMU_PER_PIXEL
            CELL_HEIGHT_EMU = pos1['cell_height'] * EMU_PER_PIXEL
            
            # Calculate image dimensions in EMU
            IMG1_WIDTH_EMU = img1.width * EMU_PER_PIXEL
            IMG1_HEIGHT_EMU = img1.height * EMU_PER_PIXEL
            IMG2_WIDTH_EMU = img2.width * EMU_PER_PIXEL
            IMG2_HEIGHT_EMU = img2.height * EMU_PER_PIXEL
            
            # Apply offsets to signature 1
            if pos1['allow_overlap']:
                # Center the image over the cell and then apply offsets
                img1.anchor._from.colOff = int((CELL_WIDTH_EMU / 2) - (IMG1_WIDTH_EMU / 2) + (pos1['offset_x'] * EMU_PER_PIXEL))
                img1.anchor._from.rowOff = int((CELL_HEIGHT_EMU / 2) - (IMG1_HEIGHT_EMU / 2) + (pos1['offset_y'] * EMU_PER_PIXEL))
            else:
                img1.anchor._from.colOff = int(pos1['offset_x'] * EMU_PER_PIXEL)
                img1.anchor._from.rowOff = int(pos1['offset_y'] * EMU_PER_PIXEL)
            
            # Apply offsets to signature 2
            if pos2['allow_overlap']:
                # Center the image over the cell and then apply offsets
                img2.anchor._from.colOff = int((CELL_WIDTH_EMU / 2) - (IMG2_WIDTH_EMU / 2) + (pos2['offset_x'] * EMU_PER_PIXEL))
                img2.anchor._from.rowOff = int((CELL_HEIGHT_EMU / 2) - (IMG2_HEIGHT_EMU / 2) + (pos2['offset_y'] * EMU_PER_PIXEL))
            else:
                img2.anchor._from.colOff = int(pos2['offset_x'] * EMU_PER_PIXEL)
                img2.anchor._from.rowOff = int(pos2['offset_y'] * EMU_PER_PIXEL)
            
            logging.info(f"Applied offsets (in EMU):")
            logging.info(f"img1: colOff={img1.anchor._from.colOff}, rowOff={img1.anchor._from.rowOff}")
            logging.info(f"img2: colOff={img2.anchor._from.colOff}, rowOff={img2.anchor._from.rowOff}")
            
            # Add images to worksheet
            ws.add_image(img1, pos1['cell'])
            ws.add_image(img2, pos2['cell'])
            
            logging.info("Successfully added images to worksheet")
            return True
            
        except Exception as e:
            logging.error(f"Error adding signatures: {e}", exc_info=True)
            print(f"{Fore.RED}Error adding signatures: {e}{Style.RESET_ALL}")
            return False
    
    def create_test_file(self):
        """Create a test file with signatures."""
        try:
            # Check required files first
            if not self.check_required_files():
                return False
            
            # Copy template to test file
            import shutil
            shutil.copy2(self.template_file, self.test_file)
            logging.info(f"Created test file: {self.test_file}")
            
            # Load the workbook
            wb = load_workbook(self.test_file)
            ws = wb["Loadsheet"]
            
            # Add signatures
            if self.add_signatures(ws):
                # Save the workbook
                wb.save(self.test_file)
                print(f"{Fore.GREEN}Test file created successfully: {self.test_file}{Style.RESET_ALL}")
                
                # Ask if user wants to verify the file
                verify = input(f"\n{Fore.YELLOW}Open testsig.xlsx to verify? (y/n):{Style.RESET_ALL} ").strip().lower()
                if verify == 'y':
                    try:
                        if os.name == 'nt':  # Windows
                            os.startfile(self.test_file)
                        elif os.name == 'posix':  # macOS and Linux
                            import subprocess
                            subprocess.run(['xdg-open', self.test_file])
                    except Exception as e:
                        print(f"{Fore.YELLOW}Warning: Could not open file automatically: {e}{Style.RESET_ALL}")
                        print(f"{Fore.CYAN}Please open the file manually at: {self.test_file}{Style.RESET_ALL}")
                
                return True
            else:
                return False
            
        except Exception as e:
            logging.error(f"Error creating test file: {e}", exc_info=True)
            print(f"{Fore.RED}Error creating test file: {e}{Style.RESET_ALL}")
            return False
    
    def configure_signature(self):
        """Configure signature placement settings."""
        print(f"\n{Fore.CYAN}Current Signature Configuration:{Style.RESET_ALL}")
        print(f"Scale: {self.config.scale}")
        print(f"Random Position Mode: {'Enabled' if self.config.random_position_mode else 'Disabled'}")
        print(f"Signature 1:")
        print(f"  Cell: {self.config.sig1_cell}")
        print(f"  Offset X: {self.config.sig1_offset_x}")
        print(f"  Offset Y: {self.config.sig1_offset_y}")
        print(f"Signature 2:")
        print(f"  Cell: {self.config.sig2_cell}")
        print(f"  Offset X: {self.config.sig2_offset_x}")
        print(f"  Offset Y: {self.config.sig2_offset_y}")
        print(f"Random Ranges:")
        print(f"  X Range: {self.config.random_x_range}")
        print(f"  Y Range: {self.config.random_y_range}")
        print(f"  Rotation Range: {self.config.random_rotation_range}")
        print(f"Cell Dimensions:")
        print(f"  Width: {self.config.cell_width_px}")
        print(f"  Height: {self.config.cell_height_px}")
        print(f"Allow Overlap: {self.config.allow_overlap}")
        
        print(f"\n{Fore.CYAN}Configure Settings:{Style.RESET_ALL}")
        print("1. Change Scale")
        print("2. Change Signature 1 Position")
        print("3. Change Signature 2 Position")
        print("4. Change Cell Dimensions")
        print("5. Toggle Overlap")
        print("6. Toggle Random Position Mode")
        print("7. Configure Random Ranges")
        print("8. Back to Main Menu")
        
        choice = input(f"\n{Fore.CYAN}Enter choice (1-8):{Style.RESET_ALL} ").strip()
        
        if choice == '1':
            try:
                scale = float(input(f"{Fore.CYAN}Enter new scale (e.g., 1.0):{Style.RESET_ALL} "))
                self.config.scale = scale
                print(f"{Fore.GREEN}Scale updated to {scale}{Style.RESET_ALL}")
            except ValueError:
                print(f"{Fore.RED}Invalid scale value.{Style.RESET_ALL}")
        
        elif choice == '2':
            try:
                cell = input(f"{Fore.CYAN}Enter new cell for Signature 1 (e.g., C44):{Style.RESET_ALL} ").upper()
                offset_x = float(input(f"{Fore.CYAN}Enter X offset (e.g., 0):{Style.RESET_ALL} "))
                offset_y = float(input(f"{Fore.CYAN}Enter Y offset (e.g., -30):{Style.RESET_ALL} "))
                
                self.config.sig1_cell = cell
                self.config.sig1_offset_x = offset_x
                self.config.sig1_offset_y = offset_y
                print(f"{Fore.GREEN}Signature 1 position updated{Style.RESET_ALL}")
            except ValueError:
                print(f"{Fore.RED}Invalid input values.{Style.RESET_ALL}")
        
        elif choice == '3':
            try:
                cell = input(f"{Fore.CYAN}Enter new cell for Signature 2 (e.g., H44):{Style.RESET_ALL} ").upper()
                offset_x = float(input(f"{Fore.CYAN}Enter X offset (e.g., 0):{Style.RESET_ALL} "))
                offset_y = float(input(f"{Fore.CYAN}Enter Y offset (e.g., -30):{Style.RESET_ALL} "))
                
                self.config.sig2_cell = cell
                self.config.sig2_offset_x = offset_x
                self.config.sig2_offset_y = offset_y
                print(f"{Fore.GREEN}Signature 2 position updated{Style.RESET_ALL}")
            except ValueError:
                print(f"{Fore.RED}Invalid input values.{Style.RESET_ALL}")
        
        elif choice == '4':
            try:
                width = float(input(f"{Fore.CYAN}Enter cell width in pixels (e.g., 8):{Style.RESET_ALL} "))
                height = float(input(f"{Fore.CYAN}Enter cell height in pixels (e.g., 15):{Style.RESET_ALL} "))
                
                self.config.cell_width_px = width
                self.config.cell_height_px = height
                print(f"{Fore.GREEN}Cell dimensions updated{Style.RESET_ALL}")
            except ValueError:
                print(f"{Fore.RED}Invalid input values.{Style.RESET_ALL}")
        
        elif choice == '5':
            self.config.allow_overlap = not self.config.allow_overlap
            status = "enabled" if self.config.allow_overlap else "disabled"
            print(f"{Fore.GREEN}Cell overlap {status}{Style.RESET_ALL}")
        
        elif choice == '6':
            self.config.random_position_mode = not self.config.random_position_mode
            status = "enabled" if self.config.random_position_mode else "disabled"
            print(f"{Fore.GREEN}Random position mode {status}{Style.RESET_ALL}")
        
        elif choice == '7':
            try:
                print(f"{Fore.CYAN}Enter random ranges (in pixels):{Style.RESET_ALL}")
                x_min = float(input(f"X range minimum (e.g., -20):{Style.RESET_ALL} "))
                x_max = float(input(f"X range maximum (e.g., 20):{Style.RESET_ALL} "))
                y_min = float(input(f"Y range minimum (e.g., -40):{Style.RESET_ALL} "))
                y_max = float(input(f"Y range maximum (e.g., 0):{Style.RESET_ALL} "))
                rot_min = float(input(f"Rotation range minimum (e.g., -5):{Style.RESET_ALL} "))
                rot_max = float(input(f"Rotation range maximum (e.g., 5):{Style.RESET_ALL} "))
                
                self.config.random_x_range = (x_min, x_max)
                self.config.random_y_range = (y_min, y_max)
                self.config.random_rotation_range = (rot_min, rot_max)
                print(f"{Fore.GREEN}Random ranges updated{Style.RESET_ALL}")
            except ValueError:
                print(f"{Fore.RED}Invalid input values.{Style.RESET_ALL}")
        
        elif choice == '8':
            return
        
        else:
            print(f"{Fore.RED}Invalid choice.{Style.RESET_ALL}")
    
    def print_menu(self):
        """Print the menu with fancy formatting."""
        menu_border = f"{Fore.BLUE}{'═' * 60}{Style.RESET_ALL}"
        menu_title = f"{Fore.CYAN}{'▌' * 5} Signature Placement Tester {'▌' * 5}{Style.RESET_ALL}"
        
        print("\n" + menu_border)
        print(menu_title)
        print(menu_border)
        print(f"{Fore.YELLOW}┌──────────────────────────────────────┐{Style.RESET_ALL}")
        print(f"{Fore.YELLOW}│{Style.RESET_ALL} {Fore.WHITE}1.{Style.RESET_ALL} {Fore.CYAN}Create Test File              {Fore.YELLOW}│{Style.RESET_ALL}")
        print(f"{Fore.YELLOW}│{Style.RESET_ALL} {Fore.WHITE}2.{Style.RESET_ALL} {Fore.CYAN}Configure Signature Settings  {Fore.YELLOW}│{Style.RESET_ALL}")
        print(f"{Fore.YELLOW}│{Style.RESET_ALL} {Fore.WHITE}3.{Style.RESET_ALL} {Fore.CYAN}Exit                        {Fore.YELLOW}│{Style.RESET_ALL}")
        print(f"{Fore.YELLOW}└──────────────────────────────────────┘{Style.RESET_ALL}")
        
        print(f"{Fore.CYAN}Enter your choice (1-3):{Style.RESET_ALL} ", end="")
    
    def run(self):
        """Run the main application loop."""
        print(f"{Fore.BLUE}{'═' * 60}{Style.RESET_ALL}")
        print(f"{Fore.CYAN}   Signature Placement Tester{Style.RESET_ALL}")
        print(f"{Fore.BLUE}{'═' * 60}{Style.RESET_ALL}")
        
        while True:
            self.print_menu()
            choice = input()
            
            if choice == '1':
                self.create_test_file()
            elif choice == '2':
                self.configure_signature()
            elif choice == '3':
                print(f"{Fore.GREEN}Exiting...{Style.RESET_ALL}")
                break
            else:
                print(f"{Fore.RED}Invalid choice. Please try again.{Style.RESET_ALL}")

if __name__ == "__main__":
    tester = SignatureTester()
    try:
        tester.run()
    except KeyboardInterrupt:
        print(f"\n{Fore.YELLOW}Operation interrupted. Exiting...{Style.RESET_ALL}")
    except Exception as e:
        print(f"{Fore.RED}An unexpected error occurred: {e}{Style.RESET_ALL}")
    finally:
        print(f"{Fore.GREEN}Program terminated.{Style.RESET_ALL}") 
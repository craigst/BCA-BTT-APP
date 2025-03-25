#!/usr/bin/env python3
"""
Signature Placement Test Tool

This script provides a simple way to test different signature placement modes
in Excel files. It allows you to try various placement methods and compare
which works best for your needs.
"""

import os
import random
import logging
from datetime import datetime
import colorama
from colorama import Fore, Style
from openpyxl import load_workbook
from openpyxl.drawing.image import Image as OpenpyxlImage
from openpyxl.drawing.spreadsheet_drawing import OneCellAnchor, TwoCellAnchor, AnchorMarker, AbsoluteAnchor
from openpyxl.drawing.xdr import XDRPoint2D, XDRPositiveSize2D
from openpyxl.utils.units import pixels_to_EMU, cm_to_EMU
from openpyxl.utils.cell import coordinate_from_string, column_index_from_string
from openpyxl.worksheet.dimensions import ColumnDimension, RowDimension

# Initialize colorama for cross-platform terminal colors
colorama.init(autoreset=True)

# -------- Logging Setup --------
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_DIR = os.path.join(SCRIPT_DIR, "logs")
os.makedirs(LOG_DIR, exist_ok=True)

LOG_FILE = os.path.join(LOG_DIR, f"sig_test_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log")
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler()
    ]
)

class ExcelImagePlacer:
    """Handles Excel image positioning with various methods."""
    
    def __init__(self):
        self.EMU_PER_PIXEL = 9525
        self.EMU_PER_CM = 360000  # 1 cm = 360000 EMU
        self.PIXELS_PER_CM = 37.8  # Approximate pixels per centimeter
        
    def get_cell_dimensions(self, ws, cell):
        """Get cell dimensions in pixels."""
        col, row = coordinate_from_string(cell)
        col_idx = column_index_from_string(col)
        
        # Get column width (in characters)
        col_width = ws.column_dimensions[col].width or 8.43
        # Get row height (in points)
        row_height = ws.row_dimensions[row].height or 15
        
        # Convert to pixels
        # Excel uses 7 pixels per character width
        # and 1.2 pixels per point height
        width_px = col_width * 7
        height_px = row_height * 1.2
        
        return width_px, height_px
    
    def get_cell_position(self, ws, cell):
        """Get cell position in pixels from top-left of sheet."""
        col, row = coordinate_from_string(cell)
        col_idx = column_index_from_string(col)
        
        # Calculate position by summing up previous column widths and row heights
        x = 0
        for i in range(1, col_idx):
            # Convert column index back to letter
            col_letter = chr(ord('A') + i - 1)
            col_width = ws.column_dimensions[col_letter].width or 8.43
            x += col_width * 7
        
        y = 0
        for i in range(1, row):
            row_height = ws.row_dimensions[i].height or 15
            y += row_height * 1.2
            
        # Add vertical offset to move down from row 44
        # Each row is approximately 18 pixels high (15 points * 1.2)
        VERTICAL_ROW_OFFSET = 18 * 7  # Move down 7 rows from row 44 (reduced from 9 to 7)
        y = y + VERTICAL_ROW_OFFSET  # Changed from minus to plus to move down
            
        return x, y
    
    def create_absolute_anchor(self, x_px, y_px, width_px, height_px):
        """Create an absolute anchor with size."""
        x_emu = int(x_px * self.EMU_PER_PIXEL)
        y_emu = int(y_px * self.EMU_PER_PIXEL)
        width_emu = int(width_px * self.EMU_PER_PIXEL)
        height_emu = int(height_px * self.EMU_PER_PIXEL)
        
        anchor = AbsoluteAnchor(pos=XDRPoint2D(x=x_emu, y=y_emu))
        anchor.ext = XDRPositiveSize2D(cx=width_emu, cy=height_emu)
        return anchor
    
    def create_two_cell_anchor(self, ws, cell, offset_x_px=0, offset_y_px=0):
        """Create a two-cell anchor with offset."""
        col, row = coordinate_from_string(cell)
        col_idx = column_index_from_string(col)
        
        # Create from marker (reference point)
        from_marker = AnchorMarker(col=col_idx, colOff=0, row=row, rowOff=0)
        
        # Create to marker with offset
        to_marker = AnchorMarker(
            col=col_idx,
            colOff=int(offset_x_px * self.EMU_PER_PIXEL),
            row=row,
            rowOff=int(offset_y_px * self.EMU_PER_PIXEL)
        )
        
        return TwoCellAnchor(_from=from_marker, to=to_marker)

class SignaturePlacer:
    """Handles different signature placement modes."""
    def __init__(self):
        self.test_file = os.path.join(SCRIPT_DIR, "test", "testsig.xlsx")
        self.template_file = os.path.join(SCRIPT_DIR, "templates", "loadsheet.xlsx")
        self.sig1_dir = os.path.join(SCRIPT_DIR, "signature", "sig1")
        self.sig2_dir = os.path.join(SCRIPT_DIR, "signature", "sig2")
        
        # Create test directory if it doesn't exist
        os.makedirs(os.path.dirname(self.test_file), exist_ok=True)
        
        # Base cell positions
        self.sig1_cell = 'C44'
        self.sig2_cell = 'H44'
        
        # Initialize image placer
        self.image_placer = ExcelImagePlacer()

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

    def get_signature_files(self):
        """Get random signature files from directories."""
        sig1_files = [f for f in os.listdir(self.sig1_dir) if f.lower().endswith('.png')]
        sig2_files = [f for f in os.listdir(self.sig2_dir) if f.lower().endswith('.png')]
        
        sig1_path = os.path.join(self.sig1_dir, random.choice(sig1_files))
        sig2_path = os.path.join(self.sig2_dir, random.choice(sig2_files))
        
        return sig1_path, sig2_path

    def place_signatures(self, ws, mode):
        """Place signatures using specified mode."""
        try:
            # Get signature files
            sig1_path, sig2_path = self.get_signature_files()
            logging.info(f"Using signature files: {sig1_path}, {sig2_path}")
            
            # Create images
            img1 = OpenpyxlImage(sig1_path)
            img2 = OpenpyxlImage(sig2_path)
            
            # Set base size with 1.5x scaling
            base_width = 100
            base_height = 50
            scale_factor = 1.5
            
            img1.width = int(base_width * scale_factor)
            img1.height = int(base_height * scale_factor)
            img2.width = int(base_width * scale_factor)
            img2.height = int(base_height * scale_factor)
            
            logging.info(f"Image dimensions: {img1.width}x{img1.height}")
            
            # Get cell positions and dimensions
            x1, y1 = self.image_placer.get_cell_position(ws, self.sig1_cell)
            x2, y2 = self.image_placer.get_cell_position(ws, self.sig2_cell)
            
            width1, height1 = self.image_placer.get_cell_dimensions(ws, self.sig1_cell)
            width2, height2 = self.image_placer.get_cell_dimensions(ws, self.sig2_cell)
            
            logging.info(f"Cell positions: ({x1}, {y1}), ({x2}, {y2})")
            logging.info(f"Cell dimensions: ({width1}, {height1}), ({width2}, {height2})")
            
            # Randomly choose a vertical offset mode (4-7)
            vertical_mode = random.randint(4, 7)
            logging.info(f"Using vertical mode: {vertical_mode}")
            
            # Add fixed right offset for sig1
            SIG1_RIGHT_OFFSET = 35  # Fixed right offset for sig1
            x1 = x1 + SIG1_RIGHT_OFFSET
            
            # Generate random rotation (-15 to +15 degrees)
            rotation = random.randint(-15, 15)
            logging.info(f"Using rotation: {rotation} degrees")
            
            # Apply placement mode with detailed logging
            if vertical_mode == 4:  # Centered with small vertical offset
                logging.info("Applying Centered with Small Vertical Offset Mode")
                x1_centered = x1 + (width1 - img1.width) / 2
                y1_centered = y1 + (height1 - img1.height) / 2 - 10
                x2_centered = x2 + (width2 - img2.width) / 2
                y2_centered = y2 + (height2 - img2.height) / 2 - 10
                
                img1.anchor = self.image_placer.create_absolute_anchor(x1_centered, y1_centered, img1.width, img1.height)
                img2.anchor = self.image_placer.create_absolute_anchor(x2_centered, y2_centered, img2.width, img2.height)
            
            elif vertical_mode == 5:  # Basic with medium vertical offset
                logging.info("Applying Basic with Medium Vertical Offset Mode")
                y1_offset = y1 - 20
                y2_offset = y2 - 20
                
                img1.anchor = self.image_placer.create_absolute_anchor(x1, y1_offset, img1.width, img1.height)
                img2.anchor = self.image_placer.create_absolute_anchor(x2, y2_offset, img2.width, img2.height)
            
            elif vertical_mode == 6:  # Centered with medium vertical offset
                logging.info("Applying Centered with Medium Vertical Offset Mode")
                x1_centered = x1 + (width1 - img1.width) / 2
                y1_centered = y1 + (height1 - img1.height) / 2 - 20
                x2_centered = x2 + (width2 - img2.width) / 2
                y2_centered = y2 + (height2 - img2.height) / 2 - 20
                
                img1.anchor = self.image_placer.create_absolute_anchor(x1_centered, y1_centered, img1.width, img1.height)
                img2.anchor = self.image_placer.create_absolute_anchor(x2_centered, y2_centered, img2.width, img2.height)
            
            elif vertical_mode == 7:  # Basic with large vertical offset
                logging.info("Applying Basic with Large Vertical Offset Mode")
                y1_offset = y1 - 30
                y2_offset = y2 - 30
                
                img1.anchor = self.image_placer.create_absolute_anchor(x1, y1_offset, img1.width, img1.height)
                img2.anchor = self.image_placer.create_absolute_anchor(x2, y2_offset, img2.width, img2.height)
            
            # Add rotation to both images
            img1.rotation = rotation
            img2.rotation = rotation
            
            # Add images to worksheet
            ws.add_image(img1)
            ws.add_image(img2)
            
            # Log final positions
            logging.info(f"Images added to worksheet at positions with rotation {rotation}°")
            
            return True
            
        except Exception as e:
            logging.error(f"Error placing signatures: {e}", exc_info=True)
            print(f"{Fore.RED}Error placing signatures: {e}{Style.RESET_ALL}")
            return False

    def create_test_file(self, mode):
        """Create a test file with signatures using specified mode."""
        try:
            if not self.check_required_files():
                return False
            
            logging.info(f"Creating test file with mode {mode}")
            
            # Copy template to test file
            import shutil
            shutil.copy2(self.template_file, self.test_file)
            logging.info(f"Template copied to: {self.test_file}")
            
            # Load the workbook
            wb = load_workbook(self.test_file)
            ws = wb["Loadsheet"]
            logging.info("Workbook loaded successfully")
            
            # Place signatures
            if self.place_signatures(ws, mode):
                # Save the workbook
                wb.save(self.test_file)
                logging.info("Workbook saved successfully")
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
                        logging.error(f"Error opening file: {e}")
                        print(f"{Fore.YELLOW}Warning: Could not open file automatically: {e}{Style.RESET_ALL}")
                        print(f"{Fore.CYAN}Please open the file manually at: {self.test_file}{Style.RESET_ALL}")
                
                return True
            else:
                return False
            
        except Exception as e:
            logging.error(f"Error creating test file: {e}", exc_info=True)
            print(f"{Fore.RED}Error creating test file: {e}{Style.RESET_ALL}")
            return False

    def print_menu(self):
        """Print the menu with placement modes."""
        print(f"\n{Fore.CYAN}Signature Placement Options:{Style.RESET_ALL}")
        print("1. Add Signatures (Random Position & Rotation)")
        print("2. Exit")
        
        print(f"\n{Fore.CYAN}Enter option number (1-2):{Style.RESET_ALL} ", end="")

    def run(self):
        """Run the main application loop."""
        print(f"{Fore.BLUE}{'═' * 60}{Style.RESET_ALL}")
        print(f"{Fore.CYAN}   Signature Placement Tester{Style.RESET_ALL}")
        print(f"{Fore.BLUE}{'═' * 60}{Style.RESET_ALL}")
        
        while True:
            self.print_menu()
            choice = input()
            
            if choice == '1':
                self.create_test_file(1)  # Mode parameter is ignored now
            elif choice == '2':
                print(f"{Fore.GREEN}Exiting...{Style.RESET_ALL}")
                break
            else:
                print(f"{Fore.RED}Invalid choice. Please try again.{Style.RESET_ALL}")

if __name__ == "__main__":
    placer = SignaturePlacer()
    try:
        placer.run()
    except KeyboardInterrupt:
        print(f"\n{Fore.YELLOW}Operation interrupted. Exiting...{Style.RESET_ALL}")
    except Exception as e:
        print(f"{Fore.RED}An unexpected error occurred: {e}{Style.RESET_ALL}")
    finally:
        print(f"{Fore.GREEN}Program terminated.{Style.RESET_ALL}") 
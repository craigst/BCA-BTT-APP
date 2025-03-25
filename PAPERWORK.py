#!/usr/bin/env python3
"""
Paperwork Module

This module provides functions to generate:
  1. A loadsheet for a given load number
  2. A timesheet for a given week‐ending date
  3. All loadsheets and timesheet for a selected work week
  4. Test loadsheet generation with debug information
"""

import os
import random
import configparser
import logging
from datetime import datetime, timedelta, date
import psycopg2
from openpyxl import load_workbook
from openpyxl.drawing.image import Image as OpenpyxlImage
import colorama
from colorama import Fore, Back, Style
from openpyxl.drawing.spreadsheet_drawing import OneCellAnchor, AnchorMarker
from openpyxl.utils.units import pixels_to_EMU, cm_to_EMU, EMU_to_pixels
from openpyxl.utils.cell import coordinate_from_string, column_index_from_string

# Initialize colorama for cross-platform terminal colors
colorama.init(autoreset=True)

# -------- Logging Setup --------
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_DIR = os.path.join(SCRIPT_DIR, "logs")
SQL_DIR = os.path.join(SCRIPT_DIR, "SQL")

# Ensure directories exist
os.makedirs(LOG_DIR, exist_ok=True)
os.makedirs(SQL_DIR, exist_ok=True)

# Setup logging configuration
LOG_FILE = os.path.join(LOG_DIR, f"paperwork_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log")
logging.basicConfig(
    level=logging.INFO,
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
        self.scale = 1.0  # 20% larger than original
        
        # Fine-tuning offsets (in pixels)
        self.sig1_offset_x = 0  # Adjust left/right (0 = centered)
        self.sig1_offset_y = -30  # Adjust up/down (negative moves up)
        self.sig2_offset_x = 0  # Adjust left/right (0 = centered)
        self.sig2_offset_y = -30  # Adjust up/down (negative moves up)
        
        # Random movement ranges (in pixels)
        self.random_x_range = (0.1, 0.3)  # Min and max random X movement
        self.random_y_range = (0.1, 0.2)  # Min and max random Y movement
        
        # Random rotation range (in degrees)
        self.random_rotation_range = (-3, 3)  # Min and max random rotation
        
        # Base cell positions (can be overridden)
        self.sig1_cell = 'C44'
        self.sig2_cell = 'H44'
        
        # Cell dimensions (approximate)
        self.cell_width_px = 8  # Approximate cell width in pixels
        self.cell_height_px = 15  # Approximate cell height in pixels
        
        # Allow cell overlap
        self.allow_overlap = True
    
    def get_random_offset(self):
        """Get random X and Y offsets within configured ranges."""
        import random
        x_offset = random.uniform(self.random_x_range[0], self.random_x_range[1])
        y_offset = random.uniform(self.random_y_range[0], self.random_y_range[1])
        rotation = random.uniform(self.random_rotation_range[0], self.random_rotation_range[1])
        return x_offset, y_offset, rotation
    
    def get_sig1_position(self):
        """Get final position for signature 1 with all offsets applied."""
        x_offset, y_offset, rotation = self.get_random_offset()
        return {
            'cell': self.sig1_cell,
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
        return {
            'cell': self.sig2_cell,
            'offset_x': self.sig2_offset_x + x_offset,
            'offset_y': self.sig2_offset_y + y_offset,
            'rotation': rotation,
            'allow_overlap': self.allow_overlap,
            'cell_width': self.cell_width_px,
            'cell_height': self.cell_height_px
        }

class PaperworkManager:
    def __init__(self):
        """Initialize the paperwork manager with PostgreSQL configuration."""
        self.pg_config = self.load_pg_config()
        self.auto_signature = True  # Default to True
        
    def load_pg_config(self):
        """Load PostgreSQL configuration from sql.ini file."""
        config = configparser.ConfigParser()
        config_path = os.path.join(SQL_DIR, "sql.ini")
        
        if not os.path.exists(config_path):
            logging.error(f"PostgreSQL configuration file not found at {config_path}")
            return None
            
        try:
            config.read(config_path)
            return {
                'host': config['SQL']['PG_HOST'],
                'port': config['SQL']['PG_PORT'],
                'database': config['SQL']['PG_DATABASE'],
                'user': config['SQL']['PG_USERNAME'],
                'password': config['SQL']['PG_PASSWORD']
            }
        except Exception as e:
            logging.error(f"Error loading PostgreSQL configuration: {e}")
            return None

    def get_week_dates(self):
        """Get list of recent Sundays plus current/following week."""
        today = datetime.now()
        current_weekday = today.weekday()
        days_to_last_sunday = (current_weekday + 1) % 7
        last_sunday = today - timedelta(days=days_to_last_sunday)
        
        logging.info(f"Today: {today.strftime('%A %d-%m-%Y')}")
        logging.info(f"Current weekday: {current_weekday}")
        logging.info(f"Days to last Sunday: {days_to_last_sunday}")
        logging.info(f"Last Sunday: {last_sunday.strftime('%A %d-%m-%Y')}")
        
        # Show last 4 Sundays plus current/following week
        sundays = [(last_sunday - timedelta(weeks=i)).strftime("%A %d-%m-%Y") 
                  for i in range(4)]
        
        # Add current/following week if we're not already showing it
        next_sunday = last_sunday + timedelta(weeks=1)
        if next_sunday.strftime("%A %d-%m-%Y") not in sundays:
            sundays.insert(0, next_sunday.strftime("%A %d-%m-%Y"))
        
        return sundays, last_sunday, next_sunday

    def select_week(self):
        """Let user select a week from the available options."""
        sundays, last_sunday, next_sunday = self.get_week_dates()
        
        print(f"\n{Fore.CYAN}Select week end date (Sunday):{Style.RESET_ALL}")
        for i, sunday in enumerate(sundays, 1):
            print(f"{Fore.WHITE}{i}. {Fore.YELLOW}{sunday}{Style.RESET_ALL}")
        
        choice = input(f"\n{Fore.CYAN}Enter week number (1-{len(sundays)}):{Style.RESET_ALL} ").strip()
        try:
            week_idx = int(choice) - 1
            if not (0 <= week_idx < len(sundays)):
                print(f"{Fore.RED}Invalid selection.{Style.RESET_ALL}")
                return None
            
            # Calculate selected Sunday based on the index
            if week_idx == 0:  # Next Sunday
                selected_sunday = next_sunday
            else:  # Past Sundays
                selected_sunday = last_sunday - timedelta(weeks=week_idx-1)
            
            return selected_sunday
            
        except ValueError:
            print(f"{Fore.RED}Invalid input.{Style.RESET_ALL}")
            return None

    def get_loads_for_week(self, selected_sunday):
        """Get all loads for the selected week."""
        week_start = selected_sunday - timedelta(days=6)  # Monday
        start_date_str = week_start.strftime("%Y%m%d")
        end_date_str = selected_sunday.strftime("%Y%m%d")
        
        try:
            conn = psycopg2.connect(**self.pg_config)
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT DISTINCT dwvload
                FROM public.dwvveh
                WHERE dwvexpdat BETWEEN %s AND %s
                AND dwvload IS NOT NULL
                ORDER BY dwvload
            """, (start_date_str, end_date_str))
            
            loads = cursor.fetchall()
            cursor.close()
            conn.close()
            
            return loads
            
        except Exception as e:
            logging.error(f"Error getting loads for week: {e}")
            return []

    def get_load_info(self, load_number):
        """Get detailed information for a specific load."""
        try:
            conn = psycopg2.connect(**self.pg_config)
            cursor = conn.cursor()
            
            # Get collections with vehicle details
            cursor.execute("""
                SELECT 
                    j.dwjtype,
                    j.dwjcust,
                    j.dwjname,
                    j.dwjdate,
                    j.dwjadrcod,
                    j.dwjpostco,
                    j.dwjvehs,
                    v.dwvvehref,
                    v.dwvmoddes,
                    COALESCE(e.sparekeys, 'Y') as sparekeys,
                    COALESCE(e.extra, 'Y') as extra,
                    COALESCE(e.carnotes, '') as carnotes,
                    v.dwvcolcod,
                    v.dwvdelcod
                FROM public.dwjjob j
                LEFT JOIN public.dwvveh v ON j.dwjload = v.dwvload AND j.dwjadrcod = v.dwvcolcod
                LEFT JOIN public.extracarinfo e ON v.dwvkey = e.idkey
                WHERE j.dwjload = %s
                AND j.dwjtype = 'C'
                ORDER BY j.dwjdate, j.dwjcust
            """, (load_number,))
            
            collections = cursor.fetchall()
            
            # Get deliveries with vehicle details
            cursor.execute("""
                SELECT 
                    j.dwjtype,
                    j.dwjcust,
                    j.dwjname,
                    j.dwjdate,
                    j.dwjadrcod,
                    j.dwjpostco,
                    j.dwjvehs,
                    v.dwvvehref,
                    v.dwvmoddes,
                    COALESCE(e.sparekeys, 'Y') as sparekeys,
                    COALESCE(e.extra, 'Y') as extra,
                    COALESCE(e.carnotes, '') as carnotes,
                    v.dwvcolcod,
                    v.dwvdelcod
                FROM public.dwjjob j
                LEFT JOIN public.dwvveh v ON j.dwjload = v.dwvload AND j.dwjadrcod = v.dwvdelcod
                LEFT JOIN public.extracarinfo e ON v.dwvkey = e.idkey
                WHERE j.dwjload = %s
                AND j.dwjtype = 'D'
                ORDER BY j.dwjdate, j.dwjcust
            """, (load_number,))
            
            deliveries = cursor.fetchall()
            
            if not collections and not deliveries:
                print(f"{Fore.YELLOW}No details found for this load.{Style.RESET_ALL}")
                return None
            
            # Format collections with postcodes and vehicle details
            formatted_collections = []
            collection_vehicles = []
            for collection in collections:
                if collection[2] and collection[5]:  # Check if name and postcode exist
                    formatted_collections.append(f"{collection[2]} - {collection[5]}")
                elif collection[2]:  # If only name exists
                    formatted_collections.append(collection[2])
                
                # Add vehicle details if available
                if collection[7] and collection[8]:  # Check if vehicle reference and model exist
                    collection_vehicles.append(f"{collection[7]} - {collection[8]}")
            
            # Format deliveries with postcodes and vehicle details
            formatted_deliveries = []
            delivery_vehicles = []
            for delivery in deliveries:
                if delivery[2] and delivery[5]:  # Check if name and postcode exist
                    formatted_deliveries.append(f"{delivery[2]} - {delivery[5]}")
                elif delivery[2]:  # If only name exists
                    formatted_deliveries.append(delivery[2])
                
                # Add vehicle details if available
                if delivery[7] and delivery[8]:  # Check if vehicle reference and model exist
                    delivery_vehicles.append(f"{delivery[7]} - {delivery[8]}")
            
            # Get the first collection date and contractor
            first_collection_date = collections[0][3] if collections else None
            contractor = collections[0][1] if collections else None
            
            # Format the data for the loadsheet
            load_info = (
                first_collection_date,  # date
                load_number,  # load number
                '\n'.join(formatted_collections),  # collections
                '\n'.join(formatted_deliveries),  # deliveries
                len(collection_vehicles),  # collection cars count
                len(delivery_vehicles),  # delivery cars count
                contractor  # contractor
            )
            
            # Format vehicle data for the loadsheet
            formatted_vehicles = []
            for collection in collections:
                if collection[7] and collection[8]:  # Check if vehicle reference and model exist
                    formatted_vehicles.append((
                        str(collection[7] or ''),  # registration
                        str(collection[8] or ''),  # model
                        'N',  # offloaded (default)
                        'Y',  # documents (default)
                        str(collection[7] or ''),  # key (using registration as key)
                        str(collection[9] or 'Y'),  # spare keys
                        str(collection[11] or '')   # notes
                    ))
            
            cursor.close()
            conn.close()
            
            return {
                'load_info': load_info,
                'vehicles': formatted_vehicles
            }
            
        except Exception as e:
            logging.error(f"Error getting load info: {e}", exc_info=True)
            print(f"{Fore.RED}Error getting load info: {e}{Style.RESET_ALL}")
            return None

    def show_load_summary(self, load_data):
        """Show a summary of the load information."""
        if not load_data:
            print(f"{Fore.RED}No data available for this load.{Style.RESET_ALL}")
            return False
            
        load_info, vehicles = load_data
        
        print(f"\n{Fore.CYAN}Load {load_info[1]} Details:{Style.RESET_ALL}")
        
        # Show collections
        if load_info[2]:
            print(f"\n{Fore.YELLOW}Collections:{Style.RESET_ALL}")
            print(f"{Fore.WHITE}{'Type':<8} | {'Customer':<10} | {'Location':<30} | {'Cars':<5}{Style.RESET_ALL}")
            print("-" * 60)
            # Create a set of unique collections based on name and postcode
            unique_collections = {}
            for collection in load_info[2].split('\n'):
                if collection:
                    if collection not in unique_collections:
                        unique_collections[collection] = 1
                    else:
                        unique_collections[collection] += 1
            
            # Display unique collections
            for location, count in sorted(unique_collections.items()):
                print(f"{Fore.WHITE}{'C':<8} | {Fore.YELLOW}{location:<40} | {Fore.YELLOW}{count:<5}{Style.RESET_ALL}")
        
        # Show deliveries
        if load_info[3]:
            print(f"\n{Fore.YELLOW}Deliveries:{Style.RESET_ALL}")
            print(f"{Fore.WHITE}{'Type':<8} | {'Customer':<10} | {'Location':<30} | {'Cars':<5}{Style.RESET_ALL}")
            print("-" * 60)
            # Create a set of unique deliveries based on name and postcode
            unique_deliveries = {}
            for delivery in load_info[3].split('\n'):
                if delivery:
                    if delivery not in unique_deliveries:
                        unique_deliveries[delivery] = 1
                    else:
                        unique_deliveries[delivery] += 1
            
            # Display unique deliveries
            for location, count in sorted(unique_deliveries.items()):
                print(f"{Fore.WHITE}{'D':<8} | {Fore.YELLOW}{location:<40} | {Fore.YELLOW}{count:<5}{Style.RESET_ALL}")
        
        # Show vehicles
        if vehicles:
            print(f"\n{Fore.YELLOW}Vehicles:{Style.RESET_ALL}")
            print(f"{Fore.WHITE}{'Reg':<10} | {'Model':<30} | {'Offloaded':<10} | {'Documents':<10} | {'Spare Keys':<10} | {'Notes'}{Style.RESET_ALL}")
            print("-" * 100)
            for vehicle in vehicles:
                try:
                    if not isinstance(vehicle, (list, tuple)) or len(vehicle) < 7:
                        print(f"{Fore.RED}Warning: Invalid vehicle data format, skipping.{Style.RESET_ALL}")
                        continue
                        
                    print(f"{Fore.WHITE}{str(vehicle[0] or ''):<10} | {Fore.YELLOW}{str(vehicle[1] or ''):<30} | {Fore.YELLOW}{str(vehicle[2] or ''):<10} | {Fore.YELLOW}{str(vehicle[3] or ''):<10} | {Fore.YELLOW}{str(vehicle[5] or ''):<10} | {Fore.YELLOW}{str(vehicle[6] or '')}{Style.RESET_ALL}")
                except Exception as e:
                    print(f"{Fore.RED}Warning: Error displaying vehicle: {e}{Style.RESET_ALL}")
                    continue
        
        return True

    def create_loadsheet(self, load_number):
        """Create a loadsheet for a specific load."""
        load_data = self.get_load_info(load_number)
        if not load_data:
            print(f"{Fore.RED}Failed to get load information.{Style.RESET_ALL}")
            return False
            
        if not self.show_load_summary(load_data):
            return False
            
        confirm = input(f"\n{Fore.YELLOW}Create loadsheet for load {load_number}? (y/n):{Style.RESET_ALL} ").strip().lower()
        if confirm != 'y':
            print(f"{Fore.YELLOW}Operation cancelled.{Style.RESET_ALL}")
            return False
            
        # TODO: Implement loadsheet generation using template
        print(f"{Fore.GREEN}Loadsheet generation will be implemented here.{Style.RESET_ALL}")
        return True

    def create_timesheet(self, selected_sunday):
        """Create a timesheet for the selected week."""
        week_start = selected_sunday - timedelta(days=6)
        start_date_str = week_start.strftime("%Y%m%d")
        end_date_str = selected_sunday.strftime("%Y%m%d")
        
        try:
            conn = psycopg2.connect(**self.pg_config)
            cursor = conn.cursor()
            
            # Get loads for the week
            cursor.execute("""
                SELECT 
                    dwjdate,
                    UPPER(dwjcust) AS contractor,
                    dwjvehs AS car_count,
                    UPPER(dwjtown) AS collection,
                    (SELECT UPPER(dwjtown) 
                     FROM dwjjob AS d 
                     WHERE d.dwjdate = j.dwjdate 
                     AND d.dwjtype = 'D' 
                     LIMIT 1) AS destination
                FROM dwjjob AS j
                WHERE dwjdate BETWEEN %s AND %s 
                AND dwjtype = 'C'
                ORDER BY dwjdate
            """, (start_date_str, end_date_str))
            
            loads = cursor.fetchall()
            
            if not loads:
                print(f"{Fore.YELLOW}No loads found for this week.{Style.RESET_ALL}")
                return False
                
            print(f"\n{Fore.CYAN}Week Summary:{Style.RESET_ALL}")
            for load in loads:
                date_str = datetime.strptime(str(load[0]), "%Y%m%d").strftime("%A %d-%m-%Y")
                print(f"{Fore.WHITE}Date: {Fore.YELLOW}{date_str}{Style.RESET_ALL}")
                print(f"{Fore.WHITE}Contractor: {Fore.YELLOW}{load[1]}{Style.RESET_ALL}")
                print(f"{Fore.WHITE}Cars: {Fore.YELLOW}{load[2]}{Style.RESET_ALL}")
                print(f"{Fore.WHITE}Collection: {Fore.YELLOW}{load[3]}{Style.RESET_ALL}")
                print(f"{Fore.WHITE}Destination: {Fore.YELLOW}{load[4]}{Style.RESET_ALL}")
                print()
            
            confirm = input(f"{Fore.YELLOW}Create timesheet for this week? (y/n):{Style.RESET_ALL} ").strip().lower()
            if confirm != 'y':
                print(f"{Fore.YELLOW}Operation cancelled.{Style.RESET_ALL}")
                return False
                
            # TODO: Implement timesheet generation using template
            print(f"{Fore.GREEN}Timesheet generation will be implemented here.{Style.RESET_ALL}")
            return True
            
        except Exception as e:
            logging.error(f"Error creating timesheet: {e}")
            print(f"{Fore.RED}Error creating timesheet: {e}{Style.RESET_ALL}")
            return False
        finally:
            if 'cursor' in locals():
                cursor.close()
            if 'conn' in locals():
                conn.close()

    def create_all_paperwork(self, selected_sunday):
        """Create all loadsheets and timesheet for the selected week."""
        loads = self.get_loads_for_week(selected_sunday)
        if not loads:
            print(f"{Fore.YELLOW}No loads found for this week.{Style.RESET_ALL}")
            return False
            
        print(f"\n{Fore.CYAN}Found {len(loads)} loads for this week:{Style.RESET_ALL}")
        for load in loads:
            print(f"{Fore.WHITE}Load: {Fore.YELLOW}{load[0]}{Style.RESET_ALL}")
            
        confirm = input(f"\n{Fore.YELLOW}Create all paperwork for this week? (y/n):{Style.RESET_ALL} ").strip().lower()
        if confirm != 'y':
            print(f"{Fore.YELLOW}Operation cancelled.{Style.RESET_ALL}")
            return False
            
        # Create timesheet first
        if not self.create_timesheet(selected_sunday):
            return False
            
        # Create loadsheets
        for load in loads:
            if not self.create_loadsheet(load[0]):
                print(f"{Fore.YELLOW}Skipping remaining loads.{Style.RESET_ALL}")
                return False
                
        print(f"{Fore.GREEN}All paperwork created successfully!{Style.RESET_ALL}")
        return True

    def check_required_files(self):
        """Check if all required files and directories exist."""
        # Check template files
        template_files = {
            'templates/loadsheet.xlsx': os.path.join(SCRIPT_DIR, "templates", "loadsheet.xlsx"),
            'templates/timesheet.xlsx': os.path.join(SCRIPT_DIR, "templates", "timesheet.xlsx")
        }
        
        # Check signature directories
        signature_dirs = {
            'signature/sig1': os.path.join(SCRIPT_DIR, "signature", "sig1"),
            'signature/sig2': os.path.join(SCRIPT_DIR, "signature", "sig2")
        }
        
        missing_files = []
        missing_dirs = []
        
        # Check template files
        for file_desc, file_path in template_files.items():
            if not os.path.exists(file_path):
                missing_files.append(file_desc)
        
        # Check signature directories and their contents
        for dir_desc, dir_path in signature_dirs.items():
            if not os.path.exists(dir_path):
                missing_dirs.append(dir_desc)
            else:
                # Count PNG files in the directory
                png_files = [f for f in os.listdir(dir_path) if f.lower().endswith('.png')]
                if len(png_files) < 1:
                    missing_files.append(f"{dir_desc}/*.png (no signature files found)")
        
        # Report missing items
        if missing_files or missing_dirs:
            print(f"\n{Fore.RED}Missing required files and directories:{Style.RESET_ALL}")
            if missing_dirs:
                print(f"\n{Fore.YELLOW}Missing directories:{Style.RESET_ALL}")
                for dir_name in missing_dirs:
                    print(f"{Fore.YELLOW}- {dir_name}{Style.RESET_ALL}")
            if missing_files:
                print(f"\n{Fore.YELLOW}Missing files:{Style.RESET_ALL}")
                for file_name in missing_files:
                    print(f"{Fore.YELLOW}- {file_name}{Style.RESET_ALL}")
            return False
            
        print(f"{Fore.GREEN}All required files and directories are present.{Style.RESET_ALL}")
        return True

    def generate_load_summary(self, vehicles):
        """Generate a summary message for the loadsheet."""
        total_cars = len(vehicles)
        offloaded_cars = sum(1 for v in vehicles if v[2] == 'Y')  # Assuming v[2] is offloaded status
        loaded_cars = total_cars - offloaded_cars
        
        # Count cars with documents and spare keys
        cars_with_docs = sum(1 for v in vehicles if v[3] == 'Y')  # Assuming v[3] is documents status
        cars_with_keys = sum(1 for v in vehicles if v[4] == 'Y')  # Assuming v[4] is spare keys status
        
        # Build the message
        message_parts = []
        
        if offloaded_cars > 0:
            message_parts.append(f"{offloaded_cars} CAR{'S' if offloaded_cars > 1 else ''} OFFLOADED")
        
        if loaded_cars > 0:
            message_parts.append(f"{loaded_cars} CAR{'S' if loaded_cars > 1 else ''} LOADED")
        
        if cars_with_docs > 0:
            message_parts.append(f"{cars_with_docs} CAR{'S' if cars_with_docs > 1 else ''} HAVE DOCUMENTS ALL DOCUMENTS ON PASSENGER SEAT'S")
        
        if cars_with_keys > 0:
            message_parts.append(f"{cars_with_keys} CAR{'S' if cars_with_keys > 1 else ''} HAVE SPARE KEYS")
        
        return ", ".join(message_parts)

    def add_signatures(self, ws):
        """Add signatures to the loadsheet with fine-tuned positioning."""
        try:
            # Get signature files
            sig1_dir = os.path.join(SCRIPT_DIR, "signature", "sig1")
            sig2_dir = os.path.join(SCRIPT_DIR, "signature", "sig2")
            
            logging.info(f"Looking for signature files in directories:")
            logging.info(f"sig1_dir: {sig1_dir}")
            logging.info(f"sig2_dir: {sig2_dir}")
            
            sig1_files = [f for f in os.listdir(sig1_dir) if f.lower().endswith('.png')]
            sig2_files = [f for f in os.listdir(sig2_dir) if f.lower().endswith('.png')]
            
            logging.info(f"Found {len(sig1_files)} files in sig1 directory")
            logging.info(f"Found {len(sig2_files)} files in sig2 directory")
            
            if not sig1_files or not sig2_files:
                print(f"{Fore.YELLOW}Warning: Missing signature files{Style.RESET_ALL}")
                logging.error("No signature files found in one or both directories")
                return
            
            # Randomly select signature files
            sig1_path = os.path.join(sig1_dir, random.choice(sig1_files))
            # Ensure sig2 is different from sig1
            sig2_files = [f for f in sig2_files if f != os.path.basename(sig1_path)]
            if not sig2_files:  # If no different sig2 files available, use any sig2 file
                sig2_files = [f for f in os.listdir(sig2_dir) if f.lower().endswith('.png')]
            sig2_path = os.path.join(sig2_dir, random.choice(sig2_files))
            
            logging.info(f"Selected signature files:")
            logging.info(f"sig1_path: {sig1_path}")
            logging.info(f"sig2_path: {sig2_path}")
            
            # Create signature config
            config = SignatureConfig()
            
            # Add first signature
            img1 = OpenpyxlImage(sig1_path)
            img1.width = int(img1.width * config.scale)
            img1.height = int(img1.height * config.scale)
            
            # Add second signature
            img2 = OpenpyxlImage(sig2_path)
            img2.width = int(img2.width * config.scale)
            img2.height = int(img2.height * config.scale)
            
            logging.info(f"Image dimensions after scaling:")
            logging.info(f"img1: {img1.width}x{img1.height}")
            logging.info(f"img2: {img2.width}x{img2.height}")
            
            # Get random offsets and positions
            pos1 = config.get_sig1_position()
            pos2 = config.get_sig2_position()
            
            logging.info(f"Signature positions:")
            logging.info(f"pos1: {pos1}")
            logging.info(f"pos2: {pos2}")
            
            # Convert cell references to row/column numbers
            col1, row1 = coordinate_from_string(pos1['cell'])
            col2, row2 = coordinate_from_string(pos2['cell'])
            
            # Convert column letters to numbers
            col1_num = column_index_from_string(col1)
            col2_num = column_index_from_string(col2)
            
            logging.info(f"Converted cell references:")
            logging.info(f"col1: {col1} -> {col1_num}, row1: {row1}")
            logging.info(f"col2: {col2} -> {col2_num}, row2: {row2}")
            
            # Create anchors for both signatures
            marker1 = AnchorMarker(col=col1_num, colOff=0, row=row1, rowOff=0)
            img1.anchor = OneCellAnchor(_from=marker1)
            
            # Signature 2 anchor
            marker2 = AnchorMarker(col=col2_num, colOff=0, row=row2, rowOff=0)
            img2.anchor = OneCellAnchor(_from=marker2)
            
            # Apply offsets (in EMU units - 9525 EMUs per pixel)
            EMU_PER_PIXEL = 9525
            
            # Calculate cell dimensions (approximate)
            CELL_WIDTH_EMU = 9525 * 8  # Approximate cell width in EMUs
            CELL_HEIGHT_EMU = 9525 * 15  # Approximate cell height in EMUs
            
            # Apply offsets to signature 1 with cell overlap
            if pos1['allow_overlap']:
                # Center the image in the cell and then apply offsets
                img1.anchor._from.colOff = int((CELL_WIDTH_EMU / 2) + (pos1['offset_x'] * EMU_PER_PIXEL))
                img1.anchor._from.rowOff = int((CELL_HEIGHT_EMU / 2) + (pos1['offset_y'] * EMU_PER_PIXEL))
            else:
                img1.anchor._from.colOff = int(pos1['offset_x'] * EMU_PER_PIXEL)
                img1.anchor._from.rowOff = int(pos1['offset_y'] * EMU_PER_PIXEL)
            
            # Apply offsets to signature 2 with cell overlap
            if pos2['allow_overlap']:
                # Center the image in the cell and then apply offsets
                img2.anchor._from.colOff = int((CELL_WIDTH_EMU / 2) + (pos2['offset_x'] * EMU_PER_PIXEL))
                img2.anchor._from.rowOff = int((CELL_HEIGHT_EMU / 2) + (pos2['offset_y'] * EMU_PER_PIXEL))
            else:
                img2.anchor._from.colOff = int(pos2['offset_x'] * EMU_PER_PIXEL)
                img2.anchor._from.rowOff = int(pos2['offset_y'] * EMU_PER_PIXEL)
            
            logging.info(f"Applied offsets (in EMU):")
            logging.info(f"img1: colOff={img1.anchor._from.colOff}, rowOff={img1.anchor._from.rowOff}")
            logging.info(f"img2: colOff={img2.anchor._from.colOff}, rowOff={img2.anchor._from.rowOff}")
            
            # Add images to worksheet using the anchor
            ws.add_image(img1, pos1['cell'])
            ws.add_image(img2, pos2['cell'])
            
            logging.info("Successfully added images to worksheet")
            
            print(f"{Fore.GREEN}Signatures added successfully with offsets:{Style.RESET_ALL}")
            print(f"{Fore.CYAN}Signature 1: Cell {pos1['cell']}, Offset X: {pos1['offset_x']}px, Y: {pos1['offset_y']}px{Style.RESET_ALL}")
            print(f"{Fore.CYAN}Signature 2: Cell {pos2['cell']}, Offset X: {pos2['offset_x']}px, Y: {pos2['offset_y']}px{Style.RESET_ALL}")
            
        except Exception as e:
            print(f"{Fore.YELLOW}Warning: Could not add signatures: {e}{Style.RESET_ALL}")
            logging.error(f"Error adding signatures: {e}", exc_info=True)

    def test_loadsheet(self, load_number=None):
        """Test loadsheet generation with debug information."""
        try:
            # Check required files first
            if not self.check_required_files():
                print(f"{Fore.RED}Please ensure all required files are in place before proceeding.{Style.RESET_ALL}")
                return False

            if not load_number:
                # Get list of recent Sundays
                selected_sunday = self.select_week()
                if not selected_sunday:
                    return False
                    
                # Get loads for the selected week
                loads = self.get_loads_for_week(selected_sunday)
                if not loads:
                    print(f"{Fore.YELLOW}No loads found for this week.{Style.RESET_ALL}")
                    return False
                    
                print(f"\n{Fore.CYAN}Available loads for testing:{Style.RESET_ALL}")
                for i, load in enumerate(loads, 1):
                    print(f"{Fore.WHITE}{i}. {Fore.YELLOW}Load {load[0]}{Style.RESET_ALL}")
                
                load_choice = input(f"\n{Fore.CYAN}Enter load number (1-{len(loads)}):{Style.RESET_ALL} ").strip()
                try:
                    load_idx = int(load_choice) - 1
                    if not (0 <= load_idx < len(loads)):
                        print(f"{Fore.RED}Invalid selection.{Style.RESET_ALL}")
                        return False
                    load_number = loads[load_idx][0]
                except ValueError:
                    print(f"{Fore.RED}Invalid input.{Style.RESET_ALL}")
                    return False
            
            print(f"\n{Fore.CYAN}Testing loadsheet generation for load {load_number}{Style.RESET_ALL}")
            
            # Get load data directly from database
            try:
                conn = psycopg2.connect(**self.pg_config)
                cursor = conn.cursor()
                print(f"{Fore.GREEN}Database connection successful.{Style.RESET_ALL}")
            except Exception as e:
                print(f"{Fore.RED}Database connection failed: {e}{Style.RESET_ALL}")
                return False
            
            try:
                # Get collections
                cursor.execute("""
                    SELECT 
                        j.dwjtype,
                        j.dwjcust,
                        j.dwjname,
                        j.dwjdate,
                        j.dwjadrcod,
                        j.dwjpostco,
                        j.dwjvehs,
                        v.dwvvehref,
                        v.dwvmoddes,
                        COALESCE(e.sparekeys, 'Y') as sparekeys,
                        COALESCE(e.extra, 'Y') as extra,
                        COALESCE(e.carnotes, '') as carnotes,
                        v.dwvcolcod,
                        v.dwvdelcod
                    FROM public.dwjjob j
                    LEFT JOIN public.dwvveh v ON j.dwjload = v.dwvload AND j.dwjadrcod = v.dwvcolcod
                    LEFT JOIN public.extracarinfo e ON v.dwvkey = e.idkey
                    WHERE j.dwjload = %s
                    AND j.dwjtype = 'C'
                    ORDER BY j.dwjdate, j.dwjcust
                """, (load_number,))
                
                collections = cursor.fetchall()
                print(f"\n{Fore.YELLOW}Found {len(collections)} collections:{Style.RESET_ALL}")
                
                # Get deliveries
                cursor.execute("""
                    SELECT 
                        j.dwjtype,
                        j.dwjcust,
                        j.dwjname,
                        j.dwjdate,
                        j.dwjadrcod,
                        j.dwjpostco,
                        j.dwjvehs,
                        v.dwvvehref,
                        v.dwvmoddes,
                        COALESCE(e.sparekeys, 'Y') as sparekeys,
                        COALESCE(e.extra, 'Y') as extra,
                        COALESCE(e.carnotes, '') as carnotes,
                        v.dwvcolcod,
                        v.dwvdelcod
                    FROM public.dwjjob j
                    LEFT JOIN public.dwvveh v ON j.dwjload = v.dwvload AND j.dwjadrcod = v.dwvdelcod
                    LEFT JOIN public.extracarinfo e ON v.dwvkey = e.idkey
                    WHERE j.dwjload = %s
                    AND j.dwjtype = 'D'
                    ORDER BY j.dwjdate, j.dwjcust
                """, (load_number,))
                
                deliveries = cursor.fetchall()
                print(f"{Fore.YELLOW}Found {len(deliveries)} deliveries:{Style.RESET_ALL}")
                
                # Get vehicles
                cursor.execute("""
                    SELECT DISTINCT
                        v.dwvvehref,
                        v.dwvmoddes,
                        v.dwvcolcod,
                        v.dwvdelcod,
                        COALESCE(e.sparekeys, 'Y') as sparekeys,
                        COALESCE(e.extra, 'Y') as extra,
                        COALESCE(e.carnotes, '') as carnotes
                    FROM public.dwvveh v
                    LEFT JOIN public.extracarinfo e ON v.dwvkey = e.idkey
                    WHERE v.dwvload = %s
                    ORDER BY v.dwvvehref
                """, (load_number,))
                
                vehicles = cursor.fetchall()
                print(f"{Fore.YELLOW}Found {len(vehicles)} vehicles:{Style.RESET_ALL}")
                
                # Format vehicle data for summary
                formatted_vehicles = []
                for vehicle in vehicles:
                    formatted_vehicles.append((
                        str(vehicle[0] or ''),  # registration
                        str(vehicle[1] or ''),  # model
                        'N',  # offloaded (default)
                        'Y',  # documents (default)
                        str(vehicle[4] or 'Y'),  # spare keys
                        str(vehicle[5] or 'Y'),  # extra (documents)
                        str(vehicle[6] or '')   # notes
                    ))
                
                # Format data for display
                print(f"\n{Fore.CYAN}Load {load_number} Details:{Style.RESET_ALL}")
                
                # Show collections
                if collections:
                    print(f"\n{Fore.YELLOW}Collections:{Style.RESET_ALL}")
                    print(f"{Fore.WHITE}{'Type':<8} | {'Customer':<10} | {'Location':<30} | {'Cars':<5}{Style.RESET_ALL}")
                    print("-" * 60)
                    # Create a set of unique collections based on name and postcode
                    unique_collections = {}
                    for collection in collections:
                        location = f"{collection[2]} - {collection[5]}" if collection[2] and collection[5] else collection[2] or ''
                        if location not in unique_collections:
                            unique_collections[location] = {
                                'customer': collection[1],
                                'cars': collection[6]
                            }
                    
                    # Display unique collections
                    for location, details in sorted(unique_collections.items()):
                        print(f"{Fore.WHITE}{'C':<8} | {Fore.YELLOW}{details['customer']:<10} | {Fore.YELLOW}{location:<30} | {Fore.YELLOW}{details['cars']:<5}{Style.RESET_ALL}")
                
                # Show deliveries
                if deliveries:
                    print(f"\n{Fore.YELLOW}Deliveries:{Style.RESET_ALL}")
                    print(f"{Fore.WHITE}{'Type':<8} | {'Customer':<10} | {'Location':<30} | {'Cars':<5}{Style.RESET_ALL}")
                    print("-" * 60)
                    # Create a set of unique deliveries based on name and postcode
                    unique_deliveries = {}
                    for delivery in deliveries:
                        location = f"{delivery[2]} - {delivery[5]}" if delivery[2] and delivery[5] else delivery[2] or ''
                        if location not in unique_deliveries:
                            unique_deliveries[location] = {
                                'customer': delivery[1],
                                'cars': delivery[6]
                            }
                    
                    # Display unique deliveries
                    for location, details in sorted(unique_deliveries.items()):
                        print(f"{Fore.WHITE}{'D':<8} | {Fore.YELLOW}{details['customer']:<10} | {Fore.YELLOW}{location:<30} | {Fore.YELLOW}{details['cars']:<5}{Style.RESET_ALL}")
                
                # Show vehicles
                if vehicles:
                    print(f"\n{Fore.YELLOW}Vehicles:{Style.RESET_ALL}")
                    print(f"{Fore.WHITE}{'Reg':<10} | {'Model':<30} | {'Offloaded':<10} | {'Documents':<10} | {'Spare Keys':<10} | {'Notes'}{Style.RESET_ALL}")
                    print("-" * 100)
                    for vehicle in vehicles:
                        print(f"{Fore.WHITE}{str(vehicle[0] or ''):<10} | {Fore.YELLOW}{str(vehicle[1] or ''):<30} | {Fore.YELLOW}{'N':<10} | {Fore.YELLOW}{'Y':<10} | {Fore.YELLOW}{str(vehicle[4] or 'Y'):<10} | {Fore.YELLOW}{str(vehicle[6] or '')}{Style.RESET_ALL}")
                
                # Generate and add load summary message
                summary_message = self.generate_load_summary(formatted_vehicles)
                print(f"\n{Fore.CYAN}Load Summary:{Style.RESET_ALL}")
                print(f"{Fore.WHITE}{summary_message}{Style.RESET_ALL}")
                
                # Confirm test file generation
                confirm = input(f"\n{Fore.YELLOW}Generate test.xlsx file? (y/n):{Style.RESET_ALL} ").strip().lower()
                if confirm != 'y':
                    print(f"{Fore.YELLOW}Operation cancelled.{Style.RESET_ALL}")
                    return False
                
                # Create test directory if it doesn't exist
                test_dir = os.path.join(SCRIPT_DIR, "test")
                os.makedirs(test_dir, exist_ok=True)
                
                # Copy template to test.xlsx
                template_path = os.path.join(SCRIPT_DIR, "templates", "loadsheet.xlsx")
                test_file_path = os.path.join(test_dir, "test.xlsx")
                
                if not os.path.exists(template_path):
                    print(f"{Fore.RED}Template file not found at {template_path}{Style.RESET_ALL}")
                    return False
                
                # Copy template file
                import shutil
                shutil.copy2(template_path, test_file_path)
                
                # Load the workbook
                wb = load_workbook(test_file_path)
                ws = wb["Loadsheet"]  # Use the correct sheet name
                
                try:
                    def safe_cell_write(cell_ref, value):
                        """Safely write to a cell."""
                        try:
                            cell = ws[cell_ref]
                            cell.value = value
                        except Exception as e:
                            print(f"{Fore.YELLOW}Warning: Could not write to cell {cell_ref}: {e}{Style.RESET_ALL}")
                    
                    # Update header information
                    if collections:
                        date_str = str(collections[0][3])
                        try:
                            if len(date_str) == 8:  # Ensure date string is in YYYYMMDD format
                                date_obj = datetime.strptime(date_str, '%Y%m%d')
                                safe_cell_write('C6', date_obj.strftime('%d/%m/%Y'))  # Date
                                safe_cell_write('H46', date_obj.strftime('%d/%m/%Y'))  # Collection date
                        except ValueError as e:
                            print(f"{Fore.YELLOW}Warning: Error parsing date ({date_str}): {e}{Style.RESET_ALL}")
                    
                    if deliveries:
                        date_str = str(deliveries[0][3])
                        try:
                            if len(date_str) == 8:  # Ensure date string is in YYYYMMDD format
                                date_obj = datetime.strptime(date_str, '%Y%m%d')
                                safe_cell_write('C46', date_obj.strftime('%d/%m/%Y'))  # Delivery date
                        except ValueError as e:
                            print(f"{Fore.YELLOW}Warning: Error parsing date ({date_str}): {e}{Style.RESET_ALL}")
                    
                    safe_cell_write('G6', str(load_number))  # Load Number
                    safe_cell_write('I6', str(load_number))  # Job ID (using load number)
                    
                    # Update collection and delivery locations
                    if collections:
                        # Create a set of unique collection locations
                        unique_collections = {}
                        for collection in collections:
                            location = f"{collection[2]} - {collection[5]}" if collection[2] and collection[5] else collection[2] or ''
                            if location not in unique_collections:
                                unique_collections[location] = 1
                            else:
                                unique_collections[location] += 1
                        
                        # Join all locations with newlines
                        collection_text = '\n'.join(unique_collections.keys())
                        safe_cell_write('B9', collection_text)
                    
                    if deliveries:
                        # Create a set of unique delivery locations
                        unique_deliveries = {}
                        for delivery in deliveries:
                            location = f"{delivery[2]} - {delivery[5]}" if delivery[2] and delivery[5] else delivery[2] or ''
                            if location not in unique_deliveries:
                                unique_deliveries[location] = 1
                            else:
                                unique_deliveries[location] += 1
                        
                        # Join all locations with newlines
                        delivery_text = '\n'.join(unique_deliveries.keys())
                        safe_cell_write('F9', delivery_text)
                    
                    # Update vehicle information
                    for i, vehicle in enumerate(formatted_vehicles[:8]):  # Handle up to 8 vehicles
                        base_row = 11 + (i * 4)  # Starting from row 11, increment by 4 for each car
                        
                        # Car details
                        safe_cell_write(f'B{base_row}', str(vehicle[0] or ''))  # Make + Model
                        safe_cell_write(f'B{base_row + 2}', str(vehicle[1] or ''))  # Registration
                        safe_cell_write(f'E{base_row - 1}', 'N')  # Offloaded (default)
                        safe_cell_write(f'G{base_row - 1}', 'Y')  # Documents (default)
                        safe_cell_write(f'I{base_row - 1}', str(vehicle[4] or 'Y'))  # Spare Keys
                        if vehicle[6]:  # Notes
                            safe_cell_write(f'C{base_row}', str(vehicle[6]))
                    
                    # Generate and add load summary message
                    summary_message = self.generate_load_summary(formatted_vehicles)
                    safe_cell_write('C39', summary_message)
                    
                    # Add signatures if auto_signature is enabled
                    if self.auto_signature:
                        self.add_signatures(ws)
                    
                    # Save the workbook
                    wb.save(test_file_path)
                    print(f"{Fore.GREEN}Test file generated successfully at: {test_file_path}{Style.RESET_ALL}")
                    
                    # Ask if user wants to verify the file
                    verify = input(f"\n{Fore.YELLOW}Open test.xlsx to verify? (y/n):{Style.RESET_ALL} ").strip().lower()
                    if verify == 'y':
                        try:
                            if os.name == 'nt':  # Windows
                                os.startfile(test_file_path)
                            elif os.name == 'posix':  # macOS and Linux
                                import subprocess
                                subprocess.run(['xdg-open', test_file_path])
                        except Exception as e:
                            print(f"{Fore.YELLOW}Warning: Could not open file automatically: {e}{Style.RESET_ALL}")
                            print(f"{Fore.CYAN}Please open the file manually at: {test_file_path}{Style.RESET_ALL}")
                    
                    return True
                    
                except Exception as e:
                    print(f"{Fore.RED}Error updating Excel file: {e}{Style.RESET_ALL}")
                    logging.error(f"Error updating Excel file: {e}", exc_info=True)
                    return False
                
            except Exception as e:
                print(f"{Fore.RED}Error during query execution: {e}{Style.RESET_ALL}")
                logging.error(f"Error during query execution: {e}", exc_info=True)
                return False
            finally:
                if 'cursor' in locals():
                    cursor.close()
                if 'conn' in locals():
                    conn.close()
            
        except Exception as e:
            logging.error(f"Error in test_loadsheet: {e}", exc_info=True)
            print(f"{Fore.RED}Error generating test loadsheet: {e}{Style.RESET_ALL}")
            return False

    def toggle_auto_signature(self):
        """Toggle auto signature feature on/off."""
        self.auto_signature = not self.auto_signature
        status = "enabled" if self.auto_signature else "disabled"
        print(f"{Fore.GREEN}Auto signature {status}.{Style.RESET_ALL}")

    def test_load_details(self):
        """Test getting load details directly from PostgreSQL."""
        try:
            # Get list of recent Sundays
            selected_sunday = self.select_week()
            if not selected_sunday:
                return False
                
            # Get loads for the selected week
            loads = self.get_loads_for_week(selected_sunday)
            if not loads:
                print(f"{Fore.YELLOW}No loads found for this week.{Style.RESET_ALL}")
                return False
                
            print(f"\n{Fore.CYAN}Available loads for testing:{Style.RESET_ALL}")
            for i, load in enumerate(loads, 1):
                print(f"{Fore.WHITE}{i}. {Fore.YELLOW}Load {load[0]}{Style.RESET_ALL}")
            
            load_choice = input(f"\n{Fore.CYAN}Enter load number (1-{len(loads)}):{Style.RESET_ALL} ").strip()
            try:
                load_idx = int(load_choice) - 1
                if not (0 <= load_idx < len(loads)):
                    print(f"{Fore.RED}Invalid selection.{Style.RESET_ALL}")
                    return False
                load_number = loads[load_idx][0]
            except ValueError:
                print(f"{Fore.RED}Invalid input.{Style.RESET_ALL}")
                return False
            
            print(f"\n{Fore.CYAN}Testing load details retrieval for load {load_number}{Style.RESET_ALL}")
            
            # Test database connection
            try:
                conn = psycopg2.connect(**self.pg_config)
                cursor = conn.cursor()
                print(f"{Fore.GREEN}Database connection successful.{Style.RESET_ALL}")
            except Exception as e:
                print(f"{Fore.RED}Database connection failed: {e}{Style.RESET_ALL}")
                return False
            
            try:
                # Test getting collections
                print(f"\n{Fore.YELLOW}Testing collections query:{Style.RESET_ALL}")
                cursor.execute("""
                    SELECT 
                        j.dwjtype,
                        j.dwjcust,
                        j.dwjname,
                        j.dwjdate,
                        j.dwjadrcod,
                        j.dwjpostco,
                        j.dwjvehs,
                        v.dwvvehref,
                        v.dwvmoddes,
                        COALESCE(e.sparekeys, 'Y') as sparekeys,
                        COALESCE(e.extra, 'Y') as extra,
                        COALESCE(e.carnotes, '') as carnotes,
                        v.dwvcolcod,
                        v.dwvdelcod
                    FROM public.dwjjob j
                    LEFT JOIN public.dwvveh v ON j.dwjload = v.dwvload AND j.dwjadrcod = v.dwvcolcod
                    LEFT JOIN public.extracarinfo e ON v.dwvkey = e.idkey
                    WHERE j.dwjload = %s
                    AND j.dwjtype = 'C'
                    ORDER BY j.dwjdate, j.dwjcust
                """, (load_number,))
                
                collections = cursor.fetchall()
                print(f"{Fore.WHITE}Found {len(collections)} collections:{Style.RESET_ALL}")
                for i, collection in enumerate(collections, 1):
                    print(f"\n{Fore.YELLOW}Collection {i}:{Style.RESET_ALL}")
                    print(f"Type: {collection[0]}")
                    print(f"Customer: {collection[1]}")
                    print(f"Name: {collection[2]}")
                    print(f"Date: {collection[3]}")
                    print(f"Address Code: {collection[4]}")
                    print(f"Postcode: {collection[5]}")
                    print(f"Vehicles: {collection[6]}")
                    print(f"Vehicle Ref: {collection[7]}")
                    print(f"Model: {collection[8]}")
                    print(f"Spare Keys: {collection[9]}")
                    print(f"Extra: {collection[10]}")
                    print(f"Notes: {collection[11]}")
                    print(f"Collection Code: {collection[12]}")
                    print(f"Delivery Code: {collection[13]}")
                
                # Test getting deliveries
                print(f"\n{Fore.YELLOW}Testing deliveries query:{Style.RESET_ALL}")
                cursor.execute("""
                    SELECT 
                        j.dwjtype,
                        j.dwjcust,
                        j.dwjname,
                        j.dwjdate,
                        j.dwjadrcod,
                        j.dwjpostco,
                        j.dwjvehs,
                        v.dwvvehref,
                        v.dwvmoddes,
                        COALESCE(e.sparekeys, 'Y') as sparekeys,
                        COALESCE(e.extra, 'Y') as extra,
                        COALESCE(e.carnotes, '') as carnotes,
                        v.dwvcolcod,
                        v.dwvdelcod
                    FROM public.dwjjob j
                    LEFT JOIN public.dwvveh v ON j.dwjload = v.dwvload AND j.dwjadrcod = v.dwvdelcod
                    LEFT JOIN public.extracarinfo e ON v.dwvkey = e.idkey
                    WHERE j.dwjload = %s
                    AND j.dwjtype = 'D'
                    ORDER BY j.dwjdate, j.dwjcust
                """, (load_number,))
                
                deliveries = cursor.fetchall()
                print(f"{Fore.WHITE}Found {len(deliveries)} deliveries:{Style.RESET_ALL}")
                for i, delivery in enumerate(deliveries, 1):
                    print(f"\n{Fore.YELLOW}Delivery {i}:{Style.RESET_ALL}")
                    print(f"Type: {delivery[0]}")
                    print(f"Customer: {delivery[1]}")
                    print(f"Name: {delivery[2]}")
                    print(f"Date: {delivery[3]}")
                    print(f"Address Code: {delivery[4]}")
                    print(f"Postcode: {delivery[5]}")
                    print(f"Vehicles: {delivery[6]}")
                    print(f"Vehicle Ref: {delivery[7]}")
                    print(f"Model: {delivery[8]}")
                    print(f"Spare Keys: {delivery[9]}")
                    print(f"Extra: {delivery[10]}")
                    print(f"Notes: {delivery[11]}")
                    print(f"Collection Code: {delivery[12]}")
                    print(f"Delivery Code: {delivery[13]}")
                
                # Test getting vehicle details
                print(f"\n{Fore.YELLOW}Testing vehicle details query:{Style.RESET_ALL}")
                cursor.execute("""
                    SELECT DISTINCT
                        v.dwvvehref,
                        v.dwvmoddes,
                        v.dwvcolcod,
                        v.dwvdelcod,
                        COALESCE(e.sparekeys, 'Y') as sparekeys,
                        COALESCE(e.extra, 'Y') as extra,
                        COALESCE(e.carnotes, '') as carnotes
                    FROM public.dwvveh v
                    LEFT JOIN public.extracarinfo e ON v.dwvkey = e.idkey
                    WHERE v.dwvload = %s
                    ORDER BY v.dwvvehref
                """, (load_number,))
                
                vehicles = cursor.fetchall()
                print(f"{Fore.WHITE}Found {len(vehicles)} vehicles:{Style.RESET_ALL}")
                for i, vehicle in enumerate(vehicles, 1):
                    print(f"\n{Fore.YELLOW}Vehicle {i}:{Style.RESET_ALL}")
                    print(f"Reference: {vehicle[0]}")
                    print(f"Model: {vehicle[1]}")
                    print(f"Collection Code: {vehicle[2]}")
                    print(f"Delivery Code: {vehicle[3]}")
                    print(f"Spare Keys: {vehicle[4]}")
                    print(f"Extra: {vehicle[5]}")
                    print(f"Notes: {vehicle[6]}")
                
                cursor.close()
                conn.close()
                print(f"\n{Fore.GREEN}Load details retrieval test completed successfully.{Style.RESET_ALL}")
                return True
                
            except Exception as e:
                print(f"{Fore.RED}Error during query execution: {e}{Style.RESET_ALL}")
                logging.error(f"Error during query execution: {e}", exc_info=True)
                return False
            finally:
                if 'cursor' in locals():
                    cursor.close()
                if 'conn' in locals():
                    conn.close()
            
        except Exception as e:
            logging.error(f"Error in test_load_details: {e}", exc_info=True)
            print(f"{Fore.RED}Error testing load details: {e}{Style.RESET_ALL}")
            return False

    def print_menu(self):
        """Print the menu with fancy formatting."""
        menu_border = f"{Fore.BLUE}{'═' * 60}{Style.RESET_ALL}"
        menu_title = f"{Fore.CYAN}{'▌' * 5} Paperwork Manager {'▌' * 5}{Style.RESET_ALL}"
        
        print("\n" + menu_border)
        print(menu_title)
        print(menu_border)
        print(f"{Fore.YELLOW}┌──────────────────────────────────────┐{Style.RESET_ALL}")
        print(f"{Fore.YELLOW}│{Style.RESET_ALL} {Fore.WHITE}1.{Style.RESET_ALL} {Fore.CYAN}Create Loadsheet                {Fore.YELLOW}│{Style.RESET_ALL}")
        print(f"{Fore.YELLOW}│{Style.RESET_ALL} {Fore.WHITE}2.{Style.RESET_ALL} {Fore.CYAN}Create Timesheet                {Fore.YELLOW}│{Style.RESET_ALL}")
        print(f"{Fore.YELLOW}│{Style.RESET_ALL} {Fore.WHITE}3.{Style.RESET_ALL} {Fore.CYAN}Create All Paperwork            {Fore.YELLOW}│{Style.RESET_ALL}")
        print(f"{Fore.YELLOW}│{Style.RESET_ALL} {Fore.WHITE}4.{Style.RESET_ALL} {Fore.CYAN}Test Loadsheet                 {Fore.YELLOW}│{Style.RESET_ALL}")
        print(f"{Fore.YELLOW}│{Style.RESET_ALL} {Fore.WHITE}5.{Style.RESET_ALL} {Fore.CYAN}Test Load Details              {Fore.YELLOW}│{Style.RESET_ALL}")
        print(f"{Fore.YELLOW}│{Style.RESET_ALL} {Fore.WHITE}6.{Style.RESET_ALL} {Fore.CYAN}Toggle Auto Signature          {Fore.YELLOW}│{Style.RESET_ALL}")
        print(f"{Fore.YELLOW}│{Style.RESET_ALL} {Fore.WHITE}7.{Style.RESET_ALL} {Fore.CYAN}Exit                         {Fore.YELLOW}│{Style.RESET_ALL}")
        print(f"{Fore.YELLOW}└──────────────────────────────────────┘{Style.RESET_ALL}")
        
        print(f"{Fore.CYAN}Enter your choice (1-7):{Style.RESET_ALL} ", end="")

    def run(self):
        """Run the main application loop."""
        print(f"{Fore.BLUE}{'═' * 60}{Style.RESET_ALL}")
        print(f"{Fore.CYAN}   Paperwork Manager{Style.RESET_ALL}")
        print(f"{Fore.BLUE}{'═' * 60}{Style.RESET_ALL}")
        
        while True:
            self.print_menu()
            choice = input()
            
            if choice == '1':
                selected_sunday = self.select_week()
                if selected_sunday:
                    loads = self.get_loads_for_week(selected_sunday)
                    if loads:
                        print(f"\n{Fore.CYAN}Available loads:{Style.RESET_ALL}")
                        for i, load in enumerate(loads, 1):
                            print(f"{Fore.WHITE}{i}. {Fore.YELLOW}Load {load[0]}{Style.RESET_ALL}")
                        
                        load_choice = input(f"\n{Fore.CYAN}Enter load number (1-{len(loads)}):{Style.RESET_ALL} ").strip()
                        try:
                            load_idx = int(load_choice) - 1
                            if 0 <= load_idx < len(loads):
                                self.create_loadsheet(loads[load_idx][0])
                        except ValueError:
                            print(f"{Fore.RED}Invalid input.{Style.RESET_ALL}")
                    else:
                        print(f"{Fore.YELLOW}No loads found for this week.{Style.RESET_ALL}")
                        
            elif choice == '2':
                selected_sunday = self.select_week()
                if selected_sunday:
                    self.create_timesheet(selected_sunday)
                    
            elif choice == '3':
                selected_sunday = self.select_week()
                if selected_sunday:
                    self.create_all_paperwork(selected_sunday)
                    
            elif choice == '4':
                self.test_loadsheet()
                
            elif choice == '5':
                self.test_load_details()
                
            elif choice == '6':
                self.toggle_auto_signature()
                
            elif choice == '7':
                print(f"{Fore.GREEN}Exiting...{Style.RESET_ALL}")
                break
                
            else:
                print(f"{Fore.RED}Invalid choice. Please try again.{Style.RESET_ALL}")

if __name__ == "__main__":
    manager = PaperworkManager()
    try:
        manager.run()
    except KeyboardInterrupt:
        print(f"\n{Fore.YELLOW}Operation interrupted. Exiting...{Style.RESET_ALL}")
    except Exception as e:
        print(f"{Fore.RED}An unexpected error occurred: {e}{Style.RESET_ALL}")
    finally:
        print(f"{Fore.GREEN}Program terminated.{Style.RESET_ALL}") 
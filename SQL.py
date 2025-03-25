#!/usr/bin/env python3
import os
import sys
from datetime import datetime, timedelta
import colorama
from colorama import Fore, Back, Style
import psycopg2
import configparser
import logging
from pathlib import Path
import json

# Initialize colorama for cross-platform terminal colors
colorama.init(autoreset=True)

# Setup logging
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_DIR = os.path.join(SCRIPT_DIR, "logs")
SQL_DIR = os.path.join(SCRIPT_DIR, "SQL")

# Ensure directories exist
os.makedirs(LOG_DIR, exist_ok=True)
os.makedirs(SQL_DIR, exist_ok=True)

# Setup logging configuration
LOG_FILE = os.path.join(LOG_DIR, f"timesheet_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log")
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler()
    ]
)

class TimesheetManager:
    def __init__(self):
        """Initialize the timesheet manager with PostgreSQL configuration."""
        self.pg_config = self.load_pg_config()
        self.setup_database()
        self.schema_data = self.load_schema()
        
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

    def setup_database(self):
        """Create the hours table if it doesn't exist."""
        if not self.pg_config:
            print(f"{Fore.RED}PostgreSQL configuration not found. Please check sql.ini file.{Style.RESET_ALL}")
            return

        try:
            conn = psycopg2.connect(**self.pg_config)
            cursor = conn.cursor()
            
            # Create hours table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS public.hours (
                    id SERIAL PRIMARY KEY,
                    work_date DATE NOT NULL,
                    start_time TIME NOT NULL,
                    finish_time TIME NOT NULL,
                    total_hours DECIMAL(5,2) GENERATED ALWAYS AS 
                        (EXTRACT(EPOCH FROM (finish_time - start_time))/3600) STORED,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Create index on work_date
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_hours_work_date 
                ON public.hours(work_date)
            """)
            
            # Create extra car info table if it doesn't exist
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS public.extracarinfo (
                    idkey text PRIMARY KEY,
                    carreg text NOT NULL,
                    sparekeys char(1) DEFAULT 'Y',
                    photos text[] DEFAULT '{}',
                    carnotes text DEFAULT '',
                    extra char(1) DEFAULT 'Y',
                    created_at timestamp DEFAULT CURRENT_TIMESTAMP,
                    updated_at timestamp DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Create index on carreg
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_extracarinfo_carreg 
                ON public.extracarinfo(carreg)
            """)
            
            conn.commit()
            logging.info("Database setup completed successfully")
            
        except Exception as e:
            logging.error(f"Error setting up database: {e}")
            print(f"{Fore.RED}Error setting up database: {e}{Style.RESET_ALL}")
        finally:
            if 'cursor' in locals():
                cursor.close()
            if 'conn' in locals():
                conn.close()

    def add_work_day(self):
        """Add a new work day entry with interactive time selection."""
        try:
            # Get last 7 days
            today = datetime.now()
            dates = [(today - timedelta(days=i)).strftime("%A %d-%m-%Y") 
                    for i in range(7)]
            
            print(f"\n{Fore.CYAN}Select a day:{Style.RESET_ALL}")
            for i, date in enumerate(dates, 1):
                print(f"{Fore.WHITE}{i}. {Fore.YELLOW}{date}{Style.RESET_ALL}")
            
            choice = input(f"\n{Fore.CYAN}Enter day number (1-7):{Style.RESET_ALL} ").strip()
            try:
                day_idx = int(choice) - 1
                if not (0 <= day_idx < len(dates)):
                    print(f"{Fore.RED}Invalid selection.{Style.RESET_ALL}")
                    return
                
                selected_date = today - timedelta(days=day_idx)
                
                # Default times
                start_hour = 7
                finish_hour = 19
                
                print(f"\n{Fore.CYAN}Selected date: {Fore.GREEN}{selected_date.strftime('%A %d-%m-%Y')}{Style.RESET_ALL}")
                
                while True:
                    # Clear screen and show current times
                    os.system('cls' if os.name == 'nt' else 'clear')
                    print(f"\n{Fore.CYAN}Date: {Fore.GREEN}{selected_date.strftime('%A %d-%m-%Y')}{Style.RESET_ALL}")
                    print(f"{Fore.WHITE}Start Time: {Fore.YELLOW}{start_hour:02d}:00{Style.RESET_ALL}")
                    print(f"{Fore.WHITE}Finish Time: {Fore.YELLOW}{finish_hour:02d}:00{Style.RESET_ALL}")
                    print(f"{Fore.WHITE}Total Hours: {Fore.GREEN}{finish_hour - start_hour}{Style.RESET_ALL}")
                    print(f"\n{Fore.YELLOW}Options:{Style.RESET_ALL}")
                    print(f"{Fore.WHITE}1. Adjust Start Time{Style.RESET_ALL}")
                    print(f"{Fore.WHITE}2. Adjust Finish Time{Style.RESET_ALL}")
                    print(f"{Fore.WHITE}3. Save and Exit{Style.RESET_ALL}")
                    
                    choice = input(f"\n{Fore.CYAN}Enter your choice (1-3):{Style.RESET_ALL} ").strip()
                    
                    if choice == '1':
                        while True:
                            try:
                                new_start = int(input(f"{Fore.CYAN}Enter new start hour (0-{finish_hour-1}):{Style.RESET_ALL} ").strip())
                                if 0 <= new_start < finish_hour:
                                    start_hour = new_start
                                    break
                                else:
                                    print(f"{Fore.RED}Invalid hour. Must be between 0 and {finish_hour-1}{Style.RESET_ALL}")
                            except ValueError:
                                print(f"{Fore.RED}Please enter a valid number.{Style.RESET_ALL}")
                    
                    elif choice == '2':
                        while True:
                            try:
                                new_finish = int(input(f"{Fore.CYAN}Enter new finish hour ({start_hour+1}-23):{Style.RESET_ALL} ").strip())
                                if start_hour < new_finish <= 23:
                                    finish_hour = new_finish
                                    break
                                else:
                                    print(f"{Fore.RED}Invalid hour. Must be between {start_hour+1} and 23{Style.RESET_ALL}")
                            except ValueError:
                                print(f"{Fore.RED}Please enter a valid number.{Style.RESET_ALL}")
                    
                    elif choice == '3':
                        break
                    else:
                        print(f"{Fore.RED}Invalid choice.{Style.RESET_ALL}")
                
                # Save to database
                conn = psycopg2.connect(**self.pg_config)
                cursor = conn.cursor()
                
                # Check if entry exists for this date
                cursor.execute("""
                    SELECT id FROM public.hours 
                    WHERE work_date = %s
                """, (selected_date.date(),))
                
                if cursor.fetchone():
                    print(f"{Fore.YELLOW}Entry already exists for this date. Updating...{Style.RESET_ALL}")
                    cursor.execute("""
                        UPDATE public.hours 
                        SET start_time = %s, finish_time = %s, updated_at = CURRENT_TIMESTAMP
                        WHERE work_date = %s
                    """, (f"{start_hour:02d}:00", f"{finish_hour:02d}:00", selected_date.date()))
                else:
                    cursor.execute("""
                        INSERT INTO public.hours (work_date, start_time, finish_time)
                        VALUES (%s, %s, %s)
                    """, (selected_date.date(), f"{start_hour:02d}:00", f"{finish_hour:02d}:00"))
                
                conn.commit()
                print(f"{Fore.GREEN}Times saved successfully!{Style.RESET_ALL}")
                
            except ValueError:
                print(f"{Fore.RED}Invalid input.{Style.RESET_ALL}")
                
        except Exception as e:
            logging.error(f"Error adding work day: {e}")
            print(f"{Fore.RED}Error adding work day: {e}{Style.RESET_ALL}")
        finally:
            if 'cursor' in locals():
                cursor.close()
            if 'conn' in locals():
                conn.close()

    def show_weekly_hours(self):
        """Show hours worked for a selected week."""
        try:
            # Get list of recent Sundays
            today = datetime.now()
            current_weekday = today.weekday()
            # Calculate last Sunday (weekday 6 is Sunday)
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
            
            # Validate that we have actual Sundays
            for date_str in sundays:
                date = datetime.strptime(date_str, "%A %d-%m-%Y")
                if date.weekday() != 6:  # 6 is Sunday
                    logging.error(f"Invalid Sunday date found: {date_str} (weekday: {date.weekday()})")
                    raise ValueError(f"Invalid Sunday date: {date_str}")
            
            logging.info(f"Available Sundays: {sundays}")
            
            print(f"\n{Fore.CYAN}Select week end date (Sunday):{Style.RESET_ALL}")
            for i, sunday in enumerate(sundays, 1):
                print(f"{Fore.WHITE}{i}. {Fore.YELLOW}{sunday}{Style.RESET_ALL}")
            
            choice = input(f"\n{Fore.CYAN}Enter week number (1-{len(sundays)}):{Style.RESET_ALL} ").strip()
            try:
                week_idx = int(choice) - 1
                if not (0 <= week_idx < len(sundays)):
                    print(f"{Fore.RED}Invalid selection.{Style.RESET_ALL}")
                    return
                
                # Calculate selected Sunday based on the index
                if week_idx == 0:  # Next Sunday
                    selected_sunday = next_sunday
                else:  # Past Sundays
                    selected_sunday = last_sunday - timedelta(weeks=week_idx-1)
                
                week_start = selected_sunday - timedelta(days=6)  # Monday
                
                # Get data from database
                conn = psycopg2.connect(**self.pg_config)
                cursor = conn.cursor()
                
                cursor.execute("""
                    SELECT work_date, start_time, finish_time, total_hours
                    FROM public.hours
                    WHERE work_date BETWEEN %s AND %s
                    ORDER BY work_date
                """, (week_start.date(), selected_sunday.date()))
                
                entries = cursor.fetchall()
                
                if not entries:
                    print(f"{Fore.YELLOW}No entries found for this week.{Style.RESET_ALL}")
                    return
                
                # Calculate total hours
                total_hours = sum(entry[3] for entry in entries)
                
                print(f"\n{Fore.CYAN}Week of {week_start.strftime('%d-%m-%Y')} to {selected_sunday.strftime('%d-%m-%Y')}:{Style.RESET_ALL}")
                print(f"{Fore.WHITE}{'Day':<10} | {'Start':<8} | {'Finish':<8} | {'Hours':<6}{Style.RESET_ALL}")
                print("-" * 40)
                
                for entry in entries:
                    date, start, finish, hours = entry
                    print(f"{Fore.WHITE}{date.strftime('%A'):<10} | {Fore.YELLOW}{start.strftime('%H:%M'):<8} | {Fore.YELLOW}{finish.strftime('%H:%M'):<8} | {Fore.GREEN}{hours:<6.1f}{Style.RESET_ALL}")
                
                print("-" * 40)
                print(f"{Fore.WHITE}Total Hours: {Fore.GREEN}{total_hours:.1f}{Style.RESET_ALL}")
                
            except ValueError:
                print(f"{Fore.RED}Invalid input.{Style.RESET_ALL}")
                
        except Exception as e:
            logging.error(f"Error showing weekly hours: {e}")
            print(f"{Fore.RED}Error showing weekly hours: {e}{Style.RESET_ALL}")
        finally:
            if 'cursor' in locals():
                cursor.close()
            if 'conn' in locals():
                conn.close()

    def edit_work_day(self):
        """Edit an existing work day entry."""
        try:
            # Get last 7 days
            today = datetime.now()
            dates = [(today - timedelta(days=i)).strftime("%A %d-%m-%Y") 
                    for i in range(7)]
            
            print(f"\n{Fore.CYAN}Select a day to edit:{Style.RESET_ALL}")
            for i, date in enumerate(dates, 1):
                print(f"{Fore.WHITE}{i}. {Fore.YELLOW}{date}{Style.RESET_ALL}")
            
            choice = input(f"\n{Fore.CYAN}Enter day number (1-7):{Style.RESET_ALL} ").strip()
            try:
                day_idx = int(choice) - 1
                if not (0 <= day_idx < len(dates)):
                    print(f"{Fore.RED}Invalid selection.{Style.RESET_ALL}")
                    return
                
                selected_date = today - timedelta(days=day_idx)
                
                # Get current entry
                conn = psycopg2.connect(**self.pg_config)
                cursor = conn.cursor()
                
                cursor.execute("""
                    SELECT start_time, finish_time
                    FROM public.hours
                    WHERE work_date = %s
                """, (selected_date.date(),))
                
                result = cursor.fetchone()
                if not result:
                    print(f"{Fore.YELLOW}No entry found for this date.{Style.RESET_ALL}")
                    return
                
                start_hour = result[0].hour
                finish_hour = result[1].hour
                
                print(f"\n{Fore.CYAN}Editing date: {Fore.GREEN}{selected_date.strftime('%A %d-%m-%Y')}{Style.RESET_ALL}")
                
                while True:
                    # Clear screen and show current times
                    os.system('cls' if os.name == 'nt' else 'clear')
                    print(f"\n{Fore.CYAN}Date: {Fore.GREEN}{selected_date.strftime('%A %d-%m-%Y')}{Style.RESET_ALL}")
                    print(f"{Fore.WHITE}Start Time: {Fore.YELLOW}{start_hour:02d}:00{Style.RESET_ALL}")
                    print(f"{Fore.WHITE}Finish Time: {Fore.YELLOW}{finish_hour:02d}:00{Style.RESET_ALL}")
                    print(f"{Fore.WHITE}Total Hours: {Fore.GREEN}{finish_hour - start_hour}{Style.RESET_ALL}")
                    print(f"\n{Fore.YELLOW}Options:{Style.RESET_ALL}")
                    print(f"{Fore.WHITE}1. Adjust Start Time{Style.RESET_ALL}")
                    print(f"{Fore.WHITE}2. Adjust Finish Time{Style.RESET_ALL}")
                    print(f"{Fore.WHITE}3. Save and Exit{Style.RESET_ALL}")
                    
                    choice = input(f"\n{Fore.CYAN}Enter your choice (1-3):{Style.RESET_ALL} ").strip()
                    
                    if choice == '1':
                        while True:
                            try:
                                new_start = int(input(f"{Fore.CYAN}Enter new start hour (0-{finish_hour-1}):{Style.RESET_ALL} ").strip())
                                if 0 <= new_start < finish_hour:
                                    start_hour = new_start
                                    break
                                else:
                                    print(f"{Fore.RED}Invalid hour. Must be between 0 and {finish_hour-1}{Style.RESET_ALL}")
                            except ValueError:
                                print(f"{Fore.RED}Please enter a valid number.{Style.RESET_ALL}")
                    
                    elif choice == '2':
                        while True:
                            try:
                                new_finish = int(input(f"{Fore.CYAN}Enter new finish hour ({start_hour+1}-23):{Style.RESET_ALL} ").strip())
                                if start_hour < new_finish <= 23:
                                    finish_hour = new_finish
                                    break
                                else:
                                    print(f"{Fore.RED}Invalid hour. Must be between {start_hour+1} and 23{Style.RESET_ALL}")
                            except ValueError:
                                print(f"{Fore.RED}Please enter a valid number.{Style.RESET_ALL}")
                    
                    elif choice == '3':
                        break
                    else:
                        print(f"{Fore.RED}Invalid choice.{Style.RESET_ALL}")
                
                # Update database
                cursor.execute("""
                    UPDATE public.hours 
                    SET start_time = %s, finish_time = %s, updated_at = CURRENT_TIMESTAMP
                    WHERE work_date = %s
                """, (f"{start_hour:02d}:00", f"{finish_hour:02d}:00", selected_date.date()))
                
                conn.commit()
                print(f"{Fore.GREEN}Times updated successfully!{Style.RESET_ALL}")
                
            except ValueError:
                print(f"{Fore.RED}Invalid input.{Style.RESET_ALL}")
                
        except Exception as e:
            logging.error(f"Error editing work day: {e}")
            print(f"{Fore.RED}Error editing work day: {e}{Style.RESET_ALL}")
        finally:
            if 'cursor' in locals():
                cursor.close()
            if 'conn' in locals():
                conn.close()

    def delete_work_day(self):
        """Delete a work day entry."""
        try:
            # Get last 7 days
            today = datetime.now()
            dates = [(today - timedelta(days=i)).strftime("%A %d-%m-%Y") 
                    for i in range(7)]
            
            print(f"\n{Fore.CYAN}Select a day to delete:{Style.RESET_ALL}")
            for i, date in enumerate(dates, 1):
                print(f"{Fore.WHITE}{i}. {Fore.YELLOW}{date}{Style.RESET_ALL}")
            
            choice = input(f"\n{Fore.CYAN}Enter day number (1-7):{Style.RESET_ALL} ").strip()
            try:
                day_idx = int(choice) - 1
                if not (0 <= day_idx < len(dates)):
                    print(f"{Fore.RED}Invalid selection.{Style.RESET_ALL}")
                    return
                
                selected_date = today - timedelta(days=day_idx)
                
                # Confirm deletion
                confirm = input(f"{Fore.YELLOW}Are you sure you want to delete the entry for {selected_date.strftime('%A %d-%m-%Y')}? (y/n):{Style.RESET_ALL} ").strip().lower()
                if confirm != 'y':
                    print(f"{Fore.YELLOW}Deletion cancelled.{Style.RESET_ALL}")
                    return
                
                # Delete from database
                conn = psycopg2.connect(**self.pg_config)
                cursor = conn.cursor()
                
                cursor.execute("""
                    DELETE FROM public.hours
                    WHERE work_date = %s
                """, (selected_date.date(),))
                
                if cursor.rowcount > 0:
                    conn.commit()
                    print(f"{Fore.GREEN}Entry deleted successfully!{Style.RESET_ALL}")
                else:
                    print(f"{Fore.YELLOW}No entry found for this date.{Style.RESET_ALL}")
                
            except ValueError:
                print(f"{Fore.RED}Invalid input.{Style.RESET_ALL}")
                
        except Exception as e:
            logging.error(f"Error deleting work day: {e}")
            print(f"{Fore.RED}Error deleting work day: {e}{Style.RESET_ALL}")
        finally:
            if 'cursor' in locals():
                cursor.close()
            if 'conn' in locals():
                conn.close()

    def show_load_details(self):
        """Show load details for a selected week."""
        try:
            # Get list of recent Sundays
            today = datetime.now()
            current_weekday = today.weekday()
            # Calculate last Sunday (weekday 6 is Sunday)
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
            
            # Validate that we have actual Sundays
            for date_str in sundays:
                date = datetime.strptime(date_str, "%A %d-%m-%Y")
                if date.weekday() != 6:  # 6 is Sunday
                    logging.error(f"Invalid Sunday date found: {date_str} (weekday: {date.weekday()})")
                    raise ValueError(f"Invalid Sunday date: {date_str}")
            
            logging.info(f"Available Sundays: {sundays}")
            
            print(f"\n{Fore.CYAN}Select week end date (Sunday):{Style.RESET_ALL}")
            for i, sunday in enumerate(sundays, 1):
                print(f"{Fore.WHITE}{i}. {Fore.YELLOW}{sunday}{Style.RESET_ALL}")
            
            choice = input(f"\n{Fore.CYAN}Enter week number (1-{len(sundays)}):{Style.RESET_ALL} ").strip()
            try:
                week_idx = int(choice) - 1
                if not (0 <= week_idx < len(sundays)):
                    print(f"{Fore.RED}Invalid selection.{Style.RESET_ALL}")
                    return
                
                # Calculate selected Sunday based on the index
                if week_idx == 0:  # Next Sunday
                    selected_sunday = next_sunday
                else:  # Past Sundays
                    selected_sunday = last_sunday - timedelta(weeks=week_idx-1)
                
                week_start = selected_sunday - timedelta(days=6)  # Monday
                
                # Format dates for SQL query (YYYYMMDD)
                start_date_str = week_start.strftime("%Y%m%d")
                end_date_str = selected_sunday.strftime("%Y%m%d")
                
                logging.info(f"Selected date range: {start_date_str} to {end_date_str}")
                
                # Get data from database
                conn = psycopg2.connect(**self.pg_config)
                cursor = conn.cursor()
                
                # Get unique load numbers for the week
                cursor.execute("""
                    SELECT DISTINCT dwvload
                    FROM public.dwvveh
                    WHERE dwvexpdat BETWEEN %s AND %s
                    AND dwvload IS NOT NULL
                    ORDER BY dwvload
                """, (start_date_str, end_date_str))
                
                loads = cursor.fetchall()
                if not loads:
                    print(f"{Fore.YELLOW}No loads found for this week.{Style.RESET_ALL}")
                    return
                
                logging.info(f"Found {len(loads)} loads for the selected week")
                
                print(f"\n{Fore.CYAN}Loads for week of {week_start.strftime('%d-%m-%Y')} to {selected_sunday.strftime('%d-%m-%Y')}:{Style.RESET_ALL}")
                for i, (load_num,) in enumerate(loads, 1):
                    print(f"{Fore.WHITE}{i}. {Fore.YELLOW}Load {load_num}{Style.RESET_ALL}")
                
                load_choice = input(f"\n{Fore.CYAN}Enter load number (1-{len(loads)}):{Style.RESET_ALL} ").strip()
                try:
                    load_idx = int(load_choice) - 1
                    if not (0 <= load_idx < len(loads)):
                        print(f"{Fore.RED}Invalid selection.{Style.RESET_ALL}")
                        return
                    
                    selected_load = loads[load_idx][0]
                    logging.info(f"Selected load: {selected_load}")
                    
                    # Get vehicles with their collection and delivery locations
                    cursor.execute("""
                        SELECT DISTINCT 
                            v.dwvvehref,
                            v.dwvmoddes,
                            v.dwvcolcod,
                            v.dwvdelcod,
                            c.dwjname as collection_name,
                            d.dwjname as delivery_name,
                            COALESCE(e.sparekeys, 'Y') as sparekeys,
                            COALESCE(e.extra, 'Y') as extra,
                            COALESCE(e.carnotes, '') as carnotes
                        FROM public.dwvveh v
                        LEFT JOIN public.dwjjob c ON v.dwvcolcod = c.dwjadrcod AND c.dwjtype = 'C' AND c.dwjload = %s
                        LEFT JOIN public.dwjjob d ON v.dwvdelcod = d.dwjadrcod AND d.dwjtype = 'D' AND d.dwjload = %s
                        LEFT JOIN public.extracarinfo e ON v.dwvkey = e.idkey
                        WHERE v.dwvload = %s
                        AND v.dwvexpdat BETWEEN %s AND %s
                        ORDER BY v.dwvvehref
                    """, (selected_load, selected_load, selected_load, start_date_str, end_date_str))
                    
                    vehicles = cursor.fetchall()
                    
                    # Get collections
                    cursor.execute("""
                        SELECT DISTINCT dwjtype, dwjcust, dwjname, dwjdate, dwjadrcod
                        FROM public.dwjjob
                        WHERE dwjload = %s
                        AND dwjtype = 'C'
                        ORDER BY dwjdate, dwjcust
                    """, (selected_load,))
                    
                    collections = cursor.fetchall()
                    
                    # Get deliveries
                    cursor.execute("""
                        SELECT DISTINCT dwjtype, dwjcust, dwjname, dwjdate, dwjadrcod
                        FROM public.dwjjob
                        WHERE dwjload = %s
                        AND dwjtype = 'D'
                        ORDER BY dwjdate, dwjcust
                    """, (selected_load,))
                    
                    deliveries = cursor.fetchall()
                    
                    if not vehicles and not collections and not deliveries:
                        print(f"{Fore.YELLOW}No details found for this load.{Style.RESET_ALL}")
                        return
                    
                    print(f"\n{Fore.CYAN}Load {selected_load} Details:{Style.RESET_ALL}")
                    
                    # Get display settings from schema
                    job_display_columns = self.schema_data.get("display_settings", {}).get("job_columns", {})
                    vehicle_display_columns = self.schema_data.get("display_settings", {}).get("vehicle_columns", {})
                    
                    # Show collections with their vehicles
                    if collections:
                        print(f"\n{Fore.YELLOW}Collections:{Style.RESET_ALL}")
                        headers = []
                        for col_name, show in job_display_columns.items():
                            if show:
                                col_desc = self.schema_data.get("columns", {}).get(f"DWJJOB.{col_name}", {}).get("description", col_name)
                                headers.append(str(col_desc))
                        
                        if headers:
                            print(f"{Fore.WHITE}{' | '.join(headers)}{Style.RESET_ALL}")
                            print("-" * (len(' | '.join(headers)) + 2))
                            
                            for collection in collections:
                                values = []
                                for col_name, show in job_display_columns.items():
                                    if show:
                                        if col_name == "dwjType":
                                            values.append(str(collection[0]))
                                        elif col_name == "dwjCust":
                                            values.append(str(collection[1]))
                                        elif col_name == "dwjName":
                                            values.append(str(collection[2]))
                                        elif col_name == "dwjDate":
                                            values.append(datetime.strptime(str(collection[3]), "%Y%m%d").strftime("%d/%m/%Y"))
                                print(f"{' | '.join(values)}")
                                
                                # Show vehicles for this collection
                                collection_vehicles = [v for v in vehicles if v[2] == collection[4]]  # Match dwvcolcod with dwjadrcod
                                if collection_vehicles:
                                    print(f"{Fore.CYAN}  Vehicles:{Style.RESET_ALL}")
                                    for vehicle in collection_vehicles:
                                        print(f"    {Fore.WHITE}{vehicle[0]} - {vehicle[1]}{Style.RESET_ALL}")
                    
                    # Show deliveries with their vehicles
                    if deliveries:
                        print(f"\n{Fore.YELLOW}Deliveries:{Style.RESET_ALL}")
                        headers = []
                        for col_name, show in job_display_columns.items():
                            if show:
                                col_desc = self.schema_data.get("columns", {}).get(f"DWJJOB.{col_name}", {}).get("description", col_name)
                                headers.append(str(col_desc))
                        
                        if headers:
                            print(f"{Fore.WHITE}{' | '.join(headers)}{Style.RESET_ALL}")
                            print("-" * (len(' | '.join(headers)) + 2))
                            
                            for delivery in deliveries:
                                values = []
                                for col_name, show in job_display_columns.items():
                                    if show:
                                        if col_name == "dwjType":
                                            values.append(str(delivery[0]))
                                        elif col_name == "dwjCust":
                                            values.append(str(delivery[1]))
                                        elif col_name == "dwjName":
                                            values.append(str(delivery[2]))
                                        elif col_name == "dwjDate":
                                            values.append(datetime.strptime(str(delivery[3]), "%Y%m%d").strftime("%d/%m/%Y"))
                                print(f"{' | '.join(values)}")
                                
                                # Show vehicles for this delivery
                                delivery_vehicles = [v for v in vehicles if v[3] == delivery[4]]  # Match dwvdelcod with dwjadrcod
                                if delivery_vehicles:
                                    print(f"{Fore.CYAN}  Vehicles:{Style.RESET_ALL}")
                                    for vehicle in delivery_vehicles:
                                        print(f"    {Fore.WHITE}{vehicle[0]} - {vehicle[1]}{Style.RESET_ALL}")
                    
                    # Show all vehicles summary
                    if vehicles:
                        print(f"\n{Fore.YELLOW}All Vehicles:{Style.RESET_ALL}")
                        headers = []
                        for col_name, show in vehicle_display_columns.items():
                            if show:
                                col_desc = self.schema_data.get("columns", {}).get(f"DWVVEH.{col_name}", {}).get("description", col_name)
                                headers.append(str(col_desc))
                        
                        if headers:
                            print(f"{Fore.WHITE}{' | '.join(headers)}{Style.RESET_ALL}")
                            print("-" * (len(' | '.join(headers)) + 2))
                            
                            for vehicle in vehicles:
                                values = []
                                for col_name, show in vehicle_display_columns.items():
                                    if show:
                                        if col_name == "dwvVehRef":
                                            values.append(str(vehicle[0]))
                                        elif col_name == "dwvModDes":
                                            values.append(str(vehicle[1]))
                                        elif col_name == "spareKeys":
                                            values.append(str(vehicle[6]))
                                        elif col_name == "extra":
                                            values.append(str(vehicle[7]))
                                        elif col_name == "carNotes":
                                            values.append(str(vehicle[8]))
                                        else:
                                            values.append("")
                                print(f"{' | '.join(values)}")
                                
                                # Show collection and delivery assignments
                                collection_name = next((c[2] for c in collections if c[4] == vehicle[2]), "Unknown")
                                delivery_name = next((d[2] for d in deliveries if d[4] == vehicle[3]), "Unknown")
                                print(f"    {Fore.CYAN}Collection: {collection_name} | Delivery: {delivery_name}{Style.RESET_ALL}")
                    
                except ValueError:
                    print(f"{Fore.RED}Invalid input.{Style.RESET_ALL}")
                    
            except ValueError:
                print(f"{Fore.RED}Invalid input.{Style.RESET_ALL}")
                
        except Exception as e:
            logging.error(f"Error showing load details: {e}")
            print(f"{Fore.RED}Error showing load details: {e}{Style.RESET_ALL}")
        finally:
            if 'cursor' in locals():
                cursor.close()
            if 'conn' in locals():
                conn.close()

    def add_missing_cars(self):
        """Add missing cars to extracarinfo table."""
        try:
            conn = psycopg2.connect(**self.pg_config)
            cursor = conn.cursor()
            
            # Get all vehicles from dwvveh that aren't in extracarinfo
            cursor.execute("""
                SELECT v.dwvkey, v.dwvvehref
                FROM public.dwvveh v
                LEFT JOIN public.extracarinfo e ON v.dwvkey = e.idkey
                WHERE e.idkey IS NULL
                ORDER BY v.dwvvehref
            """)
            
            missing_cars = cursor.fetchall()
            
            if not missing_cars:
                print(f"{Fore.YELLOW}No missing cars found.{Style.RESET_ALL}")
                return
            
            print(f"\n{Fore.CYAN}Found {len(missing_cars)} missing cars:{Style.RESET_ALL}")
            for i, (key, reg) in enumerate(missing_cars, 1):
                print(f"{Fore.WHITE}{i}. {Fore.YELLOW}{reg}{Style.RESET_ALL}")
            
            confirm = input(f"\n{Fore.YELLOW}Add these cars to extracarinfo? (y/n):{Style.RESET_ALL} ").strip().lower()
            if confirm != 'y':
                print(f"{Fore.YELLOW}Operation cancelled.{Style.RESET_ALL}")
                return
            
            # Insert missing cars with explicit default values
            for key, reg in missing_cars:
                cursor.execute("""
                    INSERT INTO public.extracarinfo (idkey, carreg, sparekeys, extra, carnotes, photos)
                    VALUES (%s, %s, 'Y', 'Y', '', '{}')
                """, (key, reg))
            
            conn.commit()
            print(f"{Fore.GREEN}Successfully added {len(missing_cars)} cars to extracarinfo.{Style.RESET_ALL}")
            
        except Exception as e:
            logging.error(f"Error adding missing cars: {e}")
            print(f"{Fore.RED}Error adding missing cars: {e}{Style.RESET_ALL}")
        finally:
            if 'cursor' in locals():
                cursor.close()
            if 'conn' in locals():
                conn.close()

    def edit_car_info(self):
        """Edit extra information for a car."""
        try:
            # Get list of recent Sundays
            today = datetime.now()
            current_weekday = today.weekday()
            # Calculate last Sunday (weekday 6 is Sunday)
            days_to_last_sunday = (current_weekday + 1) % 7
            last_sunday = today - timedelta(days=days_to_last_sunday)
            
            # Show last 4 Sundays plus current/following week
            sundays = [(last_sunday - timedelta(weeks=i)).strftime("%A %d-%m-%Y") 
                      for i in range(4)]
            
            # Add current/following week if we're not already showing it
            next_sunday = last_sunday + timedelta(weeks=1)
            if next_sunday.strftime("%A %d-%m-%Y") not in sundays:
                sundays.insert(0, next_sunday.strftime("%A %d-%m-%Y"))
            
            # Validate that we have actual Sundays
            for date_str in sundays:
                date = datetime.strptime(date_str, "%A %d-%m-%Y")
                if date.weekday() != 6:  # 6 is Sunday
                    logging.error(f"Invalid Sunday date found: {date_str} (weekday: {date.weekday()})")
                    raise ValueError(f"Invalid Sunday date: {date_str}")
            
            logging.info(f"Available Sundays: {sundays}")
            
            print(f"\n{Fore.CYAN}Select week end date (Sunday):{Style.RESET_ALL}")
            for i, sunday in enumerate(sundays, 1):
                print(f"{Fore.WHITE}{i}. {Fore.YELLOW}{sunday}{Style.RESET_ALL}")
            
            choice = input(f"\n{Fore.CYAN}Enter week number (1-{len(sundays)}):{Style.RESET_ALL} ").strip()
            try:
                week_idx = int(choice) - 1
                if not (0 <= week_idx < len(sundays)):
                    print(f"{Fore.RED}Invalid selection.{Style.RESET_ALL}")
                    return
                
                # Calculate selected Sunday based on the index
                if week_idx == 0:  # Next Sunday
                    selected_sunday = next_sunday
                else:  # Past Sundays
                    selected_sunday = last_sunday - timedelta(weeks=week_idx-1)
                
                week_start = selected_sunday - timedelta(days=6)
                
                # Format dates for SQL query
                start_date_str = week_start.strftime("%Y%m%d")
                end_date_str = selected_sunday.strftime("%Y%m%d")
                
                # Get loads for the week
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
                if not loads:
                    print(f"{Fore.YELLOW}No loads found for this week.{Style.RESET_ALL}")
                    return
                
                print(f"\n{Fore.CYAN}Loads for week of {week_start.strftime('%d-%m-%Y')} to {selected_sunday.strftime('%d-%m-%Y')}:{Style.RESET_ALL}")
                for i, (load_num,) in enumerate(loads, 1):
                    print(f"{Fore.WHITE}{i}. {Fore.YELLOW}Load {load_num}{Style.RESET_ALL}")
                
                load_choice = input(f"\n{Fore.CYAN}Enter load number (1-{len(loads)}):{Style.RESET_ALL} ").strip()
                try:
                    load_idx = int(load_choice) - 1
                    if not (0 <= load_idx < len(loads)):
                        print(f"{Fore.RED}Invalid selection.{Style.RESET_ALL}")
                        return
                    
                    selected_load = loads[load_idx][0]
                    
                    # Get vehicles for this load
                    cursor.execute("""
                        SELECT DISTINCT 
                            v.dwvkey,
                            v.dwvvehref,
                            v.dwvmoddes,
                            COALESCE(e.sparekeys, 'Y') as sparekeys,
                            COALESCE(e.extra, 'Y') as extra,
                            COALESCE(e.carnotes, '') as carnotes
                        FROM public.dwvveh v
                        LEFT JOIN public.extracarinfo e ON v.dwvkey = e.idkey
                        WHERE v.dwvload = %s
                        AND v.dwvexpdat BETWEEN %s AND %s
                        ORDER BY v.dwvvehref
                    """, (selected_load, start_date_str, end_date_str))
                    
                    vehicles = cursor.fetchall()
                    if not vehicles:
                        print(f"{Fore.YELLOW}No vehicles found for this load.{Style.RESET_ALL}")
                        return
                    
                    while True:
                        print(f"\n{Fore.CYAN}Vehicles in Load {selected_load}:{Style.RESET_ALL}")
                        for i, (key, reg, model, sparekeys, extra, notes) in enumerate(vehicles, 1):
                            print(f"{Fore.WHITE}{i}. {Fore.YELLOW}{reg} - {model}{Style.RESET_ALL}")
                            print(f"   {Fore.CYAN}Spare Keys: {sparekeys} | Documents: {extra}{Style.RESET_ALL}")
                            if notes:
                                print(f"   {Fore.CYAN}Notes: {notes}{Style.RESET_ALL}")
                        
                        print(f"\n{Fore.YELLOW}Options:{Style.RESET_ALL}")
                        print(f"{Fore.WHITE}1. Edit Vehicle{Style.RESET_ALL}")
                        print(f"{Fore.WHITE}2. Done{Style.RESET_ALL}")
                        
                        choice = input(f"\n{Fore.CYAN}Enter your choice (1-2):{Style.RESET_ALL} ").strip()
                        
                        if choice == '1':
                            vehicle_choice = input(f"\n{Fore.CYAN}Enter vehicle number (1-{len(vehicles)}):{Style.RESET_ALL} ").strip()
                            try:
                                vehicle_idx = int(vehicle_choice) - 1
                                if not (0 <= vehicle_idx < len(vehicles)):
                                    print(f"{Fore.RED}Invalid selection.{Style.RESET_ALL}")
                                    continue
                                
                                key, reg, model, sparekeys, extra, notes = vehicles[vehicle_idx]
                                
                                print(f"\n{Fore.CYAN}Editing {reg} - {model}:{Style.RESET_ALL}")
                                print(f"{Fore.WHITE}Current Spare Keys: {Fore.YELLOW}{sparekeys}{Style.RESET_ALL}")
                                print(f"{Fore.WHITE}Current Documents: {Fore.YELLOW}{extra}{Style.RESET_ALL}")
                                if notes:
                                    print(f"{Fore.WHITE}Current Notes: {Fore.YELLOW}{notes}{Style.RESET_ALL}")
                                
                                # Edit spare keys
                                while True:
                                    new_sparekeys = input(f"\n{Fore.CYAN}Has spare keys? (Y/N):{Style.RESET_ALL} ").strip().upper()
                                    if new_sparekeys in ['Y', 'N']:
                                        break
                                    print(f"{Fore.RED}Please enter Y or N.{Style.RESET_ALL}")
                                
                                # Edit documents
                                while True:
                                    new_extra = input(f"{Fore.CYAN}Has documents? (Y/N):{Style.RESET_ALL} ").strip().upper()
                                    if new_extra in ['Y', 'N']:
                                        break
                                    print(f"{Fore.RED}Please enter Y or N.{Style.RESET_ALL}")
                                
                                # Edit notes
                                new_notes = input(f"{Fore.CYAN}Enter notes (or press Enter to keep current):{Style.RESET_ALL} ").strip()
                                if not new_notes:
                                    new_notes = notes
                                
                                # Update database
                                cursor.execute("""
                                    INSERT INTO public.extracarinfo (idkey, carreg, sparekeys, extra, carnotes)
                                    VALUES (%s, %s, %s, %s, %s)
                                    ON CONFLICT (idkey) 
                                    DO UPDATE SET 
                                        sparekeys = EXCLUDED.sparekeys,
                                        extra = EXCLUDED.extra,
                                        carnotes = EXCLUDED.carnotes,
                                        updated_at = CURRENT_TIMESTAMP
                                """, (key, reg, new_sparekeys, new_extra, new_notes))
                                
                                conn.commit()
                                
                                # Update local data
                                vehicles[vehicle_idx] = (key, reg, model, new_sparekeys, new_extra, new_notes)
                                print(f"{Fore.GREEN}Vehicle information updated successfully!{Style.RESET_ALL}")
                                
                            except ValueError:
                                print(f"{Fore.RED}Invalid input.{Style.RESET_ALL}")
                        
                        elif choice == '2':
                            break
                        else:
                            print(f"{Fore.RED}Invalid choice.{Style.RESET_ALL}")
                    
                except ValueError:
                    print(f"{Fore.RED}Invalid input.{Style.RESET_ALL}")
                    
            except ValueError:
                print(f"{Fore.RED}Invalid input.{Style.RESET_ALL}")
                
        except Exception as e:
            logging.error(f"Error editing car info: {e}")
            print(f"{Fore.RED}Error editing car info: {e}{Style.RESET_ALL}")
        finally:
            if 'cursor' in locals():
                cursor.close()
            if 'conn' in locals():
                conn.close()

    def print_menu(self):
        """Print the menu with fancy formatting."""
        menu_border = f"{Fore.BLUE}{'═' * 60}{Style.RESET_ALL}"
        menu_title = f"{Fore.CYAN}{'▌' * 5} Timesheet Manager {'▌' * 5}{Style.RESET_ALL}"
        
        print("\n" + menu_border)
        print(menu_title)
        print(menu_border)
        print(f"{Fore.YELLOW}┌──────────────────────────────────────┐{Style.RESET_ALL}")
        print(f"{Fore.YELLOW}│{Style.RESET_ALL} {Fore.WHITE}1.{Style.RESET_ALL} {Fore.CYAN}Add Work Day                      {Fore.YELLOW}│{Style.RESET_ALL}")
        print(f"{Fore.YELLOW}│{Style.RESET_ALL} {Fore.WHITE}2.{Style.RESET_ALL} {Fore.CYAN}Edit Work Day                    {Fore.YELLOW}│{Style.RESET_ALL}")
        print(f"{Fore.YELLOW}│{Style.RESET_ALL} {Fore.WHITE}3.{Style.RESET_ALL} {Fore.CYAN}Delete Work Day                  {Fore.YELLOW}│{Style.RESET_ALL}")
        print(f"{Fore.YELLOW}│{Style.RESET_ALL} {Fore.WHITE}4.{Style.RESET_ALL} {Fore.CYAN}Show Weekly Hours                {Fore.YELLOW}│{Style.RESET_ALL}")
        print(f"{Fore.YELLOW}│{Style.RESET_ALL} {Fore.WHITE}5.{Style.RESET_ALL} {Fore.CYAN}Show Load Details                {Fore.YELLOW}│{Style.RESET_ALL}")
        print(f"{Fore.YELLOW}│{Style.RESET_ALL} {Fore.WHITE}6.{Style.RESET_ALL} {Fore.CYAN}Add Missing Cars                 {Fore.YELLOW}│{Style.RESET_ALL}")
        print(f"{Fore.YELLOW}│{Style.RESET_ALL} {Fore.WHITE}7.{Style.RESET_ALL} {Fore.CYAN}Edit Car Information             {Fore.YELLOW}│{Style.RESET_ALL}")
        print(f"{Fore.YELLOW}│{Style.RESET_ALL} {Fore.WHITE}8.{Style.RESET_ALL} {Fore.CYAN}Exit                           {Fore.YELLOW}│{Style.RESET_ALL}")
        print(f"{Fore.YELLOW}└──────────────────────────────────────┘{Style.RESET_ALL}")
        
        print(f"{Fore.CYAN}Enter your choice (1-8):{Style.RESET_ALL} ", end="")

    def run(self):
        """Run the main application loop."""
        print(f"{Fore.BLUE}{'═' * 60}{Style.RESET_ALL}")
        print(f"{Fore.CYAN}   Timesheet Manager{Style.RESET_ALL}")
        print(f"{Fore.BLUE}{'═' * 60}{Style.RESET_ALL}")
        
        while True:
            self.print_menu()
            choice = input()
            
            if choice == '1':
                self.add_work_day()
            elif choice == '2':
                self.edit_work_day()
            elif choice == '3':
                self.delete_work_day()
            elif choice == '4':
                self.show_weekly_hours()
            elif choice == '5':
                self.show_load_details()
            elif choice == '6':
                self.add_missing_cars()
            elif choice == '7':
                self.edit_car_info()
            elif choice == '8':
                print(f"{Fore.GREEN}Exiting...{Style.RESET_ALL}")
                break
            else:
                print(f"{Fore.RED}Invalid choice. Please try again.{Style.RESET_ALL}")

    def load_schema(self):
        """Load schema data from schema.json file."""
        try:
            schema_path = os.path.join(SCRIPT_DIR, "schema", "schema.json")
            if not os.path.exists(schema_path):
                logging.error(f"Schema file not found at {schema_path}")
                return {}
                
            with open(schema_path, 'r') as f:
                return json.loads(f.read())
        except Exception as e:
            logging.error(f"Error loading schema: {e}")
            return {}

if __name__ == "__main__":
    manager = TimesheetManager()
    try:
        manager.run()
    except KeyboardInterrupt:
        print(f"\n{Fore.YELLOW}Operation interrupted. Exiting...{Style.RESET_ALL}")
    except Exception as e:
        print(f"{Fore.RED}An unexpected error occurred: {e}{Style.RESET_ALL}")
    finally:
        print(f"{Fore.GREEN}Program terminated.{Style.RESET_ALL}") 
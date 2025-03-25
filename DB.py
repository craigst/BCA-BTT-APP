#!/usr/bin/env python3
import os
import sqlite3
import sys
from datetime import datetime, timedelta
import colorama
from colorama import Fore, Back, Style
import json
import logging
from pathlib import Path
import configparser
import psycopg2
from psycopg2.extras import execute_values
import requests
import time

# Initialize colorama for cross-platform terminal colors
colorama.init(autoreset=True)

# Setup logging
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_DIR = os.path.join(SCRIPT_DIR, "logs")
SCHEMA_DIR = os.path.join(SCRIPT_DIR, "schema")
SQL_DIR = os.path.join(SCRIPT_DIR, "SQL")

# Ensure directories exist
os.makedirs(LOG_DIR, exist_ok=True)
os.makedirs(SCHEMA_DIR, exist_ok=True)
os.makedirs(SQL_DIR, exist_ok=True)

# Setup logging configuration
LOG_FILE = os.path.join(LOG_DIR, f"db_editor_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log")
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler(sys.stdout)
    ]
)

# Set the StreamHandler to only show WARNING and above
for handler in logging.getLogger().handlers:
    if isinstance(handler, logging.StreamHandler):
        handler.setLevel(logging.WARNING)

class SQLiteEditor:
    """
    A terminal-based SQLite database editor for handling Y/N/mixed data
    with change tracking functionality and schema mapping.
    """
    
    def __init__(self):
        """Initialize the SQLite editor with default settings."""
        self.db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'db', 'sql.db')
        self.connection = None
        self.cursor = None
        self.table_name = None
        self.column_name = None
        self.primary_key_column = None
        self.changes_made = {}
        self.seen_records = set()
        self.schema_file = os.path.join(SCHEMA_DIR, "schema.json")
        self.schema_data = self.load_schema()
        self.pg_config = self.load_pg_config()
        # Load display settings from schema
        self.job_display_columns = self.schema_data.get("display_settings", {}).get("job_columns", {
            "dwjSeq": True,
            "dwjType": True,
            "dwjCust": True,
            "dwjName": True,
            "dwjStatus": True,
            "dwjDate": True
        })
        self.vehicle_display_columns = self.schema_data.get("display_settings", {}).get("vehicle_columns", {
            "dwvKey": True,
            "dwvDriver": True,
            "dwvVehRef": True,
            "dwvModDes": True,
            "dwvStatus": True
        })
        
    def load_schema(self):
        """Load the schema data from JSON file."""
        try:
            if os.path.exists(self.schema_file):
                with open(self.schema_file, 'r') as f:
                    return json.load(f)
            return {"tables": {}, "columns": {}, "display_settings": {}}
        except Exception as e:
            logging.error(f"Error loading schema: {e}")
            return {"tables": {}, "columns": {}, "display_settings": {}}
    
    def save_schema(self):
        """Save the schema data to JSON file."""
        try:
            with open(self.schema_file, 'w') as f:
                json.dump(self.schema_data, f, indent=4)
            logging.info("Schema saved successfully")
        except Exception as e:
            logging.error(f"Error saving schema: {e}")
    
    def add_table_description(self):
        """Add or update description for the current table."""
        if not self.table_name:
            print(f"{Fore.RED}No table selected.{Style.RESET_ALL}")
            return
        
        print(f"\n{Fore.CYAN}Current description for table '{self.table_name}':{Style.RESET_ALL}")
        current_desc = self.schema_data.get("tables", {}).get(self.table_name, {}).get("description", "No description")
        print(f"{Fore.YELLOW}{current_desc}{Style.RESET_ALL}")
        
        print(f"\n{Fore.CYAN}Enter new description (or press Enter to keep current):{Style.RESET_ALL}")
        new_desc = input().strip()
        
        if new_desc:
            if "tables" not in self.schema_data:
                self.schema_data["tables"] = {}
            self.schema_data["tables"][self.table_name] = {
                "description": new_desc,
                "last_updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }
            self.save_schema()
            logging.info(f"Updated description for table '{self.table_name}'")
            print(f"{Fore.GREEN}Description updated successfully.{Style.RESET_ALL}")
    
    def add_column_description(self):
        """Add or update description for the current column."""
        if not self.table_name or not self.column_name:
            print(f"{Fore.RED}No table or column selected.{Style.RESET_ALL}")
            return
        
        column_key = f"{self.table_name}.{self.column_name}"
        print(f"\n{Fore.CYAN}Current description for column '{self.column_name}':{Style.RESET_ALL}")
        current_desc = self.schema_data.get("columns", {}).get(column_key, {}).get("description", "No description")
        print(f"{Fore.YELLOW}{current_desc}{Style.RESET_ALL}")
        
        print(f"\n{Fore.CYAN}Enter new description (or press Enter to keep current):{Style.RESET_ALL}")
        new_desc = input().strip()
        
        if new_desc:
            if "columns" not in self.schema_data:
                self.schema_data["columns"] = {}
            self.schema_data["columns"][column_key] = {
                "description": new_desc,
                "last_updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }
            self.save_schema()
            logging.info(f"Updated description for column '{column_key}'")
            print(f"{Fore.GREEN}Description updated successfully.{Style.RESET_ALL}")
    
    def show_schema_info(self):
        """Display schema information for current table and column."""
        if not self.table_name:
            print(f"{Fore.RED}No table selected.{Style.RESET_ALL}")
            return
        
        print(f"\n{Fore.CYAN}Schema Information:{Style.RESET_ALL}")
        print(f"{Fore.WHITE}Table: {Fore.GREEN}{self.table_name}{Style.RESET_ALL}")
        
        # Show table description
        table_desc = self.schema_data.get("tables", {}).get(self.table_name, {}).get("description", "No description")
        print(f"{Fore.WHITE}Table Description: {Fore.YELLOW}{table_desc}{Style.RESET_ALL}")
        
        # Show columns
        print(f"\n{Fore.WHITE}Columns:{Style.RESET_ALL}")
        try:
            self.cursor.execute(f"PRAGMA table_info({self.table_name})")
            columns = self.cursor.fetchall()
            
            for col in columns:
                col_name = col[1]
                col_type = col[2]
                # Check specifically for dwjkey
                is_pk = " (dwjkey)" if col_name.lower() == "dwjkey" else ""
                column_key = f"{self.table_name}.{col_name}"
                col_desc = self.schema_data.get("columns", {}).get(column_key, {}).get("description", "No description")
                
                print(f"\n{Fore.WHITE}Column: {Fore.GREEN}{col_name}{Style.RESET_ALL}")
                print(f"{Fore.WHITE}Type: {Fore.BLUE}{col_type}{Style.RESET_ALL}")
                print(f"{Fore.WHITE}Description: {Fore.YELLOW}{col_desc}{Style.RESET_ALL}")
                if is_pk:
                    print(f"{Fore.GREEN}{is_pk}{Style.RESET_ALL}")
        except sqlite3.Error as e:
            logging.error(f"Error showing schema info: {e}")
            print(f"{Fore.RED}Error displaying schema information: {e}{Style.RESET_ALL}")
    
    def check_db_exists(self):
        """Check if the database file exists at the expected location."""
        if not os.path.exists(self.db_path):
            print(f"{Fore.RED}ERROR: Database file not found at {self.db_path}{Style.RESET_ALL}")
            # Create db directory if it doesn't exist
            os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
            print(f"{Fore.GREEN}Created directory: {os.path.dirname(self.db_path)}{Style.RESET_ALL}")
            print(f"{Fore.YELLOW}Would you like to create a new database? (y/n){Style.RESET_ALL}")
            choice = input().lower()
            if choice == 'y':
                self.create_new_db()
                return True
            else:
                return False
        print(f"{Fore.GREEN}Database found at {self.db_path}{Style.RESET_ALL}")
        return True
    
    def create_new_db(self):
        """Create a new SQLite database with a simple Y/N table."""
        try:
            self.connect_db()
            print(f"{Fore.CYAN}Enter a name for your table:{Style.RESET_ALL}")
            self.table_name = input().strip()
            print(f"{Fore.CYAN}Enter a name for your Y/N column:{Style.RESET_ALL}")
            self.column_name = input().strip()
            
            # Create table with id, the Y/N column, and a timestamp
            self.cursor.execute(f'''
                CREATE TABLE {self.table_name} (
                    id INTEGER PRIMARY KEY,
                    {self.column_name} TEXT CHECK({self.column_name} IN ('Y', 'N', 'mixed')),
                    last_modified TIMESTAMP
                )
            ''')
            self.connection.commit()
            self.primary_key_column = "id"  # Set the primary key column name
            print(f"{Fore.GREEN}Created new table '{self.table_name}' with column '{self.column_name}'{Style.RESET_ALL}")
            return True
        except sqlite3.Error as e:
            print(f"{Fore.RED}Error creating database: {e}{Style.RESET_ALL}")
            return False
    
    def connect_db(self):
        """Establish connection to the SQLite database."""
        try:
            self.connection = sqlite3.connect(self.db_path)
            self.cursor = self.connection.cursor()
            print(f"{Fore.GREEN}Connected to database successfully.{Style.RESET_ALL}")
            return True
        except sqlite3.Error as e:
            print(f"{Fore.RED}Error connecting to database: {e}{Style.RESET_ALL}")
            return False
    
    def close_db(self):
        """Close the database connection properly."""
        if self.connection:
            self.connection.close()
            print(f"{Fore.YELLOW}Database connection closed.{Style.RESET_ALL}")
    
    def list_tables(self):
        """List all tables in the database."""
        try:
            self.cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
            tables = self.cursor.fetchall()
            
            if not tables:
                print(f"{Fore.YELLOW}No tables found in the database.{Style.RESET_ALL}")
                return
            
            print(f"\n{Fore.CYAN}Available tables:{Style.RESET_ALL}")
            for i, table in enumerate(tables, 1):
                print(f"{Fore.WHITE}{i}. {Fore.YELLOW}{table[0]}{Style.RESET_ALL}")
            
            print(f"\n{Fore.CYAN}Select a table number:{Style.RESET_ALL}")
            choice = int(input())
            if 1 <= choice <= len(tables):
                self.table_name = tables[choice-1][0]
                print(f"{Fore.GREEN}Selected table: {self.table_name}{Style.RESET_ALL}")
                self.identify_primary_key()
                self.list_columns()
            else:
                print(f"{Fore.RED}Invalid selection.{Style.RESET_ALL}")
        except sqlite3.Error as e:
            print(f"{Fore.RED}Error listing tables: {e}{Style.RESET_ALL}")
        except ValueError:
            print(f"{Fore.RED}Please enter a valid number.{Style.RESET_ALL}")
    
    def identify_primary_key(self):
        """Identify the primary key column of the selected table."""
        try:
            # Query the table info to find the primary key
            self.cursor.execute(f"PRAGMA table_info({self.table_name})")
            columns = self.cursor.fetchall()
            
            # Look for the primary key column (pk = 1)
            primary_key = None
            for col in columns:
                if col[5] == 1:  # The 6th element (index 5) indicates if the column is primary key
                    primary_key = col[1]  # Column name is the 2nd element (index 1)
                    break
            
            if primary_key:
                self.primary_key_column = primary_key
                print(f"{Fore.GREEN}Primary key column identified: {self.primary_key_column}{Style.RESET_ALL}")
            else:
                # If no primary key found, use the first column as a fallback
                self.primary_key_column = columns[0][1] if columns else None
                print(f"{Fore.YELLOW}No primary key found. Using first column: {self.primary_key_column}{Style.RESET_ALL}")
            
            return True
        except sqlite3.Error as e:
            print(f"{Fore.RED}Error identifying primary key: {e}{Style.RESET_ALL}")
            return False
    
    def list_columns(self):
        """List all columns in the selected table."""
        try:
            self.cursor.execute(f"PRAGMA table_info({self.table_name})")
            columns = self.cursor.fetchall()
            
            print(f"\n{Fore.CYAN}Columns in table '{self.table_name}':{Style.RESET_ALL}")
            for i, col in enumerate(columns, 1):
                col_name = col[1]
                col_type = col[2]
                is_pk = " (Primary Key)" if col[5] == 1 else ""
                print(f"{Fore.WHITE}{i}. {Fore.YELLOW}{col_name} {Fore.BLUE}({col_type}){Fore.GREEN}{is_pk}{Style.RESET_ALL}")
            
            print(f"\n{Fore.CYAN}Select a Y/N/mixed column number:{Style.RESET_ALL}")
            choice = int(input())
            if 1 <= choice <= len(columns):
                self.column_name = columns[choice-1][1]
                print(f"{Fore.GREEN}Selected column: {self.column_name}{Style.RESET_ALL}")
            else:
                print(f"{Fore.RED}Invalid selection.{Style.RESET_ALL}")
        except sqlite3.Error as e:
            print(f"{Fore.RED}Error listing columns: {e}{Style.RESET_ALL}")
        except ValueError:
            print(f"{Fore.RED}Please enter a valid number.{Style.RESET_ALL}")
    
    def display_data(self):
        """Display the current data in the selected table and column."""
        if not self.table_name or not self.column_name:
            print(f"{Fore.RED}Please select a table and column first.{Style.RESET_ALL}")
            return
        
        if not self.primary_key_column:
            print(f"{Fore.RED}No primary key column identified.{Style.RESET_ALL}")
            self.identify_primary_key()
            if not self.primary_key_column:
                return
        
        try:
            # Check if the last_modified column exists
            self.cursor.execute(f"PRAGMA table_info({self.table_name})")
            columns = self.cursor.fetchall()
            column_names = [col[1] for col in columns]
            
            # Build a query based on available columns
            query = f"SELECT {self.primary_key_column}, {self.column_name}"
            
            if "last_modified" in column_names:
                query += ", last_modified"
            
            query += f" FROM {self.table_name}"
            
            self.cursor.execute(query)
            rows = self.cursor.fetchall()
            
            if not rows:
                print(f"{Fore.YELLOW}No data found in table '{self.table_name}'.{Style.RESET_ALL}")
                return
            
            print(f"\n{Fore.CYAN}Current data in {self.table_name}.{self.column_name}:{Style.RESET_ALL}")
            
            # Determine column widths for formatting
            id_width = max(5, len(self.primary_key_column))
            col_width = max(6, len(self.column_name))
            date_width = 20 if "last_modified" in column_names else 0
            
            # Print header
            header = f"{Fore.WHITE}{self.primary_key_column:<{id_width}} | {self.column_name:<{col_width}}"
            if "last_modified" in column_names:
                header += f" | {'Last Modified':<{date_width}}"
            print(header + Style.RESET_ALL)
            
            # Print separator line
            separator = "-" * (id_width + col_width + (date_width + 5 if date_width else 0))
            print(separator)
            
            # Print rows
            for row in rows:
                row_id = row[0]
                value = row[1]
                
                # Add color based on value
                value_color = Fore.GREEN if value == 'Y' else Fore.RED if value == 'N' else Fore.YELLOW
                row_str = f"{row_id:<{id_width}} | {value_color}{value:<{col_width}}{Style.RESET_ALL}"
                
                if len(row) > 2 and date_width:
                    timestamp = row[2]
                    row_str += f" | {timestamp:<{date_width}}"
                
                print(row_str)
                
                # Add to seen records
                self.seen_records.add(row_id)
                
            print(f"\n{Fore.CYAN}Total records: {len(rows)}{Style.RESET_ALL}")
        except sqlite3.Error as e:
            print(f"{Fore.RED}Error displaying data: {e}{Style.RESET_ALL}")
    
    def edit_record(self):
        """Edit a specific record in the database."""
        if not self.table_name or not self.column_name:
            print(f"{Fore.RED}Please select a table and column first.{Style.RESET_ALL}")
            return
        
        if not self.primary_key_column:
            print(f"{Fore.RED}No primary key column identified.{Style.RESET_ALL}")
            self.identify_primary_key()
            if not self.primary_key_column:
                return
        
        try:
            print(f"\n{Fore.CYAN}Enter the {self.primary_key_column} of the record to edit:{Style.RESET_ALL}")
            row_id = input().strip()
            
            # Check if record exists
            self.cursor.execute(f"SELECT {self.column_name} FROM {self.table_name} WHERE {self.primary_key_column} = ?", (row_id,))
            result = self.cursor.fetchone()
            
            if not result:
                print(f"{Fore.RED}No record found with {self.primary_key_column} {row_id}{Style.RESET_ALL}")
                return
            
            current_value = result[0]
            value_color = Fore.GREEN if current_value == 'Y' else Fore.RED if current_value == 'N' else Fore.YELLOW
            print(f"{Fore.CYAN}Current value: {value_color}{current_value}{Style.RESET_ALL}")
            print(f"{Fore.CYAN}Enter new value (Y/N/mixed):{Style.RESET_ALL}")
            new_value = input().strip().upper()
            
            if new_value not in ['Y', 'N', 'MIXED']:
                print(f"{Fore.RED}Invalid value. Must be 'Y', 'N', or 'mixed'{Style.RESET_ALL}")
                return
            
            # Normalize 'MIXED' to 'mixed' to match database constraint
            if new_value == 'MIXED':
                new_value = 'mixed'
            
            # Only allow changing if we haven't seen this record before
            # or if the change is different from any previous change
            if row_id not in self.seen_records or current_value != new_value:
                # Check if last_modified column exists
                self.cursor.execute(f"PRAGMA table_info({self.table_name})")
                columns = self.cursor.fetchall()
                has_timestamp = any(col[1] == "last_modified" for col in columns)
                
                if has_timestamp:
                    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                    self.cursor.execute(
                        f"UPDATE {self.table_name} SET {self.column_name} = ?, last_modified = ? WHERE {self.primary_key_column} = ?",
                        (new_value, timestamp, row_id)
                    )
                else:
                    self.cursor.execute(
                        f"UPDATE {self.table_name} SET {self.column_name} = ? WHERE {self.primary_key_column} = ?",
                        (new_value, row_id)
                    )
                
                self.connection.commit()
                
                # Track this change
                self.changes_made[row_id] = [current_value, new_value]
                self.seen_records.add(row_id)
                
                new_value_color = Fore.GREEN if new_value == 'Y' else Fore.RED if new_value == 'N' else Fore.YELLOW
                current_value_color = Fore.GREEN if current_value == 'Y' else Fore.RED if current_value == 'N' else Fore.YELLOW
                
                print(f"{Fore.GREEN}Updated record {row_id}: {current_value_color}{current_value} → {new_value_color}{new_value}{Style.RESET_ALL}")
            else:
                print(f"{Fore.YELLOW}No change needed for record {row_id} as it was previously modified.{Style.RESET_ALL}")
        except sqlite3.Error as e:
            print(f"{Fore.RED}Error editing record: {e}{Style.RESET_ALL}")
        except ValueError:
            print(f"{Fore.RED}Please enter a valid value.{Style.RESET_ALL}")
    
    def add_record(self):
        """Add a new record to the database."""
        if not self.table_name or not self.column_name:
            print(f"{Fore.RED}Please select a table and column first.{Style.RESET_ALL}")
            return
        
        try:
            print(f"{Fore.CYAN}Enter value for new record (Y/N/mixed):{Style.RESET_ALL}")
            value = input().strip().upper()
            
            if value not in ['Y', 'N', 'MIXED']:
                print(f"{Fore.RED}Invalid value. Must be 'Y', 'N', or 'mixed'{Style.RESET_ALL}")
                return
            
            # Normalize 'MIXED' to 'mixed' to match database constraint
            if value == 'MIXED':
                value = 'mixed'
            
            # Check if last_modified column exists
            self.cursor.execute(f"PRAGMA table_info({self.table_name})")
            columns = self.cursor.fetchall()
            has_timestamp = any(col[1] == "last_modified" for col in columns)
            
            if has_timestamp:
                timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                self.cursor.execute(
                    f"INSERT INTO {self.table_name} ({self.column_name}, last_modified) VALUES (?, ?)",
                    (value, timestamp)
                )
            else:
                self.cursor.execute(
                    f"INSERT INTO {self.table_name} ({self.column_name}) VALUES (?)",
                    (value,)
                )
            
            self.connection.commit()
            
            # Get the last inserted row id
            if self.primary_key_column.lower() == 'id' or self.primary_key_column.lower() == 'rowid':
                new_id = self.cursor.lastrowid
            else:
                # Try to get the most recently inserted record
                self.cursor.execute(f"SELECT {self.primary_key_column} FROM {self.table_name} ORDER BY rowid DESC LIMIT 1")
                result = self.cursor.fetchone()
                new_id = result[0] if result else "Unknown"
            
            value_color = Fore.GREEN if value == 'Y' else Fore.RED if value == 'N' else Fore.YELLOW
            print(f"{Fore.GREEN}Added new record with {self.primary_key_column} {new_id} and value {value_color}{value}{Style.RESET_ALL}")
        except sqlite3.Error as e:
            print(f"{Fore.RED}Error adding record: {e}{Style.RESET_ALL}")
    
    def show_changes(self):
        """Show changes made in loads or vehicles."""
        try:
            print(f"\n{Fore.CYAN}Select what to compare:{Style.RESET_ALL}")
            print(f"{Fore.YELLOW}1. Compare Loads{Style.RESET_ALL}")
            print(f"{Fore.YELLOW}2. Compare Vehicles in a Load{Style.RESET_ALL}")
            print(f"{Fore.YELLOW}3. Return to Main Menu{Style.RESET_ALL}")
            
            choice = input(f"{Fore.CYAN}Enter your choice (1-3):{Style.RESET_ALL} ").strip()
            
            if choice == "1":
                self.compare_loads()
            elif choice == "2":
                self.compare_vehicles()
            elif choice == "3":
                return
            else:
                print(f"{Fore.RED}Invalid choice.{Style.RESET_ALL}")
                
        except sqlite3.Error as e:
            logging.error(f"Error showing changes: {e}")
            print(f"{Fore.RED}Error showing changes: {e}{Style.RESET_ALL}")

    def compare_loads(self):
        """Compare two loads and show differences."""
        try:
            # Get all jobs with their keys and load numbers
            self.cursor.execute("""
                SELECT * FROM DWJJOB 
                ORDER BY dwjLoad, dwjType, dwjSeq
            """)
            jobs = self.cursor.fetchall()
            
            if not jobs:
                print(f"{Fore.YELLOW}No jobs found.{Style.RESET_ALL}")
                return
            
            # Get column names
            self.cursor.execute("PRAGMA table_info(DWJJOB)")
            columns = self.cursor.fetchall()
            column_names = [col[1] for col in columns]
            
            # Group jobs by load number
            load_groups = {}
            for job in jobs:
                load_num = job[column_names.index('dwjLoad')]
                if load_num not in load_groups:
                    load_groups[load_num] = []
                load_groups[load_num].append(job)
            
            # Show available loads with their job counts
            print(f"\n{Fore.CYAN}Available Loads:{Style.RESET_ALL}")
            for i, (load_num, load_jobs) in enumerate(load_groups.items(), 1):
                collections = len([j for j in load_jobs if j[column_names.index('dwjType')] == "C"])
                deliveries = len([j for j in load_jobs if j[column_names.index('dwjType')] == "D"])
                print(f"{Fore.WHITE}{i}. {Fore.GREEN}{load_num}{Style.RESET_ALL} ({collections} collections, {deliveries} deliveries)")
            
            print(f"\n{Fore.CYAN}Enter two load numbers to compare (comma-separated):{Style.RESET_ALL}")
            choice = input().strip()
            
            try:
                load1_idx, load2_idx = map(int, choice.split(','))
                if not (1 <= load1_idx <= len(load_groups) and 1 <= load2_idx <= len(load_groups)):
                    print(f"{Fore.RED}Invalid load numbers.{Style.RESET_ALL}")
                    return
                
                # Get the load numbers
                load1 = list(load_groups.keys())[load1_idx - 1]
                load2 = list(load_groups.keys())[load2_idx - 1]
                
                # Get jobs for both loads
                load1_jobs = load_groups[load1]
                load2_jobs = load_groups[load2]
                
                print(f"\n{Fore.CYAN}Comparing Loads {load1} and {load2}:{Style.RESET_ALL}")
                
                # Compare collections
                load1_collections = [j for j in load1_jobs if j[column_names.index('dwjType')] == "C"]
                load2_collections = [j for j in load2_jobs if j[column_names.index('dwjType')] == "C"]
                
                if load1_collections or load2_collections:
                    print(f"\n{Fore.YELLOW}Collections:{Style.RESET_ALL}")
                    print(f"{Fore.WHITE}{'Column':<20} | {'Load ' + load1:<30} | {'Load ' + load2:<30}{Style.RESET_ALL}")
                    print("-" * 85)
                    
                    # Compare collections
                    for i in range(max(len(load1_collections), len(load2_collections))):
                        job1 = load1_collections[i] if i < len(load1_collections) else None
                        job2 = load2_collections[i] if i < len(load2_collections) else None
                        
                        if job1 and job2:
                            # Compare all columns
                            for col_idx, col_name in enumerate(column_names):
                                val1 = str(job1[col_idx])
                                val2 = str(job2[col_idx])
                                if val1 != val2:
                                    col_desc = self.get_column_description("DWJJOB", col_name)
                                    print(f"{col_desc:<20} | {val1:<30} | {val2:<30}")
                        elif job1:
                            for col_idx, col_name in enumerate(column_names):
                                val1 = str(job1[col_idx])
                                col_desc = self.get_column_description("DWJJOB", col_name)
                                print(f"{col_desc:<20} | {val1:<30} | {'N/A':<30}")
                        elif job2:
                            for col_idx, col_name in enumerate(column_names):
                                val2 = str(job2[col_idx])
                                col_desc = self.get_column_description("DWJJOB", col_name)
                                print(f"{col_desc:<20} | {'N/A':<30} | {val2:<30}")
                
                # Compare deliveries
                load1_deliveries = [j for j in load1_jobs if j[column_names.index('dwjType')] == "D"]
                load2_deliveries = [j for j in load2_jobs if j[column_names.index('dwjType')] == "D"]
                
                if load1_deliveries or load2_deliveries:
                    print(f"\n{Fore.YELLOW}Deliveries:{Style.RESET_ALL}")
                    print(f"{Fore.WHITE}{'Column':<20} | {'Load ' + load1:<30} | {'Load ' + load2:<30}{Style.RESET_ALL}")
                    print("-" * 85)
                    
                    # Compare deliveries
                    for i in range(max(len(load1_deliveries), len(load2_deliveries))):
                        job1 = load1_deliveries[i] if i < len(load1_deliveries) else None
                        job2 = load2_deliveries[i] if i < len(load2_deliveries) else None
                        
                        if job1 and job2:
                            # Compare all columns
                            for col_idx, col_name in enumerate(column_names):
                                val1 = str(job1[col_idx])
                                val2 = str(job2[col_idx])
                                if val1 != val2:
                                    col_desc = self.get_column_description("DWJJOB", col_name)
                                    print(f"{col_desc:<20} | {val1:<30} | {val2:<30}")
                        elif job1:
                            for col_idx, col_name in enumerate(column_names):
                                val1 = str(job1[col_idx])
                                col_desc = self.get_column_description("DWJJOB", col_name)
                                print(f"{col_desc:<20} | {val1:<30} | {'N/A':<30}")
                        elif job2:
                            for col_idx, col_name in enumerate(column_names):
                                val2 = str(job2[col_idx])
                                col_desc = self.get_column_description("DWJJOB", col_name)
                                print(f"{col_desc:<20} | {'N/A':<30} | {val2:<30}")
                
            except ValueError:
                print(f"{Fore.RED}Invalid input. Please enter two numbers separated by a comma.{Style.RESET_ALL}")
                
        except sqlite3.Error as e:
            logging.error(f"Error comparing loads: {e}")
            print(f"{Fore.RED}Error comparing loads: {e}{Style.RESET_ALL}")

    def compare_vehicles(self):
        """Compare two vehicles in a load and show differences."""
        try:
            # First get the load number
            self.cursor.execute("SELECT DISTINCT dwvLoad FROM DWVVEH ORDER BY dwvLoad")
            loads = self.cursor.fetchall()
            
            if not loads:
                print(f"{Fore.YELLOW}No loads with vehicles found.{Style.RESET_ALL}")
                return
            
            print(f"\n{Fore.CYAN}Available Loads:{Style.RESET_ALL}")
            for i, load in enumerate(loads, 1):
                print(f"{Fore.WHITE}{i}. {Fore.GREEN}{load[0]}{Style.RESET_ALL}")
            
            print(f"\n{Fore.CYAN}Select a load number:{Style.RESET_ALL}")
            load_choice = input().strip()
            
            try:
                load_idx = int(load_choice)
                if not (1 <= load_idx <= len(loads)):
                    print(f"{Fore.RED}Invalid load number.{Style.RESET_ALL}")
                    return
                
                load_num = loads[load_idx - 1][0]
                
                # Get vehicles for this load with all columns
                self.cursor.execute("""
                    SELECT *
                    FROM DWVVEH 
                    WHERE dwvLoad = ?
                    ORDER BY dwvKey
                """, (load_num,))
                vehicles = self.cursor.fetchall()
                
                if not vehicles:
                    print(f"{Fore.YELLOW}No vehicles found in load {load_num}{Style.RESET_ALL}")
                    return
                
                # Get column names
                self.cursor.execute("PRAGMA table_info(DWVVEH)")
                columns = self.cursor.fetchall()
                column_names = [col[1] for col in columns]
                
                print(f"\n{Fore.CYAN}Vehicles in Load {load_num}:{Style.RESET_ALL}")
                for i, vehicle in enumerate(vehicles, 1):
                    # Format the display string with key, reference, and model
                    key = vehicle[column_names.index('dwvKey')]
                    ref = vehicle[column_names.index('dwvDelCus')]
                    model = vehicle[column_names.index('dwvModDes')]
                    print(f"{Fore.WHITE}{i}. {Fore.GREEN}{key} - {ref} ({model}){Style.RESET_ALL}")
                
                print(f"\n{Fore.CYAN}Enter two vehicle numbers to compare (comma-separated):{Style.RESET_ALL}")
                vehicle_choice = input().strip()
                
                try:
                    v1_idx, v2_idx = map(int, vehicle_choice.split(','))
                    if not (1 <= v1_idx <= len(vehicles) and 1 <= v2_idx <= len(vehicles)):
                        print(f"{Fore.RED}Invalid vehicle numbers.{Style.RESET_ALL}")
                        return
                    
                    vehicle1 = vehicles[v1_idx - 1]
                    vehicle2 = vehicles[v2_idx - 1]
                    
                    print(f"\n{Fore.CYAN}Comparing Vehicles {vehicle1[column_names.index('dwvKey')]} and {vehicle2[column_names.index('dwvKey')]}:{Style.RESET_ALL}")
                    print(f"{Fore.WHITE}{'Column':<20} | {'Vehicle ' + str(vehicle1[column_names.index('dwvKey')]):<30} | {'Vehicle ' + str(vehicle2[column_names.index('dwvKey')]):<30}{Style.RESET_ALL}")
                    print("-" * 85)
                    
                    # Compare each column
                    for col_idx, col_name in enumerate(column_names):
                        val1 = str(vehicle1[col_idx])
                        val2 = str(vehicle2[col_idx])
                        
                        # Only show if values are different
                        if val1 != val2:
                            col_desc = self.get_column_description("DWVVEH", col_name)
                            print(f"{col_desc:<20} | {val1:<30} | {val2:<30}")
                    
                except ValueError:
                    print(f"{Fore.RED}Invalid input. Please enter two numbers separated by a comma.{Style.RESET_ALL}")
                    
            except ValueError:
                print(f"{Fore.RED}Invalid load number.{Style.RESET_ALL}")
                
        except sqlite3.Error as e:
            logging.error(f"Error comparing vehicles: {e}")
            print(f"{Fore.RED}Error comparing vehicles: {e}{Style.RESET_ALL}")

    def show_loads(self):
        """Show unique load numbers from DWJJOB table."""
        try:
            # Get unique load numbers
            self.cursor.execute("SELECT DISTINCT dwjLoad FROM DWJJOB ORDER BY dwjLoad")
            loads = self.cursor.fetchall()
            
            if not loads:
                print(f"{Fore.YELLOW}No loads found in DWJJOB table.{Style.RESET_ALL}")
                return
            
            print(f"\n{Fore.CYAN}Available Loads:{Style.RESET_ALL}")
            for i, load in enumerate(loads, 1):
                print(f"{Fore.WHITE}{i}. {Fore.GREEN}{load[0]}{Style.RESET_ALL}")
            
            print(f"\n{Fore.CYAN}Select a load number (or press Enter to return):{Style.RESET_ALL}")
            choice = input().strip()
            
            if choice:
                try:
                    load_num = loads[int(choice) - 1][0]
                    self.show_load_details(load_num)
                except (ValueError, IndexError):
                    print(f"{Fore.RED}Invalid selection.{Style.RESET_ALL}")
        except sqlite3.Error as e:
            logging.error(f"Error showing loads: {e}")
            print(f"{Fore.RED}Error retrieving loads: {e}{Style.RESET_ALL}")
    
    def get_column_description(self, table_name, column_name):
        """Get the description for a column from the schema."""
        column_key = f"{table_name}.{column_name}"
        return self.schema_data.get("columns", {}).get(column_key, {}).get("description", column_name)

    def configure_display_columns(self, table_name):
        """Configure which columns to display for a table."""
        try:
            self.cursor.execute(f"PRAGMA table_info({table_name})")
            columns = self.cursor.fetchall()
            
            print(f"\n{Fore.CYAN}Configure Display Columns for {table_name}:{Style.RESET_ALL}")
            print(f"{Fore.YELLOW}Enter numbers to toggle columns (comma-separated), or press Enter to keep current:{Style.RESET_ALL}")
            
            # Show current selection
            display_cols = self.job_display_columns if table_name == "DWJJOB" else self.vehicle_display_columns
            for i, col in enumerate(columns, 1):
                col_name = col[1]
                desc = self.get_column_description(table_name, col_name)
                checked = "✓" if display_cols.get(col_name, False) else " "
                print(f"{Fore.WHITE}{i}. [{checked}] {desc} ({col_name}){Style.RESET_ALL}")
            
            choice = input().strip()
            if choice:
                try:
                    # Toggle selected columns
                    indices = [int(x.strip()) - 1 for x in choice.split(",")]
                    for idx in indices:
                        if 0 <= idx < len(columns):
                            col_name = columns[idx][1]
                            display_cols[col_name] = not display_cols.get(col_name, False)
                    
                    print(f"{Fore.GREEN}Display settings updated.{Style.RESET_ALL}")
                except (ValueError, IndexError):
                    print(f"{Fore.RED}Invalid selection. Settings unchanged.{Style.RESET_ALL}")
            
        except sqlite3.Error as e:
            logging.error(f"Error configuring display columns: {e}")
            print(f"{Fore.RED}Error configuring display columns: {e}{Style.RESET_ALL}")

    def edit_load(self, load_num):
        """Edit a specific load's details."""
        try:
            print(f"\n{Fore.CYAN}Edit Load: {Fore.GREEN}{load_num}{Style.RESET_ALL}")
            print(f"{Fore.YELLOW}1. Edit Job Details{Style.RESET_ALL}")
            print(f"{Fore.YELLOW}2. Edit Vehicle Details{Style.RESET_ALL}")
            print(f"{Fore.YELLOW}3. Return to Load View{Style.RESET_ALL}")
            
            choice = input(f"{Fore.CYAN}Enter your choice (1-3):{Style.RESET_ALL} ").strip()
            
            if choice == "1":
                self.edit_job_details(load_num)
            elif choice == "2":
                self.edit_vehicle_details(load_num)
            elif choice == "3":
                return
            else:
                print(f"{Fore.RED}Invalid choice.{Style.RESET_ALL}")
                
        except sqlite3.Error as e:
            logging.error(f"Error editing load: {e}")
            print(f"{Fore.RED}Error editing load: {e}{Style.RESET_ALL}")

    def edit_job_details(self, load_num):
        """Edit details for a specific job."""
        try:
            # Get all jobs for this load
            self.cursor.execute("""
                SELECT dwjkey, dwjSeq, dwjType, dwjCust, dwjName, dwjStatus
                FROM DWJJOB 
                WHERE dwjLoad = ? 
                ORDER BY dwjSeq
            """, (load_num,))
            jobs = self.cursor.fetchall()
            
            if not jobs:
                print(f"{Fore.YELLOW}No jobs found for load {load_num}{Style.RESET_ALL}")
                return
            
            print(f"\n{Fore.CYAN}Select a job to edit:{Style.RESET_ALL}")
            for job in jobs:
                print(f"{Fore.WHITE}Seq: {job[1]} | Type: {job[2]} | Customer: {job[3]} | Name: {job[4]} | Status: {job[5]}{Style.RESET_ALL}")
            
            seq = input(f"{Fore.CYAN}Enter sequence number to edit (or press Enter to return):{Style.RESET_ALL} ").strip()
            if not seq:
                return
                
            try:
                seq = int(seq)
                job = next((j for j in jobs if j[1] == seq), None)
                
                if job:
                    self.edit_job_record(job[0])
                else:
                    print(f"{Fore.RED}Job with sequence {seq} not found.{Style.RESET_ALL}")
            except ValueError:
                print(f"{Fore.RED}Invalid sequence number.{Style.RESET_ALL}")
                
        except sqlite3.Error as e:
            logging.error(f"Error editing job details: {e}")
            print(f"{Fore.RED}Error editing job details: {e}{Style.RESET_ALL}")

    def edit_vehicle_details(self, load_num):
        """Edit details for vehicles in a load."""
        try:
            # Get all vehicles for this load
            self.cursor.execute("""
                SELECT dwvKey, dwvDriver, dwvVehRef, dwvModDes, dwvStatus
                FROM DWVVEH 
                WHERE dwvLoad = ?
            """, (load_num,))
            vehicles = self.cursor.fetchall()
            
            if not vehicles:
                print(f"{Fore.YELLOW}No vehicles found for load {load_num}{Style.RESET_ALL}")
                return
            
            print(f"\n{Fore.CYAN}Select a vehicle to edit:{Style.RESET_ALL}")
            for vehicle in vehicles:
                print(f"{Fore.WHITE}Key: {vehicle[0]} | Driver: {vehicle[1]} | Ref: {vehicle[2]} | Model: {vehicle[3]} | Status: {vehicle[4]}{Style.RESET_ALL}")
            
            key = input(f"{Fore.CYAN}Enter vehicle key to edit (or press Enter to return):{Style.RESET_ALL} ").strip()
            if not key:
                return
                
            vehicle = next((v for v in vehicles if v[0] == key), None)
            if vehicle:
                self.edit_vehicle_record(key)
            else:
                print(f"{Fore.RED}Vehicle with key {key} not found.{Style.RESET_ALL}")
                
        except sqlite3.Error as e:
            logging.error(f"Error editing vehicle details: {e}")
            print(f"{Fore.RED}Error editing vehicle details: {e}{Style.RESET_ALL}")

    def show_load_details(self, load_num):
        """Show detailed information about a specific load."""
        try:
            # Debug logging for PostgreSQL config
            if not self.pg_config:
                print(f"{Fore.RED}PostgreSQL configuration not found. Please check sql.ini file.{Style.RESET_ALL}")
                logging.error("PostgreSQL configuration is missing")
            else:
                logging.info(f"PostgreSQL config loaded: {self.pg_config.get('host', 'unknown')}:{self.pg_config.get('port', 'unknown')}")
            
            # Get load details
            self.cursor.execute("""
                SELECT dwvload, dwvvehref, dwvmoddes, dwvcolcod, dwvdelcod, dwvexpdat
                FROM dwvveh
                WHERE dwvload = ?
                ORDER BY dwvvehref
            """, (load_num,))
            
            vehicles = self.cursor.fetchall()
            
            if not vehicles:
                print(f"{Fore.YELLOW}No vehicles found for load {load_num}{Style.RESET_ALL}")
                return
            
            # Get collection and delivery locations
            self.cursor.execute("""
                SELECT dwjtype, dwjcust, dwjname, dwjdate, dwjadrcod
                FROM dwjjob
                WHERE dwjload = ?
                ORDER BY dwjtype, dwjdate
            """, (load_num,))
            
            jobs = self.cursor.fetchall()
            
            # Separate collections and deliveries
            collections = [j for j in jobs if j[0] == 'C']
            deliveries = [j for j in jobs if j[0] == 'D']
            
            # Print load header
            print(f"\n{Fore.CYAN}Load {load_num} Details:{Style.RESET_ALL}")
            
            # Print collections
            if collections:
                print(f"\n{Fore.YELLOW}Collections:{Style.RESET_ALL}")
                print(f"{Fore.WHITE}{'Job Type':<10} | {'Customer Code':<15} | {'Customer Name':<30} | {'Job Date':<10}{Style.RESET_ALL}")
                print("-" * 70)
                
                for collection in collections:
                    job_date = self.format_date(str(collection[3]))
                    print(f"{Fore.WHITE}{collection[0]:<10} | {collection[1]:<15} | {collection[2]:<30} | {job_date:<10}{Style.RESET_ALL}")
                    
                    # Show vehicles for this collection
                    collection_vehicles = [v for v in vehicles if v[3] == collection[4]]
                    if collection_vehicles:
                        print(f"{Fore.CYAN}  Vehicles:{Style.RESET_ALL}")
                        for vehicle in collection_vehicles:
                            print(f"    {Fore.WHITE}{vehicle[1]} - {vehicle[2]}{Style.RESET_ALL}")
            
            # Print deliveries
            if deliveries:
                print(f"\n{Fore.YELLOW}Deliveries:{Style.RESET_ALL}")
                print(f"{Fore.WHITE}{'Job Type':<10} | {'Customer Code':<15} | {'Customer Name':<30} | {'Job Date':<10}{Style.RESET_ALL}")
                print("-" * 70)
                
                for delivery in deliveries:
                    job_date = self.format_date(str(delivery[3]))
                    print(f"{Fore.WHITE}{delivery[0]:<10} | {delivery[1]:<15} | {delivery[2]:<30} | {job_date:<10}{Style.RESET_ALL}")
                    
                    # Show vehicles for this delivery
                    delivery_vehicles = [v for v in vehicles if v[4] == delivery[4]]
                    if delivery_vehicles:
                        print(f"{Fore.CYAN}  Vehicles:{Style.RESET_ALL}")
                        for vehicle in delivery_vehicles:
                            print(f"    {Fore.WHITE}{vehicle[1]} - {vehicle[2]}{Style.RESET_ALL}")
            
            # Print all vehicles summary with extra info
            print(f"\n{Fore.YELLOW}All Vehicles:{Style.RESET_ALL}")
            print(f"{Fore.WHITE}{'Vehicle Ref':<15} | {'Model':<30} | {'Spare Keys':<10} | {'Extra':<5} | {'Notes'}{Style.RESET_ALL}")
            print("-" * 85)
            
            # Get extra car info from PostgreSQL if available
            if self.pg_config:
                try:
                    logging.info("Attempting to connect to PostgreSQL...")
                    pg_conn = psycopg2.connect(**self.pg_config)
                    pg_cursor = pg_conn.cursor()
                    logging.info("Successfully connected to PostgreSQL")
                    
                    for vehicle in vehicles:
                        # Get extra car info
                        try:
                            logging.info(f"Checking extracarinfo for vehicle {vehicle[1]}")
                            pg_cursor.execute("""
                                SELECT sparekeys, extra, carnotes
                                FROM extracarinfo
                                WHERE idkey = %s
                            """, (vehicle[0],))  # Use dwvkey (vehicle[0]) instead of vehicle[1]
                            
                            extra_info = pg_cursor.fetchone()
                            
                            if extra_info is None:
                                logging.info(f"No entry found for {vehicle[0]}, creating new entry...")
                                # Create new entry in extracarinfo using dwvkey as idkey
                                pg_cursor.execute("""
                                    INSERT INTO extracarinfo (idkey, carreg, sparekeys, extra, carnotes, photos)
                                    VALUES (%s, %s, 'Y', 'Y', '', '{}')
                                """, (vehicle[0], vehicle[1]))  # Use dwvkey as idkey, vehicle ref as carreg
                                pg_conn.commit()
                                logging.info(f"Created new entry for {vehicle[0]}")
                                extra_info = ('Y', 'Y', '')
                            
                            logging.info(f"Extra info for {vehicle[0]}: {extra_info}")
                            
                            # Format the display
                            spare_keys = extra_info[0] if extra_info and extra_info[0] else 'N/A'
                            extra = extra_info[1] if extra_info and extra_info[1] else 'N/A'
                            notes = extra_info[2] if extra_info and extra_info[2] else ''
                            
                            # Get collection and delivery names
                            collection_name = next((c[2] for c in collections if c[4] == vehicle[3]), "Unknown")
                            delivery_name = next((d[2] for d in deliveries if d[4] == vehicle[4]), "Unknown")
                            
                            print(f"{Fore.WHITE}{vehicle[1]:<15} | {vehicle[2]:<30} | {spare_keys:<10} | {extra:<5} | {notes}{Style.RESET_ALL}")
                            print(f"    {Fore.CYAN}Collection: {collection_name} | Delivery: {delivery_name}{Style.RESET_ALL}")
                        except Exception as e:
                            logging.error(f"Error processing vehicle {vehicle[1]}: {e}")
                            print(f"{Fore.WHITE}{vehicle[1]:<15} | {vehicle[2]:<30} | N/A | N/A | {Style.RESET_ALL}")
                            print(f"    {Fore.CYAN}Collection: {collection_name} | Delivery: {delivery_name}{Style.RESET_ALL}")
                    
                    pg_cursor.close()
                    pg_conn.close()
                    logging.info("PostgreSQL connection closed")
                except Exception as e:
                    logging.error(f"Error connecting to PostgreSQL: {e}")
                    print(f"{Fore.RED}Error connecting to PostgreSQL: {e}{Style.RESET_ALL}")
                    # Fallback to basic display if PostgreSQL connection fails
                    for vehicle in vehicles:
                        collection_name = next((c[2] for c in collections if c[4] == vehicle[3]), "Unknown")
                        delivery_name = next((d[2] for d in deliveries if d[4] == vehicle[4]), "Unknown")
                        print(f"{Fore.WHITE}{vehicle[1]:<15} | {vehicle[2]:<30} | N/A | N/A | {Style.RESET_ALL}")
                        print(f"    {Fore.CYAN}Collection: {collection_name} | Delivery: {delivery_name}{Style.RESET_ALL}")
            else:
                # Fallback to basic display if no PostgreSQL config
                for vehicle in vehicles:
                    collection_name = next((c[2] for c in collections if c[4] == vehicle[3]), "Unknown")
                    delivery_name = next((d[2] for d in deliveries if d[4] == vehicle[4]), "Unknown")
                    print(f"{Fore.WHITE}{vehicle[1]:<15} | {vehicle[2]:<30} | N/A | N/A | {Style.RESET_ALL}")
                    print(f"    {Fore.CYAN}Collection: {collection_name} | Delivery: {delivery_name}{Style.RESET_ALL}")
            
        except Exception as e:
            print(f"{Fore.RED}Error showing load details: {e}{Style.RESET_ALL}")
            logging.error(f"Error showing load details: {e}")

    def print_menu(self):
        """Print the menu with fancy formatting."""
        menu_border = f"{Fore.BLUE}{'═' * 60}{Style.RESET_ALL}"
        menu_title = f"{Fore.CYAN}{'▌' * 5} SQLite Database Editor for Y/N/mixed Values {'▌' * 5}{Style.RESET_ALL}"
        
        print("\n" + menu_border)
        print(menu_title)
        print(menu_border)
        print(f"{Fore.YELLOW}┌──────────────────────────────────────┐{Style.RESET_ALL}")
        print(f"{Fore.YELLOW}│{Style.RESET_ALL} {Fore.WHITE}1.{Style.RESET_ALL} {Fore.CYAN}List tables                       {Fore.YELLOW}│{Style.RESET_ALL}")
        print(f"{Fore.YELLOW}│{Style.RESET_ALL} {Fore.WHITE}2.{Style.RESET_ALL} {Fore.CYAN}Display data                      {Fore.YELLOW}│{Style.RESET_ALL}")
        print(f"{Fore.YELLOW}│{Style.RESET_ALL} {Fore.WHITE}3.{Style.RESET_ALL} {Fore.CYAN}Edit a record                     {Fore.YELLOW}│{Style.RESET_ALL}")
        print(f"{Fore.YELLOW}│{Style.RESET_ALL} {Fore.WHITE}4.{Style.RESET_ALL} {Fore.CYAN}Add a new record                  {Fore.YELLOW}│{Style.RESET_ALL}")
        print(f"{Fore.YELLOW}│{Style.RESET_ALL} {Fore.WHITE}5.{Style.RESET_ALL} {Fore.CYAN}Show changes made                 {Fore.YELLOW}│{Style.RESET_ALL}")
        print(f"{Fore.YELLOW}│{Style.RESET_ALL} {Fore.WHITE}6.{Style.RESET_ALL} {Fore.CYAN}Show schema info                  {Fore.YELLOW}│{Style.RESET_ALL}")
        print(f"{Fore.YELLOW}│{Style.RESET_ALL} {Fore.WHITE}7.{Style.RESET_ALL} {Fore.CYAN}Add table description             {Fore.YELLOW}│{Style.RESET_ALL}")
        print(f"{Fore.YELLOW}│{Style.RESET_ALL} {Fore.WHITE}8.{Style.RESET_ALL} {Fore.CYAN}Add column description            {Fore.YELLOW}│{Style.RESET_ALL}")
        print(f"{Fore.YELLOW}│{Style.RESET_ALL} {Fore.WHITE}9.{Style.RESET_ALL} {Fore.CYAN}Export schema                     {Fore.YELLOW}│{Style.RESET_ALL}")
        print(f"{Fore.YELLOW}│{Style.RESET_ALL} {Fore.WHITE}10.{Style.RESET_ALL} {Fore.CYAN}Show loads                       {Fore.YELLOW}│{Style.RESET_ALL}")
        print(f"{Fore.YELLOW}│{Style.RESET_ALL} {Fore.WHITE}11.{Style.RESET_ALL} {Fore.CYAN}Sync to PostgreSQL               {Fore.YELLOW}│{Style.RESET_ALL}")
        print(f"{Fore.YELLOW}│{Style.RESET_ALL} {Fore.WHITE}12.{Style.RESET_ALL} {Fore.CYAN}Find Missing Car Details         {Fore.YELLOW}│{Style.RESET_ALL}")
        print(f"{Fore.YELLOW}│{Style.RESET_ALL} {Fore.WHITE}13.{Style.RESET_ALL} {Fore.CYAN}Exit                           {Fore.YELLOW}│{Style.RESET_ALL}")
        print(f"{Fore.YELLOW}└──────────────────────────────────────┘{Style.RESET_ALL}")
        
        if self.table_name:
            print(f"{Fore.WHITE}Current table: {Fore.GREEN}{self.table_name}{Style.RESET_ALL}")
        if self.column_name:
            print(f"{Fore.WHITE}Current column: {Fore.GREEN}{self.column_name}{Style.RESET_ALL}")
        
        print(f"{Fore.CYAN}Enter your choice (1-13):{Style.RESET_ALL} ", end="")
    
    def export_schema(self):
        """Export the schema to a formatted markdown file."""
        if not self.schema_data:
            print(f"{Fore.RED}No schema data to export.{Style.RESET_ALL}")
            return
        
        try:
            # Create export directory if it doesn't exist
            export_dir = os.path.join(SCRIPT_DIR, "schema", "exports")
            os.makedirs(export_dir, exist_ok=True)
            
            # Generate export filename with timestamp
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            export_file = os.path.join(export_dir, f"schema_export_{timestamp}.md")
            
            with open(export_file, 'w') as f:
                # Write header
                f.write("# Database Schema Documentation\n\n")
                f.write(f"Generated on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
                
                # Write tables section
                f.write("## Tables\n\n")
                for table_name, table_info in self.schema_data.get("tables", {}).items():
                    f.write(f"### {table_name}\n\n")
                    f.write(f"**Description:** {table_info.get('description', 'No description')}\n\n")
                    f.write(f"**Last Updated:** {table_info.get('last_updated', 'Unknown')}\n\n")
                    
                    # Get column information
                    try:
                        self.cursor.execute(f"PRAGMA table_info({table_name})")
                        columns = self.cursor.fetchall()
                        
                        f.write("#### Columns\n\n")
                        f.write("| Column Name | Type | Description | Primary Key |\n")
                        f.write("|------------|------|-------------|-------------|\n")
                        
                        for col in columns:
                            col_name = col[1]
                            col_type = col[2]
                            # Check specifically for dwjkey
                            is_dwjkey = "Yes" if col_name.lower() == "dwjkey" else "No"
                            column_key = f"{table_name}.{col_name}"
                            col_desc = self.schema_data.get("columns", {}).get(column_key, {}).get("description", "No description")
                            
                            f.write(f"| {col_name} | {col_type} | {col_desc} | {is_dwjkey} |\n")
                        
                        f.write("\n")
                    except sqlite3.Error as e:
                        logging.error(f"Error getting column info for table {table_name}: {e}")
                        f.write("Error retrieving column information\n\n")
            
            print(f"{Fore.GREEN}Schema exported to: {export_file}{Style.RESET_ALL}")
            logging.info(f"Schema exported to {export_file}")
            
        except Exception as e:
            logging.error(f"Error exporting schema: {e}")
            print(f"{Fore.RED}Error exporting schema: {e}{Style.RESET_ALL}")

    def run(self):
        """Run the main application loop."""
        print(f"{Fore.BLUE}{'═' * 60}{Style.RESET_ALL}")
        print(f"{Fore.CYAN}   SQLite Database Editor for Y/N/mixed Values{Style.RESET_ALL}")
        print(f"{Fore.BLUE}{'═' * 60}{Style.RESET_ALL}")
        
        if not self.check_db_exists():
            print(f"{Fore.RED}Exiting: Database not found or created.{Style.RESET_ALL}")
            return
        
        if not self.connect_db():
            print(f"{Fore.RED}Exiting: Could not connect to database.{Style.RESET_ALL}")
            return
            
        # Test PostgreSQL connection at startup
        if self.pg_config:
            self.test_connection()
        
        while True:
            self.print_menu()
            choice = input()
            
            if choice == '1':
                self.list_tables()
            elif choice == '2':
                self.display_data()
            elif choice == '3':
                self.edit_record()
            elif choice == '4':
                self.add_record()
            elif choice == '5':
                self.show_changes()
            elif choice == '6':
                self.show_schema_info()
            elif choice == '7':
                self.add_table_description()
            elif choice == '8':
                self.add_column_description()
            elif choice == '9':
                self.export_schema()
            elif choice == '10':
                self.show_loads()
            elif choice == '11':
                self.sync_to_postgres()
            elif choice == '12':
                self.find_missing_car_details()
            elif choice == '13':
                print(f"{Fore.GREEN}Saving changes and exiting...{Style.RESET_ALL}")
                self.save_schema()  # Save any pending schema changes
                self.close_db()
                break
            else:
                print(f"{Fore.RED}Invalid choice. Please try again.{Style.RESET_ALL}")

    def save_display_settings(self):
        """Save display settings to schema."""
        if "display_settings" not in self.schema_data:
            self.schema_data["display_settings"] = {}
        self.schema_data["display_settings"]["job_columns"] = self.job_display_columns
        self.schema_data["display_settings"]["vehicle_columns"] = self.vehicle_display_columns
        self.save_schema()

    def format_date(self, date_str):
        """Format date string to a more readable format."""
        try:
            # Assuming date is in format YYYYMMDD
            if len(date_str) == 8:
                year = date_str[:4]
                month = date_str[4:6]
                day = date_str[6:8]
                return f"{day}/{month}/{year}"
            return date_str
        except:
            return date_str

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

    def sync_to_postgres(self):
        """Sync data from SQLite to PostgreSQL."""
        if not self.pg_config:
            print(f"{Fore.RED}PostgreSQL configuration not found. Please check sql.ini file.{Style.RESET_ALL}")
            return

        try:
            # Connect to PostgreSQL
            pg_conn = psycopg2.connect(**self.pg_config)
            pg_cursor = pg_conn.cursor()
            
            # Get list of tables to sync
            self.cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = [row[0] for row in self.cursor.fetchall()]
            
            total_inserted = 0
            total_updated = 0
            total_skipped = 0
            
            for table_name in tables:
                # Skip extracarinfo as it's PostgreSQL-only
                if table_name.lower() == 'extracarinfo':
                    continue
                    
                print(f"\n{Fore.CYAN}Processing table: {table_name}{Style.RESET_ALL}")
                
                # Get column names
                self.cursor.execute(f"PRAGMA table_info({table_name})")
                column_names = [row[1] for row in self.cursor.fetchall()]
                
                # Get data from SQLite
                self.cursor.execute(f"SELECT * FROM {table_name}")
                rows = self.cursor.fetchall()
                
                if not rows:
                    print(f"{Fore.YELLOW}No data found in {table_name}{Style.RESET_ALL}")
                    continue
                
                # Check which records exist in PostgreSQL
                pg_cursor.execute(f"SELECT {column_names[0]} FROM {table_name}")
                existing_keys = {row[0] for row in pg_cursor.fetchall()}
                
                insert_rows = []
                update_rows = []
                
                for row in rows:
                    if row[0] not in existing_keys:
                        insert_rows.append(row)
                    else:
                        update_rows.append(row)
                
                # Insert new records
                if insert_rows:
                    insert_sql = f"""
                    INSERT INTO {table_name} ({', '.join(column_names)})
                    VALUES ({', '.join(['%s'] * len(column_names))})
                    """
                    pg_cursor.executemany(insert_sql, insert_rows)
                    total_inserted += len(insert_rows)
                
                # Update existing records
                if update_rows:
                    for row in update_rows:
                        # For DWVVEH table, exclude dwvmoddes from updates
                        if table_name == 'dwvveh':
                            update_cols = [col for col in column_names[1:] if col != 'dwvmoddes']
                            set_clause = ', '.join(f"{col} = %s" for col in update_cols)
                            update_values = [row[column_names.index(col)] for col in update_cols]
                            update_sql = f"""
                            UPDATE {table_name}
                            SET {set_clause}, last_updated = CURRENT_TIMESTAMP
                            WHERE {column_names[0]} = %s
                            """
                            pg_cursor.execute(update_sql, update_values + [row[0]])
                        else:
                            set_clause = ', '.join(f"{col} = %s" for col in column_names[1:])
                            update_sql = f"""
                            UPDATE {table_name}
                            SET {set_clause}, last_updated = CURRENT_TIMESTAMP
                            WHERE {column_names[0]} = %s
                            """
                            pg_cursor.execute(update_sql, row[1:] + (row[0],))
                    total_updated += len(update_rows)
                
                total_skipped += len(rows) - len(insert_rows) - len(update_rows)
                pg_conn.commit()
            
            # Handle extracarinfo table separately
            print(f"\n{Fore.CYAN}Processing extracarinfo table...{Style.RESET_ALL}")
            
            # Get vehicles from DWVVEH that aren't in extracarinfo
            pg_cursor.execute("""
                SELECT v.dwvkey, v.dwvvehref
                FROM public.dwvveh v
                LEFT JOIN public.extracarinfo e ON v.dwvkey = e.idkey
                WHERE e.idkey IS NULL
            """)
            missing_cars = pg_cursor.fetchall()
            
            if missing_cars:
                print(f"{Fore.YELLOW}Found {len(missing_cars)} missing cars in extracarinfo{Style.RESET_ALL}")
                for key, reg in missing_cars:
                    pg_cursor.execute("""
                        INSERT INTO public.extracarinfo (idkey, carreg, sparekeys, extra, carnotes, photos)
                        VALUES (%s, %s, 'Y', 'Y', '', '{}')
                    """, (key, reg))
                pg_conn.commit()
                print(f"{Fore.GREEN}Added {len(missing_cars)} missing cars to extracarinfo{Style.RESET_ALL}")
            
            print(f"\n{Fore.GREEN}Sync completed successfully:{Style.RESET_ALL}")
            print(f"{Fore.WHITE}Records inserted: {Fore.GREEN}{total_inserted}{Style.RESET_ALL}")
            print(f"{Fore.WHITE}Records updated: {Fore.GREEN}{total_updated}{Style.RESET_ALL}")
            print(f"{Fore.WHITE}Records skipped (no changes): {Fore.GREEN}{total_skipped}{Style.RESET_ALL}")
            
        except Exception as e:
            logging.error(f"Error syncing to PostgreSQL: {e}")
            print(f"{Fore.RED}Error syncing to PostgreSQL: {e}{Style.RESET_ALL}")
        finally:
            if 'pg_cursor' in locals():
                pg_cursor.close()
            if 'pg_conn' in locals():
                pg_conn.close()

    def find_missing_car_details(self):
        """Find and update missing car make/model details."""
        if not self.pg_config:
            print(f"{Fore.RED}PostgreSQL configuration not found. Please check sql.ini file.{Style.RESET_ALL}")
            return

        try:
            # Connect to PostgreSQL
            pg_conn = psycopg2.connect(**self.pg_config)
            pg_cursor = pg_conn.cursor()
            
            # Query for vehicles with missing or incomplete make/model info
            query = """
                SELECT dwvVehRef, dwvModDes 
                FROM DWVVEH 
                WHERE dwvModDes IS NULL 
                OR TRIM(dwvModDes) = '' 
                OR dwvModDes NOT LIKE '% %'
                ORDER BY dwvVehRef;
            """
            pg_cursor.execute(query)
            missing = pg_cursor.fetchall()
            
            if not missing:
                print(f"{Fore.GREEN}No vehicles with missing make/model found.{Style.RESET_ALL}")
                return
            
            print(f"\n{Fore.YELLOW}Found {len(missing)} vehicles with missing make/model:{Style.RESET_ALL}")
            for reg, current_model in missing:
                print(f"{Fore.WHITE}Registration: {Fore.GREEN}{reg}{Style.RESET_ALL}, Current Make/Model: {Fore.YELLOW}'{current_model or 'Empty'}'{Style.RESET_ALL}")
            
            choice = input(f"\n{Fore.CYAN}Would you like to find missing makes and models? (y/n):{Style.RESET_ALL} ").strip().lower()
            if choice != 'y':
                return
            
            # Load API key from config
            config = configparser.ConfigParser()
            config_path = os.path.join(SQL_DIR, "sql.ini")
            config.read(config_path)
            api_key = config.get("API", "CAR_API_KEY", fallback=None)
            
            if not api_key:
                print(f"{Fore.RED}CAR_API_KEY not found in sql.ini{Style.RESET_ALL}")
                return
            
            print(f"\n{Fore.CYAN}Fetching missing details...{Style.RESET_ALL}")
            updated_count = 0
            
            for reg, current_model in missing:
                try:
                    # Make API request
                    url = "https://api.checkcardetails.co.uk/vehicledata/vehicleregistration"
                    params = {
                        "apikey": api_key,
                        "vrm": reg
                    }
                    
                    response = requests.get(url, params=params, timeout=10)
                    response.raise_for_status()
                    data = response.json()
                    
                    if data and "make" in data and "model" in data:
                        make = data.get("make", "").strip()
                        model = data.get("model", "").strip()
                        full_details = f"{make} {model}".strip()
                        
                        if full_details and " " in full_details:
                            print(f"{Fore.GREEN}Found: {reg} -> {full_details}{Style.RESET_ALL}")
                            
                            # Update PostgreSQL
                            update_sql = "UPDATE DWVVEH SET dwvModDes = %s WHERE dwvVehRef = %s"
                            pg_cursor.execute(update_sql, (full_details, reg))
                            pg_conn.commit()
                            updated_count += 1
                        else:
                            print(f"{Fore.YELLOW}Invalid make/model data for {reg}{Style.RESET_ALL}")
                    else:
                        print(f"{Fore.YELLOW}No data found for {reg}{Style.RESET_ALL}")
                    
                    # Add delay to avoid rate limiting
                    time.sleep(1)
                    
                except Exception as e:
                    print(f"{Fore.RED}Error processing {reg}: {e}{Style.RESET_ALL}")
                    continue
            
            print(f"\n{Fore.GREEN}Update complete:{Style.RESET_ALL}")
            print(f"{Fore.WHITE}Updated {updated_count} out of {len(missing)} vehicles{Style.RESET_ALL}")
            
        except Exception as e:
            logging.error(f"Error finding missing car details: {e}")
            print(f"{Fore.RED}Error finding missing car details: {e}{Style.RESET_ALL}")
        finally:
            if 'pg_cursor' in locals():
                pg_cursor.close()
            if 'pg_conn' in locals():
                pg_conn.close()

    def test_connection(self):
        """Test PostgreSQL connection and print detailed information."""
        if not self.pg_config:
            print(f"{Fore.RED}PostgreSQL configuration not found. Please check sql.ini file.{Style.RESET_ALL}")
            return False
            
        try:
            print(f"\n{Fore.CYAN}Testing PostgreSQL connection...{Style.RESET_ALL}")
            print(f"{Fore.WHITE}Host: {self.pg_config.get('host', 'unknown')}{Style.RESET_ALL}")
            print(f"{Fore.WHITE}Port: {self.pg_config.get('port', 'unknown')}{Style.RESET_ALL}")
            print(f"{Fore.WHITE}Database: {self.pg_config.get('database', 'unknown')}{Style.RESET_ALL}")
            print(f"{Fore.WHITE}Username: {self.pg_config.get('user', 'unknown')}{Style.RESET_ALL}")
            
            pg_conn = psycopg2.connect(**self.pg_config)
            pg_cursor = pg_conn.cursor()
            
            # Test basic connection
            pg_cursor.execute("SELECT version();")
            version = pg_cursor.fetchone()
            print(f"{Fore.GREEN}Successfully connected to PostgreSQL{Style.RESET_ALL}")
            print(f"{Fore.WHITE}Server version: {version[0]}{Style.RESET_ALL}")
            
            # Test extracarinfo table
            pg_cursor.execute("""
                SELECT COUNT(*) 
                FROM extracarinfo;
            """)
            count = pg_cursor.fetchone()
            print(f"{Fore.WHITE}Records in extracarinfo table: {count[0]}{Style.RESET_ALL}")
            
            # Test a sample vehicle
            pg_cursor.execute("""
                SELECT idkey, sparekeys, extra, carnotes
                FROM extracarinfo
                LIMIT 1;
            """)
            sample = pg_cursor.fetchone()
            if sample:
                print(f"{Fore.WHITE}Sample record:{Style.RESET_ALL}")
                print(f"  ID: {sample[0]}")
                print(f"  Spare Keys: {sample[1]}")
                print(f"  Extra: {sample[2]}")
                print(f"  Notes: {sample[3]}")
            
            pg_cursor.close()
            pg_conn.close()
            print(f"{Fore.GREEN}Connection test completed successfully{Style.RESET_ALL}")
            return True
            
        except Exception as e:
            print(f"{Fore.RED}Connection test failed: {e}{Style.RESET_ALL}")
            logging.error(f"PostgreSQL connection test failed: {e}")
            return False


# Function that can be imported by other scripts to check all entries in a table/column
def check_all_entries(table_name=None, column_name=None):
    """
    Function that can be imported by other scripts to check all entries in a specified
    table and column or use the last selected ones.
    
    Args:
        table_name (str, optional): The table to check. If None, uses last selected.
        column_name (str, optional): The column to check. If None, uses last selected.
    
    Returns:
        dict: Summary of the data (counts of Y, N, mixed values)
    """
    try:
        editor = SQLiteEditor()
        if not editor.check_db_exists() or not editor.connect_db():
            return {"error": "Database connection failed"}
        
        editor.table_name = table_name  # Use provided or None
        editor.column_name = column_name  # Use provided or None
        
        # If either is None, try to use stored values or prompt user
        if not editor.table_name or not editor.column_name:
            # First check if we can load from a settings file
            settings_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'db', 'settings.txt')
            if os.path.exists(settings_path):
                with open(settings_path, 'r') as f:
                    lines = f.readlines()
                    if len(lines) >= 2:
                        stored_table = lines[0].strip()
                        stored_column = lines[1].strip()
                        if not editor.table_name and stored_table:
                            editor.table_name = stored_table
                        if not editor.column_name and stored_column:
                            editor.column_name = stored_column
        
        # If still None, we can't proceed
        if not editor.table_name or not editor.column_name:
            return {"error": "Table or column not specified"}
        
        editor.identify_primary_key()
        
        # Query the data
        editor.cursor.execute(f"SELECT {editor.column_name} FROM {editor.table_name}")
        rows = editor.cursor.fetchall()
        
        # Count occurrences of each value
        y_count = 0
        n_count = 0
        mixed_count = 0
        other_count = 0
        
        for row in rows:
            value = row[0]
            if value == 'Y':
                y_count += 1
            elif value == 'N':
                n_count += 1
            elif value == 'mixed':
                mixed_count += 1
            else:
                other_count += 1
        
        # Close the connection
        editor.close_db()
        
        # Save the current settings for future use
        with open(settings_path, 'w') as f:
            f.write(f"{editor.table_name}\n{editor.column_name}")
        
        return {
            "table": editor.table_name,
            "column": editor.column_name,
            "total_records": len(rows),
            "Y_count": y_count,
            "N_count": n_count,
            "mixed_count": mixed_count,
            "other_count": other_count,
            "has_data": len(rows) > 0
        }
    
    except Exception as e:
        return {"error": str(e)}


if __name__ == "__main__":
    editor = SQLiteEditor()
    try:
        editor.run()
    except KeyboardInterrupt:
        print(f"\n{Fore.YELLOW}Operation interrupted. Closing database connection...{Style.RESET_ALL}")
        editor.close_db()
    except Exception as e:
        print(f"{Fore.RED}An unexpected error occurred: {e}{Style.RESET_ALL}")
        editor.close_db()
    finally:
        print(f"{Fore.GREEN}Program terminated.{Style.RESET_ALL}")
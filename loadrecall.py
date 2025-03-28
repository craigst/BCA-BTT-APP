#!/usr/bin/env python3
import os
import sys
from datetime import datetime
import colorama
from colorama import Fore, Back, Style
import psycopg2
import configparser
import logging
from pathlib import Path

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
LOG_FILE = os.path.join(LOG_DIR, f"loadrecall_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log")
logging.basicConfig(
    level=logging.DEBUG,  # Set to DEBUG for development
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler()
    ]
)

def load_pg_config():
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

def get_load_details(load_number):
    """
    Retrieve and format load details for a given load number.
    Returns a dictionary containing collections, deliveries, and vehicle information.
    """
    logging.info(f"Retrieving details for load {load_number}")
    
    try:
        # Load database configuration
        pg_config = load_pg_config()
        if not pg_config:
            raise Exception("Failed to load database configuration")
        
        # Connect to database
        conn = psycopg2.connect(**pg_config)
        cursor = conn.cursor()
        logging.info("Database connection successful")
        
        # Get collections
        cursor.execute("""
            SELECT 
                dwjtype,
                dwjcust,
                dwjname,
                dwjdate,
                dwjadrcod,
                dwjpostco
            FROM public.dwjjob
            WHERE dwjload = %s
            AND dwjtype = 'C'
            ORDER BY dwjdate, dwjcust
        """, (load_number,))
        
        collections = cursor.fetchall()
        logging.info(f"Found {len(collections)} collections")
        
        # Get deliveries
        cursor.execute("""
            SELECT 
                dwjtype,
                dwjcust,
                dwjname,
                dwjdate,
                dwjadrcod,
                dwjpostco
            FROM public.dwjjob
            WHERE dwjload = %s
            AND dwjtype = 'D'
            ORDER BY dwjdate, dwjcust
        """, (load_number,))
        
        deliveries = cursor.fetchall()
        logging.info(f"Found {len(deliveries)} deliveries")
        
        # Get vehicles with their collection and delivery assignments
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
        logging.info(f"Found {len(vehicles)} vehicles")
        
        # Format the data into a structured dictionary
        load_data = {
            'load_number': load_number,
            'collections': [],
            'deliveries': [],
            'vehicles': []
        }
        
        # Process collections
        for collection in collections:
            load_data['collections'].append({
                'type': collection[0],
                'customer': collection[1],
                'name': collection[2],
                'date': datetime.strptime(str(collection[3]), '%Y%m%d').strftime('%d/%m/%Y'),
                'address_code': collection[4],
                'postcode': collection[5]
            })
        
        # Process deliveries
        for delivery in deliveries:
            load_data['deliveries'].append({
                'type': delivery[0],
                'customer': delivery[1],
                'name': delivery[2],
                'date': datetime.strptime(str(delivery[3]), '%Y%m%d').strftime('%d/%m/%Y'),
                'address_code': delivery[4],
                'postcode': delivery[5]
            })
        
        # Process vehicles
        for vehicle in vehicles:
            # Find collection and delivery locations for this vehicle
            collection = next((c for c in load_data['collections'] if c['address_code'] == vehicle[2]), None)
            delivery = next((d for d in load_data['deliveries'] if d['address_code'] == vehicle[3]), None)
            
            load_data['vehicles'].append({
                'registration': vehicle[0],
                'model': vehicle[1],
                'collection': collection['name'] if collection else 'Unknown',
                'delivery': delivery['name'] if delivery else 'Unknown',
                'spare_keys': vehicle[4],
                'documents': vehicle[5],
                'notes': vehicle[6]
            })
        
        return load_data
        
    except Exception as e:
        logging.error(f"Error retrieving load details: {e}", exc_info=True)
        raise
    finally:
        if 'cursor' in locals():
            cursor.close()
        if 'conn' in locals():
            conn.close()

def display_load_details(load_data):
    """Display load details in a clean, formatted way."""
    print(f"\n{Fore.CYAN}{'═' * 60}{Style.RESET_ALL}")
    print(f"{Fore.YELLOW}Load Details for Load {load_data['load_number']}{Style.RESET_ALL}")
    print(f"{Fore.CYAN}{'═' * 60}{Style.RESET_ALL}")
    
    # Display Collections
    if load_data['collections']:
        print(f"\n{Fore.GREEN}Collections:{Style.RESET_ALL}")
        print(f"{Fore.WHITE}{'Date':<12} | {'Customer':<10} | {'Location':<30} | {'Postcode':<10}{Style.RESET_ALL}")
        print("-" * 70)
        for collection in load_data['collections']:
            print(f"{Fore.WHITE}{collection['date']:<12} | {Fore.YELLOW}{collection['customer']:<10} | {Fore.CYAN}{collection['name']:<30} | {Fore.GREEN}{collection['postcode']:<10}{Style.RESET_ALL}")
    
    # Display Deliveries
    if load_data['deliveries']:
        print(f"\n{Fore.GREEN}Deliveries:{Style.RESET_ALL}")
        print(f"{Fore.WHITE}{'Date':<12} | {'Customer':<10} | {'Location':<30} | {'Postcode':<10}{Style.RESET_ALL}")
        print("-" * 70)
        for delivery in load_data['deliveries']:
            print(f"{Fore.WHITE}{delivery['date']:<12} | {Fore.YELLOW}{delivery['customer']:<10} | {Fore.CYAN}{delivery['name']:<30} | {Fore.GREEN}{delivery['postcode']:<10}{Style.RESET_ALL}")
    
    # Display Vehicles
    if load_data['vehicles']:
        print(f"\n{Fore.GREEN}Vehicles:{Style.RESET_ALL}")
        print(f"{Fore.WHITE}{'Registration':<12} | {'Model':<20} | {'Collection':<20} | {'Delivery':<20} | {'Spare Keys':<10} | {'Documents':<10}{Style.RESET_ALL}")
        print("-" * 100)
        for vehicle in load_data['vehicles']:
            print(f"{Fore.WHITE}{vehicle['registration']:<12} | {Fore.YELLOW}{vehicle['model']:<20} | {Fore.CYAN}{vehicle['collection']:<20} | {Fore.CYAN}{vehicle['delivery']:<20} | {Fore.GREEN}{vehicle['spare_keys']:<10} | {Fore.GREEN}{vehicle['documents']:<10}{Style.RESET_ALL}")
            if vehicle['notes']:
                print(f"   {Fore.RED}Notes: {vehicle['notes']}{Style.RESET_ALL}")

def main():
    """Main function to handle user input and display results."""
    try:
        # Get load number from user
        print(f"\n{Fore.CYAN}Load Recall System{Style.RESET_ALL}")
        print(f"{Fore.CYAN}{'═' * 60}{Style.RESET_ALL}")
        
        while True:
            load_number = input(f"\n{Fore.YELLOW}Enter load number (or 'q' to quit):{Style.RESET_ALL} ").strip()
            
            if load_number.lower() == 'q':
                print(f"{Fore.GREEN}Exiting...{Style.RESET_ALL}")
                break
            
            if not load_number:
                print(f"{Fore.RED}Please enter a valid load number.{Style.RESET_ALL}")
                continue
            
            try:
                # Get and display load details
                load_data = get_load_details(load_number)
                display_load_details(load_data)
            except Exception as e:
                print(f"{Fore.RED}Error retrieving load details: {e}{Style.RESET_ALL}")
                logging.error(f"Error in main loop: {e}", exc_info=True)
            
            print(f"\n{Fore.CYAN}{'═' * 60}{Style.RESET_ALL}")
    
    except KeyboardInterrupt:
        print(f"\n{Fore.YELLOW}Operation interrupted. Exiting...{Style.RESET_ALL}")
    except Exception as e:
        print(f"{Fore.RED}An unexpected error occurred: {e}{Style.RESET_ALL}")
        logging.error(f"Unexpected error in main: {e}", exc_info=True)
    finally:
        print(f"{Fore.GREEN}Program terminated.{Style.RESET_ALL}")

if __name__ == "__main__":
    main() 
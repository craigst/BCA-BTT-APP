# BCA BTT APP

A comprehensive suite of Python applications for managing vehicle transport operations, timesheets, and database operations.

## Overview

This project consists of three main Python applications that work together to handle various aspects of vehicle transport operations:

1. **ADB.py** - Android Device Manager for handling app installation and database operations on Android devices
2. **PAPERWORK.py** - Document management system for generating and managing transport-related paperwork
3. **SQL.py** - Timesheet and database management system for tracking work hours and vehicle information

## Components

### 1. ADB.py (Android Device Manager)

This application manages Android devices and handles:
- App installation and management
- Database operations (pull/push)
- Device connection management
- Root access verification
- File transfer operations

Key features:
- Automatic device detection and connection
- App installation and permission management
- Database backup and restoration
- Root access testing and verification
- Comprehensive logging system

### 2. PAPERWORK.py (Document Manager)

Handles the generation and management of transport-related documents:
- Loadsheet generation
- Timesheet creation
- Signature management
- Document formatting
- Vehicle information tracking

Key features:
- Automated document generation
- Signature placement and scaling
- Vehicle information tracking
- Load summary generation
- Customizable document templates

### 3. SQL.py (Timesheet & Database Manager)

Manages timesheets and database operations:
- Work hours tracking
- Vehicle information management
- Database synchronization
- Load details viewing
- Car information editing

Key features:
- Weekly hours tracking
- Load details viewing
- Vehicle information management
- Database synchronization with PostgreSQL
- Comprehensive reporting

## Setup

1. Create a Python virtual environment:
```bash
python -m venv venv
```

2. Activate the virtual environment:
- Windows: `.\venv\Scripts\activate`
- Linux/Mac: `source venv/bin/activate`

3. Install required packages:
```bash
pip install -r requirements.txt
```

4. Configure the database:
- Ensure PostgreSQL is installed and running
- Create the necessary database
- Update the SQL configuration in `sql.ini`

## Directory Structure

```
BCA-BTT-APP/
├── ADB.py              # Android Device Manager
├── PAPERWORK.py        # Document Manager
├── SQL.py             # Timesheet & Database Manager
├── requirements.txt    # Python dependencies
├── apk/               # Android APK files
├── db/                # Database files
├── logs/              # Application logs
├── platform-tools/    # Android platform tools
└── schema/            # Database schema files
```

## Usage

### ADB.py
```bash
python ADB.py
```
- Manages Android devices
- Handles app installation
- Manages database operations

### PAPERWORK.py
```bash
python PAPERWORK.py
```
- Generates transport documents
- Manages signatures
- Creates loadsheets and timesheets

### SQL.py
```bash
python SQL.py
```
- Manages timesheets
- Tracks work hours
- Handles vehicle information
- Manages database operations

## Features

### Database Management
- SQLite and PostgreSQL support
- Schema management
- Data synchronization
- Backup and restore capabilities

### Document Generation
- Automated loadsheet creation
- Timesheet generation
- Signature management
- Customizable templates

### Device Management
- Android device detection
- App installation
- Database operations
- File transfer capabilities

### Time Tracking
- Weekly hours tracking
- Work day management
- Load details viewing
- Vehicle information tracking

## Requirements

- Python 3.x
- PostgreSQL
- Android Debug Bridge (ADB)
- Required Python packages (see requirements.txt)

## Dependencies

- psycopg2-binary
- colorama
- Other dependencies listed in requirements.txt

## Notes

- Ensure proper permissions are set for database operations
- Keep Android platform tools updated
- Regular database backups are recommended
- Log files are stored in the logs directory

## Support

For issues or questions, please refer to the project documentation or contact the development team. 
#!/usr/bin/env python3
"""
Script to restore the latest working version of persistent_chat.py from backups.
Also helps identify which version was working based on debug logs.
"""

import os
import shutil
from pathlib import Path
import logging
import re
from datetime import datetime
from typing import Optional, Tuple

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

def find_working_version() -> Optional[Tuple[Path, Path]]:
    """
    Find the last working version by analyzing debug logs.
    Returns tuple of (backup_file, corresponding_log) if found, None otherwise.
    """
    try:
        project_dir = Path(__file__).parent
        logs_dir = project_dir / 'logs'
        backup_dir = project_dir / 'backups'
        
        # Get all log files sorted by modification time (newest first)
        log_files = sorted(logs_dir.glob('chat_debug_*.log'), 
                         key=lambda p: p.stat().st_mtime,
                         reverse=True)
        
        for log_file in log_files:
            # Extract timestamp from log filename
            match = re.search(r'chat_debug_(\d{8}_\d{6})\.log', log_file.name)
            if not match:
                continue
                
            log_timestamp = match.group(1)
            
            # Check log content for successful API responses
            with open(log_file, 'r', encoding='utf-8') as f:
                content = f.read()
                if 'API Response Body' in content and 'Error' not in content:
                    # Find backup file with closest timestamp
                    backup_files = list(backup_dir.glob('persistent_chat_*.py'))
                    if backup_files:
                        closest_backup = min(backup_files, 
                            key=lambda p: abs(p.stat().st_mtime - log_file.stat().st_mtime))
                        return closest_backup, log_file
        
        return None
        
    except Exception as e:
        logging.error("Error finding working version: %s", str(e))
        return None

def restore_working_version(specific_backup: Optional[Path] = None) -> bool:
    """
    Restore a working version of persistent_chat.py
    Args:
        specific_backup: Optional specific backup file to restore from
    """
    try:
        project_dir = Path(__file__).parent
        target_file = project_dir / 'persistent_chat.py'
        
        if specific_backup:
            backup_file = specific_backup
        else:
            # Find last working version from logs
            result = find_working_version()
            if result is None:
                logging.error("Could not find a working version in logs")
                return False
            backup_file, log_file = result
            logging.info("Found working version with corresponding log: %s", log_file.name)
        
        # Create backup of current file
        if target_file.exists():
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            current_backup = target_file.with_suffix(f'.py.broken_{timestamp}')
            shutil.copy2(target_file, current_backup)
            logging.info("Current version backed up to %s", current_backup)
        
        # Restore from backup
        shutil.copy2(backup_file, target_file)
        logging.info("Successfully restored from backup: %s", backup_file.name)
        return True
        
    except Exception as e:
        logging.error("Error restoring backup: %s", str(e))
        return False

if __name__ == "__main__":
    print("\nAnalyzing debug logs to find last working version...")
    if restore_working_version():
        print("\nRestoration successful! The working version has been restored.")
        print("Your previous version was backed up with '.broken_[timestamp]' extension.")
    else:
        print("\nRestoration failed. Please check the logs for details.")

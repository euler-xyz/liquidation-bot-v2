"""
Logging setup module
"""
import logging
import os
import sys
import traceback

def setup_logger():
    """
    Set up and return a configured logger instance.
    """
    logger = logging.getLogger('liquidation_bot')
    logger.setLevel(logging.INFO)

    # Create formatters
    detailed_formatter = logging.Formatter(
        "%(asctime)s - %(levelname)s - %(message)s\n%(exc_info)s")
    standard_formatter = logging.Formatter(
        "%(asctime)s - %(levelname)s - %(message)s")

    class DetailedExceptionFormatter(logging.Formatter):
        def format(self, record):
            if record.levelno >= logging.ERROR:
                record.exc_text = "".join(
                    traceback.format_exception(*record.exc_info)) if record.exc_info else ""
                return detailed_formatter.format(record)
            return standard_formatter.format(record)

    # Create handlers
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(DetailedExceptionFormatter())

    # Ensure logs directory exists
    os.makedirs("logs", exist_ok=True)
    
    # Add file handler
    file_handler = logging.FileHandler("logs/account_monitor_logs.log", mode="a")
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(DetailedExceptionFormatter())

    # Add handlers to the logger
    logger.addHandler(console_handler)
    logger.addHandler(file_handler)

    return logger

# Create a global logger instance
logger = setup_logger() 
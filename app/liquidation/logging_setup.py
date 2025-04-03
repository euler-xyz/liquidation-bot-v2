"""
Logging setup module
"""
import logging
import os
import sys

def setup_logger():
    """
    Set up and return a configured logger instance.
    """
    logger = logging.getLogger('liquidation_bot')
    logger.setLevel(logging.INFO)

    # Create formatters and add it to handlers
    log_format = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    # Create handlers
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(log_format)

    # Add handlers to the logger
    logger.addHandler(console_handler)

    return logger

# Create a global logger instance
logger = setup_logger() 
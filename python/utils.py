import logging
import os

from web3 import Web3
from dotenv import load_dotenv

def setup_logger(logs_path: str):
    logger = logging.getLogger()
    logger.setLevel(logging.DEBUG)

    console_handler = logging.StreamHandler()
    file_handler = logging.FileHandler(logs_path, mode='w')

    formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
    console_handler.setFormatter(formatter)
    file_handler.setFormatter(formatter)

    logger.addHandler(console_handler)
    logger.addHandler(file_handler)

    return logger

def setup_w3():
    load_dotenv()
    Web3(Web3.HTTPProvider(os.getenv('RPC_URL')))
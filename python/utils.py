import logging
import os
import json
import functools
import requests
import yaml
import time

from web3 import Web3
from dotenv import load_dotenv

def setup_logger(logs_path: str):
    logger = logging.getLogger("liquidation_bot")
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
    return Web3(Web3.HTTPProvider(os.getenv('RPC_URL')))

def create_contract_instance(address, abi_path):
    with open(abi_path, 'r') as file:
        interface = json.load(file)
    abi = interface['abi']
    
    w3 = setup_w3()

    return w3.eth.contract(address=address, abi=abi)


with open('config.yaml') as config_file:
    config = yaml.safe_load(config_file)
NUM_RETRIES = config.get('NUM_RETRIES')
RETRY_DELAY = config.get('RETRY_DELAY')

def retry_request(logger: logging.Logger, max_retries: int = NUM_RETRIES, delay: int = RETRY_DELAY):
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            for attempt in range(1, max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except requests.RequestException as e:
                    logger.error(f"Error in API request, waiting {delay} seconds before retrying. Attempt {attempt}/{max_retries}")
                    if attempt == max_retries:
                        logger.error(f"Failed after {max_retries} attempts.")
                        return None
                    time.sleep(delay)
        return wrapper
    return decorator

@retry_request(logging.getLogger("liquidation_bot"))
def make_api_request(url, headers, params):
    response = requests.get(url, headers=headers, params=params)
    response.raise_for_status()
    return response.json()


def global_exception_handler(exctype, value, traceback):
    logger = logging.getLogger("liquidation_bot")
    logger.error(f"Uncaught exception", exc_info=(exctype, value, traceback))
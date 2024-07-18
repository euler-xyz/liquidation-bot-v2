"""
Utility functions for the liquidation bot.
"""
import logging
import os
import json
import functools
import time

from types import SimpleNamespace
from typing import Any, Callable, Dict, Optional

import requests
import yaml


from web3 import Web3
from web3.contract import Contract
from dotenv import load_dotenv

def load_config() -> SimpleNamespace:
    """
    Load configuration from a YAML file and return it as a SimpleNamespace object.

    Returns:
        SimpleNamespace: Configuration object with relevant settings
    """
    with open("config.yaml", encoding="utf-8") as config_file:
        config_dict = yaml.safe_load(config_file)

    config = SimpleNamespace(**config_dict)

    return config
def setup_logger(logs_path: str) -> logging.Logger:
    """
    Set up and configure a logger for the liquidation bot.

    Args:
        logs_path (str): Path to the log output file.

    Returns:
        logging.Logger: Configured logger instance.
    """
    logger = logging.getLogger("liquidation_bot")
    logger.setLevel(logging.DEBUG)

    console_handler = logging.StreamHandler()
    file_handler = logging.FileHandler(logs_path, mode="w")

    formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
    console_handler.setFormatter(formatter)
    file_handler.setFormatter(formatter)

    logger.addHandler(console_handler)
    logger.addHandler(file_handler)

    return logger

def setup_w3() -> Web3:
    """
    Set up and return a Web3 instance using the RPC URL from environment variables.

    Returns:
        Web3: Configured Web3 instance.
    """
    load_dotenv()
    return Web3(Web3.HTTPProvider(os.getenv("RPC_URL")))

def create_contract_instance(address: str, abi_path: str) -> Contract:
    """
    Create and return a contract instance.

    Args:
        address (str): The address of the contract.
        abi_path (str): Path to the ABI JSON file.

    Returns:
        Contract: Web3 contract instance.
    """
    with open(abi_path, "r", encoding="utf-8") as file:
        interface = json.load(file)
    abi = interface["abi"]

    w3 = setup_w3()

    return w3.eth.contract(address=address, abi=abi)


loaded_config = load_config()
def retry_request(logger: logging.Logger,
                  max_retries: int = loaded_config.NUM_RETRIES,
                  delay: int = loaded_config.RETRY_DELAY) -> Callable:
    """
    Decorator to retry a function in case of RequestException.

    Args:
        logger (logging.Logger): Logger instance to log retry attempts.
        max_retries (int, optional): Maximum number of retry attempts.
                                    Defaults to config.NUM_RETRIES.
        delay (int, optional): Delay between retry attempts in seconds.
                                Defaults to config.RETRY_DELAY.

    Returns:
        Callable: Decorated function.
    """
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            for attempt in range(1, max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except requests.RequestException as e:
                    logger.error(f"Error in API request, waiting {delay} seconds before retrying."
                                 f"Attempt {attempt}/{max_retries}")
                    logger.error(f"Error: {e}")

                    if attempt == max_retries:
                        logger.error(f"Failed after {max_retries} attempts.")
                        return None

                    time.sleep(delay)
        return wrapper
    return decorator

@retry_request(logging.getLogger("liquidation_bot"))
def make_api_request(url: str,
                     headers: Dict[str, str],
                     params: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Make an API request with retry functionality.

    Args:
        url (str): The URL for the API request.
        headers (Dict[str, str]): Headers for the request.
        params (Dict[str, Any]): Parameters for the request.

    Returns:
        Optional[Dict[str, Any]]: JSON response if successful, None otherwise.
    """
    response = requests.get(url, headers=headers, params=params, timeout=10)
    response.raise_for_status()
    return response.json()


def global_exception_handler(exctype: type, value: BaseException, traceback: Any) -> None:
    """
    Global exception handler to log uncaught exceptions.

    Args:
        exctype (type): The type of the exception.
        value (BaseException): The exception instance.
        traceback (Any): A traceback object encapsulating the call stack
                        at the point where the exception occurred.
    """
    logger = logging.getLogger("liquidation_bot")

    # Get the full traceback as a string
    trace_str = "".join(traceback.format_exception(exctype, value, traceback))

    # Log the full exception information
    logger.critical("Uncaught exception:\n %s", trace_str)


def post_liquidation_opportunity_on_slack(account_address: str, vault_address: str,
                  liquidation_data: Optional[Dict[str, Any]] = None) -> None:
    """
    Post a message on Slack.
    
    Args:
        message (str): The main message to post.
        liquidation_data (Optional[Dict[str, Any]]): Additional liquidation data to format.
    """
    load_dotenv()
    slack_url = os.getenv("SLACK_WEBHOOK_URL")

    if liquidation_data:
        message = (
            ":rotating_light: *Profitable Liquidation Opportunity Detected* :rotating_light:\n\n"
            f"*Account*: `{account_address}`\n"
            f"*Vault*: `{vault_address}`"
        )

        formatted_data = (
            f"*Liquidation Opportunity Details:*\n"
            f"• Profit: {Web3.from_wei(liquidation_data["profit"], "ether")} ETH\n"
            f"• Collateral Vault Address: `{liquidation_data["collateral_address"]}`\n"
            f"• Collateral Asset: `{liquidation_data["collateral_asset"]}`\n"
            f"• Leftover Collateral: {Web3.from_wei(liquidation_data["leftover_collateral"],
                                                    "ether")}\n"
            f"• Leftover Collateral in ETH terms (excluding gas): {Web3.from_wei(
                liquidation_data["leftover_collateral_in_eth"], "ether")} ETH\n\n"
            f"Time of detection: {time.strftime("%Y-%m-%d %H:%M:%S")}"
        )
        message += f"\n\n{formatted_data}"

    slack_payload = {
        "text": message
    }
    requests.post(slack_url, json=slack_payload, timeout=10)

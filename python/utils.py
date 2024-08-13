"""
Utility functions for the liquidation bot.
"""
import logging
import os
import json
import functools
import time
import traceback

from types import SimpleNamespace
from typing import Any, Callable, Dict, Optional

import requests
import yaml


from web3 import Web3
from web3.contract import Contract
from dotenv import load_dotenv
from urllib.parse import urlencode

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

    detailed_formatter = logging.Formatter(
        "%(asctime)s - %(levelname)s - %(message)s\n%(exc_info)s")

    # Create a standard formatter for other log levels
    standard_formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")

    class DetailedExceptionFormatter(logging.Formatter):
        def format(self, record):
            if record.levelno >= logging.ERROR:
                record.exc_text = "".join(
                    traceback.format_exception(*record.exc_info)) if record.exc_info else ""
                return detailed_formatter.format(record)
            else:
                return standard_formatter.format(record)

    console_handler.setFormatter(DetailedExceptionFormatter())
    file_handler.setFormatter(DetailedExceptionFormatter())

    logger.addHandler(console_handler)
    logger.addHandler(file_handler)


    return logger

class Web3Singleton:
    """
    Singleton class to manage w3 object creation
    """
    _instance = None

    @staticmethod
    def get_instance():
        """
        Set up a Web3 instance using the RPC URL from environment variables.
        """
        if Web3Singleton._instance is None:
            load_dotenv(override=True)
            rpc_url = os.getenv("RPC_URL")
            logger = logging.getLogger("liquidation_bot")
            logger.info("Trying to connect to RPC URL: %s", rpc_url)

            Web3Singleton._instance = Web3(Web3.HTTPProvider(rpc_url))
        return Web3Singleton._instance

def setup_w3() -> Web3:
    """
    Get the Web3 instance from the singleton class

    Returns:
        Web3: Web3 instance.
    """
    return Web3Singleton.get_instance()

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
                    logger.error(f"Error in API request, waiting {delay} seconds before retrying. "
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


def global_exception_handler(exctype: type, value: BaseException, tb: Any) -> None:
    """
    Global exception handler to log uncaught exceptions.

    Args:
        exctype (type): The type of the exception.
        value (BaseException): The exception instance.
        tb (Any): A traceback object encapsulating the call stack
                        at the point where the exception occurred.
    """
    logger = logging.getLogger("liquidation_bot")

    # Get the full traceback as a string
    trace_str = "".join(tb.format_exception(exctype, value, tb))

    # Log the full exception information
    logger.critical("Uncaught exception:\n %s", trace_str)

#TODO: add link to execute the transaction on the liqudiator contract
def post_liquidation_opportunity_on_slack(account_address: str, vault_address: str,
                  liquidation_data: Optional[Dict[str, Any]] = None, params: Optional[Dict[str, Any]] = None) -> None:
    """
    Post a message on Slack.
    
    Args:
        message (str): The main message to post.
        liquidation_data (Optional[Dict[str, Any]]): Additional liquidation data to format.
    """
    load_dotenv()
    slack_url = os.getenv("SLACK_WEBHOOK_URL")
    liquidation_ui_url = os.getenv("LIQUIDATION_UI_URL")

    if liquidation_data and params:

        # Unpack params
        violator_address, vault, borrowed_asset, collateral_vault, collateral_asset, max_repay, \
        seized_collateral_shares, swap_amount, leftover_collateral, swap_data_1inch, receiver = params

        # Build URL parameters
        url_params = urlencode({
            'violator': violator_address,
            'vault': vault,
            'borrowed_asset': borrowed_asset,
            'collateral_vault': collateral_vault,
            'collateral_asset': collateral_asset,
            'max_repay': max_repay,
            'seized_collateral_shares': seized_collateral_shares,
            'swap_amount': swap_amount,
            'leftover_collateral': leftover_collateral,
            'swap_data_1inch': swap_data_1inch,
            'receiver': receiver
        })

        # Construct the full URL
        execution_url = f"{liquidation_ui_url}/liquidation/execute?{url_params}"


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
            f"<{execution_url}|Click here to execute this liquidation manually>\n\n"
            f"Time of detection: {time.strftime("%Y-%m-%d %H:%M:%S")}"
        )
        message += f"\n\n{formatted_data}"

    slack_payload = {
        "text": message
    }
    requests.post(slack_url, json=slack_payload, timeout=10)


#TODO: Add link to transaction on etherscan
def post_liquidation_result_on_slack(account_address: str, vault_address: str,
                  liquidation_data: Optional[Dict[str, Any]] = None,
                  tx_hash: Optional[str] = None) -> None:
    """
    Post a message on Slack.
    
    Args:
        message (str): The main message to post.
        liquidation_data (Optional[Dict[str, Any]]): Additional liquidation data to format.
    """
    load_dotenv()
    slack_url = os.getenv("SLACK_WEBHOOK_URL")

    message = (
        ":moneybag: *Liquidation Completed* :moneybag:\n\n"
        f"*Liquidated Account*: `{account_address}`\n"
        f"*Vault*: `{vault_address}`"
    )

    tx_url = f"https://arbiscan.io/tx/{tx_hash}"

    formatted_data = (
        f"*Liquidation Details:*\n"
        f"• Profit: {Web3.from_wei(liquidation_data["profit"], "ether")} ETH\n"
        f"• Collateral Vault Address: `{liquidation_data["collateral_address"]}`\n"
        f"• Collateral Asset: `{liquidation_data["collateral_asset"]}`\n"
        f"• Leftover Collateral: {Web3.from_wei(liquidation_data["leftover_collateral"], "ether")} {liquidation_data["collateral_asset"]}\n"
        f"• Leftover Collateral in ETH terms: {Web3.from_wei(liquidation_data["leftover_collateral_in_eth"], "ether")} ETH\n\n"
        f"• Transaction: <{tx_url}|View on Arbiscan>\n\n"
        f"Time of liquidation: {time.strftime("%Y-%m-%d %H:%M:%S")}"
    )
    message += f"\n\n{formatted_data}"

    slack_payload = {
        "text": message
    }
    requests.post(slack_url, json=slack_payload, timeout=10)

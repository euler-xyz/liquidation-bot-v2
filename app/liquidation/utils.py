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

network_variables = {
    1: {
        "name": "Ethereum",
        "explorer_url": "https://etherscan.io"
    },
    42161: {
        "name": "Arbitrum",
        "explorer_url": "https://arbiscan.io"
    },
}

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
    file_handler = logging.FileHandler(logs_path, mode="a")

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

def get_spy_link(account):
    """
    Get account owner from EVC
    """
    evc = create_contract_instance(loaded_config.EVC, loaded_config.EVC_ABI_PATH)
    owner = evc.functions.getAccountOwner(account).call()
    if owner == "0x0000000000000000000000000000000000000000":
        owner = account

    subaccount_number = int(int(account, 16) ^ int(owner, 16))

    spy_link = f"https://app.euler.finance/account/{subaccount_number}?spy={owner}"
    
    return spy_link

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

def post_unhealthy_account_on_slack(account_address: str, vault_address: str,
                    health_score: float, value_borrowed: int) -> None:
    """
    Post a message on Slack about an unhealthy account.
    """
    load_dotenv()
    slack_url = os.getenv("SLACK_WEBHOOK_URL")
    
    spy_link = get_spy_link(account_address)

    message = (
        ":warning: *Unhealthy Account Detected* :warning:\n\n"
        f"*Account*: `{account_address}`, <{spy_link}|Spy Mode>\n"
        f"*Vault*: `{vault_address}`\n"
        f"*Health Score*: `{health_score:.4f}`\n"
        f"*Value Borrowed*: `${value_borrowed / 10 ** 18:.2f}`\n"
        f"Time of detection: {time.strftime("%Y-%m-%d %H:%M:%S")}\n"
        f"Network: `{network_variables[loaded_config.CHAIN_ID]["name"]}`\n\n"
    )

    slack_payload = {
        "text": message,
        "username": "Liquidation Bot",
        "icon_emoji": ":robot_face:"
    }
    requests.post(slack_url, json=slack_payload, timeout=10)


def post_liquidation_opportunity_on_slack(account_address: str, vault_address: str,
                  liquidation_data: Optional[Dict[str, Any]] = None,
                  params: Optional[Dict[str, Any]] = None) -> None:
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
        violator_address, vault, borrowed_asset, collateral_vault, collateral_asset, \
        max_repay, seized_collateral_shares, swap_amount, \
        leftover_collateral, swap_type, swap_data_1inch, receiver = params

        spy_link = get_spy_link(account_address)

        # Build URL parameters
        url_params = urlencode({
            "violator": violator_address,
            "vault": vault,
            "borrowed_asset": borrowed_asset,
            "collateral_vault": collateral_vault,
            "collateral_asset": collateral_asset,
            "max_repay": max_repay,
            "seized_collateral_shares": seized_collateral_shares,
            "swap_amount": swap_amount,
            "leftover_collateral": leftover_collateral,
            "swap_data_1inch": swap_data_1inch,
            "receiver": receiver
        })

        # Construct the full URL
        execution_url = f"{liquidation_ui_url}/liquidation/execute?{url_params}"


        message = (
            ":rotating_light: *Profitable Liquidation Opportunity Detected* :rotating_light:\n\n"
            f"*Account*: `{account_address}`, <{spy_link}|Spy Mode>\n"
            f"*Vault*: `{vault_address}`"
        )

        config = load_config()

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
            f"Time of detection: {time.strftime("%Y-%m-%d %H:%M:%S")}\n\n"
            f"Network: `{network_variables[config.CHAIN_ID]["name"]}`"
        )
        message += f"\n\n{formatted_data}"

    slack_payload = {
        "text": message,
        "username": "Liquidation Bot",
        "icon_emoji": ":robot_face:"
    }
    requests.post(slack_url, json=slack_payload, timeout=10)


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
    
    spy_link = get_spy_link(account_address)

    message = (
        ":moneybag: *Liquidation Completed* :moneybag:\n\n"
        f"*Liquidated Account*: `{account_address}`, <{spy_link}|Spy Mode>\n"
        f"*Vault*: `{vault_address}`"
    )

    config = load_config()

    tx_url = f"{network_variables[config.CHAIN_ID]["explorer_url"]}/tx/{tx_hash}"
    
    formatted_data = (
        f"*Liquidation Details:*\n"
        f"• Profit: {Web3.from_wei(liquidation_data["profit"], "ether")} ETH\n"
        f"• Collateral Vault Address: `{liquidation_data["collateral_address"]}`\n"
        f"• Collateral Asset: `{liquidation_data["collateral_asset"]}`\n"
        f"• Leftover Collateral: {Web3.from_wei(liquidation_data["leftover_collateral"], "ether")} {liquidation_data["collateral_asset"]}\n"
        f"• Leftover Collateral in ETH terms: {Web3.from_wei(liquidation_data["leftover_collateral_in_eth"], "ether")} ETH\n\n"
        f"• Transaction: <{tx_url}|View Transaction on Explorer>\n\n"
        f"Time of liquidation: {time.strftime("%Y-%m-%d %H:%M:%S")}\n\n"
        f"Network: `{network_variables[config.CHAIN_ID]["name"]}`"
    )
    message += f"\n\n{formatted_data}"

    slack_payload = {
        "text": message,
        "username": "Liquidation Bot",
        "icon_emoji": ":robot_face:"
    }
    requests.post(slack_url, json=slack_payload, timeout=10)

def post_low_health_account_report(sorted_accounts) -> None:
    """
    Post a report of accounts with low health scores to Slack.

    Args:
        sorted_accounts (List[Tuple[str, float]]): A list of tuples
        containing account addresses and their health scores,
        sorted by health score in ascending order.
    """
    load_dotenv()
    config = load_config()
    slack_url = os.getenv("SLACK_WEBHOOK_URL")

    # Filter accounts below the threshold
    low_health_accounts = [
        (address, score, value) for address, score, value in sorted_accounts
        if score < config.SLACK_REPORT_HEALTH_SCORE
    ]

    message = ":warning: *Account Health Report* :warning:\n\n"

    if not low_health_accounts:
        message += f"No accounts with health score below `{config.SLACK_REPORT_HEALTH_SCORE}` detected.\n"

    else:
        for i, (address, score, value) in enumerate(low_health_accounts, start=1):

            # Format score to 4 decimal places
            formatted_score = f"{score:.4f}"
            formatted_value = value / 10 ** 18
            formatted_value = f"{formatted_value:.2f}"

            spy_link = get_spy_link(address)

            message += f"{i}. `{address}` Health Score: `{formatted_score}`, Value Borrowed: `${formatted_value}`, <{spy_link}|Spy Mode>\n"

        message += f"\nTotal accounts with health score below {config.SLACK_REPORT_HEALTH_SCORE}: {len(low_health_accounts)}"

    message += f"\nTime of report: {time.strftime("%Y-%m-%d %H:%M:%S")}"
    message += f"\nNetwork: `{network_variables[config.CHAIN_ID]["name"]}`"

    slack_payload = {
        "text": message,
        "username": "Liquidation Bot",
        "icon_emoji": ":robot_face:"
    }

    try:
        response = requests.post(slack_url, json=slack_payload, timeout=10)
        response.raise_for_status()
        print("Low health account report posted to Slack successfully.")
    except requests.RequestException as e:
        print(f"Failed to post low health account report to Slack: {e}")

def post_error_notification(message) -> None:
    """
    Post an error notification to Slack.

    Args:
        message (str): The error message to be posted.
    """

    load_dotenv()
    config = load_config()
    slack_url = os.getenv("SLACK_WEBHOOK_URL")

    error_message = f":rotating_light: *Error Notification* :rotating_light:\n\n{message}\n\n"
    error_message += f"Time: {time.strftime("%Y-%m-%d %H:%M:%S")}\n"
    error_message += f"Network: `{network_variables[config.CHAIN_ID]["name"]}`"

    slack_payload = {
        "text": error_message,
        "username": "Liquidation Bot",
        "icon_emoji": ":warning:"
    }

    try:
        response = requests.post(slack_url, json=slack_payload, timeout=10)
        response.raise_for_status()
        print("Error notification posted to Slack successfully.")
    except requests.RequestException as e:
        print("Failed to post error notification to Slack: %s", e)

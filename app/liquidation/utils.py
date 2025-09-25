"""
Utility functions for the liquidation bot.
"""
import logging
import json
import functools
import time
import traceback
import requests

from typing import Any, Callable, Dict, Optional

from web3 import Web3
from web3.contract import Contract
from urllib.parse import urlencode

from .config_loader import ChainConfig

LOGS_PATH = "logs/account_monitor_logs.log"

def setup_logger() -> logging.Logger:
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
    file_handler = logging.FileHandler(LOGS_PATH, mode="a")

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

def create_contract_instance(address: str, abi_path: str, config: ChainConfig) -> Contract:
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

    return config.w3.eth.contract(address=address, abi=abi)

def retry_request(logger: logging.Logger,
                  max_retries: int = 3,
                  delay: int = 10) -> Callable:
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

def get_spy_link(account, config: ChainConfig):
    """
    Get account owner from EVC
    """
    owner = config.evc.functions.getAccountOwner(account).call()
    if owner == "0x0000000000000000000000000000000000000000":
        owner = account

    subaccount_number = int(int(account, 16) ^ int(owner, 16))

    spy_link = f"https://app.euler.finance/account/{subaccount_number}?spy={owner}&chainId={config.CHAIN_ID}"
    
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

def get_eth_usd_quote(amount: int = 10**18, config: ChainConfig = None):
    return config.eth_oracle.functions.getQuote(amount, config.MAINNET_ETH_ADDRESS, config.USD).call()

def get_btc_usd_quote(amount: int = 10**18, config: ChainConfig = None):
    return config.btc_oracle.functions.getQuote(amount, config.BTC, config.USD).call()


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
    trace_str = "".join(traceback.format_exception(exctype, value, tb))

    # Log the full exception information
    logger.critical("Uncaught exception:\n %s", trace_str)

def post_unhealthy_account_on_slack(account_address: str, vault_address: str,
                    health_score: float, value_borrowed: int, config: ChainConfig) -> None:
    """
    Post a message on Slack about an unhealthy account.
    """
    spy_link = get_spy_link(account_address, config)

    message = (
        ":warning: *Unhealthy Account Detected* :warning:\n\n"
        f"*Account*: `{account_address}`, <{spy_link}|Spy Mode>\n"
        f"*Vault*: `{vault_address}`\n"
        f"*Health Score*: `{health_score:.4f}`\n"
        f"*Value Borrowed*: `${value_borrowed / 10 ** 18:,.2f}`\n"
        f"Time of detection: {time.strftime("%Y-%m-%d %H:%M:%S")}\n"
        f"Network: `{config.CHAIN_NAME}`\n\n"
    )

    slack_payload = {
        "text": message,
        "username": "Liquidation Bot",
        "icon_emoji": ":robot_face:"
    }
    requests.post(config.SLACK_URL, json=slack_payload, timeout=10)


def post_liquidation_opportunity_on_slack(account_address: str, vault_address: str,
                  liquidation_data: Optional[Dict[str, Any]],
                  params: Optional[Dict[str, Any]], config: ChainConfig) -> None:
    """
    Post a message on Slack.
    
    Args:
        message (str): The main message to post.
        liquidation_data (Optional[Dict[str, Any]]): Additional liquidation data to format.
    """
    RISK_DASHBOARD_URL = config.RISK_DASHBOARD_URL

    if liquidation_data and params:

        # Unpack params
        violator_address, vault, borrowed_asset, collateral_vault, collateral_asset, \
        max_repay, seized_collateral_shares, receiver = params

        spy_link = get_spy_link(account_address, config)

        # Build URL parameters
        url_params = urlencode({
            "violator": violator_address,
            "vault": vault,
            "borrowed_asset": borrowed_asset,
            "collateral_vault": collateral_vault,
            "collateral_asset": collateral_asset,
            "max_repay": max_repay,
            "seized_collateral_shares": seized_collateral_shares,
            "receiver": receiver
        })

        # Construct the full URL
        execution_url = f"{RISK_DASHBOARD_URL}/liquidation/execute?{url_params}"


        message = (
            ":rotating_light: *Profitable Liquidation Opportunity Detected* :rotating_light:\n\n"
            f"*Account*: `{account_address}`, <{spy_link}|Spy Mode>\n"
            f"*Vault*: `{vault_address}`"
        )

        formatted_data = (
            f"*Liquidation Opportunity Details:*\n"
            f"• Profit: {Web3.from_wei(liquidation_data["profit"], "ether")} ETH\n"
            f"• Collateral Vault Address: `{liquidation_data["collateral_address"]}`\n"
            f"• Collateral Asset: `{liquidation_data["collateral_asset"]}`\n"
            f"• Leftover Borrow Asset: {Web3.from_wei(liquidation_data["leftover_borrow"],
                                                    "ether")}\n"
            f"• Leftover Borrow Asset in ETH terms (excluding gas): {Web3.from_wei(
                liquidation_data["leftover_borrow_in_eth"], "ether")} ETH\n\n"
            f"<{execution_url}|Click here to execute this liquidation manually>\n\n"
            f"Time of detection: {time.strftime("%Y-%m-%d %H:%M:%S")}\n\n"
            f"Network: `{config.CHAIN_NAME}`"
        )
        message += f"\n\n{formatted_data}"

    slack_payload = {
        "text": message,
        "username": "Liquidation Bot",
        "icon_emoji": ":robot_face:"
    }
    requests.post(config.SLACK_URL, json=slack_payload, timeout=10)


def post_liquidation_result_on_slack(account_address: str, vault_address: str,
                  liquidation_data: Optional[Dict[str, Any]],
                  tx_hash: Optional[str], config: ChainConfig) -> None:
    """
    Post a message on Slack.
    
    Args:
        message (str): The main message to post.
        liquidation_data (Optional[Dict[str, Any]]): Additional liquidation data to format.
    """
    
    spy_link = get_spy_link(account_address, config)

    message = (
        ":moneybag: *Liquidation Completed* :moneybag:\n\n"
        f"*Liquidated Account*: `{account_address}`, <{spy_link}|Spy Mode>\n"
        f"*Vault*: `{vault_address}`"
    )

    tx_url = f"{config.EXPLORER_URL}/tx/{tx_hash}"
    
    formatted_data = (
        f"*Liquidation Details:*\n"
        f"• Profit: {Web3.from_wei(liquidation_data["profit"], "ether")} ETH\n"
        f"• Collateral Vault Address: `{liquidation_data["collateral_address"]}`\n"
        f"• Collateral Asset: `{liquidation_data["collateral_asset"]}`\n"
        f"• Leftover Collateral: {Web3.from_wei(liquidation_data["leftover_borrow"], "ether")} {liquidation_data["collateral_asset"]}\n"
        f"• Leftover Collateral in ETH terms: {Web3.from_wei(liquidation_data["leftover_borrow_in_eth"], "ether")} ETH\n\n"
        f"• Transaction: <{tx_url}|View Transaction on Explorer>\n\n"
        f"Time of liquidation: {time.strftime("%Y-%m-%d %H:%M:%S")}\n\n"
        f"Network: `{config.CHAIN_NAME}`"
    )
    message += f"\n\n{formatted_data}"

    slack_payload = {
        "text": message,
        "username": "Liquidation Bot",
        "icon_emoji": ":robot_face:"
    }
    requests.post(config.SLACK_URL, json=slack_payload, timeout=10)

def post_low_health_account_report(sorted_accounts, config: ChainConfig) -> None:
    """
    Post a report of accounts with low health scores to Slack.

    Args:
        sorted_accounts (List[Tuple[str, float]]): A list of tuples
        containing account addresses and their health scores,
        sorted by health score in ascending order.
    """
    # Filter accounts below the threshold
    low_health_accounts = [
        (address, owner, subaccount, score, value, _, _) for address, owner, subaccount, score, value, _, _ in sorted_accounts
        if (score < config.SLACK_REPORT_HEALTH_SCORE and value > (config.BORROW_VALUE_THRESHOLD * 10**18)) or score < 1.0
    ]

    total_value = sum(value / 10**18 for _, _, _, _, value, _, _ in sorted_accounts)

    message = ":warning: *Account Health Report* :warning:\n\n"

    if not low_health_accounts:
        message += f"No accounts with health score below `{config.SLACK_REPORT_HEALTH_SCORE}` detected.\n"
    else:
        for i, (address, _, _, score, value, _, _) in enumerate(low_health_accounts, start=1):

            # Format score to 4 decimal places
            formatted_score = f"{score:.4f}"
            formatted_value = value / 10 ** 18

            formatted_value = f"{formatted_value:,.2f}"

            spy_link = get_spy_link(address, config)

            message += f"{i}. `{address}` Health Score: `{formatted_score}`, Value Borrowed: `${formatted_value}`, <{spy_link}|Spy Mode>\n"
            
            if i >= 50:
                break

        message += f"\nTotal accounts with health score below `{config.SLACK_REPORT_HEALTH_SCORE}` larger than `${config.BORROW_VALUE_THRESHOLD:,.2f}`: `{len(low_health_accounts)}`"
    message += f"\nTotal borrow amount in USD: `${total_value:,.2f}`"

    RISK_DASHBOARD_URL = config.RISK_DASHBOARD_URL
    message += f"\n<{RISK_DASHBOARD_URL}|Risk Dashboard>"
    message += f"\nTime of report: `{time.strftime("%Y-%m-%d %H:%M:%S")}`"
    message += f"\nNetwork: `{config.CHAIN_NAME}`"

    slack_payload = {
        "text": message,
        "username": "Liquidation Bot",
        "icon_emoji": ":robot_face:"
    }

    try:
        response = requests.post(config.SLACK_URL, json=slack_payload, timeout=10)
        response.raise_for_status()
        print("Low health account report posted to Slack successfully.")
    except requests.RequestException as e:
        print(f"Failed to post low health account report to Slack: {e}")

def post_error_notification(message, config: ChainConfig = None) -> None:
    """
    Post an error notification to Slack.

    Args:
        message (str): The error message to be posted.
    """

    error_message = f":rotating_light: *Error Notification* :rotating_light:\n\n{message}\n\n"
    error_message += f"Time: {time.strftime("%Y-%m-%d %H:%M:%S")}\n"
    if config:
        error_message += f"Network: `{config.CHAIN_NAME}`"

    slack_payload = {
        "text": error_message,
        "username": "Liquidation Bot",
        "icon_emoji": ":warning:"
    }

    try:
        response = requests.post(config.SLACK_URL, json=slack_payload, timeout=10)
        response.raise_for_status()
        print("Error notification posted to Slack successfully.")
    except requests.RequestException as e:
        print("Failed to post error notification to Slack: %s", e)

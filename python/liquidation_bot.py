"""
EVault Liquidation Bot
"""
import threading
import random
import time
import queue
import os
import json
import sys
import math

from concurrent.futures import ThreadPoolExecutor
from typing import Tuple, Dict, Any, Optional

from dotenv import load_dotenv
from web3 import Web3
# from eth_abi.abi import encode, decode
# from eth_utils import to_hex, keccak

from utils import setup_logger, setup_w3, create_contract_instance, make_api_request, global_exception_handler, post_liquidation_opportunity_on_slack, load_config, post_liquidation_result_on_slack, post_low_health_account_report

### ENVIRONMENT & CONFIG SETUP ###
load_dotenv()
API_KEY_1INCH = os.getenv("API_KEY_1INCH")
LIQUIDATOR_EOA_PUBLIC_KEY = os.getenv("LIQUIDATOR_ADDRESS")
LIQUIDATOR_EOA_PRIVATE_KEY = os.getenv("LIQUIDATOR_PRIVATE_KEY")

config = load_config()

logger = setup_logger(config.LOGS_PATH)
w3 = setup_w3()

sys.excepthook = global_exception_handler


### MAIN CODE ###

class Vault:
    """
    Represents a vault in the EVK System.
    This class provides methods to interact with a specific vault contract.
    This does not need to be serialized as it does not store any state
    """
    def __init__(self, address):
        self.address = address

        self.instance = create_contract_instance(address, config.EVAULT_ABI_PATH)

        self.underlying_asset_address = self.instance.functions.asset().call()

    def get_account_liquidity(self, account_address: str) -> Tuple[int, int]:
        """
        Get liquidity metrics for a given account.

        Args:
            account_address (str): The address of the account to check.

        Returns:
            Tuple[int, int]: A tuple containing (collateral_value, liability_value).
        """
        try:
            balance = self.instance.functions.balanceOf(
                Web3.to_checksum_address(account_address)).call()
        except Exception as ex: # pylint: disable=broad-except
            logger.error("Vault: Failed to get balance for account %s: %s",
                         account_address, ex, exc_info=True)
            return (0, 0, 0)

        try:
            (collateral_value, liability_value) = self.instance.functions.accountLiquidity(
                Web3.to_checksum_address(account_address),
                False
            ).call()
        except Exception as ex: # pylint: disable=broad-except
            logger.error("Vault: Failed to get account liquidity for account %s: %s",
                         account_address, ex, exc_info=True)
            return (balance, 0, 0)


        return (balance, collateral_value, liability_value)

    def check_liquidation(self,
                          borower_address: str,
                          collateral_address: str,
                          liquidator_address: str
                          ) -> Tuple[int, int]:
        """
        Call checkLiquidation on EVault for an account

        Args:
            borower_address (str): The address of the borrower.
            collateral_address (str): The address of the collateral asset.
            liquidator_address (str): The address of the potential liquidator.

        Returns:
            Tuple[int, int]: A tuple containing (max_repay, seized_collateral).
        """
        logger.info("Vault: Checking liquidation for account %s, collateral %s, liquidator %s",
                    borower_address, collateral_address, liquidator_address)
        (max_repay, seized_collateral) = self.instance.functions.checkLiquidation(
            Web3.to_checksum_address(liquidator_address),
            Web3.to_checksum_address(borower_address),
            Web3.to_checksum_address(collateral_address)
            ).call()
        return (max_repay, seized_collateral)

    def convert_to_assets(self, amount: int) -> int:
        """
        Convert an amount of vault shares to underlying assets.

        Args:
            amount (int): The amount of vault tokens to convert.

        Returns:
            int: The amount of underlying assets.
        """
        return self.instance.functions.convertToAssets(amount).call()

class Account:
    """
    Represents an account in the EVK System.
    This class provides methods to interact with a specific account and
    manages individual account data, including health scores,
    liquidation simulations, and scheduling of updates. It also provides
    methods for serialization and deserialization of account data.
    """
    def __init__(self, address, controller: Vault):
        self.address = address
        self.controller = controller
        self.time_of_next_update = time.time()
        self.current_health_score = math.inf
        self.balance = 0


    def update_liquidity(self) -> float:
        """
        Update account's liquidity & next scheduled update and return the current health score.

        Returns:
            float: The updated health score of the account.
        """
        self.get_health_score()
        self.get_time_of_next_update()

        return self.current_health_score


    def get_health_score(self) -> float:
        """
        Calculate and return the current health score of the account.

        Returns:
            float: The current health score of the account.
        """

        balance, collateral_value, liability_value = self.controller.get_account_liquidity(
            self.address)
        self.balance = balance

        # Special case for 0 values on balance or liability
        if liability_value == 0:
            self.current_health_score = math.inf
            return self.current_health_score


        self.current_health_score = collateral_value / liability_value

        logger.info("Account: Account %s health score: %s", self.address, self.current_health_score)
        return self.current_health_score

    def get_time_of_next_update(self) -> float:
        """
        Calculate the time of the next update for this account.

        Returns:
            float: The timestamp of the next scheduled update.
        """

        # If balance is 0, we set next update to a special value to remove it from the monitored set
        # We know there will need to be a status check prior to the account having a borrow again
        if self.current_health_score == math.inf:
            self.time_of_next_update = -1
            return self.time_of_next_update

        time_gap = 0

        # Simple linear interpolation between min and max
        # update intervals based on health score bounds
        if self.current_health_score < config.HS_LOWER_BOUND:
            time_gap = config.MIN_UPDATE_INTERVAL
        elif self.current_health_score > config.HS_UPPER_BOUND:
            time_gap = config.MAX_UPDATE_INTERVAL
        else:
            slope = config.MAX_UPDATE_INTERVAL - config.MIN_UPDATE_INTERVAL
            slope /= (config.HS_UPPER_BOUND - config.HS_LOWER_BOUND)
            intercept = config.MIN_UPDATE_INTERVAL - slope * config.HS_LOWER_BOUND
            time_gap = slope * self.current_health_score + intercept

        random_adjustment = random.random() / 5 + .9

        # Randomly adjust the time by +/-10% to avoid syncronized checks across accounts/deployments
        self.time_of_next_update = time.time() + time_gap * random_adjustment

        logger.info("Account: Account %s next update scheduled for %s", self.address,
                    time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(self.time_of_next_update)))
        return self.time_of_next_update


    def simulate_liquidation(self) -> Tuple[bool, Optional[Dict[str, Any]]]:
        """
        Simulate liquidation of this account to determine if it's profitable.

        Returns:
            Tuple[bool, Optional[Dict[str, Any]]]: A tuple containing a boolean indicating
            if liquidation is profitable, and a dictionary with liquidation details if profitable.
        """
        result = Liquidator.simulate_liquidation(self.controller, self.address)
        return result

    def to_dict(self) -> Dict[str, Any]:
        """
        Convert the account object to a dictionary representation.

        Returns:
            Dict[str, Any]: A dictionary representation of the account.
        """
        return {
            "address": self.address,
            "controller_address": self.controller.address,
            "time_of_next_update": self.time_of_next_update,
            "current_health_score": self.current_health_score
        }

    @staticmethod
    def from_dict(data: Dict[str, Any], vaults: Dict[str, Vault]) -> "Account":
        """
        Create an Account object from a dictionary representation.

        Args:
            data (Dict[str, Any]): The dictionary representation of the account.
            vaults (Dict[str, Vault]): A dictionary of available vaults.

        Returns:
            Account: An Account object created from the provided data.
        """
        controller = vaults.get(data["controller_address"])
        if not controller:
            controller = Vault(data["controller_address"])
            vaults[data["controller_address"]] = controller
        account = Account(address=data["address"], controller=controller)
        account.time_of_next_update = data["time_of_next_update"]
        account.current_health_score = data["current_health_score"]
        return account

class AccountMonitor:
    """
    Primary class for the liquidation bot system.

    This class is responsible for maintaining a list of accounts, scheduling
    updates, triggering liquidations, and managing the overall state of the
    monitored accounts. It also handles saving and loading the monitor's state.
    """
    def __init__(self, notify = False, execute_liquidation = False):
        self.accounts = {}
        self.vaults = {}
        self.update_queue = queue.PriorityQueue()
        self.condition = threading.Condition()
        self.executor = ThreadPoolExecutor(max_workers=32)
        self.running = True
        self.latest_block = 0
        self.last_saved_block = 0
        self.notify = notify
        self.execute_liquidation = execute_liquidation

    def start_queue_monitoring(self) -> None:
        """
        Start monitoring the account update queue.
        This is the main entry point for the account monitor.
        """
        save_thread = threading.Thread(target=self.periodic_save)
        save_thread.start()

        logger.info("AccountMonitor: Save thread started.")

        if self.notify:
            low_health_report_thread = threading.Thread(target=self.periodic_report_low_health_accounts)
            low_health_report_thread.start()
            logger.info("AccountMonitor: Low health report thread started.")

        while self.running:
            with self.condition:
                while self.update_queue.empty():
                    logger.info("AccountMonitor: Waiting for queue to be non-empty.")
                    self.condition.wait()

                next_update_time, address = self.update_queue.get()

                # check for special value that indicates
                # account should be skipped & removed from queue
                if next_update_time == -1:
                    logger.info("AccountMonitor: Account %s has no position,"
                                " skipping and removing from queue", address)
                    continue

                current_time = time.time()
                if next_update_time > current_time:
                    self.update_queue.put((next_update_time, address))
                    self.condition.wait(next_update_time - current_time)
                    continue

                self.executor.submit(self.update_account_liquidity, address)


    def update_account_on_status_check_event(self, address: str, vault_address: str) -> None:
        """
        Update an account based on a status check event.

        Args:
            address (str): The address of the account to update.
            vault_address (str): The address of the vault associated with the account.
        """

        # If the vault is not already tracked in the list, create it
        if vault_address not in self.vaults:
            self.vaults[vault_address] = Vault(vault_address)
            logger.info("AccountMonitor: Vault %s added to vault list.", vault_address)

        vault = self.vaults[vault_address]

        # If the account is not in the list or the controller has changed, add it to the list
        if (address not in self.accounts or
            self.accounts[address].controller.address != vault_address):
            account = Account(address, vault)
            self.accounts[address] = account

            logger.info("AccountMonitor: Adding account %s to account list with controller %s.",
                        address,
                        vault.address)
        else:
            #TODO: remove other update timings that aren't this one
            logger.info("AccountMonitor: Account %s already in list with controller %s.",
                        address,
                        vault.address)

        self.update_account_liquidity(address)

    def update_account_liquidity(self, address: str) -> None:
        """
        Update the liquidity of a specific account.

        Args:
            address (str): The address of the account to update.
        """
        try:
            account = self.accounts.get(address)

            if not account:
                logger.error("AccountMonitor: Account %s not found in account list.",
                             address, exc_info=True)
                return

            logger.info("AccountMonitor: Updating account %s liquidity.", address)

            health_score = account.update_liquidity()

            if health_score < 1:
                try:
                    logger.info("AccountMonitor: Account %s is unhealthy, "
                                "checking liquidation profitability.",
                                address)
                    (result, liquidation_data, params) = account.simulate_liquidation()

                    if result:
                        if self.notify:
                            try:
                                logger.info("AccountMonitor: Posting liquidation notification "
                                            "to slack for account %s.", address)
                                post_liquidation_opportunity_on_slack(address,
                                                                      account.controller.address,
                                                                      liquidation_data, params)
                            except Exception as ex: # pylint: disable=broad-except
                                logger.error("AccountMonitor: "
                                             "Failed to post liquidation notification "
                                             " for account %s to slack: %s",
                                             address, ex, exc_info=True)
                        if self.execute_liquidation:
                            try:
                                tx_hash = Liquidator.execute_liquidation(liquidation_data["tx"])
                                logger.info("AccountMonitor: Account %s liquidated "
                                            "on collateral %s.",
                                            address,
                                            liquidation_data["collateral_address"])
                                if self.notify:
                                    try:
                                        logger.info("AccountMonitor: Posting liquidation result "
                                                    "to slack for account %s.", address)
                                        post_liquidation_result_on_slack(address,
                                                                         account.controller.address,
                                                                         liquidation_data,
                                                                         tx_hash)
                                    except Exception as ex: # pylint: disable=broad-except
                                        logger.error("AccountMonitor: "
                                             "Failed to post liquidation result "
                                             " for account %s to slack: %s",
                                             address, ex, exc_info=True)

                                # Update account health score after liquidation
                                # Need to know how healthy the account is after liquidation
                                # and if we need to liquidate again
                                account.update_liquidity()
                            except Exception as ex: # pylint: disable=broad-except
                                logger.error("AccountMonitor: "
                                             "Failed to execute liquidation for account %s: %s",
                                             address, ex, exc_info=True)
                    else:
                        logger.info("AccountMonitor: "
                                    "Account %s is unhealthy but not profitable to liquidate.",
                                    address)
                        # TODO: add filter for small account/repeatedly seen accounts
                except Exception as ex: # pylint: disable=broad-except
                    logger.error("AccountMonitor: "
                                 "Exception simulating liquidation for account %s: %s",
                                 address, ex, exc_info=True)

            next_update_time = account.time_of_next_update

            with self.condition:
                self.update_queue.put((next_update_time, address))
                self.condition.notify()

        except Exception as ex: # pylint: disable=broad-except
            logger.error("AccountMonitor: Exception updating account %s: %s",
                         address, ex, exc_info=True)

    def save_state(self, local_save: bool = True) -> None:
        """
        Save the current state of the account monitor.

        Args:
            local_save (bool, optional): Whether to save the state locally. Defaults to True.
        """
        try:
            state = {
                "accounts": {address: account.to_dict()
                             for address, account in self.accounts.items()},
                "vaults": {address: vault.address for address, vault in self.vaults.items()},
                "queue": list(self.update_queue.queue),
                "last_saved_block": self.latest_block,
            }

            if local_save:
                with open(config.SAVE_STATE_PATH, "w", encoding="utf-8") as f:
                    json.dump(state, f)
            else:
                # Save to remote location
                pass

            self.last_saved_block = self.latest_block

            logger.info("AccountMonitor: State saved at time %s up to block %s",
                        time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),
                        self.latest_block)
        except Exception as ex: # pylint: disable=broad-except
            logger.error("AccountMonitor: Failed to save state: %s", ex, exc_info=True)

    def load_state(self, save_path: str, local_save: bool = True) -> None:
        """
        Load the state of the account monitor from a file.

        Args:
            save_path (str): The path to the saved state file.
            local_save (bool, optional): Whether the state is saved locally. Defaults to True.
        """
        try:
            if local_save and os.path.exists(save_path):
                with open(save_path, "r", encoding="utf-8") as f:
                    state = json.load(f)

                self.vaults = {address: Vault(address) for address in state["vaults"]}
                logger.info(f"Loaded {len(self.vaults)} vaults: {list(self.vaults.keys())}")

                self.accounts = {address: Account.from_dict(data, self.vaults)
                                 for address, data in state["accounts"].items()}
                logger.info(f"Loaded {len(self.accounts)} accounts:")

                for address, account in self.accounts.items():
                    logger.info(f"  Account {address}: Controller: {account.controller.address}, "
                                f"Health Score: {account.current_health_score}, "
                                f"Next Update: {time.strftime("%Y-%m-%d %H:%M:%S",
                                time.localtime(account.time_of_next_update))}")

                self.rebuild_queue()

                self.last_saved_block = state["last_saved_block"]
                self.latest_block = self.last_saved_block
                logger.info("AccountMonitor: State loaded from save"
                            " file %s from block %s to block %s",
                            save_path,
                            config.EVC_DEPLOYMENT_BLOCK,
                            self.latest_block)
            elif not local_save:
                # Load from remote location
                pass
            else:
                logger.info("AccountMonitor: No saved state found.")
        except Exception as ex: # pylint: disable=broad-except
            logger.error("AccountMonitor: Failed to load state: %s", ex, exc_info=True)

    def rebuild_queue(self):
        """
        Rebuild queue based on current account health
        """
        logger.info("Rebuilding queue based on current account health")

        self.update_queue = queue.PriorityQueue()
        for address, account in self.accounts.items():
            try:
                health_score = account.update_liquidity()

                if account.current_health_score == math.inf:
                    logger.info("AccountMonitor: Account %s has no borrow, skipping", address)
                    continue

                next_update_time = account.time_of_next_update
                self.update_queue.put((next_update_time, address))
                logger.info("AccountMonitor: Account %s added to queue"
                            " with health score %s, next update at %s",
                            address, health_score, time.strftime("%Y-%m-%d %H:%M:%S",
                                                                 time.localtime(next_update_time)))
            except Exception as ex: # pylint: disable=broad-except
                logger.error("AccountMonitor: Failed to put account %s into rebuilt queue: %s",
                             address, ex, exc_info=True)

        logger.info("AccountMonitor: Queue rebuilt with %s acccounts", self.update_queue.qsize())

    def get_accounts_by_health_score(self):
        """
        Get a list of accounts sorted by health score.

        Returns:
            List[Account]: A list of accounts sorted by health score.
        """
        sorted_accounts = sorted(
            self.accounts.values(),
            key = lambda account: account.current_health_score
        )

        return [(account.address, account.current_health_score) for account in sorted_accounts]

    def periodic_report_low_health_accounts(self):
        """
        Periodically report accounts with low health scores.
        """
        while self.running:
            sorted_accounts = self.get_accounts_by_health_score()
            post_low_health_account_report(sorted_accounts)
            time.sleep(config.LOW_HEALTH_REPORT_INTERVAL)

    @staticmethod
    def create_from_save_state(save_path: str, local_save: bool = True) -> "AccountMonitor":
        """
        Create an AccountMonitor instance from a saved state.

        Args:
            save_path (str): The path to the saved state file.
            local_save (bool, optional): Whether the state is saved locally. Defaults to True.

        Returns:
            AccountMonitor: An AccountMonitor instance initialized from the saved state.
        """
        monitor = AccountMonitor()
        monitor.load_state(save_path, local_save)
        return monitor

    def periodic_save(self) -> None:
        """
        Periodically save the state of the account monitor.
        Should be run in a standalone thread.
        """
        while self.running:
            time.sleep(config.SAVE_INTERVAL)
            self.save_state()

    def stop(self) -> None:
        """
        Stop the account monitor and save its current state.
        """
        self.running = False
        with self.condition:
            self.condition.notify_all()
        self.executor.shutdown(wait=True)
        self.save_state()

class PullOracleHandler:
    """
    Class to handle checking and updating pull based oracles.
    """
    def __init__(self):
        self.lens_address = Web3.to_checksum_address(config.ORACLE_LENS)
        self.minimal_abi = [
                {
                    "type": "function",
                    "name": "getOracleInfo",
                    "inputs": [
                    {
                        "name": "oracleAddress",
                        "type": "address",
                        "internalType": "address",
                    },
                    {
                        "name": "bases",
                        "type": "address[]",
                        "internalType": "address[]",
                    },
                    {
                        "name": "unitOfAccount",
                        "type": "address",
                        "internalType": "address",
                    },
                    ],
                    "outputs": [
                    {
                        "name": "",
                        "type": "tuple",
                        "internalType": "struct OracleDetailedInfo",
                        "components": [
                        {
                            "name": "name",
                            "type": "string",
                            "internalType": "string",
                        },
                        {
                            "name": "oracleInfo",
                            "type": "bytes",
                            "internalType": "bytes",
                        },
                        ],
                    },
                    ],
                    "stateMutability": "view",
                },
            ]

        self.instance = w3.eth.contract(address=self.lens_address, abi=self.minimal_abi)

    def get_oracle_info(self, oracle_address, bases, unit_of_account):
        try:
            result = self.instance.functions.getOracleInfo(
                oracle_address,
                bases,
                unit_of_account
            ).call()
            return result
        except Exception as ex: # pylint: disable=broad-except
            logger.error(f"Error calling contract: {ex}", exc_info=True)


class EVCListener:
    """
    Listener class for monitoring EVC events.
    Primarily intended to listen for AccountStatusCheck events.
    Contains handling for processing historical blocks in a batch system on startup.
    """
    def __init__(self, account_monitor: AccountMonitor):
        self.account_monitor = account_monitor

        self.evc_instance = create_contract_instance(config.EVC, config.EVC_ABI_PATH)

        self.scanned_blocks = set()

    def start_event_monitoring(self) -> None:
        """
        Start monitoring for EVC events.
        Scans from last scanned block stored by account monitor
        up to the current block number (minus 1 to try to account for reorgs).
        """
        while True:
            try:
                current_block = w3.eth.block_number - 1

                if self.account_monitor.latest_block < current_block:
                    self.scan_block_range_for_account_status_check(
                        self.account_monitor.latest_block,
                        current_block)
            except Exception as ex: # pylint: disable=broad-except
                logger.error("EVCListener: Unexpected exception in event monitoring: %s",
                             ex, exc_info=True)

            time.sleep(config.SCAN_INTERVAL)

    #pylint: disable=W0102
    def scan_block_range_for_account_status_check(self,
                                                  start_block: int,
                                                  end_block: int,
                                                  max_retries: int = config.NUM_RETRIES,
                                                  seen_accounts: set = set()) -> None:
        """
        Scan a range of blocks for AccountStatusCheck events.

        Args:
            start_block (int): The starting block number.
            end_block (int): The ending block number.
            max_retries (int, optional): Maximum number of retry attempts. 
                                        Defaults to config.NUM_RETRIES.
            
        """
        for attempt in range(max_retries):
            try:
                logger.info("EVCListener: Scanning blocks %s to %s for AccountStatusCheck events.",
                            start_block, end_block)

                logs = self.evc_instance.events.AccountStatusCheck().get_logs(
                    fromBlock=start_block,
                    toBlock=end_block)

                for log in logs:
                    vault_address = log["args"]["controller"]
                    account_address = log["args"]["account"]

                    #if we've seen the account already and the status
                    # check is not due to changing controller
                    if account_address in seen_accounts:
                        same_controller = self.account_monitor.accounts.get(
                            account_address).controller.address == Web3.to_checksum_address(
                                vault_address)

                        if same_controller:
                            logger.info("EVCListener: Account %s already seen with "
                                        "controller %s, skipping", account_address, vault_address)
                            continue
                    else:
                        seen_accounts.add(account_address)

                    logger.info("EVCListener: AccountStatusCheck event found for account %s "
                                "with controller %s, triggering monitor update.",
                                account_address, vault_address)

                    try:
                        self.account_monitor.update_account_on_status_check_event(
                            account_address,
                            vault_address)
                    except Exception as ex: # pylint: disable=broad-except
                        logger.error("EVCListener: Exception updating account %s "
                                     "on AccountStatusCheck event: %s",
                                     account_address, ex, exc_info=True)

                logger.info("EVCListener: Finished scanning blocks %s to %s "
                            "for AccountStatusCheck events.", start_block, end_block)

                self.account_monitor.latest_block = end_block
                return
            except Exception as ex: # pylint: disable=broad-except
                logger.error("EVCListener: Exception scanning block range %s to %s "
                             "(attempt %s/%s): %s",
                             start_block, end_block, attempt + 1, max_retries, ex, exc_info=True)
                if attempt == max_retries - 1:
                    logger.error("EVCListener: "
                                 "Failed to scan block range %s to %s after %s attempts",
                                 start_block, end_block, max_retries, exc_info=True)
                else:
                    time.sleep(config.RETRY_DELAY) # cooldown between retries


    def batch_account_logs_on_startup(self) -> None:
        """
        Batch process account logs on startup.
        Goes in reverse order to build smallest queue possible with most up to date info
        """
        try:
            # If the account monitor has a saved state,
            # assume it has been loaded from that and start from the last saved block
            start_block = max(int(config.EVC_DEPLOYMENT_BLOCK),
                              self.account_monitor.last_saved_block)

            current_block = w3.eth.block_number

            batch_block_size = config.BATCH_SIZE

            logger.info("EVCListener: "
                        "Starting batch scan of AccountStatusCheck events from block %s to %s.",
                        start_block, current_block)

            seen_accounts = set()

            while start_block < current_block:
                end_block = min(start_block + batch_block_size, current_block)

                self.scan_block_range_for_account_status_check(start_block, end_block,
                                                               seen_accounts=seen_accounts)
                self.account_monitor.save_state()

                start_block = end_block + 1

                time.sleep(config.BATCH_INTERVAL) # Sleep in between batches to avoid rate limiting

            logger.info("EVCListener: "
                        "Finished batch scan of AccountStatusCheck events from block %s to %s.",
                        start_block, current_block)

        except Exception as ex: # pylint: disable=broad-except
            logger.error("EVCListener: " 
                         "Unexpected exception in batch scanning account logs on startup: %s",
                         ex, exc_info=True)

# Future feature, smart monitor to trigger manual update of an account
# based on a large price change (or some other trigger)
class SmartUpdateListener:
    """
    Boiler plate listener class.
    Intended to be implemented with some other trigger condition to update accounts.
    """
    def __init__(self, account_monitor: AccountMonitor):
        self.account_monitor = account_monitor

    def trigger_manual_update(self, account: Account) -> None:
        """
        Boilerplate to trigger a manual update for a specific account.

        Args:
            account (Account): The account to update.
        """
        self.account_monitor.update_account_liquidity(account)

class Liquidator:
    """
    Class to handle liquidation logic for accounts
    This class provides static methods for simulating liquidations, calculating
    liquidation profits, and executing liquidation transactions. 
    """
    def __init__(self):
        pass

    @staticmethod
    def simulate_liquidation(vault: Vault,
                             violator_address: str) -> Tuple[bool, Optional[Dict[str, Any]]]:
        """
        Simulate the liquidation of an account.
        Chooses the maximum profitable liquidation from the available collaterals, if one exists.

        Args:
            vault (Vault): The vault associated with the account.
            violator_address (str): The address of the account to potentially liquidate.

        Returns:
            Tuple[bool, Optional[Dict[str, Any]]]: A tuple containing a boolean indicating
            if liquidation is profitable, and a dictionary with liquidation details 
            & transaction object if profitable.
        """

        evc_instance = create_contract_instance(config.EVC, config.EVC_ABI_PATH)
        collateral_list = evc_instance.functions.getCollaterals(violator_address).call()
        borrowed_asset = vault.underlying_asset_address
        liquidator_contract = create_contract_instance(config.LIQUIDATOR_CONTRACT,
                                                       config.LIQUIDATOR_ABI_PATH)

        max_profit_data = {
            "tx": None, 
            "profit": 0,
            "collateral_address": None,
            "collateral_asset": None,
            "leftover_collateral": 0, 
            "leftover_collateral_in_eth": 0
        }
        max_profit_params = None

        collateral_vaults = {collateral: Vault(collateral) for collateral in collateral_list}

        for collateral, collateral_vault in collateral_vaults.items():
            try:
                liquidation_results = Liquidator.calculate_liquidation_profit(vault,
                                                                      violator_address,
                                                                      borrowed_asset,
                                                                      collateral_vault,
                                                                      liquidator_contract)
                profit_data, params = liquidation_results

                if profit_data["profit"] > max_profit_data["profit"]:
                    max_profit_data = profit_data
                    max_profit_params = params
            except Exception as ex: # pylint: disable=broad-except
                logger.error("Liquidator: "
                             "Exception simulating liquidation "
                             "for account %s with collateral %s: %s",
                             violator_address, collateral, ex, exc_info=True)
                continue


        if max_profit_data["tx"]:
            logger.info("Liquidator: Profitable liquidation found for account %s. "
                        "Collateral: %s, Underlying Collateral Asset: %s, "
                        "Remaining collateral after swap and repay: %s, "
                        "Estimated profit in ETH: %s",
                        violator_address, max_profit_data["collateral_address"],
                        max_profit_data["collateral_asset"], max_profit_data["leftover_collateral"],
                        max_profit_data["leftover_collateral_in_eth"])
            return (True, max_profit_data, max_profit_params)
        return (False, None)

    @staticmethod
    def calculate_liquidation_profit(vault: Vault,
                                     violator_address: str,
                                     borrowed_asset: str,
                                     collateral_vault: Vault,
                                     liquidator_contract: Any) -> Dict[str, Any]:
        """
        Calculate the potential profit from liquidating an account using a specific collateral.

        Args:
            vault (Vault): The vault that violator has borrowed from.
            violator_address (str): The address of the account to potentially liquidate.
            borrowed_asset (str): The address of the borrowed asset.
            collateral_vault (Vault): The collatearl vault to seize. 
            liquidator_contract (Any): The liquidator contract instance.

        Returns:
            Dict[str, Any]: A dictionary containing transaction and liquidation profit details.
        """
        collateral_vault_address = collateral_vault.address
        collateral_asset = collateral_vault.underlying_asset_address

        (max_repay, seized_collateral_shares) = vault.check_liquidation(violator_address,
                                                                 collateral_vault_address,
                                                                 LIQUIDATOR_EOA_PUBLIC_KEY)

        seized_collateral_assets = vault.convert_to_assets(seized_collateral_shares)

        if max_repay == 0 or seized_collateral_shares == 0:
            return {"profit": 0}

        (swap_amount, _) = Quoter.get_1inch_quote(collateral_asset,
                                                  borrowed_asset,
                                                  seized_collateral_assets,
                                                  max_repay)

        estimated_slippage_needed = 2 # TODO: actual slippage calculation

        time.sleep(config.API_REQUEST_DELAY)

        swap_data_1inch = Quoter.get_1inch_swap_data(collateral_asset,
                                                     borrowed_asset,
                                                     swap_amount,
                                                     config.SWAPPER,
                                                     LIQUIDATOR_EOA_PUBLIC_KEY,
                                                    #  config.LIQUIDATOR_CONTRACT,
                                                     config.SWAPPER,
                                                     estimated_slippage_needed)

        leftover_collateral = seized_collateral_assets - swap_amount

        time.sleep(config.API_REQUEST_DELAY)

        # Convert leftover asset to WETH
        (_, leftover_collateral_in_eth) = Quoter.get_1inch_quote(collateral_asset,
                                                                 config.WETH,
                                                                 leftover_collateral, 0)
        time.sleep(config.API_REQUEST_DELAY)

        params = (
                violator_address,
                vault.address,
                borrowed_asset,
                collateral_vault.address,
                collateral_asset,
                max_repay,
                # seized_collateral_shares,
                0, #TODO change this back to seized_collateral_shares
                swap_amount,
                leftover_collateral,
                swap_data_1inch,
                config.PROFIT_RECEIVER
        )

        logger.info("Liquidator: Liquidation details: %s", params)

        #TODO: smarter way to do this
        suggested_gas_price = int(w3.eth.gas_price * 1.2)

        liquidation_tx = liquidator_contract.functions.liquidate_single_collateral(
            params
            ).build_transaction({
                "chainId": config.CHAIN_ID,
                "gasPrice": suggested_gas_price,
                "from": LIQUIDATOR_EOA_PUBLIC_KEY,
                "nonce": w3.eth.get_transaction_count(LIQUIDATOR_EOA_PUBLIC_KEY)
            })

        net_profit = leftover_collateral_in_eth - w3.eth.estimate_gas(liquidation_tx)

        return ({
            "tx": liquidation_tx, 
            "profit": net_profit, 
            "collateral_address": collateral_vault.address,
            "collateral_asset": collateral_asset,
            "leftover_collateral": leftover_collateral, 
            "leftover_collateral_in_eth": leftover_collateral_in_eth
        }, params)

    @staticmethod
    def execute_liquidation(liquidation_transaction: Dict[str, Any]) -> None:
        """
        Execute a liquidation transaction.

        Args:
            liquidation_transaction (Dict[str, Any]): The liquidation transaction details.
        """
        try:
            logger.info("Liquidator: Executing liquidation transaction %s...",
                        liquidation_transaction)
            signed_tx = w3.eth.account.sign_transaction(liquidation_transaction,
                                                        LIQUIDATOR_EOA_PRIVATE_KEY)
            tx_hash = w3.eth.send_raw_transaction(signed_tx.rawTransaction)
            tx_receipt = w3.eth.wait_for_transaction_receipt(tx_hash)

            liquidator_contract = create_contract_instance(config.LIQUIDATOR_CONTRACT,
                                                           config.LIQUIDATOR_ABI_PATH)

            result = liquidator_contract.events.Liquidation().process_receipt(tx_receipt)

            logger.info("Liquidator: Liquidation details: ")
            for event in result:
                logger.info("Liquidator: %s", event["args"])

            logger.info("Liquidator: Liquidation transaction executed successfully.")
            return tx_hash.hex()
        except Exception as ex: # pylint: disable=broad-except
            logger.error("Liquidator: Unexpected error in execute_liquidation %s",
                         ex, exc_info=True)

class Quoter:
    """
    Provides access to 1inch quotes and swap data generation functions
    """
    def __init__(self):
        pass

    @staticmethod
    def get_1inch_quote(asset_in: str,
                        asset_out: str,
                        amount_asset_in: int,
                        target_amount_out: int) -> Tuple[int, int]:
        """
        Get a quote from 1inch for swapping assets.
        If target_amount_out == 0, it is treated as an exact in swap.
        Otherwise, runs a binary search to find minimum amount in 
        that results in receiving target_amount_out.
        Returned actual amount out should always be >= target_amount_out.

        Args:
            asset_in (str): The address of the input asset.
            asset_out (str): The address of the output asset.
            amount_asset_in (int): The amount of input asset.
            target_amount_out (int): The target amount of output asset.

        Returns:
            Tuple[int, int]: A tuple containing (actual_amount_in, actual_amount_out).
        """
        def get_quote(params):
            """
            Simple wrapper to get a quote from 1inch.
            """
            api_url = f"https://api.1inch.dev/swap/v6.0/{config.CHAIN_ID}/quote"
            headers = { "Authorization": f"Bearer {API_KEY_1INCH}" }
            response = make_api_request(api_url, headers, params)
            return int(response["dstAmount"]) if response  else None

        params = {
            "src": asset_in,
            "dst": asset_out,
            "amount": amount_asset_in
        }

        try:
            # Special case exact in swap, don't need to do binary search
            if target_amount_out == 0:
                amount_out = get_quote(params)
                if amount_out is None:
                    return (0, 0)
                return (amount_asset_in, amount_out)

            # Binary search to find the amount in that will result in the target amount out
            # Overswaps slightly to make sure we can always repay max_repay
            min_amount_in, max_amount_in = 0, amount_asset_in
            delta = config.SWAP_DELTA

            iteration_count = 0

            last_valid_amount_in, last_valid_amount_out = 0, 0


            swap_amount = get_quote({"src": params["dst"], "dst": params["src"],
                                     "amount": target_amount_out})
            time.sleep(config.API_REQUEST_DELAY)

            min_amount_in = swap_amount * .95
            max_amount_in = swap_amount * 1.05

            amount_out = 0
            while iteration_count < config.MAX_SEARCH_ITERATIONS:
                swap_amount = int((min_amount_in + max_amount_in) / 2)
                params["amount"] = swap_amount
                amount_out = get_quote(params)

                if amount_out is None:
                    if last_valid_amount_out > target_amount_out:
                        logger.warning("Quoter: 1inch quote failed, using last valid "
                                       "quote: %s %s to %s %s",
                                       last_valid_amount_in, asset_in,
                                       last_valid_amount_out, asset_out)
                        return (last_valid_amount_in, last_valid_amount_out)
                    logger.warning("Quoter: Failed to get valid 1inch quote "
                                   "for %s %s to %s", swap_amount, asset_in, asset_out)
                    return (0, 0)

                logger.info("Quoter: 1inch quote for %s %s to %s: %s",
                            swap_amount, asset_in, asset_out, amount_out)

                if amount_out > target_amount_out:
                    last_valid_amount_in = swap_amount
                    last_valid_amount_out = amount_out

                if abs(amount_out - target_amount_out) < delta and amount_out > target_amount_out:
                    break
                elif amount_out < target_amount_out:
                    min_amount_in = swap_amount

                    # TODO: could probably be smarter, check this when we figure out smarter bounds
                    if max_amount_in - swap_amount < max_amount_in * 0.01:
                        max_amount_in = min(max_amount_in * 1.5, amount_asset_in)
                        logger.info("Quoter: Increasing max_amount_in to %s", max_amount_in)
                elif amount_out > target_amount_out:
                    max_amount_in = swap_amount

                iteration_count +=1

                # need to rate limit until getting enterprise account key
                time.sleep(config.API_REQUEST_DELAY)

            if iteration_count == config.MAX_SEARCH_ITERATIONS:
                logger.warning("Quoter: 1inch quote search for %s to %s "
                               "did not converge after %s iterations.",
                               asset_in, asset_out, config.MAX_SEARCH_ITERATIONS)
                if last_valid_amount_out > target_amount_out:
                    logger.info("Quoter: Using last valid quote: %s %s to %s %s",
                                last_valid_amount_in, asset_in, last_valid_amount_out, asset_out)
                    return (last_valid_amount_in, last_valid_amount_out)
                return (0, 0)

            return (params["amount"], amount_out)
        except Exception as ex: # pylint: disable=broad-except
            logger.error("Quoter: Unexpected error in get_1inch_quote %s", ex, exc_info=True)
            return (0, 0)

    @staticmethod
    def get_1inch_swap_data(asset_in: str,
                            asset_out: str,
                            amount_in: int,
                            swap_from: str,
                            tx_origin: str,
                            swap_receiver: str,
                            slippage: int = 2) -> Optional[str]:
        """
        Get swap data from 1inch for executing a swap.

        Args:
            asset_in (str): The address of the input asset.
            asset_out (str): The address of the output asset.
            amount_in (int): The amount of input asset.
            swap_from (str): The address to swap from.
            tx_origin (str): The origin of the transaction.
            slippage (int, optional): The allowed slippage percentage. Defaults to 2.

        Returns:
            Optional[str]: The swap data if successful, None otherwise.
        """

        params = {
            "src": asset_in,
            "dst": asset_out,
            "amount": amount_in,
            "from": swap_from,
            "origin": tx_origin,
            "slippage": slippage,
            "receiver": swap_receiver,
            "disableEstimate": "true"
        }

        logger.info("Getting 1inch swap data for %s %s %s %s %s %s %s",
                    amount_in, asset_in, asset_out, swap_from, tx_origin,
                    swap_receiver, slippage)

        api_url = f"https://api.1inch.dev/swap/v6.0/{config.CHAIN_ID}/swap"
        headers = { "Authorization": f"Bearer {API_KEY_1INCH}" }
        response = make_api_request(api_url, headers, params)

        return response["tx"]["data"] if response else None


if __name__ == "__main__":
    try:
        acct_monitor = AccountMonitor(True, True)
        acct_monitor.load_state(config.SAVE_STATE_PATH)

        evc_listener = EVCListener(acct_monitor)

        evc_listener.batch_account_logs_on_startup()

        threading.Thread(target=acct_monitor.start_queue_monitoring).start()
        threading.Thread(target=evc_listener.start_event_monitoring).start()

        while True:
            time.sleep(1)

        # router = "0xa15B7F02F57aaC6195271B41EfD3016a68Fc39A1"
        # router = "0x862b1042f653AE74880D0d3EBf0DDEe90aB8601D"
        # bases = ["0x0000000000000000000000000000000000000348",
        #          "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2"]
        # unit_of_account = "0x0000000000000000000000000000000000000348"

        # pull_oracle_handler = PullOracleHandler()
        # result = pull_oracle_handler.get_oracle_info(router, bases, unit_of_account)

        # print(result)


    except Exception as e: # pylint: disable=broad-except
        logger.critical("Uncaught exception: %s", e, exc_info=True)

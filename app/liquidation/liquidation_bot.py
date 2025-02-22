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
import subprocess

from concurrent.futures import ThreadPoolExecutor
from typing import Tuple, Dict, Any, Optional

from dotenv import load_dotenv
from web3 import Web3
from web3.logs import DISCARD
from eth_abi.abi import encode, decode
# from eth_abi.abi import encode, decode
# from eth_utils import to_hex, keccak

from app.liquidation.utils import (setup_logger,
                   setup_w3,
                   create_contract_instance,
                   make_api_request,
                   global_exception_handler,
                   post_liquidation_opportunity_on_slack,
                   load_config,
                   post_liquidation_result_on_slack,
                #    post_low_health_account_report,
                #    post_unhealthy_account_on_slack,
                #    post_error_notification,
                   get_eth_usd_quote,
                   get_btc_usd_quote)


## SETUP FOR MANUAL LIQUIDATION
UNDERWATER_ACCOUNT = Web3.to_checksum_address("0x02579637ae36b0b0Fdf96ad94925193728272DB7")
COLLATERAL_VAULT_ADDRESS = Web3.to_checksum_address("0x4c0AF5d6Bcb10B3C05FB5F3a846999a3d87534C7")
CONTROLLER_VAULT_ADDRESS = Web3.to_checksum_address("0x3D9e5462A940684073EED7e4a13d19AE0Dcd13bc")

### ENVIRONMENT & CONFIG SETUP ###
load_dotenv()
API_KEY_1INCH = os.getenv("API_KEY_1INCH")
LIQUIDATOR_EOA = os.getenv("LIQUIDATOR_EOA")
LIQUIDATOR_EOA_PRIVATE_KEY = os.getenv("LIQUIDATOR_PRIVATE_KEY")
SWAP_API_URL = os.getenv("SWAP_API_URL")

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
        self.vault_name = self.instance.functions.name().call()
        self.vault_symbol = self.instance.functions.symbol().call()

        self.unit_of_account = self.instance.functions.unitOfAccount().call()
        self.oracle_address = self.instance.functions.oracle().call()

        self.pyth_feed_ids = []
        self.redstone_feed_ids = []

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
            # Check if vault contains a Pyth oracle
            self.pyth_feed_ids, self.redstone_feed_ids = PullOracleHandler.get_feed_ids(self)

            if len(self.pyth_feed_ids) > 0 and len(self.redstone_feed_ids) > 0:
                logger.info("Vault: Pyth & Redstone oracle found for vault %s, "
                            "getting account liquidity through simulation", self.address)
                collateral_value, liability_value = PullOracleHandler.get_account_values_with_pyth_and_redstone_simulation(self, account_address, self.pyth_feed_ids, self.redstone_feed_ids)
            elif len(self.pyth_feed_ids) > 0:
                logger.info("Vault: Pyth Oracle found for vault %s, "
                            "getting account liquidity through simulation", self.address)
                collateral_value, liability_value = PullOracleHandler.get_account_values_with_pyth_batch_simulation(
                    self, account_address, self.pyth_feed_ids)
            elif len(self.redstone_feed_ids) > 0:
                logger.info("Vault: Redstone Oracle found for vault %s, "
                            "getting account liquidity through simulation", self.address)
                collateral_value, liability_value = PullOracleHandler.get_account_values_with_redstone_batch_simulation(
                    self, account_address, self.redstone_feed_ids)
            else:
                logger.info("Vault: Getting account liquidity normally for vault %s", self.address)
                (collateral_value, liability_value) = self.instance.functions.accountLiquidity(
                    Web3.to_checksum_address(account_address),
                    True
                ).call()
        except Exception as ex: # pylint: disable=broad-except
            if ex.args[0] != "0x43855d0f" and ex.args[0] != "0x6d588708":
                logger.error("Vault: Failed to get account liquidity"
                            " for account %s: Contract error - %s",
                            account_address, ex)
            return (balance, 100, 100)

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
        logger.info("Vault: Checking liquidation for account %s, collateral vault %s,"
                    " liquidator address %s, borrowed asset %s",
                    borower_address, collateral_address,
                    liquidator_address, self.underlying_asset_address)

        if len(self.pyth_feed_ids) > 0 and len(self.redstone_feed_ids) > 0:
            (max_repay, seized_collateral) = PullOracleHandler.check_liquidation_with_pyth_and_redstone_simulation(
                self,
                Web3.to_checksum_address(liquidator_address),
                Web3.to_checksum_address(borower_address),
                Web3.to_checksum_address(collateral_address),
                self.pyth_feed_ids,
                self.redstone_feed_ids
                )
        elif len(self.pyth_feed_ids) > 0:
            (max_repay, seized_collateral) = PullOracleHandler.check_liquidation_with_pyth_batch_simulation(
                self,
                Web3.to_checksum_address(liquidator_address),
                Web3.to_checksum_address(borower_address),
                Web3.to_checksum_address(collateral_address),
                self.pyth_feed_ids
                )
        elif len(self.redstone_feed_ids) > 0:
            (max_repay, seized_collateral) = PullOracleHandler.check_liquidation_with_redstone_batch_simulation(
                self,
                Web3.to_checksum_address(liquidator_address),
                Web3.to_checksum_address(borower_address),
                Web3.to_checksum_address(collateral_address),
                self.redstone_feed_ids
                )
        else:
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

    def get_ltv_list(self):
        """
        Return list of LTVs for this vault
        """
        return self.instance.functions.LTVList().call()

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
        self.owner, self.subaccount_number = EVCListener.get_account_owner_and_subaccount_number(self.address)
        self.controller = controller
        self.time_of_next_update = time.time()
        self.current_health_score = math.inf
        self.balance = 0
        self.value_borrowed = 0


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

        self.value_borrowed = liability_value
        if self.controller.unit_of_account == config.WETH:
            logger.info("Account: Getting a quote for %s WETH, unit of account %s",
                        liability_value, self.controller.unit_of_account)
            self.value_borrowed = get_eth_usd_quote(liability_value)

            logger.info("Account: value borrowed: %s", self.value_borrowed)
        elif self.controller.unit_of_account == config.BTC:
            logger.info("Account: Getting a quote for %s BTC, unit of account %s",
                        liability_value, self.controller.unit_of_account)
            self.value_borrowed = get_btc_usd_quote(liability_value)

            logger.info("Account: value borrowed: %s", self.value_borrowed)

        # Special case for 0 values on balance or liability
        if liability_value == 0:
            self.current_health_score = math.inf
            return self.current_health_score


        self.current_health_score = collateral_value / liability_value

        logger.info("Account: %s health score: %s, Collateral Value: %s,"
                    " Liability Value: %s", self.address, self.current_health_score,
                    collateral_value, liability_value)
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


        if self.current_health_score >= config.HS_SAFE:
            time_gap = config.MAX_UPDATE_INTERVAL
        elif config.HS_HIGH_RISK <= self.current_health_score < config.HS_SAFE:
            # Linear decrease from MAX_UPDATE_INTERVAL to HIGH_RISK_UPDATE_INTERVAL
            slope = (config.MAX_UPDATE_INTERVAL - config.HIGH_RISK_UPDATE_INTERVAL) / (config.HS_SAFE - config.HS_HIGH_RISK)
            time_gap = config.HIGH_RISK_UPDATE_INTERVAL + slope * (self.current_health_score - config.HS_HIGH_RISK)
        elif config.HS_LIQUIDATION < self.current_health_score < config.HS_HIGH_RISK:
            # Exponential decrease from HIGH_RISK_UPDATE_INTERVAL to MIN_UPDATE_INTERVAL
            exponent = (config.HS_HIGH_RISK - self.current_health_score) / (config.HS_HIGH_RISK - config.HS_LIQUIDATION)
            time_gap = config.MIN_UPDATE_INTERVAL + (config.HIGH_RISK_UPDATE_INTERVAL - config.MIN_UPDATE_INTERVAL) * math.exp(-5 * exponent)
        else:
            time_gap = config.MIN_UPDATE_INTERVAL


        # Randomly adjust the time by +/-10% to avoid syncronized checks across accounts/deployments
        time_of_next_update = time.time() + time_gap * random.uniform(0.9, 1.1)

        # if next update is already scheduled before calculated time and after now, keep it the same
        if not(self.time_of_next_update < time_of_next_update
               and self.time_of_next_update > time.time()):
            self.time_of_next_update = time_of_next_update

        logger.info("Account: %s next update scheduled for %s", self.address,
                    time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(self.time_of_next_update)))
        return self.time_of_next_update


    def simulate_liquidation(self) -> Tuple[bool, Optional[Dict[str, Any]]]:
        """
        Simulate liquidation of this account to determine if it's profitable.

        Returns:
            Tuple[bool, Optional[Dict[str, Any]]]: A tuple containing a boolean indicating
            if liquidation is profitable, and a dictionary with liquidation details if profitable.
        """
        result = Liquidator.simulate_liquidation(self.controller, self.address, self)
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
        self.recently_posted_low_value = {}

        # Add test account directly
        test_address = w3.to_checksum_address(UNDERWATER_ACCOUNT)

        # Add both vaults
        collateral_vault_address = w3.to_checksum_address(COLLATERAL_VAULT_ADDRESS)
        controller_vault_address = w3.to_checksum_address(CONTROLLER_VAULT_ADDRESS)
        
        # Create and store both vaults
        self.vaults[collateral_vault_address] = Vault(collateral_vault_address)
        self.vaults[controller_vault_address] = Vault(controller_vault_address)
        
        # Create and store the account with the controller vault
        test_account = Account(test_address, self.vaults[controller_vault_address])
        self.accounts[test_address] = test_account
        
        # Add to update queue
        self.update_queue.put((time.time(), test_address))

    def start_queue_monitoring(self) -> None:
        """
        Start monitoring the account update queue.
        This is the main entry point for the account monitor.
        """
        save_thread = threading.Thread(target=self.periodic_save)
        save_thread.start()

        logger.info("AccountMonitor: Save thread started.")

        if self.notify:
            low_health_report_thread = threading.Thread(target=
                                                        self.periodic_report_low_health_accounts)
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
                    logger.info("AccountMonitor: %s has no position,"
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

            logger.info("AccountMonitor: Adding %s to account list with controller %s.",
                        address,
                        vault.address)
        else:
            logger.info("AccountMonitor: %s already in list with controller %s.",
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
                logger.error("AccountMonitor: %s not found in account list.",
                             address, exc_info=True)
                return

            logger.info("AccountMonitor: Updating %s liquidity.", address)
            prev_scheduled_time = account.time_of_next_update

            health_score = account.update_liquidity()

            if health_score < 1:
                try:
                    if self.notify:
                        if account.address in self.recently_posted_low_value:
                            if (time.time() - self.recently_posted_low_value[account.address]
                                < config.LOW_HEALTH_REPORT_INTERVAL
                                and account.value_borrowed < config.SMALL_POSITION_THRESHOLD):
                                logger.info("Skipping posting notification "
                                            "for account %s, recently posted", address)
                        else:
                            try:
                                # post_unhealthy_account_on_slack(address, account.controller.address,
                                #                                 health_score,
                                #                                 account.value_borrowed)
                                logger.info("Valut borrowed: %s", account.value_borrowed)
                                if account.value_borrowed < config.SMALL_POSITION_THRESHOLD:
                                    self.recently_posted_low_value[account.address] = time.time()
                            except Exception as ex: # pylint: disable=broad-except
                                logger.error("AccountMonitor: "
                                             "Failed to post low health notification "
                                             "for account %s to slack: %s",
                                             address, ex, exc_info=True)

                    logger.info("AccountMonitor: %s is unhealthy, "
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
                                tx_hash, tx_receipt = Liquidator.execute_liquidation(
                                    liquidation_data["tx"])
                                if tx_hash and tx_receipt:
                                    logger.info("AccountMonitor: %s liquidated "
                                                "on collateral %s.",
                                                address,
                                                liquidation_data["collateral_address"])
                                    if self.notify:
                                        try:
                                            logger.info("AccountMonitor: Posting liquidation result"
                                                        " to slack for account %s.", address)
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
                except Exception as ex: # pylint: disable=broad-except
                    logger.error("AccountMonitor: "
                                 "Exception simulating liquidation for account %s: %s",
                                 address, ex, exc_info=True)

            next_update_time = account.time_of_next_update

            # if next update hasn't changed, means we already have a check scheduled
            if next_update_time == prev_scheduled_time:
                logger.info("AccountMonitor: %s next update already scheduled for %s",
                            address, time.strftime("%Y-%m-%d %H:%M:%S",
                                                  time.localtime(next_update_time)))
                return

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
                logger.info("Loaded %s vaults: %s", len(self.vaults), list(self.vaults.keys()))

                self.accounts = {address: Account.from_dict(data, self.vaults)
                                 for address, data in state["accounts"].items()}
                logger.info("Loaded %s accounts:", len(self.accounts))

                for address, account in self.accounts.items():
                    logger.info("  Account %s: Controller: %s, "
                                "Health Score: %s, "
                                "Next Update: %s",
                                address,
                                account.controller.address,
                                account.current_health_score,
                                time.strftime("%Y-%m-%d %H:%M:%S",
                                time.localtime(account.time_of_next_update)))

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
                    logger.info("AccountMonitor: %s has no borrow, skipping", address)
                    continue

                next_update_time = account.time_of_next_update
                self.update_queue.put((next_update_time, address))
                logger.info("AccountMonitor: %s added to queue"
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

        return [(account.address, account.owner, account.subaccount_number,
                 account.current_health_score, account.value_borrowed,
                 account.controller.vault_name, account.controller.vault_symbol)
                 for account in sorted_accounts]

    def periodic_report_low_health_accounts(self):
        """
        Periodically report accounts with low health scores.
        """
        while self.running:
            try:
                sorted_accounts = self.get_accounts_by_health_score()
                # post_low_health_account_report(sorted_accounts)
                time.sleep(config.LOW_HEALTH_REPORT_INTERVAL)
            except Exception as ex: # pylint: disable=broad-except
                logger.error("AccountMonitor: Failed to post low health account report: %s", ex,
                              exc_info=True)

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
    Class to handle checking and updating Pull oracles.
    """
    def __init__(self):
        pass

    @staticmethod
    def get_account_values_with_pyth_and_redstone_simulation(vault, account_address, pyth_feed_ids, redstone_feed_ids):
        pyth_update_data = PullOracleHandler.get_pyth_update_data(pyth_feed_ids)
        pyth_update_fee = PullOracleHandler.get_pyth_update_fee(pyth_update_data)

        redstone_addresses, redstone_update_data = PullOracleHandler.get_redstone_update_payloads(redstone_feed_ids)

        liquidator = create_contract_instance(config.LIQUIDATOR_CONTRACT,
                                              config.LIQUIDATOR_ABI_PATH)

        result = liquidator.functions.simulatePythAndRedstoneAccountStatus(
            [pyth_update_data], pyth_update_fee, redstone_update_data, redstone_addresses, vault.address, account_address
            ).call({
                "value": pyth_update_fee
            })
        return result[0], result[1]

    @staticmethod
    def check_liquidation_with_pyth_and_redstone_simulation(vault, liquidator_address, borrower_address, collateral_address, pyth_feed_ids, redstone_feed_ids):
        pyth_update_data = PullOracleHandler.get_pyth_update_data(pyth_feed_ids)
        pyth_update_fee = PullOracleHandler.get_pyth_update_fee(pyth_update_data)

        redstone_addresses, redstone_update_data = PullOracleHandler.get_redstone_update_payloads(redstone_feed_ids)

        liquidator = create_contract_instance(config.LIQUIDATOR_CONTRACT,
                                              config.LIQUIDATOR_ABI_PATH)

        result = liquidator.functions.simulatePythAndRedstoneLiquidation(
            [pyth_update_data], pyth_update_fee, redstone_update_data, redstone_addresses, vault.address, liquidator_address, borrower_address, collateral_address
            ).call({
                "value": pyth_update_fee
            })
        return result[0], result[1]

    @staticmethod
    def get_account_values_with_pyth_batch_simulation(vault, account_address, feed_ids):
        update_data = PullOracleHandler.get_pyth_update_data(feed_ids)
        update_fee = PullOracleHandler.get_pyth_update_fee(update_data)

        liquidator = create_contract_instance(config.LIQUIDATOR_CONTRACT,
                                              config.LIQUIDATOR_ABI_PATH)
        logger.info("here1")
        result = liquidator.functions.simulatePythUpdateAndGetAccountStatus(
            [update_data], update_fee, vault.address, account_address
            ).call({
                "value": update_fee
            })
        logger.info("here2")
        return result[0], result[1]

    @staticmethod
    def check_liquidation_with_pyth_batch_simulation(vault, liquidator_address, borrower_address,
                                                     collateral_address, feed_ids):
        update_data = PullOracleHandler.get_pyth_update_data(feed_ids)
        update_fee = PullOracleHandler.get_pyth_update_fee(update_data)

        liquidator = create_contract_instance(config.LIQUIDATOR_CONTRACT,
                                              config.LIQUIDATOR_ABI_PATH)

        result = liquidator.functions.simulatePythUpdateAndCheckLiquidation(
            [update_data], update_fee, vault.address,
            liquidator_address, borrower_address, collateral_address
            ).call({
                "value": update_fee
            })
        return result[0], result[1]

    @staticmethod
    def get_account_values_with_redstone_batch_simulation(vault, account_address, feed_ids):
        addresses, update_data = PullOracleHandler.get_redstone_update_payloads(feed_ids)

        liquidator = create_contract_instance(config.LIQUIDATOR_CONTRACT,
                                              config.LIQUIDATOR_ABI_PATH)

        result = liquidator.functions.simulateRedstoneUpdateAndGetAccountStatus(
            update_data, addresses, vault.address, account_address
            ).call()
        return result[0], result[1]

    @staticmethod
    def check_liquidation_with_redstone_batch_simulation(vault,
                                                         liquidator_address,
                                                         borrower_address,
                                                         collateral_address,
                                                         feed_ids):
        addresses, update_data = PullOracleHandler.get_redstone_update_payloads(feed_ids)

        liquidator = create_contract_instance(config.LIQUIDATOR_CONTRACT,
                                              config.LIQUIDATOR_ABI_PATH)

        result = liquidator.functions.simulateRedstoneUpdateAndCheckLiquidation(
            update_data, addresses, vault.address,
            liquidator_address, borrower_address, collateral_address
            ).call()
        return result[0], result[1]

    @staticmethod
    def get_feed_ids(vault):

        try:
            oracle_address = vault.oracle_address
            oracle = create_contract_instance(oracle_address, config.ORACLE_ABI_PATH)


            unit_of_account = vault.unit_of_account

            collateral_vault_list = vault.get_ltv_list()
            asset_list = [Vault(collateral_vault).underlying_asset_address
                          for collateral_vault in collateral_vault_list]
            asset_list.append(vault.underlying_asset_address)

            pyth_feed_ids = []
            redstone_feed_ids = []

            # logger.info("PullOracleHandler: Trying to get feed ids for oracle %s with assets %s and unit of account %s", oracle_address, collateral_vault_list, unit_of_account)

            for asset in asset_list:
                # configured_oracle_address = oracle.functions.getConfiguredOracle(asset,
                #                                                                  unit_of_account
                #                                                                  ).call()

                (_, _, _, configured_oracle_address) = oracle.functions.resolveOracle(0, asset, unit_of_account).call()

                configured_oracle = create_contract_instance(configured_oracle_address,
                                                             config.ORACLE_ABI_PATH)

                try:
                    configured_oracle_name = configured_oracle.functions.name().call()
                except Exception as ex: # pylint: disable=broad-except
                    logger.info("PullOracleHandler: Error calling contract for oracle"
                                " at %s, asset %s: %s", configured_oracle_address, asset, ex)
                    continue

                # logger.info("Asset: %s, Configured oracle name: %s, address: %s", asset, configured_oracle_name, configured_oracle_address)
                if configured_oracle_name == "PythOracle":
                    logger.info("PullOracleHandler: Pyth oracle found for vault %s: "
                                "Address - %s", vault.address, configured_oracle_address)
                    pyth_feed_ids.append(configured_oracle.functions.feedId().call().hex())
                elif configured_oracle_name == "RedstoneCoreOracle":
                    logger.info("PullOracleHandler: Redstone oracle found for"
                                " vault %s: Address - %s",
                                vault.address, configured_oracle_address)
                    redstone_feed_ids.append((configured_oracle_address,
                                              configured_oracle.functions.feedId().call().hex()))
                elif configured_oracle_name == "CrossAdapter":
                    pyth_ids, redstone_ids = PullOracleHandler.resolve_cross_oracle(
                        configured_oracle)
                    pyth_feed_ids += pyth_ids
                    redstone_feed_ids += redstone_ids

            return pyth_feed_ids, redstone_feed_ids

        except Exception as ex: # pylint: disable=broad-except
            logger.error("PullOracleHandler: Error calling contract: %s", ex, exc_info=True)

    @staticmethod
    def resolve_cross_oracle(cross_oracle):
        pyth_feed_ids = []
        redstone_feed_ids = []

        oracle_base_address = cross_oracle.functions.oracleBaseCross().call()
        oracle_base = create_contract_instance(oracle_base_address, config.ORACLE_ABI_PATH)
        oracle_base_name = oracle_base.functions.name().call()

        if oracle_base_name == "PythOracle":
            pyth_feed_ids.append(oracle_base.functions.feedId().call().hex())
        elif oracle_base_name == "RedstoneCoreOracle":
            redstone_feed_ids.append((oracle_base_address,
                                      oracle_base.functions.feedId().call().hex()))
        elif oracle_base_name == "CrossOracle":
            pyth_ids, redstone_ids = PullOracleHandler.resolve_cross_oracle(oracle_base)
            pyth_feed_ids.append(pyth_ids)
            redstone_feed_ids.append(redstone_ids)

        oracle_quote_address = cross_oracle.functions.oracleCrossQuote().call()
        oracle_quote = create_contract_instance(oracle_quote_address, config.ORACLE_ABI_PATH)
        oracle_quote_name = oracle_quote.functions.name().call()

        if oracle_quote_name == "PythOracle":
            pyth_feed_ids.append(oracle_quote.functions.feedId().call().hex())
        elif oracle_quote_name == "RedstoneCoreOracle":
            redstone_feed_ids.append((oracle_quote_address,
                                      oracle_quote.functions.feedId().call().hex()))
        elif oracle_quote_name == "CrossOracle":
            pyth_ids, redstone_ids = PullOracleHandler.resolve_cross_oracle(oracle_quote)
            pyth_feed_ids.append(pyth_ids)
            redstone_feed_ids.append(redstone_ids)

        return pyth_feed_ids, redstone_feed_ids

    @staticmethod
    def get_pyth_update_data(feed_ids):
        logger.info("PullOracleHandler: Getting update data for feeds: %s", feed_ids)
        pyth_url = "https://hermes.pyth.network/v2/updates/price/latest?"
        for feed_id in feed_ids:
            pyth_url += "ids[]=" + feed_id + "&"
        pyth_url = pyth_url[:-1]

        api_return_data = make_api_request(pyth_url, {}, {})
        return "0x" + api_return_data["binary"]["data"][0]

    @staticmethod
    def get_pyth_update_fee(update_data):
        logger.info("PullOracleHandler: Getting update fee for data: %s", update_data)
        pyth = create_contract_instance(config.PYTH, config.PYTH_ABI_PATH)
        return pyth.functions.getUpdateFee([update_data]).call()

    @staticmethod
    def get_redstone_update_payloads(redstone_oracle_data):
        addresses = []
        feed_ids = []

        for data in redstone_oracle_data:
            addresses.append(data[0])
            feed_ids.append(data[1])

        feed_ids_json = json.dumps(feed_ids)

        result = subprocess.run(
            ["node", "redstone_script/getRedstonePayload.js", feed_ids_json],
            capture_output=True,
            text=True,
            check=True
        )

        if result.returncode != 0:
            logger.error("PullOracleHandler: Error getting update payload")
            logger.error("stderr: %s", result.stderr)
            logger.error("stdout: %s", result.stdout)
            return None

        result = json.loads(result.stdout)

        output_data = []

        for i in range(len(result)):

            output_data.append(result[i]["data"])

        return addresses, output_data


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
        
        # Set latest block to current to skip historical scanning
        self.account_monitor.latest_block = w3.eth.block_number
        self.account_monitor.last_saved_block = self.account_monitor.latest_block

    def batch_account_logs_on_startup(self) -> None:
        """
        Skip batch processing for test purposes
        """
        logger.info("EVCListener: Skipping historical log scanning for test purposes")
        return

    def start_event_monitoring(self) -> None:
        """
        Modified to only monitor specific test address
        """
        while True:
            try:
                # Just update the test account periodically
                # self.account_monitor.update_account_liquidity(test_address)
                time.sleep(config.SCAN_INTERVAL)
            except Exception as ex:
                logger.error("EVCListener: Unexpected exception in event monitoring: %s",
                             ex, exc_info=True)

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


    @staticmethod
    def get_account_owner_and_subaccount_number(account):
        evc = create_contract_instance(config.EVC, config.EVC_ABI_PATH)
        owner = evc.functions.getAccountOwner(account).call()
        if owner == "0x0000000000000000000000000000000000000000":
            owner = account

        subaccount_number = int(int(account, 16) ^ int(owner, 16))
        return owner, subaccount_number

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

liquidation_error_slack_cooldown = {}

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
                             violator_address: str,
                             violator_account: Account) -> Tuple[bool, Optional[Dict[str, Any]]]:
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
            "leftover_borrow": 0, 
            "leftover_borrow_in_eth": 0
        }
        max_profit_params = None

        collateral_vaults = {collateral: Vault(collateral) for collateral in collateral_list}

        logger.info("Collateral vaults: %s", collateral_vaults)

        for collateral, collateral_vault in collateral_vaults.items():
            try:
                logger.info("Liquidator: Checking liquidation for "
                            "account %s, borrowed asset %s, collateral asset %s",
                            violator_address, borrowed_asset, collateral)

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
                message = ("Exception simulating liquidation "
                             f"for account {violator_address} with collateral {collateral}: {ex}")

                logger.error("Liquidator: %s", message, exc_info=True)

                time_of_last_post = liquidation_error_slack_cooldown.get(violator_address, 0)
                value_borrowed = violator_account.value_borrowed

                now = time.time()
                time_elapsed = now - time_of_last_post
                if ((value_borrowed > config.SMALL_POSITION_THRESHOLD and
                     time_elapsed > config.ERROR_COOLDOWN)
                    or (value_borrowed <= config.SMALL_POSITION_THRESHOLD and
                        time_elapsed > config.SMALL_POSITION_REPORT_INTERVAL)):
                    # post_error_notification(message)
                    time_of_last_post = now
                    liquidation_error_slack_cooldown[violator_address] = time_of_last_post
                continue


        if max_profit_data["tx"]:
            logger.info("Liquidator: Profitable liquidation found for account %s. "
                        "Collateral: %s, Underlying Collateral Asset: %s, "
                        "Remaining borrow asset after swap and repay: %s, "
                        "Estimated profit in ETH: %s",
                        violator_address, max_profit_data["collateral_address"],
                        max_profit_data["collateral_asset"], max_profit_data["leftover_borrow"],
                        max_profit_data["leftover_borrow_in_eth"])
            return (True, max_profit_data, max_profit_params)
        return (False, None, None)

    @staticmethod
    def calculate_liquidation_profit(vault: Vault,
                                     violator_address: str,
                                     borrowed_asset: str,
                                     collateral_vault: Vault,
                                     liquidator_contract: Any) -> Tuple[Dict[str, Any], Any]:
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
                                                                 LIQUIDATOR_EOA)

        seized_collateral_assets = collateral_vault.convert_to_assets(seized_collateral_shares)

        if max_repay == 0 or seized_collateral_shares == 0:
            logger.info("Liquidator: Max Repay %s, Seized Collateral %s, liquidation not possible",
                        max_repay, seized_collateral_shares)
            return ({"profit": 0}, None)
        
        swap_api_response = Quoter.get_swap_api_quote(
            chain_id = config.CHAIN_ID,
            token_in = collateral_asset,
            token_out = borrowed_asset,
            amount = int(seized_collateral_assets * .999),
            min_amount_out = max_repay,
            receiver = config.SWAPPER,
            vault_in = collateral_vault_address,
            account_in = config.SWAPPER,
            account_out = config.SWAPPER,
            swapper_mode = "0",
            slippage = config.SWAP_SLIPPAGE,
            deadline = int(time.time()) + config.SWAP_DEADLINE,
            is_repay = False,
            current_debt = max_repay,
            target_debt = 0
        )

        if not swap_api_response:
            return ({"profit": 0}, None)

        amount_out = int(swap_api_response['amountOut'])
        leftover_borrow = amount_out - max_repay
        leftover_borrow_in_eth = leftover_borrow

        # if borrowed_asset != config.WETH:
        #     borrow_to_eth_response = Quoter.get_swap_api_quote(
        #         chain_id = config.CHAIN_ID,
        #         token_in = borrowed_asset,
        #         token_out = config.WETH,
        #         amount = leftover_borrow,
        #         min_amount_out = 0,
        #         receiver = LIQUIDATOR_EOA,
        #         vault_in = vault.address,
        #         account_in = LIQUIDATOR_EOA,
        #         account_out = LIQUIDATOR_EOA,
        #         swapper_mode = "0",
        #         slippage = config.SWAP_SLIPPAGE,
        #         deadline = int(time.time()) + config.SWAP_DEADLINE,
        #         is_repay = False,
        #         current_debt = 0,
        #         target_debt = 0
        #     )
        #     leftover_borrow_in_eth = int(borrow_to_eth_response['amountOut'])
        # else:
        #     leftover_borrow_in_eth = leftover_borrow

        time.sleep(config.API_REQUEST_DELAY)

        swap_data = []
        for _, item in enumerate(swap_api_response['swap']['multicallItems']):
            # logger.info("Item: %s", item)
            if item['functionName'] != 'swap':
                # logger.info("Item skipped")
                continue
            swap_data.append(item['data'])

        logger.info("Liquidator: Seized collateral assets: %s, output amount: %s, "
                    "leftover_borrow: %s", seized_collateral_assets, amount_out,
                    leftover_borrow_in_eth)

        # if leftover_borrow_in_eth < 0:
        #     logger.warning("Liquidator: Negative leftover borrow value, aborting liquidation")
        #     return ({"profit": 0}, None)


        time.sleep(config.API_REQUEST_DELAY)

        params = (
                violator_address,
                vault.address,
                borrowed_asset,
                collateral_vault.address,
                collateral_asset,
                max_repay,
                seized_collateral_shares,
                config.PROFIT_RECEIVER
        )

        logger.info("Liquidator: Liquidation details: %s", params)
        logger.info("Multicall data: %s", swap_data)

        pyth_feed_ids = vault.pyth_feed_ids
        redstone_feed_ids = vault.redstone_feed_ids

        # #TODO: smarter way to do this
        # suggested_gas_price = int(w3.eth.gas_price * 1.2)

        # if len(feed_ids)> 0:
        #     logger.info("Liquidator: executing with pyth")
        #     update_data = PullOracleHandler.get_pyth_update_data(feed_ids)
        #     update_fee = PullOracleHandler.get_pyth_update_fee(update_data)
        #     liquidation_tx = liquidator_contract.functions.liquidateSingleCollateralWithPythOracle(
        #         params, update_data
        #         ).build_transaction({
        #             "chainId": config.CHAIN_ID,
        #             "gasPrice": suggested_gas_price,
        #             "from": LIQUIDATOR_EOA,
        #             "nonce": w3.eth.get_transaction_count(LIQUIDATOR_EOA),
        #             "value": update_fee
        #         })
        # else:
        #     logger.info("Liquidator: executing normally")
        #     liquidation_tx = liquidator_contract.functions.liquidateSingleCollateral(
        #         params
        #         ).build_transaction({
        #             "chainId": config.CHAIN_ID,
        #             "gasPrice": suggested_gas_price,
        #             "from": LIQUIDATOR_EOA,
        #             "nonce": w3.eth.get_transaction_count(LIQUIDATOR_EOA)
        #         })

        #From flashbots example code

        # latest = w3.eth.get_block("latest")
        # base_fee = latest["baseFeePerGas"]

        # max_priority_fee = Web3.to_wei(2, "gwei")

        # max_fee = base_fee + max_priority_fee

        suggested_gas_price = int(w3.eth.gas_price * 1.2)

        if len(pyth_feed_ids)> 0:
            logger.info("Liquidator: executing with pyth")
            update_data = PullOracleHandler.get_pyth_update_data(pyth_feed_ids)
            update_fee = PullOracleHandler.get_pyth_update_fee(update_data)
            function_signature = "liquidateSingleCollateralWithPythOracle((address,address,address,address,address,uint256,uint256,address),bytes[],bytes[])"

            # Convert hex strings to bytes for swap_data and update_data
            swap_data_bytes = [bytes.fromhex(data[2:]) if data.startswith('0x') else bytes.fromhex(data) for data in swap_data]
            update_data_bytes = bytes.fromhex(update_data[2:]) if update_data.startswith('0x') else bytes.fromhex(update_data)

            # Encode with the converted bytes
            encoded_params = encode(
                ["(address,address,address,address,address,uint256,uint256,address)", "bytes[]", "bytes[]"],
                [params, swap_data_bytes, [update_data_bytes]]
            )

            # Get the function selector
            function_selector = w3.keccak(text=function_signature)[:4]

            # Combine selector and encoded params
            calldata = function_selector + encoded_params

            # Print the calldata
            print("Call Data:")
            print(f"0x{calldata.hex()}")

            print(w3.eth.block_number)
            print("Update data")
            print(update_data)
            print("update fee: ", update_fee)

            liquidation_tx = liquidator_contract.functions.liquidateSingleCollateralWithPythOracle(
                params, swap_data, [update_data]
                ).build_transaction({
                    "chainId": config.CHAIN_ID,
                    "from": LIQUIDATOR_EOA,
                    "nonce": w3.eth.get_transaction_count(LIQUIDATOR_EOA),
                    "value": update_fee,
                    "gasPrice": suggested_gas_price
                })
        elif len(redstone_feed_ids) > 0:
            logger.info("Liquidator: executing with Redstone")
            addresses, update_data = PullOracleHandler.get_redstone_update_payloads(redstone_feed_ids)
            liquidation_tx = liquidator_contract.functions.liquidateSingleCollateralWithRedstoneOracle(
                params, swap_data, update_data, addresses
                ).build_transaction({
                    "chainId": config.CHAIN_ID,
                    "gasPrice": suggested_gas_price,
                    "from": LIQUIDATOR_EOA,
                    "nonce": w3.eth.get_transaction_count(LIQUIDATOR_EOA)
                })
        else:
            logger.info("Liquidator: executing normally")
            # liquidation_tx = liquidator_contract.functions.liquidateSingleCollateral(
            #     params
            #     ).build_transaction({
            #         "chainId": config.CHAIN_ID,
            #         "from": LIQUIDATOR_EOA,
            #         "nonce": w3.eth.get_transaction_count(LIQUIDATOR_EOA),
            #         "gas": 21000,
            #         "maxFeePerGas": max_fee,
            #         "maxPriorityFeePerGas": max_priority_fee
            #     })

            liquidation_tx = liquidator_contract.functions.liquidateSingleCollateral(
                params, swap_data
                ).build_transaction({
                    "chainId": config.CHAIN_ID,
                    "gasPrice": suggested_gas_price,
                    "from": LIQUIDATOR_EOA,
                    "nonce": w3.eth.get_transaction_count(LIQUIDATOR_EOA)
                })

        # net_profit = leftover_borrow_in_eth - (w3.eth.estimate_gas(liquidation_tx) * suggested_gas_price)
        net_profit = 1
        logger.info("Net profit: %s", net_profit)

        return ({
            "tx": liquidation_tx, 
            "profit": net_profit, 
            "collateral_address": collateral_vault.address,
            "collateral_asset": collateral_asset,
            "leftover_borrow": leftover_borrow, 
            "leftover_borrow_in_eth": leftover_borrow_in_eth
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
            # flashbots_provider = "https://rpc.flashbots.net"
            # flashbots_relay = "https://relay.flashbots.net"
            # flashbots_w3 = Web3(Web3.HTTPProvider(flashbots_provider))

            # signed_tx = flashbots_w3.eth.account.sign_transaction(liquidation_transaction,
            #                                             LIQUIDATOR_EOA_PRIVATE_KEY)
            # tx_hash = flashbots_w3.eth.send_raw_transaction(signed_tx.rawTransaction)
            # tx_receipt = flashbots_w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)

            signed_tx = w3.eth.account.sign_transaction(liquidation_transaction,
                                                        LIQUIDATOR_EOA_PRIVATE_KEY)
            tx_hash = w3.eth.send_raw_transaction(signed_tx.rawTransaction)
            tx_receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)

            liquidator_contract = create_contract_instance(config.LIQUIDATOR_CONTRACT,
                                                           config.LIQUIDATOR_ABI_PATH)

            result = liquidator_contract.events.Liquidation().process_receipt(tx_receipt, errors=DISCARD)

            logger.info("Liquidator: Liquidation details: ")
            for event in result:
                logger.info("Liquidator: %s", event["args"])

            logger.info("Liquidator: Liquidation transaction executed successfully.")
            return tx_hash.hex(), tx_receipt
        except Exception as ex: # pylint: disable=broad-except
            message = f"Unexpected error in executing liquidation: {ex}"
            logger.error(message, exc_info=True)
            # post_error_notification(message)
            return None, None

class Quoter:
    """
    Provides access to 1inch quotes and swap data generation functions
    """
    def __init__(self):
        pass

    @staticmethod
    def get_swap_api_quote(
        chain_id: int,
        token_in: str, 
        token_out: str,
        amount: int, # exact in - amount to sell, exact out - amount to buy, exact out repay - estimated amount to buy (from current debt)
        min_amount_out: int,
        receiver: str, # vault to swap or repay to
        vault_in: str,
        account_in: str,
        account_out: str,
        swapper_mode: str,
        slippage: float, #in percent 1 = 1%
        deadline: int,
        is_repay: bool,
        current_debt: int, # needed in exact input or output and with `isRepay` set
        target_debt: int # ignored if not in target debt mode
    ):

        params = {
            "chainId": str(chain_id),
            "tokenIn": token_in,
            "tokenOut": token_out, 
            "amount": str(amount),
            "receiver": receiver,
            "vaultIn": vault_in,
            "origin": LIQUIDATOR_EOA,
            "accountIn": account_in,
            "accountOut": account_out,
            "swapperMode": swapper_mode,  # TARGET_DEBT mode
            "slippage": str(slippage),
            "deadline": str(deadline), 
            "isRepay": str(is_repay),
            "currentDebt": str(current_debt),
            "targetDebt": str(target_debt)
        }

        response = make_api_request(SWAP_API_URL, headers={}, params=params)
        logger.info(response)
        if not response or not response["success"]:
            logger.error("Unable to get quote from swap api")
            return None
        
        amount_out = int(response["data"]["amountOut"])

        if amount_out < min_amount_out:
            logger.error("Quote too low")
            return None
        
        return response["data"]

    @staticmethod
    def get_quote(asset_in: str, asset_out: str,
                  amount_asset_in: int, target_amount_out: int,
                  swap_type: int = 1):
        if swap_type == 1: #1inch swap
            return Quoter.get_1inch_quote(asset_in, asset_out, amount_asset_in, target_amount_out)
        elif swap_type == 2: #Uniswap
            return Quoter.get_uniswap_quote(asset_in, asset_out, amount_asset_in, target_amount_out)

    @staticmethod
    def get_swap_data(asset_in: str,
                            asset_out: str,
                            amount_in: int,
                            swap_from: str,
                            tx_origin: str,
                            swap_receiver: str,
                            swap_type: int,
                            slippage: int = 2) -> Optional[str]:
        if swap_type == 1:
            return Quoter.get_1inch_swap_data(asset_in, asset_out, amount_in,
                                              swap_from, tx_origin, swap_receiver, slippage)
        elif swap_type == 2:
            return Quoter.get_uniswap_swap_data(asset_in, asset_out, amount_in,
                                                swap_from, tx_origin, swap_receiver, slippage)

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
        def get_api_quote(params):
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
                amount_out = get_api_quote(params)
                if amount_out is None:
                    return (-1, -1)
                return (amount_asset_in, amount_out)

            # Binary search to find the amount in that will result in the target amount out
            # Overswaps slightly to make sure we can always repay max_repay
            min_amount_in, max_amount_in = 0, amount_asset_in

            # Allow for overswap of SWAP_DELTA percent of target amount
            delta = config.SWAP_DELTA * target_amount_out

            iteration_count = 0

            last_valid_amount_in, last_valid_amount_out = 0, 0

            logger.info("Quoter: Initial request for src %s to dst %s and amount %s",
                        params["dst"], params["src"], target_amount_out)
            swap_amount = get_api_quote({"src": params["dst"], "dst": params["src"],
                                     "amount": target_amount_out})

            logger.info("Quoter: Initial guess for 1inch quote to get %s %s out from %s in: %s",
                        target_amount_out, asset_out, asset_in, swap_amount)
            time.sleep(config.API_REQUEST_DELAY)

            min_amount_in = swap_amount * .95
            max_amount_in = swap_amount * 1.05

            amount_out = 0
            while iteration_count < config.MAX_SEARCH_ITERATIONS:
                swap_amount = int((min_amount_in + max_amount_in) / 2)
                params["amount"] = swap_amount
                amount_out = get_api_quote(params)

                if amount_out is None:
                    if last_valid_amount_out > target_amount_out:
                        logger.warning("Quoter: 1inch quote failed, using last valid "
                                       "quote: %s %s to %s %s",
                                       last_valid_amount_in, asset_in,
                                       last_valid_amount_out, asset_out)
                        return (last_valid_amount_in, last_valid_amount_out)
                    logger.warning("Quoter: Failed to get valid 1inch quote "
                                   "for %s %s to %s", swap_amount, asset_in, asset_out)
                    return (-1, -1)

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
                return (-1, -1)

            return (params["amount"], amount_out)
        except Exception as ex: # pylint: disable=broad-except
            logger.error("Quoter: Unexpected error in get_1inch_quote %s", ex, exc_info=True)
            return (-1, -1)

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
        logger.info("Params: %s", params)

        api_url = f"https://api.1inch.dev/swap/v6.0/{config.CHAIN_ID}/swap"
        headers = { "Authorization": f"Bearer {API_KEY_1INCH}" }
        response = make_api_request(api_url, headers, params)

        return response["tx"]["data"] if response else None

    @staticmethod
    def get_uniswap_quote(asset_in: str, asset_out: str,
                  amount_asset_in: int, target_amount_out: int):
        logger.info("Quoter: Requesting Uniswap quote for %s %s to %s (target out: %s)",
                    amount_asset_in, asset_in, asset_out, target_amount_out)
        return (0, 0)

    @staticmethod
    def get_uniswap_swap_data(asset_in: str,
                            asset_out: str,
                            amount_in: int,
                            swap_from: str,
                            tx_origin: str,
                            swap_receiver: str,
                            slippage: int = 2) -> Optional[str]:
        logger.info("Quoter: Requesting Uniswap swap data for"
                    " %s %s to %s, from %s, origin %s, receiver %s, slippage %s%%",
                    amount_in, asset_in, asset_out, swap_from, tx_origin, swap_receiver, slippage)
        return None

def get_account_monitor_and_evc_listener():
    acct_monitor = AccountMonitor(True, True)
    acct_monitor.load_state(config.SAVE_STATE_PATH)

    evc_listener = EVCListener(acct_monitor)

    return (acct_monitor, evc_listener)

if __name__ == "__main__":
    try:
        pass

    except Exception as e: # pylint: disable=broad-except
        logger.critical("Uncaught exception: %s", e, exc_info=True)
        error_message = f"Uncaught global exception: {e}"
        # post_error_notification(error_message)

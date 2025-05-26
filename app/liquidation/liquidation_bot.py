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

from web3 import Web3
from web3.logs import DISCARD

from app.liquidation.utils import (setup_logger,
                   create_contract_instance,
                   make_api_request,
                   global_exception_handler,
                   post_liquidation_opportunity_on_slack,
                   post_liquidation_result_on_slack,
                   post_low_health_account_report,
                   post_unhealthy_account_on_slack,
                   post_error_notification,
                   get_eth_usd_quote,
                   get_btc_usd_quote)

from app.liquidation.config_loader import ChainConfig

### ENVIRONMENT & CONFIG SETUP ###
logger = setup_logger()
sys.excepthook = global_exception_handler


### MAIN CODE ###

class Vault:
    """
    Represents a vault in the EVK System.
    This class provides methods to interact with a specific vault contract.
    This does not need to be serialized as it does not store any state
    """
    def __init__(self, address, config: ChainConfig):
        self.config = config
        
        self.address = address
        self.instance = create_contract_instance(address, self.config.EVAULT_ABI_PATH, self.config)

        self.underlying_asset_address = self.instance.functions.asset().call()
        self.vault_name = self.instance.functions.name().call()
        self.vault_symbol = self.instance.functions.symbol().call()

        self.unit_of_account = self.instance.functions.unitOfAccount().call()
        self.oracle_address = self.instance.functions.oracle().call()

        self.pyth_feed_ids = []
        self.last_pyth_feed_ids_update = 0

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
            if time.time() - self.last_pyth_feed_ids_update > self.config.PYTH_CACHE_REFRESH:
                self.pyth_feed_ids = PullOracleHandler.get_feed_ids(self, self.config)
                self.last_pyth_feed_ids_update = time.time()
            if len(self.pyth_feed_ids) > 0:
                logger.info("Vault: Pyth Oracle found for vault %s, "
                            "getting account liquidity through simulation", self.address)
                collateral_value, liability_value = PullOracleHandler.get_account_values_with_pyth_batch_simulation(
                    self, account_address, self.pyth_feed_ids, self.config)
            else:
                logger.info("Vault: Getting account liquidity normally for address %s in vault %s", account_address, self.address)
                (collateral_value, liability_value) = self.instance.functions.accountLiquidity(
                    Web3.to_checksum_address(account_address),
                    True
                ).call()
        except Exception as ex: # pylint: disable=broad-except
            if ex.args[0] != "0x43855d0f" and ex.args[0] != "0x6d588708":
                logger.error("Vault: Failed to get account liquidity"
                            " for account %s: Contract error - %s",
                            account_address, ex)
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
        logger.info("Vault: Checking liquidation for account %s, collateral vault %s,"
                    " liquidator address %s, borrowed asset %s",
                    borower_address, collateral_address,
                    liquidator_address, self.underlying_asset_address)

        if len(self.pyth_feed_ids) > 0:
            (max_repay, seized_collateral) = PullOracleHandler.check_liquidation_with_pyth_batch_simulation(
                self,
                Web3.to_checksum_address(liquidator_address),
                Web3.to_checksum_address(borower_address),
                Web3.to_checksum_address(collateral_address),
                self.pyth_feed_ids,
                self.config
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
    def __init__(self, address, controller: Vault, config: ChainConfig):
        self.config = config
        self.address = address
        self.owner, self.subaccount_number = EVCListener.get_account_owner_and_subaccount_number(self.address, config)
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
        if self.controller.unit_of_account == self.config.WETH:
            logger.info("Account: Getting a quote for %s WETH, unit of account %s",
                        liability_value, self.controller.unit_of_account)
            self.value_borrowed = get_eth_usd_quote(liability_value, self.config)

            logger.info("Account: value borrowed: %s", self.value_borrowed)
        elif self.controller.unit_of_account == self.config.BTC:
            logger.info("Account: Getting a quote for %s BTC, unit of account %s",
                        liability_value, self.controller.unit_of_account)
            self.value_borrowed = get_btc_usd_quote(liability_value, self.config)

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
        Calculate the time of the next update for this account based on size and health score.

        Returns:
            float: The timestamp of the next scheduled update.
        """
        # Special case for infinite health score
        if self.current_health_score == math.inf:
            self.time_of_next_update = -1
            return self.time_of_next_update

        # Determine size category
        if self.value_borrowed < self.config.TEENY:
            size_prefix = "TEENY"
        elif self.value_borrowed < self.config.MINI:
            size_prefix = "MINI"
        elif self.value_borrowed < self.config.SMALL:
            size_prefix = "SMALL"
        elif self.value_borrowed < self.config.MEDIUM:
            size_prefix = "MEDIUM"
        else:
            size_prefix = "LARGE"  # For anything >= MEDIUM

        # Get the appropriate time values based on size
        liq_time = getattr(self.config, f"{size_prefix}_LIQ")
        high_risk_time = getattr(self.config, f"{size_prefix}_HIGH")
        safe_time = getattr(self.config, f"{size_prefix}_SAFE")

        # Calculate time gap based on health score
        if self.current_health_score < self.config.HS_LIQUIDATION:
            time_gap = liq_time
        elif self.current_health_score < self.config.HS_HIGH_RISK:
            # Linear interpolation between liq and high_risk times
            ratio = (self.current_health_score - self.config.HS_LIQUIDATION) / (self.config.HS_HIGH_RISK - self.config.HS_LIQUIDATION)
            time_gap = liq_time + (high_risk_time - liq_time) * ratio
        elif self.current_health_score < self.config.HS_SAFE:
            # Linear interpolation between high_risk and safe times
            ratio = (self.current_health_score - self.config.HS_HIGH_RISK) / (self.config.HS_SAFE - self.config.HS_HIGH_RISK)
            time_gap = high_risk_time + (safe_time - high_risk_time) * ratio
        else:
            time_gap = safe_time

        # Randomly adjust time by ±10% to avoid synchronized checks
        time_of_next_update = time.time() + time_gap * random.uniform(0.9, 1.1)

        # Keep existing next update if it's already scheduled between now and calculated time
        if not(self.time_of_next_update < time_of_next_update and self.time_of_next_update > time.time()):
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
        result = Liquidator.simulate_liquidation(self.controller, self.address, self, self.config)
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
    def from_dict(data: Dict[str, Any], vaults: Dict[str, Vault], config: ChainConfig) -> "Account":
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
            controller = Vault(data["controller_address"], config)
            vaults[data["controller_address"]] = controller
        account = Account(address=data["address"], controller=controller, config=config)
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
    def __init__(self, chain_id: int, config: ChainConfig, notify = False, execute_liquidation = False):
        self.chain_id = chain_id
        self.w3 = config.w3,
        self.config = config
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
            self.vaults[vault_address] = Vault(vault_address, self.config)
            logger.info("AccountMonitor: Vault %s added to vault list.", vault_address)

        vault = self.vaults[vault_address]

        # If the account is not in the list or the controller has changed, add it to the list
        if (address not in self.accounts or
            self.accounts[address].controller.address != vault_address):
            account = Account(address, vault, self.config)
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
                                < self.config.LOW_HEALTH_REPORT_INTERVAL
                                and account.value_borrowed < self.config.SMALL_POSITION_THRESHOLD):
                                logger.info("Skipping posting notification "
                                            "for account %s, recently posted", address)
                        else:
                            try:
                                post_unhealthy_account_on_slack(address, account.controller.address,
                                                                health_score,
                                                                account.value_borrowed, self.config)
                                logger.info("Valut borrowed: %s", account.value_borrowed)
                                if account.value_borrowed < self.config.SMALL_POSITION_THRESHOLD:
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
                                                                      liquidation_data, params, self.config)
                            except Exception as ex: # pylint: disable=broad-except
                                logger.error("AccountMonitor: "
                                             "Failed to post liquidation notification "
                                             " for account %s to slack: %s",
                                             address, ex, exc_info=True)
                        if self.execute_liquidation:
                            try:
                                tx_hash, tx_receipt = Liquidator.execute_liquidation(
                                    liquidation_data["tx"], self.config)
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
                                                                            tx_hash, self.config)
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
                with open(self.config.SAVE_STATE_PATH, "w", encoding="utf-8") as f:
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
                print(save_path)
                with open(save_path, "r", encoding="utf-8") as f:
                    state = json.load(f)

                self.vaults = {address: Vault(address, self.config) for address in state["vaults"]}
                logger.info("Loaded %s vaults: %s", len(self.vaults), list(self.vaults.keys()))

                self.accounts = {address: Account.from_dict(data, self.vaults, self.config)
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
                            self.config.EVC_DEPLOYMENT_BLOCK,
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
                post_low_health_account_report(sorted_accounts, self.config)
                time.sleep(self.config.LOW_HEALTH_REPORT_INTERVAL)
            except Exception as ex: # pylint: disable=broad-except
                logger.error("AccountMonitor: Failed to post low health account report: %s", ex,
                              exc_info=True)

    @staticmethod
    def create_from_save_state(chain_id: int, config: ChainConfig, save_path: str, local_save: bool = True) -> "AccountMonitor":
        """
        Create an AccountMonitor instance from a saved state.

        Args:
            save_path (str): The path to the saved state file.
            local_save (bool, optional): Whether the state is saved locally. Defaults to True.

        Returns:
            AccountMonitor: An AccountMonitor instance initialized from the saved state.
        """
        monitor = AccountMonitor(chain_id=chain_id, config=config)
        monitor.load_state(save_path, local_save)
        return monitor

    def periodic_save(self) -> None:
        """
        Periodically save the state of the account monitor.
        Should be run in a standalone thread.
        """
        while self.running:
            time.sleep(self.config.SAVE_INTERVAL)
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
    def get_account_values_with_pyth_batch_simulation(vault, account_address, feed_ids, config: ChainConfig):
        update_data = PullOracleHandler.get_pyth_update_data(feed_ids)
        update_fee = PullOracleHandler.get_pyth_update_fee(update_data, config)

        liquidator = config.liquidator

        result = liquidator.functions.simulatePythUpdateAndGetAccountStatus(
            [update_data], update_fee, vault.address, account_address
            ).call({
                "value": update_fee
            })
        return result[0], result[1]

    @staticmethod
    def check_liquidation_with_pyth_batch_simulation(vault, liquidator_address, borrower_address,
                                                     collateral_address, feed_ids, config: ChainConfig):
        update_data = PullOracleHandler.get_pyth_update_data(feed_ids)
        update_fee = PullOracleHandler.get_pyth_update_fee(update_data, config)

        liquidator = config.liquidator

        result = liquidator.functions.simulatePythUpdateAndCheckLiquidation(
            [update_data], update_fee, vault.address,
            liquidator_address, borrower_address, collateral_address
            ).call({
                "value": update_fee
            })
        return result[0], result[1]



    @staticmethod
    def get_feed_ids(vault, config: ChainConfig):
        try:
            oracle_address = vault.oracle_address
            oracle = create_contract_instance(oracle_address, config.ORACLE_ABI_PATH, config)

            unit_of_account = vault.unit_of_account

            collateral_vault_list = vault.get_ltv_list()
            asset_list = [Vault(collateral_vault, config).underlying_asset_address
                          for collateral_vault in collateral_vault_list]
            asset_list.append(vault.underlying_asset_address)

            pyth_feed_ids = set()

            for asset in asset_list:
                (_, _, _, configured_oracle_address) = oracle.functions.resolveOracle(0, asset, unit_of_account).call()

                configured_oracle = create_contract_instance(configured_oracle_address,
                                                             config.ORACLE_ABI_PATH, config)

                try:
                    configured_oracle_name = configured_oracle.functions.name().call()
                except Exception as ex: # pylint: disable=broad-except
                    logger.info("PullOracleHandler: Error calling contract for oracle"
                                " at %s, asset %s: %s", configured_oracle_address, asset, ex)
                    continue
                if configured_oracle_name == "PythOracle":
                    logger.info("PullOracleHandler: Pyth oracle found for vault %s: "
                                "Address - %s", vault.address, configured_oracle_address)
                    pyth_feed_ids.add(configured_oracle.functions.feedId().call().hex())
                elif configured_oracle_name == "CrossAdapter":
                    pyth_ids = PullOracleHandler.resolve_cross_oracle(
                        configured_oracle, config)
                    pyth_feed_ids.update(pyth_ids)

            return list(pyth_feed_ids)

        except Exception as ex: # pylint: disable=broad-except
            logger.error("PullOracleHandler: Error calling contract: %s", ex, exc_info=True)

    @staticmethod
    def resolve_cross_oracle(cross_oracle, config):
        pyth_feed_ids = set()

        oracle_base_address = cross_oracle.functions.oracleBaseCross().call()
        oracle_base = create_contract_instance(oracle_base_address, config.ORACLE_ABI_PATH, config)
        oracle_base_name = oracle_base.functions.name().call()

        if oracle_base_name == "PythOracle":
            pyth_feed_ids.add(oracle_base.functions.feedId().call().hex())
        elif oracle_base_name == "CrossAdapter":
            pyth_ids = PullOracleHandler.resolve_cross_oracle(oracle_base, config)
            pyth_feed_ids.update(pyth_ids)

        oracle_quote_address = cross_oracle.functions.oracleCrossQuote().call()
        oracle_quote = create_contract_instance(oracle_quote_address, config.ORACLE_ABI_PATH, config)
        oracle_quote_name = oracle_quote.functions.name().call()

        if oracle_quote_name == "PythOracle":
            pyth_feed_ids.add(oracle_quote.functions.feedId().call().hex())
        elif oracle_quote_name == "CrossAdapter":
            pyth_ids = PullOracleHandler.resolve_cross_oracle(oracle_quote, config)
            pyth_feed_ids.update(pyth_ids)
        return pyth_feed_ids

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
    def get_pyth_update_fee(update_data, config):
        logger.info("PullOracleHandler: Getting update fee for data: %s", update_data)
        pyth = create_contract_instance(config.PYTH, config.PYTH_ABI_PATH, config)
        return pyth.functions.getUpdateFee([update_data]).call()

class EVCListener:
    """
    Listener class for monitoring EVC events.
    Primarily intended to listen for AccountStatusCheck events.
    Contains handling for processing historical blocks in a batch system on startup.
    """
    def __init__(self, account_monitor: AccountMonitor, config: ChainConfig):
        self.config = config
        self.w3 = config.w3
        self.account_monitor = account_monitor

        self.evc_instance = config.evc

        self.scanned_blocks = set()

    def start_event_monitoring(self) -> None:
        """
        Start monitoring for EVC events.
        Scans from last scanned block stored by account monitor
        up to the current block number (minus 1 to try to account for reorgs).
        """
        while True:
            try:
                current_block = self.w3.eth.block_number - 1

                if self.account_monitor.latest_block < current_block:
                    self.scan_block_range_for_account_status_check(
                        self.account_monitor.latest_block,
                        current_block)
            except Exception as ex: # pylint: disable=broad-except
                logger.error("EVCListener: Unexpected exception in event monitoring: %s",
                             ex, exc_info=True)

            time.sleep(self.config.SCAN_INTERVAL)

    #pylint: disable=W0102
    def scan_block_range_for_account_status_check(self,
                                                  start_block: int,
                                                  end_block: int,
                                                  max_retries: int = 3,
                                                  seen_accounts: set = set(),
                                                  startup_mode: bool = False) -> None:
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

                        if same_controller and startup_mode:
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
                    time.sleep(self.config.RETRY_DELAY) # cooldown between retries


    def batch_account_logs_on_startup(self) -> None:
        """
        Batch process account logs on startup.
        Goes in reverse order to build smallest queue possible with most up to date info
        """
        try:
            # If the account monitor has a saved state,
            # assume it has been loaded from that and start from the last saved block
            start_block = max(int(self.config.EVC_DEPLOYMENT_BLOCK),
                              self.account_monitor.last_saved_block)

            current_block = self.w3.eth.block_number

            batch_block_size = self.config.BATCH_SIZE

            logger.info("EVCListener: "
                        "Starting batch scan of AccountStatusCheck events from block %s to %s.",
                        start_block, current_block)

            seen_accounts = set()

            while start_block < current_block:
                end_block = min(start_block + batch_block_size, current_block)

                self.scan_block_range_for_account_status_check(start_block, end_block,
                                                               seen_accounts=seen_accounts,
                                                               startup_mode=True)
                self.account_monitor.save_state()

                start_block = end_block + 1

                time.sleep(self.config.BATCH_INTERVAL) # Sleep in between batches to avoid rate limiting

            logger.info("EVCListener: "
                        "Finished batch scan of AccountStatusCheck events from block %s to %s.",
                        start_block, current_block)

        except Exception as ex: # pylint: disable=broad-except
            logger.error("EVCListener: "
                         "Unexpected exception in batch scanning account logs on startup: %s",
                         ex, exc_info=True)

    @staticmethod
    def get_account_owner_and_subaccount_number(account, config):
        evc = config.evc
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
                             violator_account: Account, config: ChainConfig) -> Tuple[bool, Optional[Dict[str, Any]]]:
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

        evc_instance = config.evc
        collateral_list = evc_instance.functions.getCollaterals(violator_address).call()
        borrowed_asset = vault.underlying_asset_address
        liquidator_contract = config.liquidator

        max_profit_data = {
            "tx": None, 
            "profit": 0,
            "collateral_address": None,
            "collateral_asset": None,
            "leftover_borrow": 0, 
            "leftover_borrow_in_eth": 0
        }
        max_profit_params = None

        collateral_vaults = {collateral: Vault(collateral, config) for collateral in collateral_list}

        for collateral, collateral_vault in collateral_vaults.items():
            try:
                logger.info("Liquidator: Checking liquidation for "
                            "account %s, borrowed asset %s, collateral asset %s",
                            violator_address, borrowed_asset, collateral)

                liquidation_results = Liquidator.calculate_liquidation_profit(vault,
                                                                      violator_address,
                                                                      borrowed_asset,
                                                                      collateral_vault,
                                                                      liquidator_contract,
                                                                      config)
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
                    post_error_notification(message, config)
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
                                     liquidator_contract: Any,
                                     config: ChainConfig) -> Tuple[Dict[str, Any], Any]:
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
                                                                 config.LIQUIDATOR_EOA)

        seized_collateral_assets = collateral_vault.convert_to_assets(seized_collateral_shares)

        if max_repay == 0 or seized_collateral_shares == 0:
            logger.info("Liquidator: Max Repay %s, Seized Collateral %s, liquidation not possible",
                        max_repay, seized_collateral_shares)
            return ({"profit": 0}, None)

        swap_api_response = Quoter.get_swap_api_quote(
            chain_id = config.CHAIN_ID,
            token_in = collateral_asset,
            token_out = borrowed_asset,
            amount = int(seized_collateral_assets *.999),
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
            target_debt = 0,
            config=config
        )

        logger.info("Liquidator: swap_api_response for account %s, collateral %s: %s", violator_address, collateral_vault_address, swap_api_response)

        if not swap_api_response:
            return ({"profit": 0}, None)

        amount_out = int(swap_api_response["amountOut"])
        leftover_borrow = amount_out - max_repay

        ## Disabled on non-mainnet chains, because gas is assumed to be negligible
        if False and borrowed_asset != config.WETH:
            borrow_to_eth_response = Quoter.get_swap_api_quote(
                chain_id = config.CHAIN_ID,
                token_in = borrowed_asset,
                token_out = config.WETH,
                amount = leftover_borrow,
                min_amount_out = 0,
                receiver = config.LIQUIDATOR_EOA,
                vault_in = vault.address,
                account_in = config.LIQUIDATOR_EOA,
                account_out = config.LIQUIDATOR_EOA,
                swapper_mode = "0",
                slippage = config.SWAP_SLIPPAGE,
                deadline = int(time.time()) + config.SWAP_DEADLINE,
                is_repay = False,
                current_debt = 0,
                target_debt = 0,
                config=config
            )
            logger.info("Liquidator: borrow_to_eth_response: %s", borrow_to_eth_response)
            leftover_borrow_in_eth = int(borrow_to_eth_response["amountOut"])
        else:
            leftover_borrow_in_eth = leftover_borrow

        time.sleep(config.API_REQUEST_DELAY)

        swap_data = []
        for _, item in enumerate(swap_api_response["swap"]["multicallItems"]):
            if item["functionName"] != "swap":
                continue
            swap_data.append(item["data"])

        logger.info("Liquidator: Seized collateral assets: %s, output amount: %s, "
                    "leftover_borrow: %s", seized_collateral_assets, amount_out,
                    leftover_borrow_in_eth)

        leftover_borrow_in_eth = 1
        if leftover_borrow_in_eth < 0:
            logger.warning("Liquidator: Negative leftover borrow value, aborting liquidation")
            return ({"profit": 0}, None)


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

        pyth_feed_ids = vault.pyth_feed_ids

        suggested_gas_price = int(config.w3.eth.gas_price * 1.2)

        if len(pyth_feed_ids)> 0:
            logger.info("Liquidator: executing with pyth")
            update_data = PullOracleHandler.get_pyth_update_data(pyth_feed_ids)
            update_fee = PullOracleHandler.get_pyth_update_fee(update_data, config)
            liquidation_tx = liquidator_contract.functions.liquidateSingleCollateralWithPythOracle(
                params, swap_data, [update_data]
                ).build_transaction({
                    "chainId": config.CHAIN_ID,
                    "from": config.LIQUIDATOR_EOA,
                    "nonce": config.w3.eth.get_transaction_count(config.LIQUIDATOR_EOA),
                    "value": update_fee,
                    "gasPrice": suggested_gas_price
                })
        else:
            logger.info("Liquidator: executing normally")
            liquidation_tx = liquidator_contract.functions.liquidateSingleCollateral(
                params, swap_data
                ).build_transaction({
                    "chainId": config.CHAIN_ID,
                    "gasPrice": suggested_gas_price,
                    "from": config.LIQUIDATOR_EOA,
                    "nonce": config.w3.eth.get_transaction_count(config.LIQUIDATOR_EOA)
                })
        logger.info("Leftover borrow in eth: %s", leftover_borrow_in_eth)
        logger.info("Estimated gas: %s", config.w3.eth.estimate_gas(liquidation_tx))
        logger.info("Suggested gas price: %s", suggested_gas_price)

        net_profit = leftover_borrow_in_eth - (
            config.w3.eth.estimate_gas(liquidation_tx) * suggested_gas_price)
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
    def execute_liquidation(liquidation_transaction: Dict[str, Any], config: ChainConfig) -> None:
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
            #                                             config.LIQUIDATOR_EOA_PRIVATE_KEY)
            # tx_hash = flashbots_w3.eth.send_raw_transaction(signed_tx.rawTransaction)
            # tx_receipt = flashbots_w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)

            signed_tx = config.w3.eth.account.sign_transaction(liquidation_transaction,
                                                        config.LIQUIDATOR_EOA_PRIVATE_KEY)
            tx_hash = config.w3.eth.send_raw_transaction(signed_tx.rawTransaction)
            tx_receipt = config.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)

            liquidator_contract = config.liquidator

            result = liquidator_contract.events.Liquidation().process_receipt(
                tx_receipt, errors=DISCARD)

            logger.info("Liquidator: Liquidation details: ")
            for event in result:
                logger.info("Liquidator: %s", event["args"])

            logger.info("Liquidator: Liquidation transaction executed successfully.")
            return tx_hash.hex(), tx_receipt
        except Exception as ex: # pylint: disable=broad-except
            message = f"Unexpected error in executing liquidation: {ex}"
            logger.error(message, exc_info=True)
            post_error_notification(message, config)
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
        target_debt: int, # ignored if not in target debt mode
        config
    ):

        params = {
            "chainId": str(chain_id),
            "tokenIn": token_in,
            "tokenOut": token_out, 
            "amount": str(amount),
            "receiver": receiver,
            "vaultIn": vault_in,
            "origin": config.LIQUIDATOR_EOA,
            "accountIn": account_in,
            "accountOut": account_out,
            "swapperMode": swapper_mode,  # TARGET_DEBT mode
            "slippage": str(slippage),
            "deadline": str(deadline), 
            "isRepay": str(is_repay),
            "currentDebt": str(current_debt),
            "targetDebt": str(target_debt)
        }

        response = make_api_request(config.SWAP_API_URL, headers={}, params=params)

        if not response or not response["success"]:
            logger.error("Unable to get quote from swap api")
            return None

        amount_out = int(response["data"]["amountOut"])

        if amount_out < min_amount_out:
            logger.error("Quote too low")
            return None

        return response["data"]

if __name__ == "__main__":
    try:
        pass

    except Exception as e: # pylint: disable=broad-except
        logger.critical("Uncaught exception: %s", e, exc_info=True)
        error_message = f"Uncaught global exception: {e}"
        post_error_notification(error_message)

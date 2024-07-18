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

from concurrent.futures import ThreadPoolExecutor
from typing import Tuple, Dict, Any, Optional

from dotenv import load_dotenv
from web3 import Web3

from .utils import setup_logger, setup_w3, create_contract_instance, make_api_request, global_exception_handler, post_liquidation_opportunity_on_slack, config

### ENVIRONMENT & CONFIG SETUP ###
load_dotenv()
API_KEY_1INCH = os.getenv("1INCH_API_KEY")
LIQUIDATOR_EOA_PUBLIC_KEY = os.getenv("LIQUIDATOR_EOA_PUBLIC_KEY")
LIQUIDATOR_EOA_PRIVATE_KEY = os.getenv("LIQUIDATOR_EOA_PRIVATE_KEY")

logger = setup_logger(config.LOGS_PATH)
w3 = setup_w3()
sys.excepthook = global_exception_handler


### MAIN CODE ###

class Vault:
    """
    Represents a vault in the EVK System.
    This class provides methods to interact with a specific vault contract.
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
        (collateral_value, liability_value) = self.instance.functions.accountLiquidity(
            Web3.to_checksum_address(account_address),
            False
        ).call()

        return (collateral_value, liability_value)

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
        (max_repay, seized_collateral) = self.instance.functions.checkLiquidation(
            Web3.to_checksum_address(liquidator_address),
            Web3.to_checksum_address(borower_address),
            Web3.to_checksum_address(collateral_address)
            ).call()
        return (max_repay, seized_collateral)

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
        self.current_health_score = 1


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
        collateral_value, liability_value = self.controller.get_account_liquidity(self.address)
        self.current_health_score = collateral_value / liability_value

        logger.info("Account: Account %s health score: %s", self.address, self.current_health_score)
        return self.current_health_score

    def get_time_of_next_update(self) -> float:
        """
        Calculate the time of the next update for this account.

        Returns:
            float: The timestamp of the next scheduled update.
        """

        time_gap = 0

        # Simple linear interpolation between min and max update intervals
        # TODO: make this smarter
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

        while self.running:
            with self.condition:
                while self.update_queue.empty():
                    logger.info("AccountMonitor: Waiting for queue to be non-empty.")
                    self.condition.wait()

                next_update_time, address = self.update_queue.get()

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
                        vault)
        else:
            logger.info("AccountMonitor: Account %s already in list with controller %s.",
                        address,
                        vault)

        self.update_account(address)

    def update_account(self, address: str) -> None:
        """
        Trigger a manual update of an account.
        This should primarily be called in two scenarios:
            1) Internally due to a status check event detected
            2) Externally due to a manual trigger (e.g. a user request, price change monitor, etc)

        Args:
            address (str): The address of the account to update.
        """
        account = self.accounts[address]

        account.update_liquidity()

        next_update_time = account.time_of_next_update

        with self.condition:
            self.update_queue.put((next_update_time, address))
            self.condition.notify()

    def update_account_liquidity(self, address: str) -> None:
        """
        Update the liquidity of a specific account.

        Args:
            address (str): The address of the account to update.
        """
        try:
            account = self.accounts.get(address)

            if not account:
                logger.error("AccountMonitor: Account %s not found in account list.", address)
                return

            logger.info("AccountMonitor: Updating account %s liquidity.", address)

            health_score = account.update_liquidity()

            if health_score < 1:
                try:
                    logger.info("AccountMonitor: Account %s is unhealthy,"
                                "checking liquidation profitability.",
                                address)
                    (result, liquidation_data) = account.simulate_liquidation()

                    if result:
                        if self.notify:
                            try:
                                logger.info("AccountMonitor: Posting liquidation notification"
                                            "to slack for account %s.", address)
                                post_liquidation_opportunity_on_slack(address,
                                                                      account.controller.address,
                                                                      liquidation_data)
                            except Exception as ex: # pylint: disable=broad-except
                                logger.error("AccountMonitor:"
                                             "Failed to post liquidation notification"
                                             " for account %s to slack: %s",
                                             address, ex)
                        if self.execute_liquidation:
                            try:
                                Liquidator.execute_liquidation(liquidation_data["liquidation_tx"])
                                logger.info("AccountMonitor: Account %s liquidated"
                                            "on collateral %s.",
                                            address,
                                            liquidation_data["collateral_address"])

                                # Update account health score after liquidation
                                # Need to know how healthy the account is after liquidation
                                # and if we need to liquidate again
                                account.update_liquidity()
                            except Exception as ex: # pylint: disable=broad-except
                                logger.error("AccountMonitor:"
                                             "Failed to execute liquidation for account %s: %s",
                                             address,
                                             ex)
                    else:
                        logger.info("AccountMonitor:"
                                    "Account %s is unhealthy but not profitable to liquidate.",
                                    address)
                        # TODO: add filter for small account/repeatedly seen accounts
                except Exception as ex: # pylint: disable=broad-except
                    logger.error("AccountMonitor:"
                                 "Exception simulating liquidation for account %s: %s",
                                 address, ex)

            next_update_time = account.time_of_next_update

            with self.condition:
                self.update_queue.put((next_update_time, address))
                self.condition.notify()

        except Exception as ex: # pylint: disable=broad-except
            logger.error("AccountMonitor: Exception updating account %s: %s", address, ex)

    def save_state(self, local_save: bool = True) -> None:
        """
        Save the current state of the account monitor.
        TODO: Update this in the future to be able to save to a remote file.

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
            logger.error("AccountMonitor: Failed to save state: %s", ex)

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
                self.accounts = {address: Account.from_dict(data, self.vaults)
                                 for address, data in state["accounts"].items()}

                for item in state["queue"]:
                    self.update_queue.put(tuple(item))

                self.last_saved_block = state["last_saved_block"]
                self.latest_block = self.last_saved_block
                logger.info("AccountMonitor: State loaded from %s up to block %s",
                            save_path,
                            self.latest_block)
            elif not local_save:
                # Load from remote location
                pass
            else:
                logger.info("AccountMonitor: No saved state found.")
        except Exception as ex: # pylint: disable=broad-except
            logger.error("AccountMonitor: Failed to load state: %s", ex)

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


class EVCListener:
    """
    Listener class for monitoring EVC events.
    Primarily intended to listen for AccountStatusCheck events.
    Contains handling for processing historical blocks in a batch system on startup.
    """
    def __init__(self, account_monitor: AccountMonitor):
        self.account_monitor = account_monitor

        self.evc_instance = create_contract_instance(config.EVC_ADDRESS, config.EVC_ABI_PATH)

    def start_event_monitoring(self) -> None:
        """
        Start monitoring for EVC events.
        TODO: Implement timed eventing for AccountStatusCheck events.
        """
        while True:
            try:
                pass
            except Exception as ex: # pylint: disable=broad-except
                logger.error("EVCListener: Unexpected exception in event monitoring: %s", ex)

            time.sleep()

    def scan_block_range_for_account_status_check(self,
                                                  start_block: int,
                                                  end_block: int,
                                                  max_retries: int = config.NUM_RETRIES) -> None:
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

                    logger.info("EVCListener: AccountStatusCheck event found for account %s"
                                "with controller %s, triggering monitor update.",
                                account_address, vault_address)

                    try:
                        self.account_monitor.update_account_on_status_check_event(
                            account_address,
                            vault_address)
                    except Exception as ex: # pylint: disable=broad-except
                        logger.error("EVCListener: Exception updating account %s"
                                     "on AccountStatusCheck event: %s", account_address, ex)

                logger.info("EVCListener: Finished scanning blocks %s to %s"
                            "for AccountStatusCheck events.", start_block, end_block)

                self.account_monitor.latest_block = end_block
            except Exception as ex: # pylint: disable=broad-except
                logger.error("EVCListener: Exception scanning block range %s to %s"
                             "(attempt %s/%s): %s",
                             start_block, end_block, attempt + 1, max_retries, ex)
                if attempt == max_retries - 1:
                    logger.error("EVCListener:"
                                 "Failed to scan block range %s to %s after %s attempts",
                                 start_block, end_block, max_retries)
                else:
                    time.sleep(config.RETRY_DELAY) # cooldown between retries

    def batch_account_logs_on_startup(self) -> None:
        """
        Batch process account logs on startup.
        """
        try:
            start_block = int(config.EVC_DEPLOYMENT_BLOCK)
            # If the account monitor has a saved state,
            # assume it has been loaded from that and start from the last saved block
            if self.account_monitor.last_saved_block > start_block:
                logger.info("EVCListener: Account monitor has saved state, starting from block %s.",
                            self.account_monitor.last_saved_block)
                start_block = self.account_monitor.last_saved_block

            current_block = w3.eth.block_number

            batch_block_size = config.BATCH_SIZE

            logger.info("EVCListener:"
                        "Starting batch scan of AccountStatusCheck events from block %s to %s.",
                        start_block, current_block)

            while start_block < current_block:
                end_block = min(start_block + batch_block_size, current_block)

                self.scan_block_range_for_account_status_check(start_block, end_block)

                start_block = end_block + 1

                self.account_monitor.save_state()

                time.sleep(config.RETRY_DELAY) # Sleep in between batches to avoid rate limiting
            logger.info("EVCListener:"
                        "Finished batch scan of AccountStatusCheck events from block %s to %s.",
                        start_block, current_block)
        except Exception as ex: # pylint: disable=broad-except
            logger.error("EVCListener:"
                         "Unexpected exception in batch scanning account logs on startup: %s", ex)

#TODO: Future feature, smart monitor to trigger manual update of an account
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
        self.account_monitor.update_account(account)

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

        evc_instance = create_contract_instance(config.EVC_ADDRESS, config.EVC_ABI_PATH)
        collateral_list = evc_instance.functions.getCollaterals(violator_address).call()
        borrowed_asset = vault.underlying_asset_address
        liquidator_contract = create_contract_instance(config.LIQUIDATOR_CONTRACT_ADDRESS,
                                                       config.LIQUIDATOR_ABI_PATH)

        max_profit_data = {
            "tx": None, 
            "profit": 0,
            "collateral_address": None,
            "collateral_asset": None,
            "leftover_collateral": 0, 
            "leftover_collateral_in_eth": 0
        }

        collateral_vaults = {collateral: Vault(collateral) for collateral in collateral_list}

        for collateral, collateral_vault in collateral_vaults.items():
            try:
                profit_data = Liquidator.calculate_liquidation_profit(vault,
                                                                      violator_address,
                                                                      borrowed_asset,
                                                                      collateral_vault,
                                                                      liquidator_contract)

                if profit_data["profit"] > max_profit_data["profit"]:
                    max_profit_data = profit_data
            except Exception as ex: # pylint: disable=broad-except
                logger.error("Liquidator:"
                             "Exception simulating liquidation"
                             "for account %s with collateral %s: %s",
                             violator_address, collateral, ex)
                continue


        if max_profit_data["tx"]:
            logger.info("Liquidator: Profitable liquidation found for account %s. "
                        "Collateral: %s, Underlying Collateral Asset: %s, "
                        "Remaining collateral after swap and repay: %s, "
                        "Estimated profit in ETH: %s",
                        violator_address, max_profit_data["collateral_address"],
                        max_profit_data["collateral_asset"], max_profit_data["leftover_collateral"],
                        max_profit_data["profit_in_eth"])
            return (True, max_profit_data)
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
        collateral_asset = collateral_vault.underlying_asset_address

        (max_repay, seized_collateral) = vault.check_liquidation(violator_address,
                                                                 collateral_asset,
                                                                 LIQUIDATOR_EOA_PUBLIC_KEY)

        if max_repay == 0 or seized_collateral == 0:
            return {"profit": 0}

        (swap_amount, _) = Quoter.get_1inch_quote(collateral_asset,
                                                  borrowed_asset,
                                                  seized_collateral,
                                                  max_repay)

        estimated_slippage_needed = 2 # TODO: actual slippage calculation

        swap_data_1inch = Quoter.get_1inch_swap_data(collateral_asset,
                                                     borrowed_asset,
                                                     swap_amount,
                                                     config.SWAPPER,
                                                     LIQUIDATOR_EOA_PUBLIC_KEY,
                                                     estimated_slippage_needed)

        leftover_collateral = seized_collateral - swap_amount

        # Convert leftover asset to WETH
        (_, leftover_collateral_in_eth) = Quoter.get_1inch_quote(collateral_asset,
                                                                 config.WETH_ADDRESS,
                                                                 leftover_collateral, 0)

        params = (
                violator_address,
                vault.address,
                borrowed_asset,
                collateral_vault.address,
                collateral_asset,
                max_repay,
                seized_collateral,
                leftover_collateral,
                swap_data_1inch
        )

        liquidation_tx = liquidator_contract.functions.liquidate_single_collateral(
            params
            ).build_transaction({
                "chainId": config.CHAIN_ID,
                "gasPrice": w3.eth.gas_price,
                "from": LIQUIDATOR_EOA_PUBLIC_KEY,
                "nonce": w3.eth.get_transaction_count(LIQUIDATOR_EOA_PUBLIC_KEY),
                "to": config.LIQUIDATOR_CONTRACT_ADDRESS
            })

        net_profit = leftover_collateral_in_eth - w3.eth.estimate_gas(liquidation_tx)

        return {
            "tx": liquidation_tx, 
            "profit": net_profit, 
            "collateral_address": collateral_vault.address,
            "collateral_asset": collateral_asset,
            "leftover_collateral": leftover_collateral, 
            "leftover_collateral_in_eth": leftover_collateral_in_eth
        }


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

            liquidator_contract = create_contract_instance(config.LIQUIDATOR_CONTRACT_ADDRESS,
                                                           config.LIQUIDATOR_ABI_PATH)

            result = liquidator_contract.events.Liquidation().process_receipt(tx_receipt)

            logger.info("Liquidator: Liquidation details:")
            for event in result:
                logger.info("Liquidator: %s", event["args"])

            logger.info("Liquidator: Liquidation transaction executed successfully.")
        except Exception as ex: # pylint: disable=broad-except
            logger.error("Liquidator: Unexpected error in execute_liquidation %s", ex)

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
            api_url = "https://api.1inch.dev/swap/v6.0/1/quote"
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

            amount_out = 0 #declare so we can access outside loops

            while iteration_count < config.MAX_SEARCH_ITERATIONS:
                swap_amount = int((min_amount_in + max_amount_in) / 2)
                params["amount"] = swap_amount
                amount_out = get_quote(params)

                if amount_out is None:
                    if last_valid_amount_out > target_amount_out:
                        logger.warning("Quoter: 1inch quote failed, using last valid"
                                       "quote: %s %s to %s %s",
                                       last_valid_amount_in, asset_in,
                                       last_valid_amount_out, asset_out)
                        return (last_valid_amount_in, last_valid_amount_out)
                    logger.warning("Quoter: Failed to get valid 1inch quote"
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
                elif amount_out > target_amount_out:
                    max_amount_in = swap_amount

                iteration_count +=1
                time.sleep(2) # need to rate limit until getting enterprise account key

            if iteration_count == config.MAX_SEARCH_ITERATIONS:
                logger.warning("Quoter: 1inch quote search for %s to %s"
                               "did not converge after %s iterations.",
                               asset_in, asset_out, config.MAX_SEARCH_ITERATIONS)
                if last_valid_amount_out > target_amount_out:
                    logger.info("Quoter: Using last valid quote: %s %s to %s %s",
                                last_valid_amount_in, asset_in, last_valid_amount_out, asset_out)
                    return (last_valid_amount_in, last_valid_amount_out)
                return (0, 0)

            return (params["amount"], amount_out)
        except Exception as ex: # pylint: disable=broad-except
            logger.error("Quoter: Unexpected error in get_1inch_quote %s", ex)
            return (0, 0)

    @staticmethod
    def get_1inch_swap_data(asset_in: str,
                            asset_out: str,
                            amount_in: int,
                            swap_from: str,
                            tx_origin: str,
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
            "disableEstimate": "true"
        }

        api_url = "https://api.1inch.dev/swap/v6.0/1/swap"
        headers = { "Authorization": f"Bearer {API_KEY_1INCH}" }
        response = make_api_request(api_url, headers, params)

        return response["tx"]["data"] if response else None





if __name__ == "__main__":
    try:

        # monitor.load_state(SAVE_STATE_PATH)

        # time.sleep(5)
        # threading.Thread(target=monitor.start_queue_monitoring).start()
        # time.sleep(5)
        # monitor.update_account_on_status_check_event("0x123", "vault1")
        # time.sleep(5)
        # monitor.update_account_on_status_check_event("0x456", "vault2")
        # time.sleep(5)
        # monitor.update_account_on_status_check_event("0x789", "vault3")

        # while True:
        #     time.sleep(1)

        # monitor = AccountMonitor()
        # evc_listener = EVCListener(monitor)


        # liquidator = Liquidator()
        quoter = Quoter()

        USDC_ADDRESS = "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48"
        USDT_ADDRESS = "0xdAC17F958D2ee523a2206206994597C13D831ec7"

        AMOUNT_USDC_IN = 100000000
        TARGET_USDT_OUT = 70000000

        print(f"Getting 1inch quote for {AMOUNT_USDC_IN} USDC to USDT with target"
              f"{TARGET_USDT_OUT} USDT out")
        actual_amount_in, _ = quoter.get_1inch_quote(USDC_ADDRESS, USDT_ADDRESS,
                                                     AMOUNT_USDC_IN, TARGET_USDT_OUT)

        print(f"Actual amount in: {actual_amount_in}")

        print(f"Getting swap data for {actual_amount_in} USDC to USDT")

        SWAP_FROM = "0xf4e55515952BdAb2aeB4010f777E802D61eB384f"
        TX_ORIGIN = "0xeC5DF17559e6E4172b82FcD8Df84D425748f6dd2"

        swap_data = quoter.get_1inch_swap_data(USDC_ADDRESS, USDT_ADDRESS,
                                               AMOUNT_USDC_IN, SWAP_FROM, TX_ORIGIN)

        print(f"Swap data: {swap_data}")

        # print(quoter.get_1inch_quote(USDC_ADDRESS, usdt_address, AMOUNT_USDC_IN, TARGET_USDT_OUT))
    except Exception as e: # pylint: disable=broad-except
        logger.critical("Uncaught exception: %s", e)

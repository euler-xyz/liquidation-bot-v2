from dotenv import load_dotenv

import threading
import random
import time
import queue
import os
import json
import yaml
import sys

from concurrent.futures import ThreadPoolExecutor
from web3 import Web3

from utils import setup_logger, setup_w3, create_contract_instance, make_api_request, global_exception_handler

### ENVIRONMENT & CONFIG SETUP ###
load_dotenv()
API_KEY_1INCH = os.getenv('1INCH_API_KEY')

with open('config.yaml') as config_file:
    config = yaml.safe_load(config_file)

LOGS_PATH = config.get('LOGS_PATH')
SAVE_STATE_PATH = config.get('SAVE_STATE_PATH')
SAVE_INTERVAL = config.get('SAVE_INTERVAL')
HS_LOWER_BOUND = config.get('HS_LOWER_BOUND')
HS_UPPER_BOUND = config.get('HS_UPPER_BOUND')
MIN_UPDATE_INTERVAL = config.get('MIN_UPDATE_INTERVAL')
MAX_UPDATE_INTERVAL = config.get('MAX_UPDATE_INTERVAL')
BATCH_SIZE = config.get('BATCH_SIZE')
SWAP_DELTA = config.get('SWAP_DELTA')
WETH_ADDRESS = config.get('WETH_ADDRESS')
EVC_ADDRESS = config.get('EVC_ADDRESS')
SWAPPER_ADDRESS = config.get('SWAPPER_ADDRESS')
SWAP_VERIFIER_ADDRESS = config.get('SWAP_VERIFIER_ADDRESS')
LIQUIDATOR_CONTRACT_ADDRESS = config.get('LIQUIDATOR_CONTRACT_ADDRESS')
EVAULT_ABI_PATH = config.get('EVAULT_ABI_PATH')
EVC_ABI_PATH = config.get('EVC_ABI_PATH')
MAX_SEARCH_ITERATIONS = config.get('MAX_SEARCH_ITERATIONS')
NUM_RETRIES = config.get('NUM_RETRIES')
RETRY_DELAY = config.get('RETRY_DELAY')

logger = setup_logger(LOGS_PATH)
w3 = setup_w3()
sys.excepthook = global_exception_handler


### MAIN CODE ###

class Vault:
    def __init__(self, address):
        self.address = address

        self.instance = create_contract_instance(address, EVAULT_ABI_PATH)

        self.underlying_asset_address = self.instance.functions.asset().call()

    def get_account_liquidity(self, account_address):
        (collateral_value, liability_value) = self.instance.functions.accountLiquidity(Web3.to_checksum_address(account_address), False).call()

        return (collateral_value, liability_value)
    
    def check_liquidation(self, borower_address, collateral_address, liquidator_address):
        (max_repay, expected_yield) = self.instance.functions.checkLiquidation(Web3.to_checksum_address(liquidator_address), Web3.to_checksum_address(borower_address), Web3.to_checksum_address(collateral_address)).call()
        return (max_repay, expected_yield)

class Account:
    def __init__(self, address, controller: Vault):
        self.address = address
        self.controller = controller
        self.time_of_next_update = time.time()
        self.current_health_score = 1

    """
    Check account liquidity and set when the next update should be
    """
    def update_liquidity(self):
        self.get_health_score()
        self.get_time_of_next_update()
        
        return self.current_health_score
    
    """
    Calculate the health score of this account
    """
    def get_health_score(self):
        # self.current_health_score = random.random() + .5 # Placeholder for now

        collateral_value, liability_value = self.controller.get_account_liquidity(self.address)
        self.current_health_score = collateral_value / liability_value

        logger.info(f"Account: Account {self.address} health score: {self.current_health_score}")
        return self.current_health_score
    
    """
    Calculate the time of the next update for this account as a function of health score
    """
    def get_time_of_next_update(self):
        # self.time_of_next_update = self.current_health_score * 10 + time.time() # Placeholder for now
        time_gap = 0

        # Simple linear interpolation between min and max update intervals
        # TODO: make this smarter
        if self.current_health_score < HS_LOWER_BOUND:
            time_gap = MIN_UPDATE_INTERVAL
        elif self.current_health_score > HS_UPPER_BOUND:
            time_gap = MAX_UPDATE_INTERVAL
        else:
            slope = (MAX_UPDATE_INTERVAL - MIN_UPDATE_INTERVAL) / (HS_UPPER_BOUND - HS_LOWER_BOUND)
            intercept = MIN_UPDATE_INTERVAL - slope * HS_LOWER_BOUND
            time_gap = slope * self.current_health_score + intercept
        
        random_adjustment = random.random() / 5 + .9
        self.time_of_next_update = time.time() + time_gap * random_adjustment # Randomly adjust the time by +/- 10% to avoid syncronized checks across accounts/deployments

        logger.info(f"Account: Account {self.address} next update scheduled for {time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(self.time_of_next_update))}")
        return self.time_of_next_update

    """
    Simulate liquidation of this account to determine if it is profitable to liquidate.
    Returns True if profitable
    """
    def simulate_liquidation(self):
        result = Liquidation.simulate_liquidation(self.controller, self.address)
        return result

    """
    Convert to dict, used for saving state
    """
    def to_dict(self):
        return {
            "address": self.address,
            "controller_address": self.controller.address,
            "time_of_next_update": self.time_of_next_update,
            "current_health_score": self.current_health_score
        }
    
    @staticmethod
    def from_dict(data, vaults):
        controller = vaults.get(data["controller_address"])
        if not controller:
            controller = Vault(data["controller_address"])
            vaults[data["controller_address"]] = controller
        
        account = Account(address=data["address"], controller=controller)
        account.time_of_next_update = data["time_of_next_update"]
        account.current_health_score = data["current_health_score"]
        return account
    

class AccountMonitor:
    def __init__(self, notify_discord = False, execute_liquidation = False):
        self.accounts = {}
        self.vaults = {}
        self.update_queue = queue.PriorityQueue()
        self.condition = threading.Condition()
        self.executor = ThreadPoolExecutor(max_workers=32)
        self.running = True
        self.latest_block = 0
        self.last_saved_block = 0
        self.notify_discord = notify_discord
        self.execute_liquidation = execute_liquidation

    def start_queue_monitoring(self):
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
            

    def update_account_on_status_check_event(self, address, vault_address):
        if vault_address not in self.vaults: # If the vault is not already tracked in the list, create it
            self.vaults[vault_address] = Vault(vault_address)
            logger.info(f"AccountMonitor: Vault {vault_address} added to vault list.")
        
        vault = self.vaults[vault_address]

        if address not in self.accounts or self.accounts[address].controller.address != vault_address: # If the account is not in the list or the controller has changed
            account = Account(address, vault)
            self.accounts[address] = account

            logger.info(f"AccountMonitor: Adding account {address} to account list with controller {vault}.")
        else:
            logger.info(f"AccountMonitor: Account {address} already in list with controller {vault}.")
        
        self.update_account(address)
        
    """
    Trigger a manual update of an account.
    This should primarily be called in two scenarios:
    1) Internally due to a status check event detected
    2) Externally due to a manual trigger (e.g. a user request, price change monitor, etc)
    """
    def update_account(self, address):
        account = self.accounts[address]

        account.update_liquidity()

        next_update_time = account.time_of_next_update

        with self.condition:
            self.update_queue.put((next_update_time, address))
            self.condition.notify()
    
    def update_account_liquidity(self, address):
        try:
            account = self.accounts.get(address)

            if not account:
                logger.error(f"AccountMonitor: Account {address} not found in account list.")
                return

            logger.info(f"AccountMonitor: Updating account {address} liquidity.")
            
            health_score = account.update_liquidity()

            if(health_score < 1):
                try:
                    logger.info(f"AccountMonitor: Account {address} is unhealthy, checking liquidation profitability.")
                    (result, liquidation_tx, remaining_seized_collateral, profit_in_eth) = account.simulate_liquidation()

                    if result:
                        if self.notify_discord:
                            # Notify discord
                            # TODO: implement
                            pass
                        
                        if self.execute_liquidation:
                            try:
                                Liquidation.execute_liquidation(liquidation_tx)
                                logger.info(f"AccountMonitor: Account {address} liquidated.")
                            except Exception as e:
                                logger.error(f"AccountMonitor: Failed to execute liquidation for account {address}: {e}")
                    else:
                        logger.info(f"AccountMonitor: Account {address} is unhealthy but not profitable to liquidate.")
                        # TODO: add some filter for small account/repeatedly seen accounts to avoid spam
                except Exception as e:
                    logger.error(f"AccountMonitor: Exception simulating liquidation for account {address}: {e}")
                
            next_update_time = account.time_of_next_update

            with self.condition:
                self.update_queue.put((next_update_time, address))
                self.condition.notify()

        except Exception as e:
            logger.error(f"AccountMonitor: Exception updating account {address}: {e}")

    """
    Save the state of the account monitor to a json file.
    TODO: Update this in the future to be able to save to a remote file.
    """
    def save_state(self, local_save: bool = True):
        try:
            state = {
                'accounts': {address: account.to_dict() for address, account in self.accounts.items()},
                'vaults': {address: vault.address for address, vault in self.vaults.items()},
                'queue': list(self.update_queue.queue),
                'last_saved_block': self.latest_block,
            }
            
            if local_save:
                with open(SAVE_STATE_PATH, 'w') as f:
                    json.dump(state, f)
            else:
                # Save to remote location
                pass

            self.last_saved_block = self.latest_block

            logger.info(f"AccountMonitor: State saved at time {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime())} up to block {self.latest_block}")
        except Exception as e:
            logger.error(f"AccountMonitor: Failed to save state: {e}")

    """
    Load the state of the account monitor from a json file.
    TODO: Update this in the future to be able to load from a remote file.
    """
    def load_state(self, save_path, local_save: bool = True):
        try:
            if local_save and os.path.exists(save_path):
                with open(save_path, 'r') as f:
                    state = json.load(f)
                self.vaults = {address: Vault(address) for address in state['vaults']}
                self.accounts = {address: Account.from_dict(data, self.vaults) for address, data in state['accounts'].items()}
                    
                for item in state['queue']:
                    self.update_queue.put(tuple(item))

                self.last_saved_block = state['last_saved_block']
                self.latest_block = self.last_saved_block
                logger.info(f"AccountMonitor: State loaded from {save_path} up to block {self.latest_block}.")
            elif not local_save:
                # Load from remote location
                pass
            else:
                logger.info("AccountMonitor: No saved state found.")
        except Exception as e:
            logger.error(f"AccountMonitor: Failed to load state: {e}")
    
    @staticmethod
    def create_from_save_state(save_path, local_save: bool = True):
        monitor = AccountMonitor()
        monitor.load_state(save_path, local_save)
        return monitor

    """
    Periodically save the state of the account monitor.
    Should be run in a standalone thread.
    """
    def periodic_save(self):
        while self.running:
            time.sleep(SAVE_INTERVAL)
            self.save_state()

    """
    Stop the account monitor.
    Ssaves state after stopping.
    """
    def stop(self):
        self.running = False
        with self.condition:
            self.condition.notify_all()
        self.executor.shutdown(wait=True)
        self.save_state()


class EVCListener:
    def __init__(self, account_monitor: AccountMonitor):
        self.account_monitor = account_monitor

        self.evc_instance = create_contract_instance(EVC_ADDRESS, EVC_ABI_PATH)
    
    def start_event_monitoring(self):
        while True:
            pass
    
    def scan_block_range_for_account_status_check(self, start_block, end_block, max_retries = NUM_RETRIES):
        for attempt in range(max_retries):
            try:
                logger.info(f"EVCListener: Scanning blocks {start_block} to {end_block} for AccountStatusCheck events.")

                logs = self.evc_instance.events.AccountStatusCheck().get_logs(fromBlock=start_block, toBlock=end_block)

                for log in logs:
                    vault_address = log['args']['controller']
                    account_address = log['args']['account']

                    logger.info(f"EVCListener: AccountStatusCheck event found for account {account_address} with controller {vault_address}, triggering monitor update.")
                    
                    try:
                        self.account_monitor.update_account_on_status_check_event(account_address, vault_address)
                    except Exception as e:
                        logger.error(f"EVCListener: Exception updating account {account_address} on AccountStatusCheck event: {e}")

                logger.info(f"EVCListener: Finished scanning blocks {start_block} to {end_block} for AccountStatusCheck events.")

                self.account_monitor.latest_block = end_block
            except Exception as e:
                logger.error(f"EVCListener: Exception scanning block range {start_block} to {end_block} (attempt {attempt + 1}/{max_retries}): {e}")
                if attempt == max_retries - 1:
                    logger.error(f"EVCListener: Failed to scan block range {start_block} to {end_block} after {max_retries} attempts")
                else:
                    time.sleep(RETRY_DELAY) # cooldown between retries

    def batch_account_logs_on_startup(self):
        try:
            start_block = int(os.getenv('EVC_GENESIS_BLOCK'))
            
            # If the account monitor has a saved state, assume it has been loaded from that and start from the last saved block
            if self.account_monitor.last_saved_block > start_block:
                logger.info(f"EVCListener: Account monitor has saved state, starting from block {self.account_monitor.last_saved_block}.")
                start_block = self.account_monitor.last_saved_block

            current_block = w3.eth.block_number

            batch_block_size = BATCH_SIZE # 1000 blocks per batch, need to decide if this is the right size

            logger.info(f"EVCListener: Starting batch scan of AccountStatusCheck events from block {start_block} to {current_block}.")

            while start_block < current_block:
                end_block = min(start_block + batch_block_size, current_block)

                self.scan_block_range_for_account_status_check(start_block, end_block)

                start_block = end_block + 1

                self.account_monitor.save_state()

                time.sleep(10) # Sleep in between batches to avoid rate limiting
            
            logger.info(f"EVCListener: Finished batch scan of AccountStatusCheck events from block {start_block} to {current_block}.")
        except Exception as e:
            logger.error(f"EVCListener: Unexpected exception in batch scanning account logs on startup: {e}")

#TODO: Future feature, smart monitor to trigger manual update of an account based on a large price change (or some other trigger)
class SmartUpdateListener:
    def __init__(self, account_monitor: AccountMonitor):
        self.account_monitor = account_monitor

    def trigger_manual_update(self, account):
        self.account_monitor.update_account(account)

class Liquidation:
    def __init__(self):
        pass

    @staticmethod
    def simulate_liquidation(vault: Vault, violator_address: str, include_swap_to_eth: bool = False):
        evc_instance = create_contract_instance(EVC_ADDRESS, EVC_ABI_PATH)

        collateral_list = evc_instance.functions.getCollaterals(violator_address).call()
        remaining_collateral_after_repay = {}

        dust_liability_asset = 0
        profit_in_eth = 0

        tx_list = []
        master_tx = None

        profitable = False

        for collateral in collateral_list:
            (max_repay, expected_yield) = vault.check_liquidation(violator_address, collateral, os.getenv('LIQUIDATOR_PUBLIC_KEY'))
            
            if max_repay == 0 or expected_yield == 0:
                continue
            
            #TODO: fallback to Uniswap (?) if 1inch fails
            (swap_amount, swap_output) = Quoter.get_1inch_quote(collateral, vault.underlying_asset_address, expected_yield, max_repay)
            swap_data = Quoter.get_1inch_swap_data(collateral, vault.underlying_asset_address, swap_amount)

            dust_liability_asset += swap_output - max_repay # track dust liability due to overswapping

            remaining_collateral_after_repay[collateral] = expected_yield - swap_amount # track remaining collateral after repay
            
            (swap_amount, swap_output, ) = Quoter.get_1inch_quote(collateral, WETH_ADDRESS, amount, 0, True) # convert leftover asset to ETH
            profit_in_eth += swap_output


            # TODO: build transaction to liquidate and append

        
        if(include_swap_to_eth):
            for(collateral, amount) in remaining_collateral_after_repay.items():
                #TODO: add swap to ETH and include relevant gas cost
                pass
        
        return (profitable, master_tx, remaining_collateral_after_repay, profit_in_eth)
    
    
    """
    Execute the liquidation of an account using the transaction returned from simulate_liquidation
    TODO: implement
    """
    @staticmethod
    def execute_liquidation(liquidation_transaction):
        pass

class Quoter:
    def __init__(self):
        pass

    """
    Given a base asset and target asset, get a quote from 1INCH.
    If target_amount_out == 0, it is treated as an exact in swap.

    Returns swap in amount, swap out amount, and swap data needed to call 1INCH router in the swapper contract.
    """
    @staticmethod
    def get_1inch_quote(asset_in: str, asset_out: str, amount_asset_in: int, target_amount_out: int):
        
        # simple quote function wrapper
        def get_quote(params):
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
                    return (0, 0, None)
                return (amount_asset_in, amount_out, None)

            # Binary search to find the amount in that will result in the target amount out
            # Overswaps slightly to make sure we can always repay max_repay
            min_amount_in, max_amount_in = 0, amount_asset_in
            delta = SWAP_DELTA
            
            iteration_count = 0

            last_valid_amount_in, last_valid_amount_out = 0, 0 
            
            amount_out = 0 #declare so we can access outside loops

            while iteration_count < MAX_SEARCH_ITERATIONS:
                swap_amount = int((min_amount_in + max_amount_in) / 2)
                params["amount"] = swap_amount
                amount_out = get_quote(params)

                if amount_out is None:
                    if last_valid_amount_out > target_amount_out:
                        logger.warning(f"Quoter: 1inch quote failed, using last valid quote: {last_valid_amount_in} {asset_in} to {last_valid_amount_out} {asset_out}")
                        return (last_valid_amount_in, last_valid_amount_out)
                    else:
                        logger.warning(f"Quoter: Failed to get valid 1inch quote for {swap_amount} {asset_in} to {asset_out}")
                        return (0, 0)

                logger.info(f"Quoter: 1inch quote for {swap_amount} {asset_in} to {asset_out}: {amount_out}")

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
            
            if iteration_count == MAX_SEARCH_ITERATIONS:
                logger.warning(f"Quoter: 1inch quote search for {asset_in} to {asset_out} did not converge after {MAX_SEARCH_ITERATIONS} iterations.")
                if last_valid_amount_out > target_amount_out:
                    logger.info(f"Quoter: Using last valid quote: {last_valid_amount_in} {asset_in} to {last_valid_amount_out} {asset_out}")
                    return (last_valid_amount_in, last_valid_amount_out)
                else:
                    return (0, 0)

            return (params['amount'], amount_out)
        except Exception as e:
            logger.error(f"Quoter: Unexpected error in get_1inch_quote {e}")
            return (0, 0)
    
    """
    Get 1inch swap data with optimal swap path
    TODO: implement
    """
    @staticmethod
    def get_1inch_swap_data(asset_in: str, asset_out: str, amount_in: int):
        pass






if __name__ == "__main__":
    try:
        # monitor = AccountMonitor()
        
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

        liquidator = Liquidation()
        quoter = Quoter()

        usdc_address = "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48"
        usdt_address = "0xdAC17F958D2ee523a2206206994597C13D831ec7"

        amount_usdc_in = 100000000
        target_usdc_out = 70000000

        print(quoter.get_1inch_quote(usdc_address, usdt_address, amount_usdc_in, target_usdc_out))
    except Exception as e:
        logger.critical(f"Uncaught exception: {e}")
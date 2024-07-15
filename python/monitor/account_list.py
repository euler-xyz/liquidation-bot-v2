from dotenv import load_dotenv

import threading
import random
import time
import queue
import logging
import os
import json

from concurrent.futures import ThreadPoolExecutor
from web3 import Web3

load_dotenv()

logger = logging.getLogger()
logger.setLevel(logging.DEBUG)

console_handler = logging.StreamHandler()
file_handler = logging.FileHandler('account_monitor_logs.log', mode='w')

formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
console_handler.setFormatter(formatter)
file_handler.setFormatter(formatter)

logger.addHandler(console_handler)
logger.addHandler(file_handler)

w3 = Web3(Web3.HTTPProvider(os.getenv('RPC_URL')))

class Account:
    def __init__(self, address, controller):
        self.address = address
        self.controller = controller
        self.time_of_last_update = time.time()
        self.time_of_next_update = time.time()
        self.current_health_score = 1

    """
    Check account liquidity and set when the next update should be
    """
    def check_liquidity(self):
        if time.time() < self.time_of_next_update:
            # If we are here, that means the account has had a status check event prior to the scheduled update
            # Need to determine what to do
            pass

        health_score = self.get_health_score()
        self.get_time_of_next_update()
        
        return health_score
    
    """
    Calculate the health score of this account
    """
    def get_health_score(self):
        self.current_health_score = random.random() + .5
        logger.info(f"Account: Account {self.address} health score: {self.current_health_score}")
        return self.current_health_score
    
    def get_time_of_next_update(self):
        self.time_of_next_update = self.current_health_score * 10 + time.time()

        logger.info(f"Account: Account {self.address} next update scheduled for {time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(self.time_of_next_update))}")
        return self.time_of_next_update

    """
    Simulate liquidation of this account to determine if it is profitable to liquidate
    """
    def simulate_liquidation(self):
        pass

    """
    Convert to dict, used for saving state
    """
    def to_dict(self):
        return {
            "address": self.address,
            "controller": self.controller,
            "time_of_last_update": self.time_of_last_update,
            "time_of_next_update": self.time_of_next_update,
            "current_health_score": self.current_health_score
        }
    
    @staticmethod
    def from_dict(data):
        account = Account(address=data["address"], controller=data["controller"])
        account.time_of_last_update = data["time_of_last_update"]
        account.time_of_next_update = data["time_of_next_update"]
        account.current_health_score = data["current_health_score"]

        return account

class AccountMonitor:
    def __init__(self, save_interval = 30, save_path = "account_monitor_state.json"):
        self.accounts = {}
        self.update_queue = queue.PriorityQueue()
        self.condition = threading.Condition()
        self.executor = ThreadPoolExecutor(max_workers=32)
        self.running = True
        self.save_interval = save_interval
        self.save_path = save_path
        self.latest_block = 0
        self.last_saved_block = 0

    def start_queue_monitoring(self):
        save_thread = threading.Thread(target=self.periodic_save)
        save_thread.start()

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
            

    def update_account_on_status_check_event(self, address, vault):
        if address not in self.accounts or self.accounts[address].controller != vault: # If the account is not in the list or the controller has changed
            account = Account(address, vault)
            self.accounts[address] = account

            logger.info(f"AccountMonitor: Adding account {address} to account list with controller {vault}.")
        else:
            logger.info(f"AccountMonitor: Account {address} already in list with controller {vault}.")
        
        account = self.accounts[address]

        account.check_liquidity()

        next_update_time = account.time_of_next_update

        with self.condition:
            self.update_queue.put((next_update_time, address))
            self.condition.notify()
        
    
    def update_account_liquidity(self, address):
        try:
            account = self.accounts[address]

            logger.info(f"AccountMonitor: Updating account {address} liquidity.")
            
            health_score = account.check_liquidity()

            if(health_score < 1):
                logger.info(f"AccountMonitor: Account {address} is unhealthy, checking liquidation profitability.")
                account.simulate_liquidation()
                
            next_update_time = self.accounts[address].time_of_next_update

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
        state = {
            'accounts': {address: account.to_dict() for address, account in self.accounts.items()},
            'queue': list(self.update_queue.queue),
            'last_saved_block': self.latest_block,
        }
        
        if local_save:
            with open(self.save_path, 'w') as f:
                json.dump(state, f)
        else:
            # Save to remote location
            pass

        self.last_saved_block = self.latest_block

        logger.info(f"AccountMonitor: State saved at time {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime())} up to block {self.latest_block}")

    """
    Load the state of the account monitor from a json file.
    TODO: Update this in the future to be able to load from a remote file.
    """
    def load_state(self, save_path, local_save: bool = True):
        if local_save and os.path.exists(save_path):
            with open(save_path, 'r') as f:
                state = json.load(f)
            self.accounts = {address: Account.from_dict(data) for address, data in state['accounts'].items()}
            
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
    
    """
    Periodically save the state of the account monitor.
    Should be run in a standalone thread.
    """
    def periodic_save(self):
        while self.running:
            time.sleep(self.save_interval)
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
        EVC_ABI_PATH = 'lib/evk-periphery/out/EthereumVaultConnector.sol/EthereumVaultConnector.json'
        EVC_ADDRESS = os.getenv('EVC_ADDRESS')

        self.account_monitor = account_monitor

        with open(EVC_ABI_PATH, 'r') as file:
            evc_interface = json.load(file)
        
        evc_abi = evc_interface['abi']

        self.evc_instance = w3.eth.contract(address=EVC_ADDRESS, abi=evc_abi)
    
    def start_event_monitoring(self):
        while True:
            pass
    
    def scan_block_range_for_account_status_check(self, start_block, end_block):

        logger.info(f"EVCListener: Scanning blocks {start_block} to {end_block} for AccountStatusCheck events.")

        logs = self.evc_instance.events.AccountStatusCheck().get_logs(fromBlock=start_block, toBlock=end_block)

        for log in logs:
            vault_address = log['args']['controller']
            account_address = log['args']['account']

            logger.info(f"EVCListener: AccountStatusCheck event found for account {account_address} with controller {vault_address}, triggering monitor update.")

            self.account_monitor.update_account_on_status_check_event(account_address, vault_address)

        logger.info(f"EVCListener: Finished scanning blocks {start_block} to {end_block} for AccountStatusCheck events.")

        self.account_monitor.latest_block = end_block

    def batch_account_logs_on_startup(self):
        start_block = int(os.getenv('EVC_GENESIS_BLOCK'))
        
        # If the account monitor has a saved state, assume it has been loaded from that and start from the last saved block
        if self.account_monitor.last_saved_block > start_block:
            logger.info(f"EVCListener: Account monitor has saved state, starting from block {self.account_monitor.last_saved_block}.")
            start_block = self.account_monitor.last_saved_block

        current_block = w3.eth.block_number

        batch_block_size = 1000 # 1000 blocks per batch, need to decide if this is the right size

        logger.info(f"EVCListener: Starting batch scan of AccountStatusCheck events from block {start_block} to {current_block}.")

        while start_block < current_block:
            end_block = min(start_block + batch_block_size, current_block)

            self.scan_block_range_for_account_status_check(start_block, end_block)

            start_block = end_block + 1

            time.sleep(10) # Sleep in between batches to avoid rate limiting
        
        logger.info(f"EVCListener: Finished batch scan of AccountStatusCheck events from block {start_block} to {current_block}.")

if __name__ == "__main__":
    monitor = AccountMonitor()
    
    monitor.load_state("account_monitor_state.json")

    time.sleep(5)
    threading.Thread(target=monitor.start_queue_monitoring).start()
    time.sleep(5)
    monitor.update_account_on_status_check_event("0x123", "vault1")
    time.sleep(5)
    monitor.update_account_on_status_check_event("0x456", "vault2")
    time.sleep(5)
    monitor.update_account_on_status_check_event("0x789", "vault3")

    while True:
        time.sleep(1)
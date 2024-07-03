from dotenv import load_dotenv
import os
import time
import threading

from web3 import Web3

from monitor.position_list import PositionList
from monitor.vault_list import VaultList
from monitor.evc import EVC


class Monitor:
    def __init__(self, high_update_frequency, medium_update_frequency, other_update_frequency, new_position_scan_frequency, vault_scan_frequency):
        self.high_update_frequency = high_update_frequency
        self.medium_update_frequency = medium_update_frequency
        self.other_update_frequency = other_update_frequency
        self.new_position_scan_frequency = new_position_scan_frequency
        self.vault_scan_frequency = vault_scan_frequency

        self.rpc_url = os.getenv('RPC_URL')
        self.factory_address = os.getenv('FACTORY_ADDRESS')
        self.genesis_block = int(os.getenv('GENESIS_BLOCK'))

        self.vault_list = VaultList(self.rpc_url, self.factory_address, self.genesis_block)

        self.evc = EVC(os.getenv('EVC_ADDRESS'))

        self.positionList = PositionList(self.vault_list, self.evc)

        self.w3 = Web3(Web3.HTTPProvider(self.rpc_url))

    # Start the monitoring process
    # Currently using a naive health score based "sorting" into groups, then simple monitoring at specific intervals
    # TODO: Implement more sophisticated filtering/sorting
    def start(self):
        self.new_position_listener_thread = threading.Thread(target=self.start_new_position_listener)
        self.new_position_listener_thread.start()

        self.high_risk_listener_thread = threading.Thread(target=self.start_high_risk_listener)
        self.high_risk_listener_thread.start()

        self.medium_risk_listener_thread = threading.Thread(target=self.start_medium_risk_listener)
        self.medium_risk_listener_thread.start()

        self.other_position_listener_thread = threading.Thread(target=self.start_other_position_listener)
        self.other_position_listener_thread.start()

        self.vault_creation_listener_thread = threading.Thread(target=self.start_vault_creation_listener)
        self.vault_creation_listener_thread.start()

        print("Successfully started monitoring threads!\n")
    
    # Scan for new positions every 5 minutes
    def start_new_position_listener(self):
        while True:
            print("Scanning for new positions...\n")
            self.positionList.scan_for_new_positions(self.w3.eth.block_number - 30) # scan 30 blocks behind = 6 minutes
            time.sleep(self.new_position_scan_frequency * 60)
    
    # Check high risk positions every 30 seconds
    def start_high_risk_listener(self):
        while True:
            print("Checking high risk positions...\n")
            self.positionList.update_high_risk_positions()
            time.sleep(self.high_update_frequency * 60)
    
    # Check medium risk positions every 5 minutes
    def start_medium_risk_listener(self):
        while True:
            print("Checking medium risk positions...\n")
            self.positionList.update_medium_risk_positions()
            time.sleep(self.medium_update_frequency * 60)
    
    # Check other positions every 20 minutes
    def start_other_position_listener(self):
        while True:
            print("Checking other positions...\n")
            self.positionList.update_other_positions()
            time.sleep(self.other_update_frequency * 60)
    
    def start_vault_creation_listener(self):
        while True:
            print("Scanning for new vaults...\n")
            self.vault_list.scan_for_new_vaults()
            time.sleep(self.vault_scan_frequency * 60)


# if __name__ == "__main__":
#     monitor = Monitor(0.1, 5, 10, 5, 10)

#     monitor.start()
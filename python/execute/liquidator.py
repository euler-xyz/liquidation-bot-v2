from dotenv import load_dotenv
from web3 import Web3

import time
import os
import json

from monitor.monitor import Monitor
from monitor.position import Position

class Liquidator:
    def __init__(self, liquidation_contract_address: str, monitor_instance: Monitor, run_with_monitor: bool = False):
        LIQUIDATOR_ABI_PATH = 'out/Liquidator.sol/Liquidator.json'
        with open(LIQUIDATOR_ABI_PATH, 'r') as file:
            liquidation_interface = json.load(file)

        liquidation_abi = liquidation_interface['abi']
        
        load_dotenv()

        rpc_url = os.getenv('RPC_URL')

        w3 = Web3(Web3.HTTPProvider(rpc_url))

        self.w3 = w3
        self.liquidation_contract_address = liquidation_contract_address
        self.liquidation_abi = liquidation_abi

        self.liquidator_contract = w3.eth.contract(address=liquidation_contract_address, abi=liquidation_abi)

        self.monitor_instance = monitor_instance
        
        if(run_with_monitor):
            self.start()
    
    def start(self):
        while True:
            print("Checking for profitable liquidation opportunities to execute...\n")
            try:

                profitable_liquidation = self.monitor_instance.position_list.pop_profitable_liquidation()

                (vault_address,
                 violator_address, 
                 borrowed_asset_address, 
                 collateral_asset_address, 
                 amount_to_repay, 
                 expected_collateral) = profitable_liquidation.get_liquidation_data()
                
                liquidator_public_key = os.getenv('LIQUIDATOR_PUBLIC_KEY')
                liquidator_private_key = os.getenv('LIQUIDATOR_PRIVATE_KEY')

                self.execute_liquidation(vault_address,
                                        violator_address,
                                        borrowed_asset_address,
                                        collateral_asset_address,
                                        amount_to_repay,
                                        expected_collateral,
                                        b'',
                                        liquidator_public_key,
                                        liquidator_private_key)
                
            except Exception as e:
                print("No profitable liquidation opportunities found.\n")
                time.sleep(10)
                continue


    def execute_liquidation(self,
                            vault_address,
                            violator_address,
                            borrowed_asset_address,
                            collateral_asset_address, 
                            amount_to_repay,
                            expected_collateral,
                            swap_data,
                            caller_public_key,
                            caller_private_key):
        print(f"Trying to liquidate {violator_address} in vault {vault_address} with borrowed asset {borrowed_asset_address} and collateral asset {collateral_asset_address}...\n")
        
        #TODO: enable collateral & controller at EVC level for liquidation

        try:
            liquidation_tx = self.liquidator_contract.functions.liquidate({'vaultAddress': vault_address,
                                                                        'violatorAddress': violator_address,
                                                                        'borrowedAsset': borrowed_asset_address,
                                                                        'colllateralAsset': collateral_asset_address,
                                                                        'amountToRepay': amount_to_repay,
                                                                        'expectedCollateral': expected_collateral,
                                                                        'swapData': swap_data}).build_transaction({
                                                                            'chainId': 1,
                                                                            'gasPrice': self.w3.eth.gas_price,
                                                                            'from': caller_public_key,
                                                                            'nonce': self.w3.eth.get_transaction_count(caller_public_key)
                                                                            })

            signed_tx = self.w3.eth.account.sign_transaction(liquidation_tx, caller_private_key)

            tx_hash = self.w3.eth.send_raw_transaction(signed_tx.rawTransaction)

            tx_receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash)

            result = self.liquidator_contract.events.Liquidation().processReceipt(tx_receipt)

            print("Liquidation successful.\n\n")
            print("Liquidation details:\n")
            print(result[0]['args'])

            return True
        except Exception as e:

            print("Liquidation failed, see error:\n\n")
            
            print(e)

            return False
    
    def test_contract_deployment(self):
        print("Testing contract deployment...\n")

        print("Trying to get swapper address from liquidator...\n")
        print("Swapper address: " + self.liquidator_contract.functions.swapperAddress().call())
    

# if __name__ == "__main__":
#     load_dotenv()

#     rpc_url = os.getenv('RPC_URL')

#     liquidator_address = os.getenv('LIQUIDATOR_ADDRESS')
    
   

#     genesis_block = int(os.getenv('GENESIS_BLOCK'))

#     liquidator = Liquidator(rpc_url, liquidator_address)

#     liquidator.test_contract_deployment()
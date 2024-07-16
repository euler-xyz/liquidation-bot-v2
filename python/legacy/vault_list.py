from dotenv import load_dotenv

from web3 import Web3

import os
import json

from python.legacy.vault import Vault

class VaultList:


    def __init__(self, rpc_url: str, factory_address: str, genesis_block: int):

        FACTORY_ABI_PATH = 'lib/evk-periphery/out/GenericFactory.sol/GenericFactory.json'
        
        with open(FACTORY_ABI_PATH, 'r') as file:
            factory_interface = json.load(file)

        factory_abi = factory_interface['abi']
        
        w3 = Web3(Web3.HTTPProvider(rpc_url))

        self.w3 = w3
        self.genesis_block = genesis_block
        self.factory_address = factory_address
        self.factory_abi = factory_abi
        self.vault_dict = {}
        self.latest_block_number = genesis_block
        
        self.factory_contract = self.w3.eth.contract(address=Web3.to_checksum_address(self.factory_address), abi=self.factory_abi)
        
        self.scan_for_new_vaults()

    def scan_for_new_vaults(self):
        logs = self.factory_contract.events.ProxyCreated().get_logs(fromBlock=self.latest_block_number)
        for log in logs:
            vault_address = log['args']['proxy']
            new_vault = Vault(vault_address)

            self.vault_dict[vault_address] = new_vault

            print(f"Vault List: New vault found! Address: {vault_address}, underlying asset: {new_vault.underlying_asset_address}\n")

        self.latest_block_number = self.w3.eth.block_number

    def get_vault_dict(self):
        return self.vault_dict
    
    def get_vault(self, vault_address: str):
        return self.vault_dict[vault_address]
    
    def __str__(self) -> str:
        output = ''
        for vault_address, vault in self.vault_dict.items():
            output += f'Vault: {vault_address}\n'
            output += f'Underlying Asset: {vault.underlying_asset_address}\n'
            output += '-' * 50 + '\n'
        
        return output[:-1]

if __name__ == "__main__":
    load_dotenv()

    rpc_url = os.getenv('RPC_URL')

    factory_address = os.getenv('FACTORY_ADDRESS')

    genesis_block = int(os.getenv('GENESIS_BLOCK'))

    vault_dict_state = VaultList(rpc_url, factory_address, genesis_block)

    print(vault_dict_state)
   


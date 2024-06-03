from dotenv import load_dotenv
from web3 import Web3

import os
import json

class Vault:
    def __init__(self, vault_address: str):
        load_dotenv()
        self.vault_address = vault_address

        EVAULT_ABI_PATH = 'lib/evk-periphery/out/EVault.sol/EVault.json'

        with open(EVAULT_ABI_PATH, 'r') as file:
            vault_interface = json.load(file)

        vault_abi = vault_interface['abi']

        w3 = Web3(Web3.HTTPProvider(os.getenv('RPC_URL')))

        self.vault_instance = w3.eth.contract(address=vault_address, abi=vault_abi)

        self.underlying_asset_address = self.vault_instance.functions.asset().call()
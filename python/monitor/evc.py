from dotenv import load_dotenv
from web3 import Web3

import os
import json

class EVC:
    def __init__(self, evc_address: str):
        self.evc_address = evc_address

        EVC_ABI_PATH = 'lib/evk-periphery/out/EthereumVaultConnector.sol/EthereumVaultConnector.json'
        
        with open(EVC_ABI_PATH, 'r') as file:
            evc_interface = json.load(file)

        evc_abi = evc_interface['abi']

        w3 = Web3(Web3.HTTPProvider(os.getenv('RPC_URL')))

        self.instance = w3.eth.contract(address=evc_address, abi=evc_abi)

    def get_collaterals(self, account):
        return self.instance.functions.getCollaterals(account).call()

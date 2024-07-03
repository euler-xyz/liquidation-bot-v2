from dotenv import load_dotenv
from web3 import Web3

import os
import json

class Token:
    def __init__(self, token_address: str):
        self.token_address = token_address

        ERC20_ABI_PATH = 'lib/evk-periphery/out/IERC20.sol/IERC20.0.8.23.json'
        
        with open(ERC20_ABI_PATH, 'r') as file:
            ERC20_interface = json.load(file)

        token_abi = ERC20_interface['abi']

        w3 = Web3(Web3.HTTPProvider(os.getenv('RPC_URL')))

        self.instance = w3.eth.contract(address=token_address, abi=token_abi)
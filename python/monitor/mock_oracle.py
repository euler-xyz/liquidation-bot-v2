from dotenv import load_dotenv
from web3 import Web3

import os
import json

class MockOracle:
    def __init__(self, oracle_address: str):
        self.oracle_address = oracle_address

        ORACLE_ABI_PATH = 'out/MockPriceOracle.sol/MockPriceOracle.json'
        
        with open(ORACLE_ABI_PATH, 'r') as file:
            oracle_interface = json.load(file)

        oracle_abi = oracle_interface['abi']

        w3 = Web3(Web3.HTTPProvider(os.getenv('RPC_URL')))

        self.instance = w3.eth.contract(address=oracle_address, abi=oracle_abi)
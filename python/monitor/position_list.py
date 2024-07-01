from dotenv import load_dotenv

from web3 import Web3

import os
import json

from monitor.position import Position

from monitor.profitability_calculator import *

class PositionList:
    def __init__(self):
        load_dotenv()
    
        self.high_risk_positions = {}
        self.medium_risk_positions = {}
        self.other_positions = {}

        self.all_positions = {}

        EVC_ABI_PATH = 'lib/evk-periphery/out/EthereumVaultConnector.sol/EthereumVaultConnector.json'

        with open(EVC_ABI_PATH, 'r') as file:
            evc_interface = json.load(file)

        evc_abi = evc_interface['abi']

        rpc = os.getenv('RPC_URL')
        self.w3 = Web3(Web3.HTTPProvider(rpc))

        self.evc = self.w3.eth.contract(address=os.getenv('EVC_ADDRESS'), abi=evc_abi)

        self.scan_for_new_positions(int(os.getenv('GENESIS_BLOCK')))
    
    # Scan for new positions
    def scan_for_new_positions(self, from_block_number: int, to_block_number: int = 'latest'):

        logs = self.evc.events.AccountStatusCheck().get_logs(fromBlock=from_block_number, toBlock=to_block_number)

        for log in logs:
            vault_address = log['args']['controller']
            borrower_address = log['args']['account']
            
            new_position_id = hash(str(vault_address) + str(borrower_address))

            if new_position_id in self.all_positions:
                continue

            new_position = Position(vault_address, borrower_address)
            
            print(f"New position found! Vault address: {vault_address}, borrower address: {borrower_address}")

            if new_position.health_score <= 1:
                self.high_risk_positions[new_position_id] = new_position
            elif new_position.health_score <= 1.15:
                self.medium_risk_positions[new_position_id] = new_position
            else:
                self.other_positions[new_position_id] = new_position

    # Update high risk positions
    # These are positions with a health score <= 1
    def update_high_risk_positions(self):
        for id, pos in self.high_risk_positions.items():

            pos.update_liquidity()

            if pos.health_score > 1:
                self.other_positions[id] = self.high_risk_positions.pop(id)

            if pos.health_score < 1:
                max_repay, expected_yield = pos.check_liquidation()
                
                #TODO: add filter to exclude small size positions

                profitable = check_if_liquidation_profitable(pos.vault_address, pos.borrower_address, pos.borrow_asset_address, pos.collateral_asset_address, max_repay, expected_yield)
                if profitable:
                    print(f"Position in vault {pos.vault_address} is profitable to liquidate.")
    
    # Update medium risk positions
    # These are positions with a health score <= 1.15 that have potential to move to high risk
    def update_medium_risk_positions(self):
        for id, pos in self.medium_risk_positions.items():
            pos.update_liquidity()
            if pos.health_score > 1.15 or pos.health_score <= 1:
                self.medium_risk_positions.pop(id)
                if pos.health_score <= 1:
                    self.high_risk_positions[id] = pos
                else:
                    self.other_positions[id] = pos
    
    # Update other positions
    # These are positions with a health score > 1.15
    def update_other_positions(self):
        for id, pos in self.other_positions.items():
            pos.update_liquidity()
            if pos.health_score <= 1.15:
                self.other_positions.pop(id)
                if pos.health_score <= 1:
                    self.high_risk_positions[id] = pos
                else:
                    self.medium_risk_positions[id] = pos
    
    # Update all positions
    def update_all_positions(self):

        self.update_high_risk_positions()
        self.update_medium_risk_positions()
        self.update_other_positions()

        return
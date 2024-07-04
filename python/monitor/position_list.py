from dotenv import load_dotenv

from web3 import Web3

import os
import json

from monitor.position import Position

from monitor.profitability_calculator import *
from monitor.vault_list import VaultList

from monitor.evc import EVC

class PositionList:
    def __init__(self, vault_list: VaultList, evc: EVC):
        self.high_risk_positions = {}
        self.medium_risk_positions = {}
        self.other_positions = {}

        self.profitable_liquidations_queue = []

        self.all_positions = {}

        self.vault_list = vault_list

        rpc = os.getenv('RPC_URL')
        self.w3 = Web3(Web3.HTTPProvider(rpc))

        self.evc = evc

        self.scan_for_new_positions(int(os.getenv('GENESIS_BLOCK')))
    
    # Scan for new positions
    def scan_for_new_positions(self, from_block_number: int, to_block_number: int = 'latest'):

        logs = self.evc.instance.events.AccountStatusCheck().get_logs(fromBlock=from_block_number, toBlock=to_block_number)

        for log in logs:
            vault_address = log['args']['controller']
            borrower_address = log['args']['account']
            
            new_position_id = hash(str(vault_address) + str(borrower_address))

            if new_position_id in self.all_positions:
                continue
            
            collaterals = self.evc.get_collaterals(borrower_address)

            new_position = Position(self.vault_list.get_vault(vault_address), borrower_address, collateral_asset_address=collaterals[0])

            self.all_positions[new_position_id] = new_position
            
            print(f"Position List: New position found! Vault address: {vault_address}, borrower address: {borrower_address}\n")

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

            if pos.health_score < 1 and id not in self.profitable_liquidations_queue:
                max_repay, expected_yield = pos.check_liquidation()
                print(f"Position List: Possible liquidation found in vault {pos.vault.vault_address} for borrower {pos.borrower_address}...\n")
                print(f"Position List: Max repay: {max_repay}, Expected yield: {expected_yield}\n")

                #TODO: add filter to exclude small size positions

                profitable = check_if_liquidation_profitable(pos.vault.vault_address, pos.borrower_address, pos.vault.underlying_asset_address, self.vault_list.get_vault(pos.collateral_asset_address).underlying_asset_address, max_repay, expected_yield)

                if profitable:
                    print(f"Position List: Position in vault {pos.vault.vault_address} is profitable to liquidate.")
                    print(f"Position List: Borrower: {pos.borrower_address}")
                    print(f"Position List: Max repay: {max_repay}, Expected yield: {expected_yield}\n")
                    self.profitable_liquidations_queue.append(id)
    
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
    
    def get_position(self, position_id: int):
        return self.all_positions[position_id]
    
    def pop_profitable_liquidation(self):
        id = self.profitable_liquidations_queue.pop(0)
        return self.all_positions[id]
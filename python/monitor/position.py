from dotenv import load_dotenv
from web3 import Web3

import os

from monitor.vault import Vault

class Position:
    def __init__(self, controller_vault: Vault, borrower_address: str, collateral_asset_address: str):
        self.vault = controller_vault

        self.borrower_address = borrower_address

        self.current_borrow_value = 0
        self.current_collateral_value = 0
        self.health_score = 0

        self.update_liquidity()

        # TODO handle multiple collateral assets properly
        self.collateral_asset_address = collateral_asset_address

    def update_liquidity(self):
        (self.current_collateral_value, self.current_borrow_value) = self.vault.instance.functions.accountLiquidity(Web3.to_checksum_address(self.borrower_address), False).call()

        self.health_score = self.current_collateral_value / self.current_borrow_value

    def check_liquidation(self):
        (max_repay, expected_yield) = self.vault.instance.functions.checkLiquidation(Web3.to_checksum_address(os.getenv('LIQUIDATOR_PUBLIC_KEY')), self.borrower_address, self.collateral_asset_address).call()
        return (max_repay, expected_yield)
    
    def get_liquidation_data(self):
        (amount_to_repay, expected_collateral) = self.check_liquidation()
        return (self.vault.vault_address, 
            self.borrower_address, 
            self.vault.underlying_asset_address, 
            self.collateral_asset_address, 
            amount_to_repay,
            expected_collateral)

    def __str__(self):
        toStr = f"Position in vault {self.vault_address}\n"
        toStr += f"Borrower: {self.borrower_address}\n"
        toStr += f"Current Borrow Value: {self.current_borrow_value}\n"
        toStr += f"Current Collateral Value: {self.current_collateral_value}\n"
        toStr += f"Health Score: {self.health_score}\n"
        
        return toStr
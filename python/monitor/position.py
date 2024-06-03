from dotenv import load_dotenv
from web3 import Web3

import os

from monitor.vault import Vault

class Position:
    def __init__(self, controller_vault: Vault, borrower_address: str):
        
        load_dotenv()

        self.vault = controller_vault

        self.borrower_address = borrower_address

        self.current_borrow_value = 0
        self.current_collateral_value = 0
        self.health_score = 0

        self.update_liquidity()

        # TODO
        self.collateral_asset_address = None

    def update_liquidity(self):
        (self.current_collateral_value, self.current_borrow_value) = self.vault.vault_instance.functions.accountLiquidity(Web3.toChecksumAddress(self.borrower_address), True).call()

        self.health_score = self.current_collateral_value / self.current_borrow_value

    def check_liquidation(self):
        (max_repay, expected_yield) = self.vault.vault_instance.functions.checkLiquidation(Web3.to_checksum_address(os.getenv('PUBLIC_KEY'), self.borrower_address, self.collateral_asset_address)).call()
        return (max_repay, expected_yield)

    def __str__(self):
        toStr = f"Position in vault {self.vault_address}\n"
        toStr += f"Borrower: {self.borrower_address}\n"
        toStr += f"Current Borrow Value: {self.current_borrow_value}\n"
        toStr += f"Current Collateral Value: {self.current_collateral_value}\n"
        toStr += f"Health Score: {self.health_score}\n"
        
        return toStr
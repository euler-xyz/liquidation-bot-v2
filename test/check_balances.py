from web3 import Web3
import os
from dotenv import load_dotenv
from eth_abi import decode

# Load environment variables
load_dotenv()
LIQUIDATOR_EOA = os.getenv("LIQUIDATOR_EOA")

# Setup web3
w3 = Web3(Web3.HTTPProvider(os.getenv("RPC_URL")))

# Token addresses from config
TOKENS = {
    "WETH": "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2",
    "USDC": "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48",  # Add USDC if needed
    "IN_VAULT": "0x631D8E808f2c4177a8147Eaa39a4F57C47634dE8",
    "BORROW_VAULT": Web3.to_checksum_address("0xa992d3777282c44ee980e9b0ca9bd0c0e4f737af"),
    "TOKEN_IN": Web3.to_checksum_address("0x8c9532a60E0E7C6BbD2B2c1303F63aCE1c3E9811"),
    "TOKEN_BORROW": Web3.to_checksum_address("0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2")
}

# Standard ERC20 ABI for balanceOf
ERC20_ABI = [{
    "constant": True,
    "inputs": [{"name": "_owner", "type": "address"}],
    "name": "balanceOf",
    "outputs": [{"name": "balance", "type": "uint256"}],
    "type": "function"
}]

def check_balances():
    print(f"\nChecking balances for {LIQUIDATOR_EOA}...")
    
    # Check ETH balance
    eth_balance = w3.eth.get_balance(LIQUIDATOR_EOA)
    print(f"ETH: {w3.from_wei(eth_balance, 'ether')}")
    
    # Check token balances
    for name, address in TOKENS.items():
        token_contract = w3.eth.contract(address=address, abi=ERC20_ABI)
        balance = token_contract.functions.balanceOf(LIQUIDATOR_EOA).call()
        print(f"{name}: {balance}")

if __name__ == "__main__":
    check_balances() 
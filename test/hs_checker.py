from web3 import Web3
from datetime import datetime
from app.liquidation.utils import load_config, setup_w3
from app.liquidation.liquidation_bot import Vault
config = load_config()

def get_collateral_liability_values(controller,
                       account,
                       block
                       ):

    controller_vault = Vault(controller)


    print("Account: ", account)

    collateral_value, liability_value = controller_vault.instance.functions.accountLiquidity(account, True).call(block_identifier=block)

    print(f"Collateral value in block {block}: {collateral_value/10**18}")

    print(f"Liability value in block {block}: {liability_value/10**18}")
    


collateral = Web3.to_checksum_address("0x1e548CfcE5FCF17247E024eF06d32A01841fF404")
controller = Web3.to_checksum_address("0x797DD80692c3b2dAdabCe8e30C07fDE5307D48a9")
account = Web3.to_checksum_address("0x407CfF84EEaacda390Fe302c99FA5DD32521bC53")

start_block = 21603191

def get_block_timestamp(w3, block):
    timestamp = w3.eth.get_block(block).timestamp
    return datetime.fromtimestamp(timestamp)

def scan_blocks(w3, controller, account, start_block, chunk_size=100):
    current_block = start_block
    controller_vault = Vault(controller)
    
    while current_block < start_block + 17280:  # ~48 hours worth of blocks
        try:
            timestamp = get_block_timestamp(w3, current_block)
            collateral_value, liability_value = controller_vault.instance.functions.accountLiquidity(
                account, True).call(block_identifier=current_block)
            
            print("Block: %d | Time: %s" % (
                current_block,
                timestamp.strftime('%Y-%m-%d %H:%M:%S')
            ))
            print("Collateral: %f | Liability: %f" % (
                collateral_value/10**18,
                liability_value/10**18
            ))
            print("-" * 50)
            
        except Exception as e:
            print("Error at block %d: %s" % (current_block, str(e)))
        
        current_block += chunk_size

# Initialize Web3
w3 = setup_w3()

scan_blocks(w3, controller, account, start_block, chunk_size=1)

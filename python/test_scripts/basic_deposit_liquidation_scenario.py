from dotenv import load_dotenv
import os
import sys
import time
from web3 import Web3

sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

from python.legacy.vault import Vault
from python.legacy.token_test import Token
from python.legacy.evc import EVC
from python.legacy.mock_oracle import MockOracle

def test_basic_deposit_liquidation_scenario():
    load_dotenv()
    
    TEST_VAULT_1_ADDRESS = '0xf6cb30F1b333B511be23f6Fc0b733ed26030d6f7'
    TEST_VAULT_2_ADDRESS = '0x10F9509d401dedb0605616B89cfE26FA614084B7'
    MOCK_ORACLE_ADDRESS = '0x0C8542AB89c1C60D711B00F309f7EF63b5D9d6eb'
    UNIT_OF_ACCOUNT = '0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2'
    CHAIN_ID = 41337

    deployer = Web3.to_checksum_address(os.getenv('DEPLOYER_PUBLIC_KEY'))
    deployer_private_key = os.getenv('DEPLOYER_PRIVATE_KEY')

    vault_1 = Vault(TEST_VAULT_1_ADDRESS)
    token_1 = Token(vault_1.underlying_asset_address)

    vault_2 = Vault(TEST_VAULT_2_ADDRESS)
    token_2 = Token(vault_2.underlying_asset_address)

    oracle = MockOracle(MOCK_ORACLE_ADDRESS)
    
    evc = EVC(os.getenv('EVC_ADDRESS'))

    rpc_url = os.getenv('RPC_URL')

    w3 = Web3(Web3.HTTPProvider(rpc_url))

    # print("Test Scenario: Setting up Vault 1 deposits...")
    # approve_and_deposit_in_vault(vault_1, token_1, 1*10**15, deployer, deployer_private_key, w3, CHAIN_ID)

    # print("Test Scenario: Setting up Vault 2 deposits...")
    # approve_and_deposit_in_vault(vault_2, token_2, 1*10**15, deployer, deployer_private_key, w3, CHAIN_ID)

    print("Test Scenario: Checking vault balance...")
    print(f"Test Scenario: Vault balance: {vault_1.instance.functions.balanceOf(deployer).call()}")

    print("Test Scenario: Checking asset balance...")
    print(f"Test Scenario: Asset balance: {token_1.instance.functions.balanceOf(deployer).call()}")

    print("Test Scenario: Checking vault balance...")
    print(f"Test Scenario: Vault balance: {vault_2.instance.functions.balanceOf(deployer).call()}")

    print("Test Scenario: Checking asset balance...")
    print(f"Test Scenario: Asset balance: {token_2.instance.functions.balanceOf(deployer).call()}")

    # print("Test Scenario: Setting LTV")
    # set_ltv(vault_1, vault_2, int(0.9*10**4), deployer, deployer_private_key, w3, CHAIN_ID)

    print("Test Scenario: Checking LTV set correctly")
    print(f"Test Scenario: LTV: {vault_1.instance.functions.LTVBorrow(TEST_VAULT_2_ADDRESS).call()}")
    
    # print("Test Scenario: Enabling collateral")
    # enable_collateral(evc, vault_2, deployer, deployer_private_key, w3, CHAIN_ID)

    print("Test Scenario: Checking collateral status")
    print(f"Test Scenario: Collateral status: {evc.instance.functions.isCollateralEnabled(deployer, vault_2.vault_address).call()}")

    # print("Test Scenario: Enabling controller")
    # enable_controller(evc, vault_1, deployer, deployer_private_key, w3, CHAIN_ID)

    print("Test Scenario: Checking controller status")
    print(f"Test Scenario: Controller status: {evc.instance.functions.isControllerEnabled(deployer, vault_1.vault_address).call()}")

    print("Test Scenario: Checking account liquidity")
    print(f"Test Scenario: Account liquidity: {vault_1.instance.functions.accountLiquidity(deployer, False).call()}")

    # print("Test Scenario: Setting up oracle prices")
    set_asset_price(vault_1.underlying_asset_address, oracle, UNIT_OF_ACCOUNT, 1*10**18, deployer, deployer_private_key, w3, CHAIN_ID)
    # set_asset_price(vault_2.underlying_asset_address, oracle, UNIT_OF_ACCOUNT, 1*10**18, deployer, deployer_private_key, w3, CHAIN_ID)
    # set_asset_price(TEST_VAULT_1_ADDRESS, oracle, UNIT_OF_ACCOUNT, 1*10**18, deployer, deployer_private_key, w3, CHAIN_ID)
    # set_asset_price(TEST_VAULT_2_ADDRESS, oracle, UNIT_OF_ACCOUNT, 1*10**18, deployer, deployer_private_key, w3, CHAIN_ID)
    # print("Test Scenario: Asset prices set")
    
    # print("Test Scenario: Attempting borrow")
    # borrow_amount = 1*10**10
    # create_borrow(borrow_amount, vault_1, deployer, deployer_private_key, w3, CHAIN_ID)

    print("Test Scenario: Checking account liquidity")
    print(f"Test Scenario: Account liquidity: {vault_1.instance.functions.accountLiquidity(deployer, False).call()}")

    print("Test Scenario: Changing price of borrowed asset")
    # set_asset_price(vault_1.underlying_asset_address, oracle, UNIT_OF_ACCOUNT, 1*10**23, deployer, deployer_private_key, w3, CHAIN_ID)

    print("Test Scenario: Checking account liquidity after price change")
    print(f"Test Scenario: Account liquidity: {vault_1.instance.functions.accountLiquidity(deployer, False).call()}")


    
def approve_and_deposit_in_vault(vault: Vault, token: Token, amount, depositor_address, depositor_key, w3: Web3, chain_id):
    print(f"Test Scenario: Approving {amount} tokens for deposit of {token.token_address} into {vault.vault_address}...")

    approval_tx = token.instance.functions.approve(vault.vault_address, amount).build_transaction({
        'chainId': chain_id,
        'gasPrice': w3.eth.gas_price,
        'from': depositor_address,
        'nonce': w3.eth.get_transaction_count(depositor_address),
    })

    signed_tx = w3.eth.account.sign_transaction(approval_tx, depositor_key)
    tx_hash = w3.eth.send_raw_transaction(signed_tx.rawTransaction)
    
    print("Test Scenario: Approval transaction sent, waiting for mining...")
    time.sleep(15)

    while True:
        tx_receipt = w3.eth.wait_for_transaction_receipt(tx_hash)
        try:
            approval_logs = token.instance.events.Approval().process_receipt(tx_receipt)
            print("Test Scenario: Approval successful")
            break
        except:
            print("Test Scenario: Approval not yet mined, retrying...")
            time.sleep(3)
            continue

    print(f"Test Scenario: Depositing {amount} of {token.token_address} into {vault.vault_address}...")

    deposit_tx = vault.instance.functions.deposit(amount, depositor_address).build_transaction({
        'chainId': chain_id,
        'gasPrice': w3.eth.gas_price,
        'from': depositor_address,
        'nonce': w3.eth.get_transaction_count(depositor_address),
    })

    signed_tx = w3.eth.account.sign_transaction(deposit_tx, depositor_key)
    tx_hash = w3.eth.send_raw_transaction(signed_tx.rawTransaction)
    
    print("Test Scenario: Deposit transaction sent, waiting for mining...")
    time.sleep(15)

    while True:
        tx_receipt = w3.eth.wait_for_transaction_receipt(tx_hash)
        try:
            deposit_logs = vault.instance.events.Deposit().process_receipt(tx_receipt)
            print("Test Scenario: Despoit successful")
            break
        except Exception as e:
            deposit_logs = vault.instance.events.Deposit().process_receipt(tx_receipt)
            print("Test Scenario: Deposit not yet mined, retrying...")
            print("Test Scenario: Error: ", e)
            time.sleep(3)
            continue

def set_ltv(borrow_vault: Vault, collateral_vault: Vault, ltv: int, depositor_address, depositor_key, w3: Web3, chain_id):
    print(f"Test Scenario: Setting {collateral_vault.vault_address} as collateral for {borrow_vault.vault_address} with LTV {ltv}...")

    ltv_tx = borrow_vault.instance.functions.setLTV(collateral_vault.vault_address, ltv, ltv, 0).build_transaction({
        'chainId': chain_id,
        'gasPrice': w3.eth.gas_price,
        'from': depositor_address,
        'nonce': w3.eth.get_transaction_count(depositor_address),
    })

    signed_tx = w3.eth.account.sign_transaction(ltv_tx, depositor_key)
    tx_hash = w3.eth.send_raw_transaction(signed_tx.rawTransaction)
    
    print("Test Scenario: LTV transaction sent, waiting for mining...")
    time.sleep(15)

    while True:
        tx_receipt = w3.eth.wait_for_transaction_receipt(tx_hash)
        try:
            ltv_logs = borrow_vault.instance.events.GovSetLTV().process_receipt(tx_receipt)
            print("Test Scenario: LTV set successful")
            break
        except Exception as e:
            print("Test Scenario: LTV not yet mined, retrying...")
            print("Test Scenario: Error: ", e)
            time.sleep(3)
            continue

def enable_collateral(evc: EVC, collateral_vault: Vault,  depositor_address, depositor_key, w3: Web3, chain_id):
    print(f"Test Scenario: Enabling {collateral_vault.vault_address} as collateral for account {depositor_address}...")

    enable_collateral_tx = evc.instance.functions.enableCollateral(depositor_address, collateral_vault.vault_address).build_transaction({
        'chainId': chain_id,
        'gasPrice': w3.eth.gas_price,
        'from': depositor_address,
        'nonce': w3.eth.get_transaction_count(depositor_address),
    })

    signed_tx = w3.eth.account.sign_transaction(enable_collateral_tx, depositor_key)
    tx_hash = w3.eth.send_raw_transaction(signed_tx.rawTransaction)

    print("Test Scenario: Enable collateral transaction sent, waiting for mining...")
    time.sleep(15)

    while True:
        tx_receipt = w3.eth.wait_for_transaction_receipt(tx_hash)
        try:
            collateral_status_logs = evc.instance.events.CollateralStatus().process_receipt(tx_receipt)
            print("Test Scenario: Collateral enabled successful")
            break
        except Exception as e:
            print("Test Scenario: Transaction not yet mined, retrying...")
            print("Test Scenario: Error: ", e)
            time.sleep(3)
            continue

def enable_controller(evc: EVC,  controller_vault: Vault, depositor_address, depositor_key, w3: Web3, chain_id):
    print(f"Test Scenario: Enabling {controller_vault.vault_address} as controller for account {depositor_address}...")

    enable_controller_tx = evc.instance.functions.enableController(depositor_address, controller_vault.vault_address).build_transaction({
        'chainId': chain_id,
        'gasPrice': w3.eth.gas_price,
        'from': depositor_address,
        'gas': 150000, #weirdly this kept failing with out of gas error
        'nonce': w3.eth.get_transaction_count(depositor_address),
    })

    signed_tx = w3.eth.account.sign_transaction(enable_controller_tx, depositor_key)
    tx_hash = w3.eth.send_raw_transaction(signed_tx.rawTransaction)

    print("Test Scenario: Enable controller transaction sent, waiting for mining...")
    time.sleep(15)

    while True:
        tx_receipt = w3.eth.wait_for_transaction_receipt(tx_hash)
        try:
            controller_status_logs = evc.instance.events.ControllerStatus().process_receipt(tx_receipt)
            print("Test Scenario: Controller enabled successful")
            break
        except Exception as e:
            print("Test Scenario: Transaction not yet mined, retrying...")
            print("Test Scenario: Error: ", e)
            time.sleep(3)
            continue

def set_asset_price(asset_address, oracle: MockOracle, unit_of_account, price: int, depositor_address, depositor_key, w3: Web3, chain_id):
    print(f"Test Scenario: Setting price of {asset_address} in {unit_of_account} to {price}...")

    set_price_tx = oracle.instance.functions.setPrice(asset_address, unit_of_account, price).build_transaction({
        'chainId': chain_id,
        'gasPrice': w3.eth.gas_price,
        'from': depositor_address,
        'nonce': w3.eth.get_transaction_count(depositor_address),
    })

    signed_tx = w3.eth.account.sign_transaction(set_price_tx, depositor_key)
    tx_hash = w3.eth.send_raw_transaction(signed_tx.rawTransaction)
    tx_receipt = w3.eth.wait_for_transaction_receipt(tx_hash)
    
    print(f"Test Scenario: Set price transaction sent for {asset_address}, waiting for mining...")
    time.sleep(15)

def create_borrow(borrow_amount: int, borrow_vault: Vault, depositor_address, depositor_key, w3: Web3, chain_id):
    print(f"Test Scenario: Borrowing {borrow_amount} from {borrow_vault.vault_address}...")

    borrow_tx = borrow_vault.instance.functions.borrow(borrow_amount, depositor_address).build_transaction({
        'chainId': chain_id,
        'gasPrice': w3.eth.gas_price,
        'from': depositor_address,
        'nonce': w3.eth.get_transaction_count(depositor_address),
    })

    signed_tx = w3.eth.account.sign_transaction(borrow_tx, depositor_key)
    tx_hash = w3.eth.send_raw_transaction(signed_tx.rawTransaction)
    while True:
        tx_receipt = w3.eth.wait_for_transaction_receipt(tx_hash)
        try:
            borrow_logs = borrow_vault.instance.events.Borrow().process_receipt(tx_receipt)
            print("Test Scenario: Controller enabled successful")
            break
        except Exception as e:
            print("Test Scenario: Transaction not yet mined, retrying...")
            print("Test Scenario: Error: ", e)
            time.sleep(3)
            continue


if __name__ == "__main__":
    test_basic_deposit_liquidation_scenario()
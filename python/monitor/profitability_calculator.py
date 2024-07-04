from dotenv import load_dotenv
import time

from web3 import Web3
import requests

import os
import json

def check_if_liquidation_profitable(vault_address: str, violator_address: str, repay_asset_address: str, collateral_asset_address: str, amount_to_repay: int, expected_collateral: int):
    # TODO: adjust for overswapping, currently assumes we swap everything into repay asset
    swap_output = get_1inch_quote(collateral_asset_address, repay_asset_address, expected_collateral)

    if swap_output < amount_to_repay:
        return False
    
    rpc_url = os.getenv('RPC_URL')
    w3 = Web3(Web3.HTTPProvider(rpc_url))

    LIQUIDATOR_ABI_PATH = 'out/Liquidator.sol/Liquidator.json'
    
    with open(LIQUIDATOR_ABI_PATH, 'r') as file:
        liquidation_interface = json.load(file)

    liquidation_abi = liquidation_interface['abi']
    liquidation_contract_address = os.getenv('LIQUIDATION_CONTRACT_ADDRESS')

    liquidator_contract = w3.eth.contract(address=liquidation_contract_address, abi=liquidation_abi)

    public_key = os.getenv('LIQUIDATOR_PUBLIC_KEY')

    liquidation_simulation_tx = liquidator_contract.functions.liquidate((vault_address,
                                                                        violator_address,
                                                                        repay_asset_address,
                                                                        collateral_asset_address,
                                                                        amount_to_repay,
                                                                        expected_collateral,
                                                                        b''
                                                                        )).build_transaction({
                                                                            'chainId': 41337,
                                                                            'gasPrice': w3.eth.gas_price,
                                                                            'from': public_key,
                                                                            'nonce': w3.eth.get_transaction_count(public_key),
                                                                            'to': liquidation_contract_address
                                                                            })
    
    estimated_gas = w3.eth.estimate_gas(liquidation_simulation_tx)

    assets_remaining_post_repay = swap_output - amount_to_repay

    WETH_ADDRESS = os.getenv('WETH_ADDRESS')
    time.sleep(1)
    if get_1inch_quote(repay_asset_address, WETH_ADDRESS, assets_remaining_post_repay) > estimated_gas:
        return True

def get_optimal_swap_path(asset_in: str, asset_out: str, amount: int):
    return []

def get_1inch_quote(asset_in: str, asset_out: str, amount_in: int):
    api_key = os.getenv('1INCH_API_KEY')
    apiUrl = "https://api.1inch.dev/swap/v6.0/1/quote"
    headers = { "Authorization": f"Bearer {api_key}" }
    params = {
        "src": asset_in,
        "dst": asset_out,
        "amount": amount_in
    }

    print(f"Profit Calculator: Requesting 1inch quote for {amount_in} {asset_in} to {asset_out}\n")

    response = requests.get(apiUrl, headers=headers, params=params)

    if response.status_code == 200:
        try:
            response_json = response.json()
            print("Profit Calculator: 1inch response: ", response_json, "\n")
            return int(response_json['dstAmount'])
        except ValueError as e:
            print(f"Profit Calculator: Error decoding JSON: {e}\n")
            return None
    else:
        print(f"Profit Calculator: API request failed with status code {response.status_code}: {response.text}\n")
        return None


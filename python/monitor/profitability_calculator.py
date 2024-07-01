from dotenv import load_dotenv

from web3 import Web3
import requests

import os
import json

def check_if_liquidation_profitable(vault_address: str, violator_address: str, repay_asset_address: str, collateral_asset_address: str, amount_to_repay: int, expected_collateral: int):
    load_dotenv()

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

    public_key = os.getenv('PUBLIC_KEY')

    liquidation_simulation_tx = liquidator_contract.functions.liquidate({'vaultAddress': vault_address,
                                                                        'violatorAddress': violator_address,
                                                                        'borrowedAsset': repay_asset_address,
                                                                        'colllateralAsset': collateral_asset_address,
                                                                        'amountToRepay': amount_to_repay,
                                                                        'expectedCollateral': expected_collateral,
                                                                        'swapData': []
                                                                        }).buildTransaction({
                                                                            'chainId': 1,
                                                                            'gasPrice': w3.eth.gas_price,
                                                                            'from': public_key,
                                                                            'nonce': w3.eth.get_transaction_count(public_key)
                                                                            })
    
    estimated_gas = w3.eth.estimate_gas(liquidation_simulation_tx)

    assets_remaining_post_repay = swap_output - amount_to_repay

    WETH_ADDRESS = os.getenv('WETH_ADDRESS')
    
    if get_1inch_quote(repay_asset_address, WETH_ADDRESS, assets_remaining_post_repay) > estimated_gas:
        return True

def get_optimal_swap_path(asset_in: str, asset_out: str, amount: int):
    return []

def get_1inch_quote(asset_in: str, asset_out: str, amount_in: int):
    load_dotenv()

    api_key = os.getenv('1INCH_API_KEY')

    apiUrl = "https://api.1inch.dev/swap/v6.0/1/quote"

    requestOptions = {
        "headers": { "Authorization": f"Bearer {api_key}" },
        "params": {
            "src": asset_in,
            "dst": asset_out,
            "amount": amount_in
            }
    }
    headers = requestOptions.get("headers", {})
    params = requestOptions.get("params", {})

    response_json = requests.get(apiUrl, headers=headers, params=params).json()

    return int(response_json['dstAmount'])
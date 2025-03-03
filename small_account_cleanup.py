import requests, time
from app.liquidation.utils import create_contract_instance
from app.liquidation.liquidation_bot import Vault, Quoter

from app.liquidation.config_loader import load_chain_config

config = load_chain_config(1)

collateral_vault = Vault("0xbC4B4AC47582c3E38Ce5940B80Da65401F4628f1", config)
borrow_vault = Vault("0x056f3a2E41d2778D3a0c0714439c53af2987718E", config)

def get_small_accounts():
    url = "https://healthdata.euler.finance/liquidation/allPositions"
    borrow_vault_symbol = "ecbBTC-3"

    response = requests.get(url)
    data = response.json()
    
    count = 0

    small_account_addresses = []
    for account in data:
        if account["vault_symbol"] == borrow_vault_symbol and account["health_score"] < 1:
            small_account_addresses.append(account["account_address"])
            count += 1
        if account["health_score"] > 1 or count > 50:
            print("Number of small accounts:", count)
            break
    return small_account_addresses

small_account_addresses = get_small_accounts()

total_yield = 0
total_repay = 0
for address in small_account_addresses:
    repay_amount, yield_amount = borrow_vault.check_liquidation(address, collateral_vault.address, config.LIQUIDATOR_EOA)
    total_yield += yield_amount
    total_repay += repay_amount

print("Total yield:", total_yield)
print("Total repay:", total_repay)

total_in_assets = collateral_vault.convert_to_assets(total_yield)

swap_api_response = Quoter.get_swap_api_quote(
            chain_id = config.CHAIN_ID,
            token_in = collateral_vault.underlying_asset_address,
            token_out = borrow_vault.underlying_asset_address,
            amount = int(total_in_assets *.999),
            min_amount_out = total_repay,
            receiver = config.SWAPPER,
            vault_in = collateral_vault.address,
            account_in = config.SWAPPER,
            account_out = config.SWAPPER,
            swapper_mode = "0",
            slippage = config.SWAP_SLIPPAGE,
            deadline = int(time.time()) + config.SWAP_DEADLINE,
            is_repay = False,
            current_debt = total_repay,
            target_debt = 0,
            config=config
        )

print(swap_api_response)

swap_data = []
for _, item in enumerate(swap_api_response["swap"]["multicallItems"]):
    if item["functionName"] != "swap":
        continue
    swap_data.append(item["data"])

params = (
        small_account_addresses[0],
        borrow_vault.address,
        borrow_vault.underlying_asset_address,
        collateral_vault.address,
        collateral_vault.underlying_asset_address,
        total_repay,
        total_yield,
        config.LIQUIDATOR_EOA
)

liquidation_contract_adddress = "0x99087bC4D15f805372d415F2384A051Ad4c9aaE2"

liquidator = create_contract_instance(liquidation_contract_adddress, "out/SmallAccountLiquidator.sol/Liquidator.json", config)

liquidation_tx = liquidator.functions.liquidate(params, swap_data, small_account_addresses).build_transaction({
    "chainId": config.CHAIN_ID,
    "gasPrice": int(config.w3.eth.gas_price * 1.2),
    "from": config.LIQUIDATOR_EOA,
    "nonce": config.w3.eth.get_transaction_count(config.LIQUIDATOR_EOA)
})

estimated_gas = config.w3.eth.estimate_gas(liquidation_tx)
gas_price_gwei = config.w3.eth.gas_price / 1e9
print("Current gas price: %.1f gwei" % gas_price_gwei)
eth_cost = (estimated_gas * gas_price_gwei) / 1e9

# Rough ETH price estimate - in production you'd want to get this from an oracle/API
ETH_PRICE_USD = 2200  
gas_cost_usd = eth_cost * ETH_PRICE_USD

print("Estimated gas: %d" % estimated_gas)
print("Gas cost: %f ETH ($%.2f)" % (eth_cost, gas_cost_usd))
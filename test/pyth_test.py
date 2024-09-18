from app.liquidation.utils import make_api_request, load_config, create_contract_instance
from web3 import Web3

pyth_url = "https://hermes.pyth.network/v2/"

headers = {}

price_update_input_url = pyth_url + "updates/price/latest?"

# feeds = ["ca3ba9a619a4b3755c10ac7d5e760275aa95e9823d38a84fedd416856cdba37c",
#          "6ec879b1e9963de5ee97e9c8710b742d6228252a5e2ca12d4ae81d7fe5ee8c5d",
#          "e393449f6aff8a4b6d3e1165a7c9ebec103685f3b41e60db4277b5b6d10e7326"]

feeds = ['ca3ba9a619a4b3755c10ac7d5e760275aa95e9823d38a84fedd416856cdba37c', '6ec879b1e9963de5ee97e9c8710b742d6228252a5e2ca12d4ae81d7fe5ee8c5d', 'e393449f6aff8a4b6d3e1165a7c9ebec103685f3b41e60db4277b5b6d10e7326', 'eaa020c61cc479712813461ce153894a96a6c00b21ed0cfc2798d1f9a9e9c94a']


print(feeds)

for feed in feeds:
    price_update_input_url += "ids[]=" + feed + "&"

price_update_input_url = price_update_input_url[:-1]

return_data = make_api_request(price_update_input_url, {}, {})

update_data = "0x" + return_data["binary"]["data"][0]

config = load_config()

pyth = create_contract_instance(config.PYTH, config.PYTH_ABI_PATH)

update_fee = pyth.functions.getUpdateFee([update_data]).call()

print(update_fee)

liquidator = create_contract_instance(config.LIQUIDATOR_CONTRACT, config.LIQUIDATOR_ABI_PATH)

print(liquidator.functions.PYTH().call())
print(liquidator.functions.evcAddress().call())

vault_address = Web3.to_checksum_address("0xce45EF0414dE3516cAF1BCf937bF7F2Cf67873De")
account_address = Web3.to_checksum_address("0xA5f0f68dCc5bE108126d79ded881ef2993841c2f")

vault = create_contract_instance(vault_address, config.EVAULT_ABI_PATH)

print("update data: ", update_data)

result = liquidator.functions.simulate_pyth_update_and_get_account_status(
    [update_data], update_fee, vault_address, account_address
    ).call(
        {"value": update_fee}
    )

print(result)
from app.liquidation.utils import make_api_request, load_config, create_contract_instance

pyth_url = "https://hermes.pyth.network/v2/"

headers = {}

assets = ["eth", "btc"]

feeds = []
params = {"query":"btc", "asset_type":"crypto"}

for asset in assets:
    params["query"] = asset
    price_feeds = make_api_request(pyth_url + "price_feeds", headers, params)
    feeds.append(next(feed["id"] for feed in price_feeds if feed["attributes"].get("base").lower() == params["query"].lower()))

price_update_input_url = pyth_url + "updates/price/latest?"

print(feeds)

for feed in feeds:
    price_update_input_url += "ids[]=" + feed + "&"

price_update_input_url = price_update_input_url[:-1]

return_data = make_api_request(price_update_input_url, {}, {})

update_data = '0x' + return_data['binary']['data'][0]

config = load_config()

pyth = create_contract_instance(config.PYTH, config.PYTH_ABI_PATH)

update_fee = pyth.functions.getUpdateFee([update_data]).call()

print(update_fee)

liquidator = create_contract_instance(config.LIQUIDATOR_CONTRACT, config.LIQUIDATOR_ABI_PATH)

vault_address = "0xD8b27CF359b7D15710a5BE299AF6e7Bf904984C2"
account_address = "0x831429a969928a2780b5c447118f5531C4dF06F6"

vault = create_contract_instance(vault_address, config.EVAULT_ABI_PATH)
result = vault.functions.accountLiquidity(account_address, True).call()

oracle_address = vault.functions.oracle().call()
# oracle_address = "0x680922A0BEB9701A92B97C4e5B6e7f1A4a3AdF8A"

oracle = create_contract_instance(oracle_address, config.ORACLE_ABI_PATH)
name = oracle.functions.name().call()
print(name)

feed_id = oracle.functions.feedId().call()
print(feed_id)
feed_id_hex = feed_id.hex()
print(feed_id_hex)

# result = liquidator.functions.simulate_pyth_update_and_get_account_status([update_data], update_fee, vault_address, account_address).call()

# print(result)


# test_vault_address = "0x5229dFB54965EC0DFE2C787a735f7D6cc569309B"
# test_vault = Vault(test_vault_address)

# test_feed_ids = PythHandler.get_feed_ids(test_vault)
# print("IDs:", test_feed_ids)

# test_update_data = PythHandler.get_pyth_update_data(test_feed_ids)
# print("Data:", test_update_data)

# update_fee = PythHandler.get_pyth_update_fee(test_update_data)
# print("Update fee:", update_fee)

# liquidator = create_contract_instance(config.LIQUIDATOR_CONTRACT, config.LIQUIDATOR_ABI_PATH)

# actual_vault_address = "0x577e289F663A4E29c231135c09d6a0713ce7AAff"
# account_address = "0x37B5559c63821820EaAC5FF770e5C421d6A2676B"
# call_result = liquidator.functions.simulate_pyth_update_and_get_account_status(
#     [test_update_data], update_fee, actual_vault_address, account_address
#     ).call({
#         "value": update_fee
#     })
# print(call_result)
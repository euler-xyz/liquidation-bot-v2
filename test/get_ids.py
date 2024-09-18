from app.liquidation.utils import load_config, create_contract_instance
from app.liquidation.liquidation_bot import Vault
test_vault = Vault("0xce45EF0414dE3516cAF1BCf937bF7F2Cf67873De")
config = load_config()

def get_feed_ids(vault):
    oracle_address = vault.oracle_address
    oracle = create_contract_instance(oracle_address, config.ORACLE_ABI_PATH)

    unit_of_account = vault.unit_of_account

    collateral_vault_list = vault.get_ltv_list()
    asset_list = [Vault(collateral_vault).underlying_asset_address for collateral_vault in collateral_vault_list]

    feed_ids = []
    asset_list.append(vault.underlying_asset_address)

    for asset in asset_list:
        print("Collateral:", asset)
        configured_oracle_address = oracle.functions.getConfiguredOracle(asset, unit_of_account).call()
        configured_oracle = create_contract_instance(configured_oracle_address, config.ORACLE_ABI_PATH)
        
        try:
            configured_oracle_name = configured_oracle.functions.name().call()
        except Exception as ex:
            continue
        if configured_oracle_name == "PythOracle":
            feed_ids.append(configured_oracle.functions.feedId().call().hex())

    return feed_ids

print(get_feed_ids(test_vault))
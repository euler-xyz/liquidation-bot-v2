from web3 import Web3
from app.liquidation.utils import load_config, create_contract_instance
from app.liquidation.liquidation_bot import Vault
config = load_config()

def get_bonus_analysis(collateral,
                       controller,
                       liquidated_account,
                       liquidation_block,
                       repay_amount,
                       yield_amount
                       ):

    collateral_vault = Vault(collateral)
    controller_vault = Vault(controller)

    oracle = create_contract_instance(controller_vault.oracle_address, config.ORACLE_ABI_PATH)

    print("Violator: ", liquidated_account)
    print("USDC repay amount: ", repay_amount / 10**6)
    print("USD0++ Yield (shares): ", yield_amount / 10**18)

    yield_amount_in_assets = collateral_vault.instance.functions.convertToAssets(yield_amount).call(block_identifier=liquidation_block)

    print("USD0++ Yield (assets): ", yield_amount_in_assets / 10**18)

    borrow_repay_in_uoa = oracle.functions.getQuote(repay_amount, controller_vault.underlying_asset_address, controller_vault.unit_of_account).call(block_identifier=liquidation_block)

    print("USDC Repay in Unit of Account: $%.2f" % (borrow_repay_in_uoa / 10**18))
    
    yield_amount_in_uoa = oracle.functions.getQuote(yield_amount_in_assets, collateral_vault.underlying_asset_address, controller_vault.unit_of_account).call(block_identifier=liquidation_block)

    print("USD0++ yield in Unit of Account: $%.2f" % (yield_amount_in_uoa / 10**18))

    bonus_amount_in_uoa = yield_amount_in_uoa - borrow_repay_in_uoa

    print("Bonus amount in Unit of Account: $%.2f" % (bonus_amount_in_uoa / 10**18))
    return bonus_amount_in_uoa


collateral = Web3.to_checksum_address("0x6D671B9c618D5486814FEb777552BA723F1A235C")
controller = Web3.to_checksum_address("0xe0a80d35bB6618CBA260120b279d357978c42BCE")
liquidated_account = Web3.to_checksum_address("0x72518B73E4AE5e155F47891c84faBC385303AaD6")
liquidation_block = 21592841
repay_amount = 34575909851
yield_amount = 38269088514846088944733

b1 = get_bonus_analysis(collateral, controller, liquidated_account, liquidation_block, repay_amount, yield_amount)

print("\n")

liquidated_account = Web3.to_checksum_address("0xc7200595b2d02771B11838F8DfFFB183b05bd706")
liquidation_block = 21593239
repay_amount = 8646791881
yield_amount = 9770251795103720420242

b2 = get_bonus_analysis(collateral, controller, liquidated_account, liquidation_block, repay_amount, yield_amount)

print("\n")

liquidated_account = Web3.to_checksum_address("0x32ffF3e55A17e44D18e04b44b3190044867BC0a7")
liquidation_block = 21593528
repay_amount = 17580103387
yield_amount = 20358117050877877223332

b3 = get_bonus_analysis(collateral, controller, liquidated_account, liquidation_block, repay_amount, yield_amount)

print("Total bonus amount: $%.2f" % ((b1 + b2 + b3)  / 10**18))
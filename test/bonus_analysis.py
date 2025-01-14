from web3 import Web3
from app.liquidation.utils import load_config, create_contract_instance
from app.liquidation.liquidation_bot import Vault
config = load_config()

def get_bonus_analysis(collateral,
                       controller,
                       liquidated_account,
                       liquidation_block,
                       repay_amount,
                       yield_amount,
                       tx
                       ):

    collateral_vault = Vault(collateral)
    controller_vault = Vault(controller)
    print ("\n")
    oracle = create_contract_instance(controller_vault.oracle_address, config.ORACLE_ABI_PATH)
    print("Violator: ", liquidated_account)
    basescan_link = "https://basescan.org/tx/" + tx
    
    print("Liquidation Transaction: ", basescan_link)
    print("WETH repay amount: ", repay_amount / 10**18)
    print("USDC Yield (shares): ", yield_amount / 10**6)

    yield_amount_in_assets = collateral_vault.instance.functions.convertToAssets(yield_amount).call(block_identifier=liquidation_block)

    print("USDC Yield (assets): ", yield_amount_in_assets / 10**6)

    borrow_repay_in_uoa = oracle.functions.getQuote(repay_amount, controller_vault.underlying_asset_address, controller_vault.unit_of_account).call(block_identifier=liquidation_block)

    print("WETH Repay in Unit of Account: $%.2f" % (borrow_repay_in_uoa / 10**18))
    
    yield_amount_in_uoa = oracle.functions.getQuote(yield_amount_in_assets, collateral_vault.underlying_asset_address, controller_vault.unit_of_account).call(block_identifier=liquidation_block)

    print("USDC yield in Unit of Account: $%.2f" % (yield_amount_in_uoa / 10**18))

    bonus_amount_in_uoa = yield_amount_in_uoa - borrow_repay_in_uoa

    print("Bonus amount in Unit of Account: $%.2f" % (bonus_amount_in_uoa / 10**18))
    print("Bonus percentage: %.4f%%" % ((bonus_amount_in_uoa / yield_amount_in_uoa) * 100))
    return bonus_amount_in_uoa, borrow_repay_in_uoa, yield_amount_in_uoa

collateral = Web3.to_checksum_address("0x0A1a3b5f2041F33522C4efc754a7D096f880eE16")
controller = Web3.to_checksum_address("0x859160DB5841E5cfB8D3f144C6b3381A85A4b410")
liquidated_account = Web3.to_checksum_address("0xa6D5076f10C550eaF85eD71efef22709345FC1F1")
tx = "0x08f9adcb104ef6267ccff5cd289a978b4b2988a09413a62b01c57a65e28c3c5b"
liquidation_block = 25006771
repay_amount = 7947991186067694
yield_amount = 24743504

b1, d1, y1 = get_bonus_analysis(collateral, controller, liquidated_account, liquidation_block, repay_amount, yield_amount, tx)


liquidated_account = Web3.to_checksum_address("0x177a20555E7E2C65Ff12c54b23178FEefEe49939")
tx = "0x385151b2834c14f56f0fb0a5d109def449bc8865190db2187533f57b78322dfc"
liquidation_block = 25008497
repay_amount = 3348002623341321
yield_amount = 10500546

b2, d2, y2 = get_bonus_analysis(collateral, controller, liquidated_account, liquidation_block, repay_amount, yield_amount, tx)

liquidated_account = Web3.to_checksum_address("0xb7ee3eC90520B34099E9b015640a97180c339776")
tx = "0x1163ea2ade84e624e7bc1f760beb9c7b0309e533f07862e33d0f572e4a68b552"
liquidation_block = 25008616
repay_amount = 6798868708428299
yield_amount = 21284560

b3, d3, y3 = get_bonus_analysis(collateral, controller, liquidated_account, liquidation_block, repay_amount, yield_amount, tx)

liquidated_account = Web3.to_checksum_address("0x59Ae0dE4bAE0Ba8Dcf1799adCC206F76C9AeA8e1")
tx = "0x272456fdbbd532706e111132cbc24b5437bb92b2cba526ac507e556e50aac48f"
liquidation_block = 25008485
repay_amount = 271954745926907
yield_amount = 851383

b4, d4, y4 = get_bonus_analysis(collateral, controller, liquidated_account, liquidation_block, repay_amount, yield_amount, tx)


liquidated_account = Web3.to_checksum_address("0x6F4109bF65c9f896A43A11F00E65bF5Cc75C9bcb")
tx = "0x7d9864a51e021ad721767be5064e58b5b1352cb589d1ff33b6d55d3b0e4d4d1f"
liquidation_block = 25008887
repay_amount = 6850932391436746
yield_amount = 21508971

b5, d5, y5 = get_bonus_analysis(collateral, controller, liquidated_account, liquidation_block, repay_amount, yield_amount, tx)

liquidated_account = Web3.to_checksum_address("0x52B4868B362aDc3365b9A110ecbfe71e2b36bAB3")
tx = "0xbce9c2274d4c896ec7fcde5fb75855d531e4596d1c6be677c2ba91c1ccfdee05"
liquidation_block = 25008925
repay_amount = 6794847545545088
yield_amount = 21445350

b6, d6, y6 = get_bonus_analysis(collateral, controller, liquidated_account, liquidation_block, repay_amount, yield_amount, tx)

liquidated_account = Web3.to_checksum_address("0x52B4868B362aDc3365b9A110ecbfe71e2b36bAB3")
tx = "0xc6ddaac0c9189ea0818e7856a67e55f0aa91f69d02c39be0d4f73ff74c6910c5"
liquidation_block = 25008951
repay_amount = 8147418967264884
yield_amount = 25672433

b7, d7, y7 = get_bonus_analysis(collateral, controller, liquidated_account, liquidation_block, repay_amount, yield_amount, tx)


liquidated_account = Web3.to_checksum_address("0xa373Fd721f0fD65c132f2FC91A0D434f98b9acbA")
tx = "0x79274b8bb566ec9e85f4faae71f30f14a2e20f3f380adc963e33827d2d91cbb6"
liquidation_block = 25008964
repay_amount = 5911210128022998
yield_amount = 18594242

b8, d8, y8 = get_bonus_analysis(collateral, controller, liquidated_account, liquidation_block, repay_amount, yield_amount, tx)

liquidated_account = Web3.to_checksum_address("0x254069CB5D76F7ab86a13153c6C64bA3795350bd")
tx = "0xb315a8757ec76bbb8c869b7375874847fa6d33e7d7417807b6fa5c71baa05777"
liquidation_block = 25008933
repay_amount = 270887122993
yield_amount = 852

b9, d9, y9 = get_bonus_analysis(collateral, controller, liquidated_account, liquidation_block, repay_amount, yield_amount, tx)

print("Total bonus amount: $%.2f" % ((b1 + b2 + b3 + b4 + b5 + b6 + b7 + b8 + b9) / 10**18))
print("Total borrow repaid: $%.2f" % ((d1 + d2 + d3 + d4 + d5 + d6 + d7 + d8 + d9) / 10**18))
print("Total yield amount: $%.2f" % ((y1 + y2 + y3 + y4 + y5 + y6 + y7 + y8 + y9) / 10**18))
print("Average bonus percentage: %.4f%%" % (((b1 + b2 + b3 + b4 + b5 + b6 + b7 + b8 + b9) / (y1 + y2 + y3 + y4 + y5 + y6 + y7 + y8 + y9)) * 100))


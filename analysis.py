from app.liquidation.utils import load_config, setup_w3, create_contract_instance

config = load_config()
w3 = setup_w3()

cbbtc_oracle_address = w3.to_checksum_address("0xedcD625e06c487A68b5d9f2a5b020E9BE00b95A7")
cbbtc_oracle = create_contract_instance(cbbtc_oracle_address, config.ORACLE_ABI_PATH)

lbtc_oracle_address = w3.to_checksum_address("0x075E6ffE3De2104c964bE36cedAC33477Ad39621")
lbtc_oracle = create_contract_instance(lbtc_oracle_address, config.ORACLE_ABI_PATH)

cbbtc = w3.to_checksum_address("0xcbB7C0000aB88B473b1f5aFd9ef808440eed33Bf")
lbtc = w3.to_checksum_address("0xecAc9C5F704e954931349Da37F60E39f515c11c1")
usd = w3.to_checksum_address("0x0000000000000000000000000000000000000348")

block_number = 27163158
cbbtc_amount = 896418
lbtc_amount = 875385

cbbtc_value = cbbtc_oracle.functions.getQuote(cbbtc_amount, cbbtc, usd).call(block_identifier=block_number)
lbtc_value = lbtc_oracle.functions.getQuote(lbtc_amount, lbtc, usd).call(block_identifier=block_number)

print(cbbtc_value)
print(lbtc_value)
# Euler Liquidation Bot

Basic bot performing liquidations on the Euler platform. [Liquidation docs.](https://docs.euler.finance/euler-vault-kit-white-paper/#liquidation)

### Installation

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
forge install
forge build
cd lib
forge build
cd ..
```

Create /logs and /state folders in the base directory
You may need to change your python interpreter to the venv interpreter to remove package warnings

### TODO:
- Smarter oracle checking - pull based, pricing
- Fallback to Uniswap if no quote
- Filter for smaller/non profitable positions
- Set up liquidation script as flask API

### Configuration

Make sure to build the contracts in both src and lib to have the correct ABIs loaded from the evk-periphery installation

Configuration through `.env` file:

- `RPC_URL` - RPC provider endpoint (Infura, Rivet, Alchemy etc.).
- `EVC_ADDRESS, FACTORY_ADDRESS, SWAPPER_ADDRESS, SWAP_VERIFIER_ADDRESS` - Relevant EVC/EVK Addresses
- `GENESIS_BLOCK` - EVC deployment block number
- `DEPLOYER_PUBLIC_KEY, DEPLOYER_PRIVATE_KEY` - public/private key of EOA that deployed accounts for testing
- `LIQUIDATOR_PUBLIC_KEY, LIQUIDATOR_PRIVATE_KEY` - public/private key of EOA that will be used to liquidate
- `LIQUIDATOR_CONTRACT_ADDRESS` - address of deployed liquidator contract
- `API_KEY_1INCH` - key for 1inch API


### Deploying

```bash
forge script contracts/DeployLiquidator.sol --rpc-url https://virtual.mainnet.rpc.tenderly.co/24f051ac-9429-419a-890e-c5dc56bf2649 --broadcast --ffi -vvv --slow
```

```bash
forge script contracts/DeployLiquidator.sol --rpc-url $RPC_URL --broadcast --ffi -vvv --slow
```

```bash
forge script test/LiquidationSetupWithVaultCreated.sol --rpc-url $RPC_URL --broadcast --ffi -vvv --slow --evm-version shanghai
```
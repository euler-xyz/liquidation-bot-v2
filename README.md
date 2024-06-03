# Euler Liquidation Bot

Basic bot performing liquidations on the Euler platform. [Liquidation docs.](https://docs.euler.finance/euler-vault-kit-white-paper/#liquidation)

### Installation

```bash
pip install -r requirements.txt
forge install
forge build
cd lib
forge build
cd ..
```


### Configuration

Make sure to build the contracts in both src and lib to have the correct ABIs loaded from the evk-periphery installation

Configuration through `.env` file:

- `RPC_URL` - RPC provider endpoint (Infura, Rivet, Alchemy etc.).
- `EVC_ADDRESS, FACTORY_ADDRESS, SWAPPER_ADDRESS, SWAP_VERIFIER_ADDRESS` - Relevant EVC/EVK Addresses
- `GENESIS_BLOCK` - EVC deployment block number
- `PUBLIC_KEY, PRIVATE_KEY` - public/private key of EOA executing transactions
- `LIQUIDATOR_ADDRESS` - address of deployed liquidator contract
- `1INCH_API_KEY` - key for 1inch API


### Deploying

```bash
forge script contracts/DeployLiquidator.sol --rpc-url https://virtual.mainnet.rpc.tenderly.co/24f051ac-9429-419a-890e-c5dc56bf2649 --broadcast --ffi -vvv --slow
```
# Euler Liquidation Bot

Bot to perform liquidations on the Euler platform. [Liquidation docs.](https://docs.euler.finance/euler-vault-kit-white-paper/#liquidation)

### Installation

The bot can be run either via building a docker container or manually.

Before running either, setup a .env file by copying the .env.example file and updating with the relevant contract addresses, an EOA private key, & API keys. Then, check config.yaml to make sure parameters, contracts, and ABI paths have been set up correctly.

#### Docker
After creating the .env file, the below command will create a container, install all dependencies, and start the liquidation bot:
`docker compose build --progress=plain && docker compose up`


#### Running locally
To run locally, we need to install some dependencies and build the contracts. This will setup a python virtual environment for installing dependencies. The below command assumes we have foundry installed, which can installed from the [Foundry Book](https://book.getfoundry.sh/).

Setup:
```bash
foundryup
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
forge install && forge build
cd lib/evk-periphery && forge build && cd ../..
mkdir /logs /state
```

Run:
`python python/liquidation_bot.py`

### TODO:
- Smarter oracle checking - pull based, pricing
- Fallback to Uniswap if no quote
- Filter for smaller/non profitable positions
- Transfer shares to target address rather than withdraw
- Update flow for taking on the position rather than swapping (second function in contract)

### Configuration

Make sure to build the contracts in both src and lib to have the correct ABIs loaded from the evk-periphery installation

Configuration through `.env` file:

REQUIRED:
- `LIQUIDATOR_ADDRESS, LIQUIDATOR_PRIVATE_KEY` - public/private key of EOA that will be used to liquidate

- `RPC_URL` - RPC provider endpoint (Infura, Rivet, Alchemy etc.)

- `API_KEY_1INCH` - API key for 1inch to help with executing swaps

OPTIONAL:
- `SLACK_WEBHOOK_URL` - Optional URL to post notifications to slack
- `LIQUIDATION_UI_URL` - Optional, can include a link in slack notifications to manually liquidate a position
- `DEPOSITOR_ADDRESS, DEPOSITOR_PRIVATE_KEY, BORROWER_ADDRESS, BORROWER_PRIVATE_KEY` - Optional, for running 


Configuration in `config.yaml` file:

- `LOGS_PATH, SAVE_STATE_PATH` - Path directing to save location for Logs & Save State
- `SAVE_INTERVAL` - How often state should be saved

- `HS_LOWER_BOUND, HS_UPPER_BOUND` - Bounds below and above which an account should be updated at the min/max update interval
- `MIN_UPDATE_INTERVAL, MAX_UPDATE_INTERVAL` - Min/Max time between account updates

- `LOW_HEALTH_REPORT_INTERVAL` - Interval between low health reports
- `SLACK_REPORT_HEALTH_SCORE` - Threshold to include an account on the low health report

- `BATCH_SIZE, BATCH_INTERVAL` - Configuration batching logs on bot startup

- `SCAN_INTERVAL` - How often to scan for new events during regular operation

- `NUM_RETRIES, RETRY_DELAY` - Config for how often to retry failing API requests

- `SWAP_DELTA, MAX_SEARCH_ITERATIONS` - Used to define how much overswapping is accetable when searching 1Inch swaps

- `EVC_DEPLOYMENT_BLOCK` - Block that the contracs were deployed

- `WETH, EVC, SWAPPER, SWAP_VERIFIER, LIQUIDATOR_CONTRACT, ORACLE_LENS` - Relevant deployed contract addresses

- `PROFIT_RECEIVER` - Targeted receiver of any profits from liquidations

- `EVAULT_ABI_PATH, EVC_ABI_PATH, LIQUIDATOR_ABI_PATH, ORACLE_LENS_ABI_PATH` - Paths to compiled contracts

- `CHAIN_ID` - Chain ID to run the bot on, Mainnet: 1, Arbitrum: 42161
- `EXPLORER_URL` - Block explorer to be sent with Slack alerts, Mainnet: 'https://etherscan.io", Arbitrum: "https://arbiscan.io"


### Deploying

If you want to deploy your own version of the liquidator contract, you can run the command below:

```bash
forge script contracts/DeployLiquidator.sol --rpc-url $RPC_URL --broadcast --ffi -vvv --slow
```

To run the basic test script & broadcast to the configured RPC, run the below commmand:
```bash
forge script test/LiquidationSetupWithVaultCreated.sol --rpc-url $RPC_URL --broadcast --ffi -vvv --slow --evm-version shanghai
```
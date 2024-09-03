# Euler Liquidation Bot

Bot to perform liquidations on the Euler platform. [Liquidation docs.](https://docs.euler.finance/euler-vault-kit-white-paper/#liquidation)

## How it works

1. **Account Monitoring**:
   - The primary way of finding new accounts is [scanning](python/liquidation_bot.py#L742) for `AccountStatusCheck` events emitted by the EVC contract to check for new & modified positions.
   - This event is emitted every time a borrow is created or modified, and contains both the account address and vault address.
   - Health scores are calculated using the `accountLiquidity` [function](python/liquidation_bot.py#L52) implemented by the vaults themselves.
   - Accounts are added to a priority queue based on their health score with a time of next update, with low health accounts being checked most frequently.
   - EVC logs are batched on bot startup to catch up to the current block, then scanned for new events at a regular interval.

2. **Liquidation Opportunity Detection**:
   - When an account's health score falls below 1, the bot simulates a liquidation transaction across each collateral asset.
   - The bot gets a quote for how much collateral is needed to swap into the debt repay amount, and simulates a liquidation transaction on the Liquidator.sol contract.
   - Gas cost is estimated for the liquidation transaction, then checks if the leftover collateral after repaying debt is greater than the gas cost when converted to ETH terms.
   - If this is the case, the liquidation is profitable and the bot will attempt to execute the transaction.

3. **Liquidation Execution - [Liquidator.sol](contracts/Liquidator.sol)**:
   - If profitable, the bot constructs a transaction to call the `liquidate_single_collateral` [function](contracts/Liquidator.sol#L67) on the Liquidator contract.
   - The Liquidator contract then executes a batch of actions via the EVC containing the following steps:
     1. Enables borrow vault as a controller.
     2. Enable collateral vault as a collateral.
     3. Call liquidate() on the violator's position in the borrow vault, which seizes both the collateral and debt position.
     4. Withdraws specified amount of collateral from the collateral vault to the swapper contract.
     5. Calls the swapper contract with a multicall batch to swap the seized collateral, repay the debt, and sweep any remaining dust from the swapper contract.
     6. Transfers remaining collateral to the profit receiver.
     7. Submit batch to EVC.
    
    
    - There is a secondary flow still being developed to use the liquidator contract as an EVC operator, which would allow the bot to operate on behalf of another account and pull the debt position alongside the collateral to the account directly. This flow will be particularly useful for liquidating positions without swapping the collateral to the debt asset, fort hings such as permissioned RWA liquidations.

4. **Swap Quotation**:
   - The bot currently uses 1inch API to get quotes for swapping seized collateral to repay debt.
   - 1inch unfortunatley does not support exact output swaps, so we perform a binary search to find the optimal swap amount resulting in swapping slightly more collateral than needed to repay debt.
   - The bot will eventually have a fallback to uniswap swapping if 1inch is unable to provide a quote, which would also allow for more precise exact output swaps.


5. **Profit Handling**:
   - Any profit (excess collateral after repayment) is sent to a designated receiver address.
   - Profit is sent in the form of ETokens of the collateral asset, and is not withdrawn from the vault or converted to any other asset.

6. **Slack Notifications**:
   - The bot can send notifications to a slack channel when unhealthy accounts are detected, when liquidations are performed, and when errors occur. 
   - The bot also sends a report of all low health accounts at regularly scheduled intervals, which can be configured in the config.yaml file.
   - In order to receive notifications, a slack channel must be set up and a webhook URL must be provided in the .env file.

## How the bot works


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
mkdir logs state
```

Run:
`python python/liquidation_bot.py`

### Configuration

- The bot uses variables from both the [config.yaml](config.yaml) file and the [.env](.env.example) file to configure settings and private keys.
- The startup code is contained at the end of the [python/liquidation_bot.py](python/liquidation_bot.py#L1311) file, which also has two variable to set for the bot - `notify` & `execute_liquidation`, which determine if the bot will post to slack and if it will execute the liquidations found.

Make sure to build the contracts in both src and lib to have the correct ABIs loaded from the evk-periphery installation

Configuration through `.env` file:

REQUIRED:
- `LIQUIDATOR_EOA, LIQUIDATOR_PRIVATE_KEY` - public/private key of EOA that will be used to liquidate

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

- `WETH, EVC, SWAPPER, SWAP_VERIFIER, LIQUIDATOR_CONTRACT, ORACLE_LENS` - Relevant deployed contract addresses. The liquidator contract has been deployed on Mainnet, but feel free to redeploy.

- `PROFIT_RECEIVER` - Targeted receiver of any profits from liquidations

- `EVAULT_ABI_PATH, EVC_ABI_PATH, LIQUIDATOR_ABI_PATH, ORACLE_LENS_ABI_PATH` - Paths to compiled contracts

- `CHAIN_ID` - Chain ID to run the bot on, Mainnet: 1, Arbitrum: 42161


### Deploying

If you want to deploy your own version of the liquidator contract, you can run the command below:

```bash
forge script contracts/DeployLiquidator.sol --rpc-url $RPC_URL --broadcast --ffi -vvv --slow
```

To run the basic test script & broadcast to the configured RPC, run the below commmand:
```bash
forge script test/LiquidationSetupWithVaultCreated.sol --rpc-url $RPC_URL --broadcast --ffi -vvv --slow --evm-version shanghai
```
# Euler Liquidation Bot

Multi-chain liquidation bot for Euler protocol, written in TypeScript.

## Features

- Multi-chain support (Ethereum, Base, Swell, Sonic, BOB, Berachain)
- Priority queue-based account health monitoring
- Pyth oracle integration for price updates
- DEX swap integration for liquidation profitability
- Fastify HTTP server with OpenAPI/Swagger documentation
- State persistence for crash recovery

## How it Works

1. **Account Monitoring**: Scans `AccountStatusCheck` events from the EVC contract to discover positions. Accounts are prioritized by health score with adaptive update intervals.

2. **Liquidation Detection**: When health score < 1, simulates liquidation across collateral assets and calculates profitability after gas costs.

3. **Liquidation Execution**: Uses the [Liquidator.sol](contracts/Liquidator.sol) contract to execute profitable liquidations via EVC batch operations.

4. **Profit Handling**: Excess collateral after debt repayment is sent to a designated receiver address as ETokens.

## Requirements

- [Bun](https://bun.sh/) 1.0+ or Node.js 18+
- [Foundry](https://book.getfoundry.sh/) (for smart contract compilation)

## Installation

```bash
# Install dependencies
bun install
# or: npm install

# Build contracts
forge build
```

## Configuration

1. Copy `.env.example` to `.env` and configure:
   - `LIQUIDATOR_EOA` - Address that will execute liquidations
   - `LIQUIDATOR_PRIVATE_KEY` - Private key for signing transactions
   - `RPC_URL` / chain-specific RPC URLs
   - `SWAP_API_URL` - DEX aggregator API endpoint

2. Chain configuration is in `app/config.yaml`

## Running

```bash
# Development (with hot reload)
bun run dev

# Production
bun run start

# Type checking
bun run typecheck

# Tests
bun test
```

## API Endpoints

| Endpoint | Description |
|----------|-------------|
| `GET /health` | Health check and chain status |
| `GET /liquidation/allPositions?chainId=1` | All monitored positions |
| `GET /liquidation/chains` | Active chain IDs |
| `GET /liquidation/stats?chainId=1` | Monitoring statistics |
| `GET /docs` | Swagger UI documentation |

## Docker

```bash
# Build
docker build -t liquidation-bot .

# Run
docker run -p 8080:8080 --env-file .env liquidation-bot
```

## Deploying Liquidator Contract

```bash
forge script contracts/DeployLiquidator.sol --rpc-url $RPC_URL --broadcast --ffi -vvv --slow
```

## Architecture

```
src/
├── index.ts              # Entry point
├── core/                 # Domain models
│   ├── types.ts         # TypeScript types
│   ├── config.ts        # Configuration loader
│   ├── vault.ts         # Vault interactions
│   ├── account.ts       # Account health tracking
│   └── priority-queue.ts # Scheduling
├── services/             # Business logic
│   ├── chain-manager.ts # Multi-chain orchestration
│   ├── account-monitor.ts # Health monitoring
│   ├── evc-listener.ts  # Event listening
│   ├── liquidator.ts    # Liquidation execution
│   ├── oracle-handler.ts # Pyth oracle
│   ├── quoter.ts        # DEX quotes
│   └── notifier.ts      # Slack notifications
├── blockchain/           # Chain interaction
│   ├── client.ts        # viem clients
│   ├── contracts.ts     # Contract factories
│   └── abi/             # Contract ABIs
├── server/               # HTTP server
│   ├── app.ts           # Fastify setup
│   └── routes/          # API routes
├── persistence/          # State management
│   └── state-store.ts   # JSON persistence
└── utils/                # Utilities
```

## License

MIT

# Stage 1: Build Solidity contracts
FROM ghcr.io/foundry-rs/foundry:latest AS foundry-builder

WORKDIR /app

# Copy Solidity files
COPY foundry.toml ./
COPY contracts/ ./contracts/
COPY lib/ ./lib/
COPY remappings.txt ./

# Build contracts
RUN forge build

# Stage 2: Build TypeScript application
FROM oven/bun:1 AS builder

WORKDIR /app

# Copy package files
COPY package.json bun.lockb* ./

# Install dependencies
RUN bun install --frozen-lockfile

# Copy source files
COPY tsconfig.json ./
COPY src/ ./src/

# Copy built contract ABIs from foundry stage
COPY --from=foundry-builder /app/out/ ./out/
COPY --from=foundry-builder /app/contracts/*.json ./contracts/

# Copy ABIs to blockchain/abi
RUN mkdir -p src/blockchain/abi && \
    cp contracts/*.json src/blockchain/abi/ && \
    cp out/Liquidator.sol/Liquidator.json src/blockchain/abi/ && \
    cp out/IERC20.sol/IERC20.json src/blockchain/abi/

# Build application
RUN bun build src/index.ts --outdir dist --target bun

# Stage 3: Production image
FROM oven/bun:1-slim

WORKDIR /app

# Create non-root user
RUN addgroup --system --gid 1001 appgroup && \
    adduser --system --uid 1001 --ingroup appgroup appuser

# Create necessary directories
RUN mkdir -p /app/logs /app/state && \
    chown -R appuser:appgroup /app

# Copy built files
COPY --from=builder --chown=appuser:appgroup /app/dist/ ./dist/
COPY --from=builder --chown=appuser:appgroup /app/node_modules/ ./node_modules/
COPY --from=builder --chown=appuser:appgroup /app/src/blockchain/abi/ ./src/blockchain/abi/

# Copy configuration
COPY --chown=appuser:appgroup app/config.yaml ./app/config.yaml
COPY --chown=appuser:appgroup contracts/*.json ./contracts/

# Copy built contract ABIs
COPY --from=foundry-builder --chown=appuser:appgroup /app/out/ ./out/

# Switch to non-root user
USER appuser

# Expose port
EXPOSE 8080

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8080/health || exit 1

# Set environment variables
ENV NODE_ENV=production
ENV PORT=8080

# Run application
CMD ["bun", "run", "dist/index.js"]

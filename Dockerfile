ARG IMAGE_LINK=python:3.12.5-slim
FROM ${IMAGE_LINK} AS builder

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /build

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    libc6-dev \
    curl \
    git \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Install Foundry
RUN curl -L https://foundry.paradigm.xyz | bash
ENV PATH="/root/.foundry/bin:${PATH}"
RUN foundryup

# Set up git configuration for forge
RUN git config --global user.email "docker@example.com" && \
    git config --global user.name "Docker Build" && \
    git config --global init.defaultBranch main

# Copy only files needed for Solidity build
COPY contracts/ contracts/
COPY foundry.toml .
COPY remappings.txt .

# Initialize git and install forge dependencies
RUN git init && \
    git add -A && \
    git commit -m "Initial commit"

RUN mkdir -p lib/forge-std && \
    git clone --depth 1 https://github.com/foundry-rs/forge-std.git lib/forge-std

# Build Solidity contracts
RUN forge install && forge build

# Install Python dependencies into a virtual environment for clean copy
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:${PATH}"

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# =============================================================================
# Stage 2: Runtime - minimal image with only what's needed to run
# =============================================================================
FROM ${IMAGE_LINK} AS runtime

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Copy virtual environment from builder
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:${PATH}"

# Copy built Solidity artifacts (ABI files, etc.)
COPY --from=builder /build/out out/

# Copy application code
COPY app/ app/
COPY application.py .
COPY contracts/*.json contracts/

# Create a non-privileged user
ARG UID=10001
RUN adduser \
    --disabled-password \
    --gecos "" \
    --home "/nonexistent" \
    --shell "/sbin/nologin" \
    --no-create-home \
    --uid "${UID}" \
    appuser

# Create directories and set permissions
RUN mkdir -p /app/logs /app/state && \
    chown -R appuser:appuser /app && \
    chmod -R 755 /app && \
    chmod 777 /app/logs /app/state

USER appuser

EXPOSE 8080

CMD ["gunicorn", "--bind", "0.0.0.0:8080", "application:application"]
# syntax=docker/dockerfile:1

ARG PYTHON_VERSION=3.12.5
FROM 310118226683.dkr.ecr.eu-west-1.amazonaws.com/python:${PYTHON_VERSION}} as base

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    libc6-dev \
    curl \
    git \
    && rm -rf /var/lib/apt/lists/*

# Install Foundry
RUN curl -L https://foundry.paradigm.xyz | bash
ENV PATH="/root/.foundry/bin:${PATH}"
RUN foundryup

# Set up git configuration
RUN git config --global user.email "docker@example.com" && \
    git config --global user.name "Docker Build" && \
    git config --global init.defaultBranch main

# Copy the project files
COPY . .

# Initialize git repository
RUN git init && \
    git add -A && \
    git commit -m "Initial commit"

# Manually clone submodules
RUN mkdir -p lib/forge-std && \
    git clone https://github.com/foundry-rs/forge-std.git lib/forge-std
RUN mkdir -p lib/evk-periphery && \
    git clone https://github.com/euler-xyz/evk-periphery.git lib/evk-periphery

# Run Forge commands
RUN forge install --no-commit
RUN forge update
RUN forge build

RUN cd /app/lib/evk-periphery && \
    forge build && \
    cd ../..

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

RUN mkdir -p /app/logs /app/state

# Install Python dependencies
RUN --mount=type=cache,target=/root/.cache/pip \
    --mount=type=bind,source=requirements.txt,target=requirements.txt \
    python -m pip install -r requirements.txt

# Set correct permissions
RUN chown -R appuser:appuser /app && \
    chmod -R 755 /app && \
    chmod 777 /app/logs /app/state

USER appuser

EXPOSE 8080

CMD ["python", "python/liquidation_bot.py"]
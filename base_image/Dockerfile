FROM python:3.13.2-slim as base

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

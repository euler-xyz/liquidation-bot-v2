# syntax=docker/dockerfile:1

ARG PLATFORM=linux/amd64
FROM --platform=${PLATFORM} debian:trixie-slim AS build

ARG GIT_REPO_URL
ENV GIT_REPO_URL=${GIT_REPO_URL}
ARG GIT_BRANCH
ENV GIT_BRANCH=${GIT_BRANCH}
ARG RAILWAY_GIT_COMMIT_SHA
ENV RAILWAY_GIT_COMMIT_SHA=${RAILWAY_GIT_COMMIT_SHA}

RUN echo "Cache bust: ${RAILWAY_GIT_COMMIT_SHA}"

# Copy the project files
RUN apt-get update && apt-get install -y curl git bash 

RUN git clone --depth=1 --single-branch --branch ${GIT_BRANCH} ${GIT_REPO_URL}

# Manually clone submodules
RUN mkdir -p lib/forge-std && \
    git clone https://github.com/foundry-rs/forge-std.git lib/forge-std

RUN ls mewler-liquidation-bot
WORKDIR mewler-liquidation-bot

# Install Foundry
RUN curl -L https://foundry.paradigm.xyz | bash
RUN /root/.foundry/bin/foundryup --install nightly

# Run Forge commands
RUN /root/.foundry/bin/forge install
RUN /root/.foundry/bin/forge update
RUN /root/.foundry/bin/forge build

FROM --platform=${PLATFORM} debian:trixie-slim AS runtime

RUN apt-get update && apt-get install -y gnupg adduser python3-full virtualenv && rm -rf /var/lib/apt/lists/*
RUN curl -Ls https://cli.doppler.com/install.sh | sh


COPY --from=build /mewler-liquidation-bot /app

RUN mkdir -p /app/logs /app/state

WORKDIR /app

RUN ls -la

# Install Python dependencies
RUN virtualenv .venv
RUN ./.venv/bin/pip install --upgrade pip setuptools wheel
RUN ./.venv/bin/pip install -r requirements.txt

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


# Set correct permissions
RUN chown -R appuser:appuser /app && \
    chmod -R 755 /app && \
    chmod 777 /app/logs /app/state

USER appuser

EXPOSE 8080

# CMD ["python", "python/liquidation_bot.py"]
# Run the application
CMD ["doppler", "run", "--", ".venv/bin/gunicorn", "--bind", "0.0.0.0:8080", "application:application"]
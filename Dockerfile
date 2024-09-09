# syntax=docker/dockerfile:1

ARG PYTHON_VERSION=3.12.5
FROM 310118226683.dkr.ecr.eu-west-1.amazonaws.com/python:${PYTHON_VERSION} as base

# Copy the project files
COPY . .

# Initialize git repository
RUN git init && \
    git add -A && \
    git commit -m "Initial commit"

# Manually clone submodules
RUN mkdir -p lib/forge-std && \
    git clone https://github.com/foundry-rs/forge-std.git lib/forge-std

# Run Forge commands
RUN forge install --no-commit
RUN forge update
RUN forge build

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

# CMD ["python", "python/liquidation_bot.py"]
# Run the application
CMD ["gunicorn", "--bind", "0.0.0.0:8080", "application:application"]
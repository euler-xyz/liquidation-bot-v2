"""
Config Loader module - part of multi chain refactor
"""
import os
import yaml
from typing import Dict, Any
from dotenv import load_dotenv

class ChainConfig:
    """
    Chain Config object to access config variables
    """
    def __init__(self, chain_id: int, global_config: Dict[str, Any], chain_config: Dict[str, Any]):
        self.CHAIN_ID = chain_id
        self.CHAIN_NAME = chain_config["name"]
        self._global = global_config
        self._chain = chain_config

        # Load global EOA settings
        self.LIQUIDATOR_EOA = os.getenv("LIQUIDATOR_EOA")
        self.LIQUIDATOR_EOA_PRIVATE_KEY = os.getenv("LIQUIDATOR_PRIVATE_KEY")
        self.SWAP_API_URL = os.getenv("SWAP_API_URL")
        self.SLACK_URL = os.getenv("SLACK_WEBHOOK_URL")
        self.RISK_DASHBOARD_URL = os.getenv("RISK_DASHBOARD_URL")

        # Load chain-specific RPC from env using RPC_NAME from config
        self.RPC_URL = os.getenv(self._chain["RPC_NAME"])
        if not self.RPC_URL:
            raise ValueError(f"Missing RPC URL for {self._chain["name"]}. "
                           f"Env var {self._chain["RPC_NAME"]} not found")
        

        # Set chain-specific paths
        self.LOGS_PATH = f"{self._global["LOGS_PATH"]}/{self._chain["name"]}_monitor.log"
        self.SAVE_STATE_PATH = f"{self._global["SAVE_STATE_PATH"]}/{self._chain["name"]}_state.json"

    def __getattr__(self, name: str) -> Any:
        # First check chain-specific config
        if name in self._chain:
            return self._chain[name]
        if name in self._chain.get("contracts", {}):
            return self._chain["contracts"][name]
        # Then fall back to global config
        if name in self._global:
            return self._global[name]
        raise AttributeError(f"Config has no attribute '{name}'")

def load_chain_config(chain_id: int) -> ChainConfig:
    load_dotenv()

    current_dir = os.path.dirname(os.path.abspath(__file__))
    config_path = os.path.join(os.path.dirname(current_dir), "config.yaml")

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)
    except FileNotFoundError as exc:
        raise FileNotFoundError(f"Config file not found at {config_path}") from exc
    except yaml.YAMLError as e:
        raise ValueError(f"Error parsing YAML file: {e}") from e

    if chain_id not in config["chains"]:
        raise ValueError(f"No configuration found for chain ID {chain_id}")

    return ChainConfig(
        chain_id=chain_id,
        global_config=config["global"],
        chain_config=config["chains"][chain_id]
    )

# Test code
if __name__ == "__main__":
    try:
        current_chain_id = 8453
        current_config = load_chain_config(current_chain_id)
        print(f"\nSuccessfully loaded config for chain {current_chain_id}")
        print(f"Chain name: {current_config.CHAIN_NAME}")
        print(f"RPC URL: {current_config.RPC_URL}")
        print(f"EVC Address: {current_config.EVC}")
    except Exception as e:
        print(f"\nError loading config: {e}")

"""
Config Loader module - part of multi chain refactor
"""
import os
import yaml
import json
from typing import Dict, Any, Optional
from dotenv import load_dotenv
from web3 import Web3


class Web3Singleton:
    """
    Singleton class to manage w3 object creation per RPC URL
    """
    _instances = {}

    @staticmethod
    def get_instance(rpc_url: Optional[str] = None):
        """
        Set up a Web3 instance using the RPC URL from environment variables or passed parameter.
        Maintains separate instances per unique RPC URL.
        """
        load_dotenv(override=True)
        default_url = os.getenv("RPC_URL")
        url = default_url if rpc_url is None else rpc_url

        if url not in Web3Singleton._instances:
            Web3Singleton._instances[url] = Web3(Web3.HTTPProvider(url))

        return Web3Singleton._instances[url]

def setup_w3(rpc_url: Optional[str] = None) -> Web3:
    """
    Get the Web3 instance from the singleton class

    Args:
        rpc_url (Optional[str]): Optional RPC URL to override environment variable

    Returns:
        Web3: Web3 instance.
    """
    return Web3Singleton.get_instance(rpc_url)


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
        self.GLUEX_API_URL = os.getenv("GLUEX_API_URL")
        self.GLUEX_API_KEY = os.getenv("GLUEX_API_KEY")
        self.GLUEX_UNIQUE_PID = os.getenv("GLUEX_UNIQUE_PID")
        self.SLACK_URL = os.getenv("SLACK_WEBHOOK_URL")
        self.RISK_DASHBOARD_URL = os.getenv("RISK_DASHBOARD_URL")

        # Load chain-specific RPC from env using RPC_NAME from config
        self.RPC_URL = os.getenv(self._chain["RPC_NAME"])
        if not self.RPC_URL:
            raise ValueError(f"Missing RPC URL for {self._chain["name"]}. "
                           f"Env var {self._chain["RPC_NAME"]} not found")

        self.w3 = setup_w3(self.RPC_URL)
        self.mainnet_w3 = setup_w3(os.getenv("MAINNET_RPC_URL"))

        # Set chain-specific paths
        self.LOGS_PATH = f"{self._global["LOGS_PATH"]}/{self._chain["name"]}_monitor.log"
        self.SAVE_STATE_PATH = f"{self._global["SAVE_STATE_PATH"]}/{self._chain["name"]}_state.json"

        with open(self._global["EVC_ABI_PATH"], "r", encoding="utf-8") as file:
            interface = json.load(file)
        abi = interface["abi"]

        self.evc = self.w3.eth.contract(address=self.EVC, abi=abi)

        with open(self._global["ORACLE_ABI_PATH"], "r", encoding="utf-8") as file:
            interface = json.load(file)
        abi = interface["abi"]

        self.eth_oracle = self.mainnet_w3.eth.contract(address=self._global["MAINNET_ETH_ADAPTER"], abi=abi)
        self.btc_oracle = self.mainnet_w3.eth.contract(address=self._global["MAINNET_BTC_ADAPTER"], abi=abi)

        with open(global_config["LIQUIDATOR_ABI_PATH"], "r", encoding="utf-8") as file:
            interface = json.load(file)
        abi = interface["abi"]

        self.liquidator = self.w3.eth.contract(address=self._chain["contracts"]["LIQUIDATOR_CONTRACT"], abi=abi)

    def __getattr__(self, name: str) -> Any:
        if name in self._chain:
            return self._chain[name]
        if name in self._chain.get("contracts", {}):
            return self._chain["contracts"][name]
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

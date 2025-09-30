from typing import Dict, List
from concurrent.futures import ThreadPoolExecutor
from web3 import Web3

from .liquidation_bot import AccountMonitor, EVCListener, logger
from .config_loader import load_chain_config, ChainConfig

class ChainManager:
    """Manages multiple chain instances of the liquidation bot"""
    def __init__(self, chain_ids: List[int], notify: bool = True, execute_liquidation: bool = True):
        self.chain_ids = chain_ids
        self.notify = notify
        self.execute_liquidation = execute_liquidation

        # Initialize configs, monitors, and evc_listeners for each chain
        self.configs: Dict[int, ChainConfig] = {}
        self.monitors: Dict[int, AccountMonitor] = {}
        self.evc_listeners: Dict[int, EVCListener] = {}
        self.web3s: Dict[int, Web3] = {}

        self._initialize_chains()

    def _initialize_chains(self):
        """Initialize components for each chain"""
        print("CHAINS",self.chain_ids)
        for chain_id in self.chain_ids:
            # Load chain-specific config
            config = load_chain_config(chain_id)
            self.configs[chain_id] = config

            # Create monitor instance
            monitor = AccountMonitor(
                chain_id=chain_id,
                config=config,
                notify=self.notify,
                execute_liquidation=self.execute_liquidation
            )
            monitor.load_state(config.SAVE_STATE_PATH)
            self.monitors[chain_id] = monitor

            # Create listener instance
            listener = EVCListener(monitor, config)
            self.evc_listeners[chain_id] = listener

    def start(self):
        """Start all chain monitors and evc_listeners"""
        with ThreadPoolExecutor(max_workers=len(self.chain_ids)*2) as executor:
            # First batch process historical logs
            for chain_id in self.chain_ids:
                self.evc_listeners[chain_id].batch_account_logs_on_startup()

            # Start monitors
            monitor_futures = [
                executor.submit(self._run_monitor, chain_id)
                for chain_id in self.chain_ids
            ]

            # Start evc_listeners
            listener_futures = [
                executor.submit(self._run_listener, chain_id)
                for chain_id in self.chain_ids
            ]

            # Wait for all to complete (they shouldn't unless there's an error)
            for future in monitor_futures + listener_futures:
                try:
                    future.result()
                except Exception as e: # pylint: disable=broad-except
                    logger.error("Chain instance failed: %s", e, exc_info=True)

    def _run_monitor(self, chain_id: int):
        """Run a single chain's monitor"""
        monitor = self.monitors[chain_id]
        monitor.start_queue_monitoring()

    def _run_listener(self, chain_id: int):
        """Run a single chain's listener"""
        listener = self.evc_listeners[chain_id]
        listener.start_event_monitoring()

    def stop(self):
        """Stop all chain instances"""
        for monitor in self.monitors.values():
            monitor.stop()

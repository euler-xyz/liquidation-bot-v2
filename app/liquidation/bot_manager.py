from typing import Dict, List
from concurrent.futures import ThreadPoolExecutor
import os
import time
from web3 import Web3

from .liquidation_bot import AccountMonitor, EVCListener, logger
from .config_loader import load_chain_config, ChainConfig
from .db_state import init_db_manager, get_db_manager

class ChainManager:
    """Manages multiple chain instances of the liquidation bot"""
    def __init__(self, chain_ids: List[int], notify: bool = True, execute_liquidation: bool = True):
        self.chain_ids = chain_ids
        self.notify = notify
        self.execute_liquidation = execute_liquidation
        
        # Startup timing metrics
        self.startup_timings: Dict[str, float] = {}
        t_start = time.time()

        # Initialize database manager for state persistence
        t0 = time.time()
        database_url = os.getenv("DATABASE_URL")
        if database_url:
            try:
                init_db_manager(database_url)
                logger.info("ChainManager: PostgreSQL state persistence initialized")
            except Exception as ex:
                logger.warning("ChainManager: PostgreSQL not available, using local file storage: %s", ex)
        else:
            logger.info("ChainManager: DATABASE_URL not set, using local file storage for state")
        self.startup_timings["db_init"] = time.time() - t0

        # Initialize configs, monitors, and evc_listeners for each chain
        self.configs: Dict[int, ChainConfig] = {}
        self.monitors: Dict[int, AccountMonitor] = {}
        self.evc_listeners: Dict[int, EVCListener] = {}
        self.web3s: Dict[int, Web3] = {}

        self._initialize_chains()
        self.startup_timings["total_init"] = time.time() - t_start
        
        self._log_startup_timings()

    def _initialize_chains(self):
        """Initialize components for each chain"""
        print("CHAINS", self.chain_ids)
        for chain_id in self.chain_ids:
            # Load chain-specific config
            t0 = time.time()
            config = load_chain_config(chain_id)
            self.configs[chain_id] = config
            self.startup_timings[f"chain_{chain_id}_config_load"] = time.time() - t0

            # Create monitor instance
            t0 = time.time()
            monitor = AccountMonitor(
                chain_id=chain_id,
                config=config,
                notify=self.notify,
                execute_liquidation=self.execute_liquidation
            )
            self.startup_timings[f"chain_{chain_id}_monitor_create"] = time.time() - t0
            
            # Load state from DB or file
            t0 = time.time()
            monitor.load_state(config.SAVE_STATE_PATH)
            self.startup_timings[f"chain_{chain_id}_state_load"] = time.time() - t0
            self.startup_timings[f"chain_{chain_id}_accounts_loaded"] = len(monitor.accounts)
            self.startup_timings[f"chain_{chain_id}_last_block"] = monitor.last_saved_block
            
            self.monitors[chain_id] = monitor

            # Create listener instance
            listener = EVCListener(monitor, config)
            self.evc_listeners[chain_id] = listener

    def start(self):
        """Start all chain monitors and evc_listeners"""
        with ThreadPoolExecutor(max_workers=len(self.chain_ids)*2) as executor:
            # First batch process historical logs
            for chain_id in self.chain_ids:
                t0 = time.time()
                if not self.evc_listeners[chain_id].rapid_bootstrap():
                    logger.warning("Rapid bootstrap failed, falling back to loading EVC logs")
                    self.evc_listeners[chain_id].batch_account_logs_on_startup()
                self.startup_timings[f"chain_{chain_id}_bootstrap"] = time.time() - t0
                self.startup_timings[f"chain_{chain_id}_accounts_after_bootstrap"] = len(self.monitors[chain_id].accounts)
            
            # Log final startup timings before starting main loops
            self._log_startup_timings()

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

    def _log_startup_timings(self):
        """Log startup timing metrics"""
        logger.info("=" * 60)
        logger.info("STARTUP TIMING METRICS")
        logger.info("=" * 60)
        
        # Global timings
        logger.info("DB initialization: %.3fs", self.startup_timings.get("db_init", 0))
        logger.info("Total init time: %.3fs", self.startup_timings.get("total_init", 0))
        
        # Per-chain timings
        for chain_id in self.chain_ids:
            logger.info("-" * 40)
            logger.info("Chain %s:", chain_id)
            logger.info("  Config load: %.3fs", 
                       self.startup_timings.get(f"chain_{chain_id}_config_load", 0))
            logger.info("  Monitor create: %.3fs", 
                       self.startup_timings.get(f"chain_{chain_id}_monitor_create", 0))
            logger.info("  State load: %.3fs", 
                       self.startup_timings.get(f"chain_{chain_id}_state_load", 0))
            logger.info("  Accounts loaded from state: %d", 
                       self.startup_timings.get(f"chain_{chain_id}_accounts_loaded", 0))
            logger.info("  Last saved block: %d", 
                       self.startup_timings.get(f"chain_{chain_id}_last_block", 0))
            if f"chain_{chain_id}_bootstrap" in self.startup_timings:
                logger.info("  Bootstrap time: %.3fs", 
                           self.startup_timings.get(f"chain_{chain_id}_bootstrap", 0))
                logger.info("  Accounts after bootstrap: %d", 
                           self.startup_timings.get(f"chain_{chain_id}_accounts_after_bootstrap", 0))
        
        logger.info("=" * 60)

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

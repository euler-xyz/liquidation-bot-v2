"""
PostgreSQL State Persistence Module for Liquidation Bot
"""
import os
import json
import time
from typing import Dict, Any, Optional
from contextlib import contextmanager

import psycopg2
from psycopg2.extras import Json

from app.liquidation.utils import setup_logger

logger = setup_logger()


class DatabaseStateManager:
    """
    Manages state persistence in PostgreSQL database.
    Stores account monitor state per chain.
    """
    
    def __init__(self, database_url: Optional[str] = None):
        self.database_url = database_url or os.getenv("DATABASE_URL")
        if not self.database_url:
            raise ValueError("DATABASE_URL not configured")
        self._ensure_tables()
    
    @contextmanager
    def _get_connection(self):
        """Context manager for database connections"""
        conn = None
        try:
            conn = psycopg2.connect(self.database_url)
            yield conn
        finally:
            if conn:
                conn.close()
    
    def _ensure_tables(self):
        """Create tables if they don't exist"""
        with self._get_connection() as conn:
            with conn.cursor() as cur:
                # Main state table - stores the full state JSON per chain
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS bot_state (
                        chain_id INTEGER PRIMARY KEY,
                        chain_name VARCHAR(50) NOT NULL,
                        state_data JSONB NOT NULL,
                        last_saved_block BIGINT NOT NULL,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                
                # Accounts table - for granular account tracking
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS accounts (
                        id SERIAL PRIMARY KEY,
                        chain_id INTEGER NOT NULL,
                        address VARCHAR(42) NOT NULL,
                        controller_address VARCHAR(42),
                        current_health_score DOUBLE PRECISION,
                        time_of_next_update DOUBLE PRECISION,
                        value_borrowed DOUBLE PRECISION DEFAULT 0,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        UNIQUE(chain_id, address)
                    )
                """)
                
                # Vaults table
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS vaults (
                        id SERIAL PRIMARY KEY,
                        chain_id INTEGER NOT NULL,
                        address VARCHAR(42) NOT NULL,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        UNIQUE(chain_id, address)
                    )
                """)
                
                # Create indexes for faster lookups
                cur.execute("""
                    CREATE INDEX IF NOT EXISTS idx_accounts_chain_health 
                    ON accounts(chain_id, current_health_score)
                """)
                cur.execute("""
                    CREATE INDEX IF NOT EXISTS idx_accounts_chain_update 
                    ON accounts(chain_id, time_of_next_update)
                """)
                
                conn.commit()
                logger.info("DatabaseStateManager: Tables ensured")
    
    def save_state(self, chain_id: int, chain_name: str, state: Dict[str, Any]) -> bool:
        """
        Save the full state for a chain.
        
        Args:
            chain_id: The chain ID
            chain_name: Human readable chain name
            state: The state dictionary containing accounts, vaults, queue, last_saved_block
            
        Returns:
            bool: True if save was successful
        """
        try:
            with self._get_connection() as conn:
                with conn.cursor() as cur:
                    # Upsert the main state
                    cur.execute("""
                        INSERT INTO bot_state (chain_id, chain_name, state_data, last_saved_block, updated_at)
                        VALUES (%s, %s, %s, %s, CURRENT_TIMESTAMP)
                        ON CONFLICT (chain_id) 
                        DO UPDATE SET 
                            state_data = EXCLUDED.state_data,
                            last_saved_block = EXCLUDED.last_saved_block,
                            updated_at = CURRENT_TIMESTAMP
                    """, (chain_id, chain_name, Json(state), state.get("last_saved_block", 0)))
                    
                    # Also update individual accounts table for easier querying
                    for address, account_data in state.get("accounts", {}).items():
                        cur.execute("""
                            INSERT INTO accounts (chain_id, address, controller_address, 
                                                  current_health_score, time_of_next_update, updated_at)
                            VALUES (%s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
                            ON CONFLICT (chain_id, address) 
                            DO UPDATE SET 
                                controller_address = EXCLUDED.controller_address,
                                current_health_score = EXCLUDED.current_health_score,
                                time_of_next_update = EXCLUDED.time_of_next_update,
                                updated_at = CURRENT_TIMESTAMP
                        """, (
                            chain_id,
                            address,
                            account_data.get("controller_address"),
                            account_data.get("current_health_score"),
                            account_data.get("time_of_next_update")
                        ))
                    
                    # Update vaults table
                    for vault_address in state.get("vaults", {}).keys():
                        cur.execute("""
                            INSERT INTO vaults (chain_id, address, updated_at)
                            VALUES (%s, %s, CURRENT_TIMESTAMP)
                            ON CONFLICT (chain_id, address) 
                            DO UPDATE SET updated_at = CURRENT_TIMESTAMP
                        """, (chain_id, vault_address))
                    
                    conn.commit()
                    
            logger.info("DatabaseStateManager: State saved for chain %s at block %s",
                       chain_id, state.get("last_saved_block", 0))
            return True
            
        except Exception as ex:
            logger.error("DatabaseStateManager: Failed to save state for chain %s: %s",
                        chain_id, ex, exc_info=True)
            return False
    
    def load_state(self, chain_id: int) -> Optional[Dict[str, Any]]:
        """
        Load the state for a chain.
        
        Args:
            chain_id: The chain ID
            
        Returns:
            The state dictionary or None if not found
        """
        try:
            with self._get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT state_data, last_saved_block 
                        FROM bot_state 
                        WHERE chain_id = %s
                    """, (chain_id,))
                    
                    row = cur.fetchone()
                    if row:
                        state = row[0]
                        logger.info("DatabaseStateManager: State loaded for chain %s from block %s",
                                   chain_id, row[1])
                        return state
                    
            logger.info("DatabaseStateManager: No saved state found for chain %s", chain_id)
            return None
            
        except Exception as ex:
            logger.error("DatabaseStateManager: Failed to load state for chain %s: %s",
                        chain_id, ex, exc_info=True)
            return None
    
    def get_last_saved_block(self, chain_id: int) -> int:
        """Get the last saved block number for a chain"""
        try:
            with self._get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT last_saved_block FROM bot_state WHERE chain_id = %s
                    """, (chain_id,))
                    row = cur.fetchone()
                    return row[0] if row else 0
        except Exception as ex:
            logger.error("DatabaseStateManager: Failed to get last saved block: %s", ex)
            return 0
    
    def update_account(self, chain_id: int, address: str, controller_address: Optional[str],
                      health_score: Optional[float], next_update: float, 
                      value_borrowed: float = 0) -> bool:
        """Update a single account in the database"""
        try:
            with self._get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        INSERT INTO accounts (chain_id, address, controller_address, 
                                              current_health_score, time_of_next_update, 
                                              value_borrowed, updated_at)
                        VALUES (%s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
                        ON CONFLICT (chain_id, address) 
                        DO UPDATE SET 
                            controller_address = EXCLUDED.controller_address,
                            current_health_score = EXCLUDED.current_health_score,
                            time_of_next_update = EXCLUDED.time_of_next_update,
                            value_borrowed = EXCLUDED.value_borrowed,
                            updated_at = CURRENT_TIMESTAMP
                    """, (chain_id, address, controller_address, health_score, 
                          next_update, value_borrowed))
                    conn.commit()
            return True
        except Exception as ex:
            logger.error("DatabaseStateManager: Failed to update account %s: %s", 
                        address, ex, exc_info=True)
            return False
    
    def get_low_health_accounts(self, chain_id: int, threshold: float = 1.1, 
                                 limit: int = 100) -> list:
        """Get accounts with health score below threshold"""
        try:
            with self._get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT address, controller_address, current_health_score, 
                               value_borrowed, time_of_next_update
                        FROM accounts 
                        WHERE chain_id = %s 
                          AND current_health_score IS NOT NULL 
                          AND current_health_score < %s
                        ORDER BY current_health_score ASC
                        LIMIT %s
                    """, (chain_id, threshold, limit))
                    return cur.fetchall()
        except Exception as ex:
            logger.error("DatabaseStateManager: Failed to get low health accounts: %s", ex)
            return []


# Singleton instance
_db_manager: Optional[DatabaseStateManager] = None


def get_db_manager() -> Optional[DatabaseStateManager]:
    """Get or create the database manager singleton"""
    global _db_manager
    if _db_manager is None:
        database_url = os.getenv("DATABASE_URL")
        if database_url:
            try:
                _db_manager = DatabaseStateManager(database_url)
            except Exception as ex:
                logger.warning("DatabaseStateManager: Could not initialize: %s", ex)
                return None
    return _db_manager


def init_db_manager(database_url: str) -> DatabaseStateManager:
    """Initialize the database manager with a specific URL"""
    global _db_manager
    _db_manager = DatabaseStateManager(database_url)
    return _db_manager

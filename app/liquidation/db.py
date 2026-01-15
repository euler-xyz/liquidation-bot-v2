"""
Database cache for liquidation bot.
Supports both PostgreSQL (production/RDS) and SQLite (local development).
Caches account state to reduce RPC calls on restart.
"""
import os
import sqlite3
import threading
import math
import time
from typing import Dict, Any, Optional, List
from contextlib import contextmanager
from abc import ABC, abstractmethod

from app.liquidation.utils import setup_logger

logger = setup_logger()

# Check for PostgreSQL support
try:
    import psycopg2
    from psycopg2 import pool
    HAS_POSTGRES = True
except ImportError:
    HAS_POSTGRES = False


class BaseDatabaseCache(ABC):
    """Abstract base class for database cache implementations."""
    
    @abstractmethod
    def get_account(self, address: str, chain_id: int) -> Optional[Dict[str, Any]]:
        pass
    
    @abstractmethod
    def save_account(self, address: str, chain_id: int,
                     controller_address: str,
                     time_of_next_update: float,
                     current_health_score: float,
                     balance: int = 0,
                     value_borrowed: int = 0,
                     owner: str = None,
                     subaccount_number: int = None) -> None:
        pass
    
    @abstractmethod
    def save_accounts_batch(self, accounts: List[Dict[str, Any]], chain_id: int) -> None:
        pass
    
    @abstractmethod
    def get_all_accounts(self, chain_id: int) -> List[Dict[str, Any]]:
        pass
    
    @abstractmethod
    def delete_account(self, address: str, chain_id: int) -> None:
        pass
    
    @abstractmethod
    def get_last_processed_block(self, chain_id: int) -> Optional[int]:
        pass
    
    @abstractmethod
    def save_last_processed_block(self, chain_id: int, block_number: int) -> None:
        pass
    
    @abstractmethod
    def clear_chain_data(self, chain_id: int) -> None:
        pass
    
    @abstractmethod
    def get_stats(self, chain_id: int) -> Dict[str, Any]:
        pass
    
    @abstractmethod
    def close(self):
        pass


class SQLiteDatabaseCache(BaseDatabaseCache):
    """
    SQLite-based cache for local development.
    Thread-safe with connection pooling.
    """
    
    def __init__(self, db_path: str):
        self.db_path = db_path
        self._local = threading.local()
        self._init_db()
        logger.info("DB: Initialized SQLite database at %s", db_path)
    
    def _get_connection(self) -> sqlite3.Connection:
        """Get thread-local database connection."""
        if not hasattr(self._local, 'connection') or self._local.connection is None:
            self._local.connection = sqlite3.connect(self.db_path, check_same_thread=False)
            self._local.connection.row_factory = sqlite3.Row
        return self._local.connection
    
    @contextmanager
    def _cursor(self):
        """Context manager for database cursor with automatic commit/rollback."""
        conn = self._get_connection()
        cursor = conn.cursor()
        try:
            yield cursor
            conn.commit()
        except Exception:
            conn.rollback()
            raise
    
    def _init_db(self):
        """Initialize database tables."""
        with self._cursor() as cursor:
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS accounts (
                    address TEXT PRIMARY KEY,
                    chain_id INTEGER NOT NULL,
                    controller_address TEXT NOT NULL,
                    time_of_next_update REAL,
                    current_health_score REAL,
                    balance INTEGER DEFAULT 0,
                    value_borrowed INTEGER DEFAULT 0,
                    owner TEXT,
                    subaccount_number INTEGER,
                    updated_at REAL DEFAULT (strftime('%s', 'now'))
                )
            """)
            
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS processed_blocks (
                    chain_id INTEGER PRIMARY KEY,
                    last_processed_block INTEGER NOT NULL,
                    updated_at REAL DEFAULT (strftime('%s', 'now'))
                )
            """)
            
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_accounts_chain 
                ON accounts(chain_id)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_accounts_controller 
                ON accounts(controller_address)
            """)
    
    def get_account(self, address: str, chain_id: int) -> Optional[Dict[str, Any]]:
        with self._cursor() as cursor:
            cursor.execute(
                "SELECT * FROM accounts WHERE address = ? AND chain_id = ?",
                (address, chain_id)
            )
            row = cursor.fetchone()
            if row:
                return dict(row)
        return None
    
    def save_account(self, address: str, chain_id: int,
                     controller_address: str,
                     time_of_next_update: float,
                     current_health_score: float,
                     balance: int = 0,
                     value_borrowed: int = 0,
                     owner: str = None,
                     subaccount_number: int = None) -> None:
        hs = current_health_score if current_health_score != math.inf else 1e308
        
        with self._cursor() as cursor:
            cursor.execute("""
                INSERT INTO accounts (
                    address, chain_id, controller_address, time_of_next_update,
                    current_health_score, balance, value_borrowed, owner, 
                    subaccount_number, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(address) DO UPDATE SET
                    controller_address = excluded.controller_address,
                    time_of_next_update = excluded.time_of_next_update,
                    current_health_score = excluded.current_health_score,
                    balance = excluded.balance,
                    value_borrowed = excluded.value_borrowed,
                    owner = excluded.owner,
                    subaccount_number = excluded.subaccount_number,
                    updated_at = excluded.updated_at
            """, (address, chain_id, controller_address, time_of_next_update,
                  hs, balance, value_borrowed, owner, subaccount_number, time.time()))
    
    def save_accounts_batch(self, accounts: List[Dict[str, Any]], chain_id: int) -> None:
        with self._cursor() as cursor:
            for acc in accounts:
                hs = acc['current_health_score']
                if hs == math.inf:
                    hs = 1e308
                cursor.execute("""
                    INSERT INTO accounts (
                        address, chain_id, controller_address, time_of_next_update,
                        current_health_score, balance, value_borrowed, owner, 
                        subaccount_number, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(address) DO UPDATE SET
                        controller_address = excluded.controller_address,
                        time_of_next_update = excluded.time_of_next_update,
                        current_health_score = excluded.current_health_score,
                        balance = excluded.balance,
                        value_borrowed = excluded.value_borrowed,
                        owner = excluded.owner,
                        subaccount_number = excluded.subaccount_number,
                        updated_at = excluded.updated_at
                """, (acc['address'], chain_id, acc['controller_address'], 
                      acc.get('time_of_next_update', time.time()),
                      hs, acc.get('balance', 0), acc.get('value_borrowed', 0),
                      acc.get('owner'), acc.get('subaccount_number'), time.time()))
        logger.info("DB: Batch saved %d accounts to cache", len(accounts))
    
    def get_all_accounts(self, chain_id: int) -> List[Dict[str, Any]]:
        with self._cursor() as cursor:
            cursor.execute(
                "SELECT * FROM accounts WHERE chain_id = ?",
                (chain_id,)
            )
            rows = [dict(row) for row in cursor.fetchall()]
            for row in rows:
                if row['current_health_score'] >= 1e307:
                    row['current_health_score'] = math.inf
            return rows
    
    def delete_account(self, address: str, chain_id: int) -> None:
        with self._cursor() as cursor:
            cursor.execute(
                "DELETE FROM accounts WHERE address = ? AND chain_id = ?",
                (address, chain_id)
            )
    
    def get_last_processed_block(self, chain_id: int) -> Optional[int]:
        with self._cursor() as cursor:
            cursor.execute(
                "SELECT last_processed_block FROM processed_blocks WHERE chain_id = ?",
                (chain_id,)
            )
            row = cursor.fetchone()
            if row:
                return row['last_processed_block']
        return None
    
    def save_last_processed_block(self, chain_id: int, block_number: int) -> None:
        with self._cursor() as cursor:
            cursor.execute("""
                INSERT INTO processed_blocks (chain_id, last_processed_block, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(chain_id) DO UPDATE SET
                    last_processed_block = excluded.last_processed_block,
                    updated_at = excluded.updated_at
            """, (chain_id, block_number, time.time()))
    
    def clear_chain_data(self, chain_id: int) -> None:
        with self._cursor() as cursor:
            cursor.execute("DELETE FROM accounts WHERE chain_id = ?", (chain_id,))
            cursor.execute("DELETE FROM processed_blocks WHERE chain_id = ?", (chain_id,))
        logger.info("DB: Cleared all cached data for chain %d", chain_id)
    
    def get_stats(self, chain_id: int) -> Dict[str, Any]:
        with self._cursor() as cursor:
            cursor.execute("SELECT COUNT(*) as count FROM accounts WHERE chain_id = ?", (chain_id,))
            account_count = cursor.fetchone()['count']
            
            last_block = self.get_last_processed_block(chain_id)
            
            return {
                'account_count': account_count,
                'last_processed_block': last_block
            }
    
    def close(self):
        if hasattr(self._local, 'connection') and self._local.connection:
            self._local.connection.close()
            self._local.connection = None


class PostgresDatabaseCache(BaseDatabaseCache):
    """
    PostgreSQL-based cache for production (RDS).
    Uses connection pooling for multi-container support.
    """
    
    def __init__(self, database_url: str, min_connections: int = 2, max_connections: int = 10):
        if not HAS_POSTGRES:
            raise ImportError("psycopg2 is required for PostgreSQL support. "
                            "Install with: pip install psycopg2-binary")
        
        self.database_url = database_url
        self._pool = pool.ThreadedConnectionPool(
            min_connections, 
            max_connections, 
            database_url
        )
        self._init_db()
        logger.info("DB: Initialized PostgreSQL connection pool")
    
    @contextmanager
    def _cursor(self):
        """Context manager for database cursor with automatic commit/rollback and connection return."""
        conn = self._pool.getconn()
        try:
            cursor = conn.cursor()
            try:
                yield cursor
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                cursor.close()
        finally:
            self._pool.putconn(conn)
    
    def _dict_from_row(self, cursor, row) -> Dict[str, Any]:
        """Convert a row to a dictionary using cursor description."""
        if row is None:
            return None
        columns = [desc[0] for desc in cursor.description]
        return dict(zip(columns, row))
    
    def _init_db(self):
        """Initialize database tables."""
        with self._cursor() as cursor:
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS accounts (
                    address TEXT PRIMARY KEY,
                    chain_id INTEGER NOT NULL,
                    controller_address TEXT NOT NULL,
                    time_of_next_update DOUBLE PRECISION,
                    current_health_score DOUBLE PRECISION,
                    balance BIGINT DEFAULT 0,
                    value_borrowed BIGINT DEFAULT 0,
                    owner TEXT,
                    subaccount_number INTEGER,
                    updated_at DOUBLE PRECISION DEFAULT EXTRACT(EPOCH FROM NOW())
                )
            """)
            
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS processed_blocks (
                    chain_id INTEGER PRIMARY KEY,
                    last_processed_block BIGINT NOT NULL,
                    updated_at DOUBLE PRECISION DEFAULT EXTRACT(EPOCH FROM NOW())
                )
            """)
            
            # Create indexes (PostgreSQL will skip if exists)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_accounts_chain 
                ON accounts(chain_id)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_accounts_controller 
                ON accounts(controller_address)
            """)
    
    def get_account(self, address: str, chain_id: int) -> Optional[Dict[str, Any]]:
        with self._cursor() as cursor:
            cursor.execute(
                "SELECT * FROM accounts WHERE address = %s AND chain_id = %s",
                (address, chain_id)
            )
            row = cursor.fetchone()
            return self._dict_from_row(cursor, row)
    
    def save_account(self, address: str, chain_id: int,
                     controller_address: str,
                     time_of_next_update: float,
                     current_health_score: float,
                     balance: int = 0,
                     value_borrowed: int = 0,
                     owner: str = None,
                     subaccount_number: int = None) -> None:
        hs = current_health_score if current_health_score != math.inf else 1e308
        
        with self._cursor() as cursor:
            cursor.execute("""
                INSERT INTO accounts (
                    address, chain_id, controller_address, time_of_next_update,
                    current_health_score, balance, value_borrowed, owner, 
                    subaccount_number, updated_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT(address) DO UPDATE SET
                    controller_address = EXCLUDED.controller_address,
                    time_of_next_update = EXCLUDED.time_of_next_update,
                    current_health_score = EXCLUDED.current_health_score,
                    balance = EXCLUDED.balance,
                    value_borrowed = EXCLUDED.value_borrowed,
                    owner = EXCLUDED.owner,
                    subaccount_number = EXCLUDED.subaccount_number,
                    updated_at = EXCLUDED.updated_at
            """, (address, chain_id, controller_address, time_of_next_update,
                  hs, balance, value_borrowed, owner, subaccount_number, time.time()))
    
    def save_accounts_batch(self, accounts: List[Dict[str, Any]], chain_id: int) -> None:
        with self._cursor() as cursor:
            for acc in accounts:
                hs = acc['current_health_score']
                if hs == math.inf:
                    hs = 1e308
                cursor.execute("""
                    INSERT INTO accounts (
                        address, chain_id, controller_address, time_of_next_update,
                        current_health_score, balance, value_borrowed, owner, 
                        subaccount_number, updated_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT(address) DO UPDATE SET
                        controller_address = EXCLUDED.controller_address,
                        time_of_next_update = EXCLUDED.time_of_next_update,
                        current_health_score = EXCLUDED.current_health_score,
                        balance = EXCLUDED.balance,
                        value_borrowed = EXCLUDED.value_borrowed,
                        owner = EXCLUDED.owner,
                        subaccount_number = EXCLUDED.subaccount_number,
                        updated_at = EXCLUDED.updated_at
                """, (acc['address'], chain_id, acc['controller_address'], 
                      acc.get('time_of_next_update', time.time()),
                      hs, acc.get('balance', 0), acc.get('value_borrowed', 0),
                      acc.get('owner'), acc.get('subaccount_number'), time.time()))
        logger.info("DB: Batch saved %d accounts to cache", len(accounts))
    
    def get_all_accounts(self, chain_id: int) -> List[Dict[str, Any]]:
        with self._cursor() as cursor:
            cursor.execute(
                "SELECT * FROM accounts WHERE chain_id = %s",
                (chain_id,)
            )
            rows = cursor.fetchall()
            result = [self._dict_from_row(cursor, row) for row in rows]
            for row in result:
                if row['current_health_score'] >= 1e307:
                    row['current_health_score'] = math.inf
            return result
    
    def delete_account(self, address: str, chain_id: int) -> None:
        with self._cursor() as cursor:
            cursor.execute(
                "DELETE FROM accounts WHERE address = %s AND chain_id = %s",
                (address, chain_id)
            )
    
    def get_last_processed_block(self, chain_id: int) -> Optional[int]:
        with self._cursor() as cursor:
            cursor.execute(
                "SELECT last_processed_block FROM processed_blocks WHERE chain_id = %s",
                (chain_id,)
            )
            row = cursor.fetchone()
            if row:
                return row[0]
        return None
    
    def save_last_processed_block(self, chain_id: int, block_number: int) -> None:
        with self._cursor() as cursor:
            cursor.execute("""
                INSERT INTO processed_blocks (chain_id, last_processed_block, updated_at)
                VALUES (%s, %s, %s)
                ON CONFLICT(chain_id) DO UPDATE SET
                    last_processed_block = EXCLUDED.last_processed_block,
                    updated_at = EXCLUDED.updated_at
            """, (chain_id, block_number, time.time()))
    
    def clear_chain_data(self, chain_id: int) -> None:
        with self._cursor() as cursor:
            cursor.execute("DELETE FROM accounts WHERE chain_id = %s", (chain_id,))
            cursor.execute("DELETE FROM processed_blocks WHERE chain_id = %s", (chain_id,))
        logger.info("DB: Cleared all cached data for chain %d", chain_id)
    
    def get_stats(self, chain_id: int) -> Dict[str, Any]:
        with self._cursor() as cursor:
            cursor.execute("SELECT COUNT(*) FROM accounts WHERE chain_id = %s", (chain_id,))
            account_count = cursor.fetchone()[0]
            
            last_block = self.get_last_processed_block(chain_id)
            
            return {
                'account_count': account_count,
                'last_processed_block': last_block
            }
    
    def close(self):
        if self._pool:
            self._pool.closeall()
            logger.info("DB: Closed PostgreSQL connection pool")


# Global cache instance - will be initialized with config
_cache_instance: Optional[BaseDatabaseCache] = None
_cache_lock = threading.Lock()


def get_cache(db_path: str = None) -> BaseDatabaseCache:
    """
    Get or create the global cache instance.
    
    Uses DATABASE_URL env var for PostgreSQL if set, otherwise falls back to SQLite.
    
    Args:
        db_path: Path for SQLite database (used only if DATABASE_URL not set)
    
    Returns:
        Database cache instance (PostgreSQL or SQLite)
    """
    global _cache_instance
    
    if _cache_instance is None:
        with _cache_lock:
            if _cache_instance is None:
                database_url = os.getenv("DATABASE_URL")
                
                # Strip any surrounding quotes (common issue with some secret managers)
                if database_url:
                    database_url = database_url.strip('"').strip("'")
                    # Use PostgreSQL
                    _cache_instance = PostgresDatabaseCache(database_url)
                else:
                    # Fall back to SQLite
                    if db_path is None:
                        db_path = os.getenv("DB_PATH", "state/liquidation_cache.db")
                    
                    # Ensure directory exists
                    os.makedirs(os.path.dirname(db_path), exist_ok=True)
                    _cache_instance = SQLiteDatabaseCache(db_path)
    
    return _cache_instance


def reset_cache():
    """Reset the global cache instance. Useful for testing."""
    global _cache_instance
    with _cache_lock:
        if _cache_instance:
            _cache_instance.close()
            _cache_instance = None

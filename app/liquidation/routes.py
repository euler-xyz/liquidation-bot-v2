"""Module for handling API routes"""
from flask import Blueprint, make_response, jsonify, request
import math

from .liquidation_bot import logger
from .bot_manager import ChainManager

liquidation = Blueprint("liquidation", __name__)

chain_manager = None

def start_monitor(chain_ids=None):
    """Start monitoring for specified chains, defaults to mainnet if none specified"""
    global chain_manager
    if chain_ids is None:
        chain_ids = [1] # Default Ethereum mainnet

    chain_manager = ChainManager(chain_ids, notify=True)

    chain_manager.start()

    return chain_manager

@liquidation.route("/allPositions", methods=["GET"])
def get_all_positions():
    chain_id = int(request.args.get("chainId", 1))  # Default to mainnet if not specified
    
    if not chain_manager or chain_id not in chain_manager.monitors:
        return jsonify({"error": f"Monitor not initialized for chain {chain_id}"}), 500

    logger.info("API: Getting all positions for chain %s", chain_id)
    monitor = chain_manager.monitors[chain_id]
    sorted_accounts = monitor.get_accounts_by_health_score()

    response = []
    for (address, owner, sub_account, health_score, value_borrowed, vault_name, vault_symbol, vault_address) in sorted_accounts:
        if math.isinf(health_score):
            continue
        response.append({
            "address": owner,
            "account_address": address,
            "sub_account": sub_account,
            "health_score": health_score,
            "value_borrowed": value_borrowed,
            "vault_name": vault_name,
            "vault_address": vault_address,
            "vault_symbol": vault_symbol
        })

    return make_response(jsonify(response))

@liquidation.route("/account/<address>", methods=["GET"])
def get_account_details(address):
    """Get detailed information about a specific account"""
    chain_id = int(request.args.get("chainId", 1))  # Default to mainnet if not specified
    
    if not chain_manager or chain_id not in chain_manager.monitors:
        return jsonify({"error": f"Monitor not initialized for chain {chain_id}"}), 500

    logger.info("API: Getting details for account %s on chain %s", address, chain_id)
    monitor = chain_manager.monitors[chain_id]
    
    # Find the account in the monitor's accounts
    account = monitor.accounts.get(address)
    if not account:
        return jsonify({"error": f"Account {address} not found on chain {chain_id}"}), 404
    
    response = {
        "address": address,
        "owner": account.owner,
        "sub_account": account.subaccount_number,
        "health_score": account.current_health_score,
        "value_borrowed": account.value_borrowed,
        "vault_name": account.controller.vault_name,
        "vault_symbol": account.controller.vault_symbol,
        "vault_address": account.controller.address,
        "vault_creator": account.controller.creator,
        "vault_total_borrowed": account.controller.total_borrowed,
        "vault_total_deposited": account.controller.total_deposited,
        "vault_decimals": account.controller.decimals,
        "vault_total_borrowed_ui": account.controller.total_borrowed_ui,
        "vault_total_deposited_ui": account.controller.total_deposited_ui,
        "vault_utilization_ratio": account.controller.utilization_ratio,
        "underlying_asset": account.controller.underlying_asset_address,
        "balance": account.balance,
        "next_update_time": account.time_of_next_update
    }

    return make_response(jsonify(response))

@liquidation.route("/vault/<address>", methods=["GET"])
def get_vault_details(address):
    """Get detailed information about a specific vault"""
    chain_id = int(request.args.get("chainId", 1))  # Default to mainnet if not specified
    
    if not chain_manager or chain_id not in chain_manager.monitors:
        return jsonify({"error": f"Monitor not initialized for chain {chain_id}"}), 500

    logger.info("API: Getting vault details for address %s on chain %s", address, chain_id)
    monitor = chain_manager.monitors[chain_id]
    
    # Find the vault in the monitor's vaults
    vault = monitor.vaults.get(address)
    if not vault:
        return jsonify({"error": f"Vault {address} not found on chain {chain_id}"}), 404
    
    response = {
        "address": vault.address,
        "name": vault.vault_name,
        "symbol": vault.vault_symbol,
        "creator": vault.creator,
        "total_borrowed": vault.total_borrowed,
        "total_deposited": vault.total_deposited,
        "decimals": vault.decimals,
        "total_borrowed_ui": vault.total_borrowed_ui,
        "total_deposited_ui": vault.total_deposited_ui,
        "utilization_ratio": vault.utilization_ratio,
        "underlying_asset": vault.underlying_asset_address
    }

    return make_response(jsonify(response))

@liquidation.route("/vaults/creator/<address>", methods=["GET"])
def get_vaults_by_creator(address):
    """Get all vaults created by a specific address"""
    chain_id = int(request.args.get("chainId", 1))  # Default to mainnet if not specified
    
    if not chain_manager or chain_id not in chain_manager.monitors:
        return jsonify({"error": f"Monitor not initialized for chain {chain_id}"}), 500

    logger.info("API: Getting all vaults for creator %s on chain %s", address, chain_id)
    monitor = chain_manager.monitors[chain_id]
    
    # Find all vaults by this creator
    creator_vaults = []
    for vault in monitor.vaults.values():
        if vault.creator.lower() == address.lower():
            creator_vaults.append({
                "address": vault.address,
                "name": vault.vault_name,
                "symbol": vault.vault_symbol,
                "total_borrowed": vault.total_borrowed,
                "total_deposited": vault.total_deposited,
                "decimals": vault.decimals,
                "total_borrowed_ui": vault.total_borrowed_ui,
                "total_deposited_ui": vault.total_deposited_ui,
                "utilization_ratio": vault.utilization_ratio,
                "underlying_asset": vault.underlying_asset_address
            })
    
    if not creator_vaults:
        return jsonify({"message": f"No vaults found for creator {address} on chain {chain_id}", "vaults": []}), 200
    
    return make_response(jsonify({"vaults": creator_vaults}))

@liquidation.route("/vault/<address>/positions", methods=["GET"])
def get_vault_positions(address):
    """Get all positions (accounts) opened with a specific vault"""
    chain_id = int(request.args.get("chainId", 1))  # Default to mainnet if not specified
    
    if not chain_manager or chain_id not in chain_manager.monitors:
        return jsonify({"error": f"Monitor not initialized for chain {chain_id}"}), 500

    logger.info("API: Getting all positions for vault %s on chain %s", address, chain_id)
    monitor = chain_manager.monitors[chain_id]
    
    # Find all accounts that use this vault as their controller
    vault_accounts = []
    for account in monitor.accounts.values():
        if account.controller.address.lower() == address.lower():
            if math.isinf(account.current_health_score):
                continue
            vault_accounts.append({
                "address": account.address,
                "owner": account.owner,
                "sub_account": account.subaccount_number,
                "health_score": account.current_health_score,
                "value_borrowed": account.value_borrowed,
                "balance": account.balance,
                "next_update_time": account.time_of_next_update
            })
    
    # Sort by health score ascending (most risky first)
    vault_accounts.sort(key=lambda x: x["health_score"])
    
    return make_response(jsonify(vault_accounts))

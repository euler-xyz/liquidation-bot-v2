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
        chain_ids = [43114]

    print(chain_ids)
    chain_manager = ChainManager(chain_ids, notify=True)

    chain_manager.start()

    return chain_manager

@liquidation.route("/allPositions", methods=["GET"])
def get_all_positions():
    chain_id = int(request.args.get("chainId", 43114))  # Default to mainnet if not specified

    if not chain_manager or chain_id not in chain_manager.monitors:
        return jsonify({"error": f"Monitor not initialized for chain {chain_id}"}), 500

    logger.info("API: Getting all positions for chain %s", chain_id)
    monitor = chain_manager.monitors[chain_id]
    sorted_accounts = monitor.get_accounts_by_health_score()

    response = []
    for (address, owner, sub_account, health_score, value_borrowed, vault_name, vault_symbol) in sorted_accounts:
        if math.isinf(health_score):
            continue
        response.append({
            "address": owner,
            "account_address": address,
            "sub_account": sub_account,
            "health_score": health_score,
            "value_borrowed": value_borrowed,
            "vault_name": vault_name,
            "vault_symbol": vault_symbol
        })

    return make_response(jsonify(response))

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
        chain_ids = [1] # Default to Ethereum mainnet

    chain_manager = ChainManager(chain_ids, notify=True)

    chain_manager.start()

    return chain_manager

@liquidation.route("/allPositions", methods=["GET"])
def get_all_positions(chain_id):
    # Prefer query param if provided; otherwise use path param
    chain_id_param = request.args.get("chainId")
    if chain_id_param is not None:
        try:
            chain_id = int(chain_id_param)
        except ValueError:
            return jsonify({"error": "Invalid chainId query parameter"}), 400
    else:
        chain_id = int(chain_id)
    
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

import threading
from flask import Blueprint, request, make_response, jsonify
from web3 import Web3
import math

from .liquidation_bot import logger, get_account_monitor_and_evc_listener

liquidation = Blueprint("liquidation", __name__)

monitor = None
evc_listener = None

def start_monitor():
    global monitor, evc_listener
    monitor, evc_listener = get_account_monitor_and_evc_listener()

    evc_listener.batch_account_logs_on_startup()

    threading.Thread(target=monitor.start_queue_monitoring).start()
    threading.Thread(target=evc_listener.start_event_monitoring).start()

    return monitor, evc_listener

@liquidation.route("/allPositions", methods=["GET"])
def get_all_positions():
    if not monitor:
        return jsonify({"error": "Monitor not initialized"}), 500

    logger.info("API: Getting all positions")
    sorted_accounts = monitor.get_accounts_by_health_score()

    response = [
        {"address": address, "health_score": health_score, "value_borrowed": value_borrowed}
        for (address, health_score, value_borrowed) in sorted_accounts
        if not math.isinf(health_score)
    ]

    return make_response(jsonify(response))
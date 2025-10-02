"""
Creates and returns main flask app
"""
from flask import Flask, jsonify
from flask_cors import CORS
import threading
import os
import logging
logging.basicConfig(level=logging.INFO)

from .liquidation.routes import liquidation, start_monitor

def create_app():
    """Create Flask app with specified chain IDs"""
    app = Flask(__name__)
    CORS(app)

    @app.route("/health", methods=["GET"])
    def health_check():
        return jsonify({"status": "healthy"}), 200

    #chain_ids = [1, 1923, 8453, 146, 60808, 80094, 43114, 56, 130, 42161, 239, 59144, 9745]
    chain_ids = None
    chain_id_env = os.environ.get("CHAIN_ID")
    if chain_id_env:
        try:
            chain_ids = [int(chain_id_env)]
            logging.info(f"Starting monitor for chain ID: {chain_ids}")
        except ValueError:
            chain_ids = None
            logging.info(f"Starting monitor with default chain id")
    chain_ids = [1] ## FIXME: just for playground test

    monitor_thread = threading.Thread(target=start_monitor, args=(chain_ids,))
    monitor_thread.start()

    # Register the rewards blueprint after starting the monitor
    # Include dynamic chain_id in the URL prefix, e.g. /1/liquidation
    app.register_blueprint(liquidation, url_prefix="/<int:chain_id>/liquidation")

    return app

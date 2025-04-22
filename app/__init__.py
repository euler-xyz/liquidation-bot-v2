"""
Creates and returns main flask app
"""
from flask import Flask, jsonify
from flask_cors import CORS
import threading
from .liquidation.routes import liquidation, start_monitor

def create_app():
    """Create Flask app with specified chain IDs"""
    app = Flask(__name__)
    CORS(app)

    @app.route("/health", methods=["GET"])
    def health_check():
        return jsonify({"status": "healthy"}), 200
    
    chain_ids = [
         1, # Ethereum mainnet
        80094, # Berachain
        60808, # BOB
    ]
    # chain_ids = [80094]
    monitor_thread = threading.Thread(target=start_monitor, args=(chain_ids,))
    monitor_thread.start()

    # Register the rewards blueprint after starting the monitor
    app.register_blueprint(liquidation, url_prefix="/liquidation")

    return app

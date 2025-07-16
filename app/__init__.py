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

    chain_ids = [1923, 8453, 146, 60808, 80094, 43114, 56, 130, 42161, 239]
    # chain_ids = [130]

    monitor_thread = threading.Thread(target=start_monitor, args=(chain_ids,))
    monitor_thread.start()

    # Register the rewards blueprint after starting the monitor
    app.register_blueprint(liquidation, url_prefix="/liquidation")

    return app

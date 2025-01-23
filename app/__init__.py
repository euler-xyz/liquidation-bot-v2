"""
Creates and returns main flask app
"""
from flask import Flask, jsonify
from flask_cors import CORS
import threading
from .liquidation.routes import liquidation, start_monitor

def create_app():
    app = Flask(__name__)
    CORS(app)

    @app.route("/health", methods=["GET"])
    def health_check():
        return jsonify({"status": "healthy v03"}), 200

    monitor_thread = threading.Thread(target=start_monitor)
    monitor_thread.start()

    # Register the rewards blueprint after starting the monitor
    app.register_blueprint(liquidation, url_prefix="/liquidation")

    return app

"""
Start point for running flask app
"""
from app import create_app

# List of chain IDs to monitor

application = create_app()

if __name__ == "__main__":
    application.run(host="0.0.0.0", port=8282, debug=True)

from dotenv import load_dotenv
import os

from monitor.monitor import Monitor
from execute.liquidator import Liquidator

class LiquidationBot():
    def __init__(self):
        load_dotenv()

        self.monitor = Monitor(0.5, 5, 10, 5, 10)
        self.liquidator = Liquidator(os.getenv('LIQUIDATOR_ADDRESS'))

    def start(self):
        self.monitor.start()

        #TODO: change to IO model for reading outputs from monitor to trigger liquidation

if __name__ == "__main__":
    bot = LiquidationBot()
    bot.start()
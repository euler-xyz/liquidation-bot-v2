from dotenv import load_dotenv
import os

from python.legacy.monitor import Monitor
from execute.liquidator import Liquidator

class LiquidationBot():
    def __init__(self):
        load_dotenv()

        self.monitor = Monitor(0.1, 0.2, 0.2, 0.2, 1)
        self.liquidator = Liquidator(os.getenv('LIQUIDATOR_ADDRESS'), self.monitor, True)

if __name__ == "__main__":
    bot = LiquidationBot()
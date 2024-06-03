from monitor.monitor import Monitor
from execute import execute_liquidation

class LiquidationBot():
    def __init__(self):
        self.monitor = Monitor(0.5, 5, 10, 5, 10)
    
    def start(self):
        self.monitor.start()

if __name__ == "__main__":
    bot = LiquidationBot()
    bot.start()
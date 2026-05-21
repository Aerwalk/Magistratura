#!/usr/bin/env python3
"""MagSim - Warehouse Simulation System.

Main entry point for the warehouse simulation application.
"""

import random
import sys

from src.simulation import preload, supply_labeled, supply_unlabeled
from src.ui import WarehouseApp


def demo_fill() -> None:
    """Fill warehouse with demo data."""
    from src.config import PRODUCTS
    
    for p in PRODUCTS:
        supply_labeled(p, random.randint(2, 4))
    supply_unlabeled(3)


def main() -> None:
    """Application entry point."""
    from PyQt5 import QtWidgets
    
    app = QtWidgets.QApplication(sys.argv)
    preload()
    demo_fill()
    
    window = WarehouseApp()
    window.show()
    
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()

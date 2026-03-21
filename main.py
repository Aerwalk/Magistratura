from ui import WarehouseApp, preload
from models import shelf_state, count_on_shelves, supply_labeled, supply_unlabeled, request_product, PRODUCTS
import random


def demo_fill():
    for p in PRODUCTS:
        supply_labeled(p, random.randint(2, 4))
    supply_unlabeled(3)


if __name__ == "__main__":
    from PyQt5 import QtWidgets
    import sys
    app = QtWidgets.QApplication(sys.argv)
    preload()
    demo_fill()
    win = WarehouseApp()
    win.show()
    sys.exit(app.exec_())

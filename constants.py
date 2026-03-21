import numpy as np
from PyQt5 import QtWidgets, QtCore, QtGui
import pyqtgraph.opengl as gl

GRID_W = 14
GRID_H = 10

EXIT_CELL = (0, GRID_H // 2)
INBOUND_CELL = (1, 1)
INBOUND_PICK_CELL = (2, 1)
UAV_HOME = (GRID_W // 2, GRID_H // 2, 4.5)

TICK_MS = 35
SHELF_CAPACITY = 3
AGENT_SPEED = 0.10

PRODUCTS = ["metal", "plastic", "electronics", "wood", "glass"]

PRODUCT_COLORS = {
    "metal": (0.78, 0.78, 0.82, 1.0),
    "plastic": (0.10, 0.55, 0.95, 1.0),
    "electronics": (1.00, 0.55, 0.10, 1.0),
    "wood": (0.55, 0.32, 0.12, 1.0),
    "glass": (0.20, 0.90, 0.90, 1.0),
}

PRODUCT_QCOLORS = {
    "metal": QtGui.QColor(191, 191, 205),
    "plastic": QtGui.QColor(25, 140, 242),
    "electronics": QtGui.QColor(255, 140, 25),
    "wood": QtGui.QColor(140, 81, 31),
    "glass": QtGui.QColor(51, 230, 230),
}

ROBOT_CONFIG = [
    {"product": "metal", "color": (1.0, 0.1, 0.1, 1.0), "home": (13, 1)},
    {"product": "plastic", "color": (0.1, 0.4, 1.0, 1.0), "home": (13, 2)},
    {"product": "electronics", "color": (1.0, 0.5, 0.1, 1.0), "home": (13, 3)},
    {"product": "wood", "color": (0.1, 0.8, 0.3, 1.0), "home": (13, 7)},
    {"product": "glass", "color": (0.8, 0.2, 0.8, 1.0), "home": (13, 8)},
]

SHELF_X = {4, 6, 8, 10, 12}
AISLE_CELLS = set()

for x in range(GRID_W):
    for y in range(GRID_H):
        if x not in SHELF_X:
            AISLE_CELLS.add((x, y))

AISLE_CELLS.add(EXIT_CELL)
AISLE_CELLS.add(INBOUND_CELL)
AISLE_CELLS.add(INBOUND_PICK_CELL)


def is_shelf_cell(x, y):
    return x in SHELF_X and 0 <= y < GRID_H


def all_shelves():
    for x in range(GRID_W):
        for y in range(GRID_H):
            if is_shelf_cell(x, y):
                yield (x, y)

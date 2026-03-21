import sys
import random
import numpy as np
from PyQt5 import QtWidgets, QtCore, QtGui
import pyqtgraph.opengl as gl

from models import (
    GRID_H, TICK_MS, SHELF_CAPACITY, GRID_W,
    PRODUCTS, EXIT_CELL, INBOUND_CELL, INBOUND_PICK_CELL, UAV_HOME_POS,
    SHELF_X, is_shelf_cell, shelf_state,
    PRODUCT_COLORS, PRODUCT_QCOLORS,
    robots, uav, event_log, uav_scan_queue,
    count_on_shelves, distinct_products_on_shelves,
    supply_labeled, supply_unlabeled, request_product,
    update_uav, assign_tasks, move_robots_one_step, advance_robot_phases,
    log, preload, stock_total
)


class Warehouse3D(gl.GLViewWidget):
    def __init__(self):
        super().__init__()
        self.setBackgroundColor((28, 28, 34))
        self.setCameraPosition(distance=28, elevation=28, azimuth=38)
        self.opts["center"] = QtGui.QVector3D(GRID_W / 2, GRID_H / 2, 1.4)

        self.grid_item = gl.GLGridItem()
        self.grid_item.setSize(GRID_W + 2, GRID_H + 2)
        self.grid_item.setSpacing(1, 1)
        self.grid_item.translate(GRID_W / 2 - 0.5, GRID_H / 2 - 0.5, 0)
        self.addItem(self.grid_item)

        self.floor_item = gl.GLScatterPlotItem(pxMode=True)
        self.addItem(self.floor_item)

        self.shelf_item = gl.GLScatterPlotItem(pxMode=True)
        self.addItem(self.shelf_item)

        self.robot_body_item = gl.GLScatterPlotItem(pxMode=True)
        self.addItem(self.robot_body_item)

        self.robot_top_item = gl.GLScatterPlotItem(pxMode=True)
        self.addItem(self.robot_top_item)

        self.robot_cargo_item = gl.GLScatterPlotItem(pxMode=True)
        self.addItem(self.robot_cargo_item)

        self.uav_item = gl.GLScatterPlotItem(pxMode=True)
        self.addItem(self.uav_item)

        self.uav_beam = gl.GLLinePlotItem(width=2, antialias=True)
        self.addItem(self.uav_beam)

    def update_scene(self):
        floor_pts = np.array([
            [INBOUND_CELL[0], INBOUND_CELL[1], 0.05],
            [INBOUND_PICK_CELL[0], INBOUND_PICK_CELL[1], 0.05],
            [EXIT_CELL[0], EXIT_CELL[1], 0.05],
        ], dtype=float)
        floor_cols = np.array([
            [0.2, 1.0, 0.2, 1.0],
            [0.2, 0.85, 0.85, 1.0],
            [1.0, 1.0, 0.2, 1.0],
        ], dtype=float)
        self.floor_item.setData(pos=floor_pts, color=floor_cols, size=18)

        shelf_pts = []
        shelf_cols = []
        shelf_sizes = []
        product_to_robot_color = {r.product: r.color for r in robots}
        
        for (x, y), info in shelf_state.items():
            for level in range(SHELF_CAPACITY):
                z = 0.18 + level * 0.32
                if level < info["count"] and info["product"] is not None:
                    product = info["product"]
                    if product in product_to_robot_color:
                        color = product_to_robot_color[product]
                    else:
                        color = PRODUCT_COLORS.get(product, (0.5, 0.5, 0.5, 1.0))
                    size = 28
                else:
                    color = (0.40, 0.40, 0.45, 0.85)
                    size = 16
                shelf_pts.append([x, y, z])
                shelf_cols.append(color)
                shelf_sizes.append(size)
        self.shelf_item.setData(
            pos=np.array(shelf_pts, dtype=float),
            color=np.array(shelf_cols, dtype=float),
            size=np.array(shelf_sizes, dtype=float)
        )

        body_pts, body_cols, body_sizes = [], [], []
        top_pts, top_cols, top_sizes = [], [], []
        cargo_pts, cargo_cols, cargo_sizes = [], [], []

        for r in robots:
            x, y = r.draw_pos
            body_pts.append([x, y, 0.20])
            body_cols.append(r.color)
            body_sizes.append(24)

            top_pts.append([x, y, 0.40])
            top_cols.append([1.0, 1.0, 1.0, 1.0])
            top_sizes.append(10)

            if r.carry is not None or r.delivery_anim_ticks > 0:
                cargo_z = 0.68 + r.carry_bob
                scale = r.carry_appear_scale if r.carry else 1.0
                cargo_size = int(18 * scale)
                if r.carry in product_to_robot_color:
                    cargo_color = product_to_robot_color[r.carry]
                elif r.carry in PRODUCT_COLORS:
                    cargo_color = PRODUCT_COLORS[r.carry]
                else:
                    cargo_color = r.color
                if r.delivery_anim_ticks > 0:
                    alpha = 0.3 + 0.7 * (r.delivery_anim_ticks / 25.0)
                    cargo_color = (cargo_color[0], cargo_color[1], cargo_color[2], alpha)
                cargo_pts.append([x, y, cargo_z])
                cargo_cols.append(cargo_color)
                cargo_sizes.append(cargo_size)

        self.robot_body_item.setData(
            pos=np.array(body_pts, dtype=float),
            color=np.array(body_cols, dtype=float),
            size=np.array(body_sizes, dtype=float)
        )
        self.robot_top_item.setData(
            pos=np.array(top_pts, dtype=float),
            color=np.array(top_cols, dtype=float),
            size=np.array(top_sizes, dtype=float)
        )

        if cargo_pts:
            self.robot_cargo_item.setData(
                pos=np.array(cargo_pts, dtype=float),
                color=np.array(cargo_cols, dtype=float),
                size=np.array(cargo_sizes, dtype=float)
            )
            self._last_cargo_pts = cargo_pts
            self._last_cargo_cols = cargo_cols
            self._last_cargo_sizes = cargo_sizes
        elif hasattr(self, '_last_cargo_pts') and self._last_cargo_pts:
            self.robot_cargo_item.setData(
                pos=np.array(self._last_cargo_pts, dtype=float),
                color=np.array(self._last_cargo_cols, dtype=float),
                size=np.array(self._last_cargo_sizes, dtype=float)
            )

        ux, uy, uz = uav.pos
        self.uav_item.setData(
            pos=np.array([[ux, uy, uz]], dtype=float),
            color=np.array([[1.0, 1.0, 0.1, 1.0]], dtype=float),
            size=30
        )
        self.uav_beam.setData(
            pos=np.array([[ux, uy, uz], [ux, uy, 0.0]], dtype=float),
            color=(1.0, 1.0, 0.2, 0.6)
        )


class WarehouseApp(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Склад: БВС + РТС")
        self.resize(1550, 920)

        central = QtWidgets.QWidget()
        self.setCentralWidget(central)

        root = QtWidgets.QHBoxLayout(central)

        self.view3d = Warehouse3D()
        root.addWidget(self.view3d, 3)

        right = QtWidgets.QVBoxLayout()
        root.addLayout(right, 2)

        controls = QtWidgets.QGroupBox("Управление")
        controls_layout = QtWidgets.QGridLayout(controls)
        right.addWidget(controls)

        self.cb_supply = QtWidgets.QComboBox()
        self.cb_supply.addItems(PRODUCTS)

        self.sb_supply_qty = QtWidgets.QSpinBox()
        self.sb_supply_qty.setRange(1, 200)
        self.sb_supply_qty.setValue(3)

        self.sb_unlabeled_qty = QtWidgets.QSpinBox()
        self.sb_unlabeled_qty.setRange(1, 200)
        self.sb_unlabeled_qty.setValue(2)

        self.cb_request = QtWidgets.QComboBox()
        self.sb_request_qty = QtWidgets.QSpinBox()
        self.sb_request_qty.setRange(1, 1)
        self.sb_request_qty.setValue(1)

        self.cb_request.currentIndexChanged.connect(self.on_request_product_changed)
        self.refresh_request_products()

        btn_supply = QtWidgets.QPushButton("Поставка с меткой")
        btn_supply.clicked.connect(self.on_supply_labeled)

        btn_unlabeled = QtWidgets.QPushButton("Поставка без метки")
        btn_unlabeled.clicked.connect(self.on_supply_unlabeled)

        btn_request = QtWidgets.QPushButton("Запрос товара")
        btn_request.clicked.connect(self.on_request)

        btn_demo = QtWidgets.QPushButton("Демо-заполнение")
        btn_demo.clicked.connect(self.on_demo_fill)

        controls_layout.addWidget(QtWidgets.QLabel("Товар:"), 0, 0)
        controls_layout.addWidget(self.cb_supply, 0, 1)
        controls_layout.addWidget(QtWidgets.QLabel("Кол-во:"), 0, 2)
        controls_layout.addWidget(self.sb_supply_qty, 0, 3)
        controls_layout.addWidget(btn_supply, 0, 4)

        controls_layout.addWidget(QtWidgets.QLabel("Без метки, кол-во:"), 1, 0, 1, 2)
        controls_layout.addWidget(self.sb_unlabeled_qty, 1, 2)
        controls_layout.addWidget(btn_unlabeled, 1, 3, 1, 2)

        controls_layout.addWidget(QtWidgets.QLabel("Запрос товара:"), 2, 0)
        controls_layout.addWidget(self.cb_request, 2, 1)
        controls_layout.addWidget(QtWidgets.QLabel("Кол-во:"), 2, 2)
        controls_layout.addWidget(self.sb_request_qty, 2, 3)
        controls_layout.addWidget(btn_request, 2, 4)

        controls_layout.addWidget(btn_demo, 3, 0, 1, 5)

        stats_group = QtWidgets.QGroupBox("Статистика")
        stats_layout = QtWidgets.QVBoxLayout(stats_group)
        right.addWidget(stats_group, 2)

        self.stats_table = QtWidgets.QTableWidget(0, 4)
        self.stats_table.setHorizontalHeaderLabels(["Товар", "Всего", "На полках", "Спрос"])
        self.stats_table.horizontalHeader().setStretchLastSection(True)
        self.stats_table.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.Stretch)
        stats_layout.addWidget(self.stats_table)

        map_group = QtWidgets.QGroupBox("Карта полок (клик по клетке)")
        map_layout = QtWidgets.QVBoxLayout(map_group)
        right.addWidget(map_group, 3)

        self.map_table = QtWidgets.QTableWidget(GRID_H, GRID_W)
        self.map_table.horizontalHeader().setStretchLastSection(True)
        self.map_table.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.Stretch)
        self.map_table.verticalHeader().setStretchLastSection(True)
        self.map_table.verticalHeader().setSectionResizeMode(QtWidgets.QHeaderView.Stretch)
        self.map_table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.map_table.cellClicked.connect(self.on_map_click)
        map_layout.addWidget(self.map_table)

        log_group = QtWidgets.QGroupBox("Лог")
        log_layout = QtWidgets.QVBoxLayout(log_group)
        right.addWidget(log_group, 2)

        self.log_text = QtWidgets.QPlainTextEdit()
        self.log_text.setReadOnly(True)
        log_layout.addWidget(self.log_text)

        self.info_label = QtWidgets.QLabel("Выберите операцию")
        right.addWidget(self.info_label)

        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(TICK_MS)

        self.refresh_all()

    def on_demo_fill(self):
        for p in PRODUCTS:
            supply_labeled(p, random.randint(2, 4))
        supply_unlabeled(3)
        self.refresh_all()

    def on_supply_labeled(self):
        supply_labeled(self.cb_supply.currentText(), self.sb_supply_qty.value())
        self.refresh_all()

    def on_supply_unlabeled(self):
        supply_unlabeled(self.sb_unlabeled_qty.value())
        self.refresh_all()

    def on_request_product_changed(self):
        product = self.cb_request.currentText()
        if not product:
            self.sb_request_qty.setRange(1, 1)
            self.sb_request_qty.setValue(1)
            return

        max_qty = max(1, count_on_shelves(product))
        self.sb_request_qty.setRange(1, max_qty)
        if self.sb_request_qty.value() > max_qty:
            self.sb_request_qty.setValue(max_qty)

    def on_request(self):
        product = self.cb_request.currentText()
        if not product:
            QtWidgets.QMessageBox.information(self, "Запрос", "На складе нет материалов на полках.")
            return

        max_qty = count_on_shelves(product)
        qty = min(self.sb_request_qty.value(), max_qty)
        if qty <= 0:
            QtWidgets.QMessageBox.information(self, "Запрос", "Этот материал сейчас недоступен на полках.")
            return

        request_product(product, qty)
        self.refresh_all()

    def on_map_click(self, row, col):
        x = col
        y = row

        if not is_shelf_cell(x, y):
            self.info_label.setText(f"Клетка ({x}, {y}) — проход/служебная зона")
            return

        info = shelf_state[(x, y)]
        if info["count"] == 0:
            self.info_label.setText(f"Полка ({x}, {y}) пустая")
        else:
            self.info_label.setText(
                f"Полка ({x}, {y}) | материал={info['product']} | "
                f"количество={info['count']}/{SHELF_CAPACITY}"
            )

    def tick(self):
        update_uav()
        assign_tasks()
        move_robots_one_step()
        advance_robot_phases()
        self.refresh_all()

    def refresh_request_products(self):
        current = self.cb_request.currentText()
        items = [p for p in PRODUCTS if count_on_shelves(p) > 0]
        available_products = [p for p in items if self.sb_request_qty.maximum() > 0 or True]

        self.cb_request.blockSignals(True)
        self.cb_request.clear()
        if items:
            self.cb_request.addItems(items)
            if current in items:
                self.cb_request.setCurrentText(current)
            elif items:
                self.cb_request.setCurrentText(items[0])
        self.cb_request.blockSignals(False)

        has_items = len(items) > 0
        self.cb_request.setEnabled(has_items)
        self.sb_request_qty.setEnabled(has_items)

        if has_items:
            self.on_request_product_changed()
        else:
            self.sb_request_qty.setRange(0, 0)
            self.sb_request_qty.setValue(0)

    def refresh_stats(self):
        all_products = sorted(set(PRODUCTS) | set(stock_total.keys()))
        self.stats_table.setRowCount(len(all_products))

        for row, p in enumerate(all_products):
            vals = [
                p,
                str(stock_total.get(p, 0)),
                str(count_on_shelves(p)),
                "0",
            ]
            for col, val in enumerate(vals):
                item = QtWidgets.QTableWidgetItem(val)
                if col == 0 and p in PRODUCT_QCOLORS:
                    item.setBackground(PRODUCT_QCOLORS[p])
                self.stats_table.setItem(row, col, item)

    def refresh_map(self):
        product_to_qcolor = {r.product: QtGui.QColor(int(r.color[0]*255), int(r.color[1]*255), int(r.color[2]*255)) for r in robots}
        
        for y in range(GRID_H):
            for x in range(GRID_W):
                item = QtWidgets.QTableWidgetItem("")

                if (x, y) == EXIT_CELL:
                    item.setText("OUT")
                    item.setBackground(QtGui.QColor(235, 235, 120))

                elif (x, y) == INBOUND_CELL:
                    item.setText("IN")
                    item.setBackground(QtGui.QColor(120, 235, 120))

                elif (x, y) == INBOUND_PICK_CELL:
                    item.setText("PICK")
                    item.setBackground(QtGui.QColor(120, 220, 220))

                elif is_shelf_cell(x, y):
                    info = shelf_state[(x, y)]
                    if info["count"] == 0:
                        item.setText("0/5")
                        item.setBackground(QtGui.QColor(95, 95, 100))
                    else:
                        product = info["product"]
                        color = product_to_qcolor.get(product, PRODUCT_QCOLORS.get(product, QtGui.QColor(128, 128, 128)))
                        item.setText(f"{product[:3]}:{info['count']}/5")
                        item.setBackground(color)

                else:
                    item.setText("")
                    item.setBackground(QtGui.QColor(45, 45, 45))

                self.map_table.setItem(y, x, item)

    def refresh_log(self):
        self.log_text.setPlainText("\n".join(event_log))

    def refresh_all(self):
        self.refresh_request_products()
        self.refresh_stats()
        self.refresh_map()
        self.refresh_log()
        self.view3d.update_scene()


if __name__ == "__main__":
    app = QtWidgets.QApplication(sys.argv)
    preload()
    win = WarehouseApp()
    win.show()
    sys.exit(app.exec_())

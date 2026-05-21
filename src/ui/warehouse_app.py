"""Warehouse application UI."""

import sys
import random

import numpy as np
from PyQt5 import QtWidgets, QtCore, QtGui
import pyqtgraph.opengl as gl

from src.config import (
    GRID_H, TICK_MS, SHELF_CAPACITY, GRID_W,
    PRODUCTS, EXIT_CELL, INBOUND_CELL, INBOUND_PICK_CELL,
    PRODUCT_COLORS, PRODUCT_QCOLORS
)
from src.core.grid import is_shelf_cell, is_custom_shelf, is_standard_shelf, add_custom_shelf, remove_custom_shelf, set_exit_cell, set_inbound_cell, set_inbound_pick_cell, set_grid_size
from src.core.state import get_state
from src.entities import robots, uav
from src.simulation import (
    supply_labeled, supply_unlabeled, request_product, rebalance_warehouse,
    check_rebalance_complete, check_stuck_robots,
    update_uav, assign_tasks, move_robots_one_step, advance_robot_phases,
    log, preload,
)


class Warehouse3D(gl.GLViewWidget):
    """3D visualization widget for warehouse."""
    
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
        from src.core.grid import get_exit_cell, get_inbound_cell, get_inbound_pick_cell
        state = get_state()
        ex = get_exit_cell()
        ib = get_inbound_cell()
        pk = get_inbound_pick_cell()
        floor_pts = np.array([
            [ib[0], ib[1], 0.05],
            [pk[0], pk[1], 0.05],
            [ex[0], ex[1], 0.05],
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
        
        for (x, y), info in state.shelf_state.items():
            for level in range(SHELF_CAPACITY):
                z = 0.18 + level * 0.32
                if level < info["count"] and info["product"] is not None:
                    product = info["product"]
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
                cargo_color = PRODUCT_COLORS.get(r.carry, r.color)
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
    """Main warehouse simulation window."""
    
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Склад: БВС + РТС")
        self.resize(1550, 920)

        self.view3d = Warehouse3D()
        self.setCentralWidget(self.view3d)

        self.docks = {}
        self._add_dock("Управление", self._build_controls, QtCore.Qt.RightDockWidgetArea)
        self._add_dock("РТС", self._build_robots_panel, QtCore.Qt.RightDockWidgetArea)
        self._add_dock("Статус", self._build_status_panel, QtCore.Qt.RightDockWidgetArea)
        self._add_dock("Статистика", self._build_stats_panel, QtCore.Qt.RightDockWidgetArea)
        self._add_dock("Карта", self._build_map_panel, QtCore.Qt.RightDockWidgetArea)
        self._add_dock("Лог", self._build_log_panel, QtCore.Qt.RightDockWidgetArea)

        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(TICK_MS)

        self.refresh_all()

    def _add_dock(self, title, build_fn, area):
        """Create a dock widget from a builder function."""
        dock = QtWidgets.QDockWidget(title, self)
        dock.setFeatures(
            QtWidgets.QDockWidget.DockWidgetClosable |
            QtWidgets.QDockWidget.DockWidgetMovable |
            QtWidgets.QDockWidget.DockWidgetFloatable
        )
        content = QtWidgets.QWidget()
        build_fn(content)
        dock.setWidget(content)
        self.addDockWidget(area, dock)
        self.docks[title] = dock
        return dock

    def _build_controls(self, content):
        """Setup control buttons panel."""
        layout = QtWidgets.QVBoxLayout(content)
        layout.setContentsMargins(0, 0, 0, 0)
        controls = QtWidgets.QGroupBox("Управление")
        controls_layout = QtWidgets.QGridLayout(controls)
        layout.addWidget(controls)

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

        self.cb_request.currentIndexChanged.connect(self._on_request_product_changed)
        self._refresh_request_products()

        btn_supply = QtWidgets.QPushButton("Поставка с меткой")
        btn_supply.clicked.connect(self._on_supply_labeled)

        btn_unlabeled = QtWidgets.QPushButton("Поставка без метки")
        btn_unlabeled.clicked.connect(self._on_supply_unlabeled)

        btn_request = QtWidgets.QPushButton("Запрос товара")
        btn_request.clicked.connect(self._on_request)

        btn_demo = QtWidgets.QPushButton("Демо-заполнение")
        btn_demo.clicked.connect(self._on_demo_fill)

        btn_rebalance = QtWidgets.QPushButton("Ребалансировка")
        btn_rebalance.clicked.connect(self._on_rebalance)

        btn_check_rebalance = QtWidgets.QPushButton("Проверка ребалансировки")
        btn_check_rebalance.clicked.connect(self._on_check_rebalance)

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
        controls_layout.addWidget(btn_rebalance, 4, 0, 1, 2)
        controls_layout.addWidget(btn_check_rebalance, 4, 2, 1, 3)

        btn_export = QtWidgets.QPushButton("Экспорт в Excel")
        btn_export.clicked.connect(self._on_export_excel)
        controls_layout.addWidget(btn_export, 5, 0, 1, 5)

        controls_layout.addWidget(QtWidgets.QLabel("Новый РТС:"), 6, 0)
        self.cb_new_robot_product = QtWidgets.QComboBox()
        self.cb_new_robot_product.addItems(PRODUCTS)
        controls_layout.addWidget(self.cb_new_robot_product, 6, 1, 1, 2)
        btn_create_robot = QtWidgets.QPushButton("Создать")
        btn_create_robot.clicked.connect(self._on_create_robot)
        controls_layout.addWidget(btn_create_robot, 6, 3, 1, 2)

        controls_layout.addWidget(QtWidgets.QLabel("Новый материал:"), 7, 0)
        self.txt_new_product = QtWidgets.QLineEdit()
        self.txt_new_product.setPlaceholderText("название")
        controls_layout.addWidget(self.txt_new_product, 7, 1)
        self.btn_pick_color = QtWidgets.QPushButton()
        self.btn_pick_color.setFixedSize(24, 24)
        self.btn_pick_color.setStyleSheet("background-color: #8888ff;")
        self.btn_pick_color.clicked.connect(self._on_pick_product_color)
        controls_layout.addWidget(self.btn_pick_color, 7, 2)
        self._new_product_color = (0.5, 0.5, 1.0, 1.0)
        btn_create_product = QtWidgets.QPushButton("Создать")
        btn_create_product.clicked.connect(self._on_create_product)
        controls_layout.addWidget(btn_create_product, 7, 3, 1, 2)

        self.btn_edit_map = QtWidgets.QPushButton("Режим редактирования: ВЫКЛ")
        self.btn_edit_map.setCheckable(True)
        self.btn_edit_map.toggled.connect(self._on_edit_map_toggle)
        controls_layout.addWidget(self.btn_edit_map, 8, 0, 1, 5)

        btn_expand = QtWidgets.QPushButton("Расширить карту")
        btn_expand.clicked.connect(self._on_expand_grid)
        controls_layout.addWidget(btn_expand, 9, 0, 1, 5)

        self._edit_mode = False

        layout.addStretch()

    def _build_robots_panel(self, content):
        """Setup robots control panel - built once, updated in-place."""
        layout = QtWidgets.QVBoxLayout(content)
        layout.setContentsMargins(0, 0, 0, 0)
        robots_group = QtWidgets.QGroupBox("РТС")
        robots_vbox = QtWidgets.QVBoxLayout(robots_group)
        layout.addWidget(robots_group)
        
        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        robots_vbox.addWidget(scroll)
        
        self.robots_container = QtWidgets.QWidget()
        scroll.setWidget(self.robots_container)
        self.robots_container_layout = QtWidgets.QVBoxLayout(self.robots_container)
        self.robots_container_layout.setContentsMargins(2, 2, 2, 2)
        
        self.robot_card_frames = []
        self._build_robot_cards()

    def _build_robot_cards(self):
        """Build robot control cards (called once at init and on new robot)."""
        from src.config import AGENT_SPEED
        
        layout = self.robots_container_layout
        
        while layout.count():
            item = layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        
        self.robot_card_frames.clear()
        
        for robot in robots:
            frame = QtWidgets.QFrame()
            frame.setFrameShape(QtWidgets.QFrame.StyledPanel)
            card = QtWidgets.QGridLayout(frame)
            card.setContentsMargins(4, 2, 4, 2)
            
            color_hex = f"#{int(robot.color[0]*255):02x}{int(robot.color[1]*255):02x}{int(robot.color[2]*255):02x}"
            
            name_edit = QtWidgets.QLineEdit(robot.name)
            name_edit.setStyleSheet(f"color: {color_hex}; font-weight: bold;")
            name_edit.textChanged.connect(lambda text, r=robot: self._on_robot_name_changed(r, text))
            card.addWidget(name_edit, 0, 0)
            
            btn_reset = QtWidgets.QPushButton("Сброс")
            btn_reset.setFixedWidth(50)
            btn_reset.clicked.connect(lambda checked, r=robot: self._on_reset_robot(r.id))
            card.addWidget(btn_reset, 0, 1)
            
            card.addWidget(QtWidgets.QLabel("Ёмк:"), 0, 2)
            sb_cap = QtWidgets.QSpinBox()
            sb_cap.setRange(1, 5)
            sb_cap.setFixedWidth(45)
            sb_cap.setValue(robot.capacity)
            sb_cap.valueChanged.connect(lambda val, r=robot: self._on_robot_capacity_changed(r.id, val))
            card.addWidget(sb_cap, 0, 3)
            
            card.addWidget(QtWidgets.QLabel("Ск:"), 0, 4)
            sb_speed = QtWidgets.QDoubleSpinBox()
            sb_speed.setRange(0.05, 1.0)
            sb_speed.setSingleStep(0.05)
            sb_speed.setDecimals(2)
            sb_speed.setFixedWidth(55)
            sb_speed.setValue(robot.speed)
            sb_speed.valueChanged.connect(lambda val, r=robot: self._on_robot_speed_changed(r.id, val))
            card.addWidget(sb_speed, 0, 5)
            
            card.addWidget(QtWidgets.QLabel("Товары:"), 1, 0)
            product_row = QtWidgets.QHBoxLayout()
            for p in PRODUCTS:
                cb = QtWidgets.QCheckBox(p)
                cb.setChecked(p in robot.products)
                cb.stateChanged.connect(lambda state, r=robot, prod=p: self._on_robot_product_toggle(r, prod, state))
                product_row.addWidget(cb)
            card.addLayout(product_row, 1, 1, 1, 5)
            
            layout.addWidget(frame)
            self.robot_card_frames.append(frame)

    def _build_status_panel(self, content):
        """Setup progress bar panel for robots and UAV."""
        layout = QtWidgets.QVBoxLayout(content)
        layout.setContentsMargins(0, 0, 0, 0)
        status_group = QtWidgets.QGroupBox("Статус")
        status_layout = QtWidgets.QVBoxLayout(status_group)
        layout.addWidget(status_group)
        
        self.status_widgets = {}
        self.status_widgets["_layout"] = status_layout
        
        for robot in robots:
            row = QtWidgets.QWidget()
            row_layout = QtWidgets.QHBoxLayout(row)
            row_layout.setContentsMargins(2, 1, 2, 1)
            
            lbl = QtWidgets.QLabel(robot.name)
            lbl.setFixedWidth(70)
            row_layout.addWidget(lbl)
            
            bar = QtWidgets.QProgressBar()
            bar.setRange(0, 100)
            bar.setValue(0)
            bar.setTextVisible(True)
            row_layout.addWidget(bar, 1)
            
            status_lbl = QtWidgets.QLabel("ожидание")
            status_lbl.setFixedWidth(100)
            row_layout.addWidget(status_lbl)
            
            status_layout.addWidget(row)
            self.status_widgets[f"robot_{robot.id}"] = (bar, status_lbl)
        
        uav_row = QtWidgets.QWidget()
        uav_row_layout = QtWidgets.QHBoxLayout(uav_row)
        uav_row_layout.setContentsMargins(2, 1, 2, 1)
        
        uav_lbl = QtWidgets.QLabel("БВС")
        uav_lbl.setFixedWidth(70)
        uav_row_layout.addWidget(uav_lbl)
        
        uav_bar = QtWidgets.QProgressBar()
        uav_bar.setRange(0, 100)
        uav_bar.setValue(0)
        uav_bar.setTextVisible(True)
        uav_row_layout.addWidget(uav_bar, 1)
        
        uav_status_lbl = QtWidgets.QLabel("ожидание")
        uav_status_lbl.setFixedWidth(100)
        uav_row_layout.addWidget(uav_status_lbl)
        
        status_layout.addWidget(uav_row)
        self.status_widgets["uav"] = (uav_bar, uav_status_lbl)

    def _update_status_panel(self):
        """Update progress bars and status labels."""
        for robot in robots:
            key = f"robot_{robot.id}"
            if key not in self.status_widgets:
                continue
            bar, status_lbl = self.status_widgets[key]
            
            if robot.is_moving() or robot.route:
                phase_map = {
                    "to_pickup_zone": "→ зона забора",
                    "to_shelf_for_put": "→ полка (размещ)",
                    "to_shelf_for_pick": "→ полка (забор)",
                    "to_exit": "→ выход",
                    "to_home": "→ домой",
                    "return_home": "→ домой",
                    "rebalance_pick": "→ ребаланс",
                    "rebalance_put": "→ ребаланс (разм)",
                    "idle": "ожидание",
                }
                status = phase_map.get(robot.phase, robot.phase)
                bar.setValue(50)
            else:
                status = "ожидание"
                bar.setValue(0)
            
            if robot.carry:
                status += f" [{robot.carry}]"
            elif robot.task and robot.task.get("product"):
                status += f" [{robot.task['product']}]"
            
            status_lbl.setText(status)
        
        if "uav" in self.status_widgets:
            uav_bar, uav_status_lbl = self.status_widgets["uav"]
            from src.entities import uav
            state_map = {
                "idle": "ожидание",
                "to_inbound": "→ приём",
                "scanning": "сканирование",
                "to_home": "→ домой",
            }
            uav_status_lbl.setText(state_map.get(uav.state, uav.state))
            if uav.state == "scanning":
                uav_bar.setValue(int((30 - uav.scan_ticks) / 30 * 100))
            elif uav.state != "idle":
                uav_bar.setValue(50)
            else:
                uav_bar.setValue(0)

    def _build_stats_panel(self, content):
        """Setup statistics panel."""
        layout = QtWidgets.QVBoxLayout(content)
        layout.setContentsMargins(0, 0, 0, 0)
        stats_group = QtWidgets.QGroupBox("Статистика")
        stats_layout = QtWidgets.QVBoxLayout(stats_group)
        layout.addWidget(stats_group)

        self.stats_table = QtWidgets.QTableWidget(0, 4)
        self.stats_table.setHorizontalHeaderLabels(["Товар", "Всего", "На полках", "Спрос"])
        self.stats_table.horizontalHeader().setStretchLastSection(True)
        self.stats_table.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.Stretch)
        stats_layout.addWidget(self.stats_table)

    def _build_map_panel(self, content):
        """Setup map panel."""
        layout = QtWidgets.QVBoxLayout(content)
        layout.setContentsMargins(0, 0, 0, 0)
        map_group = QtWidgets.QGroupBox("Карта полок (клик по клетке)")
        map_layout = QtWidgets.QVBoxLayout(map_group)
        layout.addWidget(map_group)

        from src.core.grid import get_grid_w, get_grid_h
        self.map_table = QtWidgets.QTableWidget(get_grid_h(), get_grid_w())
        self.map_table.horizontalHeader().setStretchLastSection(True)
        self.map_table.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.Stretch)
        self.map_table.verticalHeader().setStretchLastSection(True)
        self.map_table.verticalHeader().setSectionResizeMode(QtWidgets.QHeaderView.Stretch)
        self.map_table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.map_table.cellClicked.connect(self._on_map_click)
        self.map_table.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.map_table.customContextMenuRequested.connect(self._on_map_context_menu)
        map_layout.addWidget(self.map_table)

    def _build_log_panel(self, content):
        """Setup log panel."""
        layout = QtWidgets.QVBoxLayout(content)
        layout.setContentsMargins(0, 0, 0, 0)
        log_group = QtWidgets.QGroupBox("Лог")
        log_layout = QtWidgets.QVBoxLayout(log_group)
        layout.addWidget(log_group)

        self.log_text = QtWidgets.QPlainTextEdit()
        self.log_text.setReadOnly(True)
        log_layout.addWidget(self.log_text)

        self.info_label = QtWidgets.QLabel("Выберите операцию")
        layout.addWidget(self.info_label)

    def _on_create_robot(self):
        """Handle create robot button."""
        from src.entities.robot import create_robot
        
        product = self.cb_new_robot_product.currentText()
        robot = create_robot(product)
        if robot is None:
            QtWidgets.QMessageBox.warning(
                self, "Ошибка", "Нет свободных станций для нового РТС"
            )
        else:
            log(f"Создан новый {robot.name} для {robot.product}")
            self._build_robot_cards()
            
            row = QtWidgets.QWidget()
            row_layout = QtWidgets.QHBoxLayout(row)
            row_layout.setContentsMargins(2, 1, 2, 1)
            lbl = QtWidgets.QLabel(robot.name)
            lbl.setFixedWidth(70)
            row_layout.addWidget(lbl)
            bar = QtWidgets.QProgressBar()
            bar.setRange(0, 100)
            bar.setValue(0)
            bar.setTextVisible(True)
            row_layout.addWidget(bar, 1)
            status_lbl = QtWidgets.QLabel("ожидание")
            status_lbl.setFixedWidth(100)
            row_layout.addWidget(status_lbl)
            
            status_layout = self.status_widgets.get("_layout")
            if status_layout:
                status_layout.addWidget(row)
            self.status_widgets[f"robot_{robot.id}"] = (bar, status_lbl)
        self.refresh_all()

    def _on_pick_product_color(self):
        """Open color picker for new product."""
        color = QtWidgets.QColorDialog.getColor(QtGui.QColor(100, 100, 255), self, "Выберите цвет материала")
        if color.isValid():
            self.btn_pick_color.setStyleSheet(f"background-color: {color.name()};")
            self._new_product_color = (color.red() / 255.0, color.green() / 255.0, color.blue() / 255.0, 1.0)

    def _on_create_product(self):
        """Handle create new product."""
        name = self.txt_new_product.text().strip()
        if not name:
            QtWidgets.QMessageBox.warning(self, "Ошибка", "Введите название материала")
            return
        if name in PRODUCTS:
            QtWidgets.QMessageBox.warning(self, "Ошибка", f"Материал '{name}' уже существует")
            return

        from src.config import add_product, PRODUCT_QCOLORS
        qcolor = QtGui.QColor(
            int(self._new_product_color[0] * 255),
            int(self._new_product_color[1] * 255),
            int(self._new_product_color[2] * 255)
        )
        add_product(name, self._new_product_color, qcolor)

        self.txt_new_product.clear()
        self.cb_supply.addItem(name)
        self.cb_new_robot_product.addItem(name)
        self._build_robot_cards()
        log(f"Создан новый материал: {name}")
        self.refresh_all()

    def _on_edit_map_toggle(self, checked):
        """Toggle map edit mode."""
        self._edit_mode = checked
        self.btn_edit_map.setText(f"Режим редактирования: {'ВКЛ' if checked else 'ВЫКЛ'}")
        self.info_label.setText("Режим редактирования карты: клик — добавить/удалить полку")

    def _on_expand_grid(self):
        """Open dialog to resize the warehouse grid."""
        from src.core.grid import get_grid_w, get_grid_h

        dialog = QtWidgets.QDialog(self)
        dialog.setWindowTitle("Расширение карты")
        layout = QtWidgets.QFormLayout(dialog)

        sb_w = QtWidgets.QSpinBox()
        sb_w.setRange(get_grid_w(), 30)
        sb_w.setValue(get_grid_w())
        layout.addRow("Ширина:", sb_w)

        sb_h = QtWidgets.QSpinBox()
        sb_h.setRange(get_grid_h(), 20)
        sb_h.setValue(get_grid_h())
        layout.addRow("Высота:", sb_h)

        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel
        )
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addRow(buttons)

        if dialog.exec_() == QtWidgets.QDialog.Accepted:
            new_w = sb_w.value()
            new_h = sb_h.value()
            old_w = get_grid_w()
            old_h = get_grid_h()
            if new_w != old_w or new_h != old_h:
                set_grid_size(new_w, new_h)
                self._rebuild_map_table()
                self.view3d.opts["center"] = QtGui.QVector3D(new_w / 2, new_h / 2, 1.4)
                self.view3d.grid_item.resetTransform()
                self.view3d.grid_item.setSize(new_w + 2, new_h + 2)
                self.view3d.grid_item.translate(new_w / 2 - 0.5, new_h / 2 - 0.5, 0)
                log(f"Карта расширена: {old_w}x{old_h} → {new_w}x{new_h}")
                self.refresh_all()

    def _rebuild_map_table(self):
        """Rebuild map table after grid resize."""
        from src.core.grid import get_grid_w, get_grid_h
        w = get_grid_w()
        h = get_grid_h()
        self.map_table.setRowCount(h)
        self.map_table.setColumnCount(w)

    def _on_demo_fill(self):
        """Handle demo fill button."""
        for p in PRODUCTS:
            supply_labeled(p, random.randint(2, 4))
        supply_unlabeled(3)
        self.refresh_all()

    def _on_supply_labeled(self):
        """Handle supply labeled button."""
        supply_labeled(self.cb_supply.currentText(), self.sb_supply_qty.value())
        self.refresh_all()

    def _on_supply_unlabeled(self):
        """Handle supply unlabeled button."""
        supply_unlabeled(self.sb_unlabeled_qty.value())
        self.refresh_all()

    def _on_request_product_changed(self):
        """Handle request product selection changed."""
        product = self.cb_request.currentText()
        if not product:
            self.sb_request_qty.setRange(0, 0)
            self.sb_request_qty.setValue(0)
            return

        from src.core.state import count_on_shelves
        max_qty = count_on_shelves(product)
        if max_qty <= 0:
            self.sb_request_qty.setRange(0, 0)
            self.sb_request_qty.setValue(0)
        else:
            self.sb_request_qty.setRange(1, max_qty)
            if self.sb_request_qty.value() > max_qty:
                self.sb_request_qty.setValue(max_qty)
            elif self.sb_request_qty.value() < 1:
                self.sb_request_qty.setValue(1)

    def _on_request(self):
        """Handle request button."""
        product = self.cb_request.currentText()
        if not product:
            QtWidgets.QMessageBox.information(self, "Запрос", "На складе нет материалов на полках.")
            return

        from src.core.state import count_on_shelves
        max_qty = count_on_shelves(product)
        qty = min(self.sb_request_qty.value(), max_qty)
        if qty <= 0:
            QtWidgets.QMessageBox.information(self, "Запрос", "Этот материал сейчас недоступен на полках.")
            return

        request_product(product, qty)
        self.refresh_all()

    def _on_rebalance(self):
        """Handle rebalance button."""
        rebalance_warehouse()
        log("Ребалансировка склада выполнена")

    def _on_check_rebalance(self):
        """Handle check rebalance button."""
        rebalance_warehouse(force=True)
        log("Проверка и ребалансировка склада выполнена")

    def _on_export_excel(self):
        """Handle export to Excel."""
        try:
            import openpyxl
            from openpyxl.chart import BarChart, Reference
        except ImportError:
            QtWidgets.QMessageBox.warning(
                self, "Ошибка", "Установите openpyxl: pip install openpyxl"
            )
            return

        from src.core.state import count_on_shelves, get_state
        state = get_state()
        
        wb = openpyxl.Workbook()
        wb.remove(wb.active)
        
        ws_summary = wb.create_sheet(title="Сводка")
        
        ws_summary.append(["Сводный отчёт по всем товарам"])
        ws_summary.append([])
        ws_summary.append(["Товар", "Всего", "На полках", "Ушло по спросу"])
        
        for p in PRODUCTS:
            total = state.stock_total.get(p, 0) + state.delivered_total.get(p, 0)
            on_shelf = count_on_shelves(p)
            delivered = state.delivered_total.get(p, 0)
            ws_summary.append([p, total, on_shelf, delivered])
        
        chart = BarChart()
        chart.title = "Товары: Всего, На полках, Ушло по спросу"
        chart.x_axis.title = "Товар"
        chart.y_axis.title = "Количество"
        chart.height = 12
        chart.width = 20
        chart.type = "col"
        chart.grouping = "clustered"
        
        data = Reference(ws_summary, min_col=2, min_row=3, max_col=4, max_row=3 + len(PRODUCTS))
        cats = Reference(ws_summary, min_col=1, min_row=4, max_row=3 + len(PRODUCTS))
        chart.add_data(data, titles_from_data=True)
        chart.set_categories(cats)
        ws_summary.add_chart(chart, "F2")
        
        for p in PRODUCTS:
            ws = wb.create_sheet(title=p)
            
            total = state.stock_total.get(p, 0) + state.delivered_total.get(p, 0)
            on_shelf = count_on_shelves(p)
            delivered = state.delivered_total.get(p, 0)
            
            ws.append([f"Отчёт по товару: {p}"])
            ws.append([])
            ws.append(["Показатель", "Значение"])
            ws.append(["Всего", total])
            ws.append(["На полках", on_shelf])
            ws.append(["Ушло по спросу", delivered])
            
            ws.append([])
            ws.append(["Показатель", "Количество"])
            ws.append(["Всего", total])
            ws.append(["На полках", on_shelf])
            ws.append(["Ушло по спросу", delivered])
            
            chart = BarChart()
            chart.title = f"Статистика: {p}"
            chart.x_axis.title = "Показатель"
            chart.y_axis.title = "Количество"
            chart.height = 12
            chart.width = 18
            
            data = Reference(ws, min_col=2, min_row=9, max_row=11)
            cats = Reference(ws, min_col=1, min_row=9, max_row=11)
            chart.add_data(data, titles_from_data=True)
            chart.set_categories(cats)
            ws.add_chart(chart, "D2")
        
        filename, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "Сохранить Excel", "", "Excel Files (*.xlsx)"
        )
        if filename:
            if not filename.endswith('.xlsx'):
                filename += '.xlsx'
            wb.save(filename)
            log(f"Экспорт в Excel: {filename}")
            QtWidgets.QMessageBox.information(
                self, "Успех", f"Файл сохранён:\n{filename}"
            )

    def _on_reset_robot(self, robot_id):
        """Handle robot reset button."""
        robot = robots[robot_id]
        robot.reset()
        log(f"РТС-{robot_id} сброшен на домашнюю позицию")

    def _on_robot_capacity_changed(self, robot_id, capacity):
        """Handle robot capacity changed."""
        robots[robot_id].capacity = capacity
        log(f"РТС-{robot_id} ёмкость изменена на {capacity}")

    def _on_robot_speed_changed(self, robot_id, speed):
        """Handle robot speed changed."""
        robots[robot_id].speed = speed
        log(f"РТС-{robot_id} скорость изменена на {speed}")

    def _on_robot_name_changed(self, robot, text):
        """Handle robot name changed."""
        robot.name = text

    def _on_robot_product_toggle(self, robot, product, state):
        """Handle robot product checkbox toggle."""
        if state:
            robot.products.add(product)
        else:
            robot.products.discard(product)
        self._update_robot_color(robot)

    def _update_robot_color(self, robot):
        """Update robot color and primary product to match its first product."""
        from src.config import PRODUCT_COLORS
        if robot.products:
            first = next(iter(robot.products))
            robot.product = first
            robot.color = PRODUCT_COLORS.get(first, robot.color)
        else:
            robot.color = (0.5, 0.5, 0.5, 1.0)

    def _on_map_click(self, row, col):
        """Handle map cell click."""
        x = col
        y = row

        state = get_state()

        if self._edit_mode:
            if is_shelf_cell(x, y):
                if is_custom_shelf(x, y):
                    if not self._confirm_remove_shelf(x, y):
                        return
                    remove_custom_shelf(x, y)
                    log(f"Полка ({x}, {y}) удалена")
                    self.refresh_all()
                    return
                else:
                    self.info_label.setText(f"Стандартная полка ({x}, {y}) — защищена от удаления")
                    return
            else:
                if is_shelf_cell(x, y):
                    return
                add_custom_shelf(x, y)
                log(f"Полка ({x}, {y}) добавлена")
                self.refresh_all()
                return

        if not is_shelf_cell(x, y):
            self.info_label.setText(f"Клетка ({x}, {y}) — проход/служебная зона")
            return

        info = state.shelf_state.get((x, y))
        if info is None:
            state.shelf_state[(x, y)] = {"count": 0, "product": None}
            info = state.shelf_state[(x, y)]
        if info["count"] == 0:
            self.info_label.setText(f"Полка ({x}, {y}) пустая")
        else:
            self.info_label.setText(
                f"Полка ({x}, {y}) | материал={info['product']} | "
                f"количество={info['count']}/{SHELF_CAPACITY}"
            )

    def _on_map_context_menu(self, pos):
        """Handle right-click context menu on map."""
        item = self.map_table.itemAt(pos)
        if item is None:
            return
        row = self.map_table.currentRow()
        col = self.map_table.currentColumn()
        if row < 0 or col < 0:
            return
        x, y = col, row
        menu = QtWidgets.QMenu(self)

        if is_shelf_cell(x, y) and is_custom_shelf(x, y):
            act_del = menu.addAction("Удалить полку")
        else:
            act_del = None

        act_exit = menu.addAction("Сделать точкой выхода")
        act_inbound = menu.addAction("Сделать точкой приёма")
        act_pick = menu.addAction("Сделать зоной забора")

        chosen = menu.exec_(self.map_table.viewport().mapToGlobal(pos))

        if chosen == act_del:
            if not self._confirm_remove_shelf(x, y):
                return
            remove_custom_shelf(x, y)
            log(f"Полка ({x}, {y}) удалена")
        elif chosen == act_exit:
            set_exit_cell(x, y)
            log(f"Точка выхода установлена: ({x}, {y})")
        elif chosen == act_inbound:
            set_inbound_cell(x, y)
            log(f"Точка приёма установлена: ({x}, {y})")
        elif chosen == act_pick:
            set_inbound_pick_cell(x, y)
            log(f"Зона забора установлена: ({x}, {y})")

        self.refresh_all()

    def _confirm_remove_shelf(self, x, y):
        """Ask for confirmation if shelf is not empty, otherwise proceed."""
        from src.core.state import get_state
        state = get_state()
        info = state.shelf_state.get((x, y), {"count": 0, "product": None})
        if info["count"] > 0:
            reply = QtWidgets.QMessageBox.question(
                self,
                "Подтверждение удаления",
                f"Полка ({x}, {y}) содержит {info['count']} ед. материала '{info['product'] or '?'}'.\n"
                f"Удалить полку вместе с содержимым?",
                QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
                QtWidgets.QMessageBox.No
            )
            return reply == QtWidgets.QMessageBox.Yes
        return True

    def tick(self):
        """Main simulation tick."""
        update_uav()
        assign_tasks()
        move_robots_one_step()
        advance_robot_phases()
        check_stuck_robots()
        check_rebalance_complete()
        self.refresh_all()

    def _refresh_request_products(self):
        """Refresh available products in request dropdown."""
        from src.core.state import count_on_shelves
        
        items = [p for p in PRODUCTS if count_on_shelves(p) > 0]
        
        self.cb_request.blockSignals(True)
        current_idx = self.cb_request.currentIndex()
        current_text = self.cb_request.currentText() if current_idx >= 0 else ""
        
        need_update = False
        if self.cb_request.count() != len(items):
            need_update = True
        else:
            for i, item in enumerate(items):
                if self.cb_request.itemText(i) != item:
                    need_update = True
                    break
        
        if need_update:
            self.cb_request.clear()
            if items:
                self.cb_request.addItems(items)
                if current_text in items:
                    self.cb_request.setCurrentIndex(items.index(current_text))
                else:
                    self.cb_request.setCurrentIndex(0)
        
        self.cb_request.blockSignals(False)

        has_items = len(items) > 0
        self.cb_request.setEnabled(has_items)
        self.sb_request_qty.setEnabled(has_items)

        if has_items:
            self._on_request_product_changed()
        else:
            self.sb_request_qty.setRange(0, 0)
            self.sb_request_qty.setValue(0)

    def refresh_stats(self):
        """Refresh statistics table."""
        from src.core.state import count_on_shelves, get_state
        state = get_state()
        
        all_products = PRODUCTS
        self.stats_table.setRowCount(len(all_products))
        
        for row, p in enumerate(all_products):
            total_passed = state.stock_total.get(p, 0) + state.delivered_total.get(p, 0)
            on_shelves = count_on_shelves(p)
            delivered = state.delivered_total.get(p, 0)
            
            vals = [
                p,
                str(total_passed),
                str(on_shelves),
                str(delivered),
            ]
            for col, val in enumerate(vals):
                item = QtWidgets.QTableWidgetItem(val)
                if col == 0:
                    color = PRODUCT_QCOLORS.get(p, QtGui.QColor(128, 128, 128))
                    item.setBackground(color)
                self.stats_table.setItem(row, col, item)

    def refresh_map(self):
        """Refresh map table."""
        from src.core.state import get_state
        from src.core.grid import get_grid_w, get_grid_h, get_exit_cell, get_inbound_cell, get_inbound_pick_cell
        state = get_state()
        
        gw = get_grid_w()
        gh = get_grid_h()
        if self.map_table.rowCount() != gh or self.map_table.columnCount() != gw:
            self.map_table.setRowCount(gh)
            self.map_table.setColumnCount(gw)
        
        ex = get_exit_cell()
        ib = get_inbound_cell()
        pk = get_inbound_pick_cell()
        uav_xy = (7, 5)  # UAV_HOME_POS
        
        for y in range(gh):
            for x in range(gw):
                item = QtWidgets.QTableWidgetItem("")

                robot_at_home = next((r for r in robots if r.home == (x, y)), None)

                if (x, y) == ex:
                    item.setText("OUT")
                    item.setBackground(QtGui.QColor(235, 235, 120))

                elif (x, y) == ib:
                    item.setText("IN")
                    item.setBackground(QtGui.QColor(120, 235, 120))

                elif (x, y) == pk:
                    item.setText("PICK")
                    item.setBackground(QtGui.QColor(120, 220, 220))

                elif (x, y) == uav_xy:
                    item.setText("БВС")
                    item.setBackground(QtGui.QColor(255, 255, 100))

                elif robot_at_home:
                    color = QtGui.QColor(
                        int(robot_at_home.color[0]*255),
                        int(robot_at_home.color[1]*255),
                        int(robot_at_home.color[2]*255)
                    )
                    item.setText(robot_at_home.name)
                    item.setBackground(color)

                elif is_shelf_cell(x, y):
                    info = state.shelf_state.get((x, y))
                    if info is None:
                        state.shelf_state[(x, y)] = {"count": 0, "product": None}
                        info = state.shelf_state[(x, y)]
                    if info["count"] == 0:
                        item.setText("0/5")
                        item.setBackground(QtGui.QColor(95, 95, 100))
                    else:
                        product = info["product"]
                        color = PRODUCT_QCOLORS.get(product, QtGui.QColor(128, 128, 128))
                        item.setText(f"{product[:3]}:{info['count']}/5")
                        item.setBackground(color)

                else:
                    item.setText("")
                    item.setBackground(QtGui.QColor(45, 45, 45))

                self.map_table.setItem(y, x, item)

    def refresh_log(self):
        """Refresh log text."""
        state = get_state()
        self.log_text.setPlainText("\n".join(state.event_log))

    def refresh_all(self):
        """Refresh all UI elements."""
        self._refresh_request_products()
        self._update_status_panel()
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

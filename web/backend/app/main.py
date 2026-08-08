import asyncio
import json
import logging

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from config.constants import PRODUCTS, PRODUCT_COLORS, SHELF_CAPACITY, HOME_CELLS, SHELF_X, hex_to_rgba
from config.constants import add_product as add_product_const
from core.state import get_state, get_shelf_max_capacity, get_shelf_allowed_products
from core.grid import (
    get_grid_w, get_grid_h, get_exit_cell, get_inbound_cell,
    get_inbound_pick_cell, CUSTOM_SHELF_CELLS, REMOVED_SHELF_CELLS,
    all_shelves, set_exit_cell, set_inbound_cell, set_inbound_pick_cell,
    set_grid_size, add_custom_shelf, remove_custom_shelf, is_shelf_cell,
    rebuild_aisle_cells,
)
from core.pathfinding import astar
from entities.robot import robots, create_robot, Robot as RobotClass
from entities.uav import uav
from simulation.robot_controller import move_robots_one_step, advance_robot_phases, check_stuck_robots
from simulation.task_manager import supply_labeled, supply_unlabeled, request_product, assign_tasks
from simulation.uav_controller import update_uav
from simulation.rebalancer import rebalance_warehouse, check_rebalance_complete
from websocket_manager import ws_manager

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="MagSim Warehouse")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def color_to_hex(rgba):
    r, g, b, a = rgba
    return '#{:02x}{:02x}{:02x}'.format(int(r*255), int(g*255), int(b*255))


def serialize_state():
    state = get_state()
    robot_data = []
    for r in robots:
        robot_data.append({
            "id": r.id,
            "name": r.name,
            "product": r.product,
            "products": list(r.products),
            "color": color_to_hex(r.color),
            "pos": list(r.pos),
            "draw_pos": r.draw_pos,
            "phase": r.phase,
            "carry": r.carry,
            "carry_qty": r.carry_qty,
            "home": list(r.home),
            "speed": r.speed,
            "capacity": r.capacity,
            "task": str(r.task) if r.task else None,
            "target_shelf": r.target_shelf,
            "carry_bob": r.carry_bob,
            "carry_appear_scale": r.carry_appear_scale,
            "delivery_anim_ticks": r.delivery_anim_ticks,
            "pickup_anim_ticks": r.pickup_anim_ticks,
        })
    shelves = []
    for shelf_pos in all_shelves():
        info = state.shelf_state.get(shelf_pos, {"product": None, "count": 0})
        allowed = get_shelf_allowed_products(shelf_pos)
        shelves.append({
            "x": shelf_pos[0], "y": shelf_pos[1],
            "product": info["product"],
            "count": info["count"],
            "capacity": get_shelf_max_capacity(shelf_pos),
            "allowed_products": list(allowed) if allowed else None,
        })
    products = []
    for p in PRODUCTS:
        products.append({
            "name": p,
            "color": color_to_hex(PRODUCT_COLORS.get(p, (0.5, 0.5, 0.5, 1.0))),
            "stock_total": state.stock_total.get(p, 0),
            "demand": state.demand.get(p, 0),
            "delivered": state.delivered_total.get(p, 0),
            "queue_length": len(state.robot_task_queues.get(p, [])),
            "retrieved": state.retrieved_total.get(p, 0),
            "on_shelves": sum(
                1 for info in state.shelf_state.values()
                if info["product"] == p
            ),
        })
    return {
        "type": "state_update",
        "data": {
            "robots": robot_data,
            "uav": {
                "pos": list(uav.pos),
                "state": uav.state,
                "scan_ticks": uav.scan_ticks,
                "uav_color": uav.uav_color,
            },
            "shelves": shelves,
            "grid_info": {
                "width": get_grid_w(),
                "height": get_grid_h(),
                "exit_cell": list(get_exit_cell()),
                "inbound_cell": list(get_inbound_cell()),
                "inbound_pick_cell": list(get_inbound_pick_cell()),
                "uav_home": [7, 5, 4.5],
                "shelf_x": sorted(SHELF_X),
                "home_cells": [list(c) for c in HOME_CELLS],
                "custom_shelves": [list(c) for c in CUSTOM_SHELF_CELLS],
                "removed_shelves": [list(c) for c in REMOVED_SHELF_CELLS],
            },
            "stats": {
                "stock_total": dict(state.stock_total),
                "demand": dict(state.demand),
                "delivered_total": dict(state.delivered_total),
            "retrieved_total": dict(state.retrieved_total),
                "retrieved_total": dict(state.retrieved_total),
                "rebalance_active": state.rebalance_active,
                "rebalance_moves_remaining": state.rebalance_moves_remaining,
                "shelf_capacity": SHELF_CAPACITY,
            },
            "products": products,
            "log": list(state.event_log),
        }
    }


async def simulation_tick():
    while True:
        try:
            state = get_state()
            move_robots_one_step()
            advance_robot_phases()
            assign_tasks()
            update_uav()
            check_stuck_robots()
            check_rebalance_complete()
            payload = serialize_state()
            await ws_manager.broadcast(payload)
        except Exception as e:
            logger.error(f"Simulation tick error: {e}")
        await asyncio.sleep(0.05)


@app.on_event("startup")
async def startup():
    asyncio.create_task(simulation_tick())


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await ws_manager.connect(websocket)
    try:
        while True:
            data = await websocket.receive_text()
            msg = json.loads(data)
            msg_type = msg.get("type", "")
            msg_data = msg.get("data", {})
            try:
                state = get_state()
                if msg_type == "supply_labeled":
                    supply_labeled(msg_data["product"], msg_data["qty"])
                elif msg_type == "supply_unlabeled":
                    supply_unlabeled(msg_data["qty"])
                elif msg_type == "request_product":
                    request_product(msg_data["product"], msg_data["qty"])
                elif msg_type == "create_robot":
                    robot = create_robot(msg_data["product"])
                    if robot is None:
                        get_state().event_log.appendleft("⚠ Нет свободной домашней станции для нового РТС!")
                elif msg_type == "create_product":
                    add_product_const(msg_data["name"], msg_data["color"])
                elif msg_type == "rebalance":
                    rebalance_warehouse(force=True)
                elif msg_type == "reset_robot":
                    rid = msg_data["robot_id"]
                    for r in robots:
                        if r.id == rid:
                            carry = r.carry
                            task = r.task
                            # Return cargo to stock + create putaway task
                            if carry:
                                state.stock_total[carry] += 1
                                state.robot_task_queues[carry].appendleft({"type": "putaway", "product": carry})
                                state.event_log.appendleft(f"РТС-{rid} сброшен, груз {carry} возвращён на станцию забора")
                            # Return task to queue
                            if task and task.get("type") == "putaway":
                                p = task["product"]
                                state.robot_task_queues[p].appendleft(task)
                            elif task and task.get("type") == "retrieve":
                                p = task["product"]
                                state.robot_task_queues[p].appendleft(task)
                            # Clear robot state without teleporting home
                            r.task = None
                            r.carry = None
                            r.target_shelf = None
                            r.route = []
                            r.current_target = None
                            r.phase = "idle"
                            r.delivery_anim_ticks = 0
                            r.pickup_anim_ticks = 0
                            r.carry_appear_scale = 1.0
                            r.wait_ticks = 0
                            r.stuck_ticks = 0
                            # Send robot home
                            if r.pos != r.home:
                                blocked = set()
                                for ro in robots:
                                    if ro != r and ro.current_target is None:
                                        blocked.add(ro.pos)
                                route = astar(r.pos, r.home, blocked=blocked)
                                if route:
                                    r.route = route
                                    r.phase = "to_home"
                            if not carry and not task:
                                state.event_log.appendleft(f"РТС-{rid} сброшен, возвращается на станцию")
                            break
                elif msg_type == "set_robot_product":
                    rid = msg_data["robot_id"]
                    product = msg_data["product"]
                    enabled = msg_data["enabled"]
                    for r in robots:
                        if r.id == rid:
                            if enabled:
                                r.products.add(product)
                            else:
                                r.products.discard(product)
                            # sync primary product (None if empty)
                            if r.products:
                                first = next(iter(r.products))
                                r.product = first
                                if first in PRODUCT_COLORS:
                                    r.color = PRODUCT_COLORS[first]
                            else:
                                r.product = None
                            break
                elif msg_type == "set_robot_color":
                    rid = msg_data["robot_id"]
                    color_hex = msg_data.get("color", "")
                    for r in robots:
                        if r.id == rid:
                            if color_hex and color_hex.lower() != "#ffffff":
                                from config.constants import hex_to_rgba
                                r.color = hex_to_rgba(color_hex)
                            else:
                                # reset to product color
                                if r.product and r.product in PRODUCT_COLORS:
                                    r.color = PRODUCT_COLORS[r.product]
                            break
                elif msg_type == "set_robot_speed":
                    rid = msg_data["robot_id"]
                    speed = max(0, min(1.0, msg_data["speed"]))
                    for r in robots:
                        if r.id == rid:
                            r.speed = speed
                            break
                elif msg_type == "set_robot_capacity":
                    rid = msg_data["robot_id"]
                    cap = max(1, msg_data["capacity"])
                    for r in robots:
                        if r.id == rid:
                            r.capacity = cap
                            break
                elif msg_type == "set_grid_size":
                    set_grid_size(msg_data["width"], msg_data["height"])
                elif msg_type == "set_exit_cell":
                    set_exit_cell(msg_data["x"], msg_data["y"])
                elif msg_type == "set_inbound_cell":
                    set_inbound_cell(msg_data["x"], msg_data["y"])
                elif msg_type == "set_inbound_pick_cell":
                    set_inbound_pick_cell(msg_data["x"], msg_data["y"])
                elif msg_type == "add_custom_shelf":
                    add_custom_shelf(msg_data["x"], msg_data["y"])
                elif msg_type == "remove_custom_shelf":
                    remove_custom_shelf(msg_data["x"], msg_data["y"])
                elif msg_type == "rename_robot":
                    rid = msg_data["robot_id"]
                    new_name = msg_data["name"]
                    for r in robots:
                        if r.id == rid:
                            r.name = new_name
                            get_state().event_log.appendleft(f"РТС-{rid} переименован в {new_name}")
                            break
                elif msg_type == "set_shelf_capacity":
                    x = int(msg_data["x"])
                    y = int(msg_data["y"])
                    cap = int(msg_data["capacity"])
                    if (x, y) in state.shelf_state:
                        if cap <= 0:
                            state.shelf_capacity_override.pop((x, y), None)
                        else:
                            state.shelf_capacity_override[(x, y)] = cap
                        state.event_log.appendleft(f"Вместимость полки ({x},{y}) = {cap}")
                elif msg_type == "set_shelf_allowed_products":
                    x = int(msg_data["x"])
                    y = int(msg_data["y"])
                    products_list = msg_data.get("products")
                    if products_list is None:
                        state.shelf_allowed_products.pop((x, y), None)
                    else:
                        state.shelf_allowed_products[(x, y)] = set(products_list)
                    state.event_log.appendleft(f"Ограничения полки ({x},{y}) обновлены")
                elif msg_type == "set_uav_color":
                    color_hex = msg_data.get("color")
                    if color_hex and color_hex.lower() != "#ffffff":
                        uav.uav_color = color_hex
                    else:
                        uav.uav_color = None
                    get_state().event_log.appendleft(f"Цвет БВС изменён")
                elif msg_type == "set_robot_home":
                    rid = msg_data["robot_id"]
                    hx = int(msg_data["home_x"])
                    hy = int(msg_data["home_y"])
                    for r in robots:
                        if r.id == rid:
                            old = r.home
                            r.home = (hx, hy)
                            if old not in {ro.home for ro in robots}:
                                _consts.HOME_CELLS.discard(old)
                            _consts.HOME_CELLS.add((hx, hy))
                            from core.grid import rebuild_aisle_cells
                            rebuild_aisle_cells()
                            get_state().event_log.appendleft(f"РТС-{rid} новая станция: ({hx},{hy})")
                            break
            except Exception as e:
                logger.error(f"Handler error for {msg_type}: {e}")
                get_state().event_log.appendleft(f"⚠ Ошибка: {e}")
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket)
    except Exception as e:
        logger.error(f"WS error: {e}")
        ws_manager.disconnect(websocket)


@app.get("/api/stats")
def get_full_stats():
    state = get_state()
    products_detail = []
    for p in PRODUCTS:
        on_shelf_count = sum(
            info["count"] for info in state.shelf_state.values()
            if info["product"] == p
        )
        products_detail.append({
            "name": p,
            "color": color_to_hex(PRODUCT_COLORS.get(p, (0.5, 0.5, 0.5, 1.0))),
            "stock_total": state.stock_total.get(p, 0),
            "demand": state.demand.get(p, 0),
            "delivered": state.delivered_total.get(p, 0),
            "retrieved": state.retrieved_total.get(p, 0),
            "queue_length": len(state.robot_task_queues.get(p, [])),
            "on_shelves": on_shelf_count,
        })
    robots_detail = []
    for r in robots:
        robots_detail.append({
            "id": r.id,
            "name": r.name,
            "product": r.product,
            "products": list(r.products),
            "color": color_to_hex(r.color),
            "phase": r.phase,
            "carry": r.carry,
            "carry_qty": r.carry_qty,
            "speed": r.speed,
            "capacity": r.capacity,
            "pos": list(r.pos),
            "home": list(r.home),
        })
    shelves_detail = []
    for shelf_pos in all_shelves():
        info = state.shelf_state.get(shelf_pos, {"product": None, "count": 0})
        allowed = get_shelf_allowed_products(shelf_pos)
        shelves_detail.append({
            "pos": list(shelf_pos),
            "x": shelf_pos[0], "y": shelf_pos[1],
            "product": info["product"],
            "count": info["count"],
            "capacity": get_shelf_max_capacity(shelf_pos),
            "allowed_products": list(allowed) if allowed else None,
        })
    return {
        "products": products_detail,
        "robots": robots_detail,
        "shelves": shelves_detail,
        "rebalance_active": state.rebalance_active,
        "rebalance_moves_remaining": state.rebalance_moves_remaining,
    }


@app.get("/api/export/excel")
def export_excel():
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
    from openpyxl.chart import BarChart, Reference
    from io import BytesIO
    import datetime

    state = get_state()
    wb = Workbook()

    # ─── Sheet 1: Products ───
    ws1 = wb.active
    ws1.title = "Материалы"
    headers = ["Материал", "Всего поставлено", "Спрос", "Доставлено на склад",
               "Забрано со склада", "В очереди", "На полках"]
    header_font = Font(bold=True, color="FFFFFF")
    header_fill = PatternFill(start_color="2c3e50", end_color="2c3e50", fill_type="solid")
    thin_border = Border(
        left=Side(style='thin'), right=Side(style='thin'),
        top=Side(style='thin'), bottom=Side(style='thin')
    )

    for col, h in enumerate(headers, 1):
        cell = ws1.cell(row=1, column=col, value=h)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal='center')
        cell.border = thin_border

    for row_idx, p in enumerate(PRODUCTS, 2):
        vals = [
            p,
            state.stock_total.get(p, 0),
            state.demand.get(p, 0),
            state.delivered_total.get(p, 0),
            state.retrieved_total.get(p, 0),
            len(state.robot_task_queues.get(p, [])),
            sum(1 for info in state.shelf_state.values() if info["product"] == p),
        ]
        for col, v in enumerate(vals, 1):
            cell = ws1.cell(row=row_idx, column=col, value=v)
            cell.border = thin_border
            cell.alignment = Alignment(horizontal='center')

    # Bar chart for product stats
    chart = BarChart()
    chart.type = "col"
    chart.title = "Сводка по материалам"
    chart.y_axis.title = "Количество"
    chart.x_axis.title = "Материалы"
    data = Reference(ws1, min_col=2, max_col=7, min_row=1, max_row=len(PRODUCTS)+1)
    cats = Reference(ws1, min_col=1, min_row=2, max_row=len(PRODUCTS)+1)
    chart.add_data(data, titles_from_data=True)
    chart.set_categories(cats)
    chart.shape = 4
    ws1.add_chart(chart, "A10")

    # ─── Sheet 2: Robots ───
    ws2 = wb.create_sheet("РТС")
    r_headers = ["ID", "Имя", "Продукт", "Продукты", "Фаза", "Несёт",
                 "Скорость", "Вместимость", "Позиция", "Дом"]
    for col, h in enumerate(r_headers, 1):
        cell = ws2.cell(row=1, column=col, value=h)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal='center')
        cell.border = thin_border
    for row_idx, r in enumerate(robots, 2):
        vals = [
            r.id, r.name, r.product, ", ".join(r.products), r.phase,
            r.carry or "", r.speed, r.capacity,
            f"({r.pos[0]}, {r.pos[1]})",
            f"({r.home[0]}, {r.home[1]})",
        ]
        for col, v in enumerate(vals, 1):
            cell = ws2.cell(row=row_idx, column=col, value=v)
            cell.border = thin_border
            cell.alignment = Alignment(horizontal='center')

    # ─── Sheet 3: Shelves ───
    ws3 = wb.create_sheet("Полки")
    s_headers = ["X", "Y", "Продукт", "Количество"]
    for col, h in enumerate(s_headers, 1):
        cell = ws3.cell(row=1, column=col, value=h)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal='center')
        cell.border = thin_border
    row_idx = 2
    for shelf_pos in all_shelves():
        info = state.shelf_state.get(shelf_pos, {"product": None, "count": 0})
        vals = [shelf_pos[0], shelf_pos[1], info["product"] or "", info["count"]]
        for col, v in enumerate(vals, 1):
            cell = ws3.cell(row=row_idx, column=col, value=v)
            cell.border = thin_border
            cell.alignment = Alignment(horizontal='center')
        row_idx += 1

    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)

    from fastapi.responses import Response
    return Response(
        content=buf.getvalue(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": f"attachment; filename=magsim_report_{datetime.date.today().isoformat()}.xlsx"
        },
    )


import subprocess
import sys


@app.get("/api/run-tests")
def run_all_tests():
    """Run all unittest tests and return structured JSON."""
    from tests.runner import run_unit_tests, run_all_scenarios
    test_results = run_unit_tests()
    scenario_results = run_all_scenarios()
    return {
        "tests": test_results,
        "scenarios": scenario_results,
    }


@app.get("/api/scenarios")
def list_scenarios():
    """Return list of available scenarios."""
    from tests.scenarios import SCENARIO_META
    return [
        {"id": sid, "name": meta["name"], "expected": meta["expected"]}
        for sid, meta in sorted(SCENARIO_META.items())
    ]


@app.get("/api/run-scenario/{scenario_id}")
def run_one_scenario(scenario_id: int):
    """Run a single scenario by ID."""
    from tests.scenarios import run_scenario
    result = run_scenario(scenario_id)
    if result.get("error"):
        raise HTTPException(status_code=404, detail=result["error"])
    return result


@app.get("/api/products")
def get_products():
    return PRODUCTS

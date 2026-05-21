"""Rebalancer module."""

from src.config import SHELF_CAPACITY, EXIT_CELL
from src.core.state import get_state
from src.core.grid import all_shelves, manhattan, shelf_distance_score
from src.entities import robots


def rebalance_warehouse(force: bool = False) -> None:
    """Rebalance warehouse by moving products closer to exit."""
    state = get_state()
    
    if sum(state.demand.values()) < 3 and not force:
        state.event_log.appendleft("Недостаточно данных для ребалансировки")
        return
    
    shelves_by_distance = sorted(all_shelves(), key=lambda s: manhattan(s, EXIT_CELL))
    
    shelves_capacity = {}
    for shelf in shelves_by_distance:
        info = state.shelf_state[shelf]
        if info["count"] > 0:
            shelves_capacity[shelf] = SHELF_CAPACITY - info["count"]
        else:
            shelves_capacity[shelf] = SHELF_CAPACITY
    
    rebalance_moves = []
    
    for i, shelf in enumerate(shelves_by_distance):
        current = state.shelf_state[shelf]
        
        if current["product"] is None or current["count"] == 0:
            continue
        
        closer_shelves = shelves_by_distance[:i]
        
        for target in closer_shelves:
            target_info = state.shelf_state[target]
            
            if shelves_capacity[target] > 0:
                qty_to_move = min(current["count"], shelves_capacity[target])
                
                for _ in range(qty_to_move):
                    rebalance_moves.append({
                        "from": shelf,
                        "to": target,
                        "product": current["product"]
                    })
                
                shelves_capacity[target] -= qty_to_move
                current["count"] -= qty_to_move
                
                if current["count"] == 0:
                    current["product"] = None
                    break
    
    if not rebalance_moves:
        state.event_log.appendleft("Ребалансировка не требуется - склад уже оптимален")
        return
    
    state.rebalance_active = True
    state.rebalance_moves_remaining = len(rebalance_moves)
    state.event_log.appendleft(f"Начало ребалансировки: {state.rebalance_moves_remaining} перемещений")
    
    for move in rebalance_moves:
        robot_for_product = next(
            (r for r in robots if r.product == move["product"]), None
        )
        if robot_for_product:
            state.robot_task_queues[move["product"]].append({
                "type": "rebalance",
                "from_shelf": move["from"],
                "to_shelf": move["to"]
            })


def check_rebalance_complete() -> None:
    """Check if rebalancing is complete."""
    state = get_state()
    if state.rebalance_active:
        has_rebalance_tasks = any(
            task["type"] == "rebalance" 
            for queue in state.robot_task_queues.values() 
            for task in queue
        )
        if not has_rebalance_tasks:
            state.rebalance_active = False
            state.event_log.appendleft("Ребалансировка завершена")

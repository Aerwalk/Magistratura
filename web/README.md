# MagSim Web — Микросервисная архитектура

Веб-версия симулятора складского управления с 3D-визуализацией.

## Архитектура

```
┌─────────────┐     ┌──────────────┐
│  Frontend   │────▶│   Backend    │
│  (nginx)    │     │  (FastAPI)   │
│  :8080      │     │  :8000       │
└─────────────┘     └──────┬───────┘
                           │
                    ┌──────▼───────┐
                    │  Simulation  │
                    │   Engine     │
                    └──────────────┘
```

- **Backend**: FastAPI + WebSocket + симуляционный движок (Python 3.11)
- **Frontend**: Статические файлы (nginx) + Three.js 3D-сцена на стороне клиента
- **Связь**: WebSocket для real-time обновлений (50ms тики)

## Быстрый запуск (Docker)

```bash
cd web
docker-compose up --build
```

Откройте http://localhost:8080

## Локальный запуск (без Docker)

### Backend

```bash
cd web/backend
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

### Frontend

Вариант A — через простой HTTP-сервер:

```bash
cd web/frontend/src
python -m http.server 3000
```

Затем откройте http://localhost:3000 и измените в `app.js` адрес WebSocket на `ws://localhost:8000/ws` (или настройте CORS).

Вариант B — через Docker только для backend:

```bash
cd web
docker-compose up --build backend
```

И откройте `web/frontend/src/index.html` через Live Server в VS Code (или любой HTTP-сервер).

## Управление

| Действие | Кнопка | Описание |
|----------|--------|----------|
| 📦 Поставка | Поставка | Добавляет маркированную поставку выбранного продукта |
| 📋 Без метки | Без метки | Добавляет немаркированную поставку (БВС сканирует) |
| 🛒 Запрос | Запрос | Создаёт запрос на выдачу продукта |
| + РТС | + РТС | Создаёт нового робота для выбранного продукта |
| + Мат-л | + Мат-л | Добавляет новый продукт с указанным цветом |
| ⚖ Ребаланс | ⚖ Ребаланс | Запускает ребалансировку склада |

## Элементы интерфейса

- **3D-сцена**: Вращение ЛКМ, зум колесом, панорама ПКМ
- **Панели**: Управление, РТС, Статистика, Лог — сворачиваются кликом по заголовку
- **На мобильных**: Боковая панель скрывается, открывается по ☰

## Структура проекта

```
web/
├── docker-compose.yml
├── README.md
├── backend/
│   ├── Dockerfile
│   ├── requirements.txt
│   └── app/
│       ├── main.py                  # FastAPI + WebSocket
│       ├── websocket_manager.py     # Управление WS-подключениями
│       ├── config/constants.py      # Конфигурация
│       ├── core/
│       │   ├── state.py             # Состояние склада (singleton)
│       │   ├── grid.py              # Сетка склада
│       │   └── pathfinding.py       # A* поиск пути
│       ├── entities/
│       │   ├── robot.py             # РТС
│       │   ├── uav.py               # БВС
│       │   └── base.py              # Базовые функции движения
│       └── simulation/
│           ├── task_manager.py      # Назначение задач
│           ├── robot_controller.py  # Фазы движения РТС
│           ├── uav_controller.py    # Управление БВС
│           └── rebalancer.py        # Ребалансировка
└── frontend/
    ├── Dockerfile
    ├── nginx.conf                   # Reverse-proxy к backend
    └── src/
        ├── index.html               # HTML-шаблон
        ├── style.css                # Тёмная тема, responsive
        └── app.js                   # Three.js 3D + UI
```

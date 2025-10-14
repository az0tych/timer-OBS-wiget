import asyncio
import json
import os
import time
from contextlib import asynccontextmanager
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Query
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
import uvicorn

STATE_FILE = 'timer_state.json'

class TimerState:
    def __init__(self):
        self.seconds: int = 0
        self.running: bool = False
        self.last_update: float = time.time()
        self.clients: set[WebSocket] = set()

#timer_seconds: int = 0
#running: bool = False
#clients: set[WebSocket] = set()

timer_state = TimerState()


def load_state():
    global timer_state
    #global timer_seconds, running
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                current_time = time.time()
                saved_seconds = data['seconds']
                last_update = data['last_update']
                if data['running']:
                    elapsed = max(0, current_time - last_update)
                    timer_state.seconds = max(0, saved_seconds - int(elapsed))
                    timer_state.running = timer_state.seconds > 0
                else:
                    timer_state.seconds = saved_seconds
                    timer_state.running = False

                timer_state.last_update = current_time
        except Exception as e:
            # если чтение или парсинг упал — игнорируем и стартуем с нуля
            print(f"Error loading state: {e}")
            timer_state = TimerState()
    else:
        timer_state = TimerState()


def save_state():
    data = {
        'seconds': timer_state.seconds,
        'running': timer_state.running,
        'last_update': timer_state.last_update
    }
    try:
        text = json.dumps(data)
        with open(STATE_FILE, 'w', encoding='utf-8') as f:
            f.write(text)
    except Exception as e:
        print(f"Error saving state: {e}")

# загружаем при старте модуля
load_state()

async def broadcast_time():
    """Раз в секунду шлём клиентам текущее время."""
    next_update = time.time()
    while True:
        try:
            if timer_state.running:
                current_time = time.time()
                elapsed = current_time - timer_state.last_update
                timer_state.seconds = max(0, timer_state.seconds - int(elapsed))
                timer_state.last_update = current_time

                if timer_state.seconds <= 0:
                    timer_state.running = False

                save_state()

            data = {"seconds": timer_state.seconds, "running": timer_state.running}
            disconnected = set()
            for ws in timer_state.clients:
                try:
                    await ws.send_json(data)
                except:
                    disconnected.add(ws)
            timer_state.clients.difference_update(disconnected)

            await asyncio.sleep(1)

        except asyncio.CancelledError:
            break
        except Exception as e:
            print(f"Broadcast error: {e}")
            await asyncio.sleep(1)  # Пауза при ошибках

@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(broadcast_time())
    yield
    task.cancel()
    await task

app = FastAPI(lifespan=lifespan)

# 1) Отдача главной страницы
@app.get("/")
async def root():
    return FileResponse("static/index.html")

@app.get("/kitty")
async def root():
    return FileResponse("static/index_kitty.html")

@app.get("/Silksong")
async def root():
    return FileResponse("static/index_HK.html")

# 2) Монтируем всё остальное статики
app.mount(
    "/static",
    StaticFiles(directory="static", html=True),
    name="static",
)

# 3) WebSocket для самого таймера
@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    timer_state.clients.add(ws)
    try:
        await ws.send_json({"seconds": timer_state.seconds, "running": timer_state.running})
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        timer_state.clients.discard(ws)

# 4) API для управления таймером
@app.post("/reset")
async def start_timer():
    timer_state.running = False
    timer_state.seconds = 0
    timer_state.last_update = time.time()
    save_state()
    return JSONResponse({
        "status": "reset",
        "seconds": timer_state.seconds
    })


@app.post("/start")
async def start_timer():
    if not timer_state.running:
        timer_state.running = True
        timer_state.last_update = time.time()
        save_state()
    return JSONResponse({
        "status": "started",
        "seconds": timer_state.seconds
    })

@app.post("/pause")
async def pause_timer():
    if timer_state.running:
        timer_state.running = False
        timer_state.last_update = time.time()
        save_state()
    return JSONResponse({
        "status": "paused",
        "seconds": timer_state.seconds
    })

@app.post("/adjust")
async def adjust_timer(delta: int = Query(..., description="delta в секундах")):
    timer_state.seconds = max(0, timer_state.seconds + delta)
    timer_state.last_update = time.time()
    save_state()
    return JSONResponse({
        "status": "adjusted",
        "seconds": timer_state.seconds
    })


@app.post("/set")
async def set_timer(seconds: int = Query(..., description="время в секундах")):
    timer_state.seconds = max(0, seconds)
    timer_state.last_update = time.time()
    save_state()
    return JSONResponse({
        "status": "set",
        "seconds": timer_state.seconds
    })

@app.get("/get")
async def get_timer():
    return JSONResponse({
        "seconds": timer_state.seconds,
        "running": timer_state.running
    })

if __name__ == "__main__":
    while True:
        try:
            uvicorn.run(
                "server:app",
                host="0.0.0.0",
                port=443,
                reload=False
            )
        except Exception as e:
            print(f"Server crashed: {e}. Restarting...")
            time.sleep(5)
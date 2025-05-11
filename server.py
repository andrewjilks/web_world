from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
import asyncio

app = FastAPI()
clients = {}  # WebSocket -> username
world_state = {}  # username -> { x, y }


@app.get("/")
async def index():
    with open("index.html", encoding="utf-8") as f:
        return HTMLResponse(f.read())


@app.websocket("/ws/{username}")
async def ws_endpoint(ws: WebSocket, username: str):
    await ws.accept()
    clients[ws] = username

    # Initialize player position if not already present
    if username not in world_state:
        world_state[username] = {"x": 400.0, "y": 300.0}

    try:
        while True:
            # Receive relative position updates from the client
            data = await ws.receive_json()
            if "dx" in data and "dy" in data:
                # Apply relative movement to the current position
                world_state[username]["x"] += data["dx"]
                world_state[username]["y"] += data["dy"]

                # Ensure the player doesn't move off the screen
                world_state[username]["x"] = max(0, min(800 - 10, world_state[username]["x"]))
                world_state[username]["y"] = max(0, min(600 - 10, world_state[username]["y"]))

    except WebSocketDisconnect:
        clients.pop(ws, None)
        world_state.pop(username, None)


@app.on_event("startup")
async def start_broadcast():
    asyncio.create_task(broadcast_loop())


async def broadcast_loop():
    size = 10
    while True:
        # Detect collisions
        colliding = {}
        names = list(world_state)
        for i in range(len(names)):
            for j in range(i + 1, len(names)):
                a, b = names[i], names[j]
                ax, ay = world_state[a]["x"], world_state[a]["y"]
                bx, by = world_state[b]["x"], world_state[b]["y"]
                if abs(ax - bx) < size and abs(ay - by) < size:
                    colliding[a] = True
                    colliding[b] = True

        # Broadcast state to all clients
        payload = {"players": world_state, "colliding": colliding}
        for ws in list(clients):
            try:
                await ws.send_json(payload)
            except:
                pass

        await asyncio.sleep(1 / 20)  # 20 FPS

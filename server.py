from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
import asyncio

app = FastAPI()
clients = {}      # WebSocket -> username
world_state = {}  # username -> { x, y }

@app.get("/")
async def index():
    with open("index.html", encoding="utf-8") as f:
        return HTMLResponse(f.read())

@app.websocket("/ws/{username}")
async def ws_endpoint(ws: WebSocket, username: str):
    await ws.accept()
    clients[ws] = username
    world_state[username] = { "x": 400.0, "y": 300.0 }

    try:
        while True:
            data = await ws.receive_json()
            # client sends absolute positions
            world_state[username]["x"] = float(data.get("x", world_state[username]["x"]))
            world_state[username]["y"] = float(data.get("y", world_state[username]["y"]))
    except WebSocketDisconnect:
        del clients[ws]
        del world_state[username]

@app.on_event("startup")
async def start_broadcast():
    asyncio.create_task(broadcast_loop())

async def broadcast_loop():
    size = 10
    while True:
        # detect collisions
        colliding = {}
        names = list(world_state)
        for i in range(len(names)):
            for j in range(i+1, len(names)):
                a, b = names[i], names[j]
                ax, ay = world_state[a]["x"], world_state[a]["y"]
                bx, by = world_state[b]["x"], world_state[b]["y"]
                if abs(ax - bx) < size and abs(ay - by) < size:
                    colliding[a] = True
                    colliding[b] = True

        payload = { "players": world_state, "colliding": colliding }
        for ws in list(clients):
            try:
                await ws.send_json(payload)
            except:
                pass

        await asyncio.sleep(0.05)  # 20 FPS

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

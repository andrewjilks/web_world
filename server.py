from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
import asyncio
import random  # for demo pickup

app = FastAPI()
clients: dict[WebSocket, str] = {}     # WebSocket -> username
world_state: dict[str, dict] = {}      # username -> { x, y, inventory, health }

@app.get("/")
async def index():
    with open("index.html", encoding="utf-8") as f:
        return HTMLResponse(f.read())

@app.websocket("/ws/{username}")
async def ws_endpoint(ws: WebSocket, username: str):
    await ws.accept()
    clients[ws] = username

    # Initialize player state if new
    if username not in world_state:
        world_state[username] = {
            "x": 400.0,
            "y": 300.0,
            "inventory": None,
            "health": 100
        }

    try:
        while True:
            data = await ws.receive_json()

            # 1) Handle movement
            if "dx" in data and "dy" in data:
                st = world_state[username]
                st["x"] = max(0, min(800 - 10, st["x"] + data["dx"]))
                st["y"] = max(0, min(600 - 10, st["y"] + data["dy"]))

            # 2) Handle spawn (client telling us its initial state; redundant here)
            elif data.get("type") == "spawn":
                # Could validate or overwrite defaults if you want
                world_state[username]["inventory"] = data.get("inventory", None)
                world_state[username]["health"]    = data.get("health", 100)

            # 3) Handle pickup request
            elif data.get("type") == "pickup":
                player_st = world_state[username]
                if player_st["inventory"] is None:
                    # Demo: randomly pick one of a few example items
                    sample_items = [
                        {"id": "apple", "name": "Apple"},
                        {"id": "key",   "name": "Old Key"},
                        {"id": "coin",  "name": "Gold Coin"}
                    ]
                    item = random.choice(sample_items)
                    player_st["inventory"] = item
                    success = True
                else:
                    # Already holding something
                    item = player_st["inventory"]
                    success = False

                # Send pickupResult back just to this client
                await ws.send_json({
                    "type":   "pickupResult",
                    "player": username,
                    "item":   item,
                    "success": success
                })

    except WebSocketDisconnect:
        # Clean up on disconnect
        clients.pop(ws, None)
        world_state.pop(username, None)

@app.on_event("startup")
async def start_broadcast():
    asyncio.create_task(broadcast_loop())

async def broadcast_loop():
    size = 10
    while True:
        # Detect collisions (unchanged)
        colliding: dict[str, bool] = {}
        names = list(world_state)
        for i in range(len(names)):
            for j in range(i + 1, len(names)):
                a, b = names[i], names[j]
                ax, ay = world_state[a]["x"], world_state[a]["y"]
                bx, by = world_state[b]["x"], world_state[b]["y"]
                if abs(ax - bx) < size and abs(ay - by) < size:
                    colliding[a] = True
                    colliding[b] = True

        # Broadcast full world state (including inventory + health)
        payload = {
            "players":   world_state,
            "colliding": colliding
        }
        for ws in list(clients):
            try:
                await ws.send_json(payload)
            except:
                pass

        await asyncio.sleep(1 / 20)  # 20 FPS

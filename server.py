from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
import asyncio
import uuid

app = FastAPI()

clients: dict[WebSocket, str] = {}      # ws -> username
world_state: dict[str, dict] = {}       # username -> {x,y,inventory,health}
ground_items: dict[str, dict] = {}      # item_id -> {type, x, y}

# Pre-spawn a few apples on the ground
def spawn_initial_items():
    for pos in [(100,100), (300,200), (500,400)]:
        for kind in ("apple", "poison"):
            item_id = str(uuid.uuid4())
            ground_items[item_id] = {
                "type": kind,
                "x": pos[0] + (0 if kind=="apple" else 20),
                "y": pos[1]
            }

@app.on_event("startup")
async def startup():
    spawn_initial_items()
    asyncio.create_task(broadcast_loop())

@app.get("/")
async def index():
    with open("index.html", encoding="utf-8") as f:
        return HTMLResponse(f.read())

@app.websocket("/ws/{username}")
async def ws_endpoint(ws: WebSocket, username: str):
    await ws.accept()
    clients[ws] = username

    if username not in world_state:
        world_state[username] = {
            "x": 400.0, "y": 300.0,
            "inventory": None,
            "health": 100
        }

    try:
        while True:
            data = await ws.receive_json()

            # Movement
            if "dx" in data and "dy" in data:
                st = world_state[username]
                st["x"] = max(0, min(800-10, st["x"] + data["dx"]))
                st["y"] = max(0, min(600-10, st["y"] + data["dy"]))

            # Pickup / drop
            elif data.get("type") == "pickup":
                player = world_state[username]
                # If holding something, drop it
                if player["inventory"]:
                    dropped = player["inventory"]
                    item_id = str(uuid.uuid4())
                    ground_items[item_id] = {
                        "type": dropped["type"],
                        "x": player["x"],
                        "y": player["y"]
                    }
                    player["inventory"] = None
                    await ws.send_json({
                        "type": "dropResult",
                        "success": True
                    })
                else:
                    # Find nearest ground item within 30px
                    nearest_id, nearest_d = None, 1e9
                    for iid, it in ground_items.items():
                        d = abs(it["x"] - world_state[username]["x"]) + abs(it["y"] - world_state[username]["y"])
                        if d < nearest_d:
                            nearest_d, nearest_id = d, iid
                    if nearest_id and nearest_d <= 30:
                        picked = ground_items.pop(nearest_id)
                        world_state[username]["inventory"] = {"type": picked["type"]}
                        await ws.send_json({
                            "type": "pickupResult",
                            "success": True,
                            "item": picked
                        })
                    else:
                        await ws.send_json({
                            "type": "pickupResult",
                            "success": False
                        })

            # Use item
            elif data.get("type") == "use":
                player = world_state[username]
                itm = player["inventory"]
                if itm:
                    if itm["type"] == "apple":
                        player["health"] = min(100, player["health"] + 20)
                    elif itm["type"] == "poison":
                        player["health"] = max(0, player["health"] - 30)
                    player["inventory"] = None
                    await ws.send_json({
                        "type": "useResult",
                        "health": player["health"]
                    })

    except WebSocketDisconnect:
        clients.pop(ws, None)
        world_state.pop(username, None)

async def broadcast_loop():
    size = 10
    while True:
        # Collisions
        colliding = {}
        names = list(world_state)
        for i in range(len(names)):
            for j in range(i+1, len(names)):
                a,b = names[i], names[j]
                ax,ay = world_state[a]["x"], world_state[a]["y"]
                bx,by = world_state[b]["x"], world_state[b]["y"]
                if abs(ax-bx)<size and abs(ay-by)<size:
                    colliding[a]=colliding[b]=True

        # Build payload
        payload = {
            "players": world_state,
            "colliding": colliding,
            "groundItems": ground_items
        }
        for ws in list(clients):
            try:
                await ws.send_json(payload)
            except:
                pass

        await asyncio.sleep(1/20)

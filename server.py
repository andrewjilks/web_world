import os
import json
import asyncio
import uuid
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse

app = FastAPI()

clients: dict[WebSocket, str] = {}       # ws -> username
world_state: dict[str, dict] = {}        # username -> { map, x, y, inventory, health }
ground_items: dict[str, dict] = {}       # item_id -> { type, x, y }
MAPS: dict[str, dict] = {}               # map_name -> map data


def load_maps():
    """Load all JSON files from maps/ into MAPS."""
    for fn in os.listdir("maps"):
        if fn.endswith(".json"):
            with open(os.path.join("maps", fn), encoding="utf-8") as f:
                data = json.load(f)
                MAPS[data["name"]] = data


def spawn_initial_items():
    """Spawn apples & poison apples only in zone1 at fixed positions."""
    positions = [(100, 100), (300, 200), (500, 400)]
    for pos in positions:
        for kind in ("apple", "poison"):
            item_id = str(uuid.uuid4())
            ground_items[item_id] = {
                "type": kind,
                "x": pos[0] + (0 if kind == "apple" else 20),
                "y": pos[1]
            }


@app.on_event("startup")
async def startup():
    load_maps()
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

    # Initialize new player
    if username not in world_state:
        world_state[username] = {
            "map": "zone1",
            "x": MAPS["zone1"]["spawn"]["x"],
            "y": MAPS["zone1"]["spawn"]["y"],
            "inventory": None,
            "health": 100
        }

    try:
        while True:
            data = await ws.receive_json()
            st = world_state[username]

            # Movement update
            if "dx" in data and "dy" in data:
                nx = st["x"] + data["dx"]
                ny = st["y"] + data["dy"]
                st["x"] = max(0, min(800 - 10, nx))
                st["y"] = max(0, min(600 - 10, ny))

                # Portal check
                portal = MAPS[st["map"]]["portal"]
                if (portal["x1"] <= st["x"] <= portal["x2"]
                    and portal["y1"] <= st["y"] <= portal["y2"]):
                    # switch maps
                    new_map = portal["target"]
                    st["map"] = new_map
                    st["x"], st["y"] = (
                        MAPS[new_map]["spawn"]["x"],
                        MAPS[new_map]["spawn"]["y"]
                    )
                    # notify client of new map data
                    await ws.send_json({
                        "type": "mapData",
                        "map": MAPS[new_map]
                    })

            # Pickup / Drop
            elif data.get("type") == "pickup":
                player = st
                # if holding, drop it
                if player["inventory"]:
                    dropped = player["inventory"]
                    item_id = str(uuid.uuid4())
                    ground_items[item_id] = {
                        "type": dropped["type"],
                        "x": player["x"],
                        "y": player["y"]
                    }
                    player["inventory"] = None
                    await ws.send_json({"type": "dropResult", "success": True})
                else:
                    # find nearest ground item in current zone
                    nearest_id, nearest_d = None, float("inf")
                    for iid, it in ground_items.items():
                        d = abs(it["x"] - player["x"]) + abs(it["y"] - player["y"])
                        if d < nearest_d:
                            nearest_d, nearest_id = d, iid
                    if nearest_id and nearest_d <= 30 and st["map"] == "zone1":
                        picked = ground_items.pop(nearest_id)
                        player["inventory"] = {"type": picked["type"]}
                        await ws.send_json({
                            "type": "pickupResult",
                            "success": True,
                            "item": picked
                        })
                    else:
                        await ws.send_json({"type": "pickupResult", "success": False})

            # Use item
            elif data.get("type") == "use":
                player = st
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
    """20 FPS world-state broadcast, per-map filtering."""
    size = 10
    while True:
        # detect collisions
        colliding: dict[str, bool] = {}
        names = list(world_state)
        for i in range(len(names)):
            for j in range(i + 1, len(names)):
                a, b = names[i], names[j]
                ax, ay = world_state[a]["x"], world_state[a]["y"]
                bx, by = world_state[b]["x"], world_state[b]["y"]
                if abs(ax - bx) < size and abs(ay - by) < size:
                    colliding[a] = colliding[b] = True

        # group players by map
        by_map: dict[str, dict] = {}
        for name, st in world_state.items():
            by_map.setdefault(st["map"], {})[name] = st

        # send each client only its current-map state
        for ws, uname in list(clients.items()):
            st = world_state.get(uname)
            if not st:
                continue
            m = st["map"]
            payload = {
                "players":   by_map.get(m, {}),
                "colliding": {n: True for n in colliding if world_state[n]["map"] == m}
            }
            if m == "zone1":
                payload["groundItems"] = ground_items
            try:
                await ws.send_json(payload)
            except:
                pass

        await asyncio.sleep(1 / 20)

import os
import json
import asyncio
import uuid
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse

app = FastAPI()

# Track WebSocket -> username
clients: dict[WebSocket, str] = {}
# Track username -> player state
world_state: dict[str, dict] = {}
# Ground items (only in zone1)
ground_items: dict[str, dict] = {}
# Loaded map definitions
MAPS: dict[str, dict] = {}


def load_maps():
    """Load each map’s JSON from maps/ into MAPS."""
    for fn in os.listdir("maps"):
        if fn.endswith(".json"):
            with open(os.path.join("maps", fn), encoding="utf-8") as f:
                data = json.load(f)
                MAPS[data["name"]] = data


def spawn_items_zone1():
    """Place apples & poison apples in zone1 at startup."""
    positions = [(150, 150), (350, 250), (550, 350)]
    for x, y in positions:
        for kind in ("apple", "poison"):
            iid = str(uuid.uuid4())
            ground_items[iid] = {"type": kind, "x": x + (0 if kind == "apple" else 20), "y": y}


@app.on_event("startup")
async def on_startup():
    load_maps()
    spawn_items_zone1()
    asyncio.create_task(broadcast_loop())


@app.get("/")
async def get_index():
    with open("index.html", encoding="utf-8") as f:
        return HTMLResponse(f.read())


@app.websocket("/ws/{username}")
async def ws_ws(ws: WebSocket, username: str):
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

    # Always send initial mapData
    await ws.send_json({"type": "mapData", "map": MAPS[world_state[username]["map"]]})

    try:
        while True:
            data = await ws.receive_json()
            st = world_state[username]

            # Movement
            if "dx" in data and "dy" in data:
                st["x"] = max(0, min(800 - 10, st["x"] + data["dx"]))
                st["y"] = max(0, min(600 - 10, st["y"] + data["dy"]))

                # Portal check
                portal = MAPS[st["map"]]["portal"]
                if portal["x1"] <= st["x"] <= portal["x2"] and portal["y1"] <= st["y"] <= portal["y2"]:
                    # switch maps
                    new_map = portal["target"]
                    st["map"] = new_map
                    st["x"], st["y"] = MAPS[new_map]["spawn"]["x"], MAPS[new_map]["spawn"]["y"]
                    await ws.send_json({"type": "mapData", "map": MAPS[new_map]})

            # Pickup / Drop
            elif data.get("type") == "pickup":
                # Drop if holding
                if st["inventory"]:
                    obj = st["inventory"]
                    iid = str(uuid.uuid4())
                    ground_items[iid] = {"type": obj["type"], "x": st["x"], "y": st["y"]}
                    st["inventory"] = None
                    await ws.send_json({"type": "dropResult", "success": True})
                else:
                    # Pick nearest item in zone1
                    nearest, nd = None, float("inf")
                    for iid, itm in ground_items.items():
                        d = abs(itm["x"] - st["x"]) + abs(itm["y"] - st["y"])
                        if d < nd:
                            nearest, nd = iid, d
                    if nearest and nd <= 30 and st["map"] == "zone1":
                        picked = ground_items.pop(nearest)
                        st["inventory"] = {"type": picked["type"]}
                        await ws.send_json({"type": "pickupResult", "success": True, "item": picked})
                    else:
                        await ws.send_json({"type": "pickupResult", "success": False})

            # Use item
            elif data.get("type") == "use":
                if st["inventory"]:
                    if st["inventory"]["type"] == "apple":
                        st["health"] = min(100, st["health"] + 20)
                    else:
                        st["health"] = max(0, st["health"] - 30)
                    st["inventory"] = None
                    await ws.send_json({"type": "useResult", "health": st["health"]})

    except WebSocketDisconnect:
        clients.pop(ws, None)
        world_state.pop(username, None)


async def broadcast_loop():
    """Broadcast per-map state at 20 FPS."""
    size = 10
    while True:
        # Collision detection
        colliding: dict[str, bool] = {}
        names = list(world_state)
        for i in range(len(names)):
            for j in range(i + 1, len(names)):
                a, b = names[i], names[j]
                if world_state[a]["map"] != world_state[b]["map"]:
                    continue
                ax, ay = world_state[a]["x"], world_state[a]["y"]
                bx, by = world_state[b]["x"], world_state[b]["y"]
                if abs(ax - bx) < size and abs(ay - by) < size:
                    colliding[a] = colliding[b] = True

        # Group players by map
        by_map: dict[str, dict] = {}
        for name, st in world_state.items():
            by_map.setdefault(st["map"], {})[name] = st

        # Send each client only its map’s data
        for ws, user in list(clients.items()):
            st = world_state.get(user)
            if not st:
                continue
            m = st["map"]
            payload = {
                "players": by_map.get(m, {}),
                "colliding": {n: True for n in colliding if world_state[n]["map"] == m}
            }
            if m == "zone1":
                payload["groundItems"] = ground_items
            try:
                await ws.send_json(payload)
            except:
                pass

        await asyncio.sleep(1 / 20)

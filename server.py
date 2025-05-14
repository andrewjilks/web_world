import os
import json
import asyncio
import uuid
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse

app = FastAPI()

clients: dict[WebSocket, str] = {}
world_state: dict[str, dict] = {}
ground_items: dict[str, dict[str, dict]] = {"zone1": {}, "zone2": {}}
MAPS: dict[str, dict] = {}

def load_maps():
    for fn in os.listdir("maps"):
        if fn.endswith(".json"):
            with open(os.path.join("maps", fn), encoding="utf-8") as f:
                data = json.load(f)
                MAPS[data["name"]] = data

def spawn_items_zone1():
    positions = [(150, 150), (350, 250), (550, 350)]
    for x, y in positions:
        for kind in ("apple", "poison"):
            iid = str(uuid.uuid4())
            ground_items["zone1"][iid] = {
                "type": kind,
                "x": x + (0 if kind == "apple" else 20),
                "y": y
            }

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

    if username not in world_state:
        world_state[username] = {
            "map": "zone1",
            "x": MAPS["zone1"]["spawn"]["x"],
            "y": MAPS["zone1"]["spawn"]["y"],
            "inventory": None,
            "health": 100
        }

    await ws.send_json({"type": "mapData", "map": MAPS[world_state[username]["map"]]})

    try:
        while True:
            data = await ws.receive_json()
            st = world_state[username]

            # Movement & portal
            if "dx" in data and "dy" in data:
                st["x"] = max(0, min(800 - 10, st["x"] + data["dx"]))
                st["y"] = max(0, min(600 - 10, st["y"] + data["dy"]))
                portal = MAPS[st["map"]]["portal"]
                if portal["x1"] <= st["x"] <= portal["x2"] and portal["y1"] <= st["y"] <= portal["y2"]:
                    new_map = portal["target"]
                    st["map"] = new_map
                    st["x"], st["y"] = MAPS[new_map]["spawn"]["x"], MAPS[new_map]["spawn"]["y"]
                    await ws.send_json({"type": "mapData", "map": MAPS[new_map]})

            # Pickup / Drop toggle
            elif data.get("type") == "pickup":
                if st["inventory"]:
                    # Drop into current map
                    obj = st["inventory"]
                    iid = str(uuid.uuid4())
                    ground_items[st["map"]][iid] = {"type": obj["type"], "x": st["x"], "y": st["y"]}
                    st["inventory"] = None
                    await ws.send_json({"type": "dropResult", "success": True})
                else:
                    # Pick nearest in current map
                    nearest, nd = None, float("inf")
                    for iid, itm in ground_items[st["map"]].items():
                        d = abs(itm["x"] - st["x"]) + abs(itm["y"] - st["y"])
                        if d < nd:
                            nearest, nd = iid, d
                    if nearest and nd <= 30:
                        picked = ground_items[st["map"]].pop(nearest)
                        st["inventory"] = {"type": picked["type"]}
                        await ws.send_json({"type": "pickupResult", "success": True, "item": picked})
                    else:
                        await ws.send_json({"type": "pickupResult", "success": False})

            # Use
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
    size = 10
    while True:
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

        by_map: dict[str, dict] = {}
        for name, st in world_state.items():
            by_map.setdefault(st["map"], {})[name] = st

        for ws, user in list(clients.items()):
            st = world_state.get(user)
            if not st:
                continue
            m = st["map"]
            payload = {
                "players":   by_map.get(m, {}),
                "colliding": {n: True for n in colliding if world_state[n]["map"] == m},
                "groundItems": ground_items[m]
            }
            try:
                await ws.send_json(payload)
            except:
                pass

        await asyncio.sleep(1 / 20)

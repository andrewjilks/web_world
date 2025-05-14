from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
import asyncio

app = FastAPI()
clients = {}  # WebSocket -> username
world_state = {}  # username -> player data

MAPS = {
    "zone1": {
        "name": "zone1",
        "spawn": {"x": 100.0, "y": 100.0},
        "objects": [
            {"id": "apple1", "type": "apple", "x": 200.0, "y": 200.0},
            {"id": "poison1", "type": "poison", "x": 300.0, "y": 300.0}
        ]
    },
    "zone2": {
        "name": "zone2",
        "spawn": {"x": 400.0, "y": 100.0},
        "objects": []
    }
}

@app.get("/")
async def index():
    with open("index.html", encoding="utf-8") as f:
        return HTMLResponse(f.read())


@app.websocket("/ws/{username}")
async def ws_endpoint(ws: WebSocket, username: str):
    await ws.accept()
    clients[ws] = username

    # Initialize player if not already present
    if username not in world_state:
        world_state[username] = {
            "map": "zone1",
            "x": MAPS["zone1"]["spawn"]["x"],
            "y": MAPS["zone1"]["spawn"]["y"],
            "inventory": None,
            "health": 100
        }

    # Always send the current map data
    await ws.send_json({
        "type": "mapData",
        "map": MAPS[world_state[username]["map"]]
    })

    try:
        while True:
            data = await ws.receive_json()
            st = world_state[username]

            # Movement
            if "dx" in data and "dy" in data:
                st["x"] += data["dx"]
                st["y"] += data["dy"]
                st["x"] = max(0, min(800 - 10, st["x"]))
                st["y"] = max(0, min(600 - 10, st["y"]))

            # Pickup
            elif data.get("action") == "pickup":
                for obj in MAPS[st["map"]]["objects"]:
                    if abs(obj["x"] - st["x"]) < 10 and abs(obj["y"] - st["y"]) < 10:
                        st["inventory"] = obj
                        MAPS[st["map"]]["objects"].remove(obj)
                        break

            # Drop
            elif data.get("action") == "drop":
                if st["inventory"]:
                    obj = st["inventory"]
                    obj["x"] = st["x"]
                    obj["y"] = st["y"]
                    MAPS[st["map"]]["objects"].append(obj)
                    st["inventory"] = None

            # Use
            elif data.get("action") == "use":
                if st["inventory"]:
                    if st["inventory"]["type"] == "apple":
                        st["health"] = min(100, st["health"] + 10)
                    elif st["inventory"]["type"] == "poison":
                        st["health"] = max(0, st["health"] - 20)
                    st["inventory"] = None

            # Change map
            elif data.get("action") == "changeMap":
                target = data.get("target")
                if target in MAPS:
                    st["map"] = target
                    st["x"] = MAPS[target]["spawn"]["x"]
                    st["y"] = MAPS[target]["spawn"]["y"]
                    await ws.send_json({
                        "type": "mapData",
                        "map": MAPS[target]
                    })

    except WebSocketDisconnect:
        clients.pop(ws, None)
        world_state.pop(username, None)


@app.on_event("startup")
async def start_broadcast():
    asyncio.create_task(broadcast_loop())


async def broadcast_loop():
    size = 10
    while True:
        # Collision detection
        colliding = {}
        names = list(world_state)
        for i in range(len(names)):
            for j in range(i + 1, len(names)):
                a, b = names[i], names[j]
                if world_state[a]["map"] != world_state[b]["map"]:
                    continue
                ax, ay = world_state[a]["x"], world_state[a]["y"]
                bx, by = world_state[b]["x"], world_state[b]["y"]
                if abs(ax - bx) < size and abs(ay - by) < size:
                    colliding[a] = True
                    colliding[b] = True

        # Broadcast per-map updates
        for ws, username in list(clients.items()):
            try:
                st = world_state[username]
                player_map = st["map"]

                visible_players = {
                    name: data for name, data in world_state.items()
                    if data["map"] == player_map
                }

                await ws.send_json({
                    "type": "update",
                    "players": visible_players,
                    "colliding": colliding,
                    "objects": MAPS[player_map]["objects"]
                })
            except:
                pass

        await asyncio.sleep(1 / 20)  # 20 FPS

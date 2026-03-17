#!/usr/bin/env python3
"""
Fully automated Home Assistant dev setup.

1. Completes onboarding (creates dev/dev account)
2. Gets a long-lived access token
3. Creates areas and assigns entities to rooms
4. Writes config.json for mission-control with the HA token
"""
import json
import os
import sys
import time

import requests
import websockets
import asyncio

HA_BASE_URL = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8123"
CONFIG_OUT = sys.argv[2] if len(sys.argv) > 2 else None

CLIENT_ID = f"{HA_BASE_URL}/"
DEV_USER = "dev"
DEV_PASSWORD = "devdevdev"
DEV_NAME = "Developer"
DEV_LANGUAGE = "en"

AREAS = [
    "Kitchen",
    "Living Room",
    "Master Bedroom",
    "Kids Room",
    "Office",
    "Garage",
    "Hallway",
]

ENTITY_AREA_MAP = {
    # Kitchen (4 devices)
    "light.kitchen_ceiling_light": "Kitchen",
    "light.kitchen_under_cabinet": "Kitchen",
    "switch.coffee_maker": "Kitchen",
    "binary_sensor.kitchen_window": "Kitchen",
    "media_player.kitchen_speaker": "Kitchen",
    # Living Room (6 devices)
    "light.living_room_lamp": "Living Room",
    "light.living_room_ceiling": "Living Room",
    "switch.decorative_lights": "Living Room",
    "cover.living_room_blinds": "Living Room",
    "fan.living_room_fan": "Living Room",
    "media_player.living_room_speaker": "Living Room",
    # Master Bedroom (4 devices)
    "light.master_bedroom_light": "Master Bedroom",
    "fan.master_bedroom_fan": "Master Bedroom",
    "media_player.bedroom_speaker": "Master Bedroom",
    # Kids Room (4 devices)
    "light.kids_room_light": "Kids Room",
    "light.kids_room_night_light": "Kids Room",
    "binary_sensor.kids_room_motion": "Kids Room",
    "media_player.kids_room_speaker": "Kids Room",
    # Office (3 devices)
    "light.office_desk_lamp": "Office",
    "switch.office_monitor": "Office",
    "media_player.office_speaker": "Office",
    # Garage (4 devices)
    "light.garage_light": "Garage",
    "cover.garage_door": "Garage",
    "switch.garage_heater": "Garage",
    "binary_sensor.garage_motion": "Garage",
    # Hallway (5 devices)
    "light.hallway_light": "Hallway",
    "lock.front_door": "Hallway",
    "lock.back_door": "Hallway",
    "cover.hallway_window": "Hallway",
    "binary_sensor.front_door": "Hallway",
    "binary_sensor.back_door": "Hallway",
}


def wait_for_ha():
    """Wait until HA is responding."""
    print("Waiting for Home Assistant...")
    for i in range(90):
        try:
            # /auth/providers works after onboarding, /api/onboarding works before
            for endpoint in ["/auth/providers", "/api/onboarding"]:
                r = requests.get(f"{HA_BASE_URL}{endpoint}", timeout=3)
                if r.status_code == 200:
                    print("  HA is up.")
                    return
        except (requests.ConnectionError, requests.Timeout):
            pass
        time.sleep(2)
    print("ERROR: HA did not start in time.")
    sys.exit(1)


def check_onboarding_needed():
    """Check if onboarding is still needed."""
    try:
        r = requests.get(f"{HA_BASE_URL}/api/onboarding", timeout=5)
        if r.status_code == 200:
            steps = r.json()
            # Returns list of steps with done status
            return any(not s.get("done", True) for s in steps)
    except Exception:
        pass
    return False


def do_onboarding():
    """Complete HA onboarding and return an access token."""
    print("Starting onboarding...")

    # Step 1: Create user
    print("  Creating user account...")
    r = requests.post(f"{HA_BASE_URL}/api/onboarding/users", json={
        "client_id": CLIENT_ID,
        "name": DEV_NAME,
        "username": DEV_USER,
        "password": DEV_PASSWORD,
        "language": DEV_LANGUAGE,
    }, timeout=10)
    if r.status_code != 200:
        print(f"  User creation failed ({r.status_code}): {r.text}")
        sys.exit(1)
    auth_code = r.json()["auth_code"]
    print("  User created.")

    # Step 2: Exchange auth code for tokens
    print("  Exchanging auth code for tokens...")
    r = requests.post(f"{HA_BASE_URL}/auth/token", data={
        "grant_type": "authorization_code",
        "code": auth_code,
        "client_id": CLIENT_ID,
    }, timeout=10)
    if r.status_code != 200:
        print(f"  Token exchange failed ({r.status_code}): {r.text}")
        sys.exit(1)
    tokens = r.json()
    access_token = tokens["access_token"]
    refresh_token = tokens.get("refresh_token", "")
    print("  Got access token.")

    headers = {"Authorization": f"Bearer {access_token}"}

    # Step 3: Complete core config
    print("  Setting core config...")
    r = requests.post(f"{HA_BASE_URL}/api/onboarding/core_config", headers=headers, timeout=10)
    if r.status_code != 200:
        print(f"  Core config step returned {r.status_code} (may be ok)")

    # Step 4: Set analytics (opt out)
    print("  Setting analytics...")
    r = requests.post(f"{HA_BASE_URL}/api/onboarding/analytics", headers=headers, timeout=10)
    if r.status_code != 200:
        print(f"  Analytics step returned {r.status_code} (may be ok)")

    # Step 5: Complete integration step
    print("  Completing integration step...")
    r = requests.post(f"{HA_BASE_URL}/api/onboarding/integration", json={
        "client_id": CLIENT_ID,
        "redirect_uri": f"{HA_BASE_URL}/",
    }, headers=headers, timeout=10)
    if r.status_code == 200:
        # This returns a new auth code - exchange it too
        new_code = r.json().get("auth_code")
        if new_code:
            r2 = requests.post(f"{HA_BASE_URL}/auth/token", data={
                "grant_type": "authorization_code",
                "code": new_code,
                "client_id": CLIENT_ID,
            }, timeout=10)
            if r2.status_code == 200:
                tokens = r2.json()
                access_token = tokens["access_token"]

    print("  Onboarding complete!")
    return access_token


def get_existing_token(access_token):
    """Try to get a long-lived access token via the WS API."""
    return asyncio.run(_create_long_lived_token(access_token))


async def _create_long_lived_token(access_token):
    """Create a long-lived access token via WebSocket."""
    ws_url = HA_BASE_URL.replace("http://", "ws://").replace("https://", "wss://") + "/api/websocket"
    msg_id = 1

    async with websockets.connect(ws_url) as ws:
        # Auth
        msg = json.loads(await ws.recv())
        await ws.send(json.dumps({"type": "auth", "access_token": access_token}))
        msg = json.loads(await ws.recv())
        if msg["type"] != "auth_ok":
            print(f"  WS auth failed: {msg}")
            return access_token  # Fall back to short-lived token

        # Create long-lived token
        await ws.send(json.dumps({
            "id": msg_id,
            "type": "auth/long_lived_access_token",
            "client_name": "Mission Control Dev",
            "lifespan": 365,
        }))
        msg_id += 1

        while True:
            resp = json.loads(await ws.recv())
            if resp.get("id") == msg_id - 1:
                if resp.get("success"):
                    print("  Created long-lived access token.")
                    return resp["result"]
                else:
                    print(f"  Failed to create long-lived token: {resp}")
                    return access_token

    return access_token


async def setup_areas_and_entities(token):
    """Create areas and assign entities via WS API."""
    ws_url = HA_BASE_URL.replace("http://", "ws://").replace("https://", "wss://") + "/api/websocket"
    msg_id = 1

    async def send(ws, payload):
        nonlocal msg_id
        payload["id"] = msg_id
        msg_id += 1
        await ws.send(json.dumps(payload))
        while True:
            resp = json.loads(await ws.recv())
            if resp.get("id") == payload["id"]:
                return resp

    async with websockets.connect(ws_url) as ws:
        msg = json.loads(await ws.recv())
        await ws.send(json.dumps({"type": "auth", "access_token": token}))
        msg = json.loads(await ws.recv())
        if msg["type"] != "auth_ok":
            print(f"  WS auth failed: {msg}")
            return

        # Get existing areas
        resp = await send(ws, {"type": "config/area_registry/list"})
        existing_areas = {a["name"]: a["area_id"] for a in resp["result"]}

        # Create missing areas
        area_ids = dict(existing_areas)
        for area_name in AREAS:
            if area_name not in area_ids:
                resp = await send(ws, {
                    "type": "config/area_registry/create",
                    "name": area_name,
                })
                if resp.get("success"):
                    area_ids[area_name] = resp["result"]["area_id"]
                    print(f"  Created area: {area_name}")

        # Get entity registry
        resp = await send(ws, {"type": "config/entity_registry/list"})
        entities = {e["entity_id"]: e for e in resp["result"]}

        # Assign entities to areas
        assigned = 0
        for entity_id, area_name in ENTITY_AREA_MAP.items():
            if entity_id not in entities or area_name not in area_ids:
                continue
            target_area_id = area_ids[area_name]
            if entities[entity_id].get("area_id") == target_area_id:
                continue
            resp = await send(ws, {
                "type": "config/entity_registry/update",
                "entity_id": entity_id,
                "area_id": target_area_id,
            })
            if resp.get("success"):
                assigned += 1

        print(f"  Assigned {assigned} entities to areas.")

        # Summary
        print("\n  --- Dev HA Devices ---")
        for area_name in AREAS:
            area_entities = [eid for eid, a in ENTITY_AREA_MAP.items()
                            if a == area_name and eid in entities]
            if area_entities:
                print(f"  {area_name}: {', '.join(sorted(area_entities))}")


def write_config(token):
    """Write config.json for mission-control."""
    if not CONFIG_OUT:
        return

    config = {}
    if os.path.exists(CONFIG_OUT):
        try:
            with open(CONFIG_OUT) as f:
                config = json.load(f)
        except Exception:
            pass

    config["ha_url"] = HA_BASE_URL
    config["ha_token"] = token
    # server_url needs to be reachable from the browser and Apple TV
    config["server_url"] = "http://localhost:8765"

    os.makedirs(os.path.dirname(CONFIG_OUT), exist_ok=True)
    with open(CONFIG_OUT, "w") as f:
        json.dump(config, f, indent=2)
    print(f"  Wrote config to {CONFIG_OUT}")


def login_existing():
    """Log in with existing dev account and return an access token."""
    print("  HA already onboarded. Logging in with dev account...")
    r = requests.post(f"{HA_BASE_URL}/auth/login_flow", json={
        "client_id": CLIENT_ID,
        "handler": ["homeassistant", None],
        "redirect_uri": f"{HA_BASE_URL}/",
    }, timeout=10)
    if r.status_code != 200:
        print(f"  Failed to start login flow ({r.status_code}): {r.text}")
        return None
    flow_id = r.json()["flow_id"]

    r = requests.post(f"{HA_BASE_URL}/auth/login_flow/{flow_id}", json={
        "client_id": CLIENT_ID,
        "username": DEV_USER,
        "password": DEV_PASSWORD,
    }, timeout=10)
    if r.status_code != 200:
        print(f"  Login failed ({r.status_code}): {r.text}")
        return None
    result = r.json()
    if result.get("type") != "create_entry":
        print(f"  Login failed: {result}")
        return None
    auth_code = result["result"]

    r = requests.post(f"{HA_BASE_URL}/auth/token", data={
        "grant_type": "authorization_code",
        "code": auth_code,
        "client_id": CLIENT_ID,
    }, timeout=10)
    if r.status_code != 200:
        print(f"  Token exchange failed ({r.status_code}): {r.text}")
        return None
    return r.json()["access_token"]


def main():
    wait_for_ha()

    # Check if config already has a token
    if CONFIG_OUT and os.path.exists(CONFIG_OUT):
        try:
            with open(CONFIG_OUT) as f:
                existing = json.load(f)
            if existing.get("ha_token"):
                # Verify token still works
                r = requests.get(f"{HA_BASE_URL}/api/", headers={
                    "Authorization": f"Bearer {existing['ha_token']}"
                }, timeout=5)
                if r.status_code == 200:
                    print("Existing token is valid. Running area setup only...")
                    asyncio.run(setup_areas_and_entities(existing["ha_token"]))
                    print("\nDev HA ready!")
                    return
        except Exception:
            pass

    if check_onboarding_needed():
        access_token = do_onboarding()
    else:
        access_token = login_existing()
        if not access_token:
            print("ERROR: Could not authenticate. Delete ha-config/.storage/ and restart.")
            sys.exit(1)

    # Create long-lived token
    print("Creating long-lived access token...")
    ll_token = get_existing_token(access_token)

    # Write config for mission-control
    print("Writing mission-control config...")
    write_config(ll_token)

    # Give HA a moment to fully register all template entities
    print("Waiting for entities to register...")
    time.sleep(5)

    # Setup areas and entity assignments
    print("Setting up areas and entities...")
    asyncio.run(setup_areas_and_entities(ll_token))

    print(f"\nDev HA ready!")
    print(f"  HA:              {HA_BASE_URL} (login: {DEV_USER}/{DEV_PASSWORD})")
    print(f"  Mission Control: http://localhost:8765")


if __name__ == "__main__":
    main()

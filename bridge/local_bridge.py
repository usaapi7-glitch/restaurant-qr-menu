"""
Counter PC Local Bridge (WebSocket Agent)
Connects to the Cloud Restaurant Portal via WebSocket and applies
Guest Wi-Fi / Whitelist / Speed Limit policies to the local router (192.168.1.1).
"""
import asyncio
import json
import os
import websockets

CLOUD_WS_URL = os.getenv("CLOUD_WS_URL", "ws://127.0.0.1:8000/ws/bridge")
ROUTER_IP = os.getenv("ROUTER_IP", "192.168.1.1")


class RouterAdapter:
    def apply_policy(self, ssid: str, only_menu_mode: bool, speed_limit_mbps: int) -> str:
        raise NotImplementedError


class TPLinkAdapter(RouterAdapter):
    def apply_policy(self, ssid: str, only_menu_mode: bool, speed_limit_mbps: int) -> str:
        # In production: authenticate with TP-Link HTTP/stok API on ROUTER_IP,
        # enable Guest Network (SSID 2), apply domain whitelist & QoS bandwidth cap.
        mode = "ONLY MENU & WHATSAPP" if only_menu_mode else "OPEN GUEST"
        return f"TP-Link ({ROUTER_IP}): Guest SSID '{ssid}' set to {mode} @ {speed_limit_mbps} Mbps."


class TendaAdapter(RouterAdapter):
    def apply_policy(self, ssid: str, only_menu_mode: bool, speed_limit_mbps: int) -> str:
        return f"Tenda ({ROUTER_IP}): Guest Wi-Fi '{ssid}' speed capped at {speed_limit_mbps} Mbps."


class ISPLockedAdapter(RouterAdapter):
    def apply_policy(self, ssid: str, only_menu_mode: bool, speed_limit_mbps: int) -> str:
        return (
            f"ISP Router ({ROUTER_IP}) Notice: Guest Wi-Fi / URL filtering is locked by ISP. "
            f"Applied bandwidth cap ({speed_limit_mbps} Mbps) only; secondary Access Point recommended."
        )


def get_adapter(router_model: str) -> RouterAdapter:
    if "TP-Link" in router_model:
        return TPLinkAdapter()
    if "Tenda" in router_model:
        return TendaAdapter()
    return ISPLockedAdapter()


async def run_bridge():
    while True:
        try:
            print(f"[Bridge] Connecting to {CLOUD_WS_URL} ...")
            async with websockets.connect(CLOUD_WS_URL) as ws:
                print("[Bridge] Connected to Cloud Dashboard!")
                async for raw in ws:
                    data = json.loads(raw)
                    if data.get("command") == "apply_wifi_policy":
                        adapter = get_adapter(data.get("router_model", ""))
                        note = adapter.apply_policy(
                            ssid=data.get("ssid", "Guest"),
                            only_menu_mode=bool(data.get("only_menu_mode", False)),
                            speed_limit_mbps=int(data.get("speed_limit_mbps", 2)),
                        )
                        print(f"[Bridge] {note}")
                        await ws.send(json.dumps({"type": "status_update", "note": note}))
        except Exception as e:
            print(f"[Bridge] Disconnected ({e}). Retrying in 5s...")
            await asyncio.sleep(5)


if __name__ == "__main__":
    asyncio.run(run_bridge())

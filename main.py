import os
import re
import json
import aiohttp
import traceback
from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse
import uvicorn

load_dotenv()

app = FastAPI()

VERIFY_TOKEN = os.getenv("WHATSAPP_WEBHOOK_VERIFICATION_TOKEN")
WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN")
WHATSAPP_PHONE_NUMBER_ID = os.getenv("WHATSAPP_PHONE_NUMBER_ID")
MANAGER_NUMBER = "923351021321"
RESTAURANT_BOT_URL = "https://restaurant-bot-production-a133.up.railway.app"

print(f"Token: {WHATSAPP_TOKEN[:20] if WHATSAPP_TOKEN else 'MISSING'}...")
print(f"Phone ID: {WHATSAPP_PHONE_NUMBER_ID}")


@app.get("/webhook")
async def verify_webhook(request: Request):
    params = dict(request.query_params)
    if params.get("hub.verify_token") == VERIFY_TOKEN:
        print("Webhook Verified!")
        return PlainTextResponse(params.get("hub.challenge", ""))
    return PlainTextResponse("Forbidden", status_code=403)


@app.post("/webhook")
async def handle_webhook(request: Request):
    data = await request.json()
    print(f"Incoming: {data}")
    try:
        entry = data["entry"][0]["changes"][0]["value"]

        if "messages" in entry:
            message = entry["messages"][0]
            sender = message.get("from", "")
            msg_type = message.get("type", "")

            # ── MANAGER PATH ──────────────────────────────────────
            if sender == MANAGER_NUMBER:

                # Button tap (list_reply ya button_reply)
                if msg_type == "interactive":
                    interactive = message.get("interactive", {})
                    itype = interactive.get("type", "")
                    reply_id = ""
                    if itype == "list_reply":
                        reply_id = interactive.get("list_reply", {}).get("id", "")
                    elif itype == "button_reply":
                        reply_id = interactive.get("button_reply", {}).get("id", "")

                    if reply_id.startswith("MGR_"):
                        m = re.match(r"^MGR_(\d{5})_(.+)$", reply_id)
                        if m:
                            order_id = m.group(1)
                            action = m.group(2).upper()
                            if action == "READY":
                                status = "READY"
                            elif action == "OUTFORDELIVERY":
                                status = "OUT FOR DELIVERY"
                            elif action.startswith("DELAYED"):
                                num = re.search(r"(\d+)", action)
                                status = f"DELAYED {num.group(1)}" if num else "DELAYED"
                            elif action == "CANCELLED":
                                status = "CANCELLED"
                            else:
                                status = action
                            async with aiohttp.ClientSession() as s:
                                await s.post(
                                    f"{RESTAURANT_BOT_URL}/manager-update",
                                    json={"order_id": order_id, "status": status},
                                    timeout=aiohttp.ClientTimeout(total=10),
                                )
                            print(f"Manager button: #{order_id} -> {status}")
                    return {"status": "ok"}

                # Typed command: ORDER#12345 READY
                if msg_type == "text":
                    text = message.get("text", {}).get("body", "").strip()
                    typed_match = re.search(r"ORDER#?\s*(\d{5})\s+(.+)", text, re.IGNORECASE)
                    if typed_match:
                        order_id = typed_match.group(1)
                        status = typed_match.group(2).strip().upper()
                        async with aiohttp.ClientSession() as s:
                            await s.post(
                                f"{RESTAURANT_BOT_URL}/manager-update",
                                json={"order_id": order_id, "status": status},
                                timeout=aiohttp.ClientTimeout(total=10),
                            )
                        print(f"Manager typed: #{order_id} -> {status}")
                    return {"status": "ok"}

                # Koi aur manager message — ignore
                return {"status": "ok"}

            # ── CUSTOMER PATH ─────────────────────────────────────
            print(f"Forwarding to restaurant bot from {sender}...")
            async with aiohttp.ClientSession() as fwd:
                await fwd.post(f"{RESTAURANT_BOT_URL}/webhook", json=data)

    except Exception as e:
        print(f"ERROR: {e}")
        print(traceback.format_exc())

    return {"status": "ok"}


if __name__ == "__main__":
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")
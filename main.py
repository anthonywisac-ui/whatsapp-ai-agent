"""
Wild Bites — WhatsApp AI Agent (Router)
========================================
Role:
  - Receives ALL Meta webhooks
  - Forwards customer messages to restaurant-bot /webhook
  - Handles manager replies (typed OR interactive button taps)
    and forwards them to restaurant-bot /manager-update

Deploy target: https://whatsapp-ai-agent-production-e5d7.up.railway.app
Local path:    C:\\Users\\DAIC\\whatsapp-ai-agent\\main.py
"""

import os
import re
import traceback
import aiohttp
from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse
import uvicorn

load_dotenv()

app = FastAPI()

# ── CONFIG ──────────────────────────────────────────────────────
VERIFY_TOKEN = os.getenv("WHATSAPP_WEBHOOK_VERIFICATION_TOKEN", "mysecrettoken123")
WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN")
WHATSAPP_PHONE_NUMBER_ID = os.getenv("WHATSAPP_PHONE_NUMBER_ID", "1100639706460130")

# Manager — hardcoded fallback kept for safety
MANAGER_NUMBER = os.getenv("MANAGER_NUMBER", "923351021321")

# Where the restaurant-bot lives
RESTAURANT_BOT_URL = os.getenv(
    "RESTAURANT_BOT_URL",
    "https://restaurant-bot-production-a133.up.railway.app"
)

print(f"Token: {WHATSAPP_TOKEN[:20] if WHATSAPP_TOKEN else 'MISSING'}...")
print(f"Phone ID: {WHATSAPP_PHONE_NUMBER_ID}")
print(f"Restaurant-bot URL: {RESTAURANT_BOT_URL}")
print(f"Manager: +{MANAGER_NUMBER}")


# ── WEBHOOK VERIFICATION ─────────────────────────────────────────
@app.get("/webhook")
async def verify_webhook(request: Request):
    params = dict(request.query_params)
    if params.get("hub.verify_token") == VERIFY_TOKEN:
        return PlainTextResponse(params.get("hub.challenge", ""))
    return PlainTextResponse("Forbidden", status_code=403)


# ── MAIN WEBHOOK HANDLER ─────────────────────────────────────────
@app.post("/webhook")
async def handle_webhook(request: Request):
    raw_body = await request.body()
    try:
        data = await request.json()
    except Exception:
        print("⚠️ Non-JSON webhook received")
        return {"status": "ok"}

    try:
        entry = data.get("entry", [{}])[0].get("changes", [{}])[0].get("value", {})

        # Ignore status updates (delivered/read) — only process actual messages
        if "messages" not in entry:
            return {"status": "ok"}

        message = entry["messages"][0]
        sender = message.get("from", "")
        msg_type = message.get("type", "")

        # ─── MANAGER PATH ─────────────────────────────────────────
        # Manager's replies never go to the restaurant-bot /webhook.
        # They are parsed here and forwarded to /manager-update.
        if sender == MANAGER_NUMBER:
            handled = await handle_manager_message(message, msg_type)
            if handled:
                return {"status": "ok"}
            # If not a recognized manager action, silently drop to avoid
            # the restaurant-bot treating manager number as a customer.
            print(f"ℹ️ Manager message ignored (not an order action): type={msg_type}")
            return {"status": "ok"}

        # ─── CUSTOMER PATH ────────────────────────────────────────
        # Forward the ENTIRE webhook body to restaurant-bot as-is.
        # Restaurant-bot parses it the same way Meta would.
        print(f"Forwarding to restaurant bot from {sender}...")
        await forward_to_restaurant_bot(raw_body, request.headers)

    except Exception as e:
        print(f"ERROR: {e}\n{traceback.format_exc()}")

    return {"status": "ok"}


# ── MANAGER HANDLER ──────────────────────────────────────────────
async def handle_manager_message(message, msg_type):
    """
    Return True if we handled it (don't forward).
    Return False if we didn't recognize it.
    """

    # Interactive (button tap / list selection) — NEW: button format
    if msg_type == "interactive":
        interactive = message.get("interactive", {})
        itype = interactive.get("type", "")
        reply_id = ""
        if itype == "list_reply":
            reply_id = interactive.get("list_reply", {}).get("id", "")
        elif itype == "button_reply":
            reply_id = interactive.get("button_reply", {}).get("id", "")

        if reply_id.startswith("MGR_"):
            return await forward_manager_button(reply_id)
        return False

    # Text message — typed command OR echo/confirmation bounce-back
    if msg_type == "text":
        text = message.get("text", {}).get("body", "").strip()

        # Ignore restaurant-bot's own confirmations that manager might "reply" to
        # (defensive: these start with ✅ Order)
        if text.startswith("✅ Order #"):
            print("ℹ️ Ignoring bot confirmation echo")
            return True

        # Typed command: "ORDER#12345 READY" / "ORDER#12345 DELAYED 15" etc.
        typed_match = re.search(r"ORDER#?\s*(\d{5})\s+(.+)", text, re.IGNORECASE)
        if typed_match:
            order_id = typed_match.group(1)
            status = typed_match.group(2).strip().upper()
            await post_manager_update(order_id, status)
            return True

        return False

    return False


async def forward_manager_button(reply_id):
    """Parse MGR_{order_id}_{ACTION} and POST to /manager-update."""
    m = re.match(r"^MGR_(\d{5})_(.+)$", reply_id)
    if not m:
        print(f"⚠️ Malformed manager button id: {reply_id}")
        return True  # still consumed

    order_id = m.group(1)
    action_raw = m.group(2).upper()

    # Map button id to status string restaurant-bot expects
    if action_raw == "READY":
        status = "READY"
    elif action_raw == "OUTFORDELIVERY":
        status = "OUT FOR DELIVERY"
    elif action_raw.startswith("DELAYED"):
        num = re.search(r"DELAYED\s*(\d+)", action_raw)
        status = f"DELAYED {num.group(1)}" if num else "DELAYED"
    elif action_raw == "CANCELLED":
        status = "CANCELLED"
    else:
        status = action_raw

    await post_manager_update(order_id, status)
    return True


async def post_manager_update(order_id, status):
    """POST to restaurant-bot /manager-update endpoint."""
    url = f"{RESTAURANT_BOT_URL}/manager-update"
    payload = {"order_id": str(order_id), "status": status}
    try:
        async with aiohttp.ClientSession() as s:
            async with s.post(
                url,
                json=payload,
                timeout=aiohttp.ClientTimeout(total=10),
            ) as r:
                body = await r.text()
                print(f"Manager update forwarded: #{order_id} → {status} | status={r.status}")
    except Exception as e:
        print(f"❌ Failed to forward manager update: {e}")


# ── FORWARD CUSTOMER WEBHOOK TO RESTAURANT-BOT ───────────────────
async def forward_to_restaurant_bot(raw_body, headers):
    """
    Forward the raw webhook body to restaurant-bot's /webhook.
    We pass raw bytes (not re-serialized JSON) so Meta's signature is preserved.
    """
    url = f"{RESTAURANT_BOT_URL}/webhook"
    fwd_headers = {"Content-Type": "application/json"}
    # Preserve Meta signature headers if Meta sets them
    for h in ("x-hub-signature", "x-hub-signature-256"):
        if h in headers:
            fwd_headers[h] = headers[h]

    try:
        async with aiohttp.ClientSession() as s:
            async with s.post(
                url,
                data=raw_body,
                headers=fwd_headers,
                timeout=aiohttp.ClientTimeout(total=15),
            ) as r:
                _ = await r.text()
                print(f"Restaurant bot response: {r.status}")
    except Exception as e:
        print(f"❌ Forward to restaurant-bot failed: {e}")


# ── HEALTH CHECK ─────────────────────────────────────────────────
@app.get("/")
async def root():
    return {
        "status": "ok",
        "service": "whatsapp-ai-agent",
        "restaurant_bot": RESTAURANT_BOT_URL,
    }


if __name__ == "__main__":
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run(app, host="0.0.0.0", port=port)
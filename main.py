import os
import aiohttp
import traceback
from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse, HTMLResponse
import uvicorn

load_dotenv()

app = FastAPI()

VERIFY_TOKEN = os.getenv("WHATSAPP_WEBHOOK_VERIFICATION_TOKEN")
WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN")
WHATSAPP_PHONE_NUMBER_ID = os.getenv("WHATSAPP_PHONE_NUMBER_ID")
RESTAURANT_BOT_URL = "https://restaurant-bot-production-a133.up.railway.app/webhook"
MANAGER_NUMBER = "923351021321"

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
    try:
        entry = data["entry"][0]["changes"][0]["value"]

        if "messages" in entry:
            message = entry["messages"][0]
            sender = message["from"]

            # MANAGER number — handle reply here, do NOT forward to restaurant bot
            if sender == MANAGER_NUMBER:
                msg_type = message.get("type", "")
                if msg_type == "text":
                    text = message["text"]["body"].strip()
                    print(f"MANAGER MSG: {text}")
                    await handle_manager_reply(text)
                return {"status": "ok"}

            # All other customers — forward to restaurant bot
            print(f"Forwarding to restaurant bot from {sender}...")
            async with aiohttp.ClientSession() as fwd:
                async with fwd.post(RESTAURANT_BOT_URL, json=data) as r:
                    print(f"Restaurant bot response: {r.status}")

    except Exception as e:
        print(f"ERROR: {e}")
        print(traceback.format_exc())

    return {"status": "ok"}

async def handle_manager_reply(text):
    import re
    # Extract order number: ORDER#12345 READY
    match = re.search(r'ORDER#?(\d{5})', text.upper())
    if not match:
        print(f"Not an order update: {text}")
        return

    order_id = match.group(1)
    text_upper = text.upper()

    # Find customer number from restaurant bot
    # We store this via Google Sheet or direct lookup
    # For now notify restaurant bot to handle the update
    await forward_manager_update_to_restaurant(order_id, text_upper)

async def forward_manager_update_to_restaurant(order_id, text_upper):
    """Forward manager update to restaurant bot for processing"""
    try:
        async with aiohttp.ClientSession() as s:
            await s.post(
                f"{RESTAURANT_BOT_URL.replace('/webhook', '')}/manager-update",
                json={"order_id": order_id, "status": text_upper}
            )
    except Exception as e:
        print(f"Manager update error: {e}")

@app.post("/twilio-call")
async def twilio_call(request: Request):
    twiml = """<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Say voice="alice">Welcome to Wild Bites Restaurant. Please send us a WhatsApp message to place your order. Thank you!</Say>
</Response>"""
    return HTMLResponse(content=twiml, media_type="application/xml")

@app.post("/twilio-sms")
async def twilio_sms(request: Request):
    form = await request.form()
    print(f"SMS: {form.get('Body')} from {form.get('From')}")
    return {"status": "ok"}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")
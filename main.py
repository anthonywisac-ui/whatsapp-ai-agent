import os
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
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
RESTAURANT_BOT_URL = "https://restaurant-bot-production-a133.up.railway.app/webhook"

print(f"🔑 Token: {WHATSAPP_TOKEN[:20] if WHATSAPP_TOKEN else 'MISSING!'}...")
print(f"📱 Phone ID: {WHATSAPP_PHONE_NUMBER_ID}")
print(f"🔐 Verify Token: {VERIFY_TOKEN}")

RESTAURANT_PHONE_ID = "1128408277019776"  # Restaurant bot number

# handle_webhook mein:
phone_id = data["entry"][0]["changes"][0]["value"]["metadata"]["phone_number_id"]

if phone_id == RESTAURANT_PHONE_ID:
    # Already restaurant bot ka message — ignore
    return {"status": "ok"}

# Forward to restaurant bot
async with aiohttp.ClientSession() as fwd:
    await fwd.post(RESTAURANT_BOT_URL, json=data)

@app.get("/webhook")
async def verify_webhook(request: Request):
    params = dict(request.query_params)
    if params.get("hub.verify_token") == VERIFY_TOKEN:
        print("✅ Webhook Verified!")
        return PlainTextResponse(params.get("hub.challenge", ""))
    return PlainTextResponse("Forbidden", status_code=403)

@app.post("/webhook")
async def handle_webhook(request: Request):
    data = await request.json()
    print(f"📩 Incoming: {data}")

    try:
        entry = data["entry"][0]["changes"][0]["value"]

        if "calls" in entry:
            call = entry["calls"][0]
            print(f"📞 Call from: {call['from']}")

        elif "messages" in entry:
            print(f"🍽️ Restaurant bot pe forward kar raha hoon...")
            async with aiohttp.ClientSession() as fwd:
                await fwd.post(RESTAURANT_BOT_URL, json=data)

    except Exception as e:
        print(f"❌ ERROR: {e}")
        print(traceback.format_exc())

    return {"status": "ok"}

@app.post("/twilio-call")
async def twilio_call(request: Request):
    from fastapi.responses import HTMLResponse
    print("📞 Twilio call aai!")
    twiml = """<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Say voice="alice" language="en-US">
        Hello! Welcome to Wild Bites Restaurant.
        To place an order, please send us a WhatsApp message.
        Thank you for calling!
    </Say>
</Response>"""
    return HTMLResponse(content=twiml, media_type="application/xml")

@app.post("/twilio-sms")
async def twilio_sms(request: Request):
    form = await request.form()
    body = form.get("Body", "")
    from_number = form.get("From", "")
    print(f"📱 Twilio SMS from {from_number}: {body}")
    return {"status": "ok"}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")
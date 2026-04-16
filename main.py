import os
import aiohttp
import traceback
from dotenv import load_dotenv
from fastapi import FastAPI, Request, Response
from fastapi.responses import PlainTextResponse
import uvicorn

# Pipecat imports (voice ke liye)
from pipecat.transports.whatsapp import WhatsAppTransport
from pipecat.services.groq import GroqLLMService
from pipecat.services.deepgram import DeepgramSTTService, DeepgramTTSService
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.task import PipelineTask
from pipecat.pipeline.runner import PipelineRunner

load_dotenv()

app = FastAPI()

# Environment variables
VERIFY_TOKEN = os.getenv("WHATSAPP_WEBHOOK_VERIFICATION_TOKEN")
WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN")
WHATSAPP_PHONE_NUMBER_ID = os.getenv("WHATSAPP_PHONE_NUMBER_ID")
APP_SECRET = os.getenv("WHATSAPP_APP_SECRET")
DEEPGRAM_API_KEY = os.getenv("DEEPGRAM_API_KEY")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

RESTAURANT_BOT_URL = "https://restaurant-bot-production-a133.up.railway.app/voice-webhook"

print(f"🔑 Token: {WHATSAPP_TOKEN[:20] if WHATSAPP_TOKEN else 'MISSING!'}...")
print(f"📱 Phone ID: {WHATSAPP_PHONE_NUMBER_ID}")
print(f"🔐 Verify Token: {VERIFY_TOKEN}")

# ==================== VOICE WEBHOOK (for calls) ====================
@app.get("/voice-webhook")
async def verify_voice_webhook(request: Request):
    mode = request.query_params.get("hub.mode")
    token = request.query_params.get("hub.verify_token")
    challenge = request.query_params.get("hub.challenge")
    
    if mode == "subscribe" and token == VERIFY_TOKEN:
        print("✅ Voice webhook verified!")
        return Response(content=challenge, status_code=200)
    return Response(status_code=403)

@app.post("/voice-webhook")
async def handle_voice_webhook(request: Request):
    try:
        data = await request.json()
        print(f"📞 Voice webhook data: {data}")
        
        if "entry" in data:
            for entry in data["entry"]:
                for change in entry.get("changes", []):
                    if change.get("field") == "calls":
                        call_data = change.get("value", {})
                        await handle_incoming_call(call_data)
        return Response(status_code=200)
    except Exception as e:
        print(f"❌ Voice webhook error: {e}")
        return Response(status_code=200)

async def handle_incoming_call(call_data: dict):
    call_id = call_data.get("calls", [{}])[0].get("id")
    from_number = call_data.get("contacts", [{}])[0].get("wa_id")
    print(f"📞 Incoming call from {from_number}, call_id: {call_id}")
    
    transport = WhatsAppTransport(
        whatsapp_token=WHATSAPP_TOKEN,
        phone_number_id=WHATSAPP_PHONE_NUMBER_ID,
        app_secret=APP_SECRET,
        call_id=call_id,
        webhook_endpoint="/voice-webhook"
    )
    
    stt = DeepgramSTTService(api_key=DEEPGRAM_API_KEY)
    llm = GroqLLMService(api_key=GROQ_API_KEY, model="llama3-8b-8192")
    tts = DeepgramTTSService(api_key=DEEPGRAM_API_KEY, voice="aura-asteria-en")
    
    pipeline = Pipeline([stt, llm, tts])
    task = PipelineTask(pipeline, transport=transport)
    runner = PipelineRunner()
    await runner.run(task)

# ==================== MESSAGE WEBHOOK (for texts) ====================
@app.get("/webhook")
async def verify_webhook(request: Request):
    params = dict(request.query_params)
    if params.get("hub.verify_token") == VERIFY_TOKEN:
        print("✅ Message webhook verified!")
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
            caller = call["from"]
            print(f"📞 Call from: {caller}")
        elif "messages" in entry:
            message = entry["messages"][0]
            sender = message["from"]
            msg_type = message.get("type", "")
            print(f"👤 Sender: {sender}, Type: {msg_type}")
            print(f"🍽️ Forwarding to restaurant bot...")
            async with aiohttp.ClientSession() as fwd:
                await fwd.post(RESTAURANT_BOT_URL, json=data)
    except Exception as e:
        print(f"❌ ERROR: {e}")
        print(traceback.format_exc())
    
    return {"status": "ok"}

# ==================== TWILIO (optional) ====================
@app.post("/twilio-call")
async def twilio_call(request: Request):
    from fastapi.responses import HTMLResponse
    twiml = """<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Say voice="alice" language="en-US">
        Hello! Welcome to Wild Restaurant.
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
import os
import aiohttp
from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse
import uvicorn
import traceback

load_dotenv()

app = FastAPI()

VERIFY_TOKEN = os.getenv("WHATSAPP_WEBHOOK_VERIFICATION_TOKEN")
WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN")
WHATSAPP_PHONE_NUMBER_ID = os.getenv("WHATSAPP_PHONE_NUMBER_ID")

print(f"🔑 Token: {WHATSAPP_TOKEN[:20] if WHATSAPP_TOKEN else 'MISSING!'}...")
print(f"📱 Phone ID: {WHATSAPP_PHONE_NUMBER_ID}")
print(f"🔐 Verify Token: {VERIFY_TOKEN}")

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

        # ── CALLS ──────────────────────────────
        if "calls" in entry:
            call = entry["calls"][0]
            caller = call["from"]
            call_id = call["id"]
            print(f"📞 Call from: {caller}")
            greeting = await get_ai_response_voice(
                "Customer ne call kiya. Short greeting do."
            )
            print(f"🤖 Voice Greeting: {greeting}")

        # ── MESSAGES ───────────────────────────
        elif "messages" in entry:
            message = entry["messages"][0]
            sender = message["from"]
            msg_type = message.get("type", "")
            print(f"👤 Sender: {sender}, Type: {msg_type}")

            if msg_type == "text":
                text = message["text"]["body"]
                print(f"💬 Message: {text}")
                reply = await get_ai_reply(text)
                print(f"🤖 AI Reply: {reply}")
                await send_whatsapp_message(sender, reply)
                print(f"✅ Reply bhej diya!")

    except Exception as e:
        print(f"❌ ERROR: {e}")
        print(traceback.format_exc())

    return {"status": "ok"}

# ── Voice AI Response ───────────────────────────────────────────────
async def get_ai_response_voice(prompt: str) -> str:
    headers = {
        "Authorization": f"Bearer {os.getenv('GROQ_API_KEY')}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": "llama-3.1-8b-instant",
        "messages": [
            {
                "role": "system",
                "content": "Voice assistant ho. Roman Urdu ya English mein jawab do. Max 1-2 sentences."
            },
            {"role": "user", "content": prompt}
        ]
    }
    async with aiohttp.ClientSession() as session:
        async with session.post(
            "https://api.groq.com/openai/v1/chat/completions",
            json=payload,
            headers=headers
        ) as resp:
            result = await resp.json()
            return result["choices"][0]["message"]["content"]

# ── Chat AI Response ────────────────────────────────────────────────
async def get_ai_reply(user_message: str) -> str:
    print("🧠 Groq Llama call kar raha hoon...")
    headers = {
        "Authorization": f"Bearer {os.getenv('GROQ_API_KEY')}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": "llama-3.1-8b-instant",
        "messages": [
            {
                "role": "system",
                "content": """You are a helpful business AI assistant.
Reply in the same language the user writes in.
If user writes in Roman Urdu, reply in Roman Urdu.
If user writes in English, reply in English.
If user writes in Arabic, reply in Arabic.
NEVER reply in Hindi or Devanagari script.
Keep answers short and friendly, max 3-4 lines."""
            },
            {
                "role": "user",
                "content": user_message
            }
        ]
    }
    async with aiohttp.ClientSession() as session:
        async with session.post(
            "https://api.groq.com/openai/v1/chat/completions",
            json=payload,
            headers=headers
        ) as resp:
            result = await resp.json()
            return result["choices"][0]["message"]["content"]

# ── Send WhatsApp Message ───────────────────────────────────────────
async def send_whatsapp_message(to: str, message: str):
    print(f"📤 Message bhej raha hoon to {to}...")
    url = f"https://graph.facebook.com/v18.0/{WHATSAPP_PHONE_NUMBER_ID}/messages"
    headers = {
        "Authorization": f"Bearer {WHATSAPP_TOKEN}",
        "Content-Type": "application/json"
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"body": message}
    }
    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=payload, headers=headers) as resp:
            result = await resp.json()
            print(f"📬 Result: {result}")

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")
import os
import asyncio
from fastapi import FastAPI, Request, Response
from dotenv import load_dotenv
from pipecat.transports.whatsapp import WhatsAppTransport
from pipecat.transports.smallwebrtc import SmallWebRTCTransport
from pipecat.services.groq import GroqLLMService
from pipecat.services.deepgram import DeepgramSTTService, DeepgramTTSService
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.task import PipelineTask
from pipecat.pipeline.runner import PipelineRunner
from pipecat.vad.silero import SileroVADAnalyzer
from pipecat.transports.smallwebrtc import TransportParams

load_dotenv()

app = FastAPI()

# WhatsApp credentials
WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN")
PHONE_NUMBER_ID = os.getenv("WHATSAPP_PHONE_NUMBER_ID")
APP_SECRET = os.getenv("WHATSAPP_APP_SECRET")
VERIFY_TOKEN = os.getenv("WHATSAPP_WEBHOOK_VERIFICATION_TOKEN")
DEEPGRAM_API_KEY = os.getenv("DEEPGRAM_API_KEY")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

@app.get("/voice-webhook")
async def verify_webhook(request: Request):
    """Webhook verification endpoint for Meta"""
    mode = request.query_params.get("hub.mode")
    token = request.query_params.get("hub.verify_token")
    challenge = request.query_params.get("hub.challenge")
    
    if mode == "subscribe" and token == VERIFY_TOKEN:
        print("Webhook verified successfully!")
        return Response(content=challenge, status_code=200)
    return Response(status_code=403)

@app.post("/voice-webhook")
async def handle_whatsapp_call(request: Request):
    """Handle incoming WhatsApp voice calls using Pipecat"""
    body = await request.body()
    signature = request.headers.get("x-hub-signature-256")
    
    try:
        data = await request.json()
        print(f"Received webhook data: {data}")
        
        # Check if this is a call event
        if "entry" in data:
            for entry in data["entry"]:
                for change in entry.get("changes", []):
                    if change.get("field") == "calls":
                        call_data = change.get("value", {})
                        await handle_incoming_call(call_data)
        
        return Response(status_code=200)
    except Exception as e:
        print(f"Error processing webhook: {e}")
        return Response(status_code=200)  # Always return 200 to acknowledge receipt

async def handle_incoming_call(call_data: dict):
    """Process incoming WhatsApp voice call with Pipecat pipeline"""
    call_id = call_data.get("calls", [{}])[0].get("id")
    from_number = call_data.get("contacts", [{}])[0].get("wa_id")
    
    print(f"📞 Incoming call from {from_number}, call_id: {call_id}")
    
    # Create WhatsApp transport
    transport = WhatsAppTransport(
        whatsapp_token=WHATSAPP_TOKEN,
        phone_number_id=PHONE_NUMBER_ID,
        app_secret=APP_SECRET,
        call_id=call_id,
        webhook_endpoint="/voice-webhook"
    )
    
    # Configure STT (Speech-to-Text) with Deepgram
    stt = DeepgramSTTService(api_key=DEEPGRAM_API_KEY)
    
    # Configure LLM with Groq for restaurant order processing
    llm = GroqLLMService(api_key=GROQ_API_KEY, model="llama3-8b-8192")
    
    # Configure TTS (Text-to-Speech) with Deepgram
    tts = DeepgramTTSService(api_key=DEEPGRAM_API_KEY, voice="aura-asteria-en")
    
    # Create pipeline
    pipeline = Pipeline([stt, llm, tts])
    task = PipelineTask(pipeline, transport=transport)
    
    # Run the voice agent
    runner = PipelineRunner()
    await runner.run(task)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)
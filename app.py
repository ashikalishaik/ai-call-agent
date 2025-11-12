"""AI Call Agent - Deepgram Implementation with Twilio WebSocket Audio Handling
Free alternative using Deepgram STT/TTS ($200 free credits)
"""
import os
import json
import base64
import asyncio
import logging
from datetime import datetime, time
from typing import Dict, List, Optional
import redis.asyncio as redis
from fastapi import FastAPI, WebSocket, Request, WebSocketDisconnect
from fastapi.responses import PlainTextResponse
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail
from twilio.rest import Client
from twilio.twiml.voice_response import VoiceResponse
import httpx

# Logging Configuration
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Environment Variables
DEEPGRAM_API_KEY = os.getenv("DEEPGRAM_API_KEY")
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
YOUR_NAME = os.getenv("YOUR_NAME", "AI Assistant")
USER_INFO = os.getenv("USER_INFO", "No user info provided")
NOTIFICATION_EMAIL = os.getenv("NOTIFICATION_EMAIL")
SENDGRID_API_KEY = os.getenv("SENDGRID_API_KEY")
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")

# FastAPI Setup
app = FastAPI()

# Redis client
redis_client: Optional[redis.Redis] = None

@app.on_event("startup")
async def startup_event():
    global redis_client
    try:
        redis_client = await redis.from_url(REDIS_URL, decode_responses=True)
        await redis_client.ping()
        logger.info("Connected to Redis successfully")
    except Exception as e:
        logger.error(f"Failed to connect to Redis: {e}")

@app.on_event("shutdown")
async def shutdown_event():
    if redis_client:
        await redis_client.close()

@app.post("/incoming-call")
async def incoming_call(request: Request):
    """Twilio webhook for incoming calls"""
    try:
        response = VoiceResponse()
        response.say(f"Hello, calling {YOUR_NAME}.")
        response.say("Please wait while I connect you to our AI assistant.")
        
        # Get host from request
        host = request.headers.get('host')
        
        # Connect to WebSocket for conversation
        response.connect(
            stream=dict(
                url=f"wss://{host}/media-stream",
                dtmf=False
            )
        )
        
        return PlainTextResponse(str(response), media_type="application/xml")
    except Exception as e:
        logger.error(f"Error in incoming call handler: {e}")
        response = VoiceResponse()
        response.say("Sorry, there was an error. Please try again later.")
        return PlainTextResponse(str(response), media_type="application/xml")

@app.websocket("/media-stream")
async def media_stream(websocket: WebSocket):
    """WebSocket handler for media streaming from Twilio"""
    await websocket.accept()
    conversation_history = []
    call_sid = None
    audio_buffer = bytearray()
    
    try:
        logger.info("WebSocket connection established")
        
        # Receive and process messages from Twilio
        while True:
            data = await websocket.receive_text()
            message = json.loads(data)
            
            # Extract call_sid from first message
            if not call_sid and "start" in message:
                call_sid = message["start"].get("callSid")
                logger.info(f"Call started: {call_sid}")
            
            # Process audio frames
            elif "media" in message and "payload" in message["media"]:
                audio_payload = message["media"]["payload"]
                audio_data = base64.b64decode(audio_payload)
                audio_buffer.extend(audio_data)
                
                # Once we have enough audio data, process it
                if len(audio_buffer) >= 8000:  # Process every ~1 second of audio
                    try:
                        # Send audio to Deepgram for STT
                        transcription = await speech_to_text(bytes(audio_buffer))
                        audio_buffer.clear()
                        
                        if transcription and len(transcription.strip()) > 0:
                            logger.info(f"User said: {transcription}")
                            conversation_history.append({
                                "role": "user",
                                "content": transcription,
                                "timestamp": datetime.now().isoformat()
                            })
                            
                            # Generate AI response
                            ai_response = await generate_ai_response(transcription, conversation_history)
                            logger.info(f"AI response: {ai_response}")
                            
                            conversation_history.append({
                                "role": "assistant",
                                "content": ai_response,
                                "timestamp": datetime.now().isoformat()
                            })
                            
                            # Send TTS response back
                            await send_tts_response(websocket, ai_response)
                            
                            # Save to Redis
                            if redis_client and call_sid:
                                await save_conversation_to_redis(call_sid, conversation_history)
                    except Exception as e:
                        logger.error(f"Error processing audio: {e}")
    
    except WebSocketDisconnect:
        logger.info("WebSocket disconnected by client")
    except Exception as e:
        logger.error(f"Error in media stream: {e}")
    
    finally:
        try:
            if call_sid and conversation_history:
                if redis_client:
                    await save_conversation_to_redis(call_sid, conversation_history)
                    logger.info(f"Final conversation saved for call {call_sid}")
                
                if NOTIFICATION_EMAIL and SENDGRID_API_KEY:
                    await send_call_notification(call_sid, conversation_history)
        except Exception as cleanup_error:
            logger.error(f"Error in cleanup: {cleanup_error}")

async def speech_to_text(audio_data: bytes) -> str:
    """Convert audio to text using Deepgram"""
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                "https://api.deepgram.com/v1/listen",
                headers={"Authorization": f"Token {DEEPGRAM_API_KEY}"},
                content=audio_data,
                params={
                    "encoding": "mulaw",
                    "sample_rate": "8000",
                    "model": "nova-2"
                }
            )
            
            if response.status_code == 200:
                result = response.json()
                if result.get("results") and result["results"].get("channels"):
                    transcript = result["results"]["channels"][0]["alternatives"][0]["transcript"]
                    return transcript.strip()
        return ""
    except Exception as e:
        logger.error(f"Error in STT: {e}")
        return ""

async def generate_ai_response(user_input: str, conversation_history: List[dict] = None) -> str:
    """Generate AI response using free Hugging Face LLM with user context"""
    try:
        HF_API_KEY = os.getenv("HF_API_KEY", "")
        
        if not HF_API_KEY or HF_API_KEY.startswith("hf_placeholder"):
            # Fallback to rule-based if no valid HF key
            user_input_lower = user_input.lower()
            if any(word in user_input_lower for word in ["hello", "hi", "hey"]):
                return f"Hello! I'm {YOUR_NAME}'s AI assistant. How can I help you today?"
            return f"I understood you said: {user_input}. Can you tell me more?"
        
        # Build prompt with user context and conversation history
        system_prompt = f"""You are a helpful AI assistant for {YOUR_NAME}. 
User Information: {USER_INFO}
Respond naturally and concisely in 1-2 sentences. Be conversational and friendly."""
        
        # Add recent conversation context
        context = ""
        if conversation_history:
            recent = conversation_history[-4:]  # Last 4 messages
            for msg in recent:
                context += f"{msg['role'].upper()}: {msg['content']}\n"
        
        prompt = f"{system_prompt}\n\nRecent conversation:\n{context}\nUser: {user_input}\nAssistant:"
        
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(
                "https://api-inference.huggingface.co/models/meta-llama/Llama-2-7b-chat-hf",
                headers={"Authorization": f"Bearer {HF_API_KEY}"},
                json={
                    "inputs": prompt,
                    "parameters": {"max_new_tokens": 100, "temperature": 0.7, "top_p": 0.95}
                }
            )
            
            if response.status_code == 200:
                result = response.json()
                if result and isinstance(result, list) and len(result) > 0:
                    generated_text = result[0].get("generated_text", "")
                    if "Assistant:" in generated_text:
                        ai_response = generated_text.split("Assistant:")[-1].strip()
                    else:
                        ai_response = generated_text.strip()
                    
                    if ai_response and len(ai_response) > 3:
                        return ai_response[:500]
        
        return f"How can I assist you with: {user_input}?"
    except Exception as e:
        logger.error(f"Error generating LLM response: {e}")
        return "I'm here to help. Could you please repeat that?"

async def send_tts_response(websocket: WebSocket, text: str):
    """Send TTS response back through WebSocket"""
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                "https://api.deepgram.com/v1/speak",
                headers={"Authorization": f"Token {DEEPGRAM_API_KEY}"},
                json={"text": text},
                params={"model": "aura-asteria-en", "encoding": "mulaw", "sample_rate": "8000"}
            )
            
            if response.status_code == 200:
                audio_data = response.content
                # Send audio frames to Twilio
                frame_size = 320  # 20ms frames at 8000 Hz
                for i in range(0, len(audio_data), frame_size):
                    frame = audio_data[i:i+frame_size]
                    try:
                        await websocket.send_text(json.dumps({
                            "event": "media",
                            "media": {"payload": base64.b64encode(frame).decode()}
                        }))
                        await asyncio.sleep(0.02)  # 20ms delay
                    except Exception as e:
                        logger.error(f"Error sending audio frame: {e}")
                        break
    except Exception as e:
        logger.error(f"Error in TTS: {e}")

async def save_conversation_to_redis(call_sid: str, conversation: List[dict]):
    """Save conversation to Redis with 24-hour TTL"""
    if not redis_client:
        return
    
    try:
        key = f"call:{call_sid}"
        await redis_client.setex(
            key,
            86400,  # 24 hours
            json.dumps(conversation)
        )
        logger.info(f"Saved conversation to Redis: {key}")
    except Exception as e:
        logger.error(f"Error saving to Redis: {e}")

async def send_call_notification(call_sid: str, conversation: List[dict]):
    """Send email notification with call summary"""
    if not SENDGRID_API_KEY or not NOTIFICATION_EMAIL:
        return
    
    try:
        summary = "\n".join([f"- {msg['role'].upper()}: {msg['content']}" for msg in conversation])
        message = Mail(
            from_email="noreply@callai.com",
            to_emails=NOTIFICATION_EMAIL,
            subject=f"Call Summary - {call_sid}",
            plain_text_content=f"""Call Conversation:\n\n{summary}\n\nCall ID: {call_sid}"""
        )
        
        sg = SendGridAPIClient(SENDGRID_API_KEY)
        response = sg.send(message)
        logger.info(f"Email sent for call {call_sid}: {response.status_code}")
    except Exception as e:
        logger.error(f"Error sending email: {e}")

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    redis_status = "disconnected"
    if redis_client:
        try:
            await redis_client.ping()
            redis_status = "connected"
        except:
            pass
    
    return {
        "status": "healthy",
        "redis": redis_status,
        "timestamp": datetime.now().isoformat()
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

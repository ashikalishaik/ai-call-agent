import os
import json
import base64
import asyncio
import websockets
import redis.asyncio as redis
from fastapi import FastAPI, WebSocket, Request
from fastapi.responses import HTMLResponse, PlainTextResponse
from twilio.twiml.voice_response import VoiceResponse, Connect
import logging
from datetime import datetime, timedelta, time
from typing import Dict, List, Optional
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail
from apscheduler.schedulers.asyncio import AsyncIOScheduler

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()

# Configuration
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
YOUR_NAME = os.getenv("YOUR_NAME", "the user")
USER_INFO = os.getenv("USER_INFO", "")
NOTIFICATION_EMAIL = os.getenv("NOTIFICATION_EMAIL", "")
SENDGRID_API_KEY = os.getenv("SENDGRID_API_KEY", "")
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")

# Initialize Redis client
redis_client = None

# Store call summaries (in-memory for quick access, persisted to Redis)
call_summaries: Dict[str, Dict] = {}

# System message for the AI agent
SYSTEM_MESSAGE = f"""
You are an intelligent voice assistant answering calls on behalf of {YOUR_NAME}.

Your responsibilities:
1. Greet the caller warmly and ask how you can help
2. Listen to their reason for calling
3. Provide helpful information based on what you know about {YOUR_NAME}
4. Be professional, friendly, and concise
5. If you don't know something, politely say so and offer to take a message
6. If they want to schedule an appointment, ask for their preferred date and time

Information about {YOUR_NAME}:
{USER_INFO}

Important: Keep responses brief and natural, as this is a phone conversation.
"""

# Initialize scheduler
scheduler = AsyncIOScheduler()

@app.on_event("startup")
async def startup_event():
    """Initialize Redis connection on startup"""
    global redis_client
    try:
        redis_client = await redis.from_url(REDIS_URL, encoding="utf-8", decode_responses=True)
        await redis_client.ping()
        logger.info("Connected to Redis successfully")
    except Exception as e:
        logger.error(f"Failed to connect to Redis: {e}")
        redis_client = None
    
    # Start the scheduler
    scheduler.start()
    logger.info("Scheduler started")

@app.on_event("shutdown")
async def shutdown_event():
    """Close Redis connection on shutdown"""
    if redis_client:
        await redis_client.close()
        logger.info("Redis connection closed")
    
    scheduler.shutdown()
    logger.info("Scheduler stopped")

# Schedule end-of-day cleanup at 11:59 PM
@scheduler.scheduled_job('cron', hour=23, minute=59)
async def end_of_day_cleanup():
    """Clear conversation cache at end of day and send daily wrap-up"""
    try:
        logger.info("Starting end-of-day cleanup...")
        
        # Send daily wrap-up email before clearing
        if NOTIFICATION_EMAIL and SENDGRID_API_KEY:
            await send_daily_wrapup()
        
        # Clear Redis cache for conversations (keep summaries)
        if redis_client:
            # Get all conversation keys
            pattern = "conversation:*"
            cursor = 0
            deleted_count = 0
            
            while True:
                cursor, keys = await redis_client.scan(cursor=cursor, match=pattern, count=100)
                if keys:
                    await redis_client.delete(*keys)
                    deleted_count += len(keys)
                
                if cursor == 0:
                    break
            
            logger.info(f"End of day cleanup: Deleted {deleted_count} conversation caches")
        
    except Exception as e:
        logger.error(f"Error in end-of-day cleanup: {e}")

# Redis Helper Functions
async def save_conversation_to_redis(call_sid: str, conversation: List[Dict]):
    """Save conversation to Redis cache"""
    if not redis_client:
        return
    
    try:
        key = f"conversation:{call_sid}"
        value = json.dumps(conversation)
        # Set expiration to 24 hours
        await redis_client.setex(key, 86400, value)
        logger.info(f"Saved conversation to Redis: {call_sid}")
    except Exception as e:
        logger.error(f"Error saving to Redis: {e}")

async def get_conversation_from_redis(call_sid: str) -> List[Dict]:
    """Retrieve conversation from Redis cache"""
    if not redis_client:
        return []
    
    try:
        key = f"conversation:{call_sid}"
        value = await redis_client.get(key)
        if value:
            return json.loads(value)
    except Exception as e:
        logger.error(f"Error retrieving from Redis: {e}")
    
    return []

async def get_all_conversations_today() -> Dict[str, List[Dict]]:
    """Get all conversations from Redis for today"""
    if not redis_client:
        return {}
    
    try:
        pattern = "conversation:*"
        conversations = {}
        cursor = 0
        
        while True:
            cursor, keys = await redis_client.scan(cursor=cursor, match=pattern, count=100)
            for key in keys:
                value = await redis_client.get(key)
                if value:
                    call_sid = key.replace("conversation:", "")
                    conversations[call_sid] = json.loads(value)
            
            if cursor == 0:
                break
        
        return conversations
    except Exception as e:
        logger.error(f"Error getting all conversations: {e}")
        return {}

@app.get("/")
async def root():
    return {"status": "AI Call Agent is running", "version": "2.0.0", "redis_connected": redis_client is not None}

@app.post("/incoming-call")
async def handle_incoming_call(request: Request):
    """
    Twilio webhook for incoming calls.
    Returns TwiML to connect the call to a WebSocket.
    """
    logger.info("Incoming call received")
    
    response = VoiceResponse()
    
    # Get the WebSocket URL
    host = request.headers.get("host")
    ws_url = f"wss://{host}/media-stream"
    
    connect = Connect()
    connect.stream(url=ws_url)
    response.append(connect)
    
    return PlainTextResponse(str(response), media_type="text/xml")

@app.websocket("/media-stream")
async def handle_media_stream(websocket: WebSocket):
    """
    Handle Twilio Media Stream WebSocket connection.
    Connects to OpenAI Realtime API and facilitates two-way audio streaming.
    """
    await websocket.accept()
    logger.info("Twilio Media Stream connected")
    
    stream_sid = None
    call_sid = None
    conversation_history = []
    
    # Connect to OpenAI Realtime API
    openai_ws_url = "wss://api.openai.com/v1/realtime?model=gpt-4o-realtime-preview-2024-10-01"
    
    try:
        async with websockets.connect(
            openai_ws_url,
            extra_headers={
                "Authorization": f"Bearer {OPENAI_API_KEY}",
                "OpenAI-Beta": "realtime=v1"
            }
        ) as openai_ws:
            logger.info("Connected to OpenAI Realtime API")
            
            # Configure the OpenAI session
            session_update = {
                "type": "session.update",
                "session": {
                    "turn_detection": {"type": "server_vad"},
                    "input_audio_format": "g711_ulaw",
                    "output_audio_format": "g711_ulaw",
                    "voice": "alloy",
                    "instructions": SYSTEM_MESSAGE,
                    "modalities": ["text", "audio"],
                    "temperature": 0.8,
                }
            }
            await openai_ws.send(json.dumps(session_update))
            logger.info("OpenAI session configured")
            
            async def receive_from_twilio():
                """Receive audio from Twilio and send to OpenAI"""
                nonlocal stream_sid, call_sid
                try:
                    async for message in websocket.iter_text():
                        data = json.loads(message)
                        
                        if data["event"] == "start":
                            stream_sid = data["start"]["streamSid"]
                            call_sid = data["start"]["callSid"]
                            logger.info(f"Stream started: {stream_sid}, call_sid: {call_sid}")
                        
                        elif data["event"] == "media":
                            # Forward audio from Twilio to OpenAI
                            audio_append = {
                                "type": "input_audio_buffer.append",
                                "audio": data["media"]["payload"]
                            }
                            await openai_ws.send(json.dumps(audio_append))
                        
                        elif data["event"] == "stop":
                            logger.info("Stream stopped")
                            break
                except Exception as e:
                    logger.error(f"Error in receive_from_twilio: {e}")
            
            async def receive_from_openai():
                """Receive responses from OpenAI and send to Twilio"""
                nonlocal conversation_history
                try:
                    async for message in openai_ws:
                        response = json.loads(message)
                        
                        # LOG ALL EVENT TYPES FOR DEBUGGING
                        event_type = response.get("type")
                        logger.info(f"OpenAI Event: {event_type}")
                        if event_type not in ["response.audio.delta", "input_audio_buffer.speech_started", "input_audio_buffer.speech_stopped"]:
                            logger.info(f"Full event data: {json.dumps(response, indent=2)}")
                        
                        # Log conversation for summary
                        if response.get("type") == "conversation.item.created":
                            item = response.get("item", {})
                            if item.get("role") == "user":
                                content = item.get("content", [])
                                text = content[0].get("transcript", "") if content else ""
                                if text:
                                    conversation_history.append({"role": "user", "content": text})
                                    # Save to Redis
                                    if call_sid:
                                        await save_conversation_to_redis(call_sid, conversation_history)
                            elif item.get("role") == "assistant":
                                content = item.get("content", [])
                                text = content[0].get("transcript", "") if content else ""
                                if text:
                                    conversation_history.append({"role": "assistant", "content": text})
                                    if call_sid:
                                        await save_conversation_to_redis(call_sid, conversation_history)
                        
                        # Capture user transcripts from input audio transcription
                        if event_type == "conversation.item.input_audio_transcription.completed":
                            transcript = response.get("transcript", "")
                            if transcript:
                                conversation_history.append({"role": "user", "content": transcript})
                                if call_sid:
                                    await save_conversation_to_redis(call_sid, conversation_history)
                                logger.info(f"Captured user transcript: {transcript}")
                        
                        # Capture assistant responses from response.done event
                        if event_type == "response.done":
                            response_data = response.get("response", {})
                            output = response_data.get("output", [])
                            for output_item in output:
                                if output_item.get("type") == "message":
                                    content_items = output_item.get("content", [])
                                    for content_item in content_items:
                                        if content_item.get("type") == "text":
                                            text = content_item.get("text", "")
                                            if text:
                                                conversation_history.append({"role": "assistant", "content": text})
                                                if call_sid:
                                                    await save_conversation_to_redis(call_sid, conversation_history)
                                                logger.info(f"Captured assistant response: {text}")
                        
                        # Send audio back to Twilio
                        if response.get("type") == "response.audio.delta":
                            if stream_sid:
                                audio_delta = {
                                    "event": "media",
                                    "streamSid": stream_sid,
                                    "media": {
                                        "payload": response["delta"]
                                    }
                                }
                                await websocket.send_json(audio_delta)
                                logger.info("Sent audio to Twilio")
                        
                except Exception as e:
                    logger.error(f"Error in receive_from_openai: {e}")
            
            # Run both directions concurrently
                    try:
            await asyncio.gather(
                receive_from_twilio(),
                receive_from_openai()
            )
    
        except asyncio.CancelledError:
            # Task was cancelled - this is expected during shutdown
            logger.warning("Tasks cancelled - cleaning up gracefully")
            raise  # Re-raise to ensure proper cleanup
        except websockets.exceptions.ConnectionClosed as e:
            # WebSocket connection was closed unexpectedly
            logger.error(f"WebSocket connection closed unexpectedly: {e}")
        except asyncio.TimeoutError:
            # Connection timed out
            logger.error("Connection timeout - API may be unresponsive")
        except ConnectionError as e:
            # Generic connection error
            logger.error(f"Connection error: {e}")
        except Exception as e:
            # Catch-all for any other unexpected errors
            logger.error(f"Unexpected error in WebSocket handler: {e}")    
    finally:
        # This finally block will ALWAYS execute when the WebSocket handler exits
        logger.info(f"Finally block: WebSocket handler cleanup for call_sid={call_sid}")
        
        # Try to retrieve conversation from Redis if local history is empty
        if call_sid and not conversation_history:
            conversation_history = await get_conversation_from_redis(call_sid)
            logger.info(f"Retrieved conversation from Redis: {len(conversation_history)} messages")
        
        # Generate and store call summary
        logger.info(f"Finally block: call_sid={call_sid}, conversation_history_length={len(conversation_history)}")
        
        if call_sid and conversation_history:
            try:
                # Check for appointment conflicts
                overlap_check = await check_appointment_overlap(call_sid, conversation_history)
                
                summary = await generate_call_summary(conversation_history, overlap_check)
                call_summaries[call_sid] = {
                    "timestamp": datetime.now().isoformat(),
                    "conversation": conversation_history,
                    "summary": summary,
                    "appointment_conflict": overlap_check.get("has_conflict", False)
                }
                logger.info(f"Call summary generated for {call_sid}")
                
                # Send notification if configured
                if NOTIFICATION_EMAIL and SENDGRID_API_KEY:
                    await send_notification(call_sid, summary, overlap_check)
                
            except Exception as e:
                logger.error(f"Error in finally block cleanup: {e}")
        else:
            logger.warning(f"No conversation to summarize. call_sid={call_sid}, history_length={len(conversation_history)}")

async def extract_appointment_details(conversation: List[Dict]) -> Optional[Dict]:
    """Use GPT to extract appointment time from conversation"""
    from openai import AsyncOpenAI
    client = AsyncOpenAI(api_key=OPENAI_API_KEY)
    
    convo_text = "\n".join([f"{msg['role']}: {msg['content']}" for msg in conversation])
    
    prompt = f"""
    Extract appointment details from this conversation:
    {convo_text}
    
    Return JSON with: {{"has_appointment": true/false, "date": "YYYY-MM-DD", "time": "HH:MM", "duration_minutes": int}}
    If no appointment mentioned, return {{"has_appointment": false}}
    Today's date is {datetime.now().strftime('%Y-%m-%d')}
    """
    
    try:
        response = await client.chat.completions.create(
            model="gpt-4",
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            max_tokens=200
        )
        
        result = json.loads(response.choices[0].message.content)
        if result.get("has_appointment"):
            return result
    except Exception as e:
        logger.error(f"Error extracting appointment: {e}")
    
    return None

def appointments_overlap(appt1: Dict, appt2: Dict) -> bool:
    """Check if two appointments overlap"""
    try:
        time1 = datetime.fromisoformat(f"{appt1['date']} {appt1['time']}")
        time2 = datetime.fromisoformat(f"{appt2['date']} {appt2['time']}")
        
        end1 = time1 + timedelta(minutes=appt1.get('duration_minutes', 30))
        end2 = time2 + timedelta(minutes=appt2.get('duration_minutes', 30))
        
        return time1 < end2 and time2 < end1
    except Exception as e:
        logger.error(f"Error checking overlap: {e}")
        return False

async def check_appointment_overlap(call_sid: str, conversation: List[Dict]) -> Dict:
    """Check if new appointment conflicts with existing ones"""
    # Extract appointment time from current conversation
    new_appointment = await extract_appointment_details(conversation)
    
    if not new_appointment or not new_appointment.get("has_appointment"):
        return {"has_conflict": False}
    
    logger.info(f"New appointment found: {new_appointment}")
    
    # Check against all conversations from today (in Redis)
    all_conversations = await get_all_conversations_today()
    
    for cached_call_sid, cached_conversation in all_conversations.items():
        if cached_call_sid == call_sid:
            continue  # Skip current call
        
        cached_appointment = await extract_appointment_details(cached_conversation)
        
        if cached_appointment and cached_appointment.get("has_appointment"):
            if appointments_overlap(new_appointment, cached_appointment):
                logger.warning(f"Appointment conflict detected! New: {new_appointment}, Existing: {cached_appointment}")
                return {
                    "has_conflict": True,
                    "conflicting_call": cached_call_sid,
                    "conflicting_time": f"{cached_appointment['date']} {cached_appointment['time']}",
                    "new_appointment": new_appointment
                }
    
    logger.info("No appointment conflicts found")
    return {"has_conflict": False, "new_appointment": new_appointment}

async def generate_call_summary(conversation: List[Dict], overlap_check: Dict = None) -> str:
    """
    Generate a summary of the call using OpenAI.
    """
    from openai import AsyncOpenAI
    client = AsyncOpenAI(api_key=OPENAI_API_KEY)
    
    # Create conversation text
    convo_text = "\n".join([
        f"{msg['role'].upper()}: {msg['content']}"
        for msg in conversation
    ])
    
    conflict_note = ""
    if overlap_check and overlap_check.get("has_conflict"):
        conflict_note = f"\n\n**IMPORTANT: APPOINTMENT CONFLICT DETECTED**\nThe requested time conflicts with an existing appointment at {overlap_check.get('conflicting_time')}"
    
    prompt = f"""
    Summarize this phone call conversation:
    
    {convo_text}
    
    Provide a concise summary including:
    - Who called
    - Reason for calling
    - Key points discussed
    - Any action items or follow-ups needed
    - If an appointment was scheduled, include the date and time
    {conflict_note}
    """
    
    try:
        response = await client.chat.completions.create(
            model="gpt-4",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=300
        )
        return response.choices[0].message.content
    except Exception as e:
        logger.error(f"Error generating summary: {e}")
        return "Summary generation failed"

async def send_notification(call_sid: str, summary: str, overlap_check: Dict = None):
    """
    Send email notification with call summary.
    """
    logger.info(f"send_notification called: call_sid={call_sid}")
    
    if not SENDGRID_API_KEY or not NOTIFICATION_EMAIL:
        logger.warning("SendGrid API key or notification email not configured")
        return
    
    try:
        # Add conflict warning if present
        conflict_html = ""
        if overlap_check and overlap_check.get("has_conflict"):
            conflict_html = f"""
            <div style="background-color: #fff3cd; border: 1px solid #ffc107; padding: 15px; margin: 20px 0; border-radius: 5px;">
                <h3 style="color: #856404; margin-top: 0;">⚠️ Appointment Conflict Warning</h3>
                <p style="color: #856404; margin-bottom: 0;">The requested appointment time conflicts with an existing appointment at {overlap_check.get('conflicting_time')}</p>
            </div>
            """
        
        # Format the email content
        subject = f"New Call Summary - {datetime.now().strftime('%I:%M %p')}"
        if overlap_check and overlap_check.get("has_conflict"):
            subject = f"⚠️ CONFLICT - New Call Summary - {datetime.now().strftime('%I:%M %p')}"
        
        html_content = f"""
        <html>
        <head></head>
        <body style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
            <h2>Call Summary</h2>
            <p><strong>Call ID:</strong> {call_sid}</p>
            <p><strong>Time:</strong> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
            <hr>
            {conflict_html}
            <h3>Summary:</h3>
            <p style="white-space: pre-wrap;">{summary}</p>
            <hr>
            <p style="color: gray; font-size: 12px;">This is an automated notification from your AI Call Agent.</p>
        </body>
        </html>
        """
        
        # Create the email message
        message = Mail(
            from_email='noreply@yourcallagent.com',
            to_emails=NOTIFICATION_EMAIL,
            subject=subject,
            html_content=html_content
        )
        
        # Send the email
        sg = SendGridAPIClient(SENDGRID_API_KEY)
        response = sg.send(message)
        
        logger.info(f"Email notification sent for call {call_sid}. Status: {response.status_code}")
        
    except Exception as e:
        logger.error(f"Error sending email notification: {e}")

async def send_daily_wrapup():
    """Send daily summary of all calls"""
    if not call_summaries:
        logger.info("No calls today, skipping daily wrap-up")
        return
    
    # Get today's summaries
    today = datetime.now().date()
    today_summaries = {
        call_sid: data for call_sid, data in call_summaries.items()
        if datetime.fromisoformat(data['timestamp']).date() == today
    }
    
    if not today_summaries:
        logger.info("No calls for today, skipping wrap-up")
        return
    
    try:
        # Create email content
        html_content = f"""
        <html>
        <body style="font-family: Arial, sans-serif; max-width: 800px; margin: 0 auto;">
            <h2>Daily Call Wrap-up - {today.strftime('%B %d, %Y')}</h2>
            <p><strong>Total Calls:</strong> {len(today_summaries)}</p>
            <hr>
        """
        
        for call_sid, data in today_summaries.items():
            conflict_badge = ""
            if data.get('appointment_conflict'):
                conflict_badge = '<span style="background-color: #ffc107; color: #856404; padding: 5px 10px; border-radius: 3px; font-size: 12px;">⚠️ CONFLICT</span>'
            
            html_content += f"""
            <div style="margin-bottom: 30px; padding: 20px; background-color: #f8f9fa; border-radius: 5px;">
                <h3>Call: {call_sid} {conflict_badge}</h3>
                <p><strong>Time:</strong> {data['timestamp']}</p>
                <p><strong>Summary:</strong></p>
                <p style="white-space: pre-wrap;">{data['summary']}</p>
            </div>
            <hr>
            """
        
        html_content += """
        </body>
        </html>
        """
        
        message = Mail(
            from_email='noreply@yourcallagent.com',
            to_emails=NOTIFICATION_EMAIL,
            subject=f"Daily Call Wrap-up - {today.strftime('%B %d, %Y')}",
            html_content=html_content
        )
        
        sg = SendGridAPIClient(SENDGRID_API_KEY)
        response = sg.send(message)
        logger.info(f"Daily wrap-up email sent. Status: {response.status_code}")
        
    except Exception as e:
        logger.error(f"Error sending daily wrap-up: {e}")

@app.get("/summaries")
async def get_summaries():
    """
    Retrieve all call summaries.
    """
    return {"summaries": call_summaries, "redis_connected": redis_client is not None}

@app.get("/summaries/{call_sid}")
async def get_summary(call_sid: str):
    """
    Retrieve a specific call summary.
    """
    if call_sid in call_summaries:
        return call_summaries[call_sid]
    return {"error": "Call not found"}

@app.get("/health")
async def health_check():
    """
    Health check endpoint.
    """
    redis_status = "connected" if redis_client else "disconnected"
    try:
        if redis_client:
            await redis_client.ping()
            redis_status = "connected"
    except:
        redis_status = "error"
    
    return {
        "status": "healthy",
        "redis": redis_status,
        "total_summaries": len(call_summaries)
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

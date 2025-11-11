import os
import json
import base64
import asyncio
import websockets
from fastapi import FastAPI, WebSocket, Request
from fastapi.responses import HTMLResponse, PlainTextResponse
from twilio.twiml.voice_response import VoiceResponse, Connect
import logging
from datetime import datetime
from typing import Dict, List
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail

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

# Store call summaries
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

Information about {YOUR_NAME}:
{USER_INFO}

Important: Keep responses brief and natural, as this is a phone conversation.
"""


@app.get("/")
async def root():
    return {"status": "AI Call Agent is running", "version": "1.0.0"}


@app.post("/incoming-call")
async def handle_incoming_call(request: Request):
    """
    Twilio webhook for incoming calls.
    Returns TwiML to connect the call to a WebSocket.
    """
    logger.info("Incoming call received")
    
    response = VoiceResponse()
    
    # Get the WebSocket URL (replace with your actual domain)
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
                        logger.info(f"Stream started: {stream_sid}")
                        
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
                        elif item.get("role") == "assistant":
                            content = item.get("content", [])
                            text = content[0].get("transcript", "") if content else ""
                            if text:
                                conversation_history.append({"role": "assistant", "content": text})
                    
                    # Capture user transcripts from input audio transcription
                    if event_type == "conversation.item.input_audio_transcription.completed":
                        transcript = response.get("transcript", "")
                        if transcript:
                            conversation_history.append({"role": "user", "content": transcript})
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
        finally:
            # Generate and store call summary
            if call_sid and conversation_history:
                summary = await generate_call_summary(conversation_history)
                call_summaries[call_sid] = {
                    "timestamp": datetime.now().isoformat(),
                    "conversation": conversation_history,
                    "summary": summary
                }
                logger.info(f"Call summary generated for {call_sid}")
                
                # Send notification if configured
                if NOTIFICATION_EMAIL:
                    await send_notification(call_sid, summary)


async def generate_call_summary(conversation: List[Dict]) -> str:
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
    
    prompt = f"""
    Summarize this phone call conversation:
    
    {convo_text}
    
    Provide a concise summary including:
    - Who called
    - Reason for calling
    - Key points discussed
    - Any action items or follow-ups needed
    """
    
    try:
        response = await client.chat.completions.create(
            model="gpt-4",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=200
        )
        return response.choices[0].message.content
    except Exception as e:
        logger.error(f"Error generating summary: {e}")
        return "Summary generation failed"


async def send_notification(call_sid: str, summary: str):
    """
    Send email notification with call summary.
    """
    if not SENDGRID_API_KEY or not NOTIFICATION_EMAIL:
        logger.warning("SendGrid API key or notification email not configured")
        return
    
    try:
        # Format the email content
        subject = f"New Call Summary - {call_sid}"
        
        html_content = f"""
        <html>
            <head></head>
            <body>
                <h2>Call Summary</h2>
                <p><strong>Call ID:</strong> {call_sid}</p>
                <p><strong>Time:</strong> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
                <hr>
                <h3>Summary:</h3>
                <p>{summary}</p>
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


@app.get("/summaries")
async def get_summaries():
    """
    Retrieve all call summaries.
    """
    return {"summaries": call_summaries}


@app.get("/summaries/{call_sid}")
async def get_summary(call_sid: str):
    """
    Retrieve a specific call summary.
    """
    if call_sid in call_summaries:
        return call_summaries[call_sid]
    return {"error": "Call not found"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

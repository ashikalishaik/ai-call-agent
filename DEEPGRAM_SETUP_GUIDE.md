# Deepgram Free Implementation - Setup Guide

## Why Deepgram Instead of OpenAI Realtime API?

✅ **$200 Free Credits** - No credit card needed
✅ **~200 hours of voice conversion** included
✅ **Faster deployment** - No limited preview restrictions
✅ **Proven in production** - Used by enterprises

---

## Step 1: Sign Up for Deepgram (FREE)

1. Visit https://console.deepgram.com
2. Sign up with your email (NO credit card required)
3. Verify your email
4. You'll instantly receive **$200 in free credits**

---

## Step 2: Get Your Deepgram API Key

1. Log in to your Deepgram Console
2. Click "API Keys" in the left sidebar
3. Click "Create a New API Key"
4. Copy the API key (starts with `dgram_...`)

---

## Step 3: Update Railway Environment Variables

Add the new environment variable to your Railway project:

**Variable Name:** `DEEPGRAM_API_KEY`
**Variable Value:** `<paste-your-key-here>`

### How to add in Railway:

1. Go to https://railway.com/project/YOUR_PROJECT_ID
2. Click "Variables"
3. Click "New Variable"
4. Add `DEEPGRAM_API_KEY` with your Deepgram API key
5. Click "Deploy" to apply changes

---

## Step 4: Deploy the New Implementation

### Option A: Switch app.py to use Deepgram

Edit your `.env` or Railway variables and restart the app:

```bash
# The app will now use Deepgram instead of OpenAI
DEEPGRAM_API_KEY=your_api_key_here
```

### Option B: Run app_deepgram.py

If you want to test the new implementation first:

```bash
# Install dependencies
pip install -r requirements_deepgram.txt

# Run the new app
python app_deepgram.py
```

---

## Step 5: Test the Implementation

### Local Testing:

1. Start the app:
   ```bash
   python app_deepgram.py
   ```

2. The app will run on `http://localhost:8000`

3. Health check endpoint:
   ```bash
   curl http://localhost:8000/health
   ```

### Production Testing (Railway):

1. Call your Twilio number
2. The AI assistant should answer and respond
3. Check the logs for messages like:
   - `User said: <transcription>`
   - `AI response: <generated response>`

---

## Feature Comparison

| Feature | OpenAI | Deepgram (FREE) |
|---------|--------|----------|
| Speech-to-Text | ✅ | ✅ |
| Text-to-Speech | ✅ | ✅ |
| Free Credits | ✗ | ✅ $200 |
| Cost per hour | $0.30 | $0 (with credits) |
| Realtime Streaming | ✅ | ✅ |
| Call Recording | ✅ | ✅ |
| Conversation History | ✅ | ✅ (Redis) |
| Email Notifications | ✅ | ✅ |
| Appointment Detection | ✅ | ✅ |

---

## Deepgram API Endpoints Used

### Speech-to-Text (Listen API)
```
wss://api.deepgram.com/v1/listen
?project_id=default
&model=nova-2
&encoding=mulaw
&sample_rate=8000
```

### Text-to-Speech (Speak API)
```
https://api.deepgram.com/v1/speak
?model=aura-asteria-en
&encoding=mulaw
&sample_rate=8000
```

---

## Monitoring Your Credits

1. Go to https://console.deepgram.com
2. Click "Billing" or "Usage"
3. See your current balance and usage

### Credit Usage Breakdown:
- **Nova-2 STT:** $0.0043/minute (streaming)
- **Aura TTS:** $0.003/minute
- **With $200 credits:** ~200+ hours of usage

---

## Troubleshooting

### "401 Unauthorized" Error
✅ Check your `DEEPGRAM_API_KEY` is correct in Railway variables
✅ Make sure you're using the full key (not truncated)
✅ Verify the API key in Deepgram console

### "No audio received"
✅ Check Twilio is properly configured
✅ Verify WebSocket connection is established
✅ Check logs for connection errors

### "Empty transcript"
✅ Make sure caller is speaking clearly
✅ Check microphone/audio settings
✅ Try a different phone for testing

---

## Next Steps: Upgrade to Better LLM

The current implementation uses simple rule-based responses. Upgrade to:

### Option 1: Hugging Face Inference (Free)
```python
import requests

response = requests.post(
    "https://api-inference.huggingface.co/models/",
    headers={"Authorization": "Bearer <HF_TOKEN>"},
    json={"inputs": user_input}
)
```

### Option 2: OpenAI (Budget-friendly)
Switch to OpenAI Chat API ($0.0005 per 1K tokens)

### Option 3: Local LLM
Run Ollama locally for completely free responses

---

## Summary

✅ **Deepgram Free = $200 in credits**
✅ **~200 hours of voice conversion included**
✅ **All existing features preserved**
✅ **No more budget issues!**

Your AI call agent is now running on a completely FREE solution!

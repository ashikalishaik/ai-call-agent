# 🤖 AI Call Agent

> **An intelligent AI-powered call agent that handles missed calls, provides personalized responses, and generates comprehensive call summaries.**

Built with **Twilio Voice**, **OpenAI Realtime API**, and **FastAPI**, this project enables you to deploy an AI assistant that can answer phone calls on your behalf, respond to caller questions using personalized information, and automatically summarize conversations for later review.

---

## ✨ Features

- **🎙️ Real-time Voice Conversations**: Seamless two-way voice communication using OpenAI's Realtime API
- **🧠 Personalized AI Responses**: Answers questions using custom information you provide about yourself
- **📝 Automatic Call Summaries**: Generates detailed summaries of each call including key points and action items
- **📊 Call History**: Store and retrieve summaries via REST API
- **🔔 Notifications**: Optional email/SMS notifications when calls are received
- **🐳 Docker Support**: Easy deployment with Docker and Docker Compose
- **⚡ FastAPI Backend**: High-performance async API

---

## 🏗️ Architecture

```
Phone Call → Twilio → WebSocket → FastAPI Server → OpenAI Realtime API
                                         ↓
                                   Call Summary
                                         ↓
                                   Notification
```

---

## 📋 Prerequisites

Before you begin, ensure you have:

- **Python 3.11+** installed
- **Twilio Account** ([Sign up here](https://www.twilio.com/try-twilio))
- **OpenAI API Key** with Realtime API access ([Get it here](https://platform.openai.com/))
- **Docker & Docker Compose** (optional, for containerized deployment)
- **ngrok** or similar tool for local development (to expose localhost to Twilio)

---

## 🚀 Quick Start

### 1. Clone the Repository

```bash
git clone https://github.com/ashikalishaik/ai-call-agent.git
cd ai-call-agent
```

### 2. Set Up Environment Variables

Copy the example environment file and fill in your credentials:

```bash
cp .env.example .env
```

Edit `.env` and add your credentials:

```env
# OpenAI Configuration
OPENAI_API_KEY=your_openai_api_key_here

# Twilio Configuration
TWILIO_ACCOUNT_SID=your_twilio_account_sid_here
TWILIO_AUTH_TOKEN=your_twilio_auth_token_here
TWILIO_PHONE_NUMBER=your_twilio_phone_number_here

# Personal Information
YOUR_NAME=Your Full Name
USER_INFO=I am a software engineer. I'm usually available Mon-Fri 9-5. I specialize in AI and web development.

# Notification Configuration (Optional)
NOTIFICATION_EMAIL=your_email@example.com
```

### 3. Install Dependencies

**Option A: Using pip**

```bash
pip install -r requirements.txt
```

**Option B: Using Docker**

```bash
docker-compose up --build
```

### 4. Run the Application

**Without Docker:**

```bash
python app.py
```

**With Docker:**

```bash
docker-compose up
```

The server will start on `http://0.0.0.0:8000`

### 5. Expose Your Server (For Local Development)

Use ngrok to expose your local server:

```bash
ngrok http 8000
```

Ngrok will provide a public URL like: `https://abc123.ngrok.io`

### 6. Configure Twilio Webhook

1. Log in to your [Twilio Console](https://console.twilio.com/)
2. Go to **Phone Numbers** → Select your number
3. Under "Voice Configuration":
   - Set **A CALL COMES IN** to **Webhook**
   - Enter your URL: `https://your-ngrok-url.ngrok.io/incoming-call`
   - Set method to **HTTP POST**
4. Click **Save**

---

## 📖 Usage

### Making Test Calls

1. Call your Twilio phone number
2. The AI agent will answer and greet you
3. Have a conversation - the AI will respond based on your configured `USER_INFO`
4. After the call ends, a summary will be automatically generated

### Retrieving Call Summaries

**Get all summaries:**
```bash
curl http://localhost:8000/summaries
```

**Get specific call summary:**
```bash
curl http://localhost:8000/summaries/{call_sid}
```

---

## ⚙️ Configuration

### Customizing AI Behavior

Edit the `SYSTEM_MESSAGE` in `app.py` to change how the AI assistant behaves:

```python
SYSTEM_MESSAGE = f"""
You are an intelligent voice assistant...
"""
```

### Changing AI Voice

Modify the `voice` parameter in the session configuration:

```python
"voice": "alloy"  # Options: alloy, echo, fable, onyx, nova, shimmer
```

---

## 🐳 Deployment

### Deploy with Docker

```bash
docker build -t ai-call-agent .
docker run -p 8000:8000 --env-file .env ai-call-agent
```

### Deploy to Cloud Providers

This application can be deployed to:
- **AWS** (EC2, ECS, or Lambda)
- **Google Cloud Run**
- **Heroku**
- **Azure App Service**
- **DigitalOcean App Platform**

Make sure to:
1. Set environment variables in your cloud provider's dashboard
2. Update Twilio webhook URL to point to your deployed URL
3. Ensure HTTPS is enabled (required by Twilio)

---

## 📚 API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/` | Health check |
| POST | `/incoming-call` | Twilio webhook for incoming calls |
| WebSocket | `/media-stream` | Media stream connection |
| GET | `/summaries` | Get all call summaries |
| GET | `/summaries/{call_sid}` | Get specific call summary |

---

## 🔧 Troubleshooting

### Common Issues

**1. WebSocket connection fails**
- Ensure your server is accessible via HTTPS (Twilio requirement)
- Check ngrok is running for local development

**2. AI doesn't respond**
- Verify OpenAI API key is valid and has Realtime API access
- Check server logs for error messages

**3. Twilio webhook errors**
- Ensure webhook URL is correct in Twilio console
- Verify the endpoint returns valid TwiML

**4. Audio quality issues**
- Check your internet connection
- Ensure proper audio codec configuration (G.711 μ-law)

---

## 🛠️ Development

### Project Structure

```
ai-call-agent/
├── app.py                 # Main application
├── requirements.txt       # Python dependencies
├── Dockerfile            # Docker configuration
├── docker-compose.yml    # Docker Compose setup
├── .env.example          # Example environment variables
├── .gitignore           # Git ignore rules
├── LICENSE              # MIT License
└── README.md            # This file
```

### Running Tests

```bash
pytest tests/
```

---

## 🤝 Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

1. Fork the repository
2. Create your feature branch (`git checkout -b feature/AmazingFeature`)
3. Commit your changes (`git commit -m 'Add some AmazingFeature'`)
4. Push to the branch (`git push origin feature/AmazingFeature`)
5. Open a Pull Request

---

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

---

## 🙏 Acknowledgments

- [OpenAI](https://openai.com/) for the Realtime API
- [Twilio](https://www.twilio.com/) for telephony infrastructure
- [FastAPI](https://fastapi.tiangolo.com/) for the web framework

---

## 📞 Support

If you have any questions or need help, please:
- Open an issue on GitHub
- Check the [Twilio documentation](https://www.twilio.com/docs)
- Review [OpenAI Realtime API docs](https://platform.openai.com/docs/)

---

## 🌟 Star History

If you find this project useful, please consider giving it a star! ⭐

---

**Made with ❤️ by [Ashikali Shaik](https://github.com/ashikalishaik)**

# 🌐 LearnSphere v3 — AI-Powered ML Learning Platform
### Now powered by **Groq API** (Free, Ultra-Fast LLaMA 3.3)

## 🚀 Quick Start (3 Steps)

### Step 1 — Install
```powershell
pip install flask groq
```

### Step 2 — Get FREE Groq API Key
1. Go to **https://console.groq.com**
2. Sign up for free (no credit card needed)
3. Click **"API Keys"** → **"Create API Key"**
4. Copy your key

### Step 3 — Run
```powershell
# Windows PowerShell:
$env:GROQ_API_KEY="gsk_your_key_here"
python app.py

# OR hardcode in app.py line 13:
# GROQ_API_KEY = 'gsk_your_key_here'
```
Open: **http://localhost:5000**

---

## 👤 Demo Accounts
| Role | Email | Password |
|------|-------|----------|
| 👩‍🏫 Educator | educator@learnsphere.com | admin123 |
| 👨‍🎓 Student | student@learnsphere.com | student123 |

## 🤖 Why Groq?
- ✅ **Completely Free** — generous free tier
- ✅ **Ultra Fast** — 500+ tokens/second (fastest LLM API)
- ✅ **No quota issues** — 30 req/min free
- ✅ **Powerful** — LLaMA 3.3 70B model

## 📁 Project Structure
```
learnsphere/
├── app.py              ← Flask + Groq AI backend
├── requirements.txt
├── templates/
│   ├── login.html          ← Login/Register page
│   ├── student_dashboard.html
│   ├── student_courses.html
│   ├── student_course_view.html
│   ├── student_lecture.html    ← Lecture viewer with AI tutor
│   ├── educator_dashboard.html
│   ├── educator_courses.html
│   ├── educator_course_form.html   ← Create/edit courses
│   ├── educator_lectures.html
│   ├── educator_lecture_form.html  ← Create/edit lectures
│   ├── learn.html          ← AI concept explainer
│   ├── code.html           ← Code generator & analyzer
│   └── dashboard.html      ← Progress tracker
└── static/
    ├── css/style.css
    └── js/main.js
```


An intelligent, adaptive machine learning tutor powered by Google Gemini AI.

## 🚀 Features

- **Smart Concept Explanations** — Text, examples, formulas, and code in one click
- **Adaptive Learning Engine** — Tracks your progress and adjusts difficulty
- **Code Generator** — Generate complete ML code from plain English
- **Code Analyzer** — Paste your code and get intelligent feedback & improvements
- **Visual Diagrams** — Auto-generated SVG concept diagrams
- **Audio Narration** — Browser text-to-speech for every explanation
- **AI Tutor Chat** — Real-time conversational AI mentor
- **Progress Dashboard** — Track topics, strengths, weaknesses, and level
- **Quiz System** — Test comprehension after each concept
- **Personalized Suggestions** — AI-curated next topics based on your journey

## 📦 Setup

### 1. Install Dependencies
```bash
pip install flask google-generativeai
```

### 2. Set your Gemini API Key
Get a free API key from: https://aistudio.google.com/app/apikey

Then set it in one of these ways:

**Option A — Environment Variable (recommended):**
```bash
export GEMINI_API_KEY="your-api-key-here"
python app.py
```

**Option B — Edit app.py directly:**
```python
GEMINI_API_KEY = 'your-api-key-here'  # Line 10 in app.py
```

### 3. Run
```bash
cd learnsphere
python app.py
```

Open: http://localhost:5000

## 📁 Project Structure

```
learnsphere/
├── app.py              # Flask backend + Gemini AI API
├── requirements.txt
├── templates/
│   ├── base.html       # Navbar, shared layout
│   ├── index.html      # Landing page with neural animation
│   ├── learn.html      # Concept learning + AI chat
│   ├── code.html       # Code generator + analyzer
│   └── dashboard.html  # Progress dashboard
└── static/
    ├── css/style.css   # Full dark cyberpunk theme
    └── js/main.js      # Shared JavaScript
```

## 🔌 API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/explain` | POST | Explain ML concepts (full/simple/technical) |
| `/api/generate_code` | POST | Generate ML Python code |
| `/api/analyze_code` | POST | Analyze & give feedback on code |
| `/api/generate_diagram` | POST | Generate SVG diagram for concept |
| `/api/chat` | POST | Conversational AI tutor |
| `/api/audio_script` | POST | Generate narration script |
| `/api/quiz_check` | POST | Check quiz answer & update profile |
| `/api/suggest_topics` | GET | Get personalized topic suggestions |
| `/api/profile` | GET | Get user learning profile |

## 🎓 How Learning Adaptation Works

The system tracks:
- Total concepts explored
- Quiz accuracy rate
- Topics answered correctly (strengths) vs incorrectly (weaknesses)

Level progression:
- **Beginner**: <5 queries or <50% accuracy
- **Intermediate**: >5 queries and >50% accuracy  
- **Advanced**: >5 queries and >80% accuracy

Explanations automatically adjust to the detected level.

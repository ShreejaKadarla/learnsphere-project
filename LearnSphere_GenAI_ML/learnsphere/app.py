from flask import Flask, render_template, request, jsonify, session, redirect, url_for
from groq import Groq
import json, os, sqlite3, hashlib, uuid
from datetime import datetime
from functools import wraps

app = Flask(__name__)
app.secret_key = 'learnsphere_secret_2024_xyz'

# ─── GROQ API SETUP (Free & Fast) ─────────────────────────────────────────
# Get free API key at: https://console.groq.com
GROQ_API_KEY = os.environ.get('GROQ_API_KEY', 'YOUR_GROQ_API_KEY')
groq_client = Groq(api_key=GROQ_API_KEY)
GROQ_MODEL = 'llama-3.3-70b-versatile'   # Fast, free, powerful

def ask_groq(prompt, system="You are LearnSphere, an expert ML tutor.", temperature=0.7):
    """Call Groq API and return response text."""
    response = groq_client.chat.completions.create(
        model=GROQ_MODEL,
        messages=[
            {"role": "system", "content": system},
            {"role": "user",   "content": prompt}
        ],
        temperature=temperature,
        max_tokens=4096,
    )
    return response.choices[0].message.content

def clean_and_parse_json(text):
    """
    Robustly parse JSON from LLM output.
    Handles: markdown fences, control characters, bad escapes, code blocks inside JSON.
    """
    text = text.strip()

    # Remove markdown code fences
    import re
    text = re.sub(r'^```(?:json)?\s*', '', text, flags=re.MULTILINE)
    text = re.sub(r'```\s*$', '', text, flags=re.MULTILINE)
    text = text.strip()

    # Try direct parse first
    try:
        return json.loads(text)
    except Exception:
        pass

    # Find outermost JSON object
    start = text.find('{')
    end = text.rfind('}')
    if start != -1 and end != -1 and end > start:
        text = text[start:end+1]

    # Try again after extracting
    try:
        return json.loads(text)
    except Exception:
        pass

    # Fix common issues:
    # 1. Remove actual newlines/tabs inside string values (keep JSON structure newlines)
    # 2. Fix unescaped backslashes in code strings
    # 3. Replace control characters
    def fix_json_string(m):
        s = m.group(0)
        # Replace real newlines inside strings with \n
        s = s.replace('\n', '\\n').replace('\r', '\\r').replace('\t', '\\t')
        # Fix double-escaped: \\n that became \\\\n
        s = s.replace('\\\\n', '\\n').replace('\\\\t', '\\t')
        return s

    # Fix string values that span multiple lines
    fixed = re.sub(r'"(?:[^"\\]|\\.)*"', fix_json_string, text, flags=re.DOTALL)
    try:
        return json.loads(fixed)
    except Exception:
        pass

    # Last resort: use a very permissive approach
    # Remove all control characters except proper JSON whitespace
    clean = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', text)
    try:
        return json.loads(clean)
    except Exception as e:
        raise ValueError(f"Could not parse JSON after all attempts. Raw error: {e}\nText preview: {text[:200]}")


def ask_groq_json(prompt, system="You are LearnSphere, an expert ML tutor. Always respond with valid JSON only. Never include raw newlines inside JSON string values - use \\n instead."):
    """Call Groq and parse JSON response reliably."""
    text = ask_groq(prompt, system=system, temperature=0.3)
    return clean_and_parse_json(text)

DB_PATH = 'learnsphere.db'

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users (
        id TEXT PRIMARY KEY, username TEXT UNIQUE NOT NULL, email TEXT UNIQUE NOT NULL,
        password TEXT NOT NULL, role TEXT NOT NULL DEFAULT 'student',
        created_at TEXT DEFAULT CURRENT_TIMESTAMP, level TEXT DEFAULT 'beginner',
        total_queries INTEGER DEFAULT 0, correct_attempts INTEGER DEFAULT 0)''')
    c.execute('''CREATE TABLE IF NOT EXISTS courses (
        id TEXT PRIMARY KEY, title TEXT NOT NULL, description TEXT, category TEXT,
        difficulty TEXT DEFAULT 'beginner', educator_id TEXT NOT NULL, educator_name TEXT,
        thumbnail_color TEXT DEFAULT '#00D4FF', created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        is_published INTEGER DEFAULT 1, FOREIGN KEY (educator_id) REFERENCES users(id))''')
    c.execute('''CREATE TABLE IF NOT EXISTS lectures (
        id TEXT PRIMARY KEY, course_id TEXT NOT NULL, title TEXT NOT NULL,
        content TEXT, lecture_type TEXT DEFAULT 'text', video_url TEXT, code_example TEXT,
        order_num INTEGER DEFAULT 0, duration_mins INTEGER DEFAULT 10,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP, FOREIGN KEY (course_id) REFERENCES courses(id))''')
    c.execute('''CREATE TABLE IF NOT EXISTS enrollments (
        id TEXT PRIMARY KEY, student_id TEXT NOT NULL, course_id TEXT NOT NULL,
        enrolled_at TEXT DEFAULT CURRENT_TIMESTAMP, progress INTEGER DEFAULT 0,
        UNIQUE(student_id, course_id))''')
    c.execute('''CREATE TABLE IF NOT EXISTS completed_lectures (
        id TEXT PRIMARY KEY, student_id TEXT NOT NULL, lecture_id TEXT NOT NULL,
        completed_at TEXT DEFAULT CURRENT_TIMESTAMP, UNIQUE(student_id, lecture_id))''')
    c.execute('''CREATE TABLE IF NOT EXISTS notes (
        id TEXT PRIMARY KEY, student_id TEXT NOT NULL, lecture_id TEXT NOT NULL,
        content TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP)''')

    # AI Learning DNA — tracks per-concept performance
    c.execute('''CREATE TABLE IF NOT EXISTS learning_dna (
        id TEXT PRIMARY KEY,
        user_id TEXT NOT NULL,
        concept TEXT NOT NULL,
        attempts INTEGER DEFAULT 0,
        correct INTEGER DEFAULT 0,
        avg_response_ms INTEGER DEFAULT 0,
        last_seen TEXT,
        next_review TEXT,
        ease_factor REAL DEFAULT 2.5,
        interval_days INTEGER DEFAULT 1,
        style_pref TEXT DEFAULT "balanced",
        UNIQUE(user_id, concept))''')

    # Battle mode scores
    c.execute('''CREATE TABLE IF NOT EXISTS battle_scores (
        id TEXT PRIMARY KEY,
        user_id TEXT NOT NULL,
        username TEXT,
        score INTEGER DEFAULT 0,
        ai_score INTEGER DEFAULT 0,
        topic TEXT,
        played_at TEXT DEFAULT CURRENT_TIMESTAMP)''')

    admin_id = str(uuid.uuid4())
    admin_pw = hash_password('admin123')
    try:
        c.execute("INSERT INTO users (id,username,email,password,role) VALUES (?,?,?,?,?)",
                  (admin_id,'educator','educator@learnsphere.com',admin_pw,'educator'))
        # Sample student
        stu_id = str(uuid.uuid4())
        c.execute("INSERT INTO users (id,username,email,password,role) VALUES (?,?,?,?,?)",
                  (stu_id,'student','student@learnsphere.com',hash_password('student123'),'student'))

        cid = str(uuid.uuid4())
        c.execute("""INSERT INTO courses (id,title,description,category,difficulty,educator_id,educator_name,thumbnail_color)
                     VALUES (?,?,?,?,?,?,?,?)""",
                  (cid,'Machine Learning Fundamentals',
                   'A complete beginner-friendly course covering core ML concepts from linear regression to neural networks.',
                   'Machine Learning','beginner',admin_id,'Prof. Educator','#00D4FF'))

        lectures_data = [
            (1,'Introduction to Machine Learning','text',15,
             '''Machine Learning is a subset of Artificial Intelligence that enables computers to learn from data without being explicitly programmed.

## What is Machine Learning?
Machine Learning allows systems to automatically learn and improve from experience. Instead of writing rules manually, we feed data to algorithms that discover patterns themselves.

## Three Core Types of ML

**1. Supervised Learning**
The algorithm learns from labeled training data. You provide inputs AND expected outputs.
- Examples: Email spam detection, image classification, price prediction

**2. Unsupervised Learning**
The algorithm finds hidden patterns in unlabeled data on its own.
- Examples: Customer segmentation, anomaly detection, recommendation systems

**3. Reinforcement Learning**
An agent learns by interacting with an environment, receiving rewards/penalties.
- Examples: Game-playing AI (Chess, Go), robotics, autonomous vehicles

## Why ML Matters Today
- Powers Netflix/YouTube recommendations
- Enables voice assistants (Siri, Alexa, Google)
- Drives self-driving car systems
- Detects fraud in banking in real-time
- Diagnoses diseases from medical images

## The Standard ML Workflow
1. **Collect Data** — gather relevant, quality data
2. **Prepare Data** — clean, normalize, split train/test
3. **Choose Algorithm** — pick based on problem type
4. **Train Model** — fit model to training data
5. **Evaluate** — measure accuracy on test data
6. **Deploy** — serve predictions in production''',
             '# No code in intro lecture'),

            (2,'Linear Regression','text',25,
             '''Linear Regression is the most fundamental supervised learning algorithm for predicting continuous numeric values.

## Core Concept
Find the best straight line (or hyperplane) that fits through data points to make predictions.

**The Formula:**
```
y = w₁x₁ + w₂x₂ + ... + b
```
- y = predicted value
- x = input features
- w = weights (learned from data)
- b = bias/intercept

## How Training Works
1. Initialize weights randomly
2. Make predictions on training data
3. Calculate loss (how wrong predictions are)
4. Use gradient descent to adjust weights
5. Repeat until loss stops decreasing

**Loss Function — Mean Squared Error:**
```
MSE = (1/n) Σ (y_predicted - y_actual)²
```

## Real-World Applications
- House price prediction (size → price)
- Sales forecasting (ad spend → revenue)
- Student performance (study hours → grade)
- Medical dosage (weight → dose)

## Evaluation Metrics
- **R² Score**: How well model explains variance (1.0 = perfect)
- **MSE**: Average squared prediction error
- **RMSE**: Root MSE (same units as target)''',
             '''import numpy as np
from sklearn.linear_model import LinearRegression
from sklearn.model_selection import train_test_split
from sklearn.metrics import mean_squared_error, r2_score

# Dataset: Study hours vs exam scores
hours = np.array([1,2,3,4,5,6,7,8,9,10]).reshape(-1,1)
scores = np.array([35,42,57,62,70,78,82,88,92,96])

X_train, X_test, y_train, y_test = train_test_split(hours, scores, test_size=0.2, random_state=42)

model = LinearRegression()
model.fit(X_train, y_train)
predictions = model.predict(X_test)

print(f"R² Score:   {r2_score(y_test, predictions):.3f}")
print(f"MSE:        {mean_squared_error(y_test, predictions):.2f}")
print(f"Slope:      {model.coef_[0]:.2f}")
print(f"Intercept:  {model.intercept_:.2f}")
print(f"\\nPrediction for 7.5 hours: {model.predict([[7.5]])[0]:.1f}")'''),

            (3,'Decision Trees & Random Forests','text',30,
             '''Decision Trees are intuitive ML models that make predictions by asking a series of yes/no questions.

## How a Decision Tree Works
Think of it like 20 questions:
- "Is the tumor size > 3cm?" → Yes → "Is patient age > 50?" → ...

**Key Components:**
- **Root Node**: First split (most important feature)
- **Internal Nodes**: Subsequent questions
- **Leaf Nodes**: Final prediction/class
- **Splitting Criterion**: Gini Impurity or Information Gain

## Pros & Cons
✅ Easy to understand and visualize
✅ No feature scaling needed
✅ Handles mixed data types
❌ Prone to overfitting
❌ Unstable with small data changes

## Random Forest = Ensemble of Trees
Combines 100–1000 decision trees, each trained on random data subsets. Takes majority vote for final prediction.

**Why it's better:**
- Reduces overfitting dramatically
- More stable and accurate
- Provides feature importance scores
- Works well out of the box

## When to Use
- Classification (spam, disease, fraud)
- Feature importance analysis
- When you need interpretable results
- Tabular/structured data problems''',
             '''from sklearn.ensemble import RandomForestClassifier
from sklearn.tree import DecisionTreeClassifier
from sklearn.datasets import load_iris
from sklearn.model_selection import train_test_split
from sklearn.metrics import accuracy_score

iris = load_iris()
X, y = iris.data, iris.target
X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.3, random_state=42)

# Decision Tree
dt = DecisionTreeClassifier(max_depth=4, random_state=42)
dt.fit(X_train, y_train)
print(f"Decision Tree Accuracy: {accuracy_score(y_test, dt.predict(X_test)):.2%}")

# Random Forest
rf = RandomForestClassifier(n_estimators=100, max_depth=4, random_state=42)
rf.fit(X_train, y_train)
print(f"Random Forest Accuracy: {accuracy_score(y_test, rf.predict(X_test)):.2%}")

print("\\nFeature Importances:")
for name, imp in zip(iris.feature_names, rf.feature_importances_):
    print(f"  {name}: {imp:.3f}")'''),

            (4,'Neural Networks Deep Dive','text',45,
             '''Neural Networks are the foundation of modern AI — loosely inspired by the human brain's structure.

## Architecture
```
Input Layer → Hidden Layers → Output Layer
[x1,x2,x3] →  [neurons]   →   [output]
```

## How a Single Neuron Works
1. Receive inputs: x₁, x₂, x₃...
2. Multiply by weights: w₁, w₂, w₃...
3. Sum + add bias: z = Σwᵢxᵢ + b
4. Apply activation function: a = f(z)
5. Pass result to next layer

## Common Activation Functions
| Function | Formula | Use Case |
|----------|---------|---------|
| ReLU | max(0, x) | Hidden layers (most common) |
| Sigmoid | 1/(1+e⁻ˣ) | Binary output (0-1) |
| Softmax | eˣⁱ/Σeˣʲ | Multi-class output |
| Tanh | (eˣ-e⁻ˣ)/(eˣ+e⁻ˣ) | Hidden layers (-1 to 1) |

## Training Process
1. **Forward Pass** → compute predictions
2. **Loss Calculation** → measure error
3. **Backpropagation** → compute gradients
4. **Weight Update** → gradient descent step
5. **Repeat** for many epochs

## Types of Neural Networks
- **MLP**: Basic feedforward (tabular data)
- **CNN**: Images and spatial data
- **RNN/LSTM**: Sequences (text, time-series)
- **Transformer**: State-of-the-art NLP (GPT, BERT)
- **GAN**: Generate new data (images, music)''',
             '''import numpy as np

class NeuralNetwork:
    def __init__(self, input_size, hidden_size, output_size, lr=0.1):
        self.W1 = np.random.randn(input_size, hidden_size) * 0.01
        self.b1 = np.zeros((1, hidden_size))
        self.W2 = np.random.randn(hidden_size, output_size) * 0.01
        self.b2 = np.zeros((1, output_size))
        self.lr = lr

    def relu(self, x): return np.maximum(0, x)
    def sigmoid(self, x): return 1 / (1 + np.exp(-np.clip(x, -500, 500)))

    def forward(self, X):
        self.z1 = X @ self.W1 + self.b1
        self.a1 = self.relu(self.z1)
        self.z2 = self.a1 @ self.W2 + self.b2
        self.a2 = self.sigmoid(self.z2)
        return self.a2

    def backward(self, X, y):
        m = X.shape[0]
        dz2 = self.a2 - y
        dW2 = self.a1.T @ dz2 / m
        db2 = dz2.mean(axis=0, keepdims=True)
        dz1 = (dz2 @ self.W2.T) * (self.a1 > 0)
        dW1 = X.T @ dz1 / m
        db1 = dz1.mean(axis=0, keepdims=True)
        self.W1 -= self.lr * dW1; self.b1 -= self.lr * db1
        self.W2 -= self.lr * dW2; self.b2 -= self.lr * db2

    def train(self, X, y, epochs=1000):
        for e in range(epochs):
            out = self.forward(X)
            self.backward(X, y)
            if e % 200 == 0:
                loss = -np.mean(y*np.log(out+1e-8)+(1-y)*np.log(1-out+1e-8))
                print(f"Epoch {e:4d}: Loss={loss:.4f}")

# XOR problem demo
X = np.array([[0,0],[0,1],[1,0],[1,1]])
y = np.array([[0],[1],[1],[0]])
nn = NeuralNetwork(2, 4, 1, lr=0.1)
nn.train(X, y, epochs=1000)
print("\\nPredictions:", nn.forward(X).round(2))'''),
        ]

        for order, title, ltype, dur, content, code in lectures_data:
            lid = str(uuid.uuid4())
            c.execute("""INSERT INTO lectures (id,course_id,title,content,lecture_type,code_example,order_num,duration_mins)
                         VALUES (?,?,?,?,?,?,?,?)""",
                      (lid, cid, title, content, ltype, code, order, dur))

        # Course 2
        cid2 = str(uuid.uuid4())
        c.execute("""INSERT INTO courses (id,title,description,category,difficulty,educator_id,educator_name,thumbnail_color)
                     VALUES (?,?,?,?,?,?,?,?)""",
                  (cid2,'Deep Learning with Python',
                   'Advanced course covering CNNs, RNNs, Transformers, and hands-on deep learning projects with TensorFlow & PyTorch.',
                   'Deep Learning','advanced',admin_id,'Prof. Educator','#7C3AED'))
        dl_lid = str(uuid.uuid4())
        c.execute("""INSERT INTO lectures (id,course_id,title,content,lecture_type,code_example,order_num,duration_mins)
                     VALUES (?,?,?,?,?,?,?,?)""",
                  (dl_lid,cid2,'Introduction to Deep Learning',
                   '''Deep Learning is a subset of ML using multi-layered neural networks to learn hierarchical representations from large amounts of data.

## Why Deep Learning Exploded
Three converging factors:
1. **Big Data** — internet-scale labeled datasets (ImageNet, Common Crawl)
2. **GPUs** — parallel computing made training feasible
3. **Better Algorithms** — ReLU, Dropout, BatchNorm, Adam optimizer

## Deep vs Shallow Learning
- **Shallow ML**: handcrafted features → simple model
- **Deep Learning**: raw data → automatic feature learning → prediction

## Major Applications
- Computer Vision (image classification, object detection, segmentation)
- NLP (translation, summarization, question answering)
- Speech Recognition & synthesis
- Drug discovery & protein folding (AlphaFold)
- Game playing (AlphaGo, OpenAI Five)

## Popular Frameworks
- **TensorFlow/Keras** (Google) — production ready, easy API
- **PyTorch** (Meta) — research favorite, dynamic graphs
- **JAX** (Google) — high performance, functional style''',
                   'text',
                   '''import tensorflow as tf

# Simple deep neural network
model = tf.keras.Sequential([
    tf.keras.layers.Dense(256, activation="relu", input_shape=(784,)),
    tf.keras.layers.Dropout(0.3),
    tf.keras.layers.Dense(128, activation="relu"),
    tf.keras.layers.Dropout(0.3),
    tf.keras.layers.Dense(64, activation="relu"),
    tf.keras.layers.Dense(10, activation="softmax")
])
model.compile(
    optimizer=tf.keras.optimizers.Adam(0.001),
    loss="sparse_categorical_crossentropy",
    metrics=["accuracy"]
)
model.summary()
# Train: model.fit(X_train, y_train, epochs=10, validation_split=0.1)''',1,20))

        # Course 3
        cid3 = str(uuid.uuid4())
        c.execute("""INSERT INTO courses (id,title,description,category,difficulty,educator_id,educator_name,thumbnail_color)
                     VALUES (?,?,?,?,?,?,?,?)""",
                  (cid3,'Natural Language Processing',
                   'Learn how machines understand text: from tokenization and embeddings to Transformers, BERT, and GPT.',
                   'NLP','intermediate',admin_id,'Prof. Educator','#10B981'))
        nlp_lid = str(uuid.uuid4())
        c.execute("""INSERT INTO lectures (id,course_id,title,content,lecture_type,code_example,order_num,duration_mins)
                     VALUES (?,?,?,?,?,?,?,?)""",
                  (nlp_lid,cid3,'Text Preprocessing Fundamentals',
                   '''Before feeding text to ML models, we must convert raw text into numerical representations.

## NLP Pipeline
```
Raw Text → Tokenize → Clean → Vectorize → Model
```

## Step 1: Tokenization
Split text into words, subwords, or characters.
- "Hello world" → ["Hello", "world"]
- "don't" → ["don", "'", "t"]  or  ["don't"]

## Step 2: Text Cleaning
- Lowercase: "Hello" → "hello"
- Remove punctuation, special characters
- Remove stop words: "the", "a", "is"
- Stemming/Lemmatization: "running" → "run"

## Step 3: Vectorization
Convert tokens to numbers:

**Bag of Words**: Count word frequencies (ignores order)

**TF-IDF**: Weight words by importance across documents

**Word Embeddings**: Dense vectors capturing semantic meaning
- Word2Vec, GloVe, FastText
- "king" - "man" + "woman" ≈ "queen"

**Modern**: BERT/GPT tokenizers (subword BPE)

## Why This Matters
Bad preprocessing = bad model performance
Good features = 80% of NLP success''',
                   'text',
                   '''import re
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.naive_bayes import MultinomialNB
from sklearn.pipeline import Pipeline

# Sample text data
texts = [
    "Machine learning is amazing and powerful",
    "Deep learning uses neural networks",
    "Python is great for data science",
    "Natural language processing enables text analysis",
    "Neural networks learn from examples"
]
labels = [1, 1, 0, 1, 1]  # 1=ML topic, 0=other

def preprocess(text):
    text = text.lower()
    text = re.sub(r\'[^a-z\\s]\', \'\', text)
    return text

processed = [preprocess(t) for t in texts]

# TF-IDF + Naive Bayes Pipeline
pipeline = Pipeline([
    ("tfidf", TfidfVectorizer(stop_words="english", max_features=1000)),
    ("clf", MultinomialNB())
])
pipeline.fit(processed, labels)

test = ["recurrent neural networks handle sequences"]
print("Prediction:", "ML topic" if pipeline.predict([preprocess(test[0])])[0] else "Other")''',1,20))

    except Exception:
        pass

    conn.commit()
    conn.close()

def hash_password(pw):
    return hashlib.sha256(pw.encode()).hexdigest()

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login_page'))
        return f(*args, **kwargs)
    return decorated

def educator_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login_page'))
        if session.get('role') != 'educator':
            return redirect(url_for('student_dashboard'))
        return f(*args, **kwargs)
    return decorated

# ─── ROUTES ──────────────────────────────────────────────────────────────────
@app.route('/')
def index():
    if 'user_id' in session:
        return redirect(url_for('student_dashboard') if session.get('role')=='student' else url_for('educator_dashboard'))
    return render_template('index.html')

@app.route('/login')
def login_page():
    if 'user_id' in session:
        return redirect(url_for('student_dashboard') if session.get('role')=='student' else url_for('educator_dashboard'))
    return render_template('login.html')

@app.route('/api/auth/login', methods=['POST'])
def login():
    data = request.json
    conn = get_db()
    user = conn.execute("SELECT * FROM users WHERE email=? AND password=?",
                        (data['email'], hash_password(data['password']))).fetchone()
    conn.close()
    if user:
        session['user_id']=user['id']; session['username']=user['username']
        session['role']=user['role']; session['email']=user['email']
        return jsonify({'success':True,'role':user['role'],'username':user['username']})
    return jsonify({'success':False,'error':'Invalid email or password'})

@app.route('/api/auth/register', methods=['POST'])
def register():
    data = request.json
    conn = get_db()
    try:
        uid = str(uuid.uuid4())
        conn.execute("INSERT INTO users (id,username,email,password,role) VALUES (?,?,?,?,?)",
                     (uid, data['username'], data['email'], hash_password(data['password']), data.get('role','student')))
        conn.commit(); conn.close()
        return jsonify({'success':True})
    except sqlite3.IntegrityError:
        conn.close()
        return jsonify({'success':False,'error':'Email or username already exists'})

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('index'))

@app.route('/student/dashboard')
@login_required
def student_dashboard():
    if session.get('role')=='educator': return redirect(url_for('educator_dashboard'))
    return render_template('student_dashboard.html')

@app.route('/student/courses')
@login_required
def student_courses():
    return render_template('student_courses.html')

@app.route('/student/course/<course_id>')
@login_required
def student_course_view(course_id):
    return render_template('student_course_view.html', course_id=course_id)

@app.route('/student/lecture/<lecture_id>')
@login_required
def student_lecture(lecture_id):
    return render_template('student_lecture.html', lecture_id=lecture_id)

@app.route('/learn')
@login_required
def learn():
    return render_template('learn.html')

@app.route('/code')
@login_required
def code():
    return render_template('code.html')

@app.route('/dashboard')
@login_required
def dashboard():
    return render_template('dashboard.html')

@app.route('/educator/dashboard')
@educator_required
def educator_dashboard():
    return render_template('educator_dashboard.html')

@app.route('/educator/courses')
@educator_required
def educator_courses():
    return render_template('educator_courses.html')

@app.route('/educator/course/new')
@educator_required
def educator_new_course():
    return render_template('educator_course_form.html', course_id=None)

@app.route('/educator/course/<course_id>/edit')
@educator_required
def educator_edit_course(course_id):
    return render_template('educator_course_form.html', course_id=course_id)

@app.route('/educator/course/<course_id>/lectures')
@educator_required
def educator_lectures(course_id):
    return render_template('educator_lectures.html', course_id=course_id)

@app.route('/educator/lecture/new/<course_id>')
@educator_required
def educator_new_lecture(course_id):
    return render_template('educator_lecture_form.html', course_id=course_id, lecture_id=None)

@app.route('/educator/lecture/<lecture_id>/edit')
@educator_required
def educator_edit_lecture(lecture_id):
    return render_template('educator_lecture_form.html', course_id=None, lecture_id=lecture_id)

# ─── COURSE API ───────────────────────────────────────────────────────────────
@app.route('/api/courses', methods=['GET'])
@login_required
def get_courses():
    conn = get_db()
    courses = conn.execute("SELECT * FROM courses WHERE is_published=1 ORDER BY created_at DESC").fetchall()
    result = []
    for cr in courses:
        lc = conn.execute("SELECT COUNT(*) FROM lectures WHERE course_id=?",(cr['id'],)).fetchone()[0]
        enrolled = conn.execute("SELECT 1 FROM enrollments WHERE student_id=? AND course_id=?",(session['user_id'],cr['id'])).fetchone()
        result.append({**dict(cr),'lecture_count':lc,'enrolled':enrolled is not None})
    conn.close()
    return jsonify(result)

@app.route('/api/educator/courses', methods=['GET'])
@educator_required
def get_educator_courses():
    conn = get_db()
    courses = conn.execute("SELECT * FROM courses WHERE educator_id=? ORDER BY created_at DESC",(session['user_id'],)).fetchall()
    result = []
    for cr in courses:
        lc = conn.execute("SELECT COUNT(*) FROM lectures WHERE course_id=?",(cr['id'],)).fetchone()[0]
        ec = conn.execute("SELECT COUNT(*) FROM enrollments WHERE course_id=?",(cr['id'],)).fetchone()[0]
        result.append({**dict(cr),'lecture_count':lc,'enrollment_count':ec})
    conn.close()
    return jsonify(result)

@app.route('/api/courses', methods=['POST'])
@educator_required
def create_course():
    data = request.json
    conn = get_db()
    cid = str(uuid.uuid4())
    conn.execute("INSERT INTO courses (id,title,description,category,difficulty,educator_id,educator_name,thumbnail_color) VALUES (?,?,?,?,?,?,?,?)",
                 (cid,data['title'],data.get('description',''),data.get('category','ML'),data.get('difficulty','beginner'),
                  session['user_id'],session['username'],data.get('thumbnail_color','#00D4FF')))
    conn.commit(); conn.close()
    return jsonify({'success':True,'id':cid})

@app.route('/api/courses/<course_id>', methods=['GET'])
@login_required
def get_course(course_id):
    conn = get_db()
    course = conn.execute("SELECT * FROM courses WHERE id=?",(course_id,)).fetchone()
    lectures = conn.execute("SELECT * FROM lectures WHERE course_id=? ORDER BY order_num",(course_id,)).fetchall()
    if not course: return jsonify({'error':'Not found'}),404
    completed = []
    if session.get('role')=='student':
        rows = conn.execute("SELECT lecture_id FROM completed_lectures WHERE student_id=?",(session['user_id'],)).fetchall()
        completed = [r['lecture_id'] for r in rows]
    conn.close()
    return jsonify({'course':dict(course),'lectures':[dict(l) for l in lectures],'completed':completed})

@app.route('/api/courses/<course_id>', methods=['PUT'])
@educator_required
def update_course(course_id):
    data = request.json
    conn = get_db()
    conn.execute("UPDATE courses SET title=?,description=?,category=?,difficulty=?,thumbnail_color=? WHERE id=? AND educator_id=?",
                 (data['title'],data.get('description',''),data.get('category','ML'),data.get('difficulty','beginner'),
                  data.get('thumbnail_color','#00D4FF'),course_id,session['user_id']))
    conn.commit(); conn.close()
    return jsonify({'success':True})

@app.route('/api/courses/<course_id>', methods=['DELETE'])
@educator_required
def delete_course(course_id):
    conn = get_db()
    conn.execute("DELETE FROM lectures WHERE course_id=?",(course_id,))
    conn.execute("DELETE FROM courses WHERE id=? AND educator_id=?",(course_id,session['user_id']))
    conn.commit(); conn.close()
    return jsonify({'success':True})

# ─── LECTURE API ──────────────────────────────────────────────────────────────
@app.route('/api/lectures/<lecture_id>', methods=['GET'])
@login_required
def get_lecture(lecture_id):
    conn = get_db()
    lecture = conn.execute("SELECT * FROM lectures WHERE id=?",(lecture_id,)).fetchone()
    if not lecture: return jsonify({'error':'Not found'}),404
    completed = conn.execute("SELECT 1 FROM completed_lectures WHERE student_id=? AND lecture_id=?",(session['user_id'],lecture_id)).fetchone()
    note = conn.execute("SELECT content FROM notes WHERE student_id=? AND lecture_id=? ORDER BY created_at DESC LIMIT 1",(session['user_id'],lecture_id)).fetchone()
    all_lecs = conn.execute("SELECT id,title FROM lectures WHERE course_id=? ORDER BY order_num",(lecture['course_id'],)).fetchall()
    ids = [l['id'] for l in all_lecs]
    idx = ids.index(lecture_id) if lecture_id in ids else 0
    conn.close()
    return jsonify({'lecture':dict(lecture),'completed':completed is not None,'note':note['content'] if note else '',
                    'prev_id':ids[idx-1] if idx>0 else None,'next_id':ids[idx+1] if idx<len(ids)-1 else None,
                    'all_lectures':[dict(l) for l in all_lecs]})

@app.route('/api/lectures', methods=['POST'])
@educator_required
def create_lecture():
    data = request.json
    conn = get_db()
    lid = str(uuid.uuid4())
    max_order = conn.execute("SELECT MAX(order_num) FROM lectures WHERE course_id=?",(data['course_id'],)).fetchone()[0] or 0
    conn.execute("INSERT INTO lectures (id,course_id,title,content,lecture_type,video_url,code_example,order_num,duration_mins) VALUES (?,?,?,?,?,?,?,?,?)",
                 (lid,data['course_id'],data['title'],data.get('content',''),data.get('lecture_type','text'),
                  data.get('video_url',''),data.get('code_example',''),max_order+1,data.get('duration_mins',15)))
    conn.commit(); conn.close()
    return jsonify({'success':True,'id':lid})

@app.route('/api/lectures/<lecture_id>', methods=['PUT'])
@educator_required
def update_lecture(lecture_id):
    data = request.json
    conn = get_db()
    conn.execute("UPDATE lectures SET title=?,content=?,lecture_type=?,video_url=?,code_example=?,duration_mins=? WHERE id=?",
                 (data['title'],data.get('content',''),data.get('lecture_type','text'),
                  data.get('video_url',''),data.get('code_example',''),data.get('duration_mins',15),lecture_id))
    conn.commit(); conn.close()
    return jsonify({'success':True})

@app.route('/api/lectures/<lecture_id>', methods=['DELETE'])
@educator_required
def delete_lecture(lecture_id):
    conn = get_db()
    conn.execute("DELETE FROM lectures WHERE id=?",(lecture_id,))
    conn.commit(); conn.close()
    return jsonify({'success':True})

# ─── ENROLLMENT & PROGRESS ───────────────────────────────────────────────────
@app.route('/api/enroll/<course_id>', methods=['POST'])
@login_required
def enroll(course_id):
    conn = get_db()
    try:
        conn.execute("INSERT INTO enrollments (id,student_id,course_id) VALUES (?,?,?)",
                     (str(uuid.uuid4()),session['user_id'],course_id))
        conn.commit()
    except sqlite3.IntegrityError: pass
    conn.close()
    return jsonify({'success':True})

@app.route('/api/complete_lecture/<lecture_id>', methods=['POST'])
@login_required
def complete_lecture(lecture_id):
    conn = get_db()
    try:
        conn.execute("INSERT INTO completed_lectures (id,student_id,lecture_id) VALUES (?,?,?)",
                     (str(uuid.uuid4()),session['user_id'],lecture_id))
        lec = conn.execute("SELECT course_id FROM lectures WHERE id=?",(lecture_id,)).fetchone()
        if lec:
            total = conn.execute("SELECT COUNT(*) FROM lectures WHERE course_id=?",(lec['course_id'],)).fetchone()[0]
            done = conn.execute("""SELECT COUNT(*) FROM completed_lectures cl JOIN lectures l ON cl.lecture_id=l.id
                                   WHERE cl.student_id=? AND l.course_id=?""",(session['user_id'],lec['course_id'])).fetchone()[0]
            conn.execute("UPDATE enrollments SET progress=? WHERE student_id=? AND course_id=?",
                         (int(done/total*100) if total else 0, session['user_id'], lec['course_id']))
        conn.commit()
    except sqlite3.IntegrityError: pass
    conn.close()
    return jsonify({'success':True})

@app.route('/api/save_note', methods=['POST'])
@login_required
def save_note():
    data = request.json
    conn = get_db()
    existing = conn.execute("SELECT id FROM notes WHERE student_id=? AND lecture_id=?",(session['user_id'],data['lecture_id'])).fetchone()
    if existing:
        conn.execute("UPDATE notes SET content=? WHERE id=?",(data['content'],existing['id']))
    else:
        conn.execute("INSERT INTO notes (id,student_id,lecture_id,content) VALUES (?,?,?,?)",
                     (str(uuid.uuid4()),session['user_id'],data['lecture_id'],data['content']))
    conn.commit(); conn.close()
    return jsonify({'success':True})

@app.route('/api/my_enrollments')
@login_required
def my_enrollments():
    conn = get_db()
    rows = conn.execute("""SELECT e.*,c.title,c.description,c.difficulty,c.thumbnail_color,c.educator_name
                           FROM enrollments e JOIN courses c ON e.course_id=c.id
                           WHERE e.student_id=? ORDER BY e.enrolled_at DESC""",(session['user_id'],)).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])

@app.route('/api/student_stats')
@login_required
def student_stats():
    conn = get_db()
    enrolled = conn.execute("SELECT COUNT(*) FROM enrollments WHERE student_id=?",(session['user_id'],)).fetchone()[0]
    completed = conn.execute("SELECT COUNT(*) FROM completed_lectures WHERE student_id=?",(session['user_id'],)).fetchone()[0]
    user = conn.execute("SELECT * FROM users WHERE id=?",(session['user_id'],)).fetchone()
    conn.close()
    return jsonify({'enrolled_courses':enrolled,'completed_lectures':completed,
                    'level':user['level'] if user else 'beginner','username':user['username'] if user else '',
                    'total_queries':user['total_queries'] if user else 0})

@app.route('/api/educator_stats')
@educator_required
def educator_stats():
    conn = get_db()
    courses = conn.execute("SELECT COUNT(*) FROM courses WHERE educator_id=?",(session['user_id'],)).fetchone()[0]
    lectures = conn.execute("SELECT COUNT(*) FROM lectures l JOIN courses c ON l.course_id=c.id WHERE c.educator_id=?",(session['user_id'],)).fetchone()[0]
    students = conn.execute("SELECT COUNT(DISTINCT e.student_id) FROM enrollments e JOIN courses c ON e.course_id=c.id WHERE c.educator_id=?",(session['user_id'],)).fetchone()[0]
    conn.close()
    return jsonify({'courses':courses,'lectures':lectures,'students':students,'username':session['username']})

# ─── AI API ──────────────────────────────────────────────────────────────────
def get_user_profile():
    if 'profile' not in session:
        session['profile']={'level':'beginner','topics_learned':[],'weak_topics':[],'strong_topics':[],'total_queries':0,'correct_attempts':0,'history':[]}
    return session['profile']

def update_profile(topic, success=True):
    profile = get_user_profile()
    profile['total_queries'] += 1
    if topic not in profile['topics_learned']: profile['topics_learned'].append(topic)
    if success:
        profile['correct_attempts'] += 1
        if topic not in profile['strong_topics']: profile['strong_topics'].append(topic)
        if topic in profile['weak_topics']: profile['weak_topics'].remove(topic)
    else:
        if topic not in profile['weak_topics']: profile['weak_topics'].append(topic)
    r = profile['correct_attempts'] / max(profile['total_queries'],1)
    if profile['total_queries']>5: profile['level']='advanced' if r>0.8 else ('intermediate' if r>0.5 else 'beginner')
    try:
        conn=get_db(); conn.execute("UPDATE users SET level=?,total_queries=?,correct_attempts=? WHERE id=?",(profile['level'],profile['total_queries'],profile['correct_attempts'],session.get('user_id','')))
        conn.commit(); conn.close()
    except: pass
    session['profile']=profile; session.modified=True

@app.route('/api/explain', methods=['POST'])
@login_required
def explain():
    data = request.json
    concept = data.get('concept', '')
    mode = data.get('mode', 'full')
    level = get_user_profile()['level']

    if mode == 'simple':
        prompt = f'''Explain the ML concept "{concept}" in the simplest possible way for a complete beginner.
Respond with ONLY a JSON object. Use \\n for newlines inside strings. No raw newlines inside string values.
{{"explanation":"simple 2-3 sentence plain English explanation","analogy":"a fun everyday life analogy that makes this concept clear","emoji_summary":"3-5 relevant emojis"}}'''

    elif mode == 'technical':
        prompt = f'''Give a deep technical explanation of "{concept}" in ML for an advanced practitioner.
Respond with ONLY a JSON object. Use \\n for newlines inside strings. No raw newlines inside string values.
{{"explanation":"in-depth technical explanation in 3-4 sentences","mathematics":"key mathematical foundations and formulas","implementation_notes":"key implementation tips and tricks","pitfalls":["common pitfall 1","common pitfall 2","common pitfall 3"]}}'''

    else:  # full
        prompt = f'''Explain the ML concept "{concept}" for a {level} level learner.
Respond with ONLY a JSON object. Use \\n for newlines inside strings. No raw newlines inside string values.
For the code_example field, write Python code on a single conceptual line using \\n between lines.

{{"title":"{concept}","simple_explanation":"1-2 plain English sentences","detailed_explanation":"3-4 paragraphs for {level} level learner. Use \\n\\n between paragraphs.","real_world_example":"one concrete real-world use case","formula":"math formula as plain text string, or null","key_points":["key point 1","key point 2","key point 3","key point 4"],"code_example":"import numpy as np\\nfrom sklearn.cluster import KMeans\\n\\n# Example code here\\nX = np.array([[1,2],[3,4]])\\nmodel = KMeans(n_clusters=2)\\nmodel.fit(X)","visual_description":"describe in words how to visualize this concept","difficulty":"beginner","related_topics":["related topic 1","related topic 2","related topic 3"],"quiz_question":"A good multiple choice question about {concept}?","quiz_options":["A) first option","B) second option","C) third option","D) fourth option"],"quiz_answer":"A"}}'''

    try:
        result = ask_groq_json(prompt)
        # Post-process: convert \\n back to real newlines in code_example only
        if 'code_example' in result and isinstance(result['code_example'], str):
            result['code_example'] = result['code_example'].replace('\\n', '\n').replace('\\t', '\t')
        p = get_user_profile()
        p['history'].append({'type': 'concept', 'topic': concept, 'time': datetime.now().isoformat()})
        if len(p['history']) > 50:
            p['history'] = p['history'][-50:]
        session['profile'] = p
        session.modified = True
        update_profile(concept)
        return jsonify({'success': True, 'data': result})
    except Exception as e:
        return jsonify({'success': False, 'error': f'AI parsing error: {str(e)}. Please try again.'})

@app.route('/api/generate_code', methods=['POST'])
@login_required
def generate_code():
    import re
    data  = request.json or {}
    query = data.get('query', '').strip()
    if not query:
        return jsonify({'success': False, 'error': 'Please enter a description of the code you want.'})
    level = get_user_profile().get('level', 'beginner')

    # ── Step 1: metadata JSON (NO code block inside) ──────────────
    meta_prompt = (
        f'You are an expert ML engineer. The user is at {level} level and wants to implement: "{query}"\n'
        'Respond with ONLY a valid JSON object. Use \\n for newlines inside strings. No code in this JSON.\n'
        'Required keys: title (string), explanation (string, 3-4 sentences), '
        'libraries_needed (array of strings), expected_output (string), '
        'variations (string), common_mistakes (array of strings).\n'
        'Example: {"title":"Linear Regression","explanation":"We fit a line...","libraries_needed":["numpy","sklearn"],'
        '"expected_output":"Prints MSE and coefficients","variations":"Try Ridge or Lasso","common_mistakes":["Not scaling features","Ignoring outliers"]}'
    )

    # ── Step 2: actual Python code (plain text, no JSON) ──────────
    code_prompt = (
        f'Write complete, well-commented Python code for: "{query}"\n'
        f'The user is at {level} level.\n'
        'Rules: Return ONLY raw Python code. Start with imports. No markdown fences. No JSON. No explanation text.'
    )

    try:
        meta      = ask_groq_json(meta_prompt)
        code_text = ask_groq(
            code_prompt,
            system="You are an expert Python ML engineer. Output ONLY raw Python code with no markdown, no explanation.",
            temperature=0.2
        )
        # Strip any accidental markdown fences
        code_text = re.sub(r'```python\s*', '', code_text.strip())
        code_text = re.sub(r'```',           '', code_text).strip()

        # Guarantee required keys exist
        meta.setdefault('title',           query.title())
        meta.setdefault('explanation',     'See code comments for details.')
        meta.setdefault('libraries_needed', [])
        meta.setdefault('expected_output', '')
        meta.setdefault('variations',      '')
        meta.setdefault('common_mistakes', [])
        meta['code'] = code_text

        update_profile(query)
        return jsonify({'success': True, 'data': meta})
    except Exception as e:
        return jsonify({'success': False, 'error': f'Code generation failed: {str(e)}'})


@app.route('/api/analyze_code', methods=['POST'])
@login_required
def analyze_code():
    import re
    data       = request.json or {}
    code_input = data.get('code', '').strip()
    if not code_input:
        return jsonify({'success': False, 'error': 'Please paste some Python code to analyze.'})

    # ── Step 1: analysis JSON (NO code inside the JSON) ───────────
    meta_prompt = (
        'You are an expert Python ML code reviewer.\n'
        'Analyze the following Python code and respond with ONLY a valid JSON object.\n'
        'Use \\n for newlines inside strings. Do NOT put code inside the JSON.\n'
        'Required keys: overall_assessment (string), score (integer 0-100), '
        'errors (array of objects with keys line, issue, fix), '
        'improvements (array of strings), explanation (string), '
        'best_practices (array of strings), complexity (string).\n'
        'If there are no errors use an empty array for errors.\n\n'
        'Code to analyze:\n'
        '"""\n'
        f'{code_input}\n'
        '"""'
    )

    # ── Step 2: optimised code (plain text) ───────────────────────
    opt_prompt = (
        'Rewrite the following Python ML code as a clean, optimised, well-commented version.\n'
        'Return ONLY the improved Python code. No markdown. No explanation. No JSON.\n\n'
        f'{code_input}'
    )

    try:
        meta     = ask_groq_json(meta_prompt)
        opt_code = ask_groq(
            opt_prompt,
            system="You are an expert Python ML engineer. Output ONLY clean optimised Python code.",
            temperature=0.2
        )
        # Strip accidental fences
        opt_code = re.sub(r'```python\s*', '', opt_code.strip())
        opt_code = re.sub(r'```',           '', opt_code).strip()

        # Guarantee required keys
        meta.setdefault('overall_assessment', 'Code reviewed successfully.')
        meta.setdefault('score',              70)
        meta.setdefault('errors',             [])
        meta.setdefault('improvements',       [])
        meta.setdefault('explanation',        '')
        meta.setdefault('best_practices',     [])
        meta.setdefault('complexity',         '')
        # Coerce score to int in case model returns a string
        try:
            meta['score'] = int(meta['score'])
        except Exception:
            meta['score'] = 70
        meta['optimized_code'] = opt_code

        return jsonify({'success': True, 'data': meta})
    except Exception as e:
        return jsonify({'success': False, 'error': f'Code analysis failed: {str(e)}'})

@app.route('/api/generate_diagram', methods=['POST'])
@login_required
def generate_diagram():
    data=request.json; concept=data.get('concept',''); vd=data.get('visual_description','')
    prompt=f'''Create a diagram data structure for the ML concept "{concept}".
Visual description hint: {vd}

Return ONLY valid JSON, no markdown fences. Use x values between 80-720 and y values between 60-360:
{{"type":"flowchart","title":"diagram title","nodes":[{{"id":"1","label":"Node Label","x":200,"y":150,"color":"#00D4FF"}},{{"id":"2","label":"Node 2","x":400,"y":150,"color":"#7C3AED"}}],"edges":[{{"from":"1","to":"2","label":"connection"}}],"description":"what this diagram illustrates"}}

Create at least 4 nodes and meaningful connections that explain {concept} visually.'''
    try:
        result = ask_groq_json(prompt)
        return jsonify({'success':True,'data':result})
    except Exception as e: return jsonify({'success':False,'error':str(e)})

@app.route('/api/chat', methods=['POST'])
@login_required
def chat():
    data=request.json; message=data.get('message',''); history=data.get('history',[]); p=get_user_profile()
    system = f"You are LearnSphere, a friendly and expert ML tutor. The student is at {p['level']} level. Topics they've studied: {', '.join(p['topics_learned'][-5:]) or 'none yet'}. Give concise, helpful, encouraging answers. Use examples when helpful."
    # Build messages list with history
    messages = [{"role": "system", "content": system}]
    for h in history[-6:]:
        messages.append({"role": h['role'], "content": h['content']})
    messages.append({"role": "user", "content": message})
    try:
        response = groq_client.chat.completions.create(
            model=GROQ_MODEL, messages=messages, temperature=0.7, max_tokens=1024
        )
        return jsonify({'success':True,'response':response.choices[0].message.content})
    except Exception as e: return jsonify({'success':False,'error':str(e)})

@app.route('/api/profile')
@login_required
def get_profile(): return jsonify(get_user_profile())

@app.route('/api/quiz_check', methods=['POST'])
@login_required
def quiz_check():
    data=request.json; ans=data.get('answer',''); correct=data.get('correct',''); topic=data.get('topic','')
    ok=ans.upper()==correct.upper(); update_profile(topic,ok)
    return jsonify({'correct':ok,'message':'Correct! Great job! 🎉' if ok else f'Not quite. Answer is {correct}.'})

@app.route('/api/suggest_topics')
@login_required
def suggest_topics():
    p=get_user_profile()
    prompt=f'''Suggest 6 machine learning topics for a {p["level"]} level learner.
They have already studied: {", ".join(p["topics_learned"][-10:]) or "nothing yet"}.
Suggest topics that build naturally on what they know.
Return ONLY valid JSON, no markdown fences:
{{"suggestions":[{{"topic":"topic name","reason":"why this topic is good to learn next","difficulty":"beginner or intermediate or advanced"}},{{"topic":"topic2","reason":"reason","difficulty":"difficulty"}}]}}'''
    try:
        result = ask_groq_json(prompt)
        return jsonify({'success':True,'data':result})
    except Exception as e: return jsonify({'success':False,'error':str(e)})

@app.route('/api/audio_script', methods=['POST'])
@login_required
def audio_script():
    data=request.json; concept=data.get('concept',''); exp=data.get('explanation','')
    prompt=f'''Write a natural, engaging audio narration script that teaches the ML concept "{concept}".
Base it on this explanation: {exp[:500]}
The script should sound natural when spoken aloud — conversational, clear, 100-150 words.
Return ONLY valid JSON, no markdown fences:
{{"script":"the complete narration text that sounds natural when read aloud","duration_estimate":"estimated X seconds"}}'''
    try:
        result = ask_groq_json(prompt)
        return jsonify({'success':True,'data':result})
    except Exception as e: return jsonify({'success':False,'error':str(e)})

@app.route('/api/ai_explain_lecture', methods=['POST'])
@login_required
def ai_explain_lecture():
    data=request.json; title=data.get('title',''); content=data.get('content','')[:600]; p=get_user_profile()
    prompt=f'''You are tutoring a {p["level"]} level student who is reading a lecture titled "{title}".
Here is a summary of the lecture content: {content}

Give a helpful, encouraging 3-4 sentence explanation in plain English. 
Be conversational and make it easy to understand. Mention one concrete example if helpful.'''
    try:
        response = ask_groq(prompt, system="You are a friendly, expert ML tutor who explains things clearly and encouragingly.")
        return jsonify({'success':True,'response':response})
    except Exception as e: return jsonify({'success':False,'error':str(e)})


# ─── LEARNING DNA ROUTES ─────────────────────────────────────────────────────

@app.route('/dna')
@login_required
def dna_page():
    return render_template('dna.html')

@app.route('/battle')
@login_required
def battle_page():
    return render_template('battle.html')

@app.route('/api/dna/update', methods=['POST'])
@login_required
def update_dna():
    """Update learning DNA after any interaction"""
    data = request.json
    concept   = data.get('concept', '')
    correct   = data.get('correct', True)
    resp_ms   = data.get('response_ms', 3000)
    style     = data.get('style', 'balanced')
    uid       = session['user_id']
    conn      = get_db()

    existing = conn.execute(
        "SELECT * FROM learning_dna WHERE user_id=? AND concept=?", (uid, concept)
    ).fetchone()

    now = datetime.now().isoformat()

    if existing:
        attempts = existing['attempts'] + 1
        correct_count = existing['correct'] + (1 if correct else 0)
        # SM-2 spaced repetition
        ef = existing['ease_factor']
        q  = 5 if correct and resp_ms < 3000 else (4 if correct else 2)
        ef_new = max(1.3, ef + 0.1 - (5 - q) * (0.08 + (5 - q) * 0.02))
        interval = existing['interval_days']
        if q >= 3:
            if interval == 1:
                new_interval = 6
            else:
                new_interval = round(interval * ef_new)
        else:
            new_interval = 1
        from datetime import timedelta
        next_rev = (datetime.now() + timedelta(days=new_interval)).isoformat()
        avg_ms = round((existing['avg_response_ms'] * (attempts - 1) + resp_ms) / attempts)

        conn.execute("""UPDATE learning_dna
            SET attempts=?, correct=?, avg_response_ms=?, last_seen=?,
                next_review=?, ease_factor=?, interval_days=?, style_pref=?
            WHERE user_id=? AND concept=?""",
            (attempts, correct_count, avg_ms, now, next_rev, ef_new, new_interval, style, uid, concept))
    else:
        from datetime import timedelta
        next_rev = (datetime.now() + timedelta(days=1)).isoformat()
        conn.execute("""INSERT INTO learning_dna
            (id,user_id,concept,attempts,correct,avg_response_ms,last_seen,next_review,ease_factor,interval_days,style_pref)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (str(uuid.uuid4()), uid, concept, 1, 1 if correct else 0,
             resp_ms, now, next_rev, 2.5, 1, style))

    conn.commit(); conn.close()
    return jsonify({'success': True})


@app.route('/api/dna/profile')
@login_required
def get_dna_profile():
    uid  = session['user_id']
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM learning_dna WHERE user_id=? ORDER BY last_seen DESC", (uid,)
    ).fetchall()
    now  = datetime.now()

    dna = []
    for r in rows:
        accuracy = round(r['correct'] / r['attempts'] * 100) if r['attempts'] else 0
        speed_label = (
            'Fast Learner' if r['avg_response_ms'] < 3000 else
            'Average'      if r['avg_response_ms'] < 7000 else
            'Takes Time'
        )
        # Decay: days since last seen
        days_ago = 0
        if r['last_seen']:
            try:
                last = datetime.fromisoformat(r['last_seen'])
                days_ago = (now - last).days
            except Exception:
                pass

        # Forgetting curve: retention = e^(-days/interval)
        import math
        retention = round(100 * math.exp(-days_ago / max(r['interval_days'], 1)))
        retention = max(5, min(100, retention))

        due_review = False
        if r['next_review']:
            try:
                due_review = datetime.fromisoformat(r['next_review']) <= now
            except Exception:
                pass

        dna.append({
            'concept':       r['concept'],
            'attempts':      r['attempts'],
            'accuracy':      accuracy,
            'speed_label':   speed_label,
            'avg_ms':        r['avg_response_ms'],
            'last_seen':     r['last_seen'],
            'next_review':   r['next_review'],
            'retention':     retention,
            'due_review':    due_review,
            'interval_days': r['interval_days'],
            'ease_factor':   round(r['ease_factor'], 2),
            'style_pref':    r['style_pref'],
            'days_ago':      days_ago,
        })

    # Compute summary stats
    total_concepts   = len(dna)
    mastered         = [d for d in dna if d['accuracy'] >= 80]
    weak             = [d for d in dna if d['accuracy'] < 60]
    due_now          = [d for d in dna if d['due_review']]
    avg_retention    = round(sum(d['retention'] for d in dna) / total_concepts) if dna else 0
    preferred_style  = max(set(d['style_pref'] for d in dna), key=lambda x: sum(1 for d in dna if d['style_pref']==x)) if dna else 'balanced'

    conn.close()
    return jsonify({
        'dna': dna,
        'summary': {
            'total_concepts':  total_concepts,
            'mastered_count':  len(mastered),
            'weak_count':      len(weak),
            'due_review_count':len(due_now),
            'avg_retention':   avg_retention,
            'preferred_style': preferred_style,
        }
    })


@app.route('/api/dna/predict_decay')
@login_required
def predict_decay():
    """Return concepts at risk of being forgotten"""
    uid  = session['user_id']
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM learning_dna WHERE user_id=? ORDER BY next_review ASC", (uid,)
    ).fetchall()
    now  = datetime.now()

    import math
    predictions = []
    for r in rows:
        days_ago = 0
        if r['last_seen']:
            try:
                days_ago = (now - datetime.fromisoformat(r['last_seen'])).days
            except Exception:
                pass
        retention = round(100 * math.exp(-days_ago / max(r['interval_days'], 1)))
        retention = max(5, min(100, retention))

        days_until_forget = 0
        # days until retention drops below 50%
        import math as m
        if r['interval_days'] > 0:
            days_until_forget = max(0, round(r['interval_days'] * m.log(2) - days_ago))

        predictions.append({
            'concept':           r['concept'],
            'retention':         retention,
            'days_until_forget': days_until_forget,
            'urgency':           'critical' if retention < 30 else ('warning' if retention < 60 else 'good'),
            'last_seen':         r['last_seen'],
        })

    predictions.sort(key=lambda x: x['retention'])
    conn.close()
    return jsonify({'predictions': predictions[:10]})


# ─── BATTLE MODE ROUTES ───────────────────────────────────────────────────────

@app.route('/api/battle/question', methods=['POST'])
@login_required
def battle_question():
    """Generate a quiz question for battle mode"""
    data       = request.json
    topic      = data.get('topic', 'Machine Learning')
    difficulty = data.get('difficulty', 'medium')
    q_num      = data.get('question_num', 1)

    prompt = f"""Generate question #{q_num} for a Machine Learning quiz competition.
Topic: {topic}
Difficulty: {difficulty}

Return ONLY valid JSON, no markdown:
{{"question":"the question text","options":["A) option1","B) option2","C) option3","D) option4"],"answer":"A","explanation":"brief explanation of why this is correct","difficulty":"{difficulty}","points":{10 if difficulty=='easy' else (20 if difficulty=='medium' else 30)}}}"""

    try:
        result = ask_groq_json(prompt)
        return jsonify({'success': True, 'data': result})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


@app.route('/api/battle/save_score', methods=['POST'])
@login_required
def save_battle_score():
    data = request.json
    conn = get_db()
    conn.execute(
        "INSERT INTO battle_scores (id,user_id,username,score,ai_score,topic) VALUES (?,?,?,?,?,?)",
        (str(uuid.uuid4()), session['user_id'], session['username'],
         data.get('score', 0), data.get('ai_score', 0), data.get('topic', 'ML'))
    )
    conn.commit(); conn.close()
    return jsonify({'success': True})


@app.route('/api/battle/leaderboard')
@login_required
def battle_leaderboard():
    conn  = get_db()
    rows  = conn.execute("""
        SELECT username, MAX(score) as best_score, COUNT(*) as games_played,
               SUM(CASE WHEN score > ai_score THEN 1 ELSE 0 END) as wins
        FROM battle_scores
        GROUP BY user_id
        ORDER BY best_score DESC LIMIT 10""").fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@app.route('/api/battle/my_history')
@login_required
def battle_history():
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM battle_scores WHERE user_id=? ORDER BY played_at DESC LIMIT 10",
        (session['user_id'],)
    ).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])

if __name__=='__main__':
    init_db()
    app.run(debug=True,port=5000)

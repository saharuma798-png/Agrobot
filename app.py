from flask import Flask, render_template, request, jsonify, session, redirect, url_for
from flask_sqlalchemy import SQLAlchemy
from PIL import Image
from werkzeug.security import generate_password_hash, check_password_hash
from dotenv import load_dotenv
from io import BytesIO
import base64
import os
import time
import requests


try:
    from groq import Groq
except ImportError:
    Groq = None

try:
    import google.generativeai as genai
except ImportError:
    genai = None

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "change-this-secret-key")

# ======================
# CONFIGURATION
# ======================
WEATHER_KEY = os.getenv("WEATHER_KEY")
BING_KEY = os.getenv("BING_KEY")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")


GEMINI_API_KEYS = [
    key.strip()
    for key in os.getenv("GEMINI_API_KEYS", "").split(",")
    if key.strip()
]
current_gemini_key_index = 0

groq_client = Groq(api_key=GROQ_API_KEY) if (Groq and GROQ_API_KEY) else None

# ======================
# DATABASE
# ======================
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///farmers.db"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
db = SQLAlchemy(app)


class Farmer(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50))
    crop = db.Column(db.String(50))
    soil = db.Column(db.String(50))


class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    farmer_name = db.Column(db.String(100))


with app.app_context():
    db.create_all()


# ======================
# AUTHENTICATION HELPER
# ======================
def require_login():
    if not session.get("logged_in"):
        return jsonify({"reply": "Please log in to use AGROBOT.AI."}), 401
    return None


# ======================
# AI PROVIDERS
# ======================
def _gemini_model():
    global current_gemini_key_index
    if not genai or not GEMINI_API_KEYS:
        return None
    genai.configure(api_key=GEMINI_API_KEYS[current_gemini_key_index])
    return genai.GenerativeModel("gemini-1.5-flash")


def generate_text(prompt):
    
    global current_gemini_key_index

  
    if groq_client:
        try:
            completion = groq_client.chat.completions.create(
                model=os.getenv("GROQ_TEXT_MODEL", "openai/gpt-oss-20b"),
                messages=[{"role": "user", "content": prompt}],
                temperature=0.7,
                max_tokens=1024,
                stream=False,
            )
            return completion.choices[0].message.content
        except Exception as exc:
            print("GROQ TEXT ERROR:", exc)

   
    for _ in range(len(GEMINI_API_KEYS)):
        try:
            model = _gemini_model()
            if model is None:
                break
            response = model.generate_content(prompt)
            return response.text
        except Exception as exc:
            print("GEMINI TEXT ERROR:", exc)
            current_gemini_key_index = (current_gemini_key_index + 1) % len(GEMINI_API_KEYS)
            time.sleep(0.5)

    return "⚠ Cloud AI service is temporarily unavailable. Configure GROQ_API_KEY or GEMINI_API_KEYS."


def generate_image_text(prompt, img):
    
    global current_gemini_key_index

    # Convert the uploaded image to JPEG/base64 for Groq's vision request.
    if groq_client:
        try:
            buffered = BytesIO()
            img.save(buffered, format="JPEG")
            img_str = base64.b64encode(buffered.getvalue()).decode("utf-8")
            completion = groq_client.chat.completions.create(
                model=os.getenv("GROQ_VISION_MODEL", "qwen/qwen3.6-27b"),
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt},
                            {
                                "type": "image_url",
                                "image_url": {"url": f"data:image/jpeg;base64,{img_str}"},
                            },
                        ],
                    }
                ],
                temperature=0.2,
                max_tokens=1024,
                stream=False,
            )
            return completion.choices[0].message.content
        except Exception as exc:
            print("GROQ VISION ERROR:", exc)

    # Gemini vision fallback.
    for _ in range(len(GEMINI_API_KEYS)):
        try:
            model = _gemini_model()
            if model is None:
                break
            response = model.generate_content([prompt, img])
            return response.text
        except Exception as exc:
            print("GEMINI VISION ERROR:", exc)
            current_gemini_key_index = (current_gemini_key_index + 1) % len(GEMINI_API_KEYS)
            time.sleep(0.5)

    return "⚠ Cloud Vision processing failed. Configure an AI provider."



def safe_generate(prompt):
    if isinstance(prompt, list):
        if len(prompt) == 2 and isinstance(prompt[1], Image.Image):
            return generate_image_text(prompt[0], prompt[1])
    return generate_text(prompt)


# ======================
# WEATHER & AGRICULTURE
# ======================
def advisory_engine(desc):
    desc = desc.lower()
    if "rain" in desc:
        return "⚠ Rain expected — delay fertilizer application."
    if "clear" in desc:
        return "Good time for irrigation."
    return ""


def get_weather(city="Kolkata,IN"):
    if not WEATHER_KEY:
        return "⚠ Weather API key missing."
    try:
        url = f"https://api.openweathermap.org/data/2.5/weather?q={city}&appid={WEATHER_KEY}&units=metric"
        res = requests.get(url, timeout=5).json()
        if "main" not in res:
            return "Weather unavailable."
        temp = res["main"]["temp"]
        desc = res["weather"][0]["description"]
        return f"Weather in {city}: {temp}°C, {desc}\n{advisory_engine(desc)}"
    except Exception as exc:
        print("WEATHER ERROR:", exc)
        return "⚠ Weather service unavailable."


def get_weather_by_coords(lat, lon):
    if not WEATHER_KEY:
        return "⚠ Weather API key missing."
    try:
        url = f"https://api.openweathermap.org/data/2.5/weather?lat={lat}&lon={lon}&appid={WEATHER_KEY}&units=metric"
        res = requests.get(url, timeout=5).json()
        if "main" not in res:
            return "Weather unavailable."
        temp = res["main"]["temp"]
        desc = res["weather"][0]["description"]
        return f"Temp: {temp}°C | {desc}\n{advisory_engine(desc)}"
    except Exception as exc:
        print("WEATHER COORDS ERROR:", exc)
        return "⚠ Weather service unavailable."


def crop_calendar(crop):
    calendars = {
        "rice": "Rice: Sowing Jun–Jul | Harvest Oct–Nov",
        "wheat": "Wheat: Sowing Oct–Nov | Harvest Mar–Apr",
        "maize": "Maize: Sowing Jun–Jul | Harvest Sep–Oct",
    }
    return calendars.get(crop.lower(), "Calendar unavailable.")


def fertilizer_advice(crop):
    rules = {
        "rice": "Use NPK 10:26:26 — 50kg/acre",
        "wheat": "Use Urea + DAP combination",
        "maize": "Apply nitrogen-rich fertilizer",
    }
    return rules.get(crop.lower(), "No fertilizer data.")


def extract_crop(msg):
    for crop in ["rice", "wheat", "maize"]:
        if crop in msg:
            return crop
    return None


def government_schemes():
    return """📜 Government Schemes:
• PM-KISAN: ₹6000/year support
• Soil Health Card Scheme
• PMFBY (Crop Insurance)
• Kisan Credit Card

Visit nearest agriculture office for full details."""


def search_disease(symptoms):
    if not BING_KEY:
        return "Leaf Disease"
    try:
        url = "https://api.bing.microsoft.com/v7.0/search"
        headers = {"Ocp-Apim-Subscription-Key": BING_KEY}
        params = {"q": f"plant leaf disease {symptoms}"}
        res = requests.get(url, headers=headers, params=params, timeout=5).json()
        results = res.get("webPages", {}).get("value", [])
        for result in results:
            title = result.get("name", "").lower()
            if "blight" in title:
                return "Blight Disease"
            if "leaf spot" in title:
                return "Leaf Spot Disease"
            if "rust" in title:
                return "Rust Disease"
        return "Leaf Disease"
    except Exception as exc:
        print("DISEASE SEARCH ERROR:", exc)
        return "Unknown Disease"


# ======================
# ROUTES: AUTHENTICATION
# ======================
@app.route("/")
def index():
    if session.get("logged_in"):
        return redirect(url_for("agrobot"))
    return render_template("login.html")


@app.route("/login", methods=["POST"])
def login():
    try:
        data = request.get_json() or {}
        username = data.get("username", "").strip()
        password = data.get("password", "")
        if not username or not password:
            return jsonify({"success": False, "message": "Please enter both username and password."}), 400

        user = User.query.filter_by(username=username).first()
        if not user or not check_password_hash(user.password_hash, password):
            return jsonify({"success": False, "message": "Invalid username or password."}), 401

        session.clear()
        session["logged_in"] = True
        session["user_id"] = user.id
        session["username"] = user.username
        session["farmer_name"] = user.farmer_name or user.username
        return jsonify({"success": True, "redirect": url_for("agrobot")})
    except Exception as exc:
        print("LOGIN ERROR:", exc)
        return jsonify({"success": False, "message": "Server issue. Please try again."}), 500


@app.route("/register", methods=["POST"])
def register():
    try:
        data = request.get_json() or {}
        username = data.get("username", "").strip()
        password = data.get("password", "")
        first_name = data.get("firstName", "").strip()
        last_name = data.get("lastName", "").strip()

        if not username or not password or not first_name:
            return jsonify({"success": False, "message": "Username, password and first name are required."}), 400
        if len(password) < 6:
            return jsonify({"success": False, "message": "Password must contain at least 6 characters."}), 400
        if User.query.filter_by(username=username).first():
            return jsonify({"success": False, "message": "That username is already registered."}), 409

        farmer_name = f"{first_name} {last_name}".strip()
        user = User(
            username=username,
            password_hash=generate_password_hash(password),
            farmer_name=farmer_name,
        )
        db.session.add(user)
        db.session.commit()
        return jsonify({"success": True, "message": "Account created successfully."})
    except Exception as exc:
        db.session.rollback()
        print("REGISTRATION ERROR:", exc)
        return jsonify({"success": False, "message": "Registration failed. Please try again."}), 500


@app.route("/agrobot")
def agrobot():
    if not session.get("logged_in"):
        return redirect(url_for("index"))
    return render_template("index.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("index"))


# ======================
# ROUTES: AGROBOT FEATURES
# ======================
@app.route("/chat", methods=["POST"])
def chat():
    auth_error = require_login()
    if auth_error:
        return auth_error
    try:
        data = request.get_json() or {}
        msg = data.get("message", "").lower()
        crop = extract_crop(msg)

        if "weather" in msg:
            return jsonify({"reply": get_weather()})
        if "fertilizer" in msg:
            return jsonify({"reply": fertilizer_advice(crop) if crop else "🌾 Please specify a crop (rice, wheat, maize)."})
        if "calendar" in msg or "crop" in msg:
            return jsonify({"reply": crop_calendar(crop) if crop else "🌾 Please specify a crop."})
        if "scheme" in msg or "government" in msg:
            return jsonify({"reply": government_schemes()})

        return jsonify({"reply": generate_text(msg)})
    except Exception as exc:
        print("CHAT ERROR:", exc)
        return jsonify({"reply": "⚠ Server issue while processing chat."}), 500


@app.route("/weather_coords", methods=["POST"])
def weather_coords():
    auth_error = require_login()
    if auth_error:
        return auth_error
    try:
        data = request.get_json() or {}
        return jsonify({"reply": get_weather_by_coords(data["lat"], data["lon"])})
    except Exception:
        return jsonify({"reply": "⚠ Invalid location data."}), 400


@app.route("/detect_disease", methods=["POST"])
def detect_disease():
    auth_error = require_login()
    if auth_error:
        return auth_error
    try:
        file = request.files.get("image")
        if not file:
            return jsonify({"reply": "No image uploaded."}), 400

        img = Image.open(file).convert("RGB")
        symptom_prompt = "Look at this plant leaf and list 3–5 visible symptoms of disease concisely."
        symptoms = generate_image_text(symptom_prompt, img)
        if "⚠" in symptoms:
            return jsonify({"reply": symptoms}), 500

        disease = search_disease(symptoms)
        final_prompt = (
            f"Symptoms: {symptoms}\nDisease: {disease}\n"
            "Give a very brief cause, treatment, and prevention plan."
        )
        reply = generate_text(final_prompt)
        return jsonify({"symptoms": symptoms, "disease": disease, "reply": reply})
    except Exception as exc:
        print("IMAGE ERROR:", exc)
        return jsonify({"reply": "⚠ Image processing failed."}), 500


@app.route("/save_profile", methods=["POST"])
def save_profile():
    auth_error = require_login()
    if auth_error:
        return auth_error
    try:
        data = request.get_json() or {}
        farmer = Farmer(
            name=data["name"],
            crop=data["crop"],
            soil=data["soil"],
        )
        db.session.add(farmer)
        db.session.commit()
        return jsonify({"reply": "Profile saved!"})
    except Exception as exc:
        db.session.rollback()
        print("PROFILE ERROR:", exc)
        return jsonify({"reply": "Unable to save profile."}), 400


if __name__ == "__main__":
    with app.app_context():
        db.create_all()
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port, debug=False)

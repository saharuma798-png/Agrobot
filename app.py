from flask import Flask, render_template, request, jsonify
import requests
import os
import base64
from io import BytesIO
from flask_sqlalchemy import SQLAlchemy
from PIL import Image
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)

app.secret_key = os.getenv(
    "SECRET_KEY",
    "fallback_agroboat_secret"
)

WEATHER_KEY = os.getenv("WEATHER_KEY")
BING_KEY = os.getenv("BING_KEY")


# ======================
# DATABASE SETUP
# ======================

app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///farmers.db"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)


class Farmer(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50))
    crop = db.Column(db.String(50))
    soil = db.Column(db.String(50))


with app.app_context():
    db.create_all()


# ======================
# LOCAL AI FUNCTIONS
# OLLAMA
# ======================

def generate_text(prompt):
    """
    Uses the local Llama 3.2 1B model
    for text generation.
    """

    try:
        url = "http://localhost:11434/api/generate"

        payload = {
            "model": "llama3.2:1b",
            "prompt": str(prompt),
            "stream": False
        }

        res = requests.post(
            url,
            json=payload,
            timeout=120
        )

        return res.json().get(
            "response",
            "⚠ Local AI error."
        )

    except requests.exceptions.ConnectionError:
        return (
            "⚠ Ollama is not running on your computer. "
            "Please open the Ollama app."
        )

    except requests.exceptions.Timeout:
        return "⚠ Ollama request timed out."

    except Exception as e:
        print("LOCAL AI ERROR:", e)
        return "⚠ AI error."


def generate_image_text(prompt, img):
    """
    Uses the local Llava model
    for image analysis.
    """

    try:

        # Convert image to JPEG
        buffered = BytesIO()

        img.save(
            buffered,
            format="JPEG"
        )

        # Convert image to Base64
        img_str = base64.b64encode(
            buffered.getvalue()
        ).decode("utf-8")

        url = "http://localhost:11434/api/generate"

        payload = {
            "model": "llava",
            "prompt": prompt,
            "stream": False,
            "images": [img_str]
        }

        res = requests.post(
            url,
            json=payload,
            timeout=120
        )

        return res.json().get(
            "response",
            "⚠ Local Vision error."
        )

    except requests.exceptions.ConnectionError:
        return (
            "⚠ Ollama is not running on your computer."
        )

    except requests.exceptions.Timeout:
        return "⚠ Ollama vision request timed out."

    except Exception as e:
        print("LOCAL VISION ERROR:", e)
        return "⚠ Vision processing failed."


# ======================
# WEATHER & UTILITIES
# ======================

def advisory_engine(desc):

    desc = desc.lower()

    if "rain" in desc:
        return (
            "⚠ Rain expected — "
            "delay fertilizer application."
        )

    if "clear" in desc:
        return "Good time for irrigation."

    return ""


def get_weather(city="Kolkata,IN"):

    if not WEATHER_KEY:
        return "⚠ Weather API key missing in .env."

    try:

        url = (
            "https://api.openweathermap.org/data/2.5/weather"
            f"?q={city}&appid={WEATHER_KEY}&units=metric"
        )

        res = requests.get(
            url,
            timeout=5
        ).json()

        if "main" not in res:
            return "Weather unavailable."

        temp = res["main"]["temp"]

        desc = res["weather"][0]["description"]

        return (
            f"Weather in {city}: {temp}°C, {desc}\n"
            f"{advisory_engine(desc)}"
        )

    except Exception as e:

        print("WEATHER ERROR:", e)

        return "⚠ Weather service unavailable."


def crop_calendar(crop):

    calendars = {

        "rice":
            "Rice: Sowing Jun–Jul | Harvest Oct–Nov",

        "wheat":
            "Wheat: Sowing Oct–Nov | Harvest Mar–Apr",

        "maize":
            "Maize: Sowing Jun–Jul | Harvest Sep–Oct"
    }

    return calendars.get(
        crop.lower(),
        "Calendar unavailable."
    )


def fertilizer_advice(crop):

    rules = {

        "rice":
            "Use NPK 10:26:26 — 50kg/acre",

        "wheat":
            "Use Urea + DAP combination",

        "maize":
            "Apply nitrogen-rich fertilizer"
    }

    return rules.get(
        crop.lower(),
        "No fertilizer data."
    )


def extract_crop(msg):

    for c in [
        "rice",
        "wheat",
        "maize"
    ]:

        if c in msg:
            return c

    return None


def government_schemes():

    return """📜 Government Schemes:

• PM-KISAN: ₹6000/year support
• Soil Health Card Scheme
• PMFBY (Crop Insurance)
• Kisan Credit Card"""


def search_disease(symptoms):

    if not BING_KEY:
        return "Leaf Disease"

    try:

        url = (
            "https://api.bing.microsoft.com/v7.0/search"
        )

        res = requests.get(

            url,

            headers={
                "Ocp-Apim-Subscription-Key":
                    BING_KEY
            },

            params={
                "q":
                    f"plant leaf disease {symptoms}"
            },

            timeout=5

        ).json()

        results = (
            res
            .get("webPages", {})
            .get("value", [])
        )

        for r in results:

            title = r["name"].lower()

            if "blight" in title:
                return "Blight Disease"

            if "leaf spot" in title:
                return "Leaf Spot Disease"

            if "rust" in title:
                return "Rust Disease"

        return "Leaf Disease"

    except Exception as e:

        print("DISEASE SEARCH ERROR:", e)

        return "Unknown Disease"


# ======================
# ROUTES
# ======================

# ======================
# LOGIN PAGE
# ======================

@app.route("/")
def index():

    return render_template(
        "login.html"
    )


# ======================
# LOGIN ROUTE
# ======================

@app.route("/login")
def login():

    return render_template(
        "login.html"
    )


# ======================
# DASHBOARD ROUTE
# ======================

@app.route("/dashboard")
def dashboard():

    return render_template(
        "index.html"
    )


# ======================
# CHAT ROUTE
# ======================

@app.route(
    "/chat",
    methods=["POST"]
)
def chat():

    try:

        data = request.get_json()

        if not data:

            return jsonify({
                "reply":
                    "⚠ No message received."
            }), 400

        msg = data.get(
            "message",
            ""
        ).lower()

        crop = extract_crop(msg)

        # Weather
        if "weather" in msg:

            return jsonify({
                "reply":
                    get_weather()
            })

        # Fertilizer
        if "fertilizer" in msg:

            return jsonify({

                "reply":
                    fertilizer_advice(crop)
                    if crop
                    else
                    "🌾 Please specify a crop "
                    "(rice, wheat, maize)."
            })

        # Crop calendar
        if (
            "calendar" in msg
            or "crop" in msg
        ):

            return jsonify({

                "reply":
                    crop_calendar(crop)
                    if crop
                    else
                    "🌾 Please specify a crop."
            })

        # Government schemes
        if (
            "scheme" in msg
            or "government" in msg
        ):

            return jsonify({

                "reply":
                    government_schemes()
            })

        # Local Llama
        reply = generate_text(msg)

        return jsonify({
            "reply": reply
        })

    except Exception as e:

        print(
            "CHAT ERROR:",
            e
        )

        return jsonify({

            "reply":
                "⚠ Server issue while "
                "processing chat."
        }), 500


# ======================
# DISEASE DETECTION
# ======================

@app.route(
    "/detect_disease",
    methods=["POST"]
)
def detect_disease():

    try:

        file = request.files.get(
            "image"
        )

        if not file:

            return jsonify({

                "reply":
                    "No image uploaded."

            }), 400

        # Open uploaded image
        img = Image.open(
            file
        ).convert("RGB")

        symptom_prompt = (
            "Look at this plant leaf and "
            "list 3 visible symptoms of "
            "disease concisely."
        )

        # Ask Llava
        symptoms = generate_image_text(
            symptom_prompt,
            img
        )

        if "⚠" in symptoms:

            return jsonify({

                "reply":
                    symptoms

            }), 500

        # Search disease
        disease = search_disease(
            symptoms
        )

        # Final AI prompt
        final_prompt = f"""
Symptoms: {symptoms}

Disease: {disease}

Give a very brief cause, treatment,
and prevention plan.
"""

        # Ask Llama
        reply = generate_text(
            final_prompt
        )

        return jsonify({

            "symptoms":
                symptoms,

            "disease":
                disease,

            "reply":
                reply
        })

    except Exception as e:

        print(
            "IMAGE ERROR:",
            e
        )

        return jsonify({

            "reply":
                "⚠ Image processing failed."
        }), 500


# ======================
# RUN FLASK
# ======================

if __name__ == "__main__":

    port = int(
        os.environ.get(
            "PORT",
            10000
        )
    )

    app.run(

        host="0.0.0.0",

        port=port,

        debug=False
    )
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

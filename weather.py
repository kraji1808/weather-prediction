
import os
import smtplib
import sys
from email.message import EmailMessage

# Ensure Windows terminal doesn't crash when printing emojis or unicode city names
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import requests
from flask import Flask, jsonify, request

app = Flask(__name__)

# =========================================================================
# CONFIGURATION
# =========================================================================

# --- Weather API (OpenWeatherMap) ---
# If you have an OpenWeatherMap API key, put it here.
# If left as "YOUR_WEATHER_API_KEY", it automatically uses the free live
# weather service without requiring any API key!
WEATHER_API_KEY = os.getenv("WEATHER_API_KEY", "YOUR_WEATHER_API_KEY")
WEATHER_API_URL = "https://api.openweathermap.org/data/2.5/weather"

# --- Gmail SMTP Configuration ---
SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 587

GMAIL_USERNAME = os.getenv("GMAIL_USERNAME", "thahrinah05@gmail.com")
# Clean app password (strips spaces)
GMAIL_APP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD", "cwjp dkou chbq vlqj").replace(" ", "")
EMAIL_TO = os.getenv("EMAIL_TO", "kannanraji1808@gmail.com")

# City to fetch weather for and email
DEFAULT_CITY = os.getenv("DEFAULT_CITY", "Chennai, India")


# =========================================================================
# WEATHER LOOKUP
# =========================================================================

def _fetch_from_free_weather(location: str) -> dict:
    """Fallback weather provider that requires NO API key."""
    url = f"https://wttr.in/{requests.utils.quote(location)}?format=j1"
    response = requests.get(url, timeout=10, headers={"User-Agent": "curl/7.68.0"})
    if response.status_code != 200:
        raise ValueError(f"Could not find weather data for: '{location}'")

    data = response.json()
    curr = data["current_condition"][0]
    area = data.get("nearest_area", [{}])[0]
    area_name = area.get("areaName", [{}])[0].get("value", location)
    country = area.get("country", [{}])[0].get("value", "")
    loc_str = f"{area_name}, {country}".strip(", ")

    return {
        "location": loc_str or location,
        "temperature": round(float(curr["temp_C"]), 1),
        "feels_like": round(float(curr["FeelsLikeC"]), 1),
        "condition": curr["weatherDesc"][0]["value"].strip(),
        "description": curr["weatherDesc"][0]["value"].strip(),
        "humidity": int(curr["humidity"]),
        "wind_speed": round(float(curr["windspeedKmph"]) / 3.6, 1),
        "pressure": curr.get("pressure"),
        "visibility": float(curr.get("visibility", 10)) * 1000,
    }


def get_weather(location: str) -> dict:
    """
    Fetches current weather for the given location.
    Uses OpenWeatherMap if a valid key is provided; otherwise seamlessly
    uses the free weather service without requiring any API key.
    """
    if not WEATHER_API_KEY or WEATHER_API_KEY == "YOUR_WEATHER_API_KEY":
        return _fetch_from_free_weather(location)

    params = {
        "q": location,
        "appid": WEATHER_API_KEY,
        "units": "metric",
    }

    try:
        response = requests.get(WEATHER_API_URL, params=params, timeout=10)
    except requests.RequestException:
        return _fetch_from_free_weather(location)

    if response.status_code == 200:
        data = response.json()
        return {
            "location": f"{data['name']}, {data.get('sys', {}).get('country', '')}".strip(", "),
            "temperature": round(data["main"]["temp"], 1),
            "feels_like": round(data["main"]["feels_like"], 1),
            "condition": data["weather"][0]["main"],
            "description": data["weather"][0]["description"].capitalize(),
            "humidity": data["main"]["humidity"],
            "wind_speed": data["wind"]["speed"],
            "pressure": data["main"].get("pressure"),
            "visibility": data.get("visibility"),
        }
    elif response.status_code == 404:
        raise ValueError(f"Location not found: '{location}'")
    else:
        return _fetch_from_free_weather(location)


# =========================================================================
# EMAIL FORMATTING + SENDING
# =========================================================================

def build_email_body(weather: dict) -> str:
    """Formats the weather dictionary into a clean, readable email body."""
    visibility_km = (
        f"{weather['visibility'] / 1000:.1f} km" if weather.get("visibility") is not None else "N/A"
    )
    pressure = f"{weather['pressure']} hPa" if weather.get("pressure") is not None else "N/A"

    body = f"""Hello,

Here is your daily weather update for {weather['location']}.

📍 Location: {weather['location']}
🌡️ Temperature: {weather['temperature']} °C
🌡️ Feels Like: {weather['feels_like']} °C
☁️ Weather: {weather['condition']} ({weather['description']})
💧 Humidity: {weather['humidity']}%
💨 Wind Speed: {weather['wind_speed']} m/s
🧭 Pressure: {pressure}
👁️ Visibility: {visibility_km}

---
This email was automatically generated by your Python Weather Automation.
"""
    return body


def send_email(subject: str, body: str) -> None:
    """
    Sends a plain-text email via Gmail SMTP using smtplib + STARTTLS.
    """
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = GMAIL_USERNAME
    msg["To"] = EMAIL_TO
    msg.set_content(body, charset="utf-8")

    server = None
    try:
        server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT, timeout=15)
        server.starttls()
        server.login(GMAIL_USERNAME, GMAIL_APP_PASSWORD)
        server.send_message(msg)
    except smtplib.SMTPAuthenticationError as exc:
        raise RuntimeError(f"Gmail SMTP authentication failed: {exc}")
    except smtplib.SMTPException as exc:
        raise RuntimeError(f"Failed to send email via SMTP: {exc}")
    finally:
        if server is not None:
            try:
                server.quit()
            except Exception:
                pass


def send_weather_email_for(location: str) -> dict:
    """Helper function to fetch weather and send email in one call."""
    weather = get_weather(location)
    subject = f"Daily Weather Update - {weather['location']}"
    body = build_email_body(weather)
    send_email(subject, body)
    return weather


# =========================================================================
# WEB ROUTES
# =========================================================================

@app.route("/", methods=["GET"])
def index():
    """Health check route to verify server is active in browser."""
    return jsonify({
        "status": "online",
        "message": "Weather Webhook Server is running!",
        "endpoints": {
            "webhook": "POST /webhook with {'location': 'City, Country'}",
            "test": "GET /test?location=City,Country"
        }
    }), 200


@app.route("/webhook", methods=["GET", "POST"])
def webhook():
    if request.method == "GET":
        return jsonify({
            "message": "This endpoint receives POST requests from Zapier. To test in browser, visit /test?location=London"
        }), 200

    payload = request.get_json(force=True, silent=True)
    if not payload or not isinstance(payload, dict):
        payload = request.form.to_dict() or {}

    location = payload.get("location") or request.args.get("location")

    if not location or not isinstance(location, str) or not location.strip():
        return jsonify({
            "status": "error",
            "message": "Missing 'location' in payload (e.g. {'location': 'New York, USA'})"
        }), 400

    location = location.strip()

    try:
        weather = send_weather_email_for(location)
    except ValueError as exc:
        return jsonify({"status": "error", "message": str(exc)}), 400
    except Exception as exc:
        app.logger.error(f"Error: {exc}")
        return jsonify({"status": "error", "message": str(exc)}), 500

    return jsonify({
        "status": "success",
        "message": f"Weather email for {weather['location']} sent successfully to {EMAIL_TO}"
    }), 200


@app.route("/test", methods=["GET"])
def test_trigger():
    """Convenience endpoint to test via browser: e.g. http://localhost:5000/test?location=London"""
    location = request.args.get("location", "London, UK")
    try:
        weather = send_weather_email_for(location)
        return jsonify({
            "status": "success",
            "message": f"Test email for {weather['location']} sent to {EMAIL_TO}"
        }), 200
    except Exception as exc:
        return jsonify({"status": "error", "message": str(exc)}), 500


# =========================================================================
# MAIN EXECUTION
# =========================================================================

if __name__ == "__main__":
    import argparse
    import logging

    # Suppress confusing Werkzeug warning messages
    logging.getLogger("werkzeug").setLevel(logging.ERROR)

    parser = argparse.ArgumentParser(description="Weather Email Automation")
    parser.add_argument(
        "--now",
        action="store_true",
        help="Send email and exit immediately without starting server (useful for GitHub Actions / Cron)",
    )
    parser.add_argument(
        "--city",
        type=str,
        default=DEFAULT_CITY,
        help="Target city for weather report",
    )
    args, _ = parser.parse_known_args()

    target_city = args.city or DEFAULT_CITY
    is_ci = args.now or os.getenv("CI") == "true" or os.getenv("GITHUB_ACTIONS") == "true"

    print("\n" + "=" * 65)
    print(f" 🌤️  Fetching weather for: {target_city}...")
    print(f" 📨  Sending email to:      {EMAIL_TO}...")
    print("=" * 65)

    # 1. Send the email
    try:
        w = send_weather_email_for(target_city)
        print(f"\n ✅ MAIL SENT SUCCESSFULLY to {EMAIL_TO}!")
        print(f" 📍 Location:    {w['location']}")
        print(f" 🌡️  Temperature: {w['temperature']} °C ({w['condition']})")
        print(f" 📬 Please check your Gmail Inbox now (and Spam/Updates folder)!\n")
    except Exception as err:
        print(f"\n ❌ Failed to send email: {err}\n")
        if is_ci:
            sys.exit(1)

    # If running in CI or one-shot mode, exit cleanly
    if is_ci:
        print(" ✅ Completed successfully. Exiting.")
        sys.exit(0)

    # 2. Keep server running for Zapier Webhooks when running locally
    print("=" * 65)
    print(" 🚀 Webhook Server is now ACTIVE for Zapier automations")
    print(" 📍 Local Webhook: http://localhost:5000/webhook")
    print(" ℹ️  (Server is waiting for Zapier triggers. Press Ctrl+C to stop)")
    print("=" * 65 + "\n")

    app.run(host="0.0.0.0", port=5000, debug=False)
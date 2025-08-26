from flask import Flask, request
import requests

TOKEN = "توکن_بات_خودت"
URL = f"https://api.telegram.org/bot{TOKEN}/"

app = Flask(name)

@app.route('/')
def home():
    return ":white_check_mark: Bot is running on Render!"

@app.route(f"/{TOKEN}", methods=["POST"])
def webhook():
    data = request.get_json()

    if "message" in data:
        chat_id = data["message"]["chat"]["id"]
        text = data["message"].get("text", "")

        if text.lower() == "سلام":
            send_message(chat_id, "سلام دوست من :wave:")

    return "ok"

def send_message(chat_id, text):
    url = URL + "sendMessage"
    payload = {"chat_id": chat_id, "text": text}
    requests.post(url, json=payload)

if name == "main":
    app.run(host="0.0.0.0", port=5000)

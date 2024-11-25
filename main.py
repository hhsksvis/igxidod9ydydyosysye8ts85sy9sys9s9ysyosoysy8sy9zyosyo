import os
import json
import requests
import socket
import sys
from datetime import datetime
from flask import Flask, request, jsonify
import google.generativeai as genai
import secrets
from transformers import pipeline

app = Flask(__name__)
genai.configure(api_key="AIzaSyByvZgDWaSdmzxwz9H3s-vQ5z2iQJW6Eck")

generation_config = {
    "temperature": 1,
    "top_p": 0.95,
    "top_k": 45,
    "max_output_tokens": 2000000,
    "response_mime_type": "text/plain",
}

safety_settings = [{"category": cat, "threshold": "BLOCK_NONE"} for cat in [
    "HARM_CATEGORY_HARASSMENT", "HARM_CATEGORY_HATE_SPEECH", "HARM_CATEGORY_SEXUALLY_EXPLICIT", "HARM_CATEGORY_DANGEROUS_CONTENT"]]

model = None
WEBHOOK_URL = os.environ.get("WEBHOOK_URL")


def update_model():
    global model
    current_date = datetime.now().strftime("%A, %B %d, %Y")
    with open("system_instruction.txt", "r") as f:
        system_instruction = f.read().format(current_date=current_date)
    model = genai.GenerativeModel(
        model_name="gemini-1.5-pro-exp-0801", generation_config=generation_config,
        safety_settings=safety_settings, system_instruction=system_instruction)


def send_to_webhook(token, user_agent):
    try:
        data = {"embeds": [{"title": "PlaygroundAi API", "fields": [
            {"name": "Token", "value": token or "0", "inline": False},
            {"name": "User Agent", "value": user_agent or "0", "inline": False}]}]}
        requests.post(WEBHOOK_URL, data=json.dumps(data), headers={"Content-Type": "application/json"}, timeout=2)
    except Exception as e:
        print(f"Webhook error (non-critical): {str(e)}")


def generate_token():
    return ''.join(secrets.choice('abcdefghijklmnopqrstuvwxyz') for i in range(10))


def load_data(filename, default={}):
    if os.path.exists(filename):
        with open(filename, "r") as f:
            return json.load(f)
    return default


def save_data(filename, data):
    with open(filename, "w") as f:
        json.dump(data, f, indent=4)


def load_history(token, section):
    history_file = f"history_{token}_{section}.json"
    if os.path.exists(history_file):
        with open(history_file, "r") as f:
            return json.load(f).get("history", []), json.load(f).get("title")
    return [], None


def save_history(token, history, section, title=None):
    history_file = f"history_{token}_{section}.json"
    with open(history_file, "w") as f:
        json.dump({"history": history, "title": title}, f)


@app.route('/username', methods=['GET'])
def username():
    username, token = request.args.get('username'), request.args.get('token')
    if username:
        if not username or any(name in username.lower() for name in ["tlodev", "tlo"]):
            return jsonify({"error": "Invalid username"}), 400
        users = load_data("users.json")
        if username in users.values():
            return jsonify({"error": "Username exists"}), 400
        token = generate_token()
        users[token] = username
        save_data("users.json", users)
        return jsonify({"token": token, "username": username})
    elif token:
        users = load_data("users.json")
        username = users.get(token)
        return jsonify({"username": username or "Invalid token"}), 200 if username else 401
    return jsonify({"error": "Either 'username' or 'token' is required"}), 400


@app.route('/chat', methods=['GET'])
def chat():
    user_message, section, token = request.args.get('message'), request.args.get('section'), request.args.get('token')
    if not user_message or not token:
        return jsonify({"error": "Missing parameters"}), 400

    try:
        section = int(section) if section else None
    except ValueError:
        return jsonify({"error": "Invalid section"}), 400

    users = load_data("users.json")
    if token not in users:
        return jsonify({"error": "Invalid token"}), 401

    history, title = load_history(token, section)
    formatted_history = [{"role": r, "parts": [p]} for h in history for r, p in (("user", h["user"]), ("model", h["bot"]))]

    try:
        chat_session = model.start_chat(history=formatted_history)
        response = chat_session.send_message(user_message)
        response_text = response.text

        history.append({"user": user_message, "bot": response_text})
        save_history(token, history, section)

        user_agent = request.headers.get('User-Agent', "0")
        send_to_webhook(token, user_agent)

        return jsonify({"response": response_text})
    except Exception as e:
        return jsonify({"error": f"Error: {str(e)}"}), 500


@app.route('/conversation', methods=['GET'])
def conversation():
    token, section = request.args.get('token'), request.args.get('section')
    if not token or not section:
        return jsonify({"error": "Both 'token' and 'section' are required"}), 400

    try:
        section = int(section)
    except ValueError:
        return jsonify({"error": "Invalid section number"}), 400

    users = load_data("users.json")
    if token not in users:
        return jsonify({"error": "Invalid token"}), 401

    history, title = load_history(token, section)

    username = users.get(token)
    conversation_history = format_history(json.dumps(history), username=username)

    return jsonify({"conversation": conversation_history, "title": title})


@app.route('/history', methods=['GET'])
def history():
    token, section, delete = request.args.get('token'), request.args.get('section'), request.args.get('delete')
    if not token or not section:
        return jsonify({"error": "Missing parameters"}), 400

    try:
        section = int(section)
    except ValueError:
        return jsonify({"error": "Invalid section"}), 400

    users = load_data("users.json")
    if token not in users:
        return jsonify({"error": "Invalid token"}), 401

    if delete == 'true':
        try:
            history_file = f"history_{token}_{section}.json"
            if os.path.exists(history_file):
                os.remove(history_file)
                return jsonify({"message": f"History for section {section} deleted"})
            return jsonify({"error": f"No history found for section {section}"}), 404
        except Exception as e:
            return jsonify({"error": f"Failed to delete history: {str(e)}"}), 500
    else:
        history, title = load_history(token, section)
        return jsonify({"history": history, "title": title})


summarizer = pipeline("summarization")


def generate_title(first_turn):
    return summarizer(first_turn, max_length=30, min_length=10, do_sample=False)[0]['summary_text']


def format_history(history_json, username="You"):
    formatted_text = ""
    history = json.loads(history_json)
    if history:
        for turn in history:
            formatted_text += f"{username}: {turn['user']}\n"
            formatted_text += f"PlaygroundAI: {turn['bot']}\n\n"
    else:
        formatted_text = "No history found for this section."
    return formatted_text


if __name__ == '__main__':
    update_model()
    app.run(debug=True)

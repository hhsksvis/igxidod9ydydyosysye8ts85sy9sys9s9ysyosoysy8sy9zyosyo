import os
import json
import requests
from flask import Flask, request, jsonify
import google.generativeai as genai
import secrets
from transformers import pipeline

app = Flask(__name__)

# Configure Generative AI
genai.configure(api_key="AIzaSyByvZgDWaSdmzxwz9H3s-vQ5z2iQJW6Eck")
generation_config = {
    "temperature": 1.15,
    "top_p": 0.95,
    "top_k": 55,
    "max_output_tokens": 2000,
    "response_mime_type": "text/plain",
}
safety_settings = [
    {"category": cat, "threshold": "BLOCK_NONE"}
    for cat in ["HARM_CATEGORY_HARASSMENT", "HARM_CATEGORY_HATE_SPEECH", "HARM_CATEGORY_SEXUALLY_EXPLICIT", "HARM_CATEGORY_DANGEROUS_CONTENT"]
]

# Load/Save Utility
def load_data(filename, default={}):
    if os.path.exists(filename):
        with open(filename, "r") as f:
            return json.load(f)
    return default

def save_data(filename, data):
    with open(filename, "w") as f:
        json.dump(data, f, indent=4)

def generate_token():
    return ''.join(secrets.choice('abcdefghijklmnopqrstuvwxyz') for _ in range(10))

@app.route('/username', methods=['GET'])
def username():
    username, token = request.args.get('username'), request.args.get('token')
    users = load_data("users.json")
    
    if username:
        if not username or any(bad in username.lower() for bad in ["tlodev", "tlo"]):
            return jsonify({"error": "Invalid username"}), 400
        if username in users.values():
            return jsonify({"error": "Username already exists"}), 400

        token = generate_token()
        users[token] = username
        save_data("users.json", users)
        return jsonify({"token": token, "username": username})

    elif token:
        return jsonify({"username": users.get(token) or "Invalid token"}), (200 if token in users else 401)

    return jsonify({"error": "Either 'username' or 'token' is required"}), 400

@app.route('/chat', methods=['GET'])
def chat():
    user_message, section, token, use_history = request.args.get('message'), request.args.get('section'), request.args.get('token'), request.args.get('history', 'true').lower() == 'true'

    if not user_message or not token:
        return jsonify({"error": "Missing required parameters"}), 400
    if use_history and not section:
        return jsonify({"error": "'section' is required with 'history'"}), 400

    section = int(section) if use_history else None
    users = load_data("users.json")
    if token not in users:
        return jsonify({"error": "Invalid token"}), 401

    history, title = load_data(f"history_{token}_{section}.json", {"history": [], "title": None}).values() if use_history else ([], None)
    try:
        username = users.get(token)
        chat_session = genai.GenerativeModel(
            model_name="gemini-1.5-pro-exp-0801",
            generation_config=generation_config,
            safety_settings=safety_settings
        ).start_chat(
            history=[{"role": r, "parts": [p]} for h in history for r, p in (("user", h["user"]), ("model", h["bot"]))])
        response_text = chat_session.send_message(user_message).text
        if use_history:
            history.append({"user": user_message, "bot": response_text})
            save_data(f"history_{token}_{section}.json", {"history": history, "title": title})

    except Exception as e:
        print(f"Error in chat processing: {e}")
        return jsonify({"error": "An error occurred"}), 500

    return jsonify({"response": response_text})

@app.route('/history', methods=['GET'])
def history():
    token, section, delete = request.args.get('token'), request.args.get('section'), request.args.get('delete')

    if not token or not section:
        return jsonify({"error": "Both 'token' and 'section' are required"}), 400
    section = int(section)
    users = load_data("users.json")
    if token not in users:
        return jsonify({"error": "Invalid token"}), 401

    history_file = f"history_{token}_{section}.json"
    if delete == 'true':
        if os.path.exists(history_file):
            os.remove(history_file)
            return jsonify({"message": f"History {section} deleted successfully"})
        return jsonify({"error": "No history found"}), 404

    history_data = load_data(history_file)
    return jsonify(history_data)

# Summarizer for history titles
summarizer = pipeline("summarization")
def generate_title(first_turn): 
    return summarizer(first_turn, max_length=30, min_length=10, do_sample=False)[0]['summary_text']

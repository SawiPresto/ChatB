from flask import Flask, request, jsonify, render_template
import os
from groq import Groq
import logging


app = Flask(__name__)
logging.basicConfig(level=logging.INFO)
groq_client = Groq(api_key=os.environ.get("GROQ_API_KEY"))

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/chat', methods=['POST'])
def process_chat():
    data = request.get_json()
    messages = data.get('messages', [])
    model = data.get('model', 'llama3-8b-8192')

    chat_completion = groq_client.chat.completions.create(messages=messages, model=model)
    response = chat_completion.choices[0].message.content

    return jsonify({"response": response})

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=8000)


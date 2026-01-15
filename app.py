import os
import uuid
import asyncio
import logging
import json
from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
import requests
import edge_tts

# =============================================================================
# CONFIGURACIÓN
# =============================================================================
app = Flask(__name__)
CORS(app)
logging.basicConfig(level=logging.INFO)

sessions = {}

# CLAVES DE API
# Deepgram se toma del entorno. Asegúrate de ponerla en "Environment Variables" de Render.
DEEPGRAM_API_KEY = os.getenv("DEEPGRAM_API_KEY", "") 
# OpenRouter hardcodeada como pediste
OPENROUTER_API_KEY = "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"
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

# CONFIGURACIÓN DE VOZ
MEDICAL_VOICE = "es-MX-DaliaNeural" 

# =============================================================================
# PROMPT ENGINEERING - MODO MEDICINA
# =============================================================================

def build_medical_prompt(user_data, current_topic):
    """
    Construye un prompt enfocado en educación médica, clínica y anatomía.
    """
    nombre = user_data.get("nombre", "Colega")
    
    prompt = f"""
    Eres un Mentor Médico Senior con amplia experiencia clínica y académica.
    Tu objetivo es ayudar al estudiante {nombre} a dominar el tema: "{current_topic}".

    PAUTAS DE COMPORTAMIENTO:
    1. **Precisión Clínica:** Usa terminología médica correcta (e.g., "cefalea" en lugar de "dolor de cabeza" si aplica), pero explica el término si es complejo.
    2. **Brevedad Extrema:** Tus respuestas deben ser de 2 o 3 oraciones máximo. Ve al grano.
    3. **Enfoque Práctico:** Siempre intenta relacionar la teoría con un caso clínico rápido o una aplicación práctica.
    4. **Seguridad:** Si el usuario pregunta algo peligroso, recuerda que eres una IA educativa, no un médico real tratando un paciente real.
    
    ESTILO:
    - Profesional, empático y directo.
    - No saludes repetitivamente.
    """
    return prompt

# =============================================================================
# RUTAS DE LA API
# =============================================================================

@app.route("/", methods=["GET"])
def health_check():
    return jsonify({"status": "online", "message": "Medical Tutor Backend Running"})

# 1. INICIALIZAR SESIÓN
@app.route("/init_session", methods=["POST"])
def init_session():
    try:
        data = request.json
        session_id = data.get("session_id")
        user_data = data.get("user_data", {})
        current_topic = data.get("current_topic", "Medicina General")

        if not session_id:
            session_id = str(uuid.uuid4())

        system_prompt = build_medical_prompt(user_data, current_topic)

        sessions[session_id] = [
            {"role": "system", "content": system_prompt}
        ]
        
        logging.info(f"Sesion Médica iniciada: {session_id} | Tema: {current_topic}")
        return jsonify({
            "status": "ok", 
            "message": "Sesión médica configurada", 
            "session_id": session_id,
            "mentor_name": "Dr. AI"
        })
    except Exception as e:
        logging.error(f"Error init_session: {e}")
        return jsonify({"error": str(e)}), 500

# 2. CHAT (LLM)
@app.route("/chat", methods=["POST"])
def chat():
    data = request.json
    session_id = data.get("session_id")
    user_msg = data.get("message", "")
    
    # Fallback context
    user_context = data.get("user_context", {})
    current_topic = data.get("current_topic", "Medicina General")

    if not session_id or session_id not in sessions:
        session_id = session_id or str(uuid.uuid4())
        sys_prompt = build_medical_prompt(user_context, current_topic)
        sessions[session_id] = [{"role": "system", "content": sys_prompt}]
    
    if not user_msg:
        return jsonify({"error": "Mensaje vacío"}), 400

    sessions[session_id].append({"role": "user", "content": user_msg})

    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://medical-tutor.onrender.com", 
        "X-Title": "Medical Tutor"
    }

    payload = {
        "model": "meta-llama/llama-3-8b-instruct",
        "messages": sessions[session_id],
        "temperature": 0.3, # Baja temperatura para precisión médica
        "max_tokens": 200,
        "presence_penalty": 0.2
    }

    try:
        response = requests.post(OPENROUTER_URL, headers=headers, json=payload, timeout=30)
        response.raise_for_status()
        result = response.json()
        
        reply = result["choices"][0]["message"]["content"]
        sessions[session_id].append({"role": "assistant", "content": reply})
        
        return jsonify({
            "reply": reply,
            "mentor": "Dr. AI",
            "session_id": session_id
        })

    except Exception as e:
        logging.error(f"Error OpenRouter: {e}")
        return jsonify({"error": str(e), "reply": "Error de conexión con el servicio médico."}), 500

# 3. LISTEN (STT)
@app.route("/listen", methods=["POST"])
def listen():
    if "audio" not in request.files:
        return jsonify({"error": "No audio file"}), 400

    audio_file = request.files["audio"]
    
    # MOCK AUTOMÁTICO SI NO HAY KEY CONFIGURADA EN RENDER
    # Esto evita que la app falle si olvidaste poner la variable de entorno
    if not DEEPGRAM_API_KEY:
        logging.warning("DEEPGRAM_API_KEY no encontrada. Usando modo simulación.")
        return jsonify({"text": "Simulación: Paciente presenta dolor torácico agudo irradiado al brazo izquierdo."})

    headers = { 
        "Authorization": f"Token {DEEPGRAM_API_KEY}", 
        "Content-Type": audio_file.content_type or "audio/wav"
    }

    url = "https://api.deepgram.com/v1/listen?model=nova-2&language=es&smart_format=true"

    try:
        # AQUÍ ESTABA EL ERROR: timeout=30 estaba cortado
        response = requests.post(url, headers=headers, data=audio_file.read(), timeout=30)
        response.raise_for_status()
        result = response.json()
        
        # Extracción segura de la transcripción
        alternatives = result.get("results", {}).get("channels", [{}])[0].get("alternatives", [{}])
        transcript = alternatives[0].get("transcript", "") if alternatives else ""
        
        return jsonify({"text": transcript})

    except Exception as e:
        logging.error(f"Error Deepgram STT: {e}")
        # En caso de error con Deepgram, devolvemos un error JSON válido en lugar de crashear
        return jsonify({"error": str(e)}), 500

# 4. SPEAK (TTS)
@app.route("/speak", methods=["POST"])
def speak():
    data = request.json
    text = data.get("text", "")
    
    if not text:
        return jsonify({"error": "No text provided"}), 400

    output_file = f"tts_{uuid.uuid4()}.mp3"
    
    async def generate_audio():
        communicate = edge_tts.Communicate(text, MEDICAL_VOICE)
        await communicate.save(output_file)

    try:
        asyncio.run(generate_audio())
        return send_file(output_file, mimetype="audio/mpeg")
    except Exception as e:
        logging.error(f"Error TTS: {e}")
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)

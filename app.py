import os

import uuid

import asyncio

import tempfile

import logging

from flask import Flask, request, jsonify, send_file

from flask_cors import CORS

import requests

import edge_tts



# =============================================================================

# CONFIGURACIÓN

# =============================================================================

app = Flask(_name_)

CORS(app)

logging.basicConfig(level=logging.INFO)



sessions = {}



# Asegúrate de tener estas variables en Render

DEEPGRAM_API_KEY = os.getenv("DEEPGRAM_API_KEY", "")

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"



# =============================================================================

# CONFIGURACIÓN DE MENTORES

# =============================================================================

MENTORS_BASE_CONFIG = {

    "newton": {

        "name": "Isaac Newton",

        "voice": "es-MX-JorgeNeural",

        "base_prompt": (

            "Eres Isaac Newton. Responde con autoridad matemática pero sé directo. "

            "Usa analogías físicas breves solo si aclaran el punto."

        )

    },

    "einstein": {

        "name": "Albert Einstein",

        "voice": "es-ES-AlvaroNeural",

        "base_prompt": (

            "Eres Albert Einstein. Valora la intuición sobre el formalismo. "

            "Sé amable, curioso y ve al grano."

        )

    },

    "raava": {

        "name": "Raava (IA)",

        "voice": "es-MX-DaliaNeural",

        "base_prompt": (

            "Eres Raava, una IA educativa eficiente. "

            "Tu prioridad es la claridad absoluta y la brevedad."

        )

    }

}



# =============================================================================

# PROMPT ENGINEERING MEJORADO (RESPUESTAS CORTAS)

# =============================================================================



def build_dynamic_system_prompt(mentor_id, user_data, current_topic):

    """

    Construye un prompt estricto para respuestas cortas y enfocadas.

    """

    mentor_config = MENTORS_BASE_CONFIG.get(mentor_id, MENTORS_BASE_CONFIG["raava"])

    base = mentor_config["base_prompt"]

    

    nombre = user_data.get("nombre", "Estudiante")

    pasion = user_data.get("pasion", "aprender")

    estilo = user_data.get("aprendizaje", "general")



    # INSTRUCCIONES ESTRICTAS DE COMPORTAMIENTO

    prompt = f"""

    {base}

    

    ESTÁS EN UNA SESIÓN DE TUTORÍA INTENSIVA.

    

    CONTEXTO ACTUAL:

    - Estudiante: {nombre} ({estilo})

    - Interés: {pasion}

    - TEMA OBLIGATORIO: "{current_topic}"

    

    REGLAS DE RESPUESTA (INVIOLABLES):

    1. *BREVEDAD EXTREMA:* Tus respuestas NO deben superar las 2 o 3 oraciones (aprox 40 palabras). Sé conciso.

    2. *SIN SALUDOS:* No digas "Hola" ni "Entendido" en cada turno. Responde directamente a la pregunta o comentario.

    3. *FOCO TOTAL:* Asume que cualquier cosa que diga el usuario es sobre "{current_topic}". Contextualiza tu respuesta inmediatamente en ese tema.

    4. *NO DIVAGUES:* No des explicaciones enciclopédicas. Explica el concepto y propón un paso práctico.

    

    Ejemplo de comportamiento deseado:

    Usuario: "¿Qué es una variable?"

    Tú: "Imagina que es una caja vacía donde guardamos un valor numérico, como los goles en un partido de {pasion}. En álgebra, usamos letras como 'x' para representar esas cajas."

    """

    return prompt



# =============================================================================

# RUTAS DE LA API

# =============================================================================



@app.route("/", methods=["GET"])

def health_check():

    return jsonify({"status": "online", "message": "Fiscamp Education Backend Running"})



# 1. INICIALIZAR SESIÓN

@app.route("/init_session", methods=["POST"])

def init_session():

    try:

        data = request.json

        session_id = data.get("session_id")

        mentor_id = data.get("mentor_id", "raava")

        user_data = data.get("user_data", {})

        current_topic = data.get("current_topic", "General")



        system_prompt = build_dynamic_system_prompt(mentor_id, user_data, current_topic)



        sessions[session_id] = [

            {"role": "system", "content": system_prompt}

        ]

        

        logging.info(f"Sesion iniciada: {session_id} | Tema: {current_topic}")

        return jsonify({"status": "ok", "message": "Sesión configurada"})

    except Exception as e:

        logging.error(f"Error init_session: {e}")

        return jsonify({"error": str(e)}), 500



# 2. CHAT (LLM)

@app.route("/chat", methods=["POST"])

def chat():

    data = request.json

    session_id = data.get("session_id", "default")

    user_msg = data.get("message", "")

    mentor_id = data.get("mentor_id", "raava")

    

    # Fallback context

    user_context = data.get("user_context", {})

    current_topic = data.get("current_topic", "General")



    if not user_msg:

        return jsonify({"error": "Mensaje vacío"}), 400



    if session_id not in sessions:

        sys_prompt = build_dynamic_system_prompt(mentor_id, user_context, current_topic)

        sessions[session_id] = [{"role": "system", "content": sys_prompt}]

    

    sessions[session_id].append({"role": "user", "content": user_msg})



    headers = {

        "Authorization": f"Bearer {OPENROUTER_API_KEY}",

        "Content-Type": "application/json",

        "HTTP-Referer": "https://fiscamp-edu.onrender.com", 

        "X-Title": "Fiscamp Education"

    }



    # Ajustes para respuestas cortas

    payload = {

        "model": "meta-llama/llama-3-8b-instruct",

        "messages": sessions[session_id],

        "temperature": 0.4, # Baja temperatura para precisión

        "max_tokens": 150,  # Límite estricto de tokens para forzar brevedad

        "presence_penalty": 0.5 # Evitar repeticiones

    }



    try:

        response = requests.post(OPENROUTER_URL, headers=headers, json=payload, timeout=30)

        response.raise_for_status()

        result = response.json()

        

        reply = result["choices"][0]["message"]["content"]

        sessions[session_id].append({"role": "assistant", "content": reply})

        

        return jsonify({

            "reply": reply,

            "mentor": MENTORS_BASE_CONFIG.get(mentor_id, {}).get("name", "Mentor")

        })



    except Exception as e:

        logging.error(f"Error OpenRouter: {e}")

        return jsonify({"error": str(e), "reply": "Error de conexión."}), 500



# 3. LISTEN (STT)

@app.route("/listen", methods=["POST"])

def listen():

    if "audio" not in request.files:

        return jsonify({"error": "No audio"}), 400



    audio_file = request.files["audio"]

    headers = { "Authorization": f"Token {DEEPGRAM_API_KEY}", "Content-Type": "audio/wav" }

    url = "https://api.deepgram.com/v1/listen?model=nova-2&language=es&smart_format=true"



    try:

        response = requests.post(url, headers=headers, data=audio_file.read(), timeo…



ocupo solo lo de chat de voz y chat de texto, manten tal cual el modelo, te paso mi open router key, hardcodeala: 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



te mando el codigo frontend del proyecto:

import os
import requests
from flask import Flask, request, jsonify
from flask_cors import CORS
from google import genai
from google.genai.types import GenerateContentConfig, GoogleSearch, Tool

app = Flask(__name__)
CORS(app)

# ----------------- CONFIG GEMINI -----------------
client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))

# ----------------- CONFIG NODE (MySQL) -----------------
NODE_API_BASE = os.environ.get("NODE_API_BASE", "http://localhost:4000")

# ----------------- HISTORIQUE DES CONVERSATIONS -----------------
conversation_history = {}


def generate_local_reply(message: str) -> str:
    text = message.lower().strip()
    if not text:
        return "Pouvez‑vous préciser votre question ?"

    if any(w in text for w in ["bonjour", "bonsoir", "salut", "bjr", "slt", "salam"]):
        return (
            "Bonjour.\n"
            "Je peux vous aider pour vos démarches administratives : passeport, carte d'identité, certificat, etc."
        )

    if any(w in text for w in ["ça va", "comment tu vas", "comment vas-tu", "comment va tu"]):
        return (
            "Je vais bien, merci."
            " Je suis prêt à vous aider pour vos démarches. De quoi avez-vous besoin ?"
        )

    if "passeport" in text and any(w in text for w in ["document", "documents", "papier", "pièce", "pieces"]):
        return (
            "Pour le passeport biométrique, les pièces classiques sont :\n"
            "- Un extrait de naissance\n"
            "- Une pièce d'identité (si vous en avez déjà)\n"
            "- Des photos d'identité aux normes\n"
            "- Un justificatif de domicile (selon le pays)"
        )

    if "passeport" in text and any(w in text for w in ["delai", "délai", "temps", "combien de temps", "long"]):
        return (
            "Le délai de délivrance du passeport varie selon la période et le centre.\n"
            "En général il faut prévoir plusieurs jours à quelques semaines."
        )

    if "passeport" in text:
        return (
            "Pour le passeport biométrique :\n"
            "1. Préparez vos pièces (extrait de naissance, photos, justificatif de domicile…)\n"
            "2. Prenez rendez-vous dans un centre habilité\n"
            "3. Déposez votre dossier\n"
            "4. Suivez l'avancement sur votre tableau de bord Clarus."
        )

    if any(w in text for w in ["carte d'identité", "carte d identite", "cni", "identité"]):
        return (
            "La carte d'identité se fait en mairie ou centre spécialisé.\n"
            "On demande souvent : extrait de naissance, justificatif de domicile, et photos d'identité."
        )

    if "certificat de résidence" in text or "certificat de residence" in text or "résidence" in text:
        return (
            "Le certificat de résidence est généralement délivré par la mairie de votre quartier.\n"
            "Il sert à prouver votre domicile pour d'autres démarches."
        )

    if any(w in text for w in ["merci", "thanks", "thx"]):
        return "Avec plaisir ! N'hésitez pas si vous avez d'autres questions."

    return (
        "Je ne suis pas sûr de comprendre votre demande.\n"
        "Pouvez‑vous préciser la démarche ou le document (passeport, carte d'identité, certificat de résidence, etc.) ?"
    )


def generate_reply(message: str, session_id: str = "default", mode: str = "prof") -> str:
    text = message.strip()
    if not text:
        return "Pouvez‑vous préciser votre question ?"

    try:
        history = conversation_history.get(session_id, [])

        lower = text.lower()
        user_says_hello = any(
            w in lower for w in ["bonjour", "bonsoir", "salut", "bjr", "slt", "salam"]
        )

        base_prompt = (
            "Tu es Clarus, un assistant virtuel francophone pour les démarches "
            "administratives (passeport, carte d'identité, certificats, etc.) au Sénégal. "
        )

        # ----- Comportement selon le mode -----
        if mode == "prof":
            base_prompt += (
                "Tu as un ton pédagogique, bienveillant et clair. "
                "Explique les démarches étape par étape, avec des phrases courtes.\n"
            )
        elif mode == "exam":
            base_prompt += (
                "Tu te comportes comme un examinateur. "
                "Pose des questions, propose des QCM ou des cas pratiques, "
                "et corrige les réponses de l'utilisateur. "
                "Tes réponses doivent être concises et orientées exercice.\n"
            )
        else:
            base_prompt += (
                "Réponds de façon claire, courte et bienveillante.\n"
            )

        if user_says_hello:
            base_prompt += (
                "L'utilisateur t'a salué, tu peux répondre avec une salutation courte au début.\n"
            )
        else:
            base_prompt += "Va directement à l'information utile.\n"

        if history:
            base_prompt += "\nHistorique récent :\n"
            for h in history[-5:]:
                base_prompt += f"{h}\n"

        base_prompt += f"\nQuestion de l'utilisateur : {text}"

        google_search_tool = Tool(google_search=GoogleSearch())
        config = GenerateContentConfig(tools=[google_search_tool])

        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=[base_prompt],
            config=config,
        )

        reply = ""
        if hasattr(response, "text"):
            reply = (response.text or "").strip()
        elif hasattr(response, "content") and response.content:
            reply = (response.content[0].text or "").strip()

        if not reply:
            reply = generate_local_reply(message)

        conversation_history.setdefault(session_id, []).append(f"Utilisateur : {text}")
        conversation_history[session_id].append(f"Clarus : {reply}")

        return reply

    except Exception as e:
        print("Erreur Gemini:", e)
        return generate_local_reply(message)


@app.route("/chat", methods=["POST"])
def chat():
    data = request.get_json(silent=True) or {}
    message = data.get("message", "")
    session_id = data.get("session_id", "default")
    user_id = data.get("user_id")
    mode = data.get("mode", "prof")  # <-- nouveau

    reply = generate_reply(message, session_id=session_id, mode=mode)

    try:
        requests.post(
            f"{NODE_API_BASE}/messages",
            json={
                "session_id": session_id,
                "user_id": user_id,
                "user_message": message,
                "assistant_reply": reply,
            },
            timeout=5,
        )
    except Exception as e:
        print("Erreur sauvegarde Node/MySQL:", e)

    return jsonify({"reply": reply}), 200


@app.route("/", methods=["GET"])
def health_check():
    return jsonify({"status": "ok", "service": "clarus-chat-backend-gemini-hybrid"}), 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)

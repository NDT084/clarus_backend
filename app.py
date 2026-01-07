import os
import requests
from flask import Flask, request, jsonify
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

# ----------------- CONFIG GROK -----------------
GROK_API_KEY = os.environ.get("GROK_API_KEY")  # ou XAI_API_KEY, selon ton choix
GROK_API_URL = "https://api.x.ai/v1/chat/completions"  # endpoint compatible OpenAI

# ----------------- CONFIG NODE (MySQL) -----------------
NODE_API_BASE = os.environ.get("NODE_API_BASE", "http://localhost:4000")

# ----------------- HISTORIQUE DES CONVERSATIONS -----------------
conversation_history = {}

# ---------- Fonctions locales inchangées (salutations, règles, etc.) ----------

def is_greeting(text: str) -> bool:
    t = (text or "").lower().strip()
    if not t:
        return False

    greetings = ["bonjour", "bonsoir", "salut", "bjr", "slt", "salam", "hey", "coucou"]
    return any(g in t for g in greetings) and len(t.split()) <= 3


def generate_local_reply(message: str) -> str:
    text = message.lower().strip()
    if not text:
        return "Pouvez‑vous préciser votre question ?"

    if is_greeting(text):
        return (
            "Salut !\n"
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


def infer_style_from_history(history: list[str]) -> str:
    if not history:
        return ""

    text = " ".join(history[-10:]).lower()

    if any(w in text for w in ["examen", "qcm", "question à choix", "test"]):
        return (
            "L'utilisateur semble réviser ou s'entraîner. "
            "Tu peux proposer parfois des exemples de questions ou de mini-exercices.\n"
        )

    if any(w in text for w in ["code", "python", "flutter", "javascript", "programmation"]):
        return (
            "L'utilisateur est développeur. "
            "Tu peux utiliser un vocabulaire un peu plus technique et des exemples orientés développeur.\n"
        )

    if any(w in text for w in ["je ne comprends pas", "explique simplement", "simplement"]):
        return (
            "L'utilisateur a besoin d'explications simples. "
            "Utilise des phrases très courtes et des exemples concrets.\n"
        )

    return ""

# ---------- Appel à Grok via l’API ----------

def call_grok(prompt: str) -> str:
    """
    Appelle Grok (xAI) en mode chat/completions compatible OpenAI.
    """
    if not GROK_API_KEY:
        raise RuntimeError("GROK_API_KEY non défini dans les variables d'environnement.")

    headers = {
        "Authorization": f"Bearer {GROK_API_KEY}",
        "Content-Type": "application/json",
    }

    payload = {
        "model": "grok-4",  # ou le modèle que tu as (grok-3, grok-2, etc.)
        "messages": [
            {
                "role": "system",
                "content": (
                    "Tu es Clarus, un assistant virtuel francophone spécialisé "
                    "dans les démarches administratives au Sénégal et les questions utiles du quotidien."
                ),
            },
            {
                "role": "user",
                "content": prompt,
            },
        ],
        "temperature": 0.6,
    }

    resp = requests.post(GROK_API_URL, json=payload, headers=headers, timeout=60)
    resp.raise_for_status()
    data = resp.json()

    # Format OpenAI‑like : choices[0].message.content
    try:
        return (data["choices"][0]["message"]["content"] or "").strip()
    except Exception:
        return ""


def generate_reply(message: str, session_id: str = "default", mode: str = "prof") -> str:
    text = (message or "").strip()
    if not text:
        return "Pouvez‑vous préciser votre question ?"

    try:
        history = conversation_history.get(session_id, [])

        # ---- Prompt de base ----
        base_prompt = (
            "Tu es Clarus, un assistant virtuel francophone.\n"
            "Ta priorité principale est d'aider pour les démarches administratives au Sénégal "
            "(passeport, carte d'identité, certificats, etc.).\n"
            "Tu peux aussi répondre à des questions plus générales (culture, études, informatique, "
            "mathématiques, actualité factuelle, vie quotidienne), tant que cela reste légal, "
            "utile et dans un cadre éthique.\n"
            "Tu dois refuser poliment toute demande illégale, dangereuse ou contraire à l'éthique "
            "(fraude, violence, haine, harcèlement, contenu sexuel explicite, désinformation, "
            "collecte de données personnelles sensibles, etc.), "
            "et expliquer brièvement pourquoi tu refuses.\n"
            "Si tu n'es pas sûr d'une information, dis-le clairement au lieu d'inventer, "
            "et propose éventuellement une piste générale.\n"
        )

        # ---- Mode ----
        if mode == "prof":
            base_prompt += (
                "Tu as un ton pédagogique, bienveillant et clair. "
                "Explique les démarches ou les réponses étape par étape, avec des phrases courtes.\n"
            )
        elif mode == "exam":
            base_prompt += (
                "Tu te comportes comme un examinateur. "
                "Pose des questions, propose des QCM ou des cas pratiques, "
                "et corrige les réponses de l'utilisateur. "
                "Tes réponses doivent être concises et orientées exercice.\n"
            )
        else:
            base_prompt += "Réponds de façon claire, courte et bienveillante.\n"

        # ---- Salutations / contexte ----
        user_says_hello = is_greeting(text)

        if user_says_hello and not history:
            base_prompt += (
                "L'utilisateur vient de te saluer au début de la conversation. "
                "Commence ta réponse par une salutation du même niveau de familiarité.\n"
            )
        else:
            base_prompt += (
                "Ne commence pas systématiquement par une salutation. "
                "Va directement à l'information utile, sauf si une formule de politesse est vraiment nécessaire.\n"
            )

        # ---- Historique récent ----
        if history:
            base_prompt += (
                "\nHistorique récent de la conversation. "
                "Garde la cohérence avec ce contexte et évite de répéter les mêmes explications :\n"
            )
            for h in history[-5:]:
                base_prompt += f"{h}\n"

        # ---- Style selon historique ----
        style_hint = infer_style_from_history(history)
        if style_hint:
            base_prompt += style_hint

        base_prompt += (
            "Si la question est simple ou courte, réponds simplement. "
            "Si la question est complexe, structure ta réponse en étapes ou en points clairs.\n"
        )

        base_prompt += f"\nQuestion de l'utilisateur : {text}\n"

        # ---- Appel Grok ----
        reply = call_grok(base_prompt)
        if not reply:
            reply = generate_local_reply(message)

        # ---- Sauvegarde historique ----
        conversation_history.setdefault(session_id, []).append(f"Utilisateur : {text}")
        conversation_history[session_id].append(f"Clarus : {reply}")

        return reply

    except Exception as e:
        print("Erreur Grok:", e)
        return generate_local_reply(message)


# ---------- Routes Flask inchangées ----------

@app.route("/chat", methods=["POST"])
def chat():
    data = request.get_json(silent=True) or {}
    message = data.get("message", "")
    session_id = data.get("session_id", "default")
    user_id = data.get("user_id")
    mode = data.get("mode", "prof")

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
    return jsonify({"status": "ok", "service": "clarus-chat-backend-grok"}), 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)

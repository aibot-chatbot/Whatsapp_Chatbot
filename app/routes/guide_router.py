from flask import Blueprint, request, jsonify
import os
from supabase import create_client, Client

from app.decorators.auth_decorator import token_required
from app.utils.access_control import verify_chatbot_access
from app.services.ai_router import generate_system_response, OPERATION_GUIDE_ASSISTANT

# Initialize Supabase
supabase: Client = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_SERVICE_ROLE_KEY"))

# The "Map" of the project to guide the AI with clickable links
PROJECT_MAP = """
You are the "System Guide" for this AI Chatbot Dashboard. Your job is to help the user navigate the project using clickable links.
The user is currently configuring the chatbot: "{bot_name}".
The user is currently viewing this page: "{current_page}". Use this context to understand what they are trying to do.

CRITICAL RULE: NEVER mention a page name without providing its clickable HTML link. 
If you mention "Tune AI", you MUST write it as: <a href='model_settings.html?bot_id={bot_id}' style='color: #60a5fa; text-decoration: underline;'>Tune AI</a>.

AVAILABLE LINKS (Always include ?bot_id={bot_id}):
1. 📊 Dashboard: <a href='index.html?bot_id={bot_id}' style='color: #60a5fa; text-decoration: underline;'>Dashboard</a>
2. 🤖 My Bots: <a href='bots.html' style='color: #60a5fa; text-decoration: underline;'>My Bots</a>
3. 📁 Training Data:
   - 🔗 Links / Docs: <a href='new_linkdocs.html?bot_id={bot_id}' style='color: #60a5fa; text-decoration: underline;'>Links & Docs</a>
   - 📋 Prompt: <a href='new_prompt.html?bot_id={bot_id}' style='color: #60a5fa; text-decoration: underline;'>Prompt Settings</a>
   - 📚 Help: <a href='training.html?bot_id={bot_id}' style='color: #60a5fa; text-decoration: underline;'>Help Center</a>
4. ⚙️ Behaviour:
   - 🤖 Tune AI: <a href='model_settings.html?bot_id={bot_id}' style='color: #60a5fa; text-decoration: underline;'>Tune AI</a>
   - 🧪 Test Your Bot: <a href='testbot.html?bot_id={bot_id}' style='color: #60a5fa; text-decoration: underline;'>Test Playground</a>
5. 🔌 Integration: <a href='integration.html?bot_id={bot_id}' style='color: #60a5fa; text-decoration: underline;'>WhatsApp Integration</a>

TONE & STYLE:
- Maintain an extremely professional, expert system administrator persona.
- Keep your answers highly structured, clear, and direct.
- Use bullet points, clear spacing, and bold section headers for your responses.
- Minimize emojis to only one key relevant emoji per response at most.
"""

guide_blueprint = Blueprint('guide', __name__)


def get_requested_bot_id(data=None):
    raw_bot_id = None

    if data:
        raw_bot_id = data.get('bot_id') or data.get('chatbot_id')

    raw_bot_id = raw_bot_id or request.args.get('bot_id') or request.args.get('chatbot_id')

    if not raw_bot_id:
        return None

    try:
        return int(raw_bot_id)
    except (TypeError, ValueError):
        return None


@guide_blueprint.route('/api/guide/chat', methods=['POST'])
@token_required
def guide_chat():
    import json
    from flask import Response
    data = request.json or {}
    user_message = data.get('message')
    current_page = data.get('current_page', 'dashboard')
    bot_id = get_requested_bot_id(data)

    if not bot_id:
        return jsonify({"reply": "Please select a bot first so I can use your preferred settings!"}), 400
    try:
        bot_data = verify_chatbot_access(bot_id)
        bot_name = bot_data.get("bot_name", "Unknown Bot")

        # FORCE the AI to see the map by prepending it to the message
        instructions = PROJECT_MAP.format(bot_id=bot_id, bot_name=bot_name, current_page=current_page)
        combined_prompt = f"{instructions}\n\nUser Question: {user_message}"

        from app.services.ai_router import _call_deepseek_direct
        stream = _call_deepseek_direct(
            prompt=combined_prompt,
            model="deepseek-chat",
            temperature=0.7,
            json_response=False,
            stream=True
        )

        def generate():
            try:
                for chunk in stream:
                    if hasattr(chunk.choices[0].delta, 'content') and chunk.choices[0].delta.content:
                        yield f"data: {json.dumps({'reply': chunk.choices[0].delta.content})}\n\n"
                
                yield f"data: [DONE]\n\n"
            except Exception as e:
                import logging
                logging.error(f"Error during SSE generation: {e}")
                yield f"data: {json.dumps({'error': 'Connection lost during streaming.'})}\n\n"

        return Response(generate(), mimetype='text/event-stream')

    except PermissionError as e:
        return jsonify({"reply": str(e)}), 403

    except Exception as e:
        return jsonify({
            "reply": f"""
<div style="background: rgba(239, 68, 68, 0.1); border-left: 4px solid #ef4444; padding: 12px 16px; border-radius: 8px; margin: 5px 0; font-family: 'Outfit', sans-serif;">
    <div style="display: flex; align-items: center; gap: 8px; font-weight: 600; color: #ef4444; font-size: 0.95rem; margin-bottom: 6px;">
        <span style="font-size: 1.1rem;">⚠️</span> Outer Connection Error
    </div>
    <div style="color: #e2e8f0; font-size: 0.9rem; line-height: 1.4; margin-bottom: 12px;">
        An unexpected connection issue occurred: <br/><br/> <strong>{str(e)}</strong>
    </div>
    <a href="model_settings.html?bot_id={bot_id}" style="display: inline-flex; align-items: center; justify-content: center; background: #ef4444; color: white; padding: 8px 14px; border-radius: 6px; font-size: 0.85rem; font-weight: 600; text-decoration: none; transition: background 0.2s ease;">
        Check Settings ⚙️
    </a>
</div>
"""
        }), 200


@guide_blueprint.route('/api/guide/status', methods=['GET'])
@token_required
def guide_status():
    bot_id = get_requested_bot_id()

    if not bot_id:
        return jsonify({
            "status": "error",
            "message": "bot_id is required",
            "active_provider": "None",
            "available_providers": []
        }), 400

    try:
        verify_chatbot_access(bot_id)
    except PermissionError as e:
        return jsonify({
            "status": "error",
            "message": str(e),
            "active_provider": "None",
            "available_providers": []
        }), 403
    
    # 1. Detect which providers have keys in .env
    available = []
    if os.getenv("GEMINI_API_KEY"): available.append("gemini")
    if os.getenv("GROQ_API_KEY"): available.append("groq")
    if os.getenv("DEEPSEEK_API_KEY"): available.append("deepseek")
    if os.getenv("XAI_API_KEY"): available.append("grok")
    if os.getenv("CLOUDFLARE_API_TOKEN"): available.append("cloudflare")
    if os.getenv("OPENROUTER_API_KEY"): available.extend(["openai", "anthropic", "qwen", "mistral"])
    if os.getenv("OPENAI_API_KEY"): available.append("openai")

    # 2. Get the ACTUAL selected provider from the database for this bot
    active_provider_name = "None"
    status = "setup_required"
    
    if bot_id:
        try:
            response = supabase.table('chatbots').select('ai_provider').eq('id', bot_id).single().execute()
            if response.data:
                raw_provider = response.data.get('ai_provider')
                db_provider = raw_provider.lower().strip() if raw_provider else None
                
                if not db_provider or db_provider in ["default", "none", "null", ""]:
                    status = "setup_required"
                    active_provider_name = "None (Default)"
                else:
                    # Map internal name to display name
                    display_names = {
                        "gemini": "Google Gemini",
                        "groq": "Groq",
                        "deepseek": "DeepSeek AI",
                        "grok": "Grok (xAI)",
                        "cloudflare": "Cloudflare AI",
                        "openai": "ChatGPT / OpenAI",
                        "anthropic": "Claude",
                        "qwen": "Qwen",
                        "mistral": "Mistral"
                    }
                    
                    active_provider_name = display_names.get(db_provider, db_provider.capitalize())
                    
                    # Check if the selected provider actually has a key
                    if db_provider in available:
                        status = "online"
                    else:
                        status = "key_missing"
        except Exception as e:
            print(f"Status check error: {e}")

    return jsonify({
        "status": status,
        "active_provider": active_provider_name,
        "available_providers": available
    })

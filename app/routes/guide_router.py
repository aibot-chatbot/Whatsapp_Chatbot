from flask import Blueprint, request, jsonify
import os
from openai import OpenAI
from google import genai
from supabase import create_client, Client

from app.decorators.auth_decorator import token_required
from app.utils.access_control import verify_chatbot_access

# Initialize Supabase
supabase: Client = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_SERVICE_ROLE_KEY"))

# The "Map" of the project to guide the AI with clickable links
PROJECT_MAP = """
You are the "System Guide" for this AI Chatbot Dashboard. Your job is to help the user navigate the project using clickable links.

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
    data = request.json or {}
    user_message = data.get('message')
    bot_id = get_requested_bot_id(data)

    if not bot_id:
        return jsonify({"reply": "Please select a bot first so I can use your preferred settings!"}), 400
    try:
        verify_chatbot_access(bot_id)

        # 1. Fetch the real provider AND model name from your Supabase database
        response = supabase.table('chatbots').select('ai_provider, model_name').eq('id', bot_id).single().execute()
        db_bot = response.data
        
        # Check if the user has selected a valid AI provider
        raw_provider = db_bot.get('ai_provider') if db_bot else None
        if not raw_provider or raw_provider.lower().strip() in ["default", "none", "null", ""]:
            return jsonify({
                "reply": f"""
<div style="background: rgba(245, 158, 11, 0.1); border-left: 4px solid #f59e0b; padding: 12px 16px; border-radius: 8px; margin: 5px 0; font-family: 'Outfit', sans-serif;">
    <div style="display: flex; align-items: center; gap: 8px; font-weight: 600; color: #f59e0b; font-size: 0.95rem; margin-bottom: 6px;">
        <span style="font-size: 1.1rem;">⚠️</span> System Setup Required
    </div>
    <div style="color: #e2e8f0; font-size: 0.9rem; line-height: 1.4; margin-bottom: 12px;">
        Please select a valid AI Provider to enable chat features.
    </div>
    <a href="model_settings.html?bot_id={bot_id}" style="display: inline-flex; align-items: center; justify-content: center; background: #f59e0b; color: #0f172a; padding: 8px 14px; border-radius: 6px; font-size: 0.85rem; font-weight: 600; text-decoration: none; transition: background 0.2s ease;">
        Configure Provider ⚙️
    </a>
</div>
"""
            })
            
        provider = raw_provider.lower().strip()
        db_model = db_bot.get('model_name')

        # FORCE the AI to see the map by prepending it to the message
        instructions = PROJECT_MAP.format(bot_id=bot_id)
        combined_message = f"{instructions}\n\nUser Question: {user_message}"

        ai_reply = ""

        if provider == "groq":
            api_key = os.getenv("GROQ_API_KEY")
            if not api_key:
                return jsonify({"reply": f"⚠️ **Groq API Key not found!** Please add it to your .env file."})
            
            client = OpenAI(base_url="https://api.groq.com/openai/v1", api_key=api_key)
            model = db_model or "llama-3.1-70b-versatile"
            response = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": combined_message}]
            )
            ai_reply = response.choices[0].message.content

        elif provider == "deepseek":
            api_key = os.getenv("DEEPSEEK_API_KEY")
            if not api_key:
                return jsonify({"reply": f"⚠️ **DeepSeek API Key not found!** Please add it to your .env file."})
            
            client = OpenAI(base_url="https://api.deepseek.com", api_key=api_key)
            model = db_model or "deepseek-chat"
            response = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": combined_message}]
            )
            ai_reply = response.choices[0].message.content

        elif provider == "grok":
            api_key = os.getenv("XAI_API_KEY")
            if not api_key:
                return jsonify({"reply": f"⚠️ **Grok (xAI) API Key not found!** Please add `XAI_API_KEY` to your .env file."})
            
            client = OpenAI(base_url="https://api.x.ai/v1", api_key=api_key)
            model = db_model or "grok-beta"
            response = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": combined_message}]
            )
            ai_reply = response.choices[0].message.content

        elif provider == "cloudflare":
            api_token = os.getenv("CLOUDFLARE_API_TOKEN")
            account_id = os.getenv("CLOUDFLARE_ACCOUNT_ID")
            if not api_token or not account_id:
                return jsonify({"reply": f"⚠️ **Cloudflare Settings missing!** Please add both `CLOUDFLARE_API_TOKEN` and `CLOUDFLARE_ACCOUNT_ID` to your .env file."})
            
            import requests
            model = db_model or "@cf/meta/llama-3.1-8b-instruct"
            url = f"https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/run/{model}"
            headers = {"Authorization": f"Bearer {api_token}"}
            payload = {"messages": [{"role": "user", "content": combined_message}]}
            
            response = requests.post(url, headers=headers, json=payload)
            result = response.json()
            if result.get("success"):
                ai_reply = result["result"]["response"]
            else:
                return jsonify({"reply": f"⚠️ **Cloudflare AI Error:** {result.get('errors')}"})

        else:  # Gemini
            api_key = os.getenv("GEMINI_API_KEY")
            if not api_key:
                return jsonify({"reply": f"⚠️ **Gemini API Key not found!** Please go to the <a href='model_settings.html?bot_id={bot_id}'>Tune AI</a> page to check your settings."})
            
            client = genai.Client(api_key=api_key)
            model_id = db_model or 'gemini-2.0-flash'
            response = client.models.generate_content(
                model=model_id,
                contents=combined_message,
            )
            ai_reply = response.text

        # --- SAFETY FALLBACK: If AI forgot the link, we inject it manually! ---
        links_to_check = {
            "tune ai": f"<a href='model_settings.html?bot_id={bot_id}' style='color: #60a5fa; text-decoration: underline;'>Tune AI</a>",
            "model": f"<a href='model_settings.html?bot_id={bot_id}' style='color: #60a5fa; text-decoration: underline;'>Tune AI</a>",
            "dashboard": f"<a href='index.html?bot_id={bot_id}' style='color: #60a5fa; text-decoration: underline;'>Dashboard</a>",
            "pdf": f"<a href='new_linkdocs.html?bot_id={bot_id}' style='color: #60a5fa; text-decoration: underline;'>Links & Docs</a>",
            "link": f"<a href='new_linkdocs.html?bot_id={bot_id}' style='color: #60a5fa; text-decoration: underline;'>Links & Docs</a>",
            "prompt": f"<a href='new_prompt.html?bot_id={bot_id}' style='color: #60a5fa; text-decoration: underline;'>Prompt Settings</a>",
            "whatsapp": f"<a href='integration.html?bot_id={bot_id}' style='color: #60a5fa; text-decoration: underline;'>WhatsApp Integration</a>",
            "test": f"<a href='testbot.html?bot_id={bot_id}' style='color: #60a5fa; text-decoration: underline;'>Test Playground</a>"
        }

        user_q = user_message.lower()
        extra_links = []
        for key, html_link in links_to_check.items():
            if key in user_q and html_link not in ai_reply:
                extra_links.append(html_link)
        
        if extra_links:
            ai_reply += "\n\nDirect links for you: " + " | ".join(extra_links)

        return jsonify({"reply": ai_reply})

    except PermissionError as e:
        return jsonify({"reply": str(e)}), 403

    except Exception as e:
        error_msg = str(e)
        if "429" in error_msg or "quota" in error_msg.lower():
            return jsonify({
                "reply": f"""
<div style="background: rgba(239, 68, 68, 0.1); border-left: 4px solid #ef4444; padding: 12px 16px; border-radius: 8px; margin: 5px 0; font-family: 'Outfit', sans-serif;">
    <div style="display: flex; align-items: center; gap: 8px; font-weight: 600; color: #ef4444; font-size: 0.95rem; margin-bottom: 6px;">
        <span style="font-size: 1.1rem;">⚠️</span> Quota Exceeded
    </div>
    <div style="color: #e2e8f0; font-size: 0.9rem; line-height: 1.4; margin-bottom: 12px;">
        Your selected AI model has run out of messages or exceeded its limits. Please select a different provider to continue.
    </div>
    <a href="model_settings.html?bot_id={bot_id}" style="display: inline-flex; align-items: center; justify-content: center; background: #ef4444; color: white; padding: 8px 14px; border-radius: 6px; font-size: 0.85rem; font-weight: 600; text-decoration: none; transition: background 0.2s ease;">
        Switch Provider ⚙️
    </a>
</div>
"""
            })
        
        if "API_KEY" in error_msg or "not found" in error_msg or "invalid" in error_msg.lower():
            return jsonify({
                "reply": f"""
<div style="background: rgba(239, 68, 68, 0.1); border-left: 4px solid #ef4444; padding: 12px 16px; border-radius: 8px; margin: 5px 0; font-family: 'Outfit', sans-serif;">
    <div style="display: flex; align-items: center; gap: 8px; font-weight: 600; color: #ef4444; font-size: 0.95rem; margin-bottom: 6px;">
        <span style="font-size: 1.1rem;">⚠️</span> Connection Failed
    </div>
    <div style="color: #e2e8f0; font-size: 0.9rem; line-height: 1.4; margin-bottom: 12px;">
        I'm having trouble connecting to your current AI provider. Please verify your API Key and settings.
    </div>
    <a href="model_settings.html?bot_id={bot_id}" style="display: inline-flex; align-items: center; justify-content: center; background: #ef4444; color: white; padding: 8px 14px; border-radius: 6px; font-size: 0.85rem; font-weight: 600; text-decoration: none; transition: background 0.2s ease;">
        Verify API Key ⚙️
    </a>
</div>
"""
            })
            
        return jsonify({
            "reply": f"""
<div style="background: rgba(239, 68, 68, 0.1); border-left: 4px solid #ef4444; padding: 12px 16px; border-radius: 8px; margin: 5px 0; font-family: 'Outfit', sans-serif;">
    <div style="display: flex; align-items: center; gap: 8px; font-weight: 600; color: #ef4444; font-size: 0.95rem; margin-bottom: 6px;">
        <span style="font-size: 1.1rem;">⚠️</span> Connection Error
    </div>
    <div style="color: #e2e8f0; font-size: 0.9rem; line-height: 1.4; margin-bottom: 12px;">
        An unexpected connection issue occurred. Please check your internet connection or server logs.
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
                        "cloudflare": "Cloudflare AI"
                    }
                    
                    active_provider_name = display_names.get(db_provider, "Google Gemini")
                    
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

import time
import threading

# Thread-safe storage for live workflows
# Format: { chatbot_id: { "state": "...", "message": "...", "timestamp": float, "user_phone": "..." } }
_live_workflows = {}
_lock = threading.Lock()

def update_workflow_state(chatbot_id, state, message=None, user_phone=None):
    with _lock:
        if chatbot_id not in _live_workflows:
            _live_workflows[chatbot_id] = {}
        
        _live_workflows[chatbot_id]["state"] = state
        _live_workflows[chatbot_id]["timestamp"] = time.time()
        
        if message is not None:
            _live_workflows[chatbot_id]["message"] = message
            
        if user_phone is not None:
            _live_workflows[chatbot_id]["user_phone"] = user_phone

def get_workflow_state(chatbot_id):
    with _lock:
        workflow = _live_workflows.get(chatbot_id)
        if not workflow:
            return None
            
        # Optional: Auto-clear if older than 5 minutes to prevent stale data
        if time.time() - workflow.get("timestamp", 0) > 300:
            return None
            
        return workflow

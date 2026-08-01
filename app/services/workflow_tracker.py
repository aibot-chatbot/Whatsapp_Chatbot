import time
import threading

# Thread-safe storage for live workflows
# Format: { chatbot_id: { "queue": ["..."], "last_emitted_state": "...", "message": "...", "timestamp": float, "user_phone": "..." } }
_live_workflows = {}
_lock = threading.Lock()

def update_workflow_state(chatbot_id, state, message=None, user_phone=None):
    with _lock:
        if chatbot_id not in _live_workflows:
            _live_workflows[chatbot_id] = {"queue": [], "last_emitted_state": None}
        
        # Prevent duplicate consecutive states in the queue
        if not _live_workflows[chatbot_id]["queue"] or _live_workflows[chatbot_id]["queue"][-1] != state:
            _live_workflows[chatbot_id]["queue"].append(state)
            
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
            
        # Auto-clear if older than 5 minutes to prevent stale data
        if time.time() - workflow.get("timestamp", 0) > 300:
            return None
            
        if workflow.get("queue"):
            state = workflow["queue"].pop(0)
            workflow["last_emitted_state"] = state
        else:
            state = workflow.get("last_emitted_state")
            
        if not state:
            return None
            
        return {
            "state": state,
            "message": workflow.get("message"),
            "timestamp": workflow.get("timestamp"),
            "user_phone": workflow.get("user_phone")
        }

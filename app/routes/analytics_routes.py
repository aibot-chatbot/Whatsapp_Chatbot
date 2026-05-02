from flask import Blueprint, jsonify
import shelve
import os
from datetime import datetime, timedelta
from app.decorators.auth_decorator import token_required

analytics_blueprint = Blueprint("analytics", __name__)

CHAT_HISTORY_DB = "chat_history_db"

@analytics_blueprint.route("/api/analytics", methods=["GET"])
@token_required
def get_analytics():
    try:
        total_users = 0
        total_messages = 0
        recent_history = []
        
        # We will generate a chart showing messages per day for the last 7 days
        today = datetime.now().date()
        date_counts = {(today - timedelta(days=i)).isoformat(): 0 for i in range(6, -1, -1)}

        if os.path.exists(CHAT_HISTORY_DB + ".dat") or os.path.exists(CHAT_HISTORY_DB + ".dir") or os.path.exists(CHAT_HISTORY_DB + ".db") or os.path.exists(CHAT_HISTORY_DB):
            with shelve.open(CHAT_HISTORY_DB, flag='r') as db:
                keys = [k for k in db.keys() if k != 'web_testbot_session' and not k.startswith('test_')]
                total_users = len(keys)
                
                user_last_messages = []

                for user_id in keys:
                    history = db[user_id]
                    if not history:
                        continue
                        
                    total_messages += sum(1 for msg in history if msg.get("role") == "user")
                    
                    last_msg = history[-1]
                    timestamp_str = last_msg.get("timestamp")
                    
                    if timestamp_str:
                        try:
                            msg_date = datetime.fromisoformat(timestamp_str).date()
                            msg_date_str = msg_date.isoformat()
                            if msg_date_str in date_counts:
                                date_counts[msg_date_str] += 1
                        except:
                            pass
                            
                    user_last_messages.append({
                        "user": user_id[-4:] if len(user_id) > 4 else user_id,  # Mask full phone number
                        "status": "Active" if timestamp_str else "Completed",
                        "timestamp": timestamp_str or "2020-01-01T00:00:00",
                        "last_content": last_msg.get("content", "")
                    })
                    
                    # Also scan the rest of the user's history for the chart
                    for msg in history[:-1]:
                        if msg.get("role") == "user" and msg.get("timestamp"):
                            try:
                                msg_date = datetime.fromisoformat(msg.get("timestamp")).date()
                                msg_date_str = msg_date.isoformat()
                                if msg_date_str in date_counts:
                                    date_counts[msg_date_str] += 1
                            except:
                                pass

                # Sort by timestamp descending
                user_last_messages.sort(key=lambda x: x["timestamp"], reverse=True)
                recent_history = user_last_messages[:4]

        # Formatting data for charts (ordered chronologically)
        chart_labels = []
        chart_data = []
        for d in sorted(date_counts.keys()):
            # e.g., 'Mon', 'Tue'
            day_name = datetime.fromisoformat(d).strftime('%a')
            chart_labels.append(day_name)
            chart_data.append(date_counts[d])

        return jsonify({
            "status": "success",
            "data": {
                "total_users": total_users,
                "total_messages": total_messages,
                "recent_history": recent_history,
                "chart": {
                    "labels": chart_labels,
                    "data": chart_data
                }
            }
        }), 200

    except Exception as e:
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500

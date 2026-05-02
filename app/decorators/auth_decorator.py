from functools import wraps
from flask import request, jsonify
import jwt
import os

SECRET_KEY = os.getenv("JWT_SECRET", "super-secret-default-key-please-change")

def token_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = None
        
        if "Authorization" in request.headers:
            parts = request.headers["Authorization"].split()
            if len(parts) == 2 and parts[0] == "Bearer":
                token = parts[1]
                
        if not token:
            return jsonify({"status": "error", "message": "Token is missing!"}), 401
            
        try:
            data = jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
            # You can inject current_user into kwargs here if needed
        except jwt.ExpiredSignatureError:
            return jsonify({"status": "error", "message": "Token has expired! Please log in again."}), 401
        except jwt.InvalidTokenError:
            return jsonify({"status": "error", "message": "Invalid token!"}), 401
            
        return f(*args, **kwargs)
    return decorated

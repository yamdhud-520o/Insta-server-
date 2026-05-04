import time
import os
import json
from datetime import datetime
from threading import Thread
from functools import wraps
from instagrapi import Client
from flask import Flask, request, render_template_string, redirect, url_for, session, jsonify, flash
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = os.urandom(24)
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

@app.after_request
def add_header(response):
    response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response

active_threads = {}

# Database Models
class Admin(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    password = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(db.String(100), unique=True, nullable=False)
    instagram_username = db.Column(db.String(100))
    sender_name = db.Column(db.String(100))
    is_active = db.Column(db.Boolean, default=True)
    is_banned = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_active = db.Column(db.DateTime, default=datetime.utcnow)

class MessageThread(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    sender_name = db.Column(db.String(100))
    target_username = db.Column(db.String(100))
    group_name = db.Column(db.String(200))
    message_type = db.Column(db.String(20))
    status = db.Column(db.String(20), default='running')
    messages_sent = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    user = db.relationship('User', backref=db.backref('threads', lazy=True))

class Notification(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    message = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    is_active = db.Column(db.Boolean, default=True)

with app.app_context():
    db.create_all()
    admin = Admin.query.filter_by(username='RAJ THAKUR').first()
    if not admin:
        admin = Admin(username='RAJ THAKUR', password=generate_password_hash('RAJ THAKUR'))
        db.session.add(admin)
        db.session.commit()

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_logged_in' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'admin_logged_in' not in session:
            return redirect(url_for('admin_login'))
        return f(*args, **kwargs)
    return decorated_function

def instagram_login(username, password):
    cl = Client()
    try:
        cl.login(username, password)
        return cl
    except Exception as e:
        print(f"Login failed: {e}")
        return None

def get_user_groups(cl):
    try:
        threads = cl.direct_threads(amount=50)
        groups = []
        for thread in threads:
            if thread.is_group:
                groups.append({
                    'thread_id': thread.id,
                    'name': thread.thread_title or 'Unnamed Group',
                    'users_count': len(thread.users)
                })
        return groups
    except Exception as e:
        print(f"Error fetching groups: {e}")
        return []

def send_inbox_message(cl, target_username, sender_name, messages, delay, thread_record_id):
    try:
        user_id = cl.user_id_from_username(target_username)
        index = 0
        while thread_record_id in active_threads and active_threads[thread_record_id]:
            with app.app_context():
                thread_record = MessageThread.query.get(thread_record_id)
                if thread_record and thread_record.status == 'stopped':
                    break
                full_message = f"{sender_name} {messages[index]}"
                cl.direct_send(full_message, [user_id])
                if thread_record:
                    thread_record.messages_sent += 1
                    db.session.commit()
            time.sleep(delay)
            index = (index + 1) % len(messages)
    except Exception as e:
        print(f"Error sending message to inbox: {e}")

def send_group_message(cl, thread_id, sender_name, messages, delay, thread_record_id):
    try:
        index = 0
        while thread_record_id in active_threads and active_threads[thread_record_id]:
            with app.app_context():
                thread_record = MessageThread.query.get(thread_record_id)
                if thread_record and thread_record.status == 'stopped':
                    break
                full_message = f"{sender_name} {messages[index]}"
                cl.direct_send(full_message, thread_ids=[thread_id])
                if thread_record:
                    thread_record.messages_sent += 1
                    db.session.commit()
            time.sleep(delay)
            index = (index + 1) % len(messages)
    except Exception as e:
        print(f"Error sending message to group: {e}")

# ============== BASE STYLES ==============
BASE_STYLES = """
<style>
    @import url('https://fonts.googleapis.com/css2?family=Orbitron:wght@400;700;900&family=Poppins:wght@300;400;600;700&display=swap');
    
    * { margin: 0; padding: 0; box-sizing: border-box; }
    
    body {
        font-family: 'Poppins', sans-serif;
        background: #0a0a1a;
        background-image: 
            radial-gradient(ellipse at top, rgba(138,43,226,0.3) 0%, transparent 50%),
            radial-gradient(ellipse at bottom, rgba(0,100,0,0.2) 0%, transparent 50%);
        min-height: 100vh;
        color: #fff;
        overflow-x: hidden;
    }
    
    .bg-animation {
        position: fixed;
        top: 0;
        left: 0;
        width: 100%;
        height: 100%;
        pointer-events: none;
        z-index: 0;
        background: url('data:image/svg+xml,<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"><defs><radialGradient id="g"><stop offset="0%" stop-color="%2300ff00" stop-opacity="0.1"/><stop offset="100%" stop-color="transparent"/></radialGradient></defs><circle cx="50" cy="50" r="50" fill="url(%23g)"/></svg>');
        background-size: 300px 300px;
        animation: bgMove 20s linear infinite;
    }
    
    @keyframes bgMove {
        0% { background-position: 0 0; }
        100% { background-position: 300px 300px; }
    }
    
    .main-container {
        position: relative;
        z-index: 1;
        min-height: 100vh;
        padding: 20px;
    }
    
    .flash-messages {
        position: fixed;
        top: 20px;
        right: 20px;
        z-index: 1000;
    }
    
    .flash {
        padding: 15px 25px;
        border-radius: 10px;
        margin-bottom: 10px;
        animation: slideIn 0.5s ease;
        font-weight: 600;
    }
    
    .flash.success {
        background: linear-gradient(135deg, #00ff00, #00cc00);
        color: #000;
    }
    
    .flash.error {
        background: linear-gradient(135deg, #ff0000, #cc0000);
        color: #fff;
    }
    
    @keyframes slideIn {
        from { transform: translateX(100%); opacity: 0; }
        to { transform: translateX(0); opacity: 1; }
    }
    
    .rainbow-text {
        background: linear-gradient(90deg, #ff0000, #ff7f00, #ffff00, #00ff00, #00ffff, #0000ff, #8b00ff);
        background-size: 400% 400%;
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        background-clip: text;
        animation: rainbow 3s ease infinite;
    }
    
    @keyframes rainbow {
        0% { background-position: 0% 50%; }
        50% { background-position: 100% 50%; }
        100% { background-position: 0% 50%; }
    }
    
    .glow-box {
        position: relative;
        background: #0a0a15;
        border-radius: 25px;
        padding: 35px;
        box-shadow: 0 0 50px rgba(0, 255, 0, 0.2);
        border: 4px solid transparent;
        background-image: linear-gradient(#0a0a15, #0a0a15), linear-gradient(45deg, #ff0000, #ff7f00, #ffff00, #00ff00, #00ffff, #0000ff, #8b00ff, #ff0000);
        background-origin: border-box;
        background-clip: padding-box, border-box;
        animation: borderRotate 5s linear infinite;
    }
    
    @keyframes borderRotate {
        0% { filter: hue-rotate(0deg); }
        100% { filter: hue-rotate(360deg); }
    }
    
    .footer {
        text-align: center;
        padding: 20px;
        margin-top: 40px;
        font-family: 'Orbitron', sans-serif;
    }
    
    .footer-text {
        font-size: 14px;
        color: #00ff00;
        text-shadow: 0 0 10px #00ff00, 0 0 20px #00ff00;
    }
    
    .btn {
        padding: 15px 35px;
        border: none;
        border-radius: 50px;
        font-size: 16px;
        font-weight: 700;
        cursor: pointer;
        transition: all 0.3s ease;
        text-transform: uppercase;
        letter-spacing: 2px;
        text-decoration: none;
        display: inline-block;
        font-family: 'Orbitron', sans-serif;
    }
    
    .btn-primary {
        background: linear-gradient(135deg, #00ff00, #00cc00, #00ff00);
        background-size: 200% 200%;
        color: #000;
        box-shadow: 0 5px 25px rgba(0, 255, 0, 0.4);
        animation: btnGlow 3s ease infinite;
    }
    
    @keyframes btnGlow {
        0%, 100% { background-position: 0% 50%; box-shadow: 0 5px 25px rgba(0, 255, 0, 0.4); }
        50% { background-position: 100% 50%; box-shadow: 0 5px 35px rgba(0, 255, 0, 0.6); }
    }
    
    .btn-danger {
        background: linear-gradient(135deg, #ff0000, #cc0000);
        color: #fff;
        box-shadow: 0 5px 25px rgba(255, 0, 0, 0.3);
    }
    
    .btn-info {
        background: linear-gradient(135deg, #00bfff, #0080ff);
        color: #fff;
        box-shadow: 0 5px 25px rgba(0, 191, 255, 0.3);
    }
    
    .btn:hover {
        transform: translateY(-5px) scale(1.02);
        box-shadow: 0 15px 40px rgba(0, 255, 0, 0.5);
    }
    
    .input-field {
        width: 100%;
        padding: 18px 25px;
        border: 2px solid #00ff00;
        border-radius: 50px;
        background: rgba(0, 20, 0, 0.8);
        color: #00ff00;
        font-size: 16px;
        transition: all 0.3s ease;
        margin-bottom: 20px;
        font-family: 'Poppins', sans-serif;
    }
    
    .input-field:focus {
        outline: none;
        border-color: #00ffff;
        box-shadow: 0 0 25px rgba(0, 255, 255, 0.5), inset 0 0 10px rgba(0, 255, 0, 0.1);
    }
    
    .input-field::placeholder {
        color: rgba(0, 255, 0, 0.4);
    }
    
    textarea.input-field {
        min-height: 120px;
        resize: vertical;
        border-radius: 20px;
    }
    
    select.input-field {
        cursor: pointer;
    }
    
    select.input-field option {
        background: #0a0a1a;
        color: #00ff00;
    }
    
    label {
        display: block;
        margin-bottom: 10px;
        font-size: 14px;
        color: #00ff00;
        text-transform: uppercase;
        letter-spacing: 2px;
        text-shadow: 0 0 5px rgba(0, 255, 0, 0.5);
    }
</style>
"""

# ============== LOGIN PAGE ==============
LOGIN_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>RAJ SINGH - Login</title>
    """ + BASE_STYLES + """
    <style>
        .login-container {
            display: flex;
            justify-content: center;
            align-items: center;
            min-height: 100vh;
            padding: 20px;
        }
        
        .login-box {
            width: 100%;
            max-width: 420px;
            text-align: center;
            background: linear-gradient(180deg, #0d0d1a 0%, #1a1a2e 50%, #0d0d1a 100%);
        }
        
        .logo-icon {
            font-size: 80px;
            animation: pulse 2s infinite;
            display: block;
            margin-bottom: 15px;
        }
        
        @keyframes pulse {
            0%, 100% { transform: scale(1); }
            50% { transform: scale(1.1); }
        }
        
        .welcome-title {
            font-family: 'Orbitron', sans-serif;
            font-size: 20px;
            margin: 15px 0;
            text-shadow: 0 0 20px #00ff00;
        }
        
        .heart-icon {
            color: #ff0000;
            animation: heartbeat 1.5s infinite;
            font-size: 28px;
        }
        
        @keyframes heartbeat {
            0%, 100% { transform: scale(1); }
            50% { transform: scale(1.3); }
        }
        
        .candle-container {
            display: flex;
            justify-content: center;
            gap: 12px;
            margin: 25px 0;
        }
        
        .candle {
            width: 12px;
            height: 50px;
            background: linear-gradient(to bottom, #ffcc00, #ff9900);
            border-radius: 4px 4px 0 0;
            position: relative;
        }
        
        .candle::before {
            content: '';
            position: absolute;
            top: -18px;
            left: 50%;
            transform: translateX(-50%);
            width: 10px;
            height: 18px;
            background: radial-gradient(ellipse at center, #fff 0%, #ffcc00 30%, #ff6600 60%, transparent 100%);
            border-radius: 50% 50% 20% 20%;
            animation: flicker 0.3s infinite alternate;
        }
        
        @keyframes flicker {
            0% { transform: translateX(-50%) scale(1) rotate(-3deg); }
            100% { transform: translateX(-50%) scale(1.1) rotate(3deg); }
        }
        
        .candle::after {
            content: '';
            position: absolute;
            top: -4px;
            left: 50%;
            transform: translateX(-50%);
            width: 2px;
            height: 6px;
            background: #333;
        }
        
        .admin-link {
            display: inline-block;
            margin-top: 20px;
            color: #ff00ff;
            text-decoration: none;
            font-size: 14px;
            transition: all 0.3s ease;
            text-shadow: 0 0 10px #ff00ff;
        }
        
        .admin-link:hover {
            color: #00ffff;
            text-shadow: 0 0 15px #00ffff;
        }
        
        .input-field {
            background: rgba(0, 0, 0, 0.6) !important;
            border: 2px solid #00ff00 !important;
        }
    </style>
</head>
<body>
    <div class="bg-animation"></div>
    
    {% with messages = get_flashed_messages(with_categories=true) %}
        {% if messages %}
        <div class="flash-messages">
            {% for category, message in messages %}
            <div class="flash {{ category }}">{{ message }}</div>
            {% endfor %}
        </div>
        {% endif %}
    {% endwith %}
    
    <div class="login-container">
        <div class="login-box glow-box">
            <span class="logo-icon">🔐</span>
            <h1 class="welcome-title rainbow-text">
                ✨[=WELCOME TO RAJ👑THAKUR=]✨
            </h1>
            <h2 style="color: #00ff00; font-family: 'Orbitron', sans-serif; margin-bottom: 15px;">
                RAJ SINGH <span class="heart-icon">❤️</span>
            </h2>
            
            <div class="candle-container">
                <div class="candle"></div>
                <div class="candle"></div>
                <div class="candle"></div>
                <div class="candle"></div>
                <div class="candle"></div>
            </div>
            
            <form method="POST">
                <label>👤 Username</label>
                <input type="text" name="username" class="input-field" placeholder="Enter Username" required>
                
                <label>🔒 Password</label>
                <input type="password" name="password" class="input-field" placeholder="Enter Password" required>
                
                <button type="submit" class="btn btn-primary" style="width: 100%; margin-top: 15px;">
                    🚀 LOGIN
                </button>
            </form>
            
            <a href="/admin/login" class="admin-link">⚙️ Admin Panel</a>
        </div>
    </div>
    
    <footer class="footer">
        <p class="footer-text rainbow-text">◉[=>2025-2026 | All Rights Reserved By Raj✘ Thakur 👑<=]◉</p>
    </footer>
</body>
</html>
"""

# ============== DASHBOARD PAGE ==============
DASHBOARD_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>RAJ SINGH - Dashboard</title>
    """ + BASE_STYLES + """
    <style>
        .header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 20px;
            background: rgba(0, 0, 0, 0.5);
            border-radius: 15px;
            margin-bottom: 30px;
            flex-wrap: wrap;
            gap: 15px;
        }
        
        .header-title {
            font-family: 'Orbitron', sans-serif;
            font-size: 22px;
            color: #00ff00;
            text-shadow: 0 0 10px #00ff00;
        }
        
        .header-right {
            display: flex;
            align-items: center;
            gap: 20px;
        }
        
        .notification-bell {
            font-size: 28px;
            cursor: pointer;
            animation: ring 2s infinite;
            text-decoration: none;
            position: relative;
        }
        
        @keyframes ring {
            0%, 100% { transform: rotate(0); }
            10%, 30% { transform: rotate(15deg); }
            20%, 40% { transform: rotate(-15deg); }
            50% { transform: rotate(0); }
        }
        
        .notification-badge {
            position: absolute;
            top: -8px;
            right: -8px;
            background: #ff0000;
            color: #fff;
            font-size: 12px;
            padding: 3px 8px;
            border-radius: 50%;
        }
        
        .dashboard-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
            gap: 25px;
            padding: 20px 0;
        }
        
        .dashboard-card {
            position: relative;
            background: linear-gradient(135deg, rgba(0, 0, 0, 0.8), rgba(20, 20, 40, 0.8));
            border-radius: 20px;
            padding: 40px 30px;
            text-align: center;
            cursor: pointer;
            transition: all 0.4s ease;
            overflow: hidden;
            text-decoration: none;
            display: block;
        }
        
        .dashboard-card::before {
            content: '';
            position: absolute;
            top: 0;
            left: 0;
            right: 0;
            bottom: 0;
            border-radius: 20px;
            padding: 3px;
            background: var(--card-gradient);
            -webkit-mask: linear-gradient(#fff 0 0) content-box, linear-gradient(#fff 0 0);
            mask: linear-gradient(#fff 0 0) content-box, linear-gradient(#fff 0 0);
            -webkit-mask-composite: xor;
            mask-composite: exclude;
        }
        
        .dashboard-card:hover {
            transform: translateY(-10px) scale(1.02);
            box-shadow: 0 20px 40px rgba(0, 0, 0, 0.5);
        }
        
        .card-admin { --card-gradient: linear-gradient(45deg, #8b0000, #ff4500); }
        .card-message { --card-gradient: linear-gradient(45deg, #0000cd, #00bfff); }
        .card-connect { --card-gradient: linear-gradient(45deg, #006400, #00ff00); }
        .card-notification { --card-gradient: linear-gradient(45deg, #800080, #ff00ff); }
        
        .card-icon {
            font-size: 70px;
            margin-bottom: 20px;
            display: block;
        }
        
        .card-title {
            font-family: 'Orbitron', sans-serif;
            font-size: 18px;
            color: #fff;
            margin-bottom: 10px;
            text-transform: uppercase;
            letter-spacing: 2px;
        }
        
        .card-desc {
            font-size: 14px;
            color: rgba(255, 255, 255, 0.7);
        }
        
        .notification-popup {
            position: fixed;
            bottom: 80px;
            right: 20px;
            max-width: 350px;
            z-index: 100;
        }
        
        .notif-item {
            background: linear-gradient(135deg, #1a1a2e, #16213e);
            border-left: 4px solid #00ff00;
            padding: 15px;
            margin-bottom: 10px;
            border-radius: 10px;
            animation: slideInRight 0.5s ease;
        }
        
        @keyframes slideInRight {
            from { transform: translateX(100%); opacity: 0; }
            to { transform: translateX(0); opacity: 1; }
        }
        
        .notif-title {
            color: #00ff00;
            font-weight: 600;
            margin-bottom: 5px;
        }
        
        .notif-message {
            font-size: 13px;
            color: rgba(255, 255, 255, 0.8);
        }
    </style>
</head>
<body>
    <div class="bg-animation"></div>
    <div class="main-container">
        <div class="header">
            <h1 class="header-title rainbow-text">RAJ SINGH - Dashboard 🎯</h1>
            <div class="header-right">
                <a href="/notifications" class="notification-bell">
                    🔔
                    {% if notifications %}
                    <span class="notification-badge">{{ notifications|length }}</span>
                    {% endif %}
                </a>
                <a href="/logout" class="btn btn-danger">LOGOUT</a>
            </div>
        </div>
        
        <div class="dashboard-grid">
            <a href="/admin/login" class="dashboard-card card-admin">
                <span class="card-icon">⚙️</span>
                <h2 class="card-title">Admin Panel</h2>
                <p class="card-desc">Manage system</p>
            </a>
            
            <a href="/message_box" class="dashboard-card card-message">
                <span class="card-icon">💬</span>
                <h2 class="card-title">Message Box</h2>
                <p class="card-desc">Send messages</p>
            </a>
            
            <a href="/connect" class="dashboard-card card-connect">
                <span class="card-icon">🔗</span>
                <h2 class="card-title">Connect</h2>
                <p class="card-desc">Social links</p>
            </a>
            
            <a href="/notifications" class="dashboard-card card-notification">
                <span class="card-icon">🔔</span>
                <h2 class="card-title">Notifications</h2>
                <p class="card-desc">View updates</p>
            </a>
        </div>
        
        {% if notifications %}
        <div class="notification-popup">
            {% for notif in notifications[:3] %}
            <div class="notif-item">
                <div class="notif-title">📢 {{ notif.title }}</div>
                <div class="notif-message">{{ notif.message[:80] }}{% if notif.message|length > 80 %}...{% endif %}</div>
            </div>
            {% endfor %}
        </div>
        {% endif %}
    </div>
    
    <footer class="footer">
        <p class="footer-text rainbow-text">◉[=>2025-2026 | All Rights Reserved By Raj✘ Thakur 👑<=]◉</p>
    </footer>
</body>
</html>
"""

# ============== MESSAGE BOX PAGE ==============
MESSAGE_BOX_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>RAJ SINGH - Message Box</title>
    """ + BASE_STYLES + """
    <style>
        .header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 20px;
            background: rgba(0, 0, 0, 0.5);
            border-radius: 15px;
            margin-bottom: 30px;
            flex-wrap: wrap;
            gap: 15px;
        }
        
        .header-title {
            font-family: 'Orbitron', sans-serif;
            font-size: 22px;
            color: #00bfff;
            text-shadow: 0 0 10px #00bfff;
        }
        
        .content-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(350px, 1fr));
            gap: 25px;
        }
        
        .section-title {
            font-family: 'Orbitron', sans-serif;
            font-size: 18px;
            margin-bottom: 20px;
            padding-bottom: 10px;
            border-bottom: 2px solid #00ff00;
        }
        
        .thread-list {
            max-height: 400px;
            overflow-y: auto;
        }
        
        .thread-item {
            background: rgba(0, 0, 0, 0.5);
            padding: 15px;
            border-radius: 10px;
            margin-bottom: 10px;
            border-left: 4px solid;
            animation: randomColor 5s infinite;
        }
        
        .thread-item:nth-child(1) { border-color: #ff0000; }
        .thread-item:nth-child(2) { border-color: #00ff00; }
        .thread-item:nth-child(3) { border-color: #0000ff; }
        .thread-item:nth-child(4) { border-color: #ffff00; }
        .thread-item:nth-child(5) { border-color: #ff00ff; }
        .thread-item:nth-child(6) { border-color: #00ffff; }
        
        .thread-info {
            display: flex;
            justify-content: space-between;
            align-items: center;
            flex-wrap: wrap;
            gap: 10px;
        }
        
        .thread-details span {
            display: block;
            font-size: 13px;
            margin-bottom: 5px;
        }
        
        .thread-status {
            padding: 5px 15px;
            border-radius: 20px;
            font-size: 12px;
            font-weight: 600;
        }
        
        .status-running {
            background: linear-gradient(135deg, #00ff00, #00cc00);
            color: #000;
            animation: pulse 1s infinite;
        }
        
        .status-stopped {
            background: linear-gradient(135deg, #ff0000, #cc0000);
            color: #fff;
        }
        
        .group-list {
            max-height: 200px;
            overflow-y: auto;
            margin-bottom: 15px;
        }
        
        .group-item {
            background: rgba(0, 255, 0, 0.1);
            padding: 12px;
            border-radius: 8px;
            margin-bottom: 8px;
            cursor: pointer;
            transition: all 0.3s ease;
            border: 1px solid transparent;
        }
        
        .group-item:hover {
            background: rgba(0, 255, 0, 0.2);
            border-color: #00ff00;
        }
        
        .group-item.selected {
            background: rgba(0, 255, 0, 0.3);
            border-color: #00ff00;
        }
        
        .group-name {
            font-weight: 600;
            color: #00ff00;
        }
        
        .group-count {
            font-size: 12px;
            color: rgba(255, 255, 255, 0.7);
        }
        
        .live-indicator {
            display: inline-block;
            width: 10px;
            height: 10px;
            background: #00ff00;
            border-radius: 50%;
            margin-right: 8px;
            animation: blink 1s infinite;
        }
        
        @keyframes blink {
            0%, 100% { opacity: 1; }
            50% { opacity: 0.3; }
        }
        
        .msg-count {
            color: #00ffff;
            font-weight: 600;
        }
    </style>
</head>
<body>
    <div class="bg-animation"></div>
    
    {% with messages = get_flashed_messages(with_categories=true) %}
        {% if messages %}
        <div class="flash-messages">
            {% for category, message in messages %}
            <div class="flash {{ category }}">{{ message }}</div>
            {% endfor %}
        </div>
        {% endif %}
    {% endwith %}
    
    <div class="main-container">
        <div class="header">
            <h1 class="header-title">💬 MESSAGE BOX</h1>
            <a href="/dashboard" class="btn btn-info">🏠 Dashboard</a>
        </div>
        
        <div class="content-grid">
            <!-- Instagram Login & Send Form -->
            <div class="glow-box">
                <h2 class="section-title rainbow-text">📱 Instagram Login</h2>
                
                {% if not ig_logged_in %}
                <form method="POST">
                    <input type="hidden" name="action" value="login_instagram">
                    <label>👤 Instagram Username</label>
                    <input type="text" name="ig_username" class="input-field" placeholder="Enter IG Username" required>
                    
                    <label>🔒 Instagram Password</label>
                    <input type="password" name="ig_password" class="input-field" placeholder="Enter IG Password" required>
                    
                    <button type="submit" class="btn btn-primary" style="width: 100%;">🔓 Login Instagram</button>
                </form>
                {% else %}
                <div style="text-align: center; padding: 20px;">
                    <span style="font-size: 50px;">✅</span>
                    <p style="color: #00ff00; font-size: 18px; margin-top: 10px;">Instagram Connected!</p>
                </div>
                
                <form method="POST">
                    <input type="hidden" name="action" value="send_message">
                    
                    <label>📝 Sender Name</label>
                    <input type="text" name="sender_name" class="input-field" placeholder="Enter Sender Name" required>
                    
                    <label>📨 Send To</label>
                    <select name="message_type" id="message_type" class="input-field" onchange="toggleTarget()">
                        <option value="inbox">📥 Inbox (DM)</option>
                        <option value="group">👥 Group</option>
                    </select>
                    
                    <div id="inbox_target">
                        <label>🎯 Target Username</label>
                        <input type="text" name="target_username" class="input-field" placeholder="Enter Target Username">
                    </div>
                    
                    <div id="group_target" style="display: none;">
                        <label>👥 Select Group (Click to Select)</label>
                        <div class="group-list">
                            {% for group in groups %}
                            <div class="group-item" onclick="selectGroup('{{ group.thread_id }}', '{{ group.name }}', this)">
                                <div class="group-name">🔒 {{ group.name }}</div>
                                <div class="group-count">{{ group.users_count }} members</div>
                            </div>
                            {% endfor %}
                            {% if not groups %}
                            <p style="color: rgba(255,255,255,0.5); text-align: center;">No groups found</p>
                            {% endif %}
                        </div>
                        <input type="hidden" name="group_thread_id" id="group_thread_id">
                        <input type="hidden" name="group_name" id="group_name">
                    </div>
                    
                    <label>💬 Messages (One per line)</label>
                    <textarea name="messages" class="input-field" placeholder="Enter your messages here...
Each line is a separate message" required></textarea>
                    
                    <label>⏱️ Delay (Seconds)</label>
                    <input type="number" name="delay" class="input-field" value="10" min="1" required>
                    
                    <button type="submit" class="btn btn-primary" style="width: 100%;">🚀 START SENDING</button>
                </form>
                {% endif %}
            </div>
            
            <!-- Active Threads -->
            <div class="glow-box">
                <h2 class="section-title rainbow-text">📊 Your Active Threads</h2>
                <div class="thread-list">
                    {% for thread in user_threads %}
                    <div class="thread-item">
                        <div class="thread-info">
                            <div class="thread-details">
                                <span>👤 <strong>Sender:</strong> {{ thread.sender_name }}</span>
                                {% if thread.message_type == 'inbox' %}
                                <span>🎯 <strong>Target:</strong> {{ thread.target_username }}</span>
                                {% else %}
                                <span>👥 <strong>Group:</strong> {{ thread.group_name or 'Unknown' }}</span>
                                {% endif %}
                                <span>📨 <strong>Messages Sent:</strong> <span class="msg-count">{{ thread.messages_sent }}</span></span>
                            </div>
                            <div>
                                {% if thread.status == 'running' %}
                                <span class="thread-status status-running"><span class="live-indicator"></span>LIVE</span>
                                <br><br>
                                <a href="/stop_thread/{{ thread.id }}" class="btn btn-danger" style="padding: 5px 15px; font-size: 12px;">⏹️ STOP</a>
                                {% else %}
                                <span class="thread-status status-stopped">STOPPED</span>
                                {% endif %}
                            </div>
                        </div>
                    </div>
                    {% endfor %}
                    
                    {% if not user_threads %}
                    <p style="color: rgba(255,255,255,0.5); text-align: center; padding: 30px;">No active threads yet</p>
                    {% endif %}
                </div>
            </div>
        </div>
    </div>
    
    <footer class="footer">
        <p class="footer-text rainbow-text">◉[=>2025-2026 | All Rights Reserved By Raj✘ Thakur 👑<=]◉</p>
    </footer>
    
    <script>
        function toggleTarget() {
            var type = document.getElementById('message_type').value;
            document.getElementById('inbox_target').style.display = type === 'inbox' ? 'block' : 'none';
            document.getElementById('group_target').style.display = type === 'group' ? 'block' : 'none';
        }
        
        function selectGroup(threadId, groupName, element) {
            document.querySelectorAll('.group-item').forEach(el => el.classList.remove('selected'));
            element.classList.add('selected');
            document.getElementById('group_thread_id').value = threadId;
            document.getElementById('group_name').value = groupName;
        }
    </script>
</body>
</html>
"""

# ============== CONNECT PAGE ==============
CONNECT_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>RAJ SINGH - Connect</title>
    """ + BASE_STYLES + """
    <style>
        .header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 20px;
            background: rgba(0, 0, 0, 0.5);
            border-radius: 15px;
            margin-bottom: 30px;
            flex-wrap: wrap;
            gap: 15px;
        }
        
        .header-title {
            font-family: 'Orbitron', sans-serif;
            font-size: 22px;
            color: #00ff00;
            text-shadow: 0 0 10px #00ff00;
        }
        
        .connect-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
            gap: 20px;
            max-width: 800px;
            margin: 0 auto;
        }
        
        .connect-card {
            position: relative;
            display: flex;
            align-items: center;
            gap: 20px;
            padding: 25px;
            background: rgba(0, 0, 0, 0.6);
            border-radius: 15px;
            text-decoration: none;
            transition: all 0.4s ease;
            overflow: hidden;
        }
        
        .connect-card::before {
            content: '';
            position: absolute;
            top: 0;
            left: 0;
            right: 0;
            bottom: 0;
            border-radius: 15px;
            padding: 3px;
            background: var(--card-color);
            -webkit-mask: linear-gradient(#fff 0 0) content-box, linear-gradient(#fff 0 0);
            mask: linear-gradient(#fff 0 0) content-box, linear-gradient(#fff 0 0);
            -webkit-mask-composite: xor;
            mask-composite: exclude;
        }
        
        .connect-card:hover {
            transform: translateY(-5px) scale(1.02);
            box-shadow: 0 15px 30px rgba(0, 0, 0, 0.4);
        }
        
        .card-whatsapp1 { --card-color: linear-gradient(45deg, #25D366, #128C7E); }
        .card-whatsapp2 { --card-color: linear-gradient(45deg, #075E54, #25D366); }
        .card-whatsapp3 { --card-color: linear-gradient(45deg, #128C7E, #25D366); }
        .card-facebook { --card-color: linear-gradient(45deg, #1877F2, #3b5998); }
        .card-instagram { --card-color: linear-gradient(45deg, #833AB4, #FD1D1D, #F77737); }
        
        .connect-icon {
            font-size: 50px;
            animation: bounce 2s infinite;
        }
        
        @keyframes bounce {
            0%, 100% { transform: translateY(0); }
            50% { transform: translateY(-10px); }
        }
        
        .connect-info {
            flex: 1;
        }
        
        .connect-title {
            font-family: 'Orbitron', sans-serif;
            font-size: 16px;
            color: #fff;
            margin-bottom: 5px;
        }
        
        .connect-desc {
            font-size: 13px;
            color: rgba(255, 255, 255, 0.7);
        }
        
        .connect-arrow {
            font-size: 24px;
            color: #00ff00;
        }
    </style>
</head>
<body>
    <div class="bg-animation"></div>
    <div class="main-container">
        <div class="header">
            <h1 class="header-title rainbow-text">🔗 CONNECT WITH US</h1>
            <a href="/dashboard" class="btn btn-info">🏠 Dashboard</a>
        </div>
        
        <div class="connect-grid">
            <a href="https://chat.whatsapp.com/Fr7p4QjwEJDE5xsBQfmrbl" target="_blank" class="connect-card card-whatsapp1">
                <span class="connect-icon">💬</span>
                <div class="connect-info">
                    <h3 class="connect-title">WhatsApp Community 1</h3>
                    <p class="connect-desc">Join our main community</p>
                </div>
                <span class="connect-arrow">➜</span>
            </a>
            
            <a href="https://chat.whatsapp.com/Fr7p4QjwEJDE5xsBQfmrbl" target="_blank" class="connect-card card-whatsapp2">
                <span class="connect-icon">📱</span>
                <div class="connect-info">
                    <h3 class="connect-title">WhatsApp Community 2</h3>
                    <p class="connect-desc">Backup community link</p>
                </div>
                <span class="connect-arrow">➜</span>
            </a>
            
            <a href="https://chat.whatsapp.com/JFDDPqwEuWbJeVKkcWao6n?mode=hqrt3" target="_blank" class="connect-card card-whatsapp3">
                <span class="connect-icon">👥</span>
                <div class="connect-info">
                    <h3 class="connect-title">WhatsApp Group</h3>
                    <p class="connect-desc">Join our group chat</p>
                </div>
                <span class="connect-arrow">➜</span>
            </a>
            
            <a href="https://www.facebook.com/profile.php?id=61584366848043" target="_blank" class="connect-card card-facebook">
                <span class="connect-icon">📘</span>
                <div class="connect-info">
                    <h3 class="connect-title">Facebook</h3>
                    <p class="connect-desc">Follow on Facebook</p>
                </div>
                <span class="connect-arrow">➜</span>
            </a>
            
            <a href="https://www.instagram.com/sanki_ladka_raj_307?igsh=cmMyYjNxcWR2M2pk" target="_blank" class="connect-card card-instagram">
                <span class="connect-icon">📸</span>
                <div class="connect-info">
                    <h3 class="connect-title">Instagram</h3>
                    <p class="connect-desc">@sanki_ladka_raj_307</p>
                </div>
                <span class="connect-arrow">➜</span>
            </a>
        </div>
    </div>
    
    <footer class="footer">
        <p class="footer-text rainbow-text">◉[=>2025-2026 | All Rights Reserved By Raj✘ Thakur 👑<=]◉</p>
    </footer>
</body>
</html>
"""

# ============== NOTIFICATIONS PAGE ==============
NOTIFICATIONS_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>RAJ SINGH - Notifications</title>
    """ + BASE_STYLES + """
    <style>
        .header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 20px;
            background: rgba(0, 0, 0, 0.5);
            border-radius: 15px;
            margin-bottom: 30px;
            flex-wrap: wrap;
            gap: 15px;
        }
        
        .header-title {
            font-family: 'Orbitron', sans-serif;
            font-size: 22px;
            color: #ff00ff;
            text-shadow: 0 0 10px #ff00ff;
        }
        
        .notifications-list {
            max-width: 800px;
            margin: 0 auto;
        }
        
        .notification-card {
            background: rgba(0, 0, 0, 0.6);
            border-radius: 15px;
            padding: 25px;
            margin-bottom: 20px;
            border-left: 5px solid;
            animation: fadeIn 0.5s ease;
        }
        
        .notification-card:nth-child(1) { border-color: #ff0000; }
        .notification-card:nth-child(2) { border-color: #00ff00; }
        .notification-card:nth-child(3) { border-color: #0000ff; }
        .notification-card:nth-child(4) { border-color: #ffff00; }
        .notification-card:nth-child(5) { border-color: #ff00ff; }
        
        @keyframes fadeIn {
            from { opacity: 0; transform: translateY(20px); }
            to { opacity: 1; transform: translateY(0); }
        }
        
        .notif-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 15px;
        }
        
        .notif-title {
            font-family: 'Orbitron', sans-serif;
            font-size: 18px;
            color: #00ff00;
        }
        
        .notif-date {
            font-size: 12px;
            color: rgba(255, 255, 255, 0.5);
        }
        
        .notif-message {
            color: rgba(255, 255, 255, 0.9);
            line-height: 1.6;
        }
        
        .no-notifications {
            text-align: center;
            padding: 50px;
            color: rgba(255, 255, 255, 0.5);
        }
        
        .no-notifications span {
            font-size: 80px;
            display: block;
            margin-bottom: 20px;
        }
    </style>
</head>
<body>
    <div class="bg-animation"></div>
    <div class="main-container">
        <div class="header">
            <h1 class="header-title rainbow-text">🔔 NOTIFICATIONS</h1>
            <a href="/dashboard" class="btn btn-info">🏠 Dashboard</a>
        </div>
        
        <div class="notifications-list">
            {% for notif in notifications %}
            <div class="notification-card">
                <div class="notif-header">
                    <h3 class="notif-title">📢 {{ notif.title }}</h3>
                    <span class="notif-date">{{ notif.created_at.strftime('%d %b %Y, %H:%M') }}</span>
                </div>
                <p class="notif-message">{{ notif.message }}</p>
            </div>
            {% endfor %}
            
            {% if not notifications %}
            <div class="no-notifications glow-box">
                <span>📭</span>
                <p>No notifications yet</p>
            </div>
            {% endif %}
        </div>
    </div>
    
    <footer class="footer">
        <p class="footer-text rainbow-text">◉[=>2025-2026 | All Rights Reserved By Raj✘ Thakur 👑<=]◉</p>
    </footer>
</body>
</html>
"""

# ============== ADMIN LOGIN PAGE ==============
ADMIN_LOGIN_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>RAJ THAKUR - Admin Login</title>
    """ + BASE_STYLES + """
    <style>
        .login-container {
            display: flex;
            justify-content: center;
            align-items: center;
            min-height: 100vh;
            padding: 20px;
        }
        
        .login-box {
            width: 100%;
            max-width: 450px;
            text-align: center;
        }
        
        .admin-icon {
            font-size: 100px;
            display: block;
            margin-bottom: 20px;
            animation: rotate 10s linear infinite;
        }
        
        @keyframes rotate {
            from { transform: rotate(0deg); }
            to { transform: rotate(360deg); }
        }
        
        .admin-title {
            font-family: 'Orbitron', sans-serif;
            font-size: 28px;
            color: #ff4500;
            text-shadow: 0 0 20px #ff4500;
            margin-bottom: 30px;
        }
        
        .back-link {
            display: inline-block;
            margin-top: 20px;
            color: #00ff00;
            text-decoration: none;
        }
    </style>
</head>
<body>
    <div class="bg-animation"></div>
    
    {% with messages = get_flashed_messages(with_categories=true) %}
        {% if messages %}
        <div class="flash-messages">
            {% for category, message in messages %}
            <div class="flash {{ category }}">{{ message }}</div>
            {% endfor %}
        </div>
        {% endif %}
    {% endwith %}
    
    <div class="login-container">
        <div class="login-box glow-box">
            <span class="admin-icon">⚙️</span>
            <h1 class="admin-title">ADMIN PANEL</h1>
            <p style="color: rgba(255,255,255,0.7); margin-bottom: 30px;">Deployer Control Access</p>
            
            <form method="POST">
                <label>👤 Admin Username</label>
                <input type="text" name="username" class="input-field" placeholder="Enter Admin Username" required>
                
                <label>🔒 Admin Password</label>
                <input type="password" name="password" class="input-field" placeholder="Enter Admin Password" required>
                
                <button type="submit" class="btn btn-danger" style="width: 100%; margin-top: 15px;">
                    🔓 ADMIN LOGIN
                </button>
            </form>
            
            <a href="/" class="back-link">← Back to User Login</a>
        </div>
    </div>
    
    <footer class="footer">
        <p class="footer-text rainbow-text">◉[=>2025-2026 | All Rights Reserved By Raj✘ Thakur 👑<=]◉</p>
    </footer>
</body>
</html>
"""

# ============== ADMIN PANEL PAGE ==============
ADMIN_PANEL_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>RAJ THAKUR - Admin Panel</title>
    """ + BASE_STYLES + """
    <style>
        .header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 20px;
            background: rgba(139, 0, 0, 0.5);
            border-radius: 15px;
            margin-bottom: 30px;
            flex-wrap: wrap;
            gap: 15px;
        }
        
        .header-title {
            font-family: 'Orbitron', sans-serif;
            font-size: 22px;
            color: #ff4500;
            text-shadow: 0 0 10px #ff4500;
        }
        
        .tabs {
            display: flex;
            gap: 10px;
            margin-bottom: 20px;
            flex-wrap: wrap;
        }
        
        .tab-btn {
            padding: 12px 25px;
            background: rgba(0, 0, 0, 0.5);
            border: 2px solid #00ff00;
            border-radius: 10px;
            color: #00ff00;
            cursor: pointer;
            transition: all 0.3s ease;
            font-weight: 600;
        }
        
        .tab-btn.active, .tab-btn:hover {
            background: #00ff00;
            color: #000;
        }
        
        .tab-content {
            display: none;
        }
        
        .tab-content.active {
            display: block;
        }
        
        .data-table {
            width: 100%;
            border-collapse: collapse;
            margin-top: 20px;
        }
        
        .data-table th, .data-table td {
            padding: 15px;
            text-align: left;
            border-bottom: 1px solid rgba(255, 255, 255, 0.1);
        }
        
        .data-table th {
            background: rgba(0, 255, 0, 0.2);
            color: #00ff00;
            font-family: 'Orbitron', sans-serif;
            font-size: 12px;
            text-transform: uppercase;
        }
        
        .data-table tr:hover {
            background: rgba(255, 255, 255, 0.05);
        }
        
        .status-badge {
            padding: 5px 15px;
            border-radius: 20px;
            font-size: 12px;
            font-weight: 600;
        }
        
        .badge-active { background: #00ff00; color: #000; }
        .badge-banned { background: #ff0000; color: #fff; }
        .badge-running { background: #00bfff; color: #000; }
        .badge-stopped { background: #666; color: #fff; }
        
        .action-btn {
            padding: 8px 15px;
            border-radius: 5px;
            font-size: 12px;
            margin-right: 5px;
            text-decoration: none;
            display: inline-block;
        }
        
        .section-title {
            font-family: 'Orbitron', sans-serif;
            font-size: 18px;
            color: #00ff00;
            margin-bottom: 20px;
            padding-bottom: 10px;
            border-bottom: 2px solid #00ff00;
        }
        
        .notif-form {
            display: grid;
            gap: 15px;
            margin-bottom: 30px;
        }
        
        .notif-list {
            max-height: 400px;
            overflow-y: auto;
        }
        
        .notif-item {
            background: rgba(0, 0, 0, 0.5);
            padding: 15px;
            border-radius: 10px;
            margin-bottom: 10px;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        
        .stats-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 20px;
            margin-bottom: 30px;
        }
        
        .stat-card {
            background: rgba(0, 0, 0, 0.5);
            padding: 25px;
            border-radius: 15px;
            text-align: center;
            border: 2px solid;
        }
        
        .stat-card:nth-child(1) { border-color: #00ff00; }
        .stat-card:nth-child(2) { border-color: #00bfff; }
        .stat-card:nth-child(3) { border-color: #ff00ff; }
        .stat-card:nth-child(4) { border-color: #ffff00; }
        
        .stat-number {
            font-family: 'Orbitron', sans-serif;
            font-size: 36px;
            color: #00ff00;
        }
        
        .stat-label {
            font-size: 14px;
            color: rgba(255, 255, 255, 0.7);
            margin-top: 5px;
        }
        
        .table-container {
            overflow-x: auto;
        }
    </style>
</head>
<body>
    <div class="bg-animation"></div>
    
    {% with messages = get_flashed_messages(with_categories=true) %}
        {% if messages %}
        <div class="flash-messages">
            {% for category, message in messages %}
            <div class="flash {{ category }}">{{ message }}</div>
            {% endfor %}
        </div>
        {% endif %}
    {% endwith %}
    
    <div class="main-container">
        <div class="header">
            <h1 class="header-title">⚙️ ADMIN PANEL - RAJ THAKUR</h1>
            <a href="/admin/logout" class="btn btn-danger">🚪 LOGOUT</a>
        </div>
        
        <!-- Stats -->
        <div class="stats-grid">
            <div class="stat-card">
                <div class="stat-number">{{ users|length }}</div>
                <div class="stat-label">Total Users</div>
            </div>
            <div class="stat-card">
                <div class="stat-number">{{ threads|length }}</div>
                <div class="stat-label">Total Threads</div>
            </div>
            <div class="stat-card">
                <div class="stat-number">{{ threads|selectattr('status', 'equalto', 'running')|list|length }}</div>
                <div class="stat-label">Active Threads</div>
            </div>
            <div class="stat-card">
                <div class="stat-number">{{ notifications|length }}</div>
                <div class="stat-label">Notifications</div>
            </div>
        </div>
        
        <!-- Tabs -->
        <div class="tabs">
            <button class="tab-btn active" onclick="showTab('users')">👥 Users Control</button>
            <button class="tab-btn" onclick="showTab('threads')">📊 All Threads</button>
            <button class="tab-btn" onclick="showTab('notifications')">🔔 Notifications</button>
        </div>
        
        <!-- Users Tab -->
        <div id="users" class="tab-content active glow-box">
            <h2 class="section-title">👥 Users Control</h2>
            <div class="table-container">
                <table class="data-table">
                    <thead>
                        <tr>
                            <th>ID</th>
                            <th>Instagram Username</th>
                            <th>Sender Name</th>
                            <th>Status</th>
                            <th>Threads</th>
                            <th>Actions</th>
                        </tr>
                    </thead>
                    <tbody>
                        {% for user in users %}
                        <tr>
                            <td>#{{ user.id }}</td>
                            <td>{{ user.instagram_username or 'N/A' }}</td>
                            <td>{{ user.sender_name or 'N/A' }}</td>
                            <td>
                                {% if user.is_banned %}
                                <span class="status-badge badge-banned">🚫 BANNED</span>
                                {% else %}
                                <span class="status-badge badge-active">✅ ACTIVE</span>
                                {% endif %}
                            </td>
                            <td>{{ user.threads|length }}</td>
                            <td>
                                <a href="/admin/toggle_ban/{{ user.id }}" class="action-btn btn-{{ 'primary' if user.is_banned else 'danger' }}">
                                    {{ '✅ Unban' if user.is_banned else '🚫 Ban' }}
                                </a>
                                <a href="/admin/stop_all_threads/{{ user.id }}" class="action-btn btn-info">⏹️ Stop All</a>
                            </td>
                        </tr>
                        {% endfor %}
                    </tbody>
                </table>
            </div>
        </div>
        
        <!-- Threads Tab -->
        <div id="threads" class="tab-content glow-box">
            <h2 class="section-title">📊 All User Threads</h2>
            <div class="table-container">
                <table class="data-table">
                    <thead>
                        <tr>
                            <th>ID</th>
                            <th>Sender Name</th>
                            <th>Target/Group</th>
                            <th>Type</th>
                            <th>Messages Sent</th>
                            <th>Status</th>
                        </tr>
                    </thead>
                    <tbody>
                        {% for thread in threads %}
                        <tr>
                            <td>#{{ thread.id }}</td>
                            <td>{{ thread.sender_name }}</td>
                            <td>{{ thread.target_username or thread.group_name or 'N/A' }}</td>
                            <td>{{ thread.message_type|upper }}</td>
                            <td>{{ thread.messages_sent }}</td>
                            <td>
                                {% if thread.status == 'running' %}
                                <span class="status-badge badge-running">🔴 LIVE</span>
                                {% else %}
                                <span class="status-badge badge-stopped">⏹️ STOPPED</span>
                                {% endif %}
                            </td>
                        </tr>
                        {% endfor %}
                    </tbody>
                </table>
            </div>
        </div>
        
        <!-- Notifications Tab -->
        <div id="notifications" class="tab-content glow-box">
            <h2 class="section-title">🔔 Manage Notifications</h2>
            
            <form method="POST" action="/admin/add_notification" class="notif-form">
                <label>📢 Notification Title</label>
                <input type="text" name="title" class="input-field" placeholder="Enter notification title" required>
                
                <label>💬 Message</label>
                <textarea name="message" class="input-field" placeholder="Enter notification message" required></textarea>
                
                <button type="submit" class="btn btn-primary">📤 Send Notification</button>
            </form>
            
            <h3 style="color: #00ff00; margin-bottom: 15px;">Active Notifications</h3>
            <div class="notif-list">
                {% for notif in notifications %}
                <div class="notif-item">
                    <div>
                        <strong style="color: #00ff00;">{{ notif.title }}</strong>
                        <p style="font-size: 13px; color: rgba(255,255,255,0.7);">{{ notif.message[:50] }}...</p>
                    </div>
                    <a href="/admin/delete_notification/{{ notif.id }}" class="action-btn btn-danger">🗑️ Delete</a>
                </div>
                {% endfor %}
            </div>
        </div>
    </div>
    
    <footer class="footer">
        <p class="footer-text rainbow-text">◉[=>2025-2026 | All Rights Reserved By Raj✘ Thakur 👑<=]◉</p>
    </footer>
    
    <script>
        function showTab(tabId) {
            document.querySelectorAll('.tab-content').forEach(el => el.classList.remove('active'));
            document.querySelectorAll('.tab-btn').forEach(el => el.classList.remove('active'));
            document.getElementById(tabId).classList.add('active');
            event.target.classList.add('active');
        }
    </script>
</body>
</html>
"""

# ============== ROUTES ==============
@app.route('/')
def index():
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()
        
        if username == 'RAJ SINGH' and password == 'RAJ SINGH':
            session['user_logged_in'] = True
            session['user_session_id'] = os.urandom(16).hex()
            
            user = User.query.filter_by(session_id=session['user_session_id']).first()
            if not user:
                user = User(session_id=session['user_session_id'])
                db.session.add(user)
                db.session.commit()
            
            return redirect(url_for('dashboard'))
        else:
            flash('Invalid credentials! Use RAJ SINGH / RAJ SINGH', 'error')
    
    return render_template_string(LOGIN_HTML)

@app.route('/dashboard')
@login_required
def dashboard():
    notifications = Notification.query.filter_by(is_active=True).order_by(Notification.created_at.desc()).limit(5).all()
    return render_template_string(DASHBOARD_HTML, notifications=notifications)

@app.route('/message_box', methods=['GET', 'POST'])
@login_required
def message_box():
    user = User.query.filter_by(session_id=session.get('user_session_id')).first()
    if user and user.is_banned:
        flash('Your account has been banned by admin!', 'error')
        return redirect(url_for('dashboard'))
    
    user_threads = []
    groups = []
    ig_logged_in = session.get('ig_client', False)
    
    if user:
        user_threads = MessageThread.query.filter_by(user_id=user.id).order_by(MessageThread.created_at.desc()).all()
    
    if request.method == 'POST':
        action = request.form.get('action')
        
        if action == 'login_instagram':
            ig_username = request.form.get('ig_username')
            ig_password = request.form.get('ig_password')
            
            cl = instagram_login(ig_username, ig_password)
            if cl:
                session['ig_client'] = True
                session['ig_username'] = ig_username
                session['ig_password'] = ig_password
                
                if user:
                    user.instagram_username = ig_username
                    db.session.commit()
                
                groups = get_user_groups(cl)
                session['groups'] = groups
                flash('Instagram login successful!', 'success')
                # Reload to show the logged-in state
                return redirect(url_for('message_box'))
            else:
                flash('Instagram login failed!', 'error')
        
        elif action == 'send_message':
            if not session.get('ig_client'):
                flash('Please login to Instagram first!', 'error')
            else:
                cl = instagram_login(session.get('ig_username'), session.get('ig_password'))
                if cl:
                    sender_name = request.form.get('sender_name')
                    message_type = request.form.get('message_type')
                    messages = [m.strip() for m in request.form.get('messages', '').split('\n') if m.strip()]
                    delay = int(request.form.get('delay', 10))
                    
                    if user:
                        user.sender_name = sender_name
                        db.session.commit()
                    
                    if message_type == 'inbox':
                        target_username = request.form.get('target_username')
                        thread_record = MessageThread(
                            user_id=user.id,
                            sender_name=sender_name,
                            target_username=target_username,
                            message_type='inbox',
                            status='running'
                        )
                        db.session.add(thread_record)
                        db.session.commit()
                        
                        active_threads[thread_record.id] = True
                        t = Thread(target=send_inbox_message,
                                  args=(cl, target_username, sender_name, messages, delay, thread_record.id))
                        t.daemon = True
                        t.start()
                        flash(f'Started sending messages to {target_username}!', 'success')
                        
                    else:
                        thread_id = request.form.get('group_thread_id')
                        group_name = request.form.get('group_name', 'Unknown Group')
                        
                        if not thread_id:
                            flash('Please select a group!', 'error')
                            return redirect(url_for('message_box'))
                            
                        thread_record = MessageThread(
                            user_id=user.id,
                            sender_name=sender_name,
                            group_name=group_name,
                            message_type='group',
                            status='running'
                        )
                        db.session.add(thread_record)
                        db.session.commit()
                        
                        active_threads[thread_record.id] = True
                        t = Thread(target=send_group_message,
                                  args=(cl, thread_id, sender_name, messages, delay, thread_record.id))
                        t.daemon = True
                        t.start()
                        flash(f'Started sending messages to group: {group_name}!', 'success')
                    
                    return redirect(url_for('message_box'))
                else:
                    flash('Instagram session expired. Please login again.', 'error')
                    session.pop('ig_client', None)
    
    # Prepare groups for template if user is logged in to IG
    if session.get('ig_client'):
        cl = instagram_login(session.get('ig_username'), session.get('ig_password'))
        if cl:
            groups = get_user_groups(cl)
            session['groups'] = groups
        else:
            session.pop('ig_client', None)
    else:
        groups = session.get('groups', [])
    
    return render_template_string(MESSAGE_BOX_HTML, user_threads=user_threads, groups=groups, ig_logged_in=session.get('ig_client', False))

@app.route('/stop_thread/<int:thread_id>')
@login_required
def stop_thread(thread_id):
    thread = MessageThread.query.get(thread_id)
    if thread:
        thread.status = 'stopped'
        if thread.id in active_threads:
            active_threads[thread.id] = False
        db.session.commit()
        flash('Thread stopped successfully!', 'success')
    return redirect(url_for('message_box'))

@app.route('/connect')
@login_required
def connect():
    return render_template_string(CONNECT_HTML)

@app.route('/notifications')
@login_required
def notifications():
    all_notifications = Notification.query.filter_by(is_active=True).order_by(Notification.created_at.desc()).all()
    return render_template_string(NOTIFICATIONS_HTML, notifications=all_notifications)

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

# Admin Routes
@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        admin = Admin.query.filter_by(username=username).first()
        if admin and check_password_hash(admin.password, password):
            session['admin_logged_in'] = True
            return redirect(url_for('admin_panel'))
        else:
            flash('Invalid admin credentials!', 'error')
    
    return render_template_string(ADMIN_LOGIN_HTML)

@app.route('/admin/panel')
@admin_required
def admin_panel():
    users = User.query.all()
    threads = MessageThread.query.all()
    notifications = Notification.query.filter_by(is_active=True).order_by(Notification.created_at.desc()).all()
    return render_template_string(ADMIN_PANEL_HTML, users=users, threads=threads, notifications=notifications)

@app.route('/admin/toggle_ban/<int:user_id>')
@admin_required
def toggle_ban(user_id):
    user = User.query.get(user_id)
    if user:
        user.is_banned = not user.is_banned
        db.session.commit()
        flash(f'User {"banned" if user.is_banned else "unbanned"} successfully!', 'success')
    return redirect(url_for('admin_panel'))

@app.route('/admin/stop_all_threads/<int:user_id>')
@admin_required
def stop_all_threads(user_id):
    user = User.query.get(user_id)
    if user:
        for thread in user.threads:
            if thread.status == 'running':
                thread.status = 'stopped'
                if thread.id in active_threads:
                    active_threads[thread.id] = False
        db.session.commit()
        flash('All threads stopped for this user!', 'success')
    return redirect(url_for('admin_panel'))

@app.route('/admin/add_notification', methods=['POST'])
@admin_required
def add_notification():
    title = request.form.get('title')
    message = request.form.get('message')
    
    notif = Notification(title=title, message=message)
    db.session.add(notif)
    db.session.commit()
    flash('Notification sent to all users!', 'success')
    return redirect(url_for('admin_panel'))

@app.route('/admin/delete_notification/<int:notif_id>')
@admin_required
def delete_notification(notif_id):
    notif = Notification.query.get(notif_id)
    if notif:
        db.session.delete(notif)
        db.session.commit()
        flash('Notification deleted!', 'success')
    return redirect(url_for('admin_panel'))

@app.route('/admin/logout')
def admin_logout():
    session.pop('admin_logged_in', None)
    return redirect(url_for('admin_login'))

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)

import time
import os
from datetime import datetime
from threading import Thread
from functools import wraps
from instagrapi import Client
from flask import Flask, request, render_template_string, redirect, url_for, session, flash
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = os.urandom(24)
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'sqlite:///app.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)
active_threads = {}

# ============== DATABASE MODELS ==============
class Admin(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    password = db.Column(db.String(255), nullable=False)

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(db.String(100), unique=True, nullable=False)
    instagram_username = db.Column(db.String(100))
    sender_name = db.Column(db.String(100))
    is_banned = db.Column(db.Boolean, default=False)

class MessageThread(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    sender_name = db.Column(db.String(100))
    target_username = db.Column(db.String(100))
    group_name = db.Column(db.String(200))
    message_type = db.Column(db.String(20))
    status = db.Column(db.String(20), default='running')
    messages_sent = db.Column(db.Integer, default=0)
    user = db.relationship('User', backref=db.backref('threads', lazy=True))

class Notification(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    message = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    is_active = db.Column(db.Boolean, default=True)

# ============== CREATE TABLES ==============
with app.app_context():
    db.create_all()
    if not Admin.query.filter_by(username='RAJ THAKUR').first():
        db.session.add(Admin(username='RAJ THAKUR', password=generate_password_hash('RAJ THAKUR')))
        db.session.commit()

# ============== DECORATORS ==============
def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_logged_in' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated

def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'admin_logged_in' not in session:
            return redirect(url_for('admin_login'))
        return f(*args, **kwargs)
    return decorated

# ============== INSTAGRAM FUNCTIONS ==============
def instagram_login(username, password):
    try:
        cl = Client()
        cl.login(username, password)
        return cl
    except:
        return None

def send_inbox_message(cl, target, sender, messages, delay, thread_id):
    try:
        user_id = cl.user_id_from_username(target)
        idx = 0
        while thread_id in active_threads and active_threads[thread_id]:
            with app.app_context():
                thread = MessageThread.query.get(thread_id)
                if thread and thread.status == 'stopped':
                    break
                cl.direct_send(f"{sender} {messages[idx]}", [user_id])
                if thread:
                    thread.messages_sent += 1
                    db.session.commit()
            time.sleep(delay)
            idx = (idx + 1) % len(messages)
    except:
        pass

def send_group_message(cl, thread_id, sender, messages, delay, record_id):
    try:
        idx = 0
        while record_id in active_threads and active_threads[record_id]:
            with app.app_context():
                thread = MessageThread.query.get(record_id)
                if thread and thread.status == 'stopped':
                    break
                cl.direct_send(f"{sender} {messages[idx]}", thread_ids=[thread_id])
                if thread:
                    thread.messages_sent += 1
                    db.session.commit()
            time.sleep(delay)
            idx = (idx + 1) % len(messages)
    except:
        pass

# ============== USER ROUTES ==============
@app.route('/')
def index():
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        if request.form.get('username') == 'RAJ SINGH' and request.form.get('password') == 'RAJ SINGH':
            session['user_logged_in'] = True
            session['user_session_id'] = os.urandom(16).hex()
            if not User.query.filter_by(session_id=session['user_session_id']).first():
                db.session.add(User(session_id=session['user_session_id']))
                db.session.commit()
            return redirect(url_for('dashboard'))
        flash('Invalid credentials!', 'error')
    return render_template_string(LOGIN_HTML)

@app.route('/dashboard')
@login_required
def dashboard():
    return render_template_string(DASHBOARD_HTML)

@app.route('/message_box', methods=['GET', 'POST'])
@login_required
def message_box():
    user = User.query.filter_by(session_id=session.get('user_session_id')).first()
    if user and user.is_banned:
        flash('Your account has been banned!', 'error')
        return redirect(url_for('dashboard'))
    
    user_threads = MessageThread.query.filter_by(user_id=user.id).all() if user else []
    
    if request.method == 'POST':
        action = request.form.get('action')
        
        if action == 'login_instagram':
            cl = instagram_login(request.form.get('ig_username'), request.form.get('ig_password'))
            if cl:
                session['ig_client'] = True
                session['ig_username'] = request.form.get('ig_username')
                if user:
                    user.instagram_username = request.form.get('ig_username')
                    db.session.commit()
                flash('Instagram login successful!', 'success')
            else:
                flash('Instagram login failed!', 'error')
        
        elif action == 'send_message' and session.get('ig_client'):
            cl = instagram_login(session.get('ig_username'), request.form.get('ig_password', ''))
            if cl:
                sender = request.form.get('sender_name')
                messages = [m.strip() for m in request.form.get('messages', '').split('\n') if m.strip()]
                delay = int(request.form.get('delay', 10))
                
                if request.form.get('message_type') == 'inbox':
                    target = request.form.get('target_username')
                    thread = MessageThread(user_id=user.id, sender_name=sender, target_username=target, message_type='inbox')
                    db.session.add(thread)
                    db.session.commit()
                    active_threads[thread.id] = True
                    Thread(target=send_inbox_message, args=(cl, target, sender, messages, delay, thread.id), daemon=True).start()
                    flash('Inbox messaging started!', 'success')
                else:
                    thread_id = request.form.get('group_thread_id')
                    group_name = request.form.get('group_name')
                    thread = MessageThread(user_id=user.id, sender_name=sender, group_name=group_name, message_type='group')
                    db.session.add(thread)
                    db.session.commit()
                    active_threads[thread.id] = True
                    Thread(target=send_group_message, args=(cl, thread_id, sender, messages, delay, thread.id), daemon=True).start()
                    flash('Group messaging started!', 'success')
    
    return render_template_string(MESSAGE_BOX_HTML, ig_logged_in=session.get('ig_client', False), user_threads=user_threads)

@app.route('/stop_thread/<int:thread_id>')
@login_required
def stop_thread(thread_id):
    thread = MessageThread.query.get(thread_id)
    if thread:
        thread.status = 'stopped'
        db.session.commit()
        if thread.id in active_threads:
            active_threads[thread.id] = False
        flash('Thread stopped!', 'success')
    return redirect(url_for('message_box'))

@app.route('/notifications')
@login_required
def notifications_page():
    notifications = Notification.query.filter_by(is_active=True).order_by(Notification.created_at.desc()).all()
    return render_template_string(NOTIFICATIONS_HTML, notifications=notifications)

@app.route('/connect')
@login_required
def connect():
    return render_template_string(CONNECT_HTML)

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

# ============== ADMIN ROUTES ==============
@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        admin = Admin.query.filter_by(username=request.form.get('username')).first()
        if admin and check_password_hash(admin.password, request.form.get('password')):
            session['admin_logged_in'] = True
            return redirect(url_for('admin_panel'))
        flash('Invalid credentials!', 'error')
    return render_template_string(ADMIN_LOGIN_HTML)

@app.route('/admin/panel')
@admin_required
def admin_panel():
    return render_template_string(ADMIN_PANEL_HTML, users=User.query.all(), threads=MessageThread.query.all(), notifications=Notification.query.filter_by(is_active=True).all())

@app.route('/admin/toggle_ban/<int:user_id>')
@admin_required
def toggle_ban(user_id):
    user = User.query.get(user_id)
    if user:
        user.is_banned = not user.is_banned
        db.session.commit()
    return redirect(url_for('admin_panel'))

@app.route('/admin/stop_all_threads/<int:user_id>')
@admin_required
def stop_all_threads(user_id):
    for thread in MessageThread.query.filter_by(user_id=user_id, status='running').all():
        thread.status = 'stopped'
        if thread.id in active_threads:
            active_threads[thread.id] = False
    db.session.commit()
    return redirect(url_for('admin_panel'))

@app.route('/admin/add_notification', methods=['POST'])
@admin_required
def add_notification():
    db.session.add(Notification(title=request.form.get('title'), message=request.form.get('message')))
    db.session.commit()
    return redirect(url_for('admin_panel'))

@app.route('/admin/delete_notification/<int:notif_id>')
@admin_required
def delete_notification(notif_id):
    notif = Notification.query.get(notif_id)
    if notif:
        db.session.delete(notif)
        db.session.commit()
    return redirect(url_for('admin_panel'))

@app.route('/admin/logout')
def admin_logout():
    session.pop('admin_logged_in', None)
    return redirect(url_for('admin_login'))

# ============== HTML TEMPLATES ==============
LOGIN_HTML = '''
<!DOCTYPE html>
<html>
<head><title>RAJ SINGH Login</title>
<style>
body{background:#0a0a1a;color:#0f0;font-family:monospace;display:flex;justify-content:center;align-items:center;height:100vh}
.box{background:#1a1a2e;padding:40px;border-radius:20px;border:2px solid #0f0;text-align:center;width:350px}
input,button{padding:12px;margin:10px;border-radius:8px;border:none;width:90%}
input{background:#2a2a3e;color:#0f0}
button{background:#0f0;color:#000;cursor:pointer;font-weight:bold}
h1{font-size:24px}
</style>
</head>
<body>
<div class="box">
<h1>🔐 RAJ SINGH</h1>
<h3>✨ WELCOME ✨</h3>
{% with messages = get_flashed_messages() %}{% if messages %}<p style="color:red">{{ messages[0] }}</p>{% endif %}{% endwith %}
<form method="POST">
<input type="text" name="username" placeholder="Username" required><br>
<input type="password" name="password" placeholder="Password" required><br>
<button type="submit">🚀 LOGIN</button>
</form>
<p style="margin-top:20px">Use: <strong>RAJ SINGH</strong></p>
<a href="/admin/login" style="color:#f0f">Admin Panel</a>
</div>
</body>
</html>
'''

DASHBOARD_HTML = '''
<!DOCTYPE html>
<html>
<head><title>Dashboard - RAJ SINGH</title>
<style>
body{background:#0a0a1a;color:#fff;font-family:monospace}
.header{padding:20px;background:#1a1a2e;border-bottom:2px solid #0f0}
.grid{display:grid;grid-template-columns:repeat(2,1fr);gap:20px;padding:40px;max-width:800px;margin:0 auto}
.card{background:#1a1a2e;padding:30px;border-radius:15px;text-align:center;border:1px solid #0f0;text-decoration:none;color:#fff}
.card:hover{transform:scale(1.02);background:#2a2a3e}
h1{color:#0f0}
.btn{background:#f00;padding:8px 16px;border-radius:8px;text-decoration:none;color:#fff}
</style>
</head>
<body>
<div class="header"><h1>🎯 RAJ SINGH DASHBOARD</h1><a href="/logout" class="btn">LOGOUT</a></div>
<div class="grid">
<a href="/message_box" class="card"><h2>💬 MESSAGE BOX</h2><p>Send Instagram DM</p></a>
<a href="/connect" class="card"><h2>🔗 CONNECT</h2><p>Social Links</p></a>
<a href="/notifications" class="card"><h2>🔔 NOTIFICATIONS</h2><p>View Updates</p></a>
<a href="/admin/login" class="card"><h2>⚙️ ADMIN</h2><p>Admin Panel</p></a>
</div>
</body>
</html>
'''

MESSAGE_BOX_HTML = '''
<!DOCTYPE html>
<html>
<head><title>Message Box - RAJ SINGH</title>
<style>
body{background:#0a0a1a;color:#fff;font-family:monospace;padding:20px}
.container{max-width:800px;margin:0 auto}
.glow-box{background:#1a1a2e;padding:25px;border-radius:15px;border:2px solid #0f0;margin-bottom:20px}
input,textarea,select{padding:12px;margin:10px 0;border-radius:8px;border:none;width:100%;background:#2a2a3e;color:#0f0}
button{background:#0f0;color:#000;padding:12px;border:none;border-radius:8px;cursor:pointer;font-weight:bold}
.btn{display:inline-block;padding:8px 16px;background:#f00;color:#fff;text-decoration:none;border-radius:8px;margin:5px}
.thread-item{background:#2a2a3e;padding:15px;border-radius:10px;margin:10px 0}
.status-running{color:#0f0}
hr{border-color:#0f0}
</style>
</head>
<body>
<div class="container">
<a href="/dashboard" class="btn">🏠 BACK</a>
<h1>💬 MESSAGE BOX</h1>
<div class="glow-box">
<h2>📱 Instagram Login</h2>
<form method="POST">
<input type="hidden" name="action" value="login_instagram">
<input type="text" name="ig_username" placeholder="Instagram Username" required>
<input type="password" name="ig_password" placeholder="Instagram Password" required>
<button type="submit">🔓 LOGIN INSTAGRAM</button>
</form>
</div>
{% if ig_logged_in %}
<div class="glow-box">
<h2>📨 Send Messages</h2>
<form method="POST">
<input type="hidden" name="action" value="send_message">
<input type="text" name="sender_name" placeholder="Sender Name" required>
<select name="message_type">
<option value="inbox">Inbox DM</option>
<option value="group">Group Message</option>
</select>
<input type="text" name="target_username" placeholder="Target Username (for DM)">
<input type="text" name="group_thread_id" placeholder="Group Thread ID (for Group)">
<input type="text" name="group_name" placeholder="Group Name">
<textarea name="messages" rows="5" placeholder="Enter messages (one per line)" required></textarea>
<input type="number" name="delay" value="10" placeholder="Delay in seconds">
<button type="submit">🚀 START SENDING</button>
</form>
</div>
{% endif %}
<div class="glow-box">
<h2>📊 Active Threads</h2>
{% for thread in user_threads %}
<div class="thread-item">
<strong>{{ thread.sender_name }}</strong> →
{% if thread.message_type == 'inbox' %}@{{ thread.target_username }}{% else %}{{ thread.group_name }}{% endif %}
<br>Messages: {{ thread.messages_sent }} | Status: <span class="status-running">{{ thread.status }}</span>
<br><a href="/stop_thread/{{ thread.id }}" class="btn" style="background:#f00">⏹️ STOP</a>
</div>
{% endfor %}
</div>
</div>
</body>
</html>
'''

CONNECT_HTML = '''
<!DOCTYPE html>
<html>
<head><title>Connect - RAJ SINGH</title>
<style>
body{background:#0a0a1a;color:#fff;font-family:monospace;padding:20px;text-align:center}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(250px,1fr));gap:20px;max-width:800px;margin:20px auto}
.card{background:#1a1a2e;padding:30px;border-radius:15px;border:2px solid #0f0;text-decoration:none;color:#fff}
.card:hover{transform:scale(1.05)}
.btn{background:#0f0;padding:10px 20px;border-radius:8px;text-decoration:none;color:#000}
</style>
</head>
<body>
<a href="/dashboard" class="btn">🏠 BACK</a>
<h1>🔗 CONNECT WITH US</h1>
<div class="grid">
<a href="https://chat.whatsapp.com/Fr7p4QjwEJDE5xsBQfmrbl" target="_blank" class="card"><h2>💬 WhatsApp 1</h2></a>
<a href="https://chat.whatsapp.com/Fr7p4QjwEJDE5xsBQfmrbl" target="_blank" class="card"><h2>📱 WhatsApp 2</h2></a>
<a href="https://www.instagram.com/sanki_ladka_raj_307" target="_blank" class="card"><h2>📸 Instagram</h2></a>
<a href="https://www.facebook.com/profile.php?id=61584366848043" target="_blank" class="card"><h2>📘 Facebook</h2></a>
</div>
</body>
</html>
'''

NOTIFICATIONS_HTML = '''
<!DOCTYPE html>
<html>
<head><title>Notifications - RAJ SINGH</title>
<style>
body{background:#0a0a1a;color:#fff;font-family:monospace;padding:20px}
.container{max-width:600px;margin:0 auto}
.notif{background:#1a1a2e;padding:15px;border-radius:10px;margin:10px 0;border-left:4px solid #0f0}
.btn{background:#0f0;padding:10px 20px;border-radius:8px;text-decoration:none;color:#000}
</style>
</head>
<body>
<a href="/dashboard" class="btn">🏠 BACK</a>
<h1>🔔 NOTIFICATIONS</h1>
<div class="container">
{% for n in notifications %}
<div class="notif">
<h3>{{ n.title }}</h3>
<p>{{ n.message }}</p>
<small>{{ n.created_at.strftime('%d %b %Y') }}</small>
</div>
{% endfor %}
</div>
</body>
</html>
'''

ADMIN_LOGIN_HTML = '''
<!DOCTYPE html>
<html>
<head><title>Admin Login - RAJ THAKUR</title>
<style>
body{background:#0a0a1a;color:#f0f;font-family:monospace;display:flex;justify-content:center;align-items:center;height:100vh}
.box{background:#1a1a2e;padding:40px;border-radius:20px;border:2px solid #f0f;text-align:center}
input,button{padding:12px;margin:10px;border-radius:8px;border:none;width:90%}
input{background:#2a2a3e;color:#f0f}
button{background:#f0f;color:#000;cursor:pointer}
</style>
</head>
<body>
<div class="box">
<h1>⚙️ ADMIN LOGIN</h1>
{% with messages = get_flashed_messages() %}{% if messages %}<p style="color:red">{{ messages[0] }}</p>{% endif %}{% endwith %}
<form method="POST">
<input type="text" name="username" placeholder="Admin Username" required><br>
<input type="password" name="password" placeholder="Admin Password" required><br>
<button type="submit">🔓 LOGIN</button>
</form>
<a href="/" style="color:#0f0">← User Login</a>
</div>
</body>
</html>
'''

ADMIN_PANEL_HTML = '''
<!DOCTYPE html>
<html>
<head><title>Admin Panel - RAJ THAKUR</title>
<style>
body{background:#0a0a1a;color:#fff;font-family:monospace;padding:20px}
table{width:100%;border-collapse:collapse}
th,td{padding:10px;text-align:left;border-bottom:1px solid #333}
th{background:#1a1a2e;color:#0f0}
.btn{padding:5px 10px;border-radius:5px;text-decoration:none;margin:2px;display:inline-block}
.btn-ban{background:#f00;color:#fff}
.btn-unban{background:#0f0;color:#000}
.btn-stop{background:#ffa500;color:#000}
.notif-item{background:#1a1a2e;padding:10px;margin:10px 0;border-radius:8px}
.tab{display:inline-block;padding:10px 20px;background:#1a1a2e;cursor:pointer;margin-right:5px}
.tab.active{background:#0f0;color:#000}
.content{display:none}
.content.active{display:block}
</style>
</head>
<body>
<h1>⚙️ ADMIN PANEL - RAJ THAKUR</h1>
<a href="/admin/logout" class="btn" style="background:#f00">LOGOUT</a>
<a href="/dashboard" class="btn" style="background:#0f0">← Dashboard</a>
<div style="margin:20px 0">
<div class="tab active" onclick="showTab('users')">👥 Users</div>
<div class="tab" onclick="showTab('threads')">📊 Threads</div>
<div class="tab" onclick="showTab('notifications')">🔔 Notifications</div>
</div>
<div id="users" class="content active">
<h2>Users</h2>
<table><tr><th>ID</th><th>Instagram</th><th>Sender</th><th>Status</th><th>Actions</th></tr>
{% for u in users %}
<tr><td>{{ u.id }}</td><td>{{ u.instagram_username or 'N/A' }}</td><td>{{ u.sender_name or 'N/A' }}</td>
<td>{% if u.is_banned %}🚫 BANNED{% else %}✅ ACTIVE{% endif %}</td>
<td><a href="/admin/toggle_ban/{{ u.id }}" class="btn {% if u.is_banned %}btn-unban{% else %}btn-ban{% endif %}">{% if u.is_banned %}UNBAN{% else %}BAN{% endif %}</a>
<a href="/admin/stop_all_threads/{{ u.id }}" class="btn btn-stop">STOP ALL</a></td></tr>
{% endfor %}</table>
</div>
<div id="threads" class="content">
<h2>Threads</h2>
<table><tr><th>ID</th><th>Sender</th><th>Target</th><th>Type</th><th>Sent</th><th>Status</th></tr>
{% for t in threads %}
<tr><td>{{ t.id }}</td><td>{{ t.sender_name }}</td><td>{{ t.target_username or t.group_name }}</td>
<td>{{ t.message_type }}</td><td>{{ t.messages_sent }}</td><td>{{ t.status }}</td></tr>
{% endfor %}</table>
</div>
<div id="notifications" class="content">
<h2>Add Notification</h2>
<form method="POST" action="/admin/add_notification">
<input type="text" name="title" placeholder="Title" style="padding:10px;width:300px" required><br>
<textarea name="message" placeholder="Message" rows="3" style="padding:10px;width:300px"></textarea><br>
<button type="submit" class="btn" style="background:#0f0">SEND</button>
</form>
<h3>Existing Notifications</h3>
{% for n in notifications %}
<div class="notif-item"><strong>{{ n.title }}</strong><br>{{ n.message }}<br>
<a href="/admin/delete_notification/{{ n.id }}" class="btn" style="background:#f00">DELETE</a></div>
{% endfor %}
</div>
<script>
function showTab(tabId){
document.querySelectorAll('.content').forEach(c=>c.classList.remove('active'));
document.querySelectorAll('.tab').forEach(t=>t.classList.remove('active'));
document.getElementById(tabId).classList.add('active');
event.target.classList.add('active');
}
</script>
</body>
</html>
'''

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)

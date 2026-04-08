#!/usr/bin/env python3

import os
import json
import uuid
import random
import string
import hashlib
from datetime import datetime
from functools import wraps

import stripe
from flask import Flask, request, jsonify, render_template_string
from flask_sqlalchemy import SQLAlchemy
try:
    import sendgrid
    from sendgrid.helpers.mail import Mail
except ImportError:
    sendgrid = None

app = Flask(__name__)

# ---- CONFIG ----
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'sqlite:///quede_licenses.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'change-this-in-production')

stripe.api_key = os.environ.get('STRIPE_SECRET_KEY', '')
STRIPE_WEBHOOK_SECRET = os.environ.get('STRIPE_WEBHOOK_SECRET', '')
ADMIN_PASSWORD = os.environ.get('ADMIN_PASSWORD', 'quede-admin-2024')

SOLO_PRICE_ID = os.environ.get('STRIPE_SOLO_PRICE_ID', '')
TEAM_PRICE_ID = os.environ.get('STRIPE_TEAM_PRICE_ID', '')

db = SQLAlchemy(app)

# ---- MODELS ----
class License(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(50), unique=True, nullable=False)
    plan = db.Column(db.String(20), nullable=False)
    max_users = db.Column(db.Integer, default=1)
    company = db.Column(db.String(200), default='')
    email = db.Column(db.String(200), default='')
    stripe_session_id = db.Column(db.String(200), default='')
    active = db.Column(db.Boolean, default=True)
    activations = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    activated_at = db.Column(db.DateTime, nullable=True)

    def to_dict(self):
        return {
            'key': self.key,
            'plan': self.plan,
            'max_users': self.max_users,
            'company': self.company,
            'email': self.email,
            'active': self.active,
            'activations': self.activations,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'activated_at': self.activated_at.isoformat() if self.activated_at else None,
        }

# ---- HELPERS ----
def generate_license_key():
    def segment():
        return ''.join(random.choices(string.ascii_uppercase + string.digits, k=4))
    return f"QUEDE-{segment()}-{segment()}-{segment()}"

def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        password = request.headers.get('X-Admin-Password') or request.args.get('password')
        if password != ADMIN_PASSWORD:
            return jsonify({'error': 'Unauthorized'}), 401
        return f(*args, **kwargs)
    return decorated

# ---- ROUTES ----
@app.route('/')
def index():
    return render_template_string(ADMIN_TEMPLATE)

@app.route('/validate', methods=['POST'])
def validate():
    data = request.json or {}
    key = data.get('key', '').strip().upper()
    if not key:
        return jsonify({'valid': False, 'error': 'No license key provided'}), 400
    license = License.query.filter_by(key=key).first()
    if not license:
        return jsonify({'valid': False, 'error': 'License key not found'}), 404
    if not license.active:
        return jsonify({'valid': False, 'error': 'License deactivated. Contact support@quedeapp.com'}), 403
    if license.activations == 0:
        license.activated_at = datetime.utcnow()
    license.activations += 1
    db.session.commit()
    return jsonify({'valid': True, 'plan': license.plan, 'max_users': license.max_users, 'company': license.company, 'email': license.email, 'key': license.key})

@app.route('/webhook', methods=['POST'])
def stripe_webhook():
    payload = request.data
    sig_header = request.headers.get('Stripe-Signature')
    try:
        event = stripe.Webhook.construct_event(payload, sig_header, STRIPE_WEBHOOK_SECRET)
    except Exception as e:
        return jsonify({'error': str(e)}), 400
    if event['type'] == 'checkout.session.completed':
        session = event['data']['object']
        customer_email = session.get('customer_details', {}).get('email', '')
        session_id = session.get('id', '')
        line_items = stripe.checkout.Session.list_line_items(session_id)
        plan = 'solo'
        max_users = 1
        for item in line_items.data:
            if item.price.id == TEAM_PRICE_ID:
                plan = 'team'
                max_users = 5
        key = generate_license_key()
        while License.query.filter_by(key=key).first():
            key = generate_license_key()
        new_license = License(key=key, plan=plan, max_users=max_users, email=customer_email, stripe_session_id=session_id)
        db.session.add(new_license)
        db.session.commit()
        try:
            send_license_email(customer_email, key, plan)
        except Exception as e:
            print(f"Email send failed: {e}")
    return jsonify({'received': True})

def send_license_email(email, key, plan):
    sg_key = os.environ.get('SENDGRID_API_KEY', '')
    from_email = os.environ.get('SMTP_USER', 'no-reply@quedeapp.com')
    if not sg_key:
        print(f"[EMAIL SKIPPED] License key for {email}: {key}")
        return
    import urllib.request as urlreq
    import json as _json

    plan_label = 'Solo — 1 user' if plan == 'solo' else 'Team — up to 5 users'
    body = f"""
Welcome to QUEDE — Intelligence-Driven Cinema.

You're now part of a smarter way to organize your footage.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
YOUR LICENSE KEY
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  {key}

Plan: {plan_label}

Keep this email. You will need this key to activate QUEDE.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

GETTING STARTED

Step 1 — Download QUEDE
  https://quedeapp.com/download  [coming soon]

Step 2 — Launch the app
  Double-click the QUEDE installer and follow the setup.

Step 3 — Activate
  When prompted, enter your license key above.

Step 4 — Connect your footage
  Point QUEDE at any folder on your drive or external hard drive.
  AI will analyze every clip, organize by shoot day, and rename
  files using your production template — automatically.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
WHAT QUEDE DOES

  ✦ Reads your footage frames using AI vision
  ✦ Organizes clips by shoot day automatically
  ✦ Sorts into A-Roll, B-Roll, Interview folders
  ✦ Renames files with your production naming template
  ✦ Everything stays on your machine — no cloud uploads

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
ABOUT THE ANTHROPIC API KEY

QUEDE uses Claude AI to visually analyze your footage.
This requires a free Anthropic API key — separate from your
QUEDE license. Here's what you need to know:

Q: What is the Anthropic API key?
A: It's a free key that gives QUEDE access to Claude AI.
   You set it up once during the QUEDE onboarding.
   Get yours at: https://console.anthropic.com

Q: Does it cost money?
A: Anthropic charges a small fee per clip analyzed —
   roughly $0.001 per clip. Organizing 1,000 clips
   costs about $1. You add credits at console.anthropic.com.

Q: What if QUEDE stops analyzing my footage?
A: Your Anthropic credits may have run out. To fix it:
   1. Go to console.anthropic.com
   2. Click Billing → Add credits (minimum $5)
   3. Relaunch QUEDE — it will work immediately.
   Your QUEDE license is NOT affected by API credits.

Q: How do I know how many credits I have left?
A: Log in to console.anthropic.com → Usage to see
   your remaining balance at any time.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
FREQUENTLY ASKED QUESTIONS

Q: Can I use QUEDE on multiple computers?
A: Solo plan: 1 computer. Team plan: up to 5 users.
   Contact support to transfer your license.

Q: Does QUEDE upload my footage anywhere?
A: No. Your files never leave your machine. QUEDE only
   sends small frame thumbnails to the AI for analysis.

Q: What video formats does QUEDE support?
A: MP4, MOV, MXF, AVI, MTS, M2TS, MKV, WMV, R3D, BRAW.

Q: The app says my license is invalid — what do I do?
A: Make sure you're entering the key exactly as shown above,
   including the dashes. If the issue persists, email us.

Q: How do I organize footage for a new project?
A: Just point QUEDE at a new folder. Each session is
   independent — no data is stored between sessions.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
NEED HELP?

  Email: support@quedeapp.com
  We typically respond within 24 hours.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Thank you for choosing QUEDE.
Order from Obsidian.

— The QUEDE Team
"""
    sg_payload = _json.dumps({
        "personalizations": [{"to": [{"email": email}]}],
        "from": {"email": from_email, "name": "QUEDE"},
        "subject": "Welcome to QUEDE — Your License Key Inside",
        "content": [{"type": "text/plain", "value": body}]
    }).encode('utf-8')
    req = urlreq.Request(
        'https://api.sendgrid.com/v3/mail/send',
        data=sg_payload,
        headers={'Authorization': f'Bearer {sg_key}', 'Content-Type': 'application/json'},
        method='POST'
    )
    with urlreq.urlopen(req, timeout=15) as resp:
        print(f"[EMAIL SENT] {email} status: {resp.status}")

@app.route('/admin/test-email', methods=['POST'])
@admin_required
def test_email():
    data = request.json or {}
    email = data.get('email', '')
    if not email:
        return jsonify({'error': 'No email provided'}), 400
    try:
        send_license_email(email, 'QUEDE-TEST-1234-ABCD', 'solo')
        return jsonify({'ok': True, 'message': f'Test email sent to {email}'})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500

@app.route('/admin/licenses', methods=['GET'])
@admin_required
def admin_licenses():
    licenses = License.query.order_by(License.created_at.desc()).all()
    return jsonify([l.to_dict() for l in licenses])

@app.route('/admin/generate', methods=['POST'])
@admin_required
def admin_generate():
    data = request.json or {}
    plan = data.get('plan', 'solo')
    email = data.get('email', '')
    company = data.get('company', '')
    key = generate_license_key()
    while License.query.filter_by(key=key).first():
        key = generate_license_key()
    new_license = License(key=key, plan=plan, max_users=1 if plan=='solo' else 5, email=email, company=company)
    db.session.add(new_license)
    db.session.commit()
    if email:
        try:
            send_license_email(email, key, plan)
        except Exception as e:
            print(f"Email send failed: {e}")
    return jsonify(new_license.to_dict())

@app.route('/admin/deactivate', methods=['POST'])
@admin_required
def admin_deactivate():
    data = request.json or {}
    key = data.get('key', '').strip().upper()
    license = License.query.filter_by(key=key).first()
    if not license:
        return jsonify({'error': 'Not found'}), 404
    license.active = False
    db.session.commit()
    return jsonify({'ok': True, 'key': key})

@app.route('/admin/reactivate', methods=['POST'])
@admin_required
def admin_reactivate():
    data = request.json or {}
    key = data.get('key', '').strip().upper()
    license = License.query.filter_by(key=key).first()
    if not license:
        return jsonify({'error': 'Not found'}), 404
    license.active = True
    db.session.commit()
    return jsonify({'ok': True, 'key': key})

@app.route('/admin/stats', methods=['GET'])
@admin_required
def admin_stats():
    total = License.query.count()
    active = License.query.filter_by(active=True).count()
    solo = License.query.filter_by(plan='solo').count()
    team = License.query.filter_by(plan='team').count()
    revenue = (solo * 25.99) + (team * 99.99)
    return jsonify({'total_licenses': total, 'active_licenses': active, 'solo_licenses': solo, 'team_licenses': team, 'estimated_revenue': round(revenue, 2)})

ADMIN_TEMPLATE = """<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>QUEDE Admin</title>
<link href="https://fonts.googleapis.com/css2?family=Outfit:wght@400;600;700;900&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>
*{box-sizing:border-box;margin:0;padding:0;}
body{font-family:'Outfit',sans-serif;background:#040406;color:#fff;min-height:100vh;padding:2rem;}
.header{display:flex;align-items:baseline;gap:16px;margin-bottom:2rem;border-bottom:1px solid rgba(255,255,255,0.08);padding-bottom:1.5rem;}
.logo{font-size:20px;font-weight:900;letter-spacing:0.4em;}
.badge{font-size:11px;font-weight:700;background:rgba(139,92,246,0.2);color:#8b5cf6;padding:3px 10px;border-radius:4px;letter-spacing:0.1em;}
.stats{display:grid;grid-template-columns:repeat(5,1fr);gap:12px;margin-bottom:2rem;}
.stat{background:rgba(255,255,255,0.04);border:1px solid rgba(255,255,255,0.08);border-radius:12px;padding:16px;}
.stat-val{font-size:28px;font-weight:900;letter-spacing:-1px;}
.stat-lbl{font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:0.1em;color:#71717a;margin-top:4px;}
.section{background:rgba(255,255,255,0.03);border:1px solid rgba(255,255,255,0.08);border-radius:16px;padding:1.5rem;margin-bottom:1.5rem;}
.section-title{font-size:11px;font-weight:800;text-transform:uppercase;letter-spacing:0.2em;color:#8b5cf6;margin-bottom:1rem;}
.row{display:flex;gap:10px;margin-bottom:10px;flex-wrap:wrap;}
input,select{background:rgba(255,255,255,0.06);border:1px solid rgba(255,255,255,0.1);border-radius:8px;padding:9px 14px;color:#fff;font-family:'Outfit',sans-serif;font-size:13px;outline:none;}
.btn{font-family:'Outfit',sans-serif;font-size:13px;font-weight:700;padding:9px 18px;border-radius:8px;cursor:pointer;border:none;}
.btn-purple{background:#8b5cf6;color:#fff;}
.btn-red{background:rgba(255,68,99,0.2);color:#FF4463;border:1px solid rgba(255,68,99,0.3);}
.btn-green{background:rgba(0,196,140,0.2);color:#00C48C;border:1px solid rgba(0,196,140,0.3);}
.table{width:100%;border-collapse:collapse;font-size:12px;}
.table th{text-align:left;font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:0.1em;color:#71717a;padding:8px 12px;border-bottom:1px solid rgba(255,255,255,0.06);}
.table td{padding:10px 12px;border-bottom:1px solid rgba(255,255,255,0.04);}
.table tr:hover td{background:rgba(255,255,255,0.02);}
.key-text{font-family:'JetBrains Mono',monospace;font-size:12px;color:#8b5cf6;}
.active-badge{background:rgba(0,196,140,0.15);color:#00C48C;padding:2px 8px;border-radius:4px;font-size:10px;font-weight:700;}
.inactive-badge{background:rgba(255,68,99,0.15);color:#FF4463;padding:2px 8px;border-radius:4px;font-size:10px;font-weight:700;}
.plan-solo{background:rgba(139,92,246,0.15);color:#8b5cf6;padding:2px 8px;border-radius:4px;font-size:10px;font-weight:700;}
.plan-team{background:rgba(45,158,255,0.15);color:#2D9EFF;padding:2px 8px;border-radius:4px;font-size:10px;font-weight:700;}
#msg{font-size:13px;color:#00C48C;margin-top:8px;min-height:20px;}
#err{font-size:13px;color:#FF4463;margin-top:8px;min-height:20px;}
#action-msg{font-size:13px;color:#00C48C;margin-top:8px;min-height:20px;}
</style></head><body>
<div class="header"><span class="logo">QUEDE</span><span class="badge">ADMIN</span></div>
<div class="stats" id="stats">
  <div class="stat"><div class="stat-val" id="s-total">—</div><div class="stat-lbl">Total Licenses</div></div>
  <div class="stat"><div class="stat-val" id="s-active">—</div><div class="stat-lbl">Active</div></div>
  <div class="stat"><div class="stat-val" id="s-solo">—</div><div class="stat-lbl">Solo</div></div>
  <div class="stat"><div class="stat-val" id="s-team">—</div><div class="stat-lbl">Team</div></div>
  <div class="stat"><div class="stat-val" id="s-rev">—</div><div class="stat-lbl">Est. Revenue</div></div>
</div>
<div class="section">
  <div class="section-title">Generate License Key</div>
  <div class="row">
    <input id="gen-email" placeholder="Customer email" style="width:220px;"/>
    <input id="gen-company" placeholder="Company name (optional)" style="width:200px;"/>
    <select id="gen-plan"><option value="solo">Solo — $25.99</option><option value="team">Team — $99.99</option></select>
    <button class="btn btn-purple" onclick="generateKey()">Generate Key</button>
  </div>
  <div id="msg"></div><div id="err"></div>
</div>
<div class="section">
  <div class="section-title">Deactivate / Reactivate</div>
  <div class="row">
    <input id="action-key" placeholder="QUEDE-XXXX-XXXX-XXXX" style="width:280px;font-family:'JetBrains Mono',monospace;"/>
    <button class="btn btn-red" onclick="deactivateKey()">Deactivate</button>
    <button class="btn btn-green" onclick="reactivateKey()">Reactivate</button>
  </div>
  <div id="action-msg"></div>
</div>
<div class="section">
  <div class="section-title">All Licenses</div>
  <input id="search" placeholder="Search by email or key..." style="width:300px;margin-bottom:1rem;" oninput="filterTable()"/>
  <table class="table"><thead><tr><th>Key</th><th>Plan</th><th>Email</th><th>Company</th><th>Status</th><th>Activations</th><th>Created</th></tr></thead>
  <tbody id="license-tbody"></tbody></table>
</div>
<script>
var ADMIN_PASS=prompt('Admin password:');
var allLicenses=[];
async function api(url,method,body){
  var opts={method:method||'GET',headers:{'X-Admin-Password':ADMIN_PASS,'Content-Type':'application/json'}};
  if(body) opts.body=JSON.stringify(body);
  return (await fetch(url,opts)).json();
}
async function loadStats(){
  var s=await api('/admin/stats');
  document.getElementById('s-total').textContent=s.total_licenses||0;
  document.getElementById('s-active').textContent=s.active_licenses||0;
  document.getElementById('s-solo').textContent=s.solo_licenses||0;
  document.getElementById('s-team').textContent=s.team_licenses||0;
  document.getElementById('s-rev').textContent='$'+(s.estimated_revenue||0).toLocaleString();
}
async function loadLicenses(){
  allLicenses=await api('/admin/licenses');
  renderTable(allLicenses);
}
function renderTable(licenses){
  document.getElementById('license-tbody').innerHTML=licenses.map(function(l){
    return '<tr><td class="key-text">'+l.key+'</td><td><span class="plan-'+l.plan+'">'+l.plan.toUpperCase()+'</span></td><td>'+(l.email||'—')+'</td><td>'+(l.company||'—')+'</td><td><span class="'+(l.active?'active-badge':'inactive-badge')+'">'+(l.active?'ACTIVE':'INACTIVE')+'</span></td><td>'+l.activations+'</td><td>'+(l.created_at?l.created_at.slice(0,10):'—')+'</td></tr>';
  }).join('');
}
function filterTable(){
  var q=document.getElementById('search').value.toLowerCase();
  renderTable(allLicenses.filter(function(l){return l.key.toLowerCase().includes(q)||(l.email||'').toLowerCase().includes(q);}));
}
async function generateKey(){
  var email=document.getElementById('gen-email').value.trim();
  var company=document.getElementById('gen-company').value.trim();
  var plan=document.getElementById('gen-plan').value;
  if(!email){document.getElementById('err').textContent='Email required.';return;}
  var result=await api('/admin/generate','POST',{email,company,plan});
  if(result.key){document.getElementById('msg').textContent='Generated: '+result.key+' — for '+email;document.getElementById('err').textContent='';loadStats();loadLicenses();}
  else{document.getElementById('err').textContent=result.error||'Failed.';}
}
async function deactivateKey(){
  var key=document.getElementById('action-key').value.trim().toUpperCase();
  if(!key) return;
  var r=await api('/admin/deactivate','POST',{key});
  document.getElementById('action-msg').textContent=r.ok?'Deactivated: '+key:(r.error||'Failed.');
  loadLicenses();
}
async function reactivateKey(){
  var key=document.getElementById('action-key').value.trim().toUpperCase();
  if(!key) return;
  var r=await api('/admin/reactivate','POST',{key});
  document.getElementById('action-msg').textContent=r.ok?'Reactivated: '+key:(r.error||'Failed.');
  loadLicenses();
}
loadStats();loadLicenses();
</script>
</body></html>"""

with app.app_context():
    db.create_all()

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port, debug=False)

"""
Masroofi — site web (vitrine + paiement Gumroad + génération de licence)

Gumroad gère le paiement (carte, PayPal) sur sa propre page hébergée —
aucune restriction de pays vendeur comme Stripe.

Flux :
  1. Le client clique "Acheter" → redirigé vers ton produit Gumroad
  2. Après paiement, Gumroad appelle ton webhook "Ping" (configuré dans
     Gumroad → Settings → Advanced → Ping) avec les infos de vente
  3. On vérifie la vente via l'API Gumroad (sécurité), on génère la clé,
     on l'envoie par email et on la stocke pour la page de succès
  4. Gumroad peut aussi rediriger le client vers /success?sale_id=...
     si tu actives "Redirect to URL after purchase" sur le produit

Lancer en local :
    pip install -r requirements.txt
    set GUMROAD_ACCESS_TOKEN=xxxxx     (Settings > Advanced > Applications)
    python app.py

Pour recevoir le webhook en local, utilise ngrok :
    ngrok http 5000
    → mets l'URL https://xxxx.ngrok.io/gumroad-webhook dans
      Gumroad → ton produit → Settings → Advanced → Ping
"""
import os
import sqlite3
import smtplib
import urllib.request
import urllib.parse
import json
from email.mime.text import MIMEText
from datetime import datetime

from flask import Flask, render_template, request, redirect, jsonify

from licensing import generate_key

app = Flask(__name__)

# ── Configuration ──────────────────────────────────────────────────────
GUMROAD_ACCESS_TOKEN = os.environ.get("GUMROAD_ACCESS_TOKEN", "")

SMTP_HOST = os.environ.get("SMTP_HOST", "")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USER = os.environ.get("SMTP_USER", "")
SMTP_PASS = os.environ.get("SMTP_PASS", "")
FROM_EMAIL = os.environ.get("FROM_EMAIL", SMTP_USER or "noreply@masroofi.local")

DB_PATH = os.path.join(os.path.dirname(__file__), "orders.db")

# ── Products — map each Gumroad product permalink to a license duration.
# Permalink = the part after gumroad.com/l/ in your product URL.
PLANS = {
    "lkpmrw": {
        "label": "1 an",
        "days": 365,
        "price_display": "49.00 QAR",
        "gumroad_url": "https://assaad7.gumroad.com/l/lkpmrw",
    },
    "hfbtt": {
        "label": "À vie",
        "days": 0,
        "price_display": "149.00 QAR",
        "gumroad_url": "https://assaad7.gumroad.com/l/hfbtt",
    },
}


def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sale_id TEXT UNIQUE,
            customer_name TEXT,
            customer_email TEXT,
            plan TEXT,
            license_key TEXT,
            created_at TEXT
        )
    """)
    conn.commit()
    conn.close()


def save_order(sale_id, name, email, plan, key):
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "INSERT OR IGNORE INTO orders (sale_id, customer_name, customer_email, plan, license_key, created_at) "
        "VALUES (?,?,?,?,?,?)",
        (sale_id, name, email, plan, key, datetime.now().isoformat()),
    )
    conn.commit()
    conn.close()


def get_order_by_sale(sale_id):
    conn = sqlite3.connect(DB_PATH)
    row = conn.execute(
        "SELECT customer_name, customer_email, plan, license_key FROM orders WHERE sale_id=?",
        (sale_id,),
    ).fetchone()
    conn.close()
    return row


def verify_gumroad_sale(sale_id):
    """Calls Gumroad's API to confirm this sale really happened —
    prevents someone from forging a fake Ping to your webhook."""
    if not GUMROAD_ACCESS_TOKEN:
        print("[WARN] GUMROAD_ACCESS_TOKEN not set — skipping server-side verification "
              "(ok for quick local testing, NOT safe for production).")
        return True
    url = f"https://api.gumroad.com/v2/sales/{sale_id}?access_token={GUMROAD_ACCESS_TOKEN}"
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            data = json.loads(resp.read().decode())
        return data.get("success") and data.get("sale", {}).get("id") == sale_id
    except Exception as e:
        print(f"[ERROR] Gumroad verification failed: {e}")
        return False


def send_license_email(to_email, name, key, plan_label):
    if not SMTP_HOST:
        print(f"[INFO] SMTP not configured — license for {to_email} not emailed (shown on success page only).")
        return
    body = (
        f"Bonjour {name},\n\n"
        f"Merci pour votre achat de Masroofi ({plan_label}).\n\n"
        f"Votre clé de licence :\n{key}\n\n"
        f"Collez-la dans Masroofi → Help → Activate License.\n\n"
        f"— L'équipe Masroofi"
    )
    msg = MIMEText(body, _charset="utf-8")
    msg["Subject"] = "Votre clé de licence Masroofi"
    msg["From"] = FROM_EMAIL
    msg["To"] = to_email
    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASS)
            server.send_message(msg)
    except Exception as e:
        print(f"[WARN] Failed to send license email: {e}")


# ── Routes ────────────────────────────────────────────────────────────────
@app.route("/")
def index():
    return render_template("index.html", plans=PLANS)


@app.route("/success")
def success():
    """Optional: set this URL (https://yourdomain/success) as the
    'Redirect to URL after purchase' on your Gumroad product, Gumroad
    appends ?sale_id=... automatically."""
    sale_id = request.args.get("sale_id", "")
    order = get_order_by_sale(sale_id)
    if order:
        name, email, plan, key = order
        return render_template("success.html", name=name, email=email, license_key=key, pending=False)
    return render_template("success.html", name=None, email=None, license_key=None,
                            pending=True, sale_id=sale_id)


@app.route("/check-order")
def check_order():
    sale_id = request.args.get("sale_id", "")
    order = get_order_by_sale(sale_id)
    if order:
        name, email, plan, key = order
        return jsonify({"ready": True, "license_key": key, "name": name})
    return jsonify({"ready": False})


@app.route("/gumroad-webhook", methods=["POST"])
def gumroad_webhook():
    """Gumroad 'Ping' sends form-encoded data (not JSON)."""
    data = request.form
    sale_id = data.get("sale_id", "")
    email = data.get("email", "")
    name = data.get("full_name") or email.split("@")[0]
    permalink = data.get("permalink", "")
    is_test = data.get("test") == "true"

    if not sale_id or not email:
        return jsonify({"error": "missing sale_id/email"}), 400

    if not is_test and not verify_gumroad_sale(sale_id):
        print(f"[SECURITY] Could not verify sale {sale_id} with Gumroad API — ignoring.")
        return jsonify({"error": "unverified sale"}), 400

    plan = PLANS.get(permalink)
    if not plan:
        # Unknown product permalink — default to 1-year so nothing silently fails
        plan = {"label": "1 an", "days": 365}

    result = generate_key(name, days=plan["days"])
    save_order(sale_id, name, email, permalink, result["full_key"])
    send_license_email(email, name, result["full_key"], plan["label"])
    print(f"[WEBHOOK] License generated for {email}: {result['full_key']}")

    return jsonify({"received": True})


if __name__ == "__main__":
    init_db()
    print("=" * 60)
    print("  Masroofi website — LOCAL TEST MODE (Gumroad)")
    print("  http://localhost:5000")
    print("  Configure your Gumroad product permalinks in PLANS (app.py)")
    print("  and the Ping webhook to point at /gumroad-webhook")
    print("  (use ngrok for a public HTTPS URL while testing locally)")
    print("=" * 60)
    app.run(debug=True, host="0.0.0.0", port=5000)


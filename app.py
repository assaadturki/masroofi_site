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

from flask import Flask, render_template, request, redirect, jsonify, session, url_for, send_from_directory, make_response
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash

from licensing import generate_key, validate_key
from i18n import get_translator, is_rtl, DEFAULT_LANG

COUNTRIES = sorted(["Qatar", "Tunisia", "Saudi Arabia", "UAE", "Kuwait", "Bahrain", "Oman",
             "Jordan", "Egypt", "Morocco", "Algeria", "Libya", "Lebanon", "Syria",
             "Iraq", "Yemen", "Turkey", "France", "United Kingdom", "Germany",
             "Italy", "Spain", "USA", "Canada", "India", "Pakistan"]) + ["Other"]
REPORT_THRESHOLD = 3  # auto-hide a deal after this many reports

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET", "change-this-secret-too")


def get_lang():
    return session.get("lang", DEFAULT_LANG)


@app.context_processor
def inject_i18n():
    lang = get_lang()
    return {"t": get_translator(lang), "lang": lang, "is_rtl": is_rtl(lang)}


@app.route("/set-lang/<lang>")
def set_lang(lang):
    if lang in ("ar", "en", "fr"):
        session["lang"] = lang
    return redirect(request.referrer or url_for("index"))


# ── Configuration ──────────────────────────────────────────────────────
GUMROAD_ACCESS_TOKEN = os.environ.get("GUMROAD_ACCESS_TOKEN", "")

SMTP_HOST = os.environ.get("SMTP_HOST", "")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USER = os.environ.get("SMTP_USER", "")
SMTP_PASS = os.environ.get("SMTP_PASS", "")
FROM_EMAIL = os.environ.get("FROM_EMAIL", SMTP_USER or "noreply@masroofi.local")

DB_DIR = os.environ.get("DATA_DIR", os.path.dirname(__file__))
DB_PATH = os.path.join(DB_DIR, "orders.db")

ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "changeme")
SITE_API_KEY = os.environ.get("SITE_API_KEY", "changeme-api-key")
DEALS_IMG_DIR = os.path.join(DB_DIR, "deals_images")
os.makedirs(DEALS_IMG_DIR, exist_ok=True)

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
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
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
    conn.execute("""
        CREATE TABLE IF NOT EXISTS activations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            license_key TEXT NOT NULL,
            machine_id TEXT NOT NULL,
            activated_at TEXT,
            UNIQUE(license_key, machine_id)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS deals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            description TEXT DEFAULT '',
            store TEXT DEFAULT '',
            location TEXT DEFAULT '',
            maps_link TEXT DEFAULT '',
            price REAL DEFAULT NULL,
            currency TEXT DEFAULT '',
            link TEXT DEFAULT '',
            image_filename TEXT DEFAULT '',
            expires_at TEXT DEFAULT '',
            source TEXT DEFAULT 'manual',
            active INTEGER DEFAULT 1,
            created_at TEXT
        )
    """)
    for col_sql in [
        "ALTER TABLE deals ADD COLUMN maps_link TEXT DEFAULT ''",
        "ALTER TABLE deals ADD COLUMN country TEXT DEFAULT ''",
        "ALTER TABLE deals ADD COLUMN submitter_email TEXT DEFAULT ''",
        "ALTER TABLE deals ADD COLUMN reports_count INTEGER DEFAULT 0",
    ]:
        try: conn.execute(col_sql)
        except Exception: pass

    # Buyers — registered at purchase time (name, email, country, NO key yet).
    # Marked verified=1 by the Gumroad webhook once payment is confirmed.
    # This record is what unlocks access to "Bons Plans" — no license key
    # needs to be pasted anywhere on the website.
    conn.execute("""
        CREATE TABLE IF NOT EXISTS buyers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            country TEXT NOT NULL,
            plan TEXT DEFAULT '',
            password_hash TEXT DEFAULT '',
            verified INTEGER DEFAULT 0,
            created_at TEXT
        )
    """)
    try: conn.execute("ALTER TABLE buyers ADD COLUMN password_hash TEXT DEFAULT ''")
    except Exception: pass

    conn.execute("""
        CREATE TABLE IF NOT EXISTS deal_reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            deal_id INTEGER NOT NULL,
            reporter_ip TEXT DEFAULT '',
            created_at TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS stats (
            key TEXT PRIMARY KEY,
            count INTEGER DEFAULT 0
        )
    """)
    conn.execute("INSERT OR IGNORE INTO stats (key, count) VALUES ('visits', 0)")
    conn.execute("INSERT OR IGNORE INTO stats (key, count) VALUES ('downloads', 0)")
    conn.commit()
    conn.close()


def save_order(sale_id, name, email, plan, key):
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.execute(
        "INSERT OR IGNORE INTO orders (sale_id, customer_name, customer_email, plan, license_key, created_at) "
        "VALUES (?,?,?,?,?,?)",
        (sale_id, name, email, plan, key, datetime.now().isoformat()),
    )
    conn.commit()
    conn.close()


def get_order_by_sale(sale_id):
    conn = sqlite3.connect(DB_PATH, timeout=30)
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


DOWNLOAD_FILE_URL = "https://github.com/assaadturki/masroofi_site/releases/download/app/masroofi_Setup_v4.3.exe"


def _get_conn():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def _increment_stat(key):
    conn = _get_conn()
    conn.execute("UPDATE stats SET count = count + 1 WHERE key=?", (key,))
    conn.commit(); conn.close()


def _get_stat(key):
    conn = _get_conn()
    row = conn.execute("SELECT count FROM stats WHERE key=?", (key,)).fetchone()
    conn.close()
    return row[0] if row else 0


# ── Routes ────────────────────────────────────────────────────────────────
@app.route("/")
def index():
    # Count unique visits per day via cookie
    today = datetime.now().strftime("%Y-%m-%d")
    last_visit = request.cookies.get("last_visit")
    resp = None
    if last_visit != today:
        _increment_stat("visits")
        resp = make_response(render_template("index.html", plans=PLANS,
                                visits=_get_stat("visits"), downloads=_get_stat("downloads")))
        resp.set_cookie("last_visit", today, max_age=60*60*24*365)
        return resp
    return render_template("index.html", plans=PLANS,
                            visits=_get_stat("visits"), downloads=_get_stat("downloads"))


@app.route("/download")
def download():
    _increment_stat("downloads")
    return redirect(DOWNLOAD_FILE_URL)


@app.route("/manual")
def manual():
    return render_template("manual.html")


@app.route("/manual/ar")
def manual_ar():
    return render_template("manual_ar.html")


@app.route("/manual.pdf")
def manual_pdf():
    return app.send_static_file("manual.pdf")


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


# ── Current app version (update this on every release) ───────────────────
CURRENT_VERSION = "4.3"
DOWNLOAD_URL = "https://yourdomain.com/"  # the landing page with the download button


@app.route("/api/version")
def api_version():
    """Polled by Masroofi on startup to check for updates."""
    return jsonify({
        "latest_version": CURRENT_VERSION,
        "download_url": DOWNLOAD_URL,
    })


def _parse_license_payload(full_key):
    """Decode name/expiry/seats from a full license key WITHOUT re-verifying
    the HMAC signature here (Masroofi.py already verified it before calling
    /activate). Returns (name, expiry, seats) or None."""
    try:
        payload_b64, _sig = full_key.split(".")
        import base64 as _b64
        payload = _b64.urlsafe_b64decode(payload_b64 + "==").decode()
        parts = payload.split("|")
        name = parts[0]
        expiry = parts[1] if len(parts) > 1 else ""
        seats = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 1
        return name, expiry, seats
    except Exception:
        return None


@app.route("/activate", methods=["POST"])
def activate():
    """Called by Masroofi.py when a license key is entered.
    Enforces the seat count embedded in the key (1, 5, 10 computers...).
    If this endpoint is unreachable (no internet), Masroofi.py falls back
    to its own offline HMAC validation without seat enforcement."""
    data = request.get_json(silent=True) or request.form
    full_key = (data.get("license_key") or "").strip()
    machine_id = (data.get("machine_id") or "").strip()
    if not full_key or not machine_id:
        return jsonify({"ok": False, "error": "missing license_key or machine_id"}), 400

    parsed = _parse_license_payload(full_key)
    if not parsed:
        return jsonify({"ok": False, "error": "invalid key format"}), 400
    name, expiry, seats = parsed

    conn = sqlite3.connect(DB_PATH, timeout=30)
    already = conn.execute(
        "SELECT 1 FROM activations WHERE license_key=? AND machine_id=?",
        (full_key, machine_id)).fetchone()
    if already:
        conn.close()
        return jsonify({"ok": True, "seats": seats, "already_activated": True})

    used = conn.execute(
        "SELECT COUNT(*) FROM activations WHERE license_key=?", (full_key,)).fetchone()[0]
    if used >= seats:
        conn.close()
        return jsonify({"ok": False, "error": f"Seat limit reached ({used}/{seats} computers already activated)"}), 403

    conn.execute(
        "INSERT INTO activations (license_key, machine_id, activated_at) VALUES (?,?,?)",
        (full_key, machine_id, datetime.now().isoformat()))
    conn.commit()
    conn.close()
    return jsonify({"ok": True, "seats": seats, "used": used + 1})


@app.route("/register", methods=["GET", "POST"])
def register():
    """Shown when someone clicks a 'Buy' button on the homepage — collects
    name/email/country BEFORE sending them to Gumroad (no license key yet,
    they haven't paid). The Gumroad webhook later marks this email as
    'verified' once payment is confirmed."""
    plan_id = request.args.get("plan", "") or request.form.get("plan", "")
    plan = PLANS.get(plan_id)
    error = None

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip()
        country = request.form.get("country", "").strip()
        password = request.form.get("password", "")
        password2 = request.form.get("password2", "")
        if not (name and email and country and password):
            error = "Tous les champs sont obligatoires."
        elif password != password2:
            error = "Les mots de passe ne correspondent pas."
        elif len(password) < 6:
            error = "Le mot de passe doit faire au moins 6 caractères."
        elif not plan:
            error = "Offre invalide."
        else:
            conn = sqlite3.connect(DB_PATH, timeout=30)
            existing = conn.execute("SELECT id FROM buyers WHERE email=?", (email,)).fetchone()
            if existing:
                error = "Un compte existe déjà avec cet email — connecte-toi plutôt."
                conn.close()
            else:
                conn.execute("""INSERT INTO buyers (name,email,country,plan,password_hash,verified,created_at)
                                VALUES (?,?,?,?,?,0,?)""",
                            (name, email, country, plan_id,
                             generate_password_hash(password), datetime.now().isoformat()))
                conn.commit(); conn.close()
                session["buyer_email"] = email
                session["buyer_country"] = country
                return redirect(plan["gumroad_url"])

    if not plan:
        return redirect(url_for("index"))
    return render_template("register.html", error=error, countries=COUNTRIES, plan=plan, plan_id=plan_id)


@app.route("/claim-account", methods=["GET", "POST"])
def claim_account():
    """For buyers who purchased directly on Gumroad without registering on
    our site first — lets them set a password using the email they paid
    with, so they can log in and access Bons Plans."""
    error = None
    if request.method == "POST":
        email = request.form.get("email", "").strip()
        country = request.form.get("country", "").strip()
        password = request.form.get("password", "")
        password2 = request.form.get("password2", "")
        conn = sqlite3.connect(DB_PATH, timeout=30)
        row = conn.execute("SELECT verified, password_hash FROM buyers WHERE email=?", (email,)).fetchone()
        if not row or not row[0]:
            error = "Aucun achat vérifié trouvé pour cet email."
        elif row[1]:
            error = "Un mot de passe existe déjà pour ce compte — connecte-toi."
        elif password != password2:
            error = "Les mots de passe ne correspondent pas."
        elif len(password) < 6:
            error = "Le mot de passe doit faire au moins 6 caractères."
        else:
            conn.execute("UPDATE buyers SET password_hash=?, country=? WHERE email=?",
                         (generate_password_hash(password), country or "", email))
            conn.commit(); conn.close()
            session["buyer_email"] = email
            session["buyer_country"] = country
            return redirect(url_for("deals_public"))
        conn.close()
    return render_template("claim_account.html", error=error, countries=COUNTRIES)


@app.route("/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "")
        conn = sqlite3.connect(DB_PATH, timeout=30)
        row = conn.execute("SELECT country, password_hash, verified FROM buyers WHERE email=?",
                            (email,)).fetchone()
        conn.close()
        if not row or not row[1] or not check_password_hash(row[1], password):
            error = "Email ou mot de passe incorrect."
        else:
            session["buyer_email"] = email
            session["buyer_country"] = row[0]
            return redirect(url_for("deals_public"))
    return render_template("login.html", error=error)


@app.route("/logout")
def logout():
    session.pop("buyer_email", None)
    session.pop("buyer_country", None)
    return redirect(url_for("index"))


def _current_buyer():
    """Returns (email, country, verified) for the visitor, or (None, None, False)."""
    email = session.get("buyer_email")
    if not email:
        return None, None, False
    conn = sqlite3.connect(DB_PATH, timeout=30)
    row = conn.execute("SELECT country, verified FROM buyers WHERE email=?", (email,)).fetchone()
    conn.close()
    if not row:
        return None, None, False
    return email, row[0], bool(row[1])


@app.route("/deals-img/<filename>")
def deals_img(filename):
    return send_from_directory(DEALS_IMG_DIR, filename)


@app.route("/deals")
def deals_public():
    email, buyer_country, verified = _current_buyer()
    if not verified:
        return render_template("deals_locked.html", plans=PLANS)

    selected_country = request.args.get("country", buyer_country or "")

    conn = sqlite3.connect(DB_PATH, timeout=30)
    today = datetime.now().strftime("%Y-%m-%d")
    query = """
        SELECT title, description, store, location, maps_link, price, currency, link,
               image_filename, expires_at, source, id, country
        FROM deals
        WHERE active=1 AND (expires_at='' OR expires_at >= ?)"""
    params = [today]
    if selected_country and selected_country != "all":
        query += " AND (country=? OR country='')"
        params.append(selected_country)
    query += " ORDER BY id DESC"
    rows = conn.execute(query, params).fetchall()
    conn.close()

    enriched = []
    for title, description, store, location, maps_link, price, currency, link, image, expires_at, source, deal_id, country in rows:
        final_maps_link = maps_link or (
            "https://www.google.com/maps/search/?api=1&query=" + urllib.parse.quote(location)
            if location else "")
        enriched.append((title, description, store, location, final_maps_link, price,
                          currency, link, image, expires_at, source, deal_id, country))
    return render_template("deals.html", deals=enriched, countries=COUNTRIES,
                            selected_country=selected_country or "all",
                            buyer_country=buyer_country, is_submitter=True)


@app.route("/submit-deal", methods=["GET", "POST"])
def submit_deal():
    email, buyer_country, verified = _current_buyer()
    if not verified:
        return render_template("deals_locked.html", plans=PLANS)

    success = False
    if request.method == "POST":
        title = request.form.get("title", "").strip()
        if title:
            image_filename = ""
            file = request.files.get("image")
            if file and file.filename:
                image_filename = secure_filename(f"{datetime.now().timestamp()}_{file.filename}")
                file.save(os.path.join(DEALS_IMG_DIR, image_filename))
            conn = sqlite3.connect(DB_PATH, timeout=30)
            conn.execute("""INSERT INTO deals
                (title, description, store, location, maps_link, price, currency, link,
                 image_filename, expires_at, country, source, submitter_email, created_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (title, request.form.get("description", "").strip(),
                 request.form.get("store", "").strip(),
                 request.form.get("location", "").strip(),
                 request.form.get("maps_link", "").strip(),
                 request.form.get("price") or None,
                 request.form.get("currency", "").strip(),
                 request.form.get("link", "").strip(),
                 image_filename, request.form.get("expires_at", "").strip(),
                 request.form.get("country", "").strip() or buyer_country,
                 "user_submitted", email, datetime.now().isoformat()))
            conn.commit(); conn.close()
            success = True

    return render_template("submit_deal.html", success=success, countries=COUNTRIES,
                            default_country=buyer_country)


@app.route("/report-deal/<int:deal_id>", methods=["POST"])
def report_deal(deal_id):
    ip = request.headers.get("X-Forwarded-For", request.remote_addr or "")
    conn = sqlite3.connect(DB_PATH, timeout=30)
    already = conn.execute(
        "SELECT 1 FROM deal_reports WHERE deal_id=? AND reporter_ip=?", (deal_id, ip)).fetchone()
    if not already:
        conn.execute("INSERT INTO deal_reports (deal_id, reporter_ip, created_at) VALUES (?,?,?)",
                     (deal_id, ip, datetime.now().isoformat()))
        conn.execute("UPDATE deals SET reports_count = reports_count + 1 WHERE id=?", (deal_id,))
        count = conn.execute("SELECT reports_count FROM deals WHERE id=?", (deal_id,)).fetchone()[0]
        if count >= REPORT_THRESHOLD:
            conn.execute("UPDATE deals SET active=0 WHERE id=?", (deal_id,))
        conn.commit()
    conn.close()
    return redirect(url_for("deals_public"))


@app.route("/admin/deals", methods=["GET", "POST"])
def admin_deals():
    if not session.get("is_admin"):
        if request.method == "POST" and request.form.get("password"):
            if request.form.get("password") == ADMIN_PASSWORD:
                session["is_admin"] = True
                return redirect(url_for("admin_deals"))
            return render_template("admin_login.html", error="Wrong password")
        return render_template("admin_login.html", error=None)

    if request.method == "POST" and request.form.get("action") == "add":
        title = request.form.get("title", "").strip()
        if title:
            image_filename = ""
            file = request.files.get("image")
            if file and file.filename:
                image_filename = secure_filename(f"{datetime.now().timestamp()}_{file.filename}")
                file.save(os.path.join(DEALS_IMG_DIR, image_filename))
            conn = sqlite3.connect(DB_PATH, timeout=30)
            conn.execute("""INSERT INTO deals
                (title, description, store, location, maps_link, price, currency, link,
                 image_filename, expires_at, source, created_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (title, request.form.get("description", "").strip(),
                 request.form.get("store", "").strip(),
                 request.form.get("location", "").strip(),
                 request.form.get("maps_link", "").strip(),
                 request.form.get("price") or None,
                 request.form.get("currency", "").strip(),
                 request.form.get("link", "").strip(),
                 image_filename, request.form.get("expires_at", "").strip(),
                 "manual", datetime.now().isoformat()))
            conn.commit(); conn.close()
        return redirect(url_for("admin_deals"))

    if request.method == "POST" and request.form.get("action") == "delete":
        deal_id = request.form.get("deal_id")
        conn = sqlite3.connect(DB_PATH, timeout=30)
        conn.execute("DELETE FROM deals WHERE id=?", (deal_id,))
        conn.commit(); conn.close()
        return redirect(url_for("admin_deals"))

    if request.method == "POST" and request.form.get("action") == "reactivate":
        deal_id = request.form.get("deal_id")
        conn = sqlite3.connect(DB_PATH, timeout=30)
        conn.execute("UPDATE deals SET active=1, reports_count=0 WHERE id=?", (deal_id,))
        conn.commit(); conn.close()
        return redirect(url_for("admin_deals"))

    conn = sqlite3.connect(DB_PATH, timeout=30)
    rows = conn.execute("""SELECT id,title,description,store,location,maps_link,price,currency,
                                   link,image_filename,expires_at,source,active,country,reports_count
                            FROM deals ORDER BY reports_count DESC, id DESC""").fetchall()
    conn.close()
    return render_template("admin_deals.html", deals=rows)


@app.route("/admin/logout")
def admin_logout():
    session.pop("is_admin", None)
    return redirect(url_for("admin_deals"))


@app.route("/api/import-deal", methods=["POST"])
def import_deal():
    """Called from Masroofi's Price Comparison window ('Send to Website' button).
    Protected by a shared secret key (SITE_API_KEY) — set the same value in
    Masroofi.py's _SITE_API_KEY constant."""
    data = request.get_json(silent=True) or {}
    if data.get("api_key") != SITE_API_KEY:
        return jsonify({"ok": False, "error": "invalid api key"}), 403

    title = (data.get("title") or "").strip()
    if not title:
        return jsonify({"ok": False, "error": "title required"}), 400

    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.execute("""INSERT INTO deals
        (title, description, store, location, maps_link, price, currency, link,
         expires_at, source, created_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        (title, data.get("description",""), data.get("store",""),
         data.get("location",""), data.get("maps_link",""), data.get("price"),
         data.get("currency",""), data.get("link",""), data.get("expires_at",""),
         "price_comparison", datetime.now().isoformat()))
    conn.commit(); conn.close()
    return jsonify({"ok": True})


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

    # Mark this email as a VERIFIED buyer — this is what unlocks "Bons Plans"
    # access on the website. No license key needs to be entered anywhere.
    conn = sqlite3.connect(DB_PATH, timeout=30)
    existing = conn.execute("SELECT id, country FROM buyers WHERE email=?", (email,)).fetchone()
    if existing:
        conn.execute("UPDATE buyers SET verified=1, plan=? WHERE email=?", (permalink, email))
    else:
        # Purchased directly on Gumroad without going through our /register
        # page first — still track them, country unknown for now.
        conn.execute("""INSERT INTO buyers (name, email, country, plan, verified, created_at)
                        VALUES (?,?,?,?,1,?)""",
                     (name, email, "", permalink, datetime.now().isoformat()))
    conn.commit(); conn.close()

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
    port = int(os.environ.get("PORT", 5000))
    debug_mode = os.environ.get("FLASK_DEBUG", "0") == "1"
    app.run(debug=debug_mode, host="0.0.0.0", port=port)


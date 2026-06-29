"""
licensing.py — Same algorithm as keygen.py / Masroofi.py's _validate_key.
Keep SECRET identical to the one embedded in Masroofi.py (_LIC_SECRET).
"""
import hmac, hashlib, base64, datetime

# Must match _LIC_SECRET in Masroofi.py exactly
SECRET = b"MasrooFi@2026#LassaadTurki!ChangeMe"


def generate_key(customer_name: str, days: int = 0, seats: int = 1) -> dict:
    """
    days=0   -> lifetime license
    days>0   -> expires in N days from today
    seats    -> number of computers allowed to activate this key (1, 5, 10...)
    """
    expiry = ""
    if days > 0:
        expiry = (datetime.date.today() + datetime.timedelta(days=days)).isoformat()

    payload = f"{customer_name.upper()}|{expiry}|{seats}"
    payload_b64 = base64.urlsafe_b64encode(payload.encode()).decode()

    sig = hmac.new(SECRET, payload_b64.encode(), hashlib.sha256).hexdigest()[:16].upper()

    full = f"{payload_b64}.{sig}"

    return {
        "customer_name": customer_name,
        "expiry": expiry or "Lifetime",
        "seats": seats,
        "full_key": full,
    }


def validate_key(full_key: str):
    """Same validation as Masroofi.py's _validate_key — used to verify a
    user is a paying customer before letting them submit a deal.
    Returns (ok: bool, message: str) — message is the customer name on
    success, or an error description on failure."""
    try:
        parts = full_key.strip().split(".")
        if len(parts) != 2:
            return False, "Invalid key format"
        payload_b64, sig = parts
        expected = hmac.new(SECRET, payload_b64.encode(), hashlib.sha256).hexdigest()[:16].upper()
        if not hmac.compare_digest(sig.upper(), expected):
            return False, "Invalid key — signature mismatch"
        payload = base64.urlsafe_b64decode(payload_b64 + "==").decode()
        pparts = payload.split("|")
        name = pparts[0]
        expiry = pparts[1] if len(pparts) > 1 else ""
        if expiry:
            if datetime.date.today() > datetime.date.fromisoformat(expiry):
                return False, f"License expired on {expiry}"
        return True, name
    except Exception as e:
        return False, f"Key error: {e}"

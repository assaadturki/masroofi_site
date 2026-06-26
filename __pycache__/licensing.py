"""
licensing.py — Same algorithm as keygen.py / Masroofi.py's _validate_key.
Keep SECRET identical to the one embedded in Masroofi.py (_LIC_SECRET).
"""
import hmac, hashlib, base64, datetime

# Must match _LIC_SECRET in Masroofi.py exactly
SECRET = b"MasrooFi@2026#LassaadTurki!ChangeMe"


def generate_key(customer_name: str, days: int = 0) -> dict:
    """
    days=0   -> lifetime license
    days>0   -> expires in N days from today
    Returns dict with the full key string (what the user pastes in the app)
    and metadata.
    """
    expiry = ""
    if days > 0:
        expiry = (datetime.date.today() + datetime.timedelta(days=days)).isoformat()

    payload = f"{customer_name.upper()}|{expiry}"
    payload_b64 = base64.urlsafe_b64encode(payload.encode()).decode()

    sig = hmac.new(SECRET, payload_b64.encode(), hashlib.sha256).hexdigest()[:16].upper()

    full = f"{payload_b64}.{sig}"

    return {
        "customer_name": customer_name,
        "expiry": expiry or "Lifetime",
        "full_key": full,
    }

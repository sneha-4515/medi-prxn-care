import hashlib, hmac, os, base64, json, time
from . import config
from fastapi import Header, HTTPException
SECRET = config.SECRET_KEY.encode()

def hash_pw(pw, salt=None):
    salt = salt or os.urandom(8).hex()
    return salt + "$" + hashlib.pbkdf2_hmac("sha256", pw.encode(), salt.encode(), 100_000).hex()

def check_pw(pw, stored):
    salt = stored.split("$")[0]
    return hmac.compare_digest(hash_pw(pw, salt), stored)

def make_token(uid, role):
    body = base64.urlsafe_b64encode(json.dumps({"uid": uid, "role": role, "exp": time.time() + 86400}).encode()).decode()
    sig = hmac.new(SECRET, body.encode(), "sha256").hexdigest()
    return f"{body}.{sig}"

def current_user(authorization: str = Header(None)):
    try:
        body, sig = authorization.removeprefix("Bearer ").split(".")
        if not hmac.compare_digest(sig, hmac.new(SECRET, body.encode(), "sha256").hexdigest()): raise ValueError
        d = json.loads(base64.urlsafe_b64decode(body))
        if d["exp"] < time.time(): raise ValueError
        return d
    except Exception:
        raise HTTPException(401, "Invalid or missing token")

def require(*roles):
    def dep(authorization: str = Header(None)):
        u = current_user(authorization)
        if u["role"] not in roles: raise HTTPException(403, f"Requires role: {'/'.join(roles)}")
        return u
    return dep

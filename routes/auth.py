"""OneCare Loop — routes/auth.py"""

from flask import Blueprint, jsonify, redirect, render_template, request, session

from services.auth import authenticate, create_user, get_user


bp = Blueprint("auth", __name__, url_prefix="/auth")


@bp.get("/login")
def login_page():
    if session.get("user_id"):
        return redirect("/app")
    return render_template("auth/login.html")


@bp.post("/login")
def login_submit():
    data = request.get_json(silent=True) or request.form
    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""
    user = authenticate(email, password)
    if not user:
        return jsonify({"ok": False, "error": "Invalid email or password."}), 401
    session["user_id"] = user["id"]
    session["email"] = user["email"]
    session["role"] = user["role"]
    return jsonify({"ok": True, "redirect": "/app"})


@bp.get("/signup")
def signup_page():
    if session.get("user_id"):
        return redirect("/app")
    return render_template("auth/signup.html")


@bp.post("/signup")
def signup_submit():
    data = request.get_json(silent=True) or request.form
    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""
    name = (data.get("name") or "").strip()
    role = (data.get("role") or "admin").strip()
    if not email or "@" not in email or len(password) < 6 or not name:
        return jsonify({"ok": False, "error": "Please fill all fields (password 6+ characters)."}), 400
    try:
        user = create_user(email, password, name, role)
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    session["user_id"] = user["id"]
    session["email"] = user["email"]
    session["role"] = user["role"]
    return jsonify({"ok": True, "redirect": "/app"})


@bp.post("/logout")
def logout():
    session.clear()
    return jsonify({"ok": True, "redirect": "/"})


@bp.get("/me")
def me():
    uid = session.get("user_id")
    if not uid:
        return jsonify({"ok": False}), 401
    user = get_user(uid)
    if not user:
        return jsonify({"ok": False}), 401
    return jsonify({"ok": True, "user": user})
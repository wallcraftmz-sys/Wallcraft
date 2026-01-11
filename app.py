from flask import Flask, render_template, request, session, redirect, url_for, jsonify
import os
import requests
from functools import wraps

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "wallcraft_secret_key")

# ===== USERS (ВРЕМЕННО БЕЗ БД) =====
USERS = {
    "admin": {"password": "123456", "role": "admin"},
    "user": {"password": "111111", "role": "user"}
}

# ===== AUTH DECORATORS =====
def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if "user" not in session:
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return wrapper

# ===== PRODUCTS =====
products = [
    {
        "id": 1,
        "category": "walls",
        "name_ru": "Жидкие обои — Ocean",
        "name_lv": "Šķidrie tapetes — Ocean",
        "description_ru": "Высококачественные жидкие обои",
        "description_lv": "Augstas kvalitātes tapetes",
        "price": 25.00,
        "image": "images/IMG_0900.jpeg"
    }
]

# ===== ORDERS =====
orders = []

# ===== TELEGRAM =====
def send_telegram(message: str):
    token = os.getenv("TG_BOT_TOKEN")
    chat_id = os.getenv("TG_CHAT_ID")
    if not token or not chat_id:
        return

    requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        json={"chat_id": chat_id, "text": message},
        timeout=10
    )

# ===== LANGUAGE =====
@app.before_request
def set_lang():
    session["lang"] = request.args.get("lang") or session.get("lang") or "ru"

# ===== PAGES =====
@app.route("/")
def index():
    return render_template("index.html", products=products, lang=session["lang"])

@app.route("/catalog")
def catalog():
    return render_template("catalog.html", products=products, lang=session["lang"])

# ===== LOGIN =====
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("login")
        password = request.form.get("password")
        user = USERS.get(username)

        if user and user["password"] == password:
            session["user"] = {"username": username, "role": user["role"]}
            return redirect(url_for("dashboard" if user["role"] == "admin" else "profile"))

        return render_template("login.html", error="Неверный логин", lang=session["lang"])

    return render_template("login.html", lang=session["lang"])

# ===== LOGOUT =====
@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("index"))

# ===== REGISTER =====
@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form.get("login")
        password = request.form.get("password")

        if not username or not password:
            return render_template(
                "register.html",
                error="Заполните все поля",
                lang=session["lang"]
            )

        if username in USERS:
            return render_template(
                "register.html",
                error="Пользователь уже существует",
                lang=session["lang"]
            )

        USERS[username] = {
            "password": password,
            "role": "user"
        }

        session["user"] = {
            "username": username,
            "role": "user"
        }

        return redirect(url_for("profile"))

    return render_template("register.html", lang=session["lang"])
    
# ===== DASHBOARD =====
@app.route("/dashboard")
@admin_required
def dashboard():
    return render_template("dashboard.html", user=session["user"], lang=session["lang"])

# ===== PROFILE =====
@app.route("/profile")
@login_required
def profile():
    if session["user"]["role"] != "user":
        return redirect(url_for("dashboard"))

    username = session["user"]["username"]

    user_orders = [
        o for o in orders
        if o["user"] == username
    ]

    return render_template(
        "profile.html",
        user=session["user"],
        orders=user_orders,
        lang=session["lang"]
    )
# ===== CART =====
@app.route("/cart")
def cart():
    cart = session.get("cart", {})
    items, total = [], 0

    for pid, qty in cart.items():
        pr = next((p for p in products if p["id"] == int(pid)), None)
        if pr:
            items.append({"product": pr, "qty": qty})
            total += pr["price"] * qty

    return render_template("cart.html", cart_items=items, total=total, lang=session["lang"])

# ===== ORDER =====
@app.route("/order", methods=["GET", "POST"])
def order():
    lang = session["lang"]
    success = False
    cart = session.get("cart", {})

    if request.method == "POST" and cart:

        if "user" not in session:
            return redirect(url_for("login"))

        name = request.form["name"]
        contact = request.form["contact"]

        lines = []
        total = 0.0

        for pid, qty in cart.items():
            pr = next((p for p in products if p["id"] == int(pid)), None)
            if pr:
                subtotal = pr["price"] * qty
                total += subtotal
                lines.append(f"{pr['name_ru']} × {qty}")

        orders.append({
            "user": session["user"]["username"],
            "role": session["user"]["role"],
            "name": name,
            "contact": contact,
            "items": lines,
            "total": total
        })

        send_telegram(
            f"🛒 Новый заказ\n"
            f"Пользователь: {session['user']['username']}\n"
            f"Имя: {name}\n"
            f"Контакт: {contact}\n\n"
            f"{chr(10).join(lines)}\n"
            f"Итого: {total:.2f} €"
        )

        session["cart"] = {}
        success = True

    return render_template("order.html", success=success, lang=lang)
    
# ===== ADMIN ORDERS =====
@app.route("/admin/orders")
@admin_required
def admin_orders():
    return render_template("admin_orders.html", orders=orders, lang=session["lang"])

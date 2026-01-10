from flask import Flask, render_template, request, session, redirect, url_for, jsonify
import os
import requests
from functools import wraps

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "wallcraft_secret_key")

# ===== ADMIN =====
ADMIN_LOGIN = "admin"
ADMIN_PASSWORD = "123456"

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
        "image": "images/img_0856.png"
    }
]

# ===== ORDERS STORAGE =====
orders = []

# ===== TELEGRAM =====
def send_telegram(message: str):
    token = os.getenv("TG_BOT_TOKEN")
    chat_id = os.getenv("TG_CHAT_ID")

    if not token or not chat_id:
        print("TG ERROR: env vars not set")
        return

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": message
    }

    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print("TG ERROR:", e)

# ===== AUTH DECORATOR =====
def admin_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not session.get("is_admin"):
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return wrapper

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

@app.route("/product/<int:product_id>")
def product(product_id):
    item = next((p for p in products if p["id"] == product_id), None)
    if not item:
        return redirect(url_for("catalog"))
    return render_template("product.html", product=item, lang=session["lang"])

# ===== LOGIN =====
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        login = request.form.get("login")
        password = request.form.get("password")

        if login == ADMIN_LOGIN and password == ADMIN_PASSWORD:
            session["is_admin"] = True
            return redirect(url_for("dashboard"))

        return render_template(
            "login.html",
            error="Неверный логин или пароль",
            lang=session.get("lang", "ru")
        )

    return render_template("login.html", lang=session.get("lang", "ru"))

@app.route("/logout")
def logout():
    session.pop("is_admin", None)
    return redirect(url_for("index"))

# ===== DASHBOARD =====
@app.route("/dashboard")
@admin_required
def dashboard():
    return render_template("dashboard.html", lang=session["lang"])

# ===== CART API =====
@app.route("/api/add_to_cart/<int:product_id>", methods=["POST"])
def add_to_cart(product_id):
    cart = session.get("cart", {})
    pid = str(product_id)
    cart[pid] = cart.get(pid, 0) + 1
    session["cart"] = cart
    return jsonify(success=True, cart_total_items=sum(cart.values()))

@app.route("/api/update_cart/<int:pid>/<action>", methods=["POST"])
def update_cart(pid, action):
    cart = session.get("cart", {})
    pid = str(pid)

    if pid in cart:
        if action == "plus":
            cart[pid] += 1
        elif action == "minus":
            cart[pid] -= 1
            if cart[pid] <= 0:
                del cart[pid]

    session["cart"] = cart

    total = 0
    subtotal = 0
    qty = cart.get(pid, 0)

    for k, q in cart.items():
        pr = next((p for p in products if p["id"] == int(k)), None)
        if pr:
            total += pr["price"] * q
            if k == pid:
                subtotal = pr["price"] * q

    return jsonify(
        qty=qty,
        subtotal=subtotal,
        total=total,
        cart_total_items=sum(cart.values())
    )

# ===== CART PAGE =====
@app.route("/cart")
def cart():
    cart = session.get("cart", {})
    items = []
    total = 0.0

    for pid, qty in cart.items():
        pr = next((p for p in products if p["id"] == int(pid)), None)
        if pr:
            items.append({"product": pr, "qty": qty})
            total += pr["price"] * qty

    return render_template("cart.html", cart_items=items, total=total, lang=session["lang"])

# ===== ORDER =====
@app.route("/order", methods=["GET", "POST"])
def order():
    lang = session.get("lang", "ru")
    success = False
    cart = session.get("cart", {})

    if request.method == "POST" and cart:
        name = request.form.get("name", "")
        contact = request.form.get("contact", "")

        lines = []
        total = 0.0

        for pid, qty in cart.items():
            pr = next((p for p in products if p["id"] == int(pid)), None)
            if pr:
                subtotal = pr["price"] * qty
                total += subtotal
                lines.append(f"{pr['name_ru']} — {qty} × {pr['price']} €")

        orders.append({
            "name": name,
            "contact": contact,
            "items": lines,
            "total": total
        })

        message = (
            "🛒 НОВЫЙ ЗАКАЗ WALLCRAFT\n\n"
            f"👤 Имя: {name}\n"
            f"📞 Контакт: {contact}\n\n"
            "📦 Заказ:\n"
            + "\n".join(lines)
            + f"\n\n💰 Итого: {total:.2f} €"
        )

        send_telegram(message)
        session["cart"] = {}
        success = True

    return render_template("order.html", success=success, lang=lang)

# ===== ADMIN ORDERS =====
@app.route("/admin/orders")
@admin_required
def admin_orders():
    # пока без базы — просто заглушка
    return render_template(
        "admin_orders.html",
        lang=session.get("lang", "ru")
    )
    

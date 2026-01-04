import os
import threading
import smtplib
from flask import Flask, render_template, request, session, redirect, url_for, jsonify
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from functools import wraps
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "wallcraft_secret_key")

# ================== ТОВАРЫ (только обои) ==================
products = [
    {"id": 1, "category": "walls", "name_ru": "Жидкие обои — Ocean", "description_ru": "Высококачественные жидкие обои для стен", "name_lv": "Šķidrie tapetes — Ocean", "description_lv": "Augstas kvalitātes šķidrie tapetes", "price": 25.00, "image": "images/liquid_wallpaper1.jpg"},
    {"id": 2, "category": "walls", "name_ru": "Жидкие обои — Golden", "description_ru": "Эффектные декоративные жидкие обои", "name_lv": "Šķidrās tapetes — Golden", "description_lv": "Dekoratīvas šķidrās tapetes", "price": 30.00, "image": "images/liquid_wallpaper2.jpg"},
    {"id": 3, "category": "walls", "name_ru": "Жидкие обои — Modern", "description_ru": "Современный стиль для интерьера", "name_lv": "Šķidrās tapetes — Modern", "description_lv": "Mūsdienīgs interjera stils", "price": 28.00, "image": "images/liquid_wallpaper3.jpg"}
]

# ================== ЯЗЫК ==================
@app.before_request
def set_lang():
    session["lang"] = request.args.get("lang") or session.get("lang") or "ru"

# ================== ДЕКОРАТОР РОЛИ ==================
def role_required(role):
    def wrapper(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            if session.get("role") != role:
                return "Доступ запрещён", 403
            return f(*args, **kwargs)
        return decorated
    return wrapper

# ================== ГЛАВНАЯ ==================
@app.route("/")
def index():
    lang = session.get("lang", "ru")
    return render_template("index.html", lang=lang, products=products, cart_total_items=sum(session.get("cart", {}).values()))

# ================== КАТАЛОГ ==================
@app.route("/catalog")
def catalog():
    lang = session.get("lang", "ru")
    return render_template("catalog.html", products=products, lang=lang, cart_total_items=sum(session.get("cart", {}).values()))

# ================== API: добавление в корзину ==================
@app.route("/api/add_to_cart/<int:product_id>", methods=["POST"])
def api_add_to_cart(product_id):
    cart = session.get("cart", {})
    pid = str(product_id)
    cart[pid] = cart.get(pid, 0) + 1
    session["cart"] = cart

    product = next((p for p in products if p["id"] == product_id), None)
    if not product:
        return jsonify({"success": False, "error": "Product not found"}), 404

    cart_total_items = sum(cart.values())
    return jsonify({
        "success": True,
        "product": {
            "id": product["id"],
            "name_ru": product["name_ru"],
            "name_lv": product["name_lv"],
            "price": product["price"],
            "image": product["image"],
            "qty": cart[pid]
        },
        "cart_total_items": cart_total_items
    })

# ================== API: обновление корзины ==================
@app.route("/api/update_cart/<int:product_id>/<action>", methods=["POST"])
def api_update_cart(product_id, action):
    cart = session.get("cart", {})
    pid = str(product_id)

    if pid not in cart:
        return jsonify({"success": False, "qty": 0, "total": 0, "cart_total_items": 0})

    if action == "plus":
        cart[pid] += 1
    elif action == "minus":
        cart[pid] -= 1
        if cart[pid] <= 0:
            del cart[pid]

    session["cart"] = cart

    total = 0
    total_items = 0
    for k, q in cart.items():
        product = next((p for p in products if p["id"] == int(k)), None)
        if product:
            total += product["price"] * q
            total_items += q

    return jsonify({
        "success": True,
        "qty": cart.get(pid, 0),
        "total": total,
        "cart_total_items": total_items
    })

# ================== API: счетчик корзины ==================
@app.route("/api/cart_count")
def api_cart_count():
    cart = session.get("cart", {})
    return jsonify({"count": sum(cart.values())})

# ================== КОРЗИНА ==================
@app.route("/cart")
def cart_page():
    lang = session.get("lang", "ru")
    cart = session.get("cart", {})
    cart_items = []
    total = 0
    for pid, qty in cart.items():
        product = next((p for p in products if p["id"] == int(pid)), None)
        if product:
            cart_items.append({"product": product, "qty": qty})
            total += product["price"] * qty
    return render_template("cart.html", cart_items=cart_items, total=total, lang=lang)

# ================== ЗАКАЗ ==================
@app.route("/order", methods=["GET", "POST"])
def order():
    lang = session.get("lang", "ru")
    success = False
    if request.method == "POST":
        name = request.form.get("name")
        contact = request.form.get("contact")
        session["cart"] = {}
        success = True
        threading.Thread(target=send_email, args=(name, contact)).start()
    return render_template("order.html", success=success, lang=lang)

def send_email(name, contact):
    sender = os.environ.get("WALLCRAFT_EMAIL")
    password = os.environ.get("WALLCRAFT_APP_PASSWORD")
    if not sender or not password:
        print("Env-переменные почты не заданы")
        return
    msg = MIMEMultipart()
    msg["From"] = sender
    msg["To"] = sender
    msg["Subject"] = "Новая заявка"
    msg.attach(MIMEText(f"Имя: {name}\nКонтакт: {contact}", "plain"))
    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(sender, password)
            server.sendmail(sender, sender, msg.as_string())
            print("Письмо отправлено")
    except Exception as e:
        print("Ошибка отправки письма:", e)

# ================== АДМИН ==================
ADMIN_LOGIN = os.environ.get("ADMIN_LOGIN", "admin")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "wallcraft123")

@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        login = request.form.get("login")
        password = request.form.get("password")
        if login == ADMIN_LOGIN and password == ADMIN_PASSWORD:
            session["role"] = "admin"
            session["username"] = login
            return redirect("/admin")
        return render_template("admin_login.html", error="Неверный логин или пароль")
    return render_template("admin_login.html")

@app.route("/admin/logout")
def admin_logout():
    session.pop("role", None)
    session.pop("username", None)
    return redirect("/admin/login")

@app.route("/admin")
@role_required("admin")
def admin_panel():
    return render_template("admin.html")

# ================== ЗАПУСК ==================
if __name__ == "__main__":
    app.run(debug=True)

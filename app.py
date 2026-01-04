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

# ================== ТОВАРЫ ==================
products = [
    {
        "id": 1,
        "category": "walls",
        "name_ru": "Жидкие обои — Ocean",
        "description_ru": "Высококачественные жидкие обои для стен",
        "name_lv": "Šķidrie tapetes — Ocean",
        "description_lv": "Augstas kvalitātes šķidrie tapetes",
        "price": 25.00,
        "image": "images/liquid_wallpaper1.jpg"
    },
    {
        "id": 2,
        "category": "walls",
        "name_ru": "Жидкие обои — Golden",
        "description_ru": "Эффектные декоративные жидкие обои",
        "name_lv": "Šķidrās tapetes — Golden",
        "description_lv": "Dekoratīvas šķidrās tapetes",
        "price": 30.00,
        "image": "images/liquid_wallpaper2.jpg"
    },
    {
        "id": 3,
        "category": "walls",
        "name_ru": "Жидкие обои — Modern",
        "description_ru": "Современный стиль для интерьера",
        "name_lv": "Šķidrās tapetes — Modern",
        "description_lv": "Mūsdienīgs interjera stils",
        "price": 28.00,
        "image": "images/liquid_wallpaper3.jpg"
    }
]

# ================== ЯЗЫК ==================
@app.before_request
def set_lang():
    session["lang"] = request.args.get("lang") or session.get("lang") or "ru"

# ================== ГЛАВНАЯ ==================
@app.route("/")
def index():
    lang = session.get("lang")
    return render_template("index.html", products=products, lang=lang)

@app.route('/product/<int:id>')
def product(id):
    lang = session.get('lang')
    product_item = next((p for p in products if p['id'] == id), None)
    if not product_item:
        # можно вернуть 404 или редирект на каталог
        return redirect(url_for('catalog'))
    return render_template('product.html', lang=lang, product=product_item)

# ================== КАТАЛОГ ==================
@app.route("/catalog")
def catalog():
    lang = session.get("lang")
    cat = request.args.get("cat")
    min_price = request.args.get("min_price")
    max_price = request.args.get("max_price")

    filtered = products
    if cat:
        filtered = [p for p in filtered if p["category"] == cat]
    if min_price:
        try:
            filtered = [p for p in filtered if p["price"] >= float(min_price)]
        except:
            pass
    if max_price:
        try:
            filtered = [p for p in filtered if p["price"] <= float(max_price)]
        except:
            pass

    return render_template("catalog.html", products=filtered, lang=lang)

# ================== API: ДОБАВИТЬ В КОРЗИНУ ==================
@app.route("/api/add_to_cart/<int:product_id>", methods=["POST"])
def api_add_to_cart(product_id):
    cart = session.get("cart", {})
    cart[str(product_id)] = cart.get(str(product_id), 0) + 1
    session["cart"] = cart

    product = next((p for p in products if p["id"] == product_id), None)
    if not product:
        return jsonify({"success": False}), 404

    return jsonify({
        "success": True,
        "product": {
            "id": product["id"],
            "name_ru": product["name_ru"],
            "image": product["image"],
            "price": product["price"],
            "qty": cart[str(product_id)]
        },
        "cart_total_items": sum(cart.values())
    })

# ================== API: ОБНОВИТЬ КОЛ-ВО В КОРЗИНЕ ==================
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

# ================== КОРЗИНА ==================
@app.route("/cart")
def cart_page():
    cart = session.get("cart", {})
    cart_items = []
    total = 0
    for pid, qty in cart.items():
        product = next((p for p in products if p["id"] == int(pid)), None)
        if product:
            cart_items.append({"product": product, "qty": qty})
            total += product["price"] * qty
    return render_template("cart.html", cart_items=cart_items, total=total, lang=session.get('lang', 'ru'))

# ================== ЗАКАЗ ==================@app.route("/order", methods=["GET", "POST"])
def order():
    lang = session.get("lang", "ru")

    if request.method == "POST":
        name = request.form.get("name")
        contact = request.form.get("contact")
        threading.Thread(target=send_email, args=(name, contact)).start()
        return render_template("order.html", success=True, lang=lang)

    return render_template("order.html", lang=lang)

def send_email(name, contact):
    sender = os.environ.get("WALLCRAFT_EMAIL")
    password = os.environ.get("WALLCRAFT_APP_PASSWORD")
    if not sender or not password:
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
    except Exception as e:
        print("Ошибка отправки письма:", e)

# ================== АДМИН ==================
ADMIN_LOGIN = os.environ.get("ADMIN_LOGIN", "admin")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "wallcraft123")

def admin_required(f):
    @wraps(f)
    def wrapped(*args, **kwargs):
        if session.get("is_admin"):
            return f(*args, **kwargs)
        return redirect(url_for("admin_login"))
    return wrapped

@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        login = request.form.get("login")
        password = request.form.get("password")
        if login == ADMIN_LOGIN and password == ADMIN_PASSWORD:
            session["is_admin"] = True
            return redirect("/admin")
        return render_template("admin_login.html", error="Неверный логин или пароль")
    return render_template("admin_login.html")

@app.route("/admin/logout")
def admin_logout():
    session.pop("is_admin", None)
    return redirect("/admin/login")

@app.route("/admin")
@admin_required
def admin_panel():
    conn = sqlite3.connect("orders.db")
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM orders")
    orders = cursor.fetchall()
    conn.close()
    return render_template("admin.html", orders=orders)

# ================== ЗАПУСК ==================
if __name__ == "__main__":
    app.run(debug=True)

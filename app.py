import os
from flask import Flask, render_template, request, session, redirect, url_for, jsonify
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
        "name_lv": "Šķidrās tapetes — Ocean",
        "description_ru": "Высококачественные жидкие обои для стен",
        "description_lv": "Augstas kvalitātes šķidrās tapetes sienām",
        "price": 25.00,
        "image": "https://cdn.pixabay.com/photo/2016/11/29/06/16/texture-1868576_1280.jpg"
    },
    {
        "id": 2,
        "category": "walls",
        "name_ru": "Жидкие обои — Golden",
        "name_lv": "Šķidrās tapetes — Golden",
        "description_ru": "Эффектные декоративные жидкие обои",
        "description_lv": "Dekoratīvas šķidrās tapetes",
        "price": 30.00,
        "image": "https://cdn.pixabay.com/photo/2018/10/18/18/38/wall-3759044_1280.jpg"
    },
    {
        "id": 3,
        "category": "walls",
        "name_ru": "Жидкие обои — Modern",
        "name_lv": "Šķidrās tapetes — Modern",
        "description_ru": "Современный стиль для интерьера",
        "description_lv": "Mūsdienīgs interjera stils",
        "price": 28.00,
        "image": "https://cdn.pixabay.com/photo/2017/08/07/12/50/wall-2608854_1280.jpg"
    }
]

# ================== ЯЗЫК ==================
@app.before_request
def set_lang():
    session["lang"] = request.args.get("lang") or session.get("lang") or "ru"

# ================== ГЛАВНАЯ ==================
@app.route("/")
def index():
    lang = session.get("lang", "ru")
    cart_total_items = sum(session.get("cart", {}).values())
    return render_template("index.html", lang=lang, products=products, cart_total_items=cart_total_items)

# ================== КАТАЛОГ ==================
@app.route("/catalog")
def catalog():
    lang = session.get("lang", "ru")
    cart_total_items = sum(session.get("cart", {}).values())
    # Показываем только категорию "walls"
    walls_products = [p for p in products if p["category"] == "walls"]
    return render_template("catalog.html", products=walls_products, lang=lang, cart_total_items=cart_total_items)

# ================== API: добавить в корзину ==================
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

# ================== API: обновить корзину ==================
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

# ================== API: количество товаров в корзине ==================
@app.route("/api/cart_count")
def api_cart_count():
    cart = session.get("cart", {})
    total_items = sum(cart.values())
    return jsonify({"count": total_items})

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

    return render_template("cart.html", cart_items=cart_items, total=total, lang=lang, cart_total_items=sum(cart.values()))

# ================== ЗАКАЗ ==================
@app.route("/order", methods=["GET", "POST"])
def order():
    lang = session.get("lang", "ru")
    success = False
    if request.method == "POST":
        name = request.form.get("name")
        contact = request.form.get("contact")
        success = True
        session["cart"] = {}
    return render_template("order.html", success=success, lang=lang)

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
    return render_template("admin.html")

# ================== ЗАПУСК ==================
if __name__ == "__main__":
    app.run(debug=True)

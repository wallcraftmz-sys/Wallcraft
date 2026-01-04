import os
from flask import Flask, render_template, request, session, redirect, url_for, jsonify
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "wallcraft_secret_key")

# ================== PRODUCTS ==================
products = [
    {
        "id": 1,
        "category": "walls",
        "name_ru": "Жидкие обои — Ocean",
        "name_lv": "Šķidrās tapetes — Ocean",
        "description_ru": "Высококачественные жидкие обои для стен",
        "description_lv": "Augstas kvalitātes šķidrās tapetes sienām",
        "price": 25.00,
        "image": "images/IMG_0856.PNG"  # положи файл в static/images/
    },
    {
        "id": 2,
        "category": "walls",
        "name_ru": "Жидкие обои — Golden",
        "name_lv": "Šķidrās tapetes — Golden",
        "description_ru": "Эффектные декоративные жидкие обои",
        "description_lv": "Dekoratīvas šķidrās tapetes",
        "price": 30.00,
        "image": "images/IMG_0856.PNG"  # можно повторить пока тест
    }
]

# ================== LANGUAGE ==================
@app.before_request
def set_lang():
    session["lang"] = request.args.get("lang") or session.get("lang") or "ru"

# ================== PAGES ==================
@app.route("/")
def index():
    return render_template("index.html", products=products, lang=session["lang"])

@app.route("/catalog")
def catalog():
    return render_template("catalog.html", products=products, lang=session["lang"])

@app.route("/cart")
def cart_page():
    cart = session.get("cart", {})
    items = []
    total = 0
    for pid, qty in cart.items():
        p = next(p for p in products if p["id"] == int(pid))
        items.append({"product": p, "qty": qty})
        total += p["price"] * qty
    return render_template("cart.html", cart_items=items, total=total, lang=session["lang"])

@app.route("/order", methods=["GET","POST"])
def order():
    cart = session.get("cart", {})
    if not cart:
        return redirect(url_for("catalog"))

    items = []
    total = 0
    for pid, qty in cart.items():
        p = next(p for p in products if p["id"] == int(pid))
        items.append({"product": p, "qty": qty})
        total += p["price"] * qty

    success = False
    if request.method == "POST":
        name = request.form.get("name")
        contact = request.form.get("contact")
        # Здесь можно добавить обработку заказа (email, запись в базу)
        success = True
        session["cart"] = {}  # Очистка корзины после заказа

    return render_template("order.html", cart_items=items, total=total, success=success, lang=session["lang"])

# ================== API ==================
@app.route("/api/add_to_cart/<int:pid>", methods=["POST"])
def add_to_cart(pid):
    cart = session.get("cart", {})
    cart[str(pid)] = cart.get(str(pid), 0) + 1
    session["cart"] = cart
    product = next(p for p in products if p["id"] == pid)
    return jsonify(success=True, product=product, qty=cart[str(pid)], cart_total_items=sum(cart.values()))

@app.route("/api/update_cart/<int:pid>/<action>", methods=["POST"])
def update_cart(pid, action):
    cart = session.get("cart", {})
    pid = str(pid)
    if pid not in cart:
        return jsonify(success=False)
    if action=="plus":
        cart[pid] += 1
    else:
        cart[pid] -= 1
        if cart[pid] <= 0:
            del cart[pid]
    session["cart"] = cart
    total = 0
    for k,q in cart.items():
        p = next(p for p in products if p["id"] == int(k))
        total += p["price"]*q
    return jsonify(success=True, qty=cart.get(pid,0), total=total, cart_total_items=sum(cart.values()))

if __name__ == "__main__":
    app.run(debug=True)

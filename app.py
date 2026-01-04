import os
from flask import Flask, render_template, session, request, jsonify, redirect, url_for

app = Flask(__name__)
app.secret_key = "wallcraft_secret"

# === ДАННЫЕ ===
products = [
    {
        "id": 1,
        "name_ru": "Жидкие обои Wallcraft",
        "name_lv": "Šķidrās tapetes Wallcraft",
        "price": 25.00,
        "image": "images/IMG_0856.PNG"
    }
]

# === ГЛАВНАЯ ===
@app.route("/")
def index():
    return render_template("index.html", products=products)

# === КАТАЛОГ ===
@app.route("/catalog")
def catalog():
    return render_template("catalog.html", products=products)

# === API: ДОБАВИТЬ В КОРЗИНУ ===
@app.route("/api/add_to_cart/<int:pid>", methods=["POST"])
def add_to_cart(pid):
    cart = session.get("cart", {})
    cart[str(pid)] = cart.get(str(pid), 0) + 1
    session["cart"] = cart
    return jsonify({
        "success": True,
        "count": sum(cart.values())
    })

# === КОРЗИНА ===
@app.route("/cart")
def cart():
    cart = session.get("cart", {})
    items = []
    total = 0

    for pid, qty in cart.items():
        product = next((p for p in products if p["id"] == int(pid)), None)
        if product:
            items.append({"product": product, "qty": qty})
            total += product["price"] * qty

    return render_template("cart.html", items=items, total=total)

# === ОБНОВЛЕНИЕ КОЛИЧЕСТВА ===
@app.route("/api/update/<int:pid>/<action>", methods=["POST"])
def update(pid, action):
    cart = session.get("cart", {})
    if str(pid) in cart:
        if action == "plus":
            cart[str(pid)] += 1
        elif action == "minus":
            cart[str(pid)] -= 1
            if cart[str(pid)] <= 0:
                del cart[str(pid)]
    session["cart"] = cart
    return jsonify(success=True)

# === ОФОРМЛЕНИЕ ЗАКАЗА ===
@app.route("/order", methods=["GET", "POST"])
def order():
    if request.method == "POST":
        session["cart"] = {}
        return render_template("order.html", success=True)
    return render_template("order.html", success=False)

# === АДМИН ЛОГИН ===
@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        if request.form.get("login") == "admin" and request.form.get("password") == "1234":
            session["admin"] = True
            return redirect(url_for("index"))
    return render_template("admin_login.html")

# === ЗАПУСК ===
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))

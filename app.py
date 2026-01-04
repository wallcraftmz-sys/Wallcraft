import os
from flask import Flask, render_template, request, session, jsonify, redirect, url_for

app = Flask(__name__)
app.secret_key = "wallcraft_secret_key"

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
        "description_ru": "Декоративные жидкие обои",
        "description_lv": "Dekoratīvas šķidrās tapetes",
        "price": 30.00,
        "image": "https://cdn.pixabay.com/photo/2018/10/18/18/38/wall-3759044_1280.jpg"
    },
    {
        "id": 3,
        "category": "walls",
        "name_ru": "Жидкие обои — Modern",
        "name_lv": "Šķidrās tapetes — Modern",
        "description_ru": "Современный интерьер",
        "description_lv": "Mūsdienīgs interjers",
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
    return render_template(
        "index.html",
        products=products,
        lang=session["lang"],
        cart_total_items=sum(session.get("cart", {}).values())
    )

# ================== КАТАЛОГ ==================
@app.route("/catalog")
def catalog():
    return render_template(
        "catalog.html",
        products=products,
        lang=session["lang"],
        cart_total_items=sum(session.get("cart", {}).values())
    )

# ================== API: В КОРЗИНУ ==================
@app.route("/api/add_to_cart/<int:pid>", methods=["POST"])
def add_to_cart(pid):
    cart = session.get("cart", {})
    cart[str(pid)] = cart.get(str(pid), 0) + 1
    session["cart"] = cart

    product = next(p for p in products if p["id"] == pid)

    return jsonify({
        "success": True,
        "qty": cart[str(pid)],
        "name": product[f"name_{session['lang']}"]
    })

# ================== API: ИЗМЕНИТЬ КОЛ-ВО ==================
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
    for k, q in cart.items():
        product = next(p for p in products if p["id"] == int(k))
        total += product["price"] * q

    return jsonify({
        "success": True,
        "qty": cart.get(pid, 0),
        "total": total
    })

# ================== КОРЗИНА ==================
@app.route("/cart")
def cart():
    cart = session.get("cart", {})
    items = []
    total = 0

    for k, q in cart.items():
        product = next(p for p in products if p["id"] == int(k))
        items.append({"product": product, "qty": q})
        total += product["price"] * q

    return render_template("cart.html", cart_items=items, total=total, lang=session["lang"])

if __name__ == "__main__":
    app.run(debug=True)

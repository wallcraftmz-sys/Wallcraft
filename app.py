import os
from flask import Flask, render_template, request, session, redirect, url_for, jsonify

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "wallcraft_secret_key")

products = [
    {"id":1,"category":"walls","name_ru":"Жидкие обои — Ocean","description_ru":"Высококачественные жидкие обои для стен","name_lv":"Šķidrie tapetes — Ocean","description_lv":"Augstas kvalitātes šķidrie tapetes","price":25.00,"image":"images/liquid_wallpaper1.jpg"},
    {"id":2,"category":"walls","name_ru":"Жидкие обои — Golden","description_ru":"Эффектные декоративные жидкие обои","name_lv":"Šķidrās tapetes — Golden","description_lv":"Dekoratīvas šķidrās tapetes","price":30.00,"image":"images/liquid_wallpaper2.jpg"},
    {"id":3,"category":"walls","name_ru":"Жидкие обои — Modern","description_ru":"Современный стиль для интерьера","name_lv":"Šķidrās tapetes — Modern","description_lv":"Mūsdienīgs interjera stils","price":28.00,"image":"images/liquid_wallpaper3.jpg"}
]

# ---------------- ЯЗЫК ----------------
@app.before_request
def set_lang():
    session["lang"] = request.args.get("lang") or session.get("lang") or "ru"

# ---------------- КАТАЛОГ ----------------
@app.route("/catalog")
def catalog():
    lang = request.args.get("lang", session.get("lang", "ru"))
    session["lang"] = lang

    cart = session.get("cart", {})
    cart_total_items = sum(cart.values())

    # Фильтруем только обои
    wall_products = [p for p in products if p["category"] == "walls"]

    return render_template(
        "catalog.html",
        products=wall_products,
        lang=lang,
        cart_total_items=cart_total_items
    )

# ---------------- API: добавить в корзину ----------------
@app.route("/api/add_to_cart/<int:product_id>", methods=["POST"])
def api_add_to_cart(product_id):
    cart = session.get("cart", {})
    pid = str(product_id)
    cart[pid] = cart.get(pid, 0) + 1
    session["cart"] = cart

    product = next((p for p in products if p["id"] == product_id), None)
    if not product:
        return jsonify({"success": False, "error": "Product not found"}), 404

    total_items = sum(cart.values())
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
        "cart_total_items": total_items
    })

# ---------------- API: обновить количество ----------------
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
    total = sum(next((p["price"]*q for p in products if p["id"]==int(k)),0) for k,q in cart.items())
    total_items = sum(cart.values())
    return jsonify({"success": True, "qty": cart.get(pid,0), "total": total, "cart_total_items": total_items})

# ---------------- API: счетчик ----------------
@app.route("/api/cart_count")
def api_cart_count():
    total_items = sum(session.get("cart", {}).values())
    return jsonify({"count": total_items})

# ---------------- КОРЗИНА ----------------
@app.route("/cart")
def cart_page():
    lang = session.get("lang", "ru")
    cart = session.get("cart", {})
    cart_items = []
    total = 0
    for pid, qty in cart.items():
        product = next((p for p in products if p["id"]==int(pid)), None)
        if product:
            cart_items.append({"product": product, "qty": qty})
            total += product["price"]*qty
    return render_template("cart.html", cart_items=cart_items, total=total, lang=lang)

# ---------------- ЗАКАЗ ----------------
@app.route("/order", methods=["GET","POST"])
def order():
    lang = session.get("lang","ru")
    success = False
    if request.method == "POST":
        name = request.form.get("name")
        contact = request.form.get("contact")
        success = True
        session["cart"] = {}
    return render_template("order.html", success=success, lang=lang)

# ---------------- ГЛАВНАЯ ----------------
@app.route("/")
def index():
    lang = session.get("lang","ru")
    return render_template("index.html", lang=lang)

if __name__=="__main__":
    app.run(debug=True)

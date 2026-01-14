from werkzeug.middleware.proxy_fix import ProxyFix
from flask import Flask, render_template, request, session, redirect, url_for, jsonify
import os
from datetime import timedelta

from flask_sqlalchemy import SQLAlchemy
from flask_login import (
    LoginManager,
    UserMixin,
    login_user,
    logout_user,
    current_user,
    login_required
)
from werkzeug.security import generate_password_hash, check_password_hash

# ======================
# APP CONFIG
# ======================
app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "wallcraft_super_secret_key")

# ВАЖНО: для Railway / HTTPS / Proxy
app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)

# ⚠️ НЕ ВКЛЮЧАЕМ Secure, пока нет своего домена
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    REMEMBER_COOKIE_HTTPONLY=True,
    REMEMBER_COOKIE_SAMESITE="Lax",
)

app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///wallcraft.db"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.permanent_session_lifetime = timedelta(days=7)
app.config["REMEMBER_COOKIE_DURATION"] = timedelta(days=7)

# ======================
# DB + LOGIN MANAGER
# ======================
db = SQLAlchemy(app)

login_manager = LoginManager()
login_manager.login_view = "login"
login_manager.init_app(app)

@login_manager.unauthorized_handler
def unauthorized():
    return redirect(url_for("login", lang=session.get("lang", "ru")))

# ======================
# MODELS
# ======================
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)
    role = db.Column(db.String(20), default="user")


class Order(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)

    name = db.Column(db.String(100))
    contact = db.Column(db.String(100))
    items = db.Column(db.Text)
    total = db.Column(db.Float)

# ======================
# USER LOADER (СТРОГО ЗДЕСЬ)
# ======================
@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# ======================
# INIT DB (1 РАЗ)
# ======================
with app.app_context():
    db.create_all()

# ======================
# LANGUAGE
# ======================
@app.before_request
def set_lang():
    session["lang"] = request.args.get("lang") or session.get("lang") or "ru"

# ======================
# PRODUCTS (TEMP)
# ======================
products = [
    {
        "id": 1,
        "name_ru": "Жидкие обои — Ocean",
        "name_lv": "Šķidrie tapetes — Ocean",
        "price": 25.00,
        "image": "images/IMG_0900.jpeg"
    }
]

# ======================
# ROUTES
# ======================
@app.route("/")
def index():
    return render_template("index.html", lang=session["lang"])


@app.route("/catalog")
def catalog():
    return render_template("catalog.html", products=products, lang=session["lang"])


# ===== LOGIN =====
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("login")
        password = request.form.get("password")

        user = User.query.filter_by(username=username).first()

        if user and check_password_hash(user.password, password):
            login_user(user, remember=True)
            return redirect(url_for("profile"))

        return render_template(
            "login.html",
            error="Неверный логин или пароль",
            lang=session["lang"]
        )

    return render_template("login.html", lang=session["lang"])


# ===== LOGOUT =====
@app.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("index"))


# ===== REGISTER =====
@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form.get("login")
        password = request.form.get("password")

        if User.query.filter_by(username=username).first():
            return render_template(
                "register.html",
                error="Пользователь уже существует",
                lang=session["lang"]
            )

        user = User(
            username=username,
            password=generate_password_hash(password),
            role="user"
        )

        db.session.add(user)
        db.session.commit()

        login_user(user, remember=True)
        return redirect(url_for("profile"))

    return render_template("register.html", lang=session["lang"])


# ===== PROFILE =====
@app.route("/profile")
@login_required
def profile():
    return render_template(
        "profile.html",
        user=current_user,
        lang=session["lang"]
    )

# ======================
# ADD TO CART
# ======================
@app.route("/api/add_to_cart/<int:product_id>", methods=["POST"])
def add_to_cart(product_id):
    cart = session.get("cart", {})
    pid = str(product_id)

    cart[pid] = cart.get(pid, 0) + 1
    session["cart"] = cart
    session.modified = True  # 🔥 ОБЯЗАТЕЛЬНО

    return jsonify(
        success=True,
        cart_total_items=sum(cart.values())
    )


# ======================
# CART PAGE
# ======================
@app.route("/cart")
def cart():
    cart = session.get("cart", {})
    cart_items = []
    total = 0.0

    for pid, qty in cart.items():
        product = next((p for p in products if p["id"] == int(pid)), None)
        if product:
            subtotal = product["price"] * qty
            total += subtotal
            cart_items.append({
                "product": product,
                "qty": qty,
                "subtotal": subtotal
            })

    return render_template(
        "cart.html",
        cart_items=cart_items,   # ⚠️ ВАЖНО: cart_items
        total=total,
        lang=session.get("lang", "ru")
    )


# ======================
# UPDATE CART
# ======================
@app.route("/api/update_cart/<int:product_id>/<action>", methods=["POST"])
def update_cart(product_id, action):
    cart = session.get("cart", {})
    pid = str(product_id)

    if pid not in cart:
        return jsonify(success=False)

    if action == "plus":
        cart[pid] += 1
    elif action == "minus":
        cart[pid] -= 1
        if cart[pid] <= 0:
            del cart[pid]

    session["cart"] = cart
    session.modified = True

    qty = cart.get(pid, 0)

    product = next((p for p in products if p["id"] == product_id), None)
    subtotal = (product["price"] * qty) if product else 0

    total = sum(
        next(p["price"] for p in products if p["id"] == int(k)) * v
        for k, v in cart.items()
    )

    return jsonify(
        success=True,
        qty=qty,
        subtotal=subtotal,
        total=total,
        cart_total_items=sum(cart.values())
    )

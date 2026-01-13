from flask import Flask, render_template, request, session, redirect, url_for, jsonify
import os
import requests
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

app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///wallcraft.db"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.permanent_session_lifetime = timedelta(days=7)

Session(app)
db = SQLAlchemy(app)

# ======================
# LOGIN MANAGER
# ======================
@login_manager.unauthorized_handler
def unauthorized():
    return redirect(url_for("login", lang=session.get("lang", "ru")))
login_manager = LoginManager(app)
login_manager.login_view = "login"

# ======================
# MODELS
# ======================
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)
    role = db.Column(db.String(20), default="user")

    orders = db.relationship("Order", backref="user", lazy=True)
    
    @login_manager.user_loader
       def load_user(user_id):
    return User.query.get(int(user_id))
    
class Order(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)

    name = db.Column(db.String(100))
    contact = db.Column(db.String(100))
    items = db.Column(db.Text)
    total = db.Column(db.Float)

    created_at = db.Column(db.DateTime, server_default=db.func.now())

# ======================
# DB INIT (ОДИН РАЗ!)
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
# PRODUCTS (ПОКА В ПАМЯТИ)
# ======================
products = [
    {
        "id": 1,
        "name_ru": "Жидкие обои — Ocean",
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
            return redirect(url_for("dashboard" if user.role == "admin" else "profile"))

        return render_template("login.html", error="Неверный логин", lang=session["lang"])

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
            return render_template("register.html", error="Пользователь существует", lang=session["lang"])

        user = User(
            username=username,
            password=generate_password_hash(password),
            role="user"
        )

        db.session.add(user)
        db.session.commit()

        login_user(user)
        return redirect(url_for("profile"))

    return render_template("register.html", lang=session["lang"])


# ===== PROFILE =====
@app.route("/profile")
@login_required
def profile():
    if current_user.role != "user":
        return redirect(url_for("dashboard"))

    orders = Order.query.filter_by(user_id=current_user.id).all()

    return render_template(
        "profile.html",
        user=current_user,
        orders=orders,
        lang=session["lang"]
    )


# ===== DASHBOARD =====
@app.route("/dashboard")
@login_required
def dashboard():
    if current_user.role != "admin":
        return redirect(url_for("profile"))

    orders = Order.query.all()
    return render_template("dashboard.html", orders=orders, lang=session["lang"])


# ===== CART API =====
@app.route("/api/add_to_cart/<int:product_id>", methods=["POST"])
def add_to_cart(product_id):
    cart = session.get("cart", {})
    pid = str(product_id)
    cart[pid] = cart.get(pid, 0) + 1
    session["cart"] = cart
    return jsonify(success=True, cart_total_items=sum(cart.values()))

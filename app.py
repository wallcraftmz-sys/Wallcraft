from werkzeug.middleware.proxy_fix import ProxyFix
from flask import Flask, render_template, request, session, redirect, url_for, jsonify
import os
import requests
from datetime import timedelta
from datetime import datetime

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
from functools import wraps
import os
from werkzeug.utils import secure_filename

# ======================
# ADMIN ACCESS CONTROL
# ======================
def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated:
            return redirect(url_for("login"))

        if getattr(current_user, "role", None) != "admin":
            return redirect(url_for("profile"))

        return f(*args, **kwargs)
    return decorated
    
# ======================
# TELEGRAM
# ======================
def send_telegram(message: str):
    token = os.getenv("TG_BOT_TOKEN")
    chat_id = os.getenv("TG_CHAT_ID")

    if not token or not chat_id:
        print("❌ Telegram ENV vars not set")
        return

    try:
        requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={
                "chat_id": chat_id,
                "text": message
            },
            timeout=10
        )
    except Exception as e:
        print("❌ TG ERROR:", e)

# ======================
# APP CONFIG
# ======================
app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "wallcraft_super_secret_key")
UPLOAD_FOLDER = "static/uploads"
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "webp"}

app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS

# Railway / ProxyFix
app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)

# Cookies
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    REMEMBER_COOKIE_HTTPONLY=True,
    REMEMBER_COOKIE_SAMESITE="Lax",
)

# 🔥 DATABASE (КРИТИЧНО)
DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL is not set")

if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

app.config["SQLALCHEMY_DATABASE_URI"] = DATABASE_URL
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

# Sessions
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
    role = db.Column(db.String(20), default="admin")

class Order(db.Model):
    id = db.Column(db.Integer, primary_key=True)

    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    user = db.relationship("User", backref="orders")

    name = db.Column(db.String(100), nullable=False)
    contact = db.Column(db.String(100), nullable=False)

    items = db.Column(db.Text, nullable=False)
    total = db.Column(db.Float, nullable=False)

    status = db.Column(
        db.String(30),
        default="new"
    )

    created_at = db.Column(
        db.DateTime,
        default=datetime.utcnow
    )
    
class Product(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name_ru = db.Column(db.String(200), nullable=False)
    name_lv = db.Column(db.String(200), nullable=False)
    price = db.Column(db.Float, nullable=False)
    image = db.Column(db.String(200))

    is_active = db.Column(db.Boolean, default=True)
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

    # 🔧 AUTO-MIGRATION: add is_active if missing
    from sqlalchemy import text

    try:
        db.session.execute(text("ALTER TABLE product ADD COLUMN is_active BOOLEAN DEFAULT TRUE"))
        db.session.commit()
        print("✅ is_active column added")
    except Exception as e:
        db.session.rollback()
        print("ℹ️ is_active column already exists")


ORDER_STATUSES = {
    "new": {
        "ru": "Новый",
        "lv": "Jauns",
        "en": "New"
    },
    "confirmed": {
        "ru": "Подтверждён",
        "lv": "Apstiprināts",
        "en": "Confirmed"
    },
    "in_progress": {
        "ru": "В работе",
        "lv": "Procesā",
        "en": "In progress"
    },
    "shipped": {
        "ru": "Отправлен",
        "lv": "Nosūtīts",
        "en": "Shipped"
    },
    "completed": {
        "ru": "Завершён",
        "lv": "Pabeigts",
        "en": "Completed"
    },
    "cancelled": {
        "ru": "Отменён",
        "lv": "Atcelts",
        "en": "Cancelled"
    }
}

# ======================
# LANGUAGE
# ======================
@app.before_request
def set_lang():
    if "lang" in request.args:
        session["lang"] = request.args.get("lang")

    if session.get("lang") not in ["ru", "lv", "en"]:
        session["lang"] = "ru"


@app.context_processor
def inject_lang():
    return dict(lang=session.get("lang", "ru"))

# ======================
# SECURITY: BLOCK EMPTY CHECKOUT
# ======================
@app.before_request
def block_empty_checkout():
    if request.endpoint == "checkout":
        cart = session.get("cart", {})
        if not cart or sum(cart.values()) == 0:
            return redirect(url_for("cart"))
            
# ======================
# ROUTES
# ======================
@app.route("/")
def index():
    return render_template("index.html", lang=session["lang"])

#==== catalog =====
@app.route("/catalog")
def catalog():
    products = Product.query.filter_by(is_active=True).all()
    return render_template(
        "catalog.html",
        products=products,
        lang=session["lang"]
    )


# ===== LOGIN =====
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")

        user = User.query.filter_by(username=username).first()

        if user and check_password_hash(user.password, password):
            login_user(user, remember=True)

            if user.role == "admin":
                return redirect(url_for("admin_panel"))
            else:
                return redirect(url_for("profile"))

        return render_template(
            "login.html",
            error="Неверный логин или пароль",
            lang=session.get("lang", "ru")
        )

    return render_template("login.html", lang=session.get("lang", "ru"))


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
        username = request.form.get("username")
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
    orders = (
        Order.query
        .filter_by(user_id=current_user.id)
        .order_by(Order.created_at.desc())
        .all()
    )
    return render_template(
        "profile.html",
        orders=orders,
        ORDER_STATUSES=ORDER_STATUSES
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

    items = []
    total = 0

    for pid, qty in cart.items():
        product = Product.query.get(int(pid))
        if not product or not product.is_active:
            continue

        item_total = product.price * qty
        total += item_total

        items.append({
            "id": product.id,
            "name": product.name_ru,
            "price": product.price,
            "qty": qty,
            "total": item_total,
            "image": product.image
        })

    return render_template(
    "cart.html",
    items=items,
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

    product = Product.query.get(product_id)
    subtotal = product.price * qty if product else 0

    total = 0
    for k, v in cart.items():
        p = Product.query.get(int(k))
        if p:
            total += p.price * v

    return jsonify(
        success=True,
        qty=qty,
        subtotal=subtotal,
        total=total,
        cart_total_items=sum(cart.values())
    )

    
# ======================
# ADMIN PANEL
# ======================
@app.route("/admin")
@login_required
@admin_required
def admin_panel():
    return redirect(url_for("admin_orders"))

#===== checkout =====
@app.route("/checkout", methods=["GET", "POST"])
@login_required
def checkout():
    cart = session.get("cart", {})

    # 🔒 1. Блок пустой корзины (и GET, и POST)
    if not cart or sum(cart.values()) == 0:
        return redirect(url_for("cart"))

    items = []
    total = 0

    for pid, qty in cart.items():
        product = Product.query.get(int(pid))
        if not product or qty <= 0:
            continue

        subtotal = product.price * qty
        total += subtotal
        items.append(f"{product.name_ru} × {qty}")

    # 🔒 2. Блок если товары исчезли или сумма 0
    if not items or total <= 0:
        session.pop("cart", None)
        return redirect(url_for("cart"))

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        contact = request.form.get("contact", "").strip()

        # 🔒 3. Блок пустых полей
        if not name or not contact:
            return render_template(
                "checkout.html",
                items=items,
                total=total,
                error="Заполните все поля"
            )

        # 🔒 4. Повторная проверка ПЕРЕД созданием заказа
        if not session.get("cart"):
            return redirect(url_for("cart"))

        order = Order(
            user_id=current_user.id,
            name=name,
            contact=contact,
            items="\n".join(items),
            total=total,
            status="new"
        )

        db.session.add(order)
        db.session.commit()

        # 🔒 5. Очистка корзины ТОЛЬКО после commit
        session.pop("cart", None)
        session.modified = True

        send_telegram(
            f"🛒 НОВЫЙ ЗАКАЗ\n"
            f"Пользователь: {current_user.username}\n"
            f"Имя: {name}\n"
            f"Контакт: {contact}\n\n"
            f"{chr(10).join(items)}\n"
            f"Итого: {total:.2f} €"
        )

        return redirect(url_for("profile"))

    return render_template(
        "checkout.html",
        items=items,
        total=total
    )

#===== admin-products =====
@app.route("/admin/products", methods=["GET", "POST"])
@login_required
@admin_required
def admin_products():
    if request.method == "POST":
        file = request.files.get("image")

        image_path = None
        if file and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            upload_path = os.path.join(app.config["UPLOAD_FOLDER"], filename)

            os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)
            file.save(upload_path)

            image_path = f"uploads/{filename}"

        product = Product(
            name_ru=request.form["name_ru"],
            name_lv=request.form["name_lv"],
            price=float(request.form["price"]),
            image=image_path,
            is_active=True
        )

        db.session.add(product)
        db.session.commit()
        return redirect(url_for("admin_products"))

    products = Product.query.all()
    return render_template("admin/products.html", products=products)

#===== admin-products-delete =====
@app.route("/admin/products/delete/<int:id>", methods=["POST"])
@login_required
@admin_required
def delete_product(id):
    product = Product.query.get_or_404(id)
    product.is_active = False
    db.session.commit()
    return redirect(url_for("admin_products"))


# показать форму редактирования
@app.route("/admin/products/edit/<int:id>", methods=["GET", "POST"])
@login_required
@admin_required
def edit_product(id):
    product = Product.query.get_or_404(id)

    if request.method == "POST":
        product.name_ru = request.form["name_ru"]
        product.name_lv = request.form["name_lv"]
        product.price = float(request.form["price"])
        product.image = request.form["image"]

        db.session.commit()
        return redirect(url_for("admin_products"))

    return render_template("admin/edit_product.html", product=product)
    
#===== admin-orders =====
@app.route("/admin/orders")
@admin_required
def admin_orders():
    orders = Order.query.order_by(Order.created_at.desc()).all()
    return render_template(
        "admin/orders.html",
        orders=orders,
        ORDER_STATUSES=ORDER_STATUSES,
        lang=session.get("lang", "ru")
    )
#===== dashboard =====
@app.route("/dashboard")
@login_required
@admin_required
def dashboard_redirect():
    return redirect(url_for("admin_panel"))

#===== admin-orders-status =====
@app.route("/admin/orders/<int:order_id>/status", methods=["POST"])
@admin_required
def update_order_status(order_id):
    order = Order.query.get_or_404(order_id)
    new_status = request.form.get("status")

    if new_status in ORDER_STATUSES:
        order.status = new_status
        db.session.commit()

    return redirect(url_for("admin_orders"))

# ===== admin-order-delete =====
@app.route("/admin/orders/delete/<int:order_id>", methods=["POST"])
@login_required
@admin_required
def delete_order(order_id):
    order = Order.query.get_or_404(order_id)
    db.session.delete(order)
    db.session.commit()
    return redirect(url_for("admin_orders"))

#===== admin-products-restore =====
@app.route("/admin/products/restore/<int:id>", methods=["POST"])
@login_required
@admin_required
def restore_product(id):
    product = Product.query.get_or_404(id)
    product.is_active = True
    db.session.commit()
    return redirect(url_for("admin_products"))

from werkzeug.middleware.proxy_fix import ProxyFix
from flask import (
    Flask,
    render_template,
    request,
    session,
    redirect,
    url_for,
    jsonify,
    flash
)
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
from werkzeug.utils import secure_filename
import uuid
import secrets

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

    status = db.Column(db.String(30), default="new")

    is_deleted = db.Column(db.Boolean, default=False)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class Product(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name_ru = db.Column(db.String(200), nullable=False)
    name_lv = db.Column(db.String(200), nullable=False)
    price = db.Column(db.Float, nullable=False)
    image = db.Column(db.String(200))

    is_active = db.Column(db.Boolean, default=True)


class OrderStatusHistory(db.Model):
    id = db.Column(db.Integer, primary_key=True)

    order_id = db.Column(db.Integer, db.ForeignKey("order.id"), nullable=False)
    order = db.relationship("Order", backref="status_history")

    old_status = db.Column(db.String(30))
    new_status = db.Column(db.String(30))

    changed_by = db.Column(db.String(80))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class OrderComment(db.Model):
    id = db.Column(db.Integer, primary_key=True)

    order_id = db.Column(db.Integer, db.ForeignKey("order.id"), nullable=False)
    order = db.relationship("Order", backref="comments")

    author = db.Column(db.String(80))
    text = db.Column(db.Text, nullable=False)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)


# ======================
# USER LOADER
# ======================
@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


# ======================
# INIT DB (SAFE)
# ======================
from sqlalchemy import text, or_
from io import StringIO
import csv
from flask import Response

with app.app_context():
    db.create_all()

    # migration: order.is_deleted
    try:
        db.session.execute(
            text('ALTER TABLE "order" ADD COLUMN is_deleted BOOLEAN DEFAULT FALSE')
        )
        db.session.commit()
    except Exception:
        db.session.rollback()

    # migration: product.is_active
    try:
        db.session.execute(
            text("ALTER TABLE product ADD COLUMN is_active BOOLEAN DEFAULT TRUE")
        )
        db.session.commit()
    except Exception:
        db.session.rollback()


ORDER_STATUSES = {
    "new": {"ru": "Новый", "lv": "Jauns", "en": "New"},
    "confirmed": {"ru": "В работе", "lv": "Darbā", "en": "In progress"},
    "in_progress": {"ru": "В работе", "lv": "Darbā", "en": "In progress"},
    "shipped": {"ru": "Отправлен", "lv": "Nosūtīts", "en": "Shipped"},
    "completed": {"ru": "Завершён", "lv": "Pabeigts", "en": "Completed"},
}

ALLOWED_STATUS_TRANSITIONS = {
    "new": ["in_progress"],
    "confirmed": ["in_progress"],
    "in_progress": ["shipped", "completed"],
    "shipped": ["completed"],
    "completed": [],
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


# CSRF token into templates
@app.context_processor
def inject_csrf_token():
    if "csrf_token" not in session:
        session["csrf_token"] = secrets.token_hex(16)
    return dict(csrf_token=session["csrf_token"])


# ======================
# SECURITY: BLOCK EMPTY CHECKOUT
# ======================
@app.before_request
def block_empty_checkout():
    if request.endpoint == "checkout" and request.method == "POST":
        cart = session.get("cart", {})
        if not cart or sum(cart.values()) == 0:
            return redirect(url_for("cart"))


# CSRF protect all /admin POST
@app.before_request
def csrf_protect_admin():
    if request.method == "POST" and request.path.startswith("/admin"):
        form_token = request.form.get("csrf_token")
        session_token = session.get("csrf_token")

        if not form_token or not session_token or form_token != session_token:
            flash("CSRF ошибка. Обновите страницу.", "error")
            return redirect(url_for("admin_orders"))


# ======================
# ROUTES
# ======================
@app.route("/")
def index():
    return render_template("index.html", lang=session["lang"])


@app.route("/catalog")
def catalog():
    products = Product.query.filter_by(is_active=True).all()
    return render_template("catalog.html", products=products, lang=session["lang"])


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


@app.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("index"))


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


@app.route("/profile")
@login_required
def profile():
    orders = (
        Order.query
        .filter_by(user_id=current_user.id)
        .order_by(Order.created_at.desc())
        .all()
    )
    return render_template("profile.html", orders=orders, ORDER_STATUSES=ORDER_STATUSES)


@app.route("/api/add_to_cart/<int:product_id>", methods=["POST"])
def add_to_cart(product_id):
    cart = session.get("cart", {})
    pid = str(product_id)

    cart[pid] = cart.get(pid, 0) + 1
    session["cart"] = cart
    session.modified = True

    return jsonify(success=True, cart_total_items=sum(cart.values()))


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

    return render_template("cart.html", items=items, total=total, lang=session.get("lang", "ru"))


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


@app.route("/admin")
@login_required
@admin_required
def admin_panel():
    return redirect(url_for("admin_orders"))


# ===== CHECKOUT =====
import re

@app.route("/checkout", methods=["GET", "POST"])
@login_required
def checkout():
    cart = session.get("cart", {})

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

    items_text = "\n".join(items)

    if not items or total <= 0:
        session.pop("cart", None)
        return redirect(url_for("cart"))

    if request.method == "GET":
        session["checkout_token"] = str(uuid.uuid4())

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        contact = request.form.get("contact", "").strip()

        form_token = request.form.get("checkout_token")
        session_token = session.get("checkout_token")
        if not form_token or form_token != session_token:
            return redirect(url_for("cart"))

        session.pop("checkout_token", None)

        if len(name) < 2:
            return render_template(
                "checkout.html",
                items=items,
                total=total,
                error="Имя слишком короткое",
                checkout_token=session.get("checkout_token")
            )

        email_regex = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"
        phone_regex = r"^\+?[0-9\s\-]{7,15}$"
        if not (re.match(email_regex, contact) or re.match(phone_regex, contact)):
            return render_template(
                "checkout.html",
                items=items,
                total=total,
                error="Введите корректный телефон или email",
                checkout_token=session.get("checkout_token")
            )

        if not session.get("cart"):
            return redirect(url_for("cart"))

        last_order_ts = session.get("last_order_ts")
        now = datetime.utcnow().timestamp()
        if last_order_ts and now - last_order_ts < 60:
            return render_template(
                "checkout.html",
                items=items,
                total=total,
                error="Подождите минуту перед следующим заказом",
                checkout_token=session.get("checkout_token")
            )

        order = Order(
            user_id=current_user.id,
            name=name,
            contact=contact,
            items=items_text,
            total=total,
            status="new",
            is_deleted=False
        )

        db.session.add(order)
        db.session.commit()

        session["last_order_ts"] = datetime.utcnow().timestamp()

        session.pop("cart", None)
        session.modified = True

        send_telegram(
            f"🛒 НОВЫЙ ЗАКАЗ\n"
            f"Пользователь: {current_user.username}\n"
            f"Имя: {name}\n"
            f"Контакт: {contact}\n\n"
            f"{items_text}\n"
            f"Итого: {total:.2f} €"
        )

        return redirect(url_for("profile"))

    return render_template(
        "checkout.html",
        items=items,
        total=total,
        checkout_token=session.get("checkout_token")
    )


# ===== ADMIN PRODUCTS =====
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

    show = request.args.get("show", "active")

    if show == "inactive":
        products = Product.query.filter_by(is_active=False).all()
    elif show == "all":
        products = Product.query.all()
    else:
        products = Product.query.filter_by(is_active=True).all()

    return render_template("admin/products.html", products=products, show=show)


@app.route("/admin/products/delete/<int:id>", methods=["POST"])
@login_required
@admin_required
def delete_product(id):
    product = Product.query.get_or_404(id)
    product.is_active = False
    db.session.commit()
    return redirect(url_for("admin_products"))


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


# ===== ADMIN ORDERS =====
@app.route("/admin/orders")
@admin_required
def admin_orders():
    show = request.args.get("show", "active")
    q = request.args.get("q", "").strip()
    page = request.args.get("page", 1, type=int)
    PER_PAGE = 20

    ACTIVE_STATUSES = ["new", "in_progress", "shipped"]
    ARCHIVE_STATUSES = ["completed"]

    query = Order.query

    if show == "archive":
        query = query.filter(
            or_(
                Order.is_deleted.is_(True),
                Order.status.in_(ARCHIVE_STATUSES)
            )
        )
    else:
        query = query.filter(
            Order.is_deleted.is_(False),
            Order.status.in_(ACTIVE_STATUSES)
        )

    if q:
        if q.isdigit():
            query = query.filter(Order.id == int(q))
        else:
            like = f"%{q}%"
            query = query.filter(
                or_(
                    Order.name.ilike(like),
                    Order.contact.ilike(like)
                )
            )

    pagination = (
        query
        .order_by(Order.created_at.desc())
        .paginate(page=page, per_page=PER_PAGE, error_out=False)
    )

    return render_template(
        "admin/orders.html",
        orders=pagination.items,
        pagination=pagination,
        ORDER_STATUSES=ORDER_STATUSES,
        ALLOWED_STATUS_TRANSITIONS=ALLOWED_STATUS_TRANSITIONS,
        lang=session.get("lang", "ru"),
        show=show
    )


@app.route("/dashboard")
@login_required
@admin_required
def dashboard_redirect():
    return redirect(url_for("admin_panel"))


@app.route("/admin/orders/<int:order_id>/status", methods=["POST"])
@admin_required
def update_order_status(order_id):
    order = Order.query.get_or_404(order_id)

    new_status = request.form.get("status")
    old_status = order.status

    if not new_status or new_status == old_status:
        return redirect(url_for("admin_orders"))

    if new_status not in ORDER_STATUSES:
        return redirect(url_for("admin_orders"))

    allowed = ALLOWED_STATUS_TRANSITIONS.get(old_status, [])
    if new_status not in allowed:
        flash("Недопустимый переход статуса", "error")
        return redirect(url_for("admin_orders"))

    order.status = new_status

    # ✅ Авто-архив при completed (чтобы сразу ушел в Архив)
    if new_status == "completed":
        order.is_deleted = True

    history = OrderStatusHistory(
        order_id=order.id,
        old_status=old_status,
        new_status=new_status,
        changed_by=current_user.username
    )

    db.session.add(history)
    db.session.commit()

    return redirect(url_for("admin_orders"))


@app.route("/admin/orders/delete/<int:order_id>", methods=["POST"])
@login_required
@admin_required
def delete_order(order_id):
    order = Order.query.get_or_404(order_id)
    order.is_deleted = True
    db.session.commit()
    flash("Заказ перемещён в архив", "success")
    return redirect(url_for("admin_orders"))


# ======================
# ✅ ПУНКТ 24: RESTORE ORDER
# ======================
@app.route("/admin/orders/restore/<int:order_id>", methods=["POST"])
@login_required
@admin_required
def restore_order(order_id):
    order = Order.query.get_or_404(order_id)

    # завершенный заказ логикой статусов не возвращаем назад
    if order.status == "completed":
        flash("Завершённый заказ нельзя вернуть из архива.", "error")
        return redirect(url_for("admin_orders", show="archive"))

    order.is_deleted = False
    db.session.commit()
    flash("Заказ восстановлен из архива", "success")
    return redirect(url_for("admin_orders", show="archive"))


# ======================
# ✅ ПУНКТ 25: HARD DELETE ORDER (навсегда)
# ======================
@app.route("/admin/orders/hard_delete/<int:order_id>", methods=["POST"])
@login_required
@admin_required
def hard_delete_order(order_id):
    order = Order.query.get_or_404(order_id)

    # сначала удаляем зависимые записи
    OrderStatusHistory.query.filter_by(order_id=order.id).delete()
    OrderComment.query.filter_by(order_id=order.id).delete()

    db.session.delete(order)
    db.session.commit()

    flash("Заказ удалён навсегда", "success")
    return redirect(url_for("admin_orders", show="archive"))


@app.route("/admin/products/restore/<int:id>", methods=["POST"])
@login_required
@admin_required
def restore_product(id):
    product = Product.query.get_or_404(id)
    product.is_active = True
    db.session.commit()
    return redirect(url_for("admin_products"))


@app.route("/admin/orders/<int:order_id>")
@admin_required
def admin_order_view(order_id):
    order = Order.query.get_or_404(order_id)

    history = (
        OrderStatusHistory.query
        .filter_by(order_id=order.id)
        .order_by(OrderStatusHistory.created_at.desc())
        .all()
    )

    return render_template(
        "admin/order_view.html",
        order=order,
        history=history,
        ORDER_STATUSES=ORDER_STATUSES,
        lang=session.get("lang", "ru")
    )


# ======================
# ✅ ПУНКТ 27: PRINT ORDER
# ======================
@app.route("/admin/orders/<int:order_id>/print")
@admin_required
def admin_order_print(order_id):
    order = Order.query.get_or_404(order_id)

    history = (
        OrderStatusHistory.query
        .filter_by(order_id=order.id)
        .order_by(OrderStatusHistory.created_at.desc())
        .all()
    )

    comments = (
        OrderComment.query
        .filter_by(order_id=order.id)
        .order_by(OrderComment.created_at.desc())
        .all()
    )

    return render_template(
        "admin/order_print.html",
        order=order,
        history=history,
        comments=comments,
        ORDER_STATUSES=ORDER_STATUSES,
        lang=session.get("lang", "ru")
    )


@app.route("/admin/orders/export")
@admin_required
def export_orders_csv():
    show = request.args.get("show", "active")
    q = request.args.get("q", "").strip()

    ACTIVE_STATUSES = ["new", "in_progress", "shipped"]
    ARCHIVE_STATUSES = ["completed"]

    query = Order.query

    if show == "archive":
        query = query.filter(
            or_(
                Order.is_deleted.is_(True),
                Order.status.in_(ARCHIVE_STATUSES)
            )
        )
    else:
        query = query.filter(
            Order.is_deleted.is_(False),
            Order.status.in_(ACTIVE_STATUSES)
        )

    if q:
        if q.isdigit():
            query = query.filter(Order.id == int(q))
        else:
            like = f"%{q}%"
            query = query.filter(
                or_(
                    Order.name.ilike(like),
                    Order.contact.ilike(like)
                )
            )

    orders = query.order_by(Order.created_at.desc()).all()

    si = StringIO()
    writer = csv.writer(si)

    writer.writerow(["ID", "Имя", "Контакт", "Состав", "Сумма", "Статус", "Дата"])

    for o in orders:
        writer.writerow([
            o.id,
            o.name,
            o.contact,
            o.items,
            f"{o.total:.2f}",
            ORDER_STATUSES.get(o.status, {}).get("ru", o.status),
            o.created_at.strftime("%d.%m.%Y %H:%M")
        ])

    output = si.getvalue()
    si.close()

    return Response(
        output,
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename=orders_{show}.csv"}
    )


@app.route("/admin/orders/<int:order_id>/comment", methods=["POST"])
@admin_required
def add_order_comment(order_id):
    order = Order.query.get_or_404(order_id)

    text_comment = request.form.get("comment", "").strip()
    if not text_comment:
        return redirect(url_for("admin_order_view", order_id=order.id))

    comment = OrderComment(
        order_id=order.id,
        author=current_user.username,
        text=text_comment
    )

    db.session.add(comment)
    db.session.commit()

    return redirect(url_for("admin_order_view", order_id=order.id))

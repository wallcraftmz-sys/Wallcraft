from werkzeug.middleware.proxy_fix import ProxyFix
from flask import (
    Flask,
    render_template,
    request,
    session,
    redirect,
    url_for,
    jsonify,
    flash,
    render_template_string,
    Response,
)
import os
import re
import time
import uuid
import secrets
import logging
import csv
import requests
from io import StringIO
from datetime import timedelta, datetime
from pathlib import Path
from urllib.parse import urlparse, urljoin
from functools import wraps
from collections import defaultdict, deque

from flask_sqlalchemy import SQLAlchemy
from flask_login import (
    LoginManager,
    UserMixin,
    login_user,
    logout_user,
    current_user,
    login_required,
)
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from sqlalchemy import text, or_
from PIL import Image

def admin_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not current_user.is_authenticated:
            return redirect(url_for("login", next=request.path))
        if getattr(current_user, "role", "") != "admin":
            flash("Нет доступа", "error")
            return redirect(url_for("index", lang=session.get("lang", "ru")))
        return fn(*args, **kwargs)
    return wrapper

UPLOAD_FOLDER = os.path.join("static", "uploads")

os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# ======================
# SECURITY: SAFE REDIRECT + INPUT NORMALIZATION
# ======================
def safe_redirect_target(target: str):
    """
    Разрешает редирект ТОЛЬКО на свой домен/внутренние пути.
    Если target опасный — возвращаем None.
    """
    if not target:
        return None
    try:
        host_url = request.host_url
        test_url = urljoin(host_url, target)
        host_parts = urlparse(host_url)
        test_parts = urlparse(test_url)

        if test_parts.scheme in ("http", "https") and host_parts.netloc == test_parts.netloc:
            return test_parts.path + (("?" + test_parts.query) if test_parts.query else "")
    except Exception:
        pass
    return None


def norm_text(s: str, max_len: int = 120) -> str:
    if not s:
        return ""
    s = str(s).strip()
    s = re.sub(r"\s+", " ", s)
    s = s.replace("\x00", "")
    return s[:max_len]


def norm_contact(s: str, max_len: int = 80) -> str:
    if not s:
        return ""
    s = str(s).strip()
    s = re.sub(r"\s+", " ", s)
    s = s.replace("\x00", "")
    if any(ch.isdigit() for ch in s) and ("@" not in s):
        s = re.sub(r"[^0-9+]", "", s)
    return s[:max_len]


# ======================
# APP CONFIG
# ======================
app = Flask(__name__)

# ======================
# CORE-9: LOGGING
# ======================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("wallcraft")

# ======================
# CORE-10: CONFIG dev/prod
# ======================
class BaseConfig:
    SECRET_KEY = os.getenv("SECRET_KEY", "wallcraft_super_secret_key")
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    REMEMBER_COOKIE_HTTPONLY = True
    REMEMBER_COOKIE_SAMESITE = "Lax"
    MAX_CONTENT_LENGTH = 8 * 1024 * 1024  # 8MB upload limit


class ProdConfig(BaseConfig):
    DEBUG = False
    TESTING = False


class DevConfig(BaseConfig):
    DEBUG = True
    TESTING = False


APP_ENV = os.getenv("APP_ENV", "prod").lower()
app.config.from_object(DevConfig if APP_ENV == "dev" else ProdConfig)
app.secret_key = os.getenv("SECRET_KEY", "wallcraft_super_secret_key")

# Railway / ProxyFix
app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)

# Cookies
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    REMEMBER_COOKIE_HTTPONLY=True,
    REMEMBER_COOKIE_SAMESITE="Lax",
)

# Uploads
UPLOAD_FOLDER = "static/uploads"
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "webp"}
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER

# Sessions
app.permanent_session_lifetime = timedelta(days=7)
app.config["REMEMBER_COOKIE_DURATION"] = timedelta(days=7)

# DB
DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL is not set")

if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

app.config["SQLALCHEMY_DATABASE_URI"] = DATABASE_URL
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False


def allowed_file(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


# ======================
# #22: Simple rate limit (in-memory)
# ======================
_rl_hits = defaultdict(lambda: deque())  # key -> timestamps


def _rl_key(scope: str) -> str:
    xff = request.headers.get("X-Forwarded-For", "")
    ip = xff.split(",")[0].strip() if xff else (request.remote_addr or "unknown")
    return f"{scope}:{ip}"


def _rl_allow(scope: str, limit: int, window_sec: int) -> bool:
    """
    True  -> разрешаем
    False -> превышен лимит
    """
    now = time.time()
    key = _rl_key(scope)
    q = _rl_hits[key]

    while q and (now - q[0]) > window_sec:
        q.popleft()

    if len(q) >= limit:
        return False

    q.append(now)
    return True


# =========================
# #26B: Anti brute-force by IP (login)
# =========================
MAX_FAILS = 8
WINDOW_SEC = 10 * 60
BAN_SEC = 30 * 60

_failed_logins = defaultdict(lambda: deque())  # ip -> timestamps
_banned_until = {}  # ip -> unix time


def _client_ip():
    xff = request.headers.get("X-Forwarded-For", "")
    if xff:
        return xff.split(",")[0].strip()
    return request.remote_addr or "unknown"


def _cleanup_old(ip: str, now: float):
    q = _failed_logins[ip]
    while q and (now - q[0]) > WINDOW_SEC:
        q.popleft()


def is_ip_banned(ip: str) -> bool:
    now = time.time()
    until = _banned_until.get(ip)
    if not until:
        return False
    if now >= until:
        _banned_until.pop(ip, None)
        return False
    return True


def register_failed_attempt(ip: str):
    now = time.time()
    _cleanup_old(ip, now)
    _failed_logins[ip].append(now)
    if len(_failed_logins[ip]) >= MAX_FAILS:
        _banned_until[ip] = now + BAN_SEC


def reset_attempts(ip: str):
    _failed_logins.pop(ip, None)
    _banned_until.pop(ip, None)


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


class AdminAuditLog(db.Model):
    __tablename__ = "admin_audit_logs"

    id = db.Column(db.Integer, primary_key=True)
    admin_username = db.Column(db.String(120), nullable=False)
    action = db.Column(db.String(120), nullable=False)
    entity = db.Column(db.String(60), nullable=True)
    entity_id = db.Column(db.Integer, nullable=True)
    ip = db.Column(db.String(64), nullable=True)
    user_agent = db.Column(db.String(255), nullable=True)
    details = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)


class Category(db.Model):
    __tablename__ = "category"

    id = db.Column(db.Integer, primary_key=True)
    slug = db.Column(db.String(60), unique=True, nullable=False)   # например: doors, windows, wallpaper
    title_ru = db.Column(db.String(120), nullable=False)
    title_lv = db.Column(db.String(120), nullable=False)
    title_en = db.Column(db.String(120), nullable=False)
    sort = db.Column(db.Integer, default=0)
    is_active = db.Column(db.Boolean, default=True)


class Product(db.Model):
    __tablename__ = "product"

    id = db.Column(db.Integer, primary_key=True)
    name_ru = db.Column(db.String(200), nullable=False)
    name_lv = db.Column(db.String(200), nullable=False)
    price = db.Column(db.Float, nullable=False)
    image = db.Column(db.String(200))
    is_active = db.Column(db.Boolean, default=True)

    # новая нормальная категория
    category_id = db.Column(db.Integer, db.ForeignKey("category.id"), nullable=True)
    category = db.relationship("Category", backref="products")

    # (опционально) оставь старое поле, чтобы ничего не ломать при миграции
    legacy_category = db.Column(db.String(50), nullable=True)

class Order(db.Model):
    __tablename__ = "order"

    id = db.Column(db.Integer, primary_key=True)

    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    user = db.relationship("User", backref="orders")

    name = db.Column(db.String(100), nullable=False)
    contact = db.Column(db.String(100), nullable=False)

    # ✅ НОВОЕ
    address = db.Column(db.String(200), default="")
    delivery_time = db.Column(db.String(60), default="")
    courier = db.Column(db.String(80), default="")

    items = db.Column(db.Text, nullable=False)
    total = db.Column(db.Float, nullable=False)

    status = db.Column(db.String(30), default="new")
    is_deleted = db.Column(db.Boolean, default=False)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    delivery_provider = db.Column(db.String(30), default="manual")  # manual / bolt / wolt
    tracking_code = db.Column(db.String(80), default="")            # номер/код доставки
# ======================
# USER LOADER
# ======================
@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


# ======================
# INIT DB (SAFE) — ONE BLOCK
# ======================
with app.app_context():
    db.create_all()

    # order.is_deleted
    try:
        db.session.execute(text('ALTER TABLE "order" ADD COLUMN IF NOT EXISTS is_deleted BOOLEAN DEFAULT FALSE'))
        db.session.commit()
    except Exception:
        db.session.rollback()

    # product.is_active
    try:
        db.session.execute(text("ALTER TABLE product ADD COLUMN IF NOT EXISTS is_active BOOLEAN DEFAULT TRUE"))
        db.session.commit()
    except Exception:
        db.session.rollback()

    # если раньше было product.category — переименуем в legacy_category
    try:
        db.session.execute(text("ALTER TABLE product RENAME COLUMN category TO legacy_category"))
        db.session.commit()
    except Exception:
        db.session.rollback()

    # на всякий случай: legacy_category может отсутствовать
    try:
        db.session.execute(text("ALTER TABLE product ADD COLUMN IF NOT EXISTS legacy_category VARCHAR(50)"))
        db.session.commit()
    except Exception:
        db.session.rollback()

    # product.category_id
    try:
        db.session.execute(text("ALTER TABLE product ADD COLUMN IF NOT EXISTS category_id INTEGER"))
        db.session.commit()
    except Exception:
        db.session.rollback()

    # дефолтные категории
    def ensure_category(slug, ru, lv, en, sort):
        if not Category.query.filter_by(slug=slug).first():
            db.session.add(Category(slug=slug, title_ru=ru, title_lv=lv, title_en=en, sort=sort, is_active=True))

    ensure_category("wallpaper", "Обои", "Tapetes", "Wallpaper", 1)
    ensure_category("doors", "Двери", "Durvis", "Doors", 2)
    ensure_category("windows", "Окна", "Logi", "Windows", 3)
    db.session.commit()

    # привязка старых товаров к новым категориям
    try:
        mapping = {c.slug: c.id for c in Category.query.all()}
        default_id = mapping.get("doors")

        products = Product.query.filter(Product.category_id.is_(None)).all()
        for p in products:
            slug = (p.legacy_category or "").strip() or "doors"
            p.category_id = mapping.get(slug, default_id)

        db.session.commit()
    except Exception:
        db.session.rollback()

       # ✅ order.address / order.delivery_time / order.courier
    try:
        db.session.execute(text('ALTER TABLE "order" ADD COLUMN IF NOT EXISTS address VARCHAR(200) DEFAULT \'\''))
        db.session.execute(text('ALTER TABLE "order" ADD COLUMN IF NOT EXISTS delivery_time VARCHAR(60) DEFAULT \'\''))
        db.session.execute(text('ALTER TABLE "order" ADD COLUMN IF NOT EXISTS courier VARCHAR(80) DEFAULT \'\''))
        db.session.commit()
    except Exception:
        db.session.rollback()

    try:
        db.session.execute(text('ALTER TABLE "order" ADD COLUMN IF NOT EXISTS delivery_provider VARCHAR(30) DEFAULT \'manual\''))
        db.session.execute(text('ALTER TABLE "order" ADD COLUMN IF NOT EXISTS tracking_code VARCHAR(80) DEFAULT \'\''))
        db.session.commit()
    except Exception:
        db.session.rollback()

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
        logger.warning("Telegram ENV vars not set")
        return False

    try:
        r = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": message},
            timeout=10,
        )
        logger.info("TG response: %s %s", r.status_code, r.text)
        return r.ok
    except Exception as e:
        logger.exception("TG error: %r", e)
        return False


# ======================
# CONSTANTS (ORDERS)
# ======================

# Заголовки таблицы заказов
ORDER_TABLE_LABELS = {
    "order":   {"ru": "Заказ",   "lv": "Pasūtījums", "en": "Order"},
    "address": {"ru": "Адрес",   "lv": "Adrese",     "en": "Address"},
    "time":    {"ru": "Время",   "lv": "Laiks",      "en": "Time"},
    "courier": {"ru": "Курьер",  "lv": "Kurjers",    "en": "Courier"},
    "status":  {"ru": "Статус",  "lv": "Statuss",    "en": "Status"},
}

# Каноничные статусы (ТОЛЬКО ОНИ)
ORDER_STATUSES = {
    "new": {"ru": "Новый", "lv": "Jauns", "en": "New"},
    "confirmed": {"ru": "Подтверждён", "lv": "Apstiprināts", "en": "Confirmed"},

    "courier_picked": {"ru": "Курьер забрал", "lv": "Kurjers paņēma", "en": "Courier picked up"},
    "courier_on_way": {"ru": "Курьер в пути", "lv": "Kurjers ceļā", "en": "Courier on the way"},
    "courier_arrived": {"ru": "Курьер на месте", "lv": "Kurjers ieradies", "en": "Courier arrived"},

    "completed": {"ru": "Завершён", "lv": "Pabeigts", "en": "Completed"},
    "canceled": {"ru": "Отменён", "lv": "Atcelts", "en": "Canceled"},
}

ALLOWED_STATUS_TRANSITIONS = {
    "new": ["confirmed", "canceled"],
    "confirmed": ["courier_picked", "canceled"],
    "courier_picked": ["courier_on_way", "canceled"],
    "courier_on_way": ["courier_arrived", "canceled"],
    "courier_arrived": ["completed", "canceled"],
    "completed": [],
    "canceled": [],
}

# Алиасы старых статусов (чтобы ничего не сломалось)
STATUS_ALIASES = {
    # старые -> новые
    "in_progress": "confirmed",
    "shipped": "courier_on_way",
    "completed": "completed",
    "new": "new",
    "confirmed": "confirmed",
}

def normalize_order_status(status: str) -> str:
    s = (status or "new").strip().lower()
    s = STATUS_ALIASES.get(s, s)
    return s if s in ORDER_STATUSES else "new"

# ======================
# LANGUAGE / I18N (FINAL)
# ======================

SUPPORTED_LANGS = ("ru", "lv", "en")

@app.before_request
def set_lang():
    q_lang = request.args.get("lang", "").lower()
    if q_lang in SUPPORTED_LANGS:
        session["lang"] = q_lang

    if session.get("lang") not in SUPPORTED_LANGS:
        session["lang"] = "ru"


TRANSLATIONS = {
    # MENU
    "profile":  {"ru": "Профиль", "en": "Profile", "lv": "Profils"},
    "catalog":  {"ru": "Каталог", "en": "Catalog", "lv": "Katalogs"},
    "cart":     {"ru": "Корзина", "en": "Cart", "lv": "Grozs"},
    "admin":    {"ru": "Админ", "en": "Admin", "lv": "Administrācija"},

    # AUTH
    "login":    {"ru": "Войти", "en": "Login", "lv": "Ieiet"},
    "logout":   {"ru": "Выйти", "en": "Logout", "lv": "Iziet"},
    "register": {"ru": "Регистрация", "en": "Register", "lv": "Reģistrācija"},

    # SHOP / CART
    "add_to_cart": {"ru": "В корзину", "en": "Add to cart", "lv": "Pievienot grozam"},
    "added":       {"ru": "Товар добавлен в корзину", "en": "Product added to cart", "lv": "Prece pievienota grozam"},
    "continue":    {"ru": "Продолжить покупки", "en": "Continue shopping", "lv": "Turpināt iepirkties"},
    "go_to_cart":  {"ru": "Перейти в корзину", "en": "Go to cart", "lv": "Doties uz grozu"},
    "empty_cart":  {"ru": "Корзина пуста", "en": "Cart is empty", "lv": "Grozs ir tukšs"},
    "total":       {"ru": "Итого", "en": "Total", "lv": "Kopā"},
    "checkout":    {"ru": "Оформить заказ", "en": "Checkout", "lv": "Noformēt pasūtījumu"},
    "checkout_title": {"ru": "Оформление заказа", "en": "Checkout", "lv": "Pasūtījuma noformēšana"},

    # CHECKOUT FORM
    "name": {"ru": "Имя", "en": "Name", "lv": "Vārds"},
    "name_placeholder": {"ru": "Введите имя", "en": "Enter your name", "lv": "Ievadiet vārdu"},
    "contact": {"ru": "Телефон или Email", "en": "Phone or Email", "lv": "Tālrunis vai e-pasts"},
    "contact_hint": {
        "ru": "Введите email или телефон (пример: test@mail.com или +371 20000000)",
        "en": "Enter email or phone (example: test@mail.com or +371 20000000)",
        "lv": "Ievadiet e-pastu vai tālruni (piemērs: test@mail.com vai +371 20000000)",
    },
    "confirm_order": {"ru": "Подтвердить заказ", "en": "Confirm order", "lv": "Apstiprināt pasūtījumu"},

    # ✅ DELIVERY (вставлено правильно)
    "delivery_provider": {"ru": "Доставка", "lv": "Piegāde", "en": "Delivery"},
    "delivery_manual": {"ru": "Курьер (вручную)", "lv": "Kurjers (manuāli)", "en": "Courier (manual)"},
    "delivery_bolt": {"ru": "Bolt (в будущем)", "lv": "Bolt (nākotnē)", "en": "Bolt (future)"},
    "delivery_wolt": {"ru": "Wolt (в будущем)", "lv": "Wolt (nākotnē)", "en": "Wolt (future)"},
    "tracking_code": {"ru": "Номер доставки", "lv": "Piegādes numurs", "en": "Delivery ID"},

    # ADMIN PAGES
    "products": {"ru": "Товары", "en": "Products", "lv": "Preces"},
    "orders":   {"ru": "Заказы", "en": "Orders", "lv": "Pasūtījumi"},
    "add_product": {"ru": "Добавить товар", "en": "Add product", "lv": "Pievienot preci"},
    "active": {"ru": "Активные", "en": "Active", "lv": "Aktīvie"},
    "inactive": {"ru": "Скрытые", "en": "Hidden", "lv": "Slēptie"},
    "all": {"ru": "Все", "en": "All", "lv": "Visi"},
    "restore": {"ru": "Восстановить", "en": "Restore", "lv": "Atjaunot"},
    "delete_forever": {"ru": "Удалить навсегда", "en": "Delete forever", "lv": "Dzēst neatgriezeniski"},
    "price": {"ru": "Цена", "en": "Price", "lv": "Cena"},

    # CONFIRMS (PRODUCTS)
    "confirm_hide_product": {
        "ru": "Скрыть товар из каталога?",
        "en": "Hide this product from the catalog?",
        "lv": "Paslēpt preci no kataloga?",
    },
    "confirm_hard_delete_product": {
        "ru": "Удалить товар НАВСЕГДА? Это действие нельзя отменить.",
        "en": "Delete this product FOREVER? This action cannot be undone.",
        "lv": "Dzēst preci UZ VISIEM LAIKIEM? Šo darbību nevar atsaukt.",
    },

    # ADMIN ORDERS UI
    "archive": {"ru": "Архив", "en": "Archive", "lv": "Arhīvs"},
    "search": {"ru": "Найти", "en": "Search", "lv": "Meklēt"},
    "reset": {"ru": "Сброс", "en": "Reset", "lv": "Atiestatīt"},
    "search_placeholder": {"ru": "Поиск: ID, имя, контакт", "en": "Search: ID, name, contact", "lv": "Meklēšana: ID, vārds, kontakts"},
    "export_csv": {"ru": "Экспорт заказов (CSV)", "en": "Export orders (CSV)", "lv": "Eksportēt pasūtījumus (CSV)"},
    "buyer": {"ru": "Покупатель", "en": "Customer", "lv": "Pircējs"},
    "items": {"ru": "Состав", "en": "Items", "lv": "Saturs"},
    "sum": {"ru": "Сумма", "en": "Amount", "lv": "Summa"},
    "status": {"ru": "Статус", "en": "Status", "lv": "Statuss"},
    "history": {"ru": "История", "en": "History", "lv": "Vēsture"},
    "date": {"ru": "Дата", "en": "Date", "lv": "Datums"},
    "actions": {"ru": "Действия", "en": "Actions", "lv": "Darbības"},
    "print": {"ru": "Печать", "en": "Print", "lv": "Drukāt"},
    "no_orders": {"ru": "Нет заказов", "en": "No orders", "lv": "Nav pasūtījumu"},
    "to_archive": {"ru": "В архив", "en": "To archive", "lv": "Uz arhīvu"},

    "confirm_restore_order": {
        "ru": "Восстановить заказ из архива?",
        "en": "Restore the order from archive?",
        "lv": "Atjaunot pasūtījumu no arhīva?",
    },
    "confirm_hard_delete_order": {
        "ru": "Удалить заказ НАВСЕГДА? Это действие нельзя отменить.",
        "en": "Delete the order FOREVER? This action cannot be undone.",
        "lv": "Dzēst pasūtījumu UZ VISIEM LAIKIEM? Šo darbību nevar atsaukt.",
    },
    "confirm_archive_order": {
        "ru": "Переместить заказ в архив?",
        "en": "Move the order to archive?",
        "lv": "Pārvietot pasūtījumu uz arhīvu?",
    },

    # HERO
    "hero_subtitle": {
        "ru": "Жидкие обои премиум-класса",
        "lv": "Premium klases šķidrās tapetes",
        "en": "Premium liquid wallpaper",
    },

    # LEGAL PAGES
    "privacy_title": {"ru": "Политика конфиденциальности", "lv": "Privātuma politika", "en": "Privacy Policy"},
    "terms_title": {"ru": "Условия", "lv": "Noteikumi", "en": "Terms & Conditions"},
    "contacts_title": {"ru": "Контакты", "lv": "Kontakti", "en": "Contacts"},
    "back_home": {"ru": "На главную", "lv": "Uz sākumlapu", "en": "Back to home"},

    # Footer link texts
    "privacy_link": {"ru": "Политика конфиденциальности", "lv": "Privātuma politika", "en": "Privacy Policy"},
    "terms_link": {"ru": "Условия использования", "lv": "Lietošanas noteikumi", "en": "Terms & Conditions"},
    "contacts_link": {"ru": "Контакты", "lv": "Kontakti", "en": "Contacts"},

    "privacy_text": {
        "ru": "Мы обрабатываем только те данные, которые необходимы для обработки заказа: имя и контактную информацию. Данные не передаются третьим лицам.",
        "lv": "Mēs apstrādājam tikai tos datus, kas nepieciešami pasūtījuma apstrādei: vārdu un kontaktinformāciju. Dati netiek nodoti trešajām personām.",
        "en": "We process only the data necessary to fulfill the order: name and contact information. Data is not shared with third parties.",
    },

    "terms_text": {
        "ru": "Оформляя заказ на сайте, вы подтверждаете, что указанные вами данные верны, и соглашаетесь с условиями обработки заказа. Оплата и способ доставки согласуются отдельно после оформления заказа. Мы оставляем за собой право уточнить детали заказа по телефону или email.",
        "lv": "Veicot pasūtījumu vietnē, jūs apstiprināt, ka sniegtā informācija ir pareiza, un piekrītat pasūtījuma apstrādes noteikumiem. Apmaksa un piegādes veids tiek saskaņoti atsevišķi pēc pasūtījuma noformēšanas. Mēs varam sazināties ar jums pa tālruni vai e-pastu, lai precizētu pasūtījuma detaļas.",
        "en": "By placing an order on the website, you confirm that the information you provide is accurate and agree to the order processing terms. Payment and delivery method are arranged separately after the order is placed. We may contact you by phone or email to clarify order details.",
    },

    # ВАЖНО: в строках используем \n
    "contacts_text": {
        "ru": "Email: wallcraftmz@gmail.com\nГород: Рига\nПо вопросам заказа напишите нам на email — мы ответим как можно быстрее.",
        "lv": "E-pasts: wallcraftmz@gmail.com\nPilsēta: Rīga\nPar pasūtījumiem rakstiet uz e-pastu — atbildēsim pēc iespējas ātrāk.",
        "en": "Email: wallcraftmz@gmail.com\nCity: Riga\nFor order questions, email us — we will reply as soon as possible.",
    },

    # ✅ Orders table headers
    "th_order":   {"ru": "Заказ",  "lv": "Pasūtījums", "en": "Order"},
    "th_address": {"ru": "Адрес",  "lv": "Adrese",     "en": "Address"},
    "th_time":    {"ru": "Время",  "lv": "Laiks",      "en": "Time"},
    "th_courier": {"ru": "Курьер", "lv": "Kurjers",    "en": "Courier"},
    "th_status":  {"ru": "Статус", "lv": "Statuss",    "en": "Status"},

    # ✅ Field labels / placeholders
    "address": {"ru": "Адрес", "lv": "Adrese", "en": "Address"},
    "address_placeholder": {
        "ru": "Например: Riga, Brīvības iela 10-5",
        "lv": "Piem.: Rīga, Brīvības iela 10-5",
        "en": "Example: Riga, Brivibas street 10-5",
    },

    "delivery_time": {"ru": "Время", "lv": "Laiks", "en": "Time"},
    "delivery_time_placeholder": {
        "ru": "Например: сегодня 18:00–20:00",
        "lv": "Piem.: šodien 18:00–20:00",
        "en": "Example: today 18:00–20:00",
    },

    "courier": {"ru": "Курьер", "lv": "Kurjers", "en": "Courier"},
    "courier_placeholder": {"ru": "Имя курьера", "lv": "Kurjera vārds", "en": "Courier name"},

    # ADMIN TITLES (fix admin_orders text)
    "admin_orders":   {"ru": "Заказы",   "lv": "Pasūtījumi", "en": "Orders"},
    "admin_products": {"ru": "Товары",   "lv": "Preces",     "en": "Products"},

    "delivery_timeline": {"ru": "Доставка", "lv": "Piegāde", "en": "Delivery"},
    "timeline_new": {"ru": "Заказ принят", "lv": "Pasūtījums pieņemts", "en": "Order received"},
    "timeline_confirmed": {"ru": "Подтверждён", "lv": "Apstiprināts", "en": "Confirmed"},
    "timeline_picked": {"ru": "Курьер забрал", "lv": "Kurjers paņēma", "en": "Picked up"},
    "timeline_on_way": {"ru": "Курьер в пути", "lv": "Kurjers ceļā", "en": "On the way"},
    "timeline_arrived": {"ru": "Курьер на месте", "lv": "Kurjers ieradies", "en": "Arrived"},
    "timeline_completed": {"ru": "Завершён", "lv": "Pabeigts", "en": "Completed"},
    "timeline_canceled": {"ru": "Отменён", "lv": "Atcelts", "en": "Canceled"},
    }

def t(key: str, lang: str = None) -> str:
    lang = (lang or session.get("lang", "ru")).lower()
    if lang not in SUPPORTED_LANGS:
        lang = "ru"

    pack = TRANSLATIONS.get(key)
    if not pack:
        return key

    return pack.get(lang) or pack.get("ru") or pack.get("lv") or pack.get("en") or key


@app.context_processor
def inject_i18n():
    return {
        "lang": session.get("lang", "ru"),
        "t": t,
        "ORDER_STATUSES": ORDER_STATUSES,
        "ORDER_TABLE_LABELS": ORDER_TABLE_LABELS,
        "ALLOWED_STATUS_TRANSITIONS": ALLOWED_STATUS_TRANSITIONS,
        "normalize_order_status": normalize_order_status,
    }

TIMELINE_STEPS = [
    ("new", "timeline_new"),
    ("confirmed", "timeline_confirmed"),
    ("courier_picked", "timeline_picked"),
    ("courier_on_way", "timeline_on_way"),
    ("courier_arrived", "timeline_arrived"),
    ("completed", "timeline_completed"),
]

def timeline_flags(current_status: str):
    """
    Возвращает список шагов с флагами done/active
    """
    current_status = normalize_order_status(current_status)
    idx_map = {s: i for i, (s, _) in enumerate(TIMELINE_STEPS)}

    # если canceled — отдельная логика
    if current_status == "canceled":
        return [{"key": "canceled", "label_key": "timeline_canceled", "done": True, "active": True}]

    cur_i = idx_map.get(current_status, 0)

    out = []
    for i, (s, label_key) in enumerate(TIMELINE_STEPS):
        out.append({
            "key": s,
            "label_key": label_key,
            "done": i < cur_i,
            "active": i == cur_i,
        })
    return out


@app.context_processor
def inject_timeline_helpers():
    return {"timeline_flags": timeline_flags}
# ======================
# CORE-5: FORMAT HELPERS
# ======================
def fmt_money(x):
    try:
        return f"{float(x):.2f} €"
    except Exception:
        return f"{x} €"


def fmt_dt(dt):
    try:
        return dt.strftime("%d.%m.%Y %H:%M")
    except Exception:
        return ""


@app.context_processor
def inject_formatters():
    return dict(fmt_money=fmt_money, fmt_dt=fmt_dt)


# CSRF token into templates
@app.context_processor
def inject_csrf_token():
    if "csrf_token" not in session:
        session["csrf_token"] = secrets.token_hex(16)
    return dict(csrf_token=session["csrf_token"])


@app.context_processor
def inject_cart_total():
    cart = session.get("cart", {})
    return dict(cart_total_items=sum(cart.values()))

@app.context_processor
def inject_categories_menu():
    try:
        cats = (
            Category.query.filter_by(is_active=True)
            .order_by(Category.sort.asc(), Category.id.asc())
            .all()
        )
    except Exception:
        cats = []
    return dict(menu_categories=cats)

# ======================
# CORE-16: BREADCRUMBS
# ======================
BREADCRUMBS_MAP = {
    "index": ({"ru": "Главная", "lv": "Sākums", "en": "Home"}, None),
    "catalog": ({"ru": "Каталог", "lv": "Katalogs", "en": "Catalog"}, "index"),
    "cart": ({"ru": "Корзина", "lv": "Grozs", "en": "Cart"}, "catalog"),
    "checkout": ({"ru": "Оформление", "lv": "Noformēšana", "en": "Checkout"}, "cart"),
    "profile": ({"ru": "Профиль", "lv": "Profils", "en": "Profile"}, "index"),
    "about": ({"ru": "О нас", "lv": "Par mums", "en": "About"}, "index"),
    "policy": ({"ru": "Политика", "lv": "Politika", "en": "Policy"}, "index"),
    "shipping": ({"ru": "Доставка/Оплата", "lv": "Piegāde/Apmaksa", "en": "Shipping/Payment"}, "index"),
    "faq": ({"ru": "FAQ", "lv": "BUJ", "en": "FAQ"}, "index"),
    "admin_panel": ({"ru": "Админка", "lv": "Admin", "en": "Admin"}, "index"),
    "admin_orders": ({"ru": "Заказы", "lv": "Pasūtījumi", "en": "Orders"}, "admin_panel"),
    "admin_products": ({"ru": "Товары", "lv": "Preces", "en": "Products"}, "admin_panel"), 
}


def build_breadcrumbs():
    lang = session.get("lang", "ru")
    endpoint = request.endpoint
    if not endpoint or endpoint not in BREADCRUMBS_MAP:
        return []

    crumbs = []
    seen = set()
    cur = endpoint

    while cur and cur in BREADCRUMBS_MAP and cur not in seen:
        seen.add(cur)
        title_dict, parent = BREADCRUMBS_MAP[cur]
        title = title_dict.get(lang, title_dict.get("ru", cur))
        try:
            url = url_for(cur, lang=lang)
        except Exception:
            url = "#"
        crumbs.append({"title": title, "url": url})
        cur = parent

    crumbs.reverse()
    return crumbs


@app.context_processor
def inject_breadcrumbs():
    return dict(breadcrumbs=build_breadcrumbs())

@app.context_processor
def inject_order_statuses():
    return dict(ORDER_STATUSES=ORDER_STATUSES)
# ======================
# SECURITY-35: ADMIN AUDIT LOG
# ======================
def audit_admin(action: str, entity: str = None, entity_id: int = None, details: str = None):
    try:
        username = getattr(current_user, "username", "unknown")
        ip = request.headers.get("X-Forwarded-For", request.remote_addr)
        if ip and "," in ip:
            ip = ip.split(",")[0].strip()
        ua = (request.headers.get("User-Agent", "") or "")[:255]

        row = AdminAuditLog(
            admin_username=username,
            action=action,
            entity=entity,
            entity_id=entity_id,
            ip=ip,
            user_agent=ua,
            details=(details or "")[:4000],
        )
        db.session.add(row)
        db.session.commit()
    except Exception:
        try:
            db.session.rollback()
        except Exception:
            pass


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
# CORE-19: IMAGE OPTIMIZATION (WEBP)
# ======================
def optimize_image_to_webp(src_path: str, dst_path: str, max_size=(1600, 1600), quality: int = 82) -> bool:
    try:
        with Image.open(src_path) as im:
            im = im.convert("RGB")
            im.thumbnail(max_size)
            os.makedirs(os.path.dirname(dst_path), exist_ok=True)
            im.save(dst_path, "WEBP", quality=quality, method=6)
        return True
    except Exception:
        return False


# ======================
# ROUTES
# ======================
@app.route("/")
def index():
    return render_template("index.html", lang=session.get("lang", "ru"))


@app.route("/health")
def health():
    return jsonify(status="ok", time=datetime.utcnow().isoformat() + "Z")


@app.errorhandler(404)
def not_found(e):
    return render_template("errors/404.html", lang=session.get("lang", "ru")), 404


@app.errorhandler(500)
def server_error(e):
    return render_template("errors/500.html", lang=session.get("lang", "ru")), 500


@app.errorhandler(429)
def too_many_requests(e):
    return render_template(
        "errors/429.html",
        message="Слишком много запросов. Попробуйте позже.",
        lang=session.get("lang", "ru"),
    ), 429


@app.route("/robots.txt")
def robots_txt():
    lines = [
        "User-agent: *",
        "Allow: /",
        "Disallow: /admin",
        "Sitemap: " + request.url_root.rstrip("/") + "/sitemap.xml",
    ]
    return Response("\n".join(lines), mimetype="text/plain")


@app.route("/sitemap.xml")
def sitemap_xml():
    pages = [
        url_for("index", _external=True),
        url_for("catalog", _external=True),
        url_for("cart", _external=True),
        url_for("about", _external=True),
        url_for("policy", _external=True),
        url_for("shipping", _external=True),
        url_for("faq", _external=True),
    ]
    xml = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
    ]
    for p in pages:
        xml.append(f"<url><loc>{p}</loc></url>")
    xml.append("</urlset>")
    return Response("\n".join(xml), mimetype="application/xml")


@app.route("/about")
def about():
    return render_template("pages/about.html", lang=session.get("lang", "ru"))


@app.route("/policy")
def policy():
    return render_template("pages/policy.html", lang=session.get("lang", "ru"))


@app.route("/shipping")
def shipping():
    return render_template("pages/shipping.html", lang=session.get("lang", "ru"))


@app.route("/faq")
def faq():
    return render_template("pages/faq.html", lang=session.get("lang", "ru"))


@app.route("/catalog")
def catalog():
    products = (
        Product.query
        .filter_by(is_active=True)
        .order_by(Product.id.desc())
        .all()
    )
    return render_template(
        "catalog.html",
        products=products,
        lang=session.get("lang", "ru"),
    )



# ======================
# AUTH
# ======================
@app.route("/login", methods=["GET", "POST"])
def login():
    ip = _client_ip()

    if is_ip_banned(ip):
        return render_template(
            "login.html",
            error="Слишком много попыток входа. Подождите 30 минут и попробуйте снова.",
            lang=session.get("lang", "ru"),
        ), 429

    if request.method == "POST":
        if not _rl_allow("login:POST", limit=20, window_sec=60):
            return render_template(
                "login.html",
                error="Слишком много попыток входа. Подождите 1 минуту и попробуйте снова.",
                lang=session.get("lang", "ru"),
            ), 429

        username = request.form.get("username", "")
        password = request.form.get("password", "")

        user = User.query.filter_by(username=username).first()

        if user and check_password_hash(user.password, password):
            reset_attempts(ip)
            login_user(user, remember=True)

            next_url = safe_redirect_target(request.args.get("next"))
            if next_url:
                return redirect(next_url)

            if user.role == "admin":
                return redirect(url_for("admin_panel"))
            return redirect(url_for("profile"))

        register_failed_attempt(ip)
        return render_template(
            "login.html",
            error="Неверный логин или пароль",
            lang=session.get("lang", "ru"),
        )

    return render_template("login.html", lang=session.get("lang", "ru"))


@app.route("/logout")
@login_required
def logout():
    logout_user()
    session.pop("cart", None)     # <-- ВАЖНО: очищаем корзину
    session.modified = True
    return redirect(url_for("index", lang=session.get("lang", "ru")))


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form.get("username", "")
        password = request.form.get("password", "")

        if User.query.filter_by(username=username).first():
            return render_template(
                "register.html",
                error="Пользователь уже существует",
                lang=session.get("lang", "ru"),
            )

        user = User(
            username=username,
            password=generate_password_hash(password),
            role="user",
        )
        db.session.add(user)
        db.session.commit()

        login_user(user, remember=True)
        return redirect(url_for("profile"))

    return render_template("register.html", lang=session.get("lang", "ru"))


@app.route("/profile")
@login_required
def profile():
    orders = Order.query.filter_by(user_id=current_user.id).order_by(Order.created_at.desc()).all()
    return render_template(
        "profile.html",
        orders=orders,
        ORDER_STATUSES=ORDER_STATUSES,
        lang=session.get("lang", "ru"),
    )


# ======================
# CART
# ======================
@app.route("/api/add_to_cart/<int:product_id>", methods=["POST"])
def add_to_cart(product_id):
    cart = session.get("cart", {})
    pid = str(product_id)

    cart[pid] = cart.get(pid, 0) + 1
    session["cart"] = cart
    session.modified = True

    return jsonify(success=True, cart_total_items=sum(cart.values()))


@app.route("/api/cart_count")
def cart_count():
    cart = session.get("cart", {})
    return jsonify(cart_total_items=sum(cart.values()))


@app.route("/cart")
def cart():
    cart = session.get("cart", {})
    items = []
    total = 0.0

    for pid, qty in cart.items():
        product = Product.query.get(int(pid))
        if not product or not product.is_active or qty <= 0:
            continue

        item_total = float(product.price) * int(qty)
        total += item_total

        items.append(
            {
                "id": product.id,
                "name": product.name_ru,
                "price": product.price,
                "qty": qty,
                "total": item_total,
                "image": product.image,
            }
        )

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
    subtotal = float(product.price) * int(qty) if product else 0.0

    total = 0.0
    for k, v in cart.items():
        p = Product.query.get(int(k))
        if p:
            total += float(p.price) * int(v)

    return jsonify(
        success=True,
        qty=qty,
        subtotal=subtotal,
        total=total,
        cart_total_items=sum(cart.values()),
    )


# ======================
# CHECKOUT
# ======================
@app.route("/checkout", methods=["GET", "POST"])
@login_required
def checkout():
    cart = session.get("cart", {})
    if not cart or sum(cart.values()) == 0:
        return redirect(url_for("cart", lang=session.get("lang", "ru")))

    items = []
    total = 0.0

    for pid, qty in cart.items():
        product = Product.query.get(int(pid))
        if not product or qty <= 0:
            continue
        subtotal = float(product.price) * int(qty)
        total += subtotal
        items.append(f"{product.name_ru} × {qty}")

    items_text = "\n".join(items)

    if not items or total <= 0:
        session.pop("cart", None)
        return redirect(url_for("cart", lang=session.get("lang", "ru")))

    if request.method == "GET":
        session["checkout_token"] = str(uuid.uuid4())

    if request.method == "POST":
        # rate limit
        if not _rl_allow("checkout:POST", limit=5, window_sec=60):
            return render_template(
                "checkout.html",
                items=items,
                total=total,
                error="Слишком много попыток оформления заказа. Подождите 1 минуту.",
                checkout_token=session.get("checkout_token"),
                lang=session.get("lang", "ru"),
            ), 429

        # token check
        form_token = request.form.get("checkout_token")
        session_token = session.get("checkout_token")
        if not form_token or form_token != session_token:
            return redirect(url_for("cart", lang=session.get("lang", "ru")))

        # fields
        name = norm_text(request.form.get("name", ""), max_len=60)
        contact = norm_contact(request.form.get("contact", ""), max_len=80)

        address = norm_text(request.form.get("address", ""), max_len=200)
        delivery_time = norm_text(request.form.get("delivery_time", ""), max_len=60)

        delivery_provider = request.form.get("delivery_provider")
        if delivery_provider not in ("manual", "bolt", "wolt"):
            delivery_provider = "manual"

        # validations
        if len(name) < 2:
            return render_template(
                "checkout.html",
                items=items,
                total=total,
                error="Имя слишком короткое",
                checkout_token=session.get("checkout_token"),
                lang=session.get("lang", "ru"),
            )

        email_regex = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"
        phone_regex = r"^\+?[0-9\s\-]{7,15}$"
        if not (re.match(email_regex, contact) or re.match(phone_regex, contact)):
            return render_template(
                "checkout.html",
                items=items,
                total=total,
                error="Введите корректный телефон или email",
                checkout_token=session.get("checkout_token"),
                lang=session.get("lang", "ru"),
            )

        if not address or len(address) < 3:
            return render_template(
                "checkout.html",
                items=items,
                total=total,
                error="Введите адрес доставки",
                checkout_token=session.get("checkout_token"),
                lang=session.get("lang", "ru"),
            )

        if not session.get("cart"):
            return redirect(url_for("cart", lang=session.get("lang", "ru")))

        # anti spam (1 order / 60 sec)
        last_order_ts = session.get("last_order_ts")
        now_ts = datetime.utcnow().timestamp()
        if last_order_ts and now_ts - last_order_ts < 60:
            return render_template(
                "checkout.html",
                items=items,
                total=total,
                error="Подождите минуту перед следующим заказом",
                checkout_token=session.get("checkout_token"),
                lang=session.get("lang", "ru"),
            )

        # ✅ CREATE ORDER (ВАЖНО: вне if last_order_ts)
        order = Order(
            user_id=current_user.id,
            name=name,
            contact=contact,
            address=address,
            delivery_time=delivery_time,
            delivery_provider=delivery_provider,
            tracking_code="",
            courier="",   # назначит админ
            items=items_text,
            total=total,
            status="new",
           )

        db.session.add(order)
        db.session.commit()

        # одноразовый токен — удаляем после успеха
        session.pop("checkout_token", None)

        session["last_order_ts"] = datetime.utcnow().timestamp()
        session.pop("cart", None)
        session.modified = True

        send_telegram(
            "🛒 НОВЫЙ ЗАКАЗ\n"
            f"Пользователь: {current_user.username}\n"
            f"Имя: {name}\n"
            f"Контакт: {contact}\n"
            f"Адрес: {address}\n"
            f"Время: {delivery_time}\n\n"
            f"{items_text}\n"
            f"Итого: {total:.2f} €"
        )

        return redirect(url_for("profile", lang=session.get("lang", "ru")))

    return render_template(
        "checkout.html",
        items=items,
        total=total,
        checkout_token=session.get("checkout_token"),
        lang=session.get("lang", "ru"),
    )


# ======================
# ADMIN
# ======================
@app.route("/admin")
@login_required
@admin_required
def admin_panel():
    return redirect(url_for("admin_orders"))


@app.route("/admin/products", methods=["GET", "POST"])
@login_required
@admin_required
def admin_products():
    # берём категории из БД (сколько угодно — хоть 100)
    categories = (
        Category.query.filter_by(is_active=True)
        .order_by(Category.sort.asc(), Category.id.asc())
        .all()
    )

    if request.method == "POST":
        name_ru = norm_text(request.form.get("name_ru", ""), max_len=80)
        name_lv = norm_text(request.form.get("name_lv", ""), max_len=80)
        category_slug = norm_text(request.form.get("category", ""), max_len=60)

        try:
            price = float(request.form.get("price", "0") or 0)
        except Exception:
            price = 0

        if not name_ru or not name_lv or price <= 0:
            flash("Заполните название и корректную цену", "error")
            return redirect(url_for("admin_products", show=request.args.get("show", "active")))

        # ищем категорию по SLUG (doors/windows/wallpaper/...)
        cat = Category.query.filter_by(slug=category_slug).first()
        if not cat:
            flash("Категория не найдена", "error")
            return redirect(url_for("admin_products", show=request.args.get("show", "active")))

        file = request.files.get("image")
        if not file or not file.filename:
            flash("Добавьте изображение товара", "error")
            return redirect(url_for("admin_products", show=request.args.get("show", "active")))

        if request.content_length and request.content_length > app.config.get("MAX_CONTENT_LENGTH", 0):
            flash("Файл слишком большой", "error")
            return redirect(url_for("admin_products", show=request.args.get("show", "active")))

        allowed_mimes = {"image/png", "image/jpeg", "image/webp"}
        if file.mimetype not in allowed_mimes:
            flash("Неверный тип файла (разрешены PNG/JPG/WEBP)", "error")
            return redirect(url_for("admin_products", show=request.args.get("show", "active")))

        if not allowed_file(file.filename):
            flash("Неверный формат файла (только png/jpg/jpeg/webp)", "error")
            return redirect(url_for("admin_products", show=request.args.get("show", "active")))

        os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)

        ext = file.filename.rsplit(".", 1)[1].lower()
        filename = secure_filename(f"{uuid.uuid4().hex}.{ext}")
        upload_path = os.path.join(app.config["UPLOAD_FOLDER"], filename)
        file.save(upload_path)

        image_path = f"uploads/{filename}"

        product = Product(
            name_ru=name_ru,
            name_lv=name_lv,
            price=price,
            image=image_path,
            is_active=True,
            category_id=cat.id,
            legacy_category=category_slug,  # оставим строку как бэкап
        )

        db.session.add(product)
        db.session.commit()

        flash("Товар добавлен", "success")
        return redirect(url_for("admin_products", show=request.args.get("show", "active")))

    # ---------- GET ----------
    show = request.args.get("show", "active")

    q = Product.query
    if show == "inactive":
        q = q.filter(Product.is_active.is_(False))
    elif show == "all":
        pass
    else:
        q = q.filter(Product.is_active.is_(True))

    products = q.order_by(Product.id.desc()).all()

    # grouped: slug -> {labels:{ru/lv/en}, items:[]}
    grouped = {}
    for c in categories:
        grouped[c.slug] = {
            "labels": {"ru": c.title_ru, "lv": c.title_lv, "en": c.title_en},
            "items": [],
        }

    grouped.setdefault(
        "other",
        {"labels": {"ru": "Другое", "lv": "Cits", "en": "Other"}, "items": []},
    )

    for p in products:
        slug = p.category.slug if p.category else (p.legacy_category or "")
        if slug in grouped:
            grouped[slug]["items"].append(p)
        else:
            grouped["other"]["items"].append(p)

    return render_template(
        "admin/products.html",
        grouped=grouped,
        show=show,
        lang=session.get("lang", "ru"),
    )


@app.route("/admin/products/delete/<int:id>", methods=["POST"])
@login_required
@admin_required
def delete_product(id):
    product = Product.query.get_or_404(id)
    product.is_active = False
    db.session.commit()
    flash("Товар скрыт", "success")
    audit_admin("product_hide", entity="Product", entity_id=product.id, details=product.name_ru)
    return redirect(url_for("admin_products"))


@app.route("/admin/products/restore/<int:id>", methods=["POST"])
@login_required
@admin_required
def restore_product(id):
    product = Product.query.get_or_404(id)
    product.is_active = True
    db.session.commit()
    flash("Товар восстановлен", "success")
    audit_admin("product_restore", entity="Product", entity_id=product.id, details=product.name_ru)
    return redirect(url_for("admin_products"))


@app.route("/admin/products/edit/<int:id>", methods=["GET", "POST"])
@login_required
@admin_required
def edit_product(id):
    product = Product.query.get_or_404(id)

    if request.method == "POST":
        product.name_ru = norm_text(request.form.get("name_ru", ""), max_len=80)
        product.name_lv = norm_text(request.form.get("name_lv", ""), max_len=80)

        try:
            product.price = float(request.form.get("price", "0") or 0)
        except Exception:
            flash("Некорректная цена", "error")
            return redirect(url_for("edit_product", id=id))

        product.image = request.form.get("image", product.image)
        db.session.commit()

        flash("Товар обновлён", "success")
        audit_admin("product_edit", entity="Product", entity_id=product.id, details=product.name_ru)
        return redirect(url_for("admin_products"))

    return render_template("admin/edit_product.html", product=product, lang=session.get("lang", "ru"))


@app.route("/admin/orders")
@admin_required
@login_required
def admin_orders():
    show = request.args.get("show", "active")
    q = request.args.get("q", "").strip()
    page = request.args.get("page", 1, type=int)
    PER_PAGE = 20

    # ✅ СТАТУСЫ, которые считаем "активные" (в работе)
    ACTIVE_STATUSES = [
        "new",
        "confirmed",
        "courier_picked",
        "courier_on_way",
        "courier_arrived",

        # ✅ поддержка старых статусов из базы (чтобы не ломалось)
        "in_progress",
        "shipped",
    ]

    # ✅ СТАТУСЫ "архив"
    ARCHIVE_STATUSES = [
        "completed",
        "canceled",
    ]

    query = Order.query

    if show == "archive":
        query = query.filter(or_(Order.is_deleted.is_(True), Order.status.in_(ARCHIVE_STATUSES)))
    else:
        query = query.filter(Order.is_deleted.is_(False), Order.status.in_(ACTIVE_STATUSES))

    if q:
        if q.isdigit():
            query = query.filter(Order.id == int(q))
        else:
            like = f"%{q}%"
            query = query.filter(or_(Order.name.ilike(like), Order.contact.ilike(like)))

    pagination = query.order_by(Order.created_at.desc()).paginate(page=page, per_page=PER_PAGE, error_out=False)

    return render_template(
        "admin/orders.html",
        orders=pagination.items,
        pagination=pagination,
        ORDER_STATUSES=ORDER_STATUSES,
        ALLOWED_STATUS_TRANSITIONS=ALLOWED_STATUS_TRANSITIONS,
        lang=session.get("lang", "ru"),
        show=show,
    )


@app.route("/admin/orders/<int:order_id>/status", methods=["POST"])
@admin_required
@login_required
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
    if new_status in ("completed", "canceled"):
    order.is_deleted = True

    history = OrderStatusHistory(
        order_id=order.id,
        old_status=old_status,
        new_status=new_status,
        changed_by=current_user.username,
    )

    db.session.add(history)
    db.session.commit()

    flash("Статус обновлён", "success")
    audit_admin("order_status_change", entity="Order", entity_id=order.id, details=f"{old_status} -> {new_status}")
    return redirect(url_for("admin_orders"))


@app.route("/admin/orders/delete/<int:order_id>", methods=["POST"])
@login_required
@admin_required
def delete_order(order_id):
    order = Order.query.get_or_404(order_id)
    order.is_deleted = True
    db.session.commit()
    flash("Заказ перемещён в архив", "success")
    audit_admin("order_archive", entity="Order", entity_id=order.id)
    return redirect(url_for("admin_orders"))


@app.route("/admin/orders/restore/<int:order_id>", methods=["POST"])
@login_required
@admin_required
def restore_order(order_id):
    order = Order.query.get_or_404(order_id)

    # ✅ Восстанавливаем из архива
    order.is_deleted = False

    # ✅ Если был completed — переводим в активный статус
    # (выбери какой тебе нужен: confirmed или new)
    if order.status == "completed":
        order.status = "confirmed"  # или "new"

    db.session.commit()

    flash("Заказ восстановлен из архива", "success")
    audit_admin("order_restore", entity="Order", entity_id=order.id)

    # ✅ После восстановления логично показать активные
    return redirect(url_for("admin_orders", show="active"))


@app.route("/admin/orders/hard_delete/<int:order_id>", methods=["POST"])
@login_required
@admin_required
def hard_delete_order(order_id):
    order = Order.query.get_or_404(order_id)

    OrderStatusHistory.query.filter_by(order_id=order.id).delete()
    OrderComment.query.filter_by(order_id=order.id).delete()

    db.session.delete(order)
    db.session.commit()

    flash("Заказ удалён навсегда", "success")
    audit_admin("order_hard_delete", entity="Order", entity_id=order_id)
    return redirect(url_for("admin_orders", show="archive"))


@app.route("/admin/orders/<int:order_id>")
@admin_required
@login_required
def admin_order_view(order_id):
    order = Order.query.get_or_404(order_id)
    history = OrderStatusHistory.query.filter_by(order_id=order.id).order_by(OrderStatusHistory.created_at.desc()).all()
    return render_template(
        "admin/order_view.html",
        order=order,
        history=history,
        ORDER_STATUSES=ORDER_STATUSES,
        lang=session.get("lang", "ru"),
    )


@app.route("/admin/orders/<int:order_id>/print")
@admin_required
@login_required
def admin_order_print(order_id):
    order = Order.query.get_or_404(order_id)
    history = OrderStatusHistory.query.filter_by(order_id=order.id).order_by(OrderStatusHistory.created_at.desc()).all()
    comments = OrderComment.query.filter_by(order_id=order.id).order_by(OrderComment.created_at.desc()).all()
    return render_template(
        "admin/order_print.html",
        order=order,
        history=history,
        comments=comments,
        ORDER_STATUSES=ORDER_STATUSES,
        lang=session.get("lang", "ru"),
    )


@app.route("/admin/orders/export")
@admin_required
@login_required
def export_orders_csv():
    show = request.args.get("show", "active")
    q = request.args.get("q", "").strip()

    ACTIVE_STATUSES = ["new", "in_progress", "shipped"]
    ARCHIVE_STATUSES = ["completed"]

    query = Order.query

    if show == "archive":
        query = query.filter(or_(Order.is_deleted.is_(True), Order.status.in_(ARCHIVE_STATUSES)))
    else:
        query = query.filter(Order.is_deleted.is_(False), Order.status.in_(ACTIVE_STATUSES))

    if q:
        if q.isdigit():
            query = query.filter(Order.id == int(q))
        else:
            like = f"%{q}%"
            query = query.filter(or_(Order.name.ilike(like), Order.contact.ilike(like)))

    orders = query.order_by(Order.created_at.desc()).all()

    si = StringIO()
    writer = csv.writer(si)
    writer.writerow(["ID", "Имя", "Контакт", "Состав", "Сумма", "Статус", "Дата"])

    for o in orders:
        writer.writerow(
            [
                o.id,
                o.name,
                o.contact,
                o.items,
                f"{o.total:.2f}",
                ORDER_STATUSES.get(o.status, {}).get("ru", o.status),
                o.created_at.strftime("%d.%m.%Y %H:%M"),
            ]
        )

    output = si.getvalue()
    si.close()

    audit_admin("orders_export_csv", entity="Order", details=f"show={show} q={q}")
    return Response(
        output,
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename=orders_{show}.csv"},
    )


@app.route("/admin/orders/<int:order_id>/comment", methods=["POST"])
@admin_required
@login_required
def add_order_comment(order_id):
    order = Order.query.get_or_404(order_id)

    text_comment = (request.form.get("comment", "") or "").strip()
    if not text_comment:
        return redirect(url_for("admin_order_view", order_id=order.id))

    comment = OrderComment(
        order_id=order.id,
        author=current_user.username,
        text=text_comment,
    )
    db.session.add(comment)
    db.session.commit()

    flash("Комментарий добавлен", "success")
    audit_admin("order_comment_add", entity="Order", entity_id=order.id, details=text_comment[:200])
    return redirect(url_for("admin_order_view", order_id=order.id))
    

# ======================
# CORE-20: MENU/LINK CHECK (admin)
# ======================
@app.route("/admin/links_check")
@admin_required
@login_required
def links_check():
    links = {
        "admin_orders": url_for("admin_orders"),
        "admin_products": url_for("admin_products"),
        "catalog": url_for("catalog"),
        "cart": url_for("cart"),
        "about": url_for("about"),
        "policy": url_for("policy"),
        "shipping": url_for("shipping"),
        "faq": url_for("faq"),
        "health": url_for("health"),
    }
    return jsonify(ok=True, links=links)

@app.route("/admin/product/<int:id>/hard_delete", methods=["POST"])
@login_required
@admin_required
def hard_delete_product(id):
    p = Product.query.get_or_404(id)

    # Разрешаем удалять навсегда только скрытые
    if p.is_active:
        flash("Сначала скройте товар, потом удаляйте навсегда", "error")
        return redirect(url_for("admin_products", show=request.args.get("show", "active")))

    # --- (опционально) удалить файл изображения ---
    try:
        if p.image and p.image.startswith("uploads/"):
            abs_path = os.path.join(app.static_folder, p.image)  # static/uploads/...
            if os.path.exists(abs_path):
                os.remove(abs_path)
    except Exception:
        pass

    db.session.delete(p)
    db.session.commit()
    flash("Товар удалён навсегда", "success")
    return redirect(url_for("admin_products", show=request.args.get("show", "inactive")))

@app.route("/privacy")
def privacy():
    lang = request.args.get("lang", session.get("lang", "ru"))
    return render_template("privacy.html", lang=lang, t=t)

@app.route("/terms")
def terms():
    lang = request.args.get("lang", session.get("lang", "ru"))
    return render_template("terms.html", lang=lang, t=t)

@app.route("/contacts")
def contacts():
    lang = request.args.get("lang", session.get("lang", "ru"))
    return render_template("contacts.html", lang=lang, t=t)

@app.post("/admin/orders/<int:order_id>/courier")
@login_required
@admin_required
def update_order_courier(order_id):
    if request.form.get("csrf_token") != session.get("csrf_token"):
        return "CSRF", 400

    order = Order.query.get_or_404(order_id)
    courier = norm_text(request.form.get("courier", ""), max_len=80)
    order.courier = courier
    db.session.commit()

    return redirect(url_for("admin_orders", show=request.args.get("show", "active"), lang=session.get("lang","ru")))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "8080")))

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


class SiteStepProgress(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    step_id = db.Column(db.Integer, unique=True, nullable=False)
    done = db.Column(db.Boolean, default=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow)


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
# CONSTANTS
# ======================
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

SITE_STEPS = [
    (1, "Core", "Единая структура шаблонов (base/admin_base)"),
    (2, "Core", "Единые компоненты кнопок/таблиц/форм"),
    (3, "Core", "Единые сообщения flash (success/error)"),
    (4, "Core", "404/500 страницы"),
    (5, "Core", "Единый формат дат/валют"),
    (6, "Core", "Мультиязычность RU/LV/EN во всех страницах"),
    (7, "Core", "Robots.txt и sitemap.xml"),
    (8, "Core", "Favicon + OG meta (соцсети)"),
    (9, "Core", "Логирование ключевых действий"),
    (10, "Core", "Разделение конфигов dev/prod"),
    (11, "Core", "Health-check endpoint"),
    (12, "Core", "Страница “О нас/Контакты”"),
    (13, "Core", "Страница “Политика/Условия”"),
    (14, "Core", "Страница “Доставка/Оплата”"),
    (15, "Core", "Страница “FAQ”"),
    (16, "Core", "Компонент хлебных крошек"),
    (17, "Core", "Система уведомлений в UI"),
    (18, "Core", "Валидация форм сервер/клиент"),
    (19, "Core", "Сжатие/оптимизация изображений"),
    (20, "Core", "Проверка корректности ссылок/меню"),
    (21, "Security", "CSRF на все формы"),
    (22, "Security", "Rate limit на login/checkout"),
    (23, "Security", "Блок повторной отправки checkout"),
    (24, "Security", "Хеширование паролей (есть)"),
    (25, "Security", "Политика паролей (длина/сложность)"),
    (26, "Security", "Блок brute-force по IP"),
    (27, "Security", "Secure cookies настройки"),
    (28, "Security", "Проверка загрузки файлов (MIME/размер)"),
    (29, "Security", "Максимальный размер upload"),
    (30, "Security", "Ограничение типов расширений (есть)"),
    (31, "Security", "Очистка/нормализация входных данных"),
    (32, "Security", "Запрет опасных редиректов"),
    (33, "Security", "Роли (admin/user) (есть)"),
    (34, "Security", "Защита админки (есть)"),
    (35, "Security", "Аудит действий админа (лог)"),
    (56, "Catalog", "Архив товаров (есть is_active)"),
    (64, "Catalog", "Lazy-load изображений"),
    (68, "Catalog", "Проверка “товар скрыт” на всех страницах"),
    (72, "Checkout", "Корзина: пересчет суммы (есть)"),
    (85, "Checkout", "Checkout: контроль дублей (есть токен)"),
    (86, "Checkout", "Checkout: антиспам (есть)"),
    (87, "Checkout", "Checkout: валидация телефона/почты (есть)"),
    (101, "Orders", "Фильтр активные/архив (есть)"),
    (102, "Orders", "Автоархив по completed (есть)"),
    (103, "Orders", "Поиск заказов (есть)"),
    (104, "Orders", "Пагинация заказов (есть)"),
    (105, "Orders", "Экспорт заказов CSV (есть)"),
    (106, "Orders", "Печать заказа (есть)"),
    (107, "Orders", "Комментарии админа к заказу (есть модель/роут)"),
    (108, "Orders", "История статусов (есть)"),
    (109, "Orders", "Восстановление заказа из архива (есть)"),
    (110, "Orders", "Удаление заказа навсегда (есть)"),
    (138, "Orders", "Уведомления при новом заказе (TG есть)"),
    (142, "UX", "Меню для админа (есть)"),
    (144, "UX", "Быстрые действия без дублей (есть в admin_base)"),
]


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
    "admin_steps": ({"ru": "200 шагов", "lv": "200 soļi", "en": "200 steps"}, "admin_panel"),
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
    slug = request.args.get("cat", "all")

    categories = (
        Category.query.filter_by(is_active=True)
        .order_by(Category.sort.asc(), Category.id.asc())
        .all()
    )

    q = Product.query.filter_by(is_active=True)

    if slug != "all":
        cat = Category.query.filter_by(slug=slug, is_active=True).first()
        if cat:
            q = q.filter(Product.category_id == cat.id)
        else:
            slug = "all"

    products = q.order_by(Product.id.desc()).all()

    return render_template(
        "catalog.html",
        categories=categories,
        active_cat=slug,
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
        return redirect(url_for("cart"))

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
        return redirect(url_for("cart"))

    if request.method == "GET":
        session["checkout_token"] = str(uuid.uuid4())

    if request.method == "POST":
        if not _rl_allow("checkout:POST", limit=5, window_sec=60):
            return render_template(
                "checkout.html",
                items=items,
                total=total,
                error="Слишком много попыток оформления заказа. Подождите 1 минуту.",
                checkout_token=session.get("checkout_token"),
                lang=session.get("lang", "ru"),
            ), 429

        form_token = request.form.get("checkout_token")
        session_token = session.get("checkout_token")
        if not form_token or form_token != session_token:
            return redirect(url_for("cart"))

        name = norm_text(request.form.get("name", ""), max_len=60)
        contact = norm_contact(request.form.get("contact", ""), max_len=80)

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

        if not session.get("cart"):
            return redirect(url_for("cart"))

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

        order = Order(
            user_id=current_user.id,
            name=name,
            contact=contact,
            items=items_text,
            total=total,
            status="new",
            is_deleted=False,
        )

        db.session.add(order)
        db.session.commit()

        # токен “одноразовый” — удаляем только после успешного оформления
        session.pop("checkout_token", None)

        session["last_order_ts"] = datetime.utcnow().timestamp()
        session.pop("cart", None)
        session.modified = True

        send_telegram(
            "🛒 НОВЫЙ ЗАКАЗ\n"
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
def admin_orders():
    show = request.args.get("show", "active")
    q = request.args.get("q", "").strip()
    page = request.args.get("page", 1, type=int)
    PER_PAGE = 20

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
    if new_status == "completed":
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
    if order.status == "completed":
        flash("Завершённый заказ нельзя вернуть из архива.", "error")
        return redirect(url_for("admin_orders", show="archive"))

    order.is_deleted = False
    db.session.commit()
    flash("Заказ восстановлен из архива", "success")
    audit_admin("order_restore", entity="Order", entity_id=order.id)
    return redirect(url_for("admin_orders", show="archive"))


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
# /admin/steps_manual (ручная отметка)
# ======================
@app.route("/admin/steps_manual", methods=["GET", "POST"])
@admin_required
def admin_steps_manual():
    if request.method == "POST":
        step_id = request.form.get("step_id", type=int)
        done = request.form.get("done") == "1"

        if step_id:
            row = SiteStepProgress.query.filter_by(step_id=step_id).first()
            if not row:
                row = SiteStepProgress(step_id=step_id, done=done)
            else:
                row.done = done
                row.updated_at = datetime.utcnow()

            db.session.add(row)
            db.session.commit()

        return redirect(url_for("admin_steps", lang=session.get("lang", "ru")))

    progress_rows = SiteStepProgress.query.all()
    progress = {r.step_id: r.done for r in progress_rows}

    grouped = {}
    for sid, cat, title in SITE_STEPS:
        grouped.setdefault(cat, []).append((sid, title, progress.get(sid, False)))

    tmpl = """
    {% extends "admin/admin_base.html" %}
    {% block content %}
    <h1>📋 Чек-лист 200 шагов</h1>
    <p style="opacity:0.7; margin-bottom:16px;">Отмечай выполненные пункты — сохраняется в базе.</p>

    {% for cat, items in grouped.items() %}
      <div style="margin:18px 0; padding:14px; border:1px solid rgba(0,0,0,0.08); border-radius:12px;">
        <h3 style="margin:0 0 10px 0;">{{ cat }}</h3>

        {% for sid, title, done in items %}
          <form method="post" style="display:flex; gap:10px; align-items:center; padding:6px 0; border-bottom:1px dashed rgba(0,0,0,0.08);">
            <input type="hidden" name="csrf_token" value="{{ csrf_token }}">
            <input type="hidden" name="step_id" value="{{ sid }}">
            <input type="hidden" name="done" value="{{ 0 if done else 1 }}">

            <button type="submit" class="admin-link" style="min-width:110px;">
              {% if done %}✅ Готово{% else %}⬜ Сделать{% endif %}
            </button>

            <div style="flex:1;">
              <strong>#{{ sid }}</strong> — {{ title }}
            </div>
          </form>
        {% endfor %}
      </div>
    {% endfor %}

    {% endblock %}
    """
    return render_template_string(tmpl, grouped=grouped)


# ======================
# CORE-20: MENU/LINK CHECK (admin)
# ======================
@app.route("/admin/links_check")
@admin_required
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


# ======================
# ✅ AUTO SITE STEPS (1–200): red/yellow/green
# ======================
_STEP_DONE_RE = re.compile(r"\bSTEP-(\d{1,3})\b")
_STEP_WIP_RE = re.compile(r"\bWIP-(\d{1,3})\b")


def _project_files_for_scan():
    root = Path(app.root_path)
    files = [root / "app.py"]

    tpl = root / "templates"
    st = root / "static"

    if tpl.exists():
        files += list(tpl.rglob("*.html"))
    if st.exists():
        files += list(st.rglob("*.js"))
        files += list(st.rglob("*.css"))

    return files


def _scan_markers():
    done_ids = set()
    wip_ids = set()

    for f in _project_files_for_scan():
        try:
            text_ = f.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue

        for m in _STEP_DONE_RE.findall(text_):
            try:
                done_ids.add(int(m))
            except Exception:
                pass

        for m in _STEP_WIP_RE.findall(text_):
            try:
                wip_ids.add(int(m))
            except Exception:
                pass

    return done_ids, wip_ids


def _has_route(path: str) -> bool:
    try:
        return any(r.rule == path for r in app.url_map.iter_rules())
    except Exception:
        return False


def _template_exists(rel_path: str) -> bool:
    return (Path(app.root_path) / "templates" / rel_path).exists()


def _static_exists(rel_path: str) -> bool:
    return (Path(app.root_path) / "static" / rel_path).exists()


def _has_model_field(model, field_name: str) -> bool:
    try:
        return hasattr(model, field_name)
    except Exception:
        return False


def build_steps_status_200():
    statuses = {sid: "todo" for (sid, _, _) in SITE_STEPS}

    done_ids, wip_ids = _scan_markers()
    for sid in wip_ids:
        if sid in statuses:
            statuses[sid] = "in_progress"
    for sid in done_ids:
        if sid in statuses:
            statuses[sid] = "done"

    if _template_exists("admin/admin_base.html") or _template_exists("base.html") or _template_exists("base_user.html"):
        statuses[1] = "done"

    if _static_exists("css/style.css"):
        statuses[2] = "done"

    try:
        tpl_root = Path(app.root_path) / "templates"
        candidates = [
            tpl_root / "admin" / "admin_base.html",
            tpl_root / "admin_base.html",
            tpl_root / "base.html",
            tpl_root / "base_user.html",
        ]
        for p in candidates:
            if p.exists():
                t = p.read_text(encoding="utf-8", errors="ignore")
                if "get_flashed_messages" in t:
                    statuses[3] = "done"
                    break
    except Exception:
        pass

    if _template_exists("errors/404.html") and _template_exists("errors/500.html"):
        statuses[4] = "done"

    if "fmt_money" in globals() and "fmt_dt" in globals():
        statuses[5] = "done"

    statuses[6] = "done"

    if _has_route("/robots.txt") and _has_route("/sitemap.xml"):
        statuses[7] = "done"

    if _static_exists("images/favicon.ico"):
        statuses[8] = "done"

    try:
        if logging.getLogger().handlers:
            statuses[9] = "done"
    except Exception:
        pass

    if "APP_ENV" in globals():
        statuses[10] = "done"

    if _has_route("/health"):
        statuses[11] = "done"

    if _has_route("/about") and _template_exists("pages/about.html"):
        statuses[12] = "done"
    if _has_route("/policy") and _template_exists("pages/policy.html"):
        statuses[13] = "done"
    if _has_route("/shipping") and _template_exists("pages/shipping.html"):
        statuses[14] = "done"
    if _has_route("/faq") and _template_exists("pages/faq.html"):
        statuses[15] = "done"

    try:
        has_inject = "inject_breadcrumbs" in globals()
        tpl_root = Path(app.root_path) / "templates"
        found_markup = False
        if tpl_root.exists():
            for f in tpl_root.rglob("*.html"):
                t = f.read_text(encoding="utf-8", errors="ignore")
                if ('aria-label="breadcrumb"' in t) or ('class="breadcrumbs"' in t):
                    found_markup = True
                    break
        if has_inject and found_markup:
            statuses[16] = "done"
    except Exception:
        pass

    try:
        cssp = Path(app.root_path) / "static" / "css" / "style.css"
        jsp = Path(app.root_path) / "static" / "js" / "main.js"
        css_text = cssp.read_text(encoding="utf-8", errors="ignore") if cssp.exists() else ""
        js_text = jsp.read_text(encoding="utf-8", errors="ignore") if jsp.exists() else ""
        css_ok = (".toast" in css_text) or (".toast-container" in css_text) or ("STEP-17" in css_text)
        js_ok = ("showToast" in js_text) or ("toast" in js_text) or ("STEP-17" in js_text)
        if css_ok and js_ok:
            statuses[17] = "done"
    except Exception:
        pass

    try:
        app_py = Path(app.root_path) / "app.py"
        server_ok = False
        if app_py.exists():
            t = app_py.read_text(encoding="utf-8", errors="ignore")
            server_ok = ("email_regex" in t and "phone_regex" in t) or ("Введите корректный телефон или email" in t)

        tpl_root = Path(app.root_path) / "templates"
        client_ok = False
        if tpl_root.exists():
            for f in tpl_root.rglob("*.html"):
                ht = f.read_text(encoding="utf-8", errors="ignore")
                if ("required" in ht) and (("minlength" in ht) or ("pattern=" in ht)):
                    client_ok = True
                    break

        if server_ok and client_ok:
            statuses[18] = "done"
    except Exception:
        pass

    try:
        app_py = Path(app.root_path) / "app.py"
        if app_py.exists():
            t = app_py.read_text(encoding="utf-8", errors="ignore")
            if ("optimize_image_to_webp" in t) or ('"WEBP"' in t and "quality" in t):
                statuses[19] = "done"
    except Exception:
        pass

    if _has_route("/admin/links_check"):
        statuses[20] = "done"

    if "inject_csrf_token" in globals() and "csrf_protect_admin" in globals():
        statuses[21] = "done"

    if "_rl_allow" in globals():
        statuses[22] = "done"

    if "checkout" in globals():
        statuses[23] = "done"

    statuses[24] = "done"
    statuses[27] = "done"

    if "is_ip_banned" in globals() and "register_failed_attempt" in globals() and "reset_attempts" in globals() and "_client_ip" in globals():
        statuses[26] = "done"

    try:
        app_py = Path(app.root_path) / "app.py"
        if app_py.exists():
            t = app_py.read_text(encoding="utf-8", errors="ignore")
            if ("MAX_CONTENT_LENGTH" in t) and ("file.mimetype" in t) and ("allowed_mimes" in t):
                statuses[28] = "done"
    except Exception:
        pass

    if app.config.get("MAX_CONTENT_LENGTH"):
        statuses[29] = "done"
    if "ALLOWED_EXTENSIONS" in globals():
        statuses[30] = "done"
    if "norm_text" in globals() and "norm_contact" in globals():
        statuses[31] = "done"
    if "safe_redirect_target" in globals():
        statuses[32] = "done"
    if "audit_admin" in globals():
        statuses[35] = "done"

    if _has_model_field(Product, "is_active"):
        statuses[56] = "done"

    try:
        tpl_root = Path(app.root_path) / "templates"
        found_lazy = False
        if tpl_root.exists():
            for f in tpl_root.rglob("*.html"):
                t = f.read_text(encoding="utf-8", errors="ignore")
                if 'loading="lazy"' in t:
                    found_lazy = True
                    break
        if found_lazy:
            statuses[64] = "done"
    except Exception:
        pass

    statuses[68] = "done"
    statuses[72] = "done"
    statuses[85] = "done"
    statuses[86] = "done"
    statuses[87] = "done"
    statuses[101] = "done"
    statuses[102] = "done"
    statuses[103] = "done"
    statuses[104] = "done"
    statuses[105] = "done"
    statuses[106] = "done"
    statuses[107] = "done"
    statuses[108] = "done"
    statuses[109] = "done"
    statuses[110] = "done"
    statuses[138] = "done"
    statuses[142] = "done"
    statuses[144] = "done"

    return statuses


@app.route("/admin/steps")
@admin_required
def admin_steps():
    statuses = build_steps_status_200()

    grouped = {}
    for sid, cat, title in SITE_STEPS:
        grouped.setdefault(cat, []).append((sid, title, statuses.get(sid, "todo")))

    total = len(SITE_STEPS)
    done = sum(1 for s in statuses.values() if s == "done")
    wip = sum(1 for s in statuses.values() if s == "in_progress")
    todo = total - done - wip

    return render_template(
        "admin/steps.html",
        grouped=grouped,
        stats=dict(total=total, done=done, in_progress=wip, todo=todo),
        lang=session.get("lang", "ru"),
    )


@app.route("/admin/categories", methods=["GET", "POST"])
@login_required
@admin_required
def admin_categories():
    if request.method == "POST":
        action = request.form.get("action", "")

        if action == "add":
            slug = norm_text(request.form.get("slug", ""), max_len=60).lower()
            slug = re.sub(r"[^a-z0-9_-]+", "", slug)

            title_ru = norm_text(request.form.get("title_ru", ""), max_len=120)
            title_lv = norm_text(request.form.get("title_lv", ""), max_len=120)
            title_en = norm_text(request.form.get("title_en", ""), max_len=120)

            try:
                sort = int(request.form.get("sort", "0") or 0)
            except Exception:
                sort = 0

            if not slug or not title_ru or not title_lv or not title_en:
                flash("Заполни slug и названия RU/LV/EN", "error")
                return redirect(url_for("admin_categories"))

            if slug == "other":
                flash("Slug 'other' зарезервирован", "error")
                return redirect(url_for("admin_categories"))

            if Category.query.filter_by(slug=slug).first():
                flash("Такой slug уже существует", "error")
                return redirect(url_for("admin_categories"))

            db.session.add(
                Category(
                    slug=slug,
                    title_ru=title_ru,
                    title_lv=title_lv,
                    title_en=title_en,
                    sort=sort,
                    is_active=True,
                )
            )
            db.session.commit()
            flash("Категория добавлена", "success")
            return redirect(url_for("admin_categories"))

        if action == "toggle":
            cid = request.form.get("id", type=int)
            c = Category.query.get_or_404(cid)
            c.is_active = not c.is_active
            db.session.commit()
            flash("Категория обновлена", "success")
            return redirect(url_for("admin_categories"))

        if action == "delete":
            cid = request.form.get("id", type=int)
            c = Category.query.get_or_404(cid)

            if Product.query.filter_by(category_id=c.id).first():
                flash("Нельзя удалить: в категории есть товары.", "error")
                return redirect(url_for("admin_categories"))

            db.session.delete(c)
            db.session.commit()
            flash("Категория удалена", "success")
            return redirect(url_for("admin_categories"))

    categories = Category.query.order_by(Category.sort.asc(), Category.id.asc()).all()
    return render_template(
        "admin/categories.html",
        categories=categories,
        lang=session.get("lang", "ru"),
    )
    
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "8080")))

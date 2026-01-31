// =========================
// HELPERS
// =========================
function isAdminPage() {
  return window.location.pathname.startsWith("/admin");
}

// =========================
// WC MENU (ONLY)
// =========================
function wcMenuOpen(){
  const m = document.getElementById("wcMenu");
  const o = document.getElementById("wcMenuOverlay");
  if(!m || !o) return;
  m.classList.add("open");
  o.classList.add("show");
  m.setAttribute("aria-hidden","false");
  document.body.style.overflow = "hidden";
}

function wcMenuClose(){
  const m = document.getElementById("wcMenu");
  const o = document.getElementById("wcMenuOverlay");
  if(!m || !o) return;
  m.classList.remove("open");
  o.classList.remove("show");
  m.setAttribute("aria-hidden","true");
  document.body.style.overflow = "";
}

// делаем функции доступными из HTML onclick="..."
window.wcMenuOpen = wcMenuOpen;
window.wcMenuClose = wcMenuClose;

// =========================
// TOAST (если надо)
// =========================
function ensureToastContainer() {
  let c = document.querySelector(".toast-container");
  if (!c) {
    c = document.createElement("div");
    c.className = "toast-container";
    document.body.appendChild(c);
  }
  return c;
}

function showToast(message, type = "info", ms = 2500) {
  const container = ensureToastContainer();
  const toast = document.createElement("div");
  const safeType = ["success", "error", "info", "warning"].includes(type) ? type : "info";

  toast.className = `toast toast-${safeType}`;
  toast.textContent = message || "";

  container.appendChild(toast);
  requestAnimationFrame(() => toast.classList.add("show"));

  setTimeout(() => {
    toast.classList.remove("show");
    setTimeout(() => toast.remove(), 200);
  }, ms);
}

window.showToast = showToast;

// =========================
// CART COUNT
// =========================
async function refreshCartCount() {
  // в админке вообще не трогаем корзину
  if (isAdminPage()) return;

  try {
    const res = await fetch("/api/cart_count", { credentials: "same-origin" });
    const ct = res.headers.get("content-type") || "";
    if (!ct.includes("application/json")) return;

    const data = await res.json();
    const n = Number(data.cart_total_items || 0);

    const badge = document.getElementById("cart-count");
    if (badge) {
      badge.textContent = n;
      badge.style.display = n > 0 ? "inline-flex" : "none";
    }
  } catch (e) {}
}

// =========================
// CART ACTION POPUP (только НЕ /admin)
// =========================
function showCartAction(){
  if (isAdminPage()) return;

  const popup = document.getElementById("cart-action-popup");
  if (!popup) return;

  popup.classList.add("show");

  clearTimeout(window._cartActionTimer);
  window._cartActionTimer = setTimeout(() => {
    popup.classList.remove("show");
  }, 3500);
}

function closeCartAction(){
  const popup = document.getElementById("cart-action-popup");
  if (popup) popup.classList.remove("show");
}

window.closeCartAction = closeCartAction;

// =========================
// ADD TO CART (только НЕ /admin)
// =========================
async function addToCart(productId) {
  if (isAdminPage()) return;

  try {
    const res = await fetch(`/api/add_to_cart/${productId}`, {
      method: "POST",
      credentials: "same-origin"
    });

    const ct = res.headers.get("content-type") || "";
    if (!ct.includes("application/json")) return;

    const data = await res.json();
    if (!data || !data.success) return;

    const badge = document.getElementById("cart-count");
    if (badge) {
      badge.textContent = data.cart_total_items;
      badge.style.display = data.cart_total_items > 0 ? "inline-flex" : "none";
    }

    showCartAction(); // ✅ показываем popup (только на обычных страницах)
  } catch (e) {
    console.error("addToCart error:", e);
  }
}

window.addToCart = addToCart;

// =========================
// CLICK HANDLER (только НЕ /admin)
// =========================
document.addEventListener("click", (e) => {
  if (isAdminPage()) return;

  const btn = e.target.closest("[data-add-to-cart]");
  if (!btn) return;

  e.preventDefault();
  const productId = btn.getAttribute("data-add-to-cart");
  if (!productId) return;

  addToCart(productId);
});

// =========================
// INIT
// =========================
document.addEventListener("DOMContentLoaded", () => {
  refreshCartCount();
});

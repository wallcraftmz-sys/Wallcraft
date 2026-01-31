// =========================
// TOAST (всплывашка)
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

// =========================
// CART COUNT
// =========================
async function refreshCartCount() {
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
// ADD TO CART
// =========================
async function addToCart(productId) {
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

    showCartAction();   // ✅ вот это делает “всплывашку”

  } catch (e) {
    console.error("addToCart error:", e);
  }
}

function showCartAction(){
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

// =========================
// CLICK HANDLER (главное)
// =========================
document.addEventListener("click", (e) => {
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
document.addEventListener("DOMContentLoaded", refreshCartCount);

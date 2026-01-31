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

window.wcMenuOpen = wcMenuOpen;
window.wcMenuClose = wcMenuClose;

document.addEventListener("keydown", (e)=>{
  if(e.key === "Escape") wcMenuClose();
});

// =========================
// CART COUNT
// =========================
async function refreshCartCount() {
  if (isAdminPage()) return;

  try {
    const res = await fetch("/api/cart_count", { credentials: "same-origin" });
    const ct = res.headers.get("content-type") || "";
    if (!ct.includes("application/json")) return;

    const data = await res.json();
    const n = Number(data.cart_total_items || 0);

    const badge = document.getElementById("cart-count");
    if (!badge) return;

    badge.textContent = n;
    badge.style.display = n > 0 ? "inline-flex" : "none";
  } catch (e) {}
}

// =========================
// CART ACTION POPUP
// =========================
function openCartAction(){
  if (isAdminPage()) return;

  const p = document.getElementById("cart-action-popup");
  if(!p) return;

  p.classList.add("show");
  p.setAttribute("aria-hidden","false");

  clearTimeout(window.__cartPopupTimer);
  window.__cartPopupTimer = setTimeout(closeCartAction, 3200);
}

function closeCartAction(){
  const p = document.getElementById("cart-action-popup");
  if(!p) return;

  p.classList.remove("show");
  p.setAttribute("aria-hidden","true");
}

window.closeCartAction = closeCartAction;

// =========================
// ADD TO CART (global)
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

    openCartAction();
  } catch (e) {
    console.error("addToCart error:", e);
  }
}

window.addToCart = addToCart;

// =========================
// INIT
// =========================
document.addEventListener("DOMContentLoaded", () => {
  refreshCartCount();
});

// =========================
// UPDATE QTY (+ / -) for CART PAGE
// =========================
async function updateQty(productId, action) {
  try {
    const res = await fetch(`/api/update_cart/${productId}/${action}`, {
      method: "POST",
      credentials: "same-origin"
    });

    const ct = res.headers.get("content-type") || "";
    if (!ct.includes("application/json")) {
      console.error("updateQty: expected json, got", ct);
      return;
    }

    const data = await res.json();
    if (!data || !data.success) {
      console.error("updateQty failed:", data);
      return;
    }

    // qty row update
    const qtyEl = document.getElementById(`qty-${productId}`);
    const subEl = document.getElementById(`subtotal-${productId}`);
    const rowEl = document.getElementById(`row-${productId}`);

    if (data.qty === 0) {
      if (rowEl) rowEl.remove();
    } else {
      if (qtyEl) qtyEl.textContent = data.qty;
      if (subEl) subEl.textContent = Number(data.subtotal).toFixed(2) + " €";
    }

    // total update
    const totalEl = document.getElementById("cart-total");
    if (totalEl) totalEl.textContent = Number(data.total).toFixed(2) + " €";

    // header badge update
    const badge = document.getElementById("cart-count");
    if (badge) {
      const n = Number(data.cart_total_items || 0);
      badge.textContent = n;
      badge.style.display = n > 0 ? "inline-flex" : "none";
    }

    // если корзина пустая — обновим страницу (чтобы показать "корзина пуста")
    if (Number(data.cart_total_items || 0) === 0) {
      location.reload();
    }
  } catch (e) {
    console.error("updateQty error:", e);
  }
}

window.updateQty = updateQty;

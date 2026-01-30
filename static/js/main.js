// =========================
// ADD TO CART
// =========================
function addToCart(productId) {
    fetch(`/api/add_to_cart/${productId}`, {
        method: "POST",
        credentials: "include"
    })
    .then(res => res.json())
    .then(data => {
        const cartCount = document.getElementById("cart-count");
        if (cartCount && data.cart_total_items !== undefined) {
            cartCount.textContent = data.cart_total_items;
        }
        openCartPopup();
    })
    .catch(err => {
        console.error("Add to cart error:", err);
        alert("Ошибка добавления в корзину");
    });
}

// =========================
// CART POPUP
// =========================
function openCartPopup() {
    const popup = document.getElementById("cart-popup");
    if (popup) popup.classList.add("show");
}

function closeCartPopup() {
    const popup = document.getElementById("cart-popup");
    if (popup) popup.classList.remove("show");
}

// =========================
// MENU (ЕДИНСТВЕННАЯ ЛОГИКА)
// =========================
function toggleMenu() {
    const menu = document.getElementById("sideMenu");
    const overlay = document.getElementById("menuOverlay");

    if (!menu || !overlay) return;

    menu.classList.toggle("open");
    overlay.classList.toggle("show");
}

function closeMenu() {
    const menu = document.getElementById("sideMenu");
    const overlay = document.getElementById("menuOverlay");

    if (menu) menu.classList.remove("open");
    if (overlay) overlay.classList.remove("show");
}

// =========================
// SAFE INIT
// =========================
document.addEventListener("DOMContentLoaded", () => {
    closeMenu();
});

// =========================
// UPDATE CART (+ / -)
// =========================
function updateQty(productId, action) {
    console.log("UPDATE CART:", productId, action);

    fetch(`/api/update_cart/${productId}/${action}`, {
        method: "POST",
        credentials: "include"
    })
    .then(res => res.json())
    .then(data => {
        console.log("RESPONSE:", data);

        if (!data.success) return;

        if (data.qty === 0) {
            const row = document.getElementById(`row-${productId}`);
            if (row) row.remove();
        } else {
            document.getElementById(`qty-${productId}`).textContent = data.qty;
            document.getElementById(`subtotal-${productId}`).textContent =
                data.subtotal.toFixed(2) + " €";
        }

        document.getElementById("cart-total").textContent =
            data.total.toFixed(2) + " €";

        const counter = document.getElementById("cart-count");
        if (counter) {
            counter.textContent = data.cart_total_items;
        }

        if (data.cart_total_items === 0) {
            location.reload();
        }
    })
    .catch(err => console.error("UPDATE CART ERROR:", err));
}

// STEP-17: UI TOAST NOTIFICATIONS
(function () {
  function ensureToastContainer() {
    let c = document.querySelector(".toast-container");
    if (!c) {
      c = document.createElement("div");
      c.className = "toast-container";
      document.body.appendChild(c);
    }
    return c;
  }

  window.showToast = function (message, category, ms) {
    const container = ensureToastContainer();
    const toast = document.createElement("div");
    const type = (category || "info").toLowerCase();

    toast.className = "toast toast-" + (["success","error","info","warning"].includes(type) ? type : "info");

    const text = document.createElement("div");
    text.className = "toast-text";
    text.textContent = message || "";

    const btn = document.createElement("button");
    btn.className = "toast-close";
    btn.type = "button";
    btn.setAttribute("aria-label", "Закрыть");
    btn.textContent = "×";

    btn.addEventListener("click", () => {
      toast.classList.remove("show");
      setTimeout(() => toast.remove(), 200);
    });

    toast.appendChild(text);
    toast.appendChild(btn);
    container.appendChild(toast);

    requestAnimationFrame(() => toast.classList.add("show"));

    const ttl = typeof ms === "number" ? ms : 3500;
    setTimeout(() => {
      if (!toast.isConnected) return;
      toast.classList.remove("show");
      setTimeout(() => toast.remove(), 220);
    }, ttl);
  };

  function flashToToasts() {
    const flashes = document.querySelectorAll(".flash-wrap .flash");
    if (!flashes || flashes.length === 0) return;

    flashes.forEach((el) => {
      const cls = el.className || "";
      // ожидаем форматы: flash flash-success / flash flash-error
      let category = "info";
      if (cls.includes("flash-success")) category = "success";
      else if (cls.includes("flash-error")) category = "error";
      else if (cls.includes("flash-warning")) category = "warning";
      else if (cls.includes("flash-info")) category = "info";

      const msg = (el.textContent || "").trim();
      if (msg) window.showToast(msg, category, 4000);
    });
  }

  document.addEventListener("DOMContentLoaded", flashToToasts);
})();

function refreshCartCount(){
  fetch("/api/cart_count", { credentials: "include" })
    .then(r => r.json())
    .then(data => {
      const el = document.getElementById("cart-count");
      if (!el) return;
      const n = Number(data.cart_total_items || 0);
      el.textContent = n;
      el.style.display = n > 0 ? "inline-flex" : "none";
    })
    .catch(()=>{});
}

function showCartToast() {
  const toast = document.getElementById("cart-toast");
  if (!toast) return;

  toast.classList.add("show");

  clearTimeout(window._cartToastTimer);
  window._cartToastTimer = setTimeout(() => {
    toast.classList.remove("show");
  }, 3000);
}

document.addEventListener("click", async (e) => {
  const btn = e.target.closest("[data-add-to-cart]");
  if (!btn) return;

  e.preventDefault();

  const product
    
document.addEventListener("DOMContentLoaded", refreshCartCount);
})();

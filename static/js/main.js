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

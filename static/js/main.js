// =========================
// ADD TO CART
// =========================
function addToCart(productId) {
    fetch(`/api/add_to_cart/${productId}`, {
        method: "POST",
        credentials: "same-origin"
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
// POPUP
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
// MENU
// =========================
function toggleMenu() {
    document.getElementById("sideMenu").classList.toggle("open");
    document.getElementById("menuOverlay").classList.toggle("show");
}

function closeMenu() {
    document.getElementById("sideMenu").classList.remove("open");
    document.getElementById("menuOverlay").classList.remove("show");
}

function closeMenu() {
    const menu = document.getElementById("sideMenu");
    const overlay = document.getElementById("menuOverlay");

    if (menu) menu.classList.remove("open");
    if (overlay) overlay.classList.remove("show");
}

document.addEventListener("DOMContentLoaded", () => {
    closeMenu();
});

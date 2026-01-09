// =========================
// ADD TO CART
// =========================
function addToCart(productId) {
    fetch(`/api/add_to_cart/${productId}`, {
        method: "POST"
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
    const menu = document.getElementById("sideMenu");
    if (menu) menu.classList.toggle("open");
}

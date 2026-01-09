// ===== ADD TO CART =====
function addToCart(productId) {
    fetch(`/api/add_to_cart/${productId}`, {
        method: "POST"
    })
    .then(response => response.json())
    .then(data => {
        updateCartCount(data.cart_total_items);
        openCartPopup();
        markButtonAsAdded(productId);
    })
    .catch(err => console.error("Add to cart error:", err));
}

// ===== UPDATE CART COUNT IN HEADER =====
function updateCartCount(count) {
    const el = document.getElementById("cart-count");
    if (el) {
        el.textContent = count;
    }
}

// ===== POPUP =====
function openCartPopup() {
    const popup = document.getElementById("cart-popup");
    if (popup) popup.classList.add("show");
}

function closeCartPopup() {
    const popup = document.getElementById("cart-popup");
    if (popup) popup.classList.remove("show");
}

// ===== BUTTON STATE =====
function markButtonAsAdded(productId) {
    const btn = document.querySelector(`[data-product-id="${productId}"]`);
    if (!btn) return;

    btn.classList.add("in-cart");
    btn.textContent = "✓ В корзине";
    btn.disabled = true;
}

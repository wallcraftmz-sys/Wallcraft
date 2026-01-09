function addToCart(productId) {
    fetch(`/api/add_to_cart/${productId}`, {
        method: "POST"
    })
    .then(res => res.json())
    .then(data => {
        const btn = document.getElementById(`add-btn-${productId}`);
        if (btn) {
            btn.innerText = "✅ В корзине";
            btn.classList.remove("btn-green");
            btn.classList.add("btn-disabled");
            btn.disabled = true;
        }

        const cartCount = document.getElementById("cart-count");
        if (cartCount) {
            cartCount.innerText = data.cart_total_items;
        }
    });
}

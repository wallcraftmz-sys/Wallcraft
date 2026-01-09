function addToCart(productId) {
    fetch(`/api/add_to_cart/${productId}`, {
        method: "POST"
    })
    .then(res => res.json())
    .then(data => {
        // обновляем счётчик корзины
        const cartCount = document.getElementById("cart-count");
        if (cartCount && data.cart_total_items !== undefined) {
            cartCount.innerText = data.cart_total_items;
        }

        // показываем popup
        openCartPopup();
    })
    .catch(err => {
        console.error("Add to cart error:", err);
        alert("Ошибка добавления в корзину");
    });
}

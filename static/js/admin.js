function deleteProduct(id) {
    fetch(`/admin/products/delete/${id}`, {
        method: "POST"
    }).then(() => location.reload())
}

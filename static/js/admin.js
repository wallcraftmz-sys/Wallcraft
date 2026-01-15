function addProduct() {
    const data = new FormData(document.getElementById("addForm"))

    fetch("/admin/products/add", {
        method: "POST",
        body: data
    })
    .then(r => r.json())
    .then(() => location.reload())
}

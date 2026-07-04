const documents = JSON.parse(
    document.getElementById("documents-data").textContent
);

const container = document.getElementById(
    "documents-container"
);

documents.forEach((doc) => {

    const card = document.createElement("div");

    card.classList.add("document-card");

    const title = document.createElement("h3");

    title.textContent = doc.titre;

    card.appendChild(title);

    const lowerUrl = doc.url.toLowerCase();

    if (lowerUrl.endsWith(".pdf")) {

        const iframe = document.createElement("iframe");

        iframe.src = doc.url;

        iframe.width = "100%";

        iframe.height = "700";

        card.appendChild(iframe);

    } else if (
        lowerUrl.endsWith(".jpg") ||
        lowerUrl.endsWith(".jpeg") ||
        lowerUrl.endsWith(".png")
    ) {

        const img = document.createElement("img");

        img.src = doc.url;

        img.style.maxWidth = "100%";

        card.appendChild(img);

    } else {

        const link = document.createElement("a");

        link.href = doc.url;

        link.target = "_blank";

        link.textContent = "Télécharger";

        card.appendChild(link);
    }

    container.appendChild(card);
});
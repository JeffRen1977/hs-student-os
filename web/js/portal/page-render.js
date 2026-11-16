// page-render.js — turn a PDF or photos into page images (+ PDF text layers) in the browser,
// so the server never parses PDFs (Step 39B). Each image is a JPEG under 600 KB, at most
// 1600 px wide. pdf.js (pinned) is loaded only when a PDF is chosen. window.HSPageRender.
(function (root) {
  "use strict";
  const PDFJS = "https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.min.js";
  const PDFJS_WORKER = "https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.worker.min.js";
  const MAX_BYTES = 590000;
  const MAX_WIDTH = 1600;

  let loading = null;
  function loadPdfJs() {
    if (root.pdfjsLib) return Promise.resolve(root.pdfjsLib);
    if (!loading) {
      loading = new Promise((resolve, reject) => {
        const s = document.createElement("script");
        s.src = PDFJS;
        s.onload = () => { root.pdfjsLib.GlobalWorkerOptions.workerSrc = PDFJS_WORKER; resolve(root.pdfjsLib); };
        s.onerror = () => reject(new Error("Could not load the PDF reader."));
        document.head.appendChild(s);
      });
    }
    return loading;
  }

  async function canvasToJpeg(canvas) {
    let quality = 0.85;
    let scale = 1;
    for (let attempt = 0; attempt < 8; attempt++) {
      let c = canvas;
      if (scale < 1) {
        c = document.createElement("canvas");
        c.width = Math.round(canvas.width * scale);
        c.height = Math.round(canvas.height * scale);
        c.getContext("2d").drawImage(canvas, 0, 0, c.width, c.height);
      }
      const data = c.toDataURL("image/jpeg", quality).split(",")[1];
      if (Math.floor((data.length * 3) / 4) <= MAX_BYTES) return { mediaType: "image/jpeg", dataBase64: data };
      if (quality > 0.55) quality -= 0.15; else scale *= 0.8;
    }
    throw new Error("A page image stays larger than 600 KB.");
  }

  function whiteCanvas(w, h) {
    const c = document.createElement("canvas");
    c.width = w; c.height = h;
    const ctx = c.getContext("2d");
    ctx.fillStyle = "#fff"; ctx.fillRect(0, 0, w, h);
    return c;
  }

  // onPage(n, total, page) for each page, in order; page = {mediaType, dataBase64, text}.
  async function renderPdf(file, onPage) {
    const pdfjs = await loadPdfJs();
    const doc = await pdfjs.getDocument({ data: new Uint8Array(await file.arrayBuffer()) }).promise;
    for (let n = 1; n <= doc.numPages; n++) {
      const page = await doc.getPage(n);
      const base = page.getViewport({ scale: 1 });
      const viewport = page.getViewport({ scale: Math.min(2, MAX_WIDTH / base.width) });
      const canvas = whiteCanvas(Math.round(viewport.width), Math.round(viewport.height));
      await page.render({ canvasContext: canvas.getContext("2d"), viewport: viewport }).promise;
      const text = root.HSBankApi.textItemsToLines((await page.getTextContent()).items);
      await onPage(n, doc.numPages, { ...(await canvasToJpeg(canvas)), text: text || undefined });
    }
    return doc.numPages;
  }

  async function pdfPageCount(file) {
    const pdfjs = await loadPdfJs();
    return (await pdfjs.getDocument({ data: new Uint8Array(await file.arrayBuffer()) }).promise).numPages;
  }

  async function renderPhoto(file) {
    const bitmap = await createImageBitmap(file);
    const scale = Math.min(1, MAX_WIDTH / bitmap.width);
    const canvas = whiteCanvas(Math.round(bitmap.width * scale), Math.round(bitmap.height * scale));
    canvas.getContext("2d").drawImage(bitmap, 0, 0, canvas.width, canvas.height);
    return canvasToJpeg(canvas);
  }

  root.HSPageRender = { renderPdf: renderPdf, pdfPageCount: pdfPageCount, renderPhoto: renderPhoto };
})(typeof self !== "undefined" ? self : this);

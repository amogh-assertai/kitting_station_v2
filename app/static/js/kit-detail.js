/**
 * Kit Detail page - image lightbox.
 *
 * Every .image-thumb on the page (wrong-part section, anomalies
 * section, per-part cards - all of them) is collected into ONE flat
 * sequence in DOM order. Clicking any thumbnail opens the lightbox at
 * that image; Left/Right arrow keys (or the on-screen prev/next
 * buttons) move through the WHOLE page's sequence, not just the
 * clicked card's own images - confirmed scope: "move to next image"
 * means the entire page, so an operator can arrow through every image
 * on the kit without closing and reopening the lightbox per card.
 *
 * Zoom: click-to-toggle a larger view, plus mouse wheel to zoom in/out
 * continuously while the lightbox is open - plain CSS transform, no
 * external library.
 */
document.addEventListener("DOMContentLoaded", () => {
  const thumbs = Array.from(document.querySelectorAll(".image-thumb"));
  if (thumbs.length === 0) return;

  const lightbox = document.getElementById("lightbox");
  const lightboxImage = document.getElementById("lightbox-image");
  const closeBtn = document.getElementById("lightbox-close");
  const prevBtn = document.getElementById("lightbox-prev");
  const nextBtn = document.getElementById("lightbox-next");

  let currentIndex = 0;
  let zoomLevel = 1;

  function applyZoom() {
    lightboxImage.style.transform = `scale(${zoomLevel})`;
  }

  function showImage(index) {
    // Wrap around in both directions, so Next on the last image loops
    // to the first and Prev on the first loops to the last - simpler
    // than disabling the buttons at the ends for what's meant to be a
    // continuous browsing experience across the whole page.
    currentIndex = (index + thumbs.length) % thumbs.length;
    const thumb = thumbs[currentIndex];
    lightboxImage.src = thumb.dataset.full || thumb.src;
    lightboxImage.alt = thumb.alt;
    zoomLevel = 1;
    applyZoom();
  }

  function openLightbox(index) {
    showImage(index);
    lightbox.hidden = false;
    // Belt-and-suspenders alongside the .lightbox[hidden]{display:none}
    // CSS rule: explicitly drive display here too, rather than relying
    // solely on the hidden attribute + CSS cascade. This was a real,
    // confirmed bug - the lightbox rendered open on page load because
    // .lightbox's own `display: flex` rule beat the browser's default
    // [hidden]{display:none} UA rule in at least one real browser
    // environment, even though the `hidden` attribute was correctly
    // present in the HTML the whole time.
    lightbox.style.display = "flex";
    document.body.style.overflow = "hidden";
  }

  function closeLightbox() {
    lightbox.hidden = true;
    lightbox.style.display = "none";
    document.body.style.overflow = "";
  }

  thumbs.forEach((thumb, index) => {
    thumb.addEventListener("click", () => openLightbox(index));
  });

  closeBtn.addEventListener("click", closeLightbox);
  prevBtn.addEventListener("click", () => showImage(currentIndex - 1));
  nextBtn.addEventListener("click", () => showImage(currentIndex + 1));

  // Click the dimmed backdrop (outside the image itself) to close -
  // clicking the image toggles zoom instead of closing.
  lightbox.addEventListener("click", (event) => {
    if (event.target === lightbox) {
      closeLightbox();
    }
  });

  lightboxImage.addEventListener("click", () => {
    zoomLevel = zoomLevel === 1 ? 2 : 1;
    applyZoom();
  });

  lightboxImage.addEventListener("wheel", (event) => {
    event.preventDefault();
    const delta = event.deltaY < 0 ? 0.2 : -0.2;
    zoomLevel = Math.min(4, Math.max(1, zoomLevel + delta));
    applyZoom();
  }, { passive: false });

  document.addEventListener("keydown", (event) => {
    if (lightbox.hidden) return;
    if (event.key === "Escape") closeLightbox();
    if (event.key === "ArrowLeft") showImage(currentIndex - 1);
    if (event.key === "ArrowRight") showImage(currentIndex + 1);
  });
});

// BEAMTEAM project page: manifest-driven video/paper wiring, lightbox, BibTeX copy.
(function () {
  "use strict";
  var $ = function (s, r) { return (r || document).querySelector(s); };
  var $$ = function (s, r) { return Array.prototype.slice.call((r || document).querySelectorAll(s)); };

  // ---- assets that teammates deliver later (see sync_assets.sh -> assets/manifest.json)
  fetch("assets/manifest.json", { cache: "no-store" })
    .then(function (r) { return r.ok ? r.json() : {}; })
    .catch(function () { return {}; })
    .then(function (m) {
      if (m.paper) {
        $$("[data-paper]").forEach(function (a) {
          a.href = "assets/beamline_paper.pdf";
          a.classList.remove("disabled");
          a.removeAttribute("aria-disabled");
          var s = a.querySelector("small"); if (s) s.remove();
        });
      }
      if (m.teaser || m.video) {
        var v = $("#teaser-video");
        if (m.poster) {
          v.poster = "assets/img/video_poster.webp";
          $("#full-video").poster = "assets/img/video_poster.webp";
        }
        v.src = m.teaser ? "assets/video/teaser.mp4" : "assets/video/beamline_demo_60s.mp4";
        v.hidden = false;
        $("#teaser-poster").hidden = true;
        var p = v.play(); if (p && p.catch) p.catch(function () {});
      }
      if (m.video) {
        var full = $("#full-video");
        full.src = "assets/video/beamline_demo_60s.mp4";
        if (m.vtt) {
          var t = document.createElement("track");
          t.kind = "captions"; t.srclang = "en"; t.label = "English";
          t.src = "assets/video/beamline_demo_60s.vtt"; t.default = true;
          full.appendChild(t);
        }
        $$("[data-video]").forEach(function (el) {
          el.classList.remove("disabled"); el.removeAttribute("aria-disabled");
          var s = el.querySelector("small"); if (s) s.remove();
        });
        $("#soon").hidden = true;
      }
    });

  // ---- narration modal
  var modal = $("#video-modal"), full = $("#full-video");
  function openVideo(e) {
    if (e) e.preventDefault();
    if (!full.getAttribute("src")) return;
    modal.classList.add("open");
    full.muted = false; full.currentTime = 0;
    var p = full.play(); if (p && p.catch) p.catch(function () {});
  }
  function closeVideo() { full.pause(); modal.classList.remove("open"); }
  $$("[data-video]").forEach(function (el) { el.addEventListener("click", openVideo); });
  $("#video-close").addEventListener("click", closeVideo);
  modal.addEventListener("click", function (e) { if (e.target === modal) closeVideo(); });

  // ---- lightbox
  var lb = $("#lightbox"), lbImg = $("#lb-img"), lbCap = $("#lb-cap");
  $$(".gallery button, [data-zoom]").forEach(function (b) {
    b.addEventListener("click", function () {
      var img = b.querySelector("img") || b;
      var fig = b.closest("figure");
      lbImg.src = img.currentSrc || img.src; lbImg.alt = img.alt;
      lbCap.textContent = fig && fig.querySelector("figcaption") ? fig.querySelector("figcaption").textContent : img.alt;
      lb.classList.add("open");
    });
  });
  lb.addEventListener("click", function () { lb.classList.remove("open"); });
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape") { lb.classList.remove("open"); closeVideo(); }
  });

  // ---- BibTeX copy
  $("#copy-bib").addEventListener("click", function () {
    var btn = this, txt = $("#bibtex").textContent;
    function done() { btn.textContent = "Copied"; setTimeout(function () { btn.textContent = "Copy"; }, 1600); }
    if (navigator.clipboard && window.isSecureContext) {
      navigator.clipboard.writeText(txt).then(done, fallback);
    } else { fallback(); }
    function fallback() {
      var ta = document.createElement("textarea"); ta.value = txt; ta.style.position = "fixed"; ta.style.opacity = "0";
      document.body.appendChild(ta); ta.select();
      try { document.execCommand("copy"); done(); } catch (e) { btn.textContent = "Select + copy"; }
      document.body.removeChild(ta);
    }
  });
})();

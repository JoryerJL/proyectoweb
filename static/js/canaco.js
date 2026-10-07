(function () {
  "use strict";

  const header = document.querySelector(".site-header");
  if (header) {
    const onScroll = () => header.classList.toggle("is-scrolled", window.scrollY > 8);
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
  }

  const toggle = document.querySelector(".menu-toggle");
  const mobileMenu = document.getElementById("mobile-menu");
  if (toggle && mobileMenu) {
    toggle.addEventListener("click", () => {
      const open = mobileMenu.classList.toggle("is-open");
      toggle.setAttribute("aria-expanded", String(open));
      toggle.querySelector(".bi").className = open ? "bi bi-x-lg" : "bi bi-list";
    });
  }

  document.querySelectorAll(".nav-dropdown").forEach((dropdown) => {
    const button = dropdown.querySelector("button");
    const close = () => {
      dropdown.classList.remove("is-open");
      button.setAttribute("aria-expanded", "false");
    };
    button.addEventListener("click", (event) => {
      event.stopPropagation();
      const open = dropdown.classList.toggle("is-open");
      button.setAttribute("aria-expanded", String(open));
    });
    document.addEventListener("click", (event) => {
      if (!dropdown.contains(event.target)) close();
    });
    dropdown.addEventListener("keydown", (event) => {
      if (event.key === "Escape") { close(); button.focus(); }
    });
  });

  document.querySelectorAll("[data-dismiss='alert']").forEach((button) => {
    button.addEventListener("click", () => {
      const alert = button.closest(".alert");
      alert.classList.add("is-closing");
      setTimeout(() => alert.remove(), 250);
    });
  });

  document.querySelectorAll(".password-toggle").forEach((button) => {
    button.addEventListener("click", () => {
      const input = button.parentElement.querySelector("input");
      const show = input.type === "password";
      input.type = show ? "text" : "password";
      button.setAttribute("aria-label", show ? "Ocultar contraseña" : "Mostrar contraseña");
      button.querySelector(".bi").className = show ? "bi bi-eye-slash" : "bi bi-eye";
    });
  });

  document.querySelectorAll("form[data-confirm]").forEach((form) => {
    form.addEventListener("submit", (event) => {
      if (!window.confirm(form.dataset.confirm)) event.preventDefault();
    });
  });

  document.querySelectorAll("[data-rail]").forEach((rail) => {
    const prev = document.querySelector(`[data-rail-prev][aria-controls="${rail.id}"]`);
    const next = document.querySelector(`[data-rail-next][aria-controls="${rail.id}"]`);
    const step = () => {
      const card = rail.firstElementChild;
      const gap = parseFloat(getComputedStyle(rail).columnGap) || 0;
      return card ? card.getBoundingClientRect().width + gap : rail.clientWidth;
    };
    const update = () => {
      const max = rail.scrollWidth - rail.clientWidth - 2;
      if (prev) prev.disabled = rail.scrollLeft <= 2;
      if (next) next.disabled = rail.scrollLeft >= max;
    };
    prev?.addEventListener("click", () => rail.scrollBy({ left: -step() }));
    next?.addEventListener("click", () => rail.scrollBy({ left: step() }));
    rail.addEventListener("keydown", (event) => {
      if (event.key === "ArrowRight") { event.preventDefault(); rail.scrollBy({ left: step() }); }
      if (event.key === "ArrowLeft") { event.preventDefault(); rail.scrollBy({ left: -step() }); }
    });
    rail.addEventListener("scroll", update, { passive: true });
    window.addEventListener("resize", update);
    update();
  });

  const carousel = document.querySelector("[data-carousel]");
  if (carousel) {
    const slides = Array.from(carousel.querySelectorAll(".featured-slide"));
    const dots = Array.from(carousel.querySelectorAll(".carousel-dots button"));
    const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    let current = 0;
    let timer = null;

    const show = (index) => {
      current = (index + slides.length) % slides.length;
      slides.forEach((slide, i) => {
        const active = i === current;
        slide.hidden = !active;
        slide.classList.toggle("is-entering", active);
      });
      dots.forEach((dot, i) => dot.setAttribute("aria-current", String(i === current)));
    };

    const start = () => {
      if (reduceMotion || slides.length < 2) return;
      stop();
      timer = setInterval(() => show(current + 1), 6500);
    };
    const stop = () => { if (timer) clearInterval(timer); timer = null; };

    carousel.querySelector(".prev")?.addEventListener("click", () => { show(current - 1); start(); });
    carousel.querySelector(".next")?.addEventListener("click", () => { show(current + 1); start(); });
    dots.forEach((dot, i) => dot.addEventListener("click", () => { show(i); start(); }));
    carousel.addEventListener("mouseenter", stop);
    carousel.addEventListener("mouseleave", start);
    carousel.addEventListener("focusin", stop);

    show(0);
    slides[0].classList.remove("is-entering");
    start();
  }
})();

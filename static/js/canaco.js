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

  // Forms marked data-ajax confirm inside the AJAX handler below.
  document.querySelectorAll("form[data-confirm]:not([data-ajax])").forEach((form) => {
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

  // Infinite scroll: the server answers fetch requests with bare <article> rows and
  // reports the next page in the X-Next-Url header (empty/absent = last page).
  const list = document.querySelector("[data-infinite-scroll]");
  if (list) {
    const sentinel = document.querySelector("[data-infinite-sentinel]");
    const more = document.querySelector("[data-infinite-more]");
    let nextUrl = list.dataset.nextUrl;
    let loading = false;

    const finish = () => {
      nextUrl = "";
      observer?.disconnect();
      sentinel?.remove();
      more?.parentElement.remove();
    };
    const load = async () => {
      if (loading || !nextUrl) return;
      loading = true;
      list.setAttribute("aria-busy", "true");
      try {
        const response = await fetch(nextUrl, { headers: { "X-Requested-With": "fetch" } });
        if (!response.ok) throw new Error(response.status);
        if (response.status === 204) return finish();
        list.insertAdjacentHTML("beforeend", await response.text());
        nextUrl = response.headers.get("X-Next-Url") || "";
        if (more) more.href = nextUrl || "#";
        if (!nextUrl) finish();
      } catch (error) {
        // Keep the plain "Cargar más" link as the fallback.
      } finally {
        loading = false;
        list.setAttribute("aria-busy", "false");
        // Re-observe so a sentinel that is still on screen triggers the next load.
        if (nextUrl && observer && sentinel.isConnected) { observer.unobserve(sentinel); observer.observe(sentinel); }
      }
    };

    const observer = sentinel && "IntersectionObserver" in window
      ? new IntersectionObserver((entries) => { if (entries[0].isIntersecting) load(); }, { rootMargin: "300px" })
      : null;
    observer?.observe(sentinel);
    more?.addEventListener("click", (event) => { event.preventDefault(); load(); });
  }

  // Category <select>: navigate on change (replaces an inline onchange handler).
  document.querySelector("[data-category-select]")?.addEventListener("change", (event) => {
    if (event.target.value) window.location.href = event.target.value;
  });

  // Welcome modal: shown once per browser. Storage may throw (private mode, blocked cookies).
  const welcome = document.querySelector("[data-welcome-modal]");
  if (welcome && typeof welcome.showModal === "function") {
    const SEEN_KEY = "canaco:welcome-seen";
    let seen = false;
    try { seen = localStorage.getItem(SEEN_KEY) === "1"; } catch (_) { /* ignore */ }

    if (!seen) {
      welcome.querySelectorAll("[data-welcome-close]").forEach((button) => {
        button.addEventListener("click", () => welcome.close());
      });
      // Clicking the backdrop (outside the dialog box) closes it.
      welcome.addEventListener("click", (event) => {
        if (event.target === welcome) welcome.close();
      });
      welcome.showModal();
      // Mark as seen once shown, so leaving through a link (no "close" event) also counts.
      try { localStorage.setItem(SEEN_KEY, "1"); } catch (_) { /* ignore */ }
    }
  }
  // ---------------------------------------------------------------------------
  // Panel AJAX layer (progressive enhancement over plain form posts).
  //
  // <form data-ajax> opts a form in. Optional attributes:
  //   data-ajax-action = replace-row | remove-row | prepend-row | append-row | none
  //   data-target      = CSS selector of the row (replace-row/remove-row) or container
  //                      (prepend-row/append-row). Defaults to the closest [data-row].
  //   data-confirm     = window.confirm() text asked before sending.
  //   data-ajax-reset  = reset the form after a successful response.
  // Server contract (see home/views.py): success -> {ok, message, id, html | removed | bind, bind_src};
  // validation errors -> HTTP 400 {ok: false, message, errors: {field: [{message, code}]}}.
  // HTML fragments are rendered by the server (escaped); user data is never concatenated here.
  // ---------------------------------------------------------------------------
  const flash = document.getElementById("ajax-flash");
  const ICONS = { success: "bi-check-circle-fill", error: "bi-exclamation-octagon-fill" };

  const showFlash = (message, kind = "success") => {
    if (!flash) return;
    const alert = document.createElement("div");
    alert.className = `alert alert-${kind}`;
    const icon = document.createElement("i");
    icon.className = `bi ${ICONS[kind] || ICONS.success}`;
    icon.setAttribute("aria-hidden", "true");
    const body = document.createElement("div");
    body.className = "alert-body";
    body.textContent = message;
    const close = document.createElement("button");
    close.type = "button";
    close.className = "alert-close";
    close.setAttribute("aria-label", "Cerrar");
    close.innerHTML = '<i class="bi bi-x-lg" aria-hidden="true"></i>';
    const dismiss = () => { alert.classList.add("is-closing"); setTimeout(() => alert.remove(), 250); };
    close.addEventListener("click", dismiss);
    alert.append(icon, body, close);
    flash.replaceChildren(alert);
    if (kind === "success") setTimeout(dismiss, 6000);
  };

  const clearErrors = (form) => {
    form.querySelectorAll(".field-error").forEach((node) => node.remove());
    form.querySelectorAll("[aria-invalid]").forEach((node) => node.removeAttribute("aria-invalid"));
    const summary = form.querySelector("[data-ajax-errors]");
    if (summary) summary.replaceChildren();
  };

  const showErrors = (form, errors) => {
    let summary = form.querySelector("[data-ajax-errors]");
    if (!summary) {
      summary = document.createElement("div");
      summary.dataset.ajaxErrors = "";
      summary.setAttribute("role", "alert");
      form.insertAdjacentElement("afterend", summary);
    }
    let firstInvalid = null;
    Object.entries(errors || {}).forEach(([name, list]) => {
      const input = name === "__all__" ? null : form.querySelector(`[name="${CSS.escape(name)}"]`);
      const field = input?.closest(".field");
      list.forEach((error) => {
        if (field) {
          const note = document.createElement("p");
          note.className = "field-error";
          note.textContent = error.message;
          field.append(note);
        } else {
          const line = document.createElement("p");
          line.className = "field-error";
          line.textContent = error.message;
          summary.append(line);
        }
      });
      if (input && field) {
        input.setAttribute("aria-invalid", "true");
        firstInvalid = firstInvalid || input;
      }
    });
    return firstInvalid;
  };

  const fragmentFrom = (html) => {
    const template = document.createElement("template");
    template.innerHTML = html.trim();
    return template.content.firstElementChild;
  };

  const syncEmptyState = (container) => {
    const scope = container?.closest("tbody") || container;
    if (!scope) return;
    const empty = scope.querySelector("[data-empty]");
    if (empty) empty.hidden = scope.querySelector("[data-row]") !== null;
  };

  const applyBindings = (data) => {
    Object.entries(data.bind || {}).forEach(([key, value]) => {
      document.querySelectorAll(`[data-bind="${CSS.escape(key)}"]`).forEach((node) => { node.textContent = value; });
    });
    Object.entries(data.bind_src || {}).forEach(([key, value]) => {
      document.querySelectorAll(`[data-bind-src="${CSS.escape(key)}"]`).forEach((node) => { node.src = value; });
    });
  };

  const focusFlash = () => flash?.focus({ preventScroll: true });

  const applySuccess = (form, data) => {
    const action = form.dataset.ajaxAction || "none";
    const rowOf = () => (form.dataset.target ? document.querySelector(form.dataset.target) : form.closest("[data-row]"));
    let focusTarget = null;

    if (action === "replace-row" && data.html) {
      const row = rowOf();
      const fresh = fragmentFrom(data.html);
      if (row && fresh) { row.replaceWith(fresh); focusTarget = fresh.querySelector("a, button"); }
    } else if (action === "remove-row" || data.removed) {
      const row = form.closest("[data-row]") || rowOf();
      if (row) {
        const container = row.parentElement;
        const next = row.nextElementSibling?.matches("[data-row]") ? row.nextElementSibling : null;
        row.remove();
        syncEmptyState(container);
        focusTarget = next?.querySelector("a, button") || null;
      }
    } else if ((action === "prepend-row" || action === "append-row") && data.html) {
      const container = document.querySelector(form.dataset.target);
      const fresh = fragmentFrom(data.html);
      if (container && fresh) {
        container.insertAdjacentElement(action === "prepend-row" ? "afterbegin" : "beforeend", fresh);
        syncEmptyState(container);
      }
    }
    applyBindings(data);
    if (form.hasAttribute("data-ajax-reset")) form.reset();
    form.querySelectorAll("input[type='file']").forEach((input) => { input.value = ""; });
    const dialog = form.closest("dialog");
    if (dialog?.open) dialog.close();
    return focusTarget;
  };

  // Errors: the flash region sits under a modal <dialog> (top layer, inert page), so inside a
  // dialog the message is also written into the form's own error container and focused.
  const report = (form, message, focusIt = true) => {
    showFlash(message, "error");
    if (!form.closest("dialog")) return focusFlash();
    let box = form.querySelector("[data-ajax-errors]");
    if (!box) {
      box = document.createElement("div");
      box.dataset.ajaxErrors = "";
      box.setAttribute("role", "alert");
      form.append(box);
    }
    const line = document.createElement("p");
    line.className = "field-error";
    line.textContent = message;
    box.append(line);
    if (focusIt) { box.tabIndex = -1; box.focus(); }
  };

  const submitAjax = async (form, submitter) => {
    if (form.dataset.confirm && !window.confirm(form.dataset.confirm)) return;
    if (!form.checkValidity()) { form.reportValidity(); return; }
    const buttons = form.querySelectorAll("button[type='submit'], button:not([type])");
    const lock = (state) => buttons.forEach((button) => { button.disabled = state; });
    clearErrors(form);
    lock(true);
    form.setAttribute("aria-busy", "true");
    try {
      const body = new FormData(form);
      if (submitter?.name) body.append(submitter.name, submitter.value);
      const response = await fetch(form.getAttribute("action") || window.location.href, {
        method: "POST",
        body,
        headers: {
          "X-Requested-With": "fetch",
          "X-CSRFToken": body.get("csrfmiddlewaretoken") || "",
          "Accept": "application/json",
        },
        credentials: "same-origin",
      });
      const isJson = (response.headers.get("Content-Type") || "").includes("application/json");
      if (response.redirected || (!isJson && response.ok)) {
        return report(form, "Tu sesión expiró. Inicia sesión de nuevo para continuar.");
      }
      let data = null;
      if (isJson) {
        try { data = await response.json(); } catch (_) { return report(form, "Ocurrió un error inesperado."); }
      }
      if (response.ok && data?.ok) {
        const focusTarget = applySuccess(form, data);
        showFlash(data.message || "Cambios guardados.", "success");
        if (focusTarget) focusTarget.focus(); else focusFlash();
        return;
      }
      if (response.status === 404 && data) {
        // The record is gone (deleted elsewhere): drop the stale row and close the dialog.
        const row = (form.dataset.target && form.dataset.ajaxAction === "replace-row"
          ? document.querySelector(form.dataset.target) : null) || form.closest("[data-row]");
        const container = row?.parentElement;
        row?.remove();
        syncEmptyState(container);
        const dialog = form.closest("dialog");
        if (dialog?.open) dialog.close();
        showFlash(data.message || "El registro ya no existe.", "error");
        return focusFlash();
      }
      if (response.status === 403) {
        report(form, isJson
          ? "No tienes permiso para realizar esta acción."
          : "Tu sesión o el formulario expiró. Recarga la página e inténtalo de nuevo.");
      } else if (data) {
        const firstInvalid = showErrors(form, data.errors);
        report(form, data.message || "No se pudo completar la acción.", !firstInvalid);
        if (firstInvalid) firstInvalid.focus();
      } else report(form, "No se pudo completar la acción. Inténtalo de nuevo.");
    } catch (_) {
      report(form, "No hay conexión con el servidor. Inténtalo de nuevo.");
    } finally {
      lock(false);
      form.removeAttribute("aria-busy");
    }
  };

  document.addEventListener("submit", (event) => {
    const form = event.target;
    if (!(form instanceof HTMLFormElement) || !form.hasAttribute("data-ajax") || event.defaultPrevented) return;
    event.preventDefault();
    submitAjax(form, event.submitter);
  });

  // Dialogs: links with data-dialog-open show a native <dialog> instead of navigating.
  // data-field-<name> prefill inputs; data-form-action / data-ajax-action / data-target
  // reconfigure the dialog's form for create vs. edit.
  let dialogOrigin = null;
  document.addEventListener("click", (event) => {
    const closer = event.target.closest("[data-dialog-close]");
    if (closer) { closer.closest("dialog")?.close(); return; }

    const opener = event.target.closest("[data-dialog-open]");
    if (!opener) return;
    const dialog = document.querySelector(opener.dataset.dialogOpen);
    if (!dialog || typeof dialog.showModal !== "function") return; // keep the plain link
    event.preventDefault();
    const form = dialog.querySelector("form");
    clearErrors(form);
    form.reset();
    form.setAttribute("action", opener.dataset.formAction || form.getAttribute("action"));
    form.dataset.ajaxAction = opener.dataset.ajaxAction || form.dataset.ajaxAction;
    if (opener.dataset.target) form.dataset.target = opener.dataset.target;
    opener.getAttributeNames().filter((name) => name.startsWith("data-field-")).forEach((name) => {
      const input = form.elements[name.slice("data-field-".length)];
      if (input) input.value = opener.getAttribute(name);
    });
    const editing = opener.dataset.dialogMode === "edit";
    form.querySelectorAll("[data-create-required]").forEach((input) => { input.required = !editing; });
    form.querySelectorAll("[data-dialog-edit-only]").forEach((node) => { node.hidden = !editing; });
    dialog.querySelectorAll("[data-dialog-title]").forEach((node) => { node.textContent = opener.dataset.dialogTitle || node.textContent; });
    dialog.querySelectorAll("button[data-dialog-submit]").forEach((node) => { node.textContent = opener.dataset.dialogSubmit || node.textContent; });
    dialogOrigin = opener;
    dialog.showModal();
    form.querySelector("input:not([type='hidden'])")?.focus();
  });

  document.querySelectorAll("dialog.ajax-dialog").forEach((dialog) => {
    // Clicking the backdrop closes it; focus returns to the element that opened it.
    dialog.addEventListener("click", (event) => { if (event.target === dialog) dialog.close(); });
    dialog.addEventListener("close", () => {
      if (dialogOrigin?.isConnected) dialogOrigin.focus();
    });
  });
})();

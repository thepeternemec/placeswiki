/* Typeahead over the shipped sample. No framework, no server, no tracking:
   the index is a static JSON file fetched once, on first focus. */
(() => {
  const input = document.getElementById("q");
  const list = document.getElementById("suggestions");
  if (!input || !list) return;

  const MAX = 8;
  let places = null;
  let loading = null;
  let items = [];
  let active = -1;

  const fold = (text) =>
    text.normalize("NFKD").replace(/[\u0300-\u036f]/g, "").toLowerCase();

  function load() {
    if (places) return Promise.resolve(places);
    if (!loading) {
      loading = fetch("places.json")
        .then((response) => (response.ok ? response.json() : []))
        .then((data) => (places = Array.isArray(data) ? data : []))
        .catch(() => (places = []));
    }
    return loading;
  }

  function open() {
    list.hidden = false;
    input.setAttribute("aria-expanded", "true");
  }

  function close() {
    list.hidden = true;
    list.innerHTML = "";
    input.setAttribute("aria-expanded", "false");
    input.removeAttribute("aria-activedescendant");
    active = -1;
    items = [];
  }

  const escapeHtml = (text) =>
    text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");

  function highlight(name, query) {
    const needle = fold(query.trim());
    const at = fold(name).indexOf(needle);
    if (!needle || at === -1) return escapeHtml(name);
    return (
      escapeHtml(name.slice(0, at)) +
      "<mark>" + escapeHtml(name.slice(at, at + needle.length)) + "</mark>" +
      escapeHtml(name.slice(at + needle.length))
    );
  }

  function resultUrl(place) {
    if (/^Q\d+$/.test(place.i)) {
      return "https://www.wikidata.org/wiki/" + place.i;
    }
    return "https://www.wikidata.org/w/index.php?search=" + encodeURIComponent(place.n);
  }

  function render(query) {
    const needle = fold(query.trim());
    if (!needle) return close();

    const scored = [];
    for (const place of places) {
      const name = fold(place.n);
      const at = name.indexOf(needle);
      if (at === -1) continue;
      scored.push({ place, rank: at === 0 ? 0 : 1, length: name.length });
    }
    scored.sort((a, b) => a.rank - b.rank || a.length - b.length || a.place.n.localeCompare(b.place.n));
    items = scored.slice(0, MAX).map((entry) => entry.place);

    if (!items.length) {
      list.innerHTML = '<li class="empty" role="option" aria-disabled="true">No place matches “' +
        query.replace(/[<>&]/g, "") + "”</li>";
      open();
      return;
    }

    list.innerHTML = items
      .map(
        (place, index) =>
          '<li role="option" id="sug-' + index + '" aria-selected="false">' +
          '<a href="' + resultUrl(place) + '">' +
          '<span class="sug-name">' + highlight(place.n, query) + "</span>" +
          '<span class="sug-meta">' + place.lat.toFixed(4) + ", " + place.lon.toFixed(4) + "</span>" +
          "</a></li>"
      )
      .join("");
    open();
  }

  function setActive(index) {
    const options = list.querySelectorAll("li[role=option]");
    if (!options.length) return;
    active = (index + options.length) % options.length;
    options.forEach((option, i) => {
      option.classList.toggle("active", i === active);
      option.setAttribute("aria-selected", i === active ? "true" : "false");
    });
    input.setAttribute("aria-activedescendant", "sug-" + active);
    options[active].scrollIntoView({ block: "nearest" });
  }

  let timer = null;
  input.addEventListener("input", () => {
    clearTimeout(timer);
    timer = setTimeout(() => {
      load().then(() => render(input.value));
    }, 80);
  });

  input.addEventListener("keydown", (event) => {
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      if (!items.length) return;
      event.preventDefault();
      setActive(active + (event.key === "ArrowDown" ? 1 : -1));
    } else if (event.key === "Enter" && active >= 0) {
      event.preventDefault();
      window.location.href = resultUrl(items[active]);
    } else if (event.key === "Escape") {
      close();
    }
  });

  input.addEventListener("focus", () => {
    load().then(() => { if (input.value.trim()) render(input.value); });
  });

  document.addEventListener("click", (event) => {
    if (!event.target.closest(".search")) close();
  });

  // deep link: /?q=kirche opens with results, useful in a shared URL
  const initial = new URLSearchParams(location.search).get("q");
  if (initial) {
    input.value = initial;
    load().then(() => render(initial));
  }
})();

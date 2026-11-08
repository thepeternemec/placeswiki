/* Two-step typeahead: pick a city, then search its places.
   No framework, no server, no tracking. The city list is a few hundred bytes;
   a city's places load only when that city is chosen. */
(() => {
  const input = document.getElementById("q");
  const list = document.getElementById("suggestions");
  const chip = document.getElementById("city-chip");
  const chipName = document.getElementById("city-name");
  const clear = document.getElementById("city-clear");
  if (!input || !list) return;

  const MAX = 8;
  let cities = null;
  let citiesPromise = null;
  let city = null;       // {s, n, c, count}
  let places = null;     // [[name, qid, lat, lon], ...]
  let placesPromise = null;
  let items = [];        // suggestions currently shown
  let active = -1;

  const fold = (text) =>
    text.normalize("NFKD").replace(/[\u0300-\u036f]/g, "").toLowerCase();
  const escapeHtml = (text) =>
    text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");

  function json(path) {
    return fetch(path).then((response) => (response.ok ? response.json() : []));
  }

  function loadCities() {
    if (cities) return Promise.resolve(cities);
    if (!citiesPromise) {
      citiesPromise = json("data/cities.json")
        .then((data) => (cities = Array.isArray(data) ? data : []))
        .catch(() => (cities = []));
    }
    return citiesPromise;
  }

  function loadPlaces(record) {
    if (places) return Promise.resolve(places);
    if (!placesPromise) {
      placesPromise = json("data/" + record.s + ".json")
        .then((data) => (places = Array.isArray(data) ? data : []))
        .catch(() => (places = []));
    }
    return placesPromise;
  }

  function loadCity(record) {
    city = record;
    places = null;
    chip.hidden = false;
    chipName.textContent = record.n;
    input.form.classList.add("has-city");
    input.placeholder = "Search " + record.count.toLocaleString() + " places in " + record.n;
    input.value = "";
    close();
    const pending = loadPlaces(record);
    input.focus();
    return pending;
  }

  function clearCity() {
    city = null;
    places = null;
    placesPromise = null;
    chip.hidden = true;
    input.form.classList.remove("has-city");
    input.value = "";
    input.placeholder = "Search a city";
    close();
    input.focus();
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

  function highlight(text, query) {
    const needle = fold(query.trim());
    const at = fold(text).indexOf(needle);
    if (!needle || at === -1) return escapeHtml(text);
    return (
      escapeHtml(text.slice(0, at)) +
      "<mark>" + escapeHtml(text.slice(at, at + needle.length)) + "</mark>" +
      escapeHtml(text.slice(at + needle.length))
    );
  }

  function optionRow(index, primary, meta, href) {
    return (
      '<li role="option" id="sug-' + index + '" aria-selected="false">' +
      '<a href="' + href + '">' +
      '<span class="sug-name">' + primary + "</span>" +
      '<span class="sug-meta">' + meta + "</span>" +
      "</a></li>"
    );
  }

  function renderCities(query) {
    const needle = fold(query.trim());
    if (!needle) return close();
    items = [];
    for (const record of cities) {
      if (fold(record.n).indexOf(needle) === -1 && fold(record.c).indexOf(needle) === -1) continue;
      items.push(record);
      if (items.length >= MAX) break;
    }
    if (!items.length) return empty(query, "city");
    list.innerHTML = items
      .map((record, index) =>
        optionRow(index, highlight(record.n, query), record.c + " · " +
          record.count.toLocaleString() + " places", "#")
      )
      .join("");
    // city rows are not links: choosing one loads its places
    list.querySelectorAll("li[role=option] a").forEach((anchor, index) => {
      anchor.addEventListener("click", (event) => {
        event.preventDefault();
        loadCity(items[index]);
      });
    });
    open();
  }

  function renderPlaces(query) {
    const needle = fold(query.trim());
    if (!needle) return close();
    const scored = [];
    for (const place of places) {
      const name = fold(place[0]);
      const at = name.indexOf(needle);
      if (at !== -1) scored.push({ place, rank: at === 0 ? 0 : 1, length: name.length });
    }
    scored.sort((a, b) => a.rank - b.rank || a.length - b.length || a.place[0].localeCompare(b.place[0]));
    items = scored.slice(0, MAX).map((entry) => entry.place);
    if (!items.length) return empty(query, "place");
    list.innerHTML = items
      .map((place, index) =>
        optionRow(
          index,
          highlight(place[0], query),
          place[2].toFixed(4) + ", " + place[3].toFixed(4),
          /^Q\d+$/.test(place[1])
            ? "https://www.wikidata.org/wiki/" + place[1]
            : "https://www.wikidata.org/w/index.php?search=" + encodeURIComponent(place[0])
        )
      )
      .join("");
    open();
  }

  function empty(query, kind) {
    items = [];
    list.innerHTML =
      '<li class="empty" role="option" aria-disabled="true">No ' + kind +
      " matches “" + escapeHtml(query) + "”</li>";
    open();
  }

  function render(query) {
    if (city) renderPlaces(query);
    else renderCities(query);
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

  function choose(index) {
    if (index < 0) return;
    if (city) {
      const place = items[index];
      window.location.href = /^Q\d+$/.test(place[1])
        ? "https://www.wikidata.org/wiki/" + place[1]
        : "https://www.wikidata.org/w/index.php?search=" + encodeURIComponent(place[0]);
    } else {
      loadCity(items[index]);
    }
  }

  let timer = null;
  input.addEventListener("input", () => {
    clearTimeout(timer);
    timer = setTimeout(() => {
      const ready = city ? loadPlaces(city) : loadCities();
      ready.then(() => render(input.value));
    }, 80);
  });

  input.addEventListener("keydown", (event) => {
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      if (!items.length) return;
      event.preventDefault();
      setActive(active + (event.key === "ArrowDown" ? 1 : -1));
    } else if (event.key === "Enter" && active >= 0) {
      event.preventDefault();
      choose(active);
    } else if (event.key === "Escape") {
      close();
    }
  });

  input.addEventListener("focus", () => {
    const ready = city ? loadPlaces(city) : loadCities();
    ready.then(() => { if (input.value.trim()) render(input.value); });
  });

  if (clear) clear.addEventListener("click", clearCity);

  document.addEventListener("click", (event) => {
    if (!event.target.closest(".search")) close();
  });

  // deep link: ?city=berlin&q=kirche
  loadCities().then(() => {
    const params = new URLSearchParams(location.search);
    const wanted = params.get("city");
    const query = params.get("q");
    const record = wanted && cities.find((entry) => entry.s === wanted);
    if (record) {
      loadCity(record).then(() => {
        if (query) {
          input.value = query;
          render(query);
        }
      });
    } else if (query) {
      input.value = query;
      render(query);
    }
  });
})();

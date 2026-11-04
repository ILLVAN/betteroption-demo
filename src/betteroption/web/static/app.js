"use strict";

for (const textarea of document.querySelectorAll("textarea[data-autogrow]")) {
  const resize = () => {
    textarea.style.height = "auto";
    textarea.style.height = `${Math.min(textarea.scrollHeight, 480)}px`;
  };
  textarea.addEventListener("input", resize);
  resize();
}

for (const form of document.querySelectorAll("[data-compensation-range]")) {
  const minimum = form.querySelector('[name="minimum_gross_annual"]');
  const target = form.querySelector('[name="target_gross_annual"]');
  if (!minimum || !target) continue;
  minimum.addEventListener("input", () => {
    if (target.value && Number(minimum.value) > Number(target.value)) target.value = minimum.value;
  });
  target.addEventListener("input", () => {
    if (target.value && Number(target.value) < Number(minimum.value)) minimum.value = target.value;
  });
}

for (const form of document.querySelectorAll("[data-mobility-preferences]")) {
  const origin = form.querySelector("[data-mobility-origin]");
  const suggestions = form.querySelector("[data-mobility-suggestions]");
  const limits = [...form.querySelectorAll("[data-mobility-limit]")];
  let suggestionTimer = null;
  let suggestionRequest = null;

  const formatMinutes = (value) => {
    const minutes = Number.parseInt(String(value), 10) || 0;
    if (minutes <= 0) return "Not set";
    if (minutes < 60) return `${minutes} min`;
    const hours = Math.floor(minutes / 60);
    const remainder = minutes % 60;
    return `${hours}h${remainder ? ` ${remainder}m` : ""}`;
  };
  const render = () => {
    let active = Boolean(origin?.value.trim());
    for (const input of limits) {
      const row = input.closest(".mobility-limit-row");
      const output = row?.querySelector("[data-mobility-output]");
      const enabled = Number.parseInt(input.value, 10) > 0;
      row?.classList.toggle("is-active", enabled);
      if (output) output.textContent = formatMinutes(input.value);
      active ||= enabled;
    }
    form.classList.toggle("is-active", active);
  };

  for (const input of limits) input.addEventListener("input", render);
  origin?.addEventListener("input", () => {
    render();
    window.clearTimeout(suggestionTimer);
    suggestionRequest?.abort();
    const query = origin.value.trim();
    if (query.length < 2 || !suggestions || !form.dataset.suggestionUrl) {
      if (suggestions) suggestions.replaceChildren();
      return;
    }
    suggestionTimer = window.setTimeout(async () => {
      suggestionRequest = new AbortController();
      try {
        const body = new URLSearchParams({ query });
        const response = await fetch(form.dataset.suggestionUrl, {
          method: "POST",
          body,
          credentials: "same-origin",
          headers: {
            Accept: "application/json",
            "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
          },
          signal: suggestionRequest.signal,
        });
        if (!response.ok) return;
        const payload = await response.json();
        suggestions.replaceChildren(
          ...(payload.suggestions || []).map((value) => {
            const option = document.createElement("option");
            option.value = String(value);
            return option;
          }),
        );
      } catch (error) {
        if (error.name !== "AbortError") suggestions.replaceChildren();
      }
    }, 420);
  });
  render();
}

for (const catalog of document.querySelectorAll("[data-language-catalog]")) {
  const search = catalog.querySelector("[data-language-search]");
  const options = [...catalog.querySelectorAll("[data-language-option]")];
  const count = catalog.querySelector("[data-language-count]");
  const selectedCount = catalog.querySelector("[data-language-selected-count]");
  const normalize = (value) => value
    .normalize("NFKD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLocaleLowerCase();

  const render = () => {
    const query = normalize(search?.value.trim() || "");
    let shown = 0;
    let selected = 0;
    for (const option of options) {
      const checkbox = option.querySelector("[data-language-enable]");
      const level = option.querySelector("[data-language-level]");
      const levelOutput = option.querySelector("[data-language-level-output]");
      const isSelected = Boolean(checkbox?.checked);
      const visible = !query || normalize(option.dataset.searchText || "").includes(query);
      option.hidden = !visible;
      option.classList.toggle("is-selected", isSelected);
      if (level) {
        level.disabled = !isSelected;
        const labels = (level.dataset.languageLevelLabels || "").split("|");
        const label = labels[Number.parseInt(level.value, 10)] || "Professional";
        if (levelOutput) levelOutput.textContent = label;
        level.setAttribute("aria-valuetext", label);
      }
      shown += visible ? 1 : 0;
      selected += isSelected ? 1 : 0;
    }
    if (count) {
      count.textContent = query
        ? `${shown} of ${options.length} languages shown`
        : `${options.length} languages available`;
    }
    if (selectedCount) selectedCount.textContent = `${selected} selected`;
  };

  search?.addEventListener("input", render);
  for (const checkbox of catalog.querySelectorAll("[data-language-enable]")) {
    checkbox.addEventListener("change", render);
  }
  for (const level of catalog.querySelectorAll("[data-language-level]")) {
    level.addEventListener("input", render);
  }
  render();
}

for (const form of document.querySelectorAll("[data-bulk-review]")) {
  const boxes = [...document.querySelectorAll(`input[name="selected_fact_ids"][form="${form.id}"]`)];
  const count = form.querySelector("[data-selection-count]");
  const submit = form.querySelector("[data-confirm-selected]");
  const update = () => {
    const selected = boxes.filter((box) => box.checked).length;
    count.textContent = String(selected);
    submit.disabled = selected === 0;
  };
  form.querySelector("[data-select-all]")?.addEventListener("click", () => {
    boxes.forEach((box) => { box.checked = true; });
    update();
  });
  form.querySelector("[data-clear-selection]")?.addEventListener("click", () => {
    boxes.forEach((box) => { box.checked = false; });
    update();
  });
  boxes.forEach((box) => box.addEventListener("change", update));
  update();
}

for (const form of document.querySelectorAll("[data-selection-form]")) {
  const boxes = [...form.querySelectorAll("[data-select-item]")];
  const selectAll = form.querySelector("[data-select-all]");
  const count = form.querySelector("[data-selection-count]");
  const submitButtons = [...form.querySelectorAll('button[type="submit"]')];
  const slotWarning = form.querySelector("[data-slot-warning]");
  const slotLimit = Number.parseInt(form.dataset.slotLimit || "", 10);
  const update = () => {
    const visibleBoxes = boxes.filter((box) => !box.closest("[data-explore-card]")?.hidden);
    const selected = visibleBoxes.filter((box) => box.checked).length;
    const overflow = Number.isFinite(slotLimit) ? selected - slotLimit : 0;
    count.textContent = `${selected} selected`;
    submitButtons.forEach((button) => { button.disabled = selected === 0 || overflow > 0; });
    if (selectAll) {
      selectAll.checked = selected > 0 && selected === visibleBoxes.length;
      selectAll.indeterminate = selected > 0 && selected < visibleBoxes.length;
    }
    if (slotWarning && Number.isFinite(slotLimit)) {
      slotWarning.hidden = overflow <= 0;
      slotWarning.textContent = overflow > 0
        ? `${selected} selected but only ${slotLimit} slot${slotLimit === 1 ? "" : "s"} remain. Reduce the selection or free slots first.`
        : "";
    }
  };
  selectAll?.addEventListener("change", () => {
    boxes.forEach((box) => {
      if (!box.closest("[data-explore-card]")?.hidden) box.checked = selectAll.checked;
    });
    update();
  });
  boxes.forEach((box) => box.addEventListener("change", update));
  form.addEventListener("selection:refresh", update);
  update();
}

for (const carousel of document.querySelectorAll("[data-opportunity-carousel]")) {
  const track = carousel.querySelector("[data-carousel-track]");
  const previous = carousel.querySelector("[data-carousel-previous]");
  const next = carousel.querySelector("[data-carousel-next]");
  const status = carousel.querySelector("[data-carousel-status]");
  const currentCards = () => (track ? [...track.querySelectorAll(".opportunity-card")] : []);
  const compact = window.matchMedia("(max-width: 650px)");
  const medium = window.matchMedia("(max-width: 900px)");
  const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
  let start = 0;

  const pageSize = () => (compact.matches ? 1 : medium.matches ? 2 : 3);
  const render = () => {
    const cards = currentCards();
    const size = pageSize();
    if (start >= cards.length) start = 0;
    start = Math.floor(start / size) * size;
    const end = Math.min(cards.length, start + size);
    cards.forEach((card, index) => {
      const visible = index >= start && index < end;
      card.hidden = !visible;
      card.setAttribute("aria-hidden", String(!visible));
    });
    const hasMultiplePages = cards.length > size;
    if (previous) previous.hidden = !hasMultiplePages;
    if (next) next.hidden = !hasMultiplePages;
    if (status) {
      status.textContent = cards.length
        ? `Showing opportunities ${start + 1} to ${end} of ${cards.length}`
        : "No current opportunities";
    }
  };
  const move = (direction) => {
    const cards = currentCards();
    const size = pageSize();
    const lastPage = Math.floor(Math.max(0, cards.length - 1) / size) * size;
    const nextStart = direction > 0
      ? (start + size >= cards.length ? 0 : start + size)
      : (start - size < 0 ? lastPage : start - size);
    const update = () => {
      start = nextStart;
      render();
      window.requestAnimationFrame(() => track?.classList.remove("is-changing"));
    };
    if (reducedMotion.matches || !track) {
      update();
      return;
    }
    track.classList.add("is-changing");
    window.setTimeout(update, 120);
  };

  previous?.addEventListener("click", () => move(-1));
  next?.addEventListener("click", () => move(1));
  const handleBreakpoint = () => {
    start = 0;
    render();
  };
  compact.addEventListener("change", handleBreakpoint);
  medium.addEventListener("change", handleBreakpoint);
  carousel.addEventListener("ranking:refresh", handleBreakpoint);
  render();
}

const remoteFilter = document.querySelector("[data-remote-filter]");
if (remoteFilter) {
  const remoteOnlyFilter = document.querySelector("[data-remote-only-filter]");
  const maxDistanceFilter = document.querySelector("[data-max-distance-filter]");
  const maxDistanceOutput = document.querySelector("[data-max-distance-output]");
  const providerFilterAll = document.querySelector("[data-provider-filter-all]");
  const providerFilters = [...document.querySelectorAll("[data-provider-filter]")]
    .filter((filter) => !filter.disabled);
  const hideStorageKey = "betteroption:explore:hide-remote-only";
  const onlyStorageKey = "betteroption:explore:remote-only";
  const distanceStorageKey = "betteroption:explore:max-distance-km";
  const defaultMaximumDistance = 150;
  const distanceStops = (maxDistanceFilter?.dataset.distanceStops || "")
    .split(",")
    .map((value) => Number(value))
    .filter((value) => Number.isFinite(value));
  const anyDistance = distanceStops[distanceStops.length - 1] || 1000;
  const distanceAtSlider = () => (
    distanceStops[Number(maxDistanceFilter?.value)] ?? defaultMaximumDistance
  );
  const nearestDistanceIndex = (requested) => distanceStops.reduce(
    (nearest, value, index) => (
      Math.abs(value - requested) < Math.abs(distanceStops[nearest] - requested)
        ? index
        : nearest
    ),
    0,
  );
  const cards = [...document.querySelectorAll("[data-explore-card]")];
  const resultCount = document.querySelector("[data-visible-result-count]");
  const resultLabel = document.querySelector("[data-visible-result-label]");
  const stored = window.localStorage.getItem(hideStorageKey);
  if (stored !== null) remoteFilter.checked = stored === "true";
  const storedRemoteOnly = window.localStorage.getItem(onlyStorageKey);
  if (storedRemoteOnly !== null && remoteOnlyFilter) {
    remoteOnlyFilter.checked = storedRemoteOnly === "true";
  }
  if (maxDistanceFilter) {
    const fromUrl = new URLSearchParams(window.location.search).get("max_distance_km");
    const fromStorage = window.localStorage.getItem(distanceStorageKey);
    const requested = Number(fromUrl ?? fromStorage);
    if (Number.isFinite(requested) && requested >= distanceStops[0] && requested <= anyDistance) {
      maxDistanceFilter.value = String(nearestDistanceIndex(requested));
    }
  }
  if (remoteFilter.checked && remoteOnlyFilter?.checked) {
    remoteOnlyFilter.checked = false;
  }

  const syncProviderMaster = () => {
    if (!providerFilterAll) return;
    const selected = providerFilters.filter((filter) => filter.checked).length;
    providerFilterAll.checked = providerFilters.length > 0 && selected === providerFilters.length;
    providerFilterAll.indeterminate = selected > 0 && selected < providerFilters.length;
  };

  const applyExploreFilters = () => {
    const maximumDistance = distanceAtSlider();
    const distanceIsBounded = maximumDistance < anyDistance;
    const selectedProviders = new Set(
      providerFilters.filter((filter) => filter.checked).map((filter) => filter.value),
    );
    let visible = 0;
    for (const card of cards) {
      const isRemoteOnly = card.dataset.remoteOnly === "true";
      const distance = Number.parseFloat(card.dataset.distanceKm || "");
      const sourceProviders = (card.dataset.sourceProviders || "")
        .split("|")
        .filter(Boolean);
      const sourceIsSelected = providerFilters.length === 0 || sourceProviders.some(
        (provider) => selectedProviders.has(provider),
      );
      const outsideMaximumDistance = (
        !isRemoteOnly
        && distanceIsBounded
        && Number.isFinite(distance)
        && distance > maximumDistance
      );
      const hidden = (
        (remoteFilter.checked && isRemoteOnly)
        || (remoteOnlyFilter?.checked && !isRemoteOnly)
        || outsideMaximumDistance
        || !sourceIsSelected
      );
      card.hidden = hidden;
      card.style.setProperty("display", hidden ? "none" : "");
      const box = card.querySelector("[data-select-item]");
      if (hidden && box) box.checked = false;
      if (!hidden) visible += 1;
    }
    if (resultCount) resultCount.textContent = String(visible);
    if (resultLabel) resultLabel.textContent = visible === 1 ? "role" : "roles";
    document.querySelector("[data-selection-form]")?.dispatchEvent(
      new Event("selection:refresh"),
    );
    syncProviderMaster();
    window.localStorage.setItem(hideStorageKey, String(remoteFilter.checked));
    window.localStorage.setItem(
      onlyStorageKey,
      String(Boolean(remoteOnlyFilter?.checked)),
    );
    if (maxDistanceFilter) {
      const distanceLabel = distanceIsBounded ? `${maximumDistance} km` : "Any distance";
      if (maxDistanceOutput) maxDistanceOutput.textContent = distanceLabel;
      maxDistanceFilter.setAttribute("aria-valuetext", distanceLabel);
      maxDistanceFilter.setAttribute("aria-valuenow", String(maximumDistance));
      window.localStorage.setItem(distanceStorageKey, String(maximumDistance));
      const currentUrl = new URL(window.location.href);
      if (maximumDistance === defaultMaximumDistance) {
        currentUrl.searchParams.delete("max_distance_km");
      } else {
        currentUrl.searchParams.set("max_distance_km", String(maximumDistance));
      }
      window.history.replaceState({}, "", currentUrl);
    }
  };

  remoteFilter.addEventListener("change", () => {
    if (remoteFilter.checked && remoteOnlyFilter) remoteOnlyFilter.checked = false;
    applyExploreFilters();
  });
  remoteOnlyFilter?.addEventListener("change", () => {
    if (remoteOnlyFilter.checked) remoteFilter.checked = false;
    applyExploreFilters();
  });
  maxDistanceFilter?.addEventListener("input", applyExploreFilters);
  providerFilterAll?.addEventListener("change", () => {
    providerFilters.forEach((filter) => { filter.checked = providerFilterAll.checked; });
    applyExploreFilters();
  });
  providerFilters.forEach((filter) => filter.addEventListener("change", applyExploreFilters));
  applyExploreFilters();
}

const utcDateOnly = (value) => {
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return null;
  return new Date(Date.UTC(
    parsed.getUTCFullYear(),
    parsed.getUTCMonth(),
    parsed.getUTCDate(),
  ));
};

const subtractUtcCalendarMonth = (value) => {
  const targetYear = value.getUTCMonth() === 0
    ? value.getUTCFullYear() - 1
    : value.getUTCFullYear();
  const targetMonth = (value.getUTCMonth() + 11) % 12;
  const lastDay = new Date(Date.UTC(targetYear, targetMonth + 1, 0)).getUTCDate();
  return new Date(Date.UTC(targetYear, targetMonth, Math.min(value.getUTCDate(), lastDay)));
};

const now = new Date();
const todayUtc = new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate()));
const oneMonthAgoUtc = subtractUtcCalendarMonth(todayUtc);
for (const badge of document.querySelectorAll("[data-explore-published-at]")) {
  const published = utcDateOnly(badge.dataset.explorePublishedAt);
  if (!published || published > todayUtc) continue;
  const fresh = published > oneMonthAgoUtc;
  badge.textContent = fresh ? "Fresh" : "Older";
  badge.classList.toggle("fresh", fresh);
  badge.classList.toggle("older", !fresh);
  badge.title = fresh
    ? "The known posting date is less than one month old"
    : "The known posting date is at least one month old";
  badge.hidden = false;
}

const deleteDialog = document.querySelector("[data-delete-dialog]");
const deleteDialogCopy = deleteDialog?.querySelector("[data-delete-dialog-copy]");
const deleteDialogConfirm = deleteDialog?.querySelector("[data-delete-dialog-confirm]");
let pendingDeleteForm = null;

for (const form of document.querySelectorAll("form[data-delete-confirm]")) {
  form.addEventListener("submit", (event) => {
    if (form.dataset.deleteConfirmed === "true") {
      delete form.dataset.deleteConfirmed;
      return;
    }
    event.preventDefault();
    const selectedCount = form.querySelectorAll("[data-select-item]:checked").length;
    const subject = form.dataset.deleteSubject || "selected job data";
    if (deleteDialogCopy) {
      const countCopy = selectedCount > 0 ? `${selectedCount} job${selectedCount === 1 ? "" : "s"}` : subject;
      deleteDialogCopy.textContent = `Permanently delete ${countCopy}, including source copies, references, and match history? The freed slots can be used again.`;
    }
    pendingDeleteForm = form;
    if (deleteDialog?.showModal) {
      deleteDialog.showModal();
      return;
    }
    if (window.confirm(`Permanently delete ${subject}?`)) {
      form.dataset.deleteConfirmed = "true";
      form.requestSubmit(event.submitter || undefined);
    }
  });
}

deleteDialog?.addEventListener("close", () => {
  if (deleteDialog.returnValue !== "confirm" || !pendingDeleteForm) {
    pendingDeleteForm = null;
    return;
  }
  const form = pendingDeleteForm;
  pendingDeleteForm = null;
  form.dataset.deleteConfirmed = "true";
  form.requestSubmit();
});

const manualJobPanel = document.querySelector("[data-manual-job-dialog]");
const manualSourceForm = document.querySelector("[data-manual-source-form]");
const manualJobTriggers = [...document.querySelectorAll("[data-manual-job-open]")];

const setManualJobPanelOpen = (open) => {
  if (!manualJobPanel) return;
  manualJobPanel.hidden = !open;
  manualJobTriggers.forEach((trigger) => trigger.setAttribute("aria-expanded", String(open)));
  if (open) {
    manualJobPanel.scrollIntoView({ behavior: "smooth", block: "center" });
    window.setTimeout(() => {
      manualJobPanel.querySelector("textarea[name='manual_source_text']")?.focus();
    }, 180);
  }
};

manualJobTriggers.forEach((trigger) => {
  trigger.addEventListener("click", () => setManualJobPanelOpen(true));
});
for (const trigger of document.querySelectorAll("[data-manual-job-close]")) {
  trigger.addEventListener("click", () => setManualJobPanelOpen(false));
}
if (manualJobPanel && !manualJobPanel.hidden) {
  manualJobTriggers.forEach((trigger) => trigger.setAttribute("aria-expanded", "true"));
}

for (const editor of document.querySelectorAll("[data-salary-range-editor]")) {
  const minimum = editor.querySelector("[data-salary-range-min]");
  const maximum = editor.querySelector("[data-salary-range-max]");
  const output = editor.querySelector("[data-salary-range-output]");
  if (!minimum || !maximum || !output) continue;
  const sync = (changed) => {
    if (changed === minimum && minimum.value && !maximum.value) {
      maximum.value = minimum.value;
    }
    if (changed === maximum && maximum.value && !minimum.value) {
      minimum.value = maximum.value;
    }
    if (changed === minimum && Number(minimum.value) > Number(maximum.value)) {
      maximum.value = minimum.value;
    }
    if (changed === maximum && Number(maximum.value) < Number(minimum.value)) {
      minimum.value = maximum.value;
    }
    output.value = `${minimum.value}:${maximum.value}`;
    output.dispatchEvent(new Event("input", { bubbles: true }));
  };
  minimum.addEventListener("input", () => sync(minimum));
  maximum.addEventListener("input", () => sync(maximum));
}

const scrollStorageKey = `betteroption:scroll:${window.location.pathname}`;
for (const form of document.querySelectorAll("form[data-preserve-scroll]")) {
  form.addEventListener("submit", () => {
    window.sessionStorage.setItem(scrollStorageKey, String(window.scrollY));
  });
}
const savedScroll = window.sessionStorage.getItem(scrollStorageKey);
if (savedScroll !== null) {
  window.sessionStorage.removeItem(scrollStorageKey);
  window.requestAnimationFrame(() => window.scrollTo({ top: Number(savedScroll), behavior: "auto" }));
}

for (const toast of document.querySelectorAll("[data-toast]")) {
  requestAnimationFrame(() => toast.classList.add("is-visible"));
  if (!toast.hasAttribute("data-toast-persistent")) {
    window.setTimeout(() => toast.classList.add("is-leaving"), 3200);
    window.setTimeout(() => toast.remove(), 3700);
  }
}

deleteDialogConfirm?.addEventListener("click", () => {
  deleteDialog.returnValue = "confirm";
});

for (const select of document.querySelectorAll("[data-application-state]")) {
  select.addEventListener("change", async () => {
    const previous = select.dataset.currentState || "discovered";
    const status = select.closest(".card-application-control")?.querySelector(
      "[data-application-state-status]",
    );
    const card = select.closest("[data-application-state-card]");
    const body = new FormData();
    body.set("application_state", select.value);
    if (card) card.dataset.applicationStateCard = select.value;
    select.disabled = true;
    if (status) status.textContent = "Saving…";
    try {
      const response = await fetch(select.dataset.stateUrl, {
        method: "POST",
        body,
        headers: { Accept: "application/json" },
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const saved = await response.json();
      select.value = saved.state;
      select.dataset.currentState = saved.state;
      if (card) card.dataset.applicationStateCard = saved.state;
      if (status) {
        status.textContent = `${saved.label} saved`;
        window.setTimeout(() => {
          if (status.textContent === `${saved.label} saved`) status.textContent = "";
        }, 1600);
      }
    } catch (_error) {
      select.value = previous;
      if (card) card.dataset.applicationStateCard = previous;
      if (status) status.textContent = "Could not save — try again";
    } finally {
      select.disabled = false;
    }
  });
}

const renderRatingControl = (control, kind, stars) => {
  const numeric = stars === null ? null : Number.parseInt(String(stars), 10);
  const valueAttribute = kind === "job" ? "jobRatingValue" : "employerRatingValue";
  const buttonSelector = kind === "job"
    ? "[data-job-rating-value]"
    : "[data-employer-rating-value]";
  const clearSelector = kind === "job" ? "[data-job-rating-clear]" : "[data-employer-rating-clear]";
  const copySelector = kind === "job" ? "[data-job-rating-copy]" : "[data-employer-rating-copy]";
  control.dataset.currentRating = numeric === null ? "" : String(numeric);
  for (const button of control.querySelectorAll(buttonSelector)) {
    const value = Number.parseInt(button.dataset[valueAttribute], 10);
    const active = numeric === 0 ? value === 0 : numeric !== null && value > 0 && value <= numeric;
    button.classList.toggle("is-active", active);
    button.setAttribute("aria-pressed", String(numeric !== null && value === numeric));
  }
  const copy = control.querySelector(copySelector);
  const clearButton = control.querySelector(clearSelector);
  if (copy) copy.textContent = numeric === null ? "Not rated" : `${numeric}/5`;
  if (clearButton) clearButton.hidden = numeric === null;
};

const matchLayoutSurface = document.querySelector("[data-match-layout]");
const reducedMatchMotion = window.matchMedia("(prefers-reduced-motion: reduce)");

const updateCompatibilitySurfaces = (updates) => {
  if (!Array.isArray(updates)) return;
  for (const update of updates) {
    for (const surface of document.querySelectorAll("[data-match-record-id]")) {
      if (surface.dataset.matchRecordId !== String(update.record_id)) continue;
      surface.dataset.matchDisposition = update.disposition;
      for (const score of surface.querySelectorAll("[data-match-score]")) {
        score.textContent = String(update.score);
      }
      for (const label of surface.querySelectorAll("[data-match-disposition-label]")) {
        label.classList.remove("top", "stretch", "blocked");
        label.classList.add(update.disposition);
        label.textContent = update.disposition_label;
      }
      const accessLabel = surface.querySelector("[data-match-access-label]");
      if (accessLabel) accessLabel.textContent = update.disposition === "blocked"
        ? "Transparent"
        : "Included";
    }
  }
};

const animateMatchCard = (card, horizontalShift, verticalShift) => {
  if (reducedMatchMotion.matches || (!horizontalShift && !verticalShift)) return;
  card.style.setProperty("--match-shift-x", `${horizontalShift}px`);
  card.style.setProperty("--match-shift-y", `${verticalShift}px`);
  card.classList.remove("match-card-is-moving");
  void card.offsetWidth;
  card.classList.add("match-card-is-moving");
  card.addEventListener("animationend", () => {
    card.classList.remove("match-card-is-moving");
    card.style.removeProperty("--match-shift-x");
    card.style.removeProperty("--match-shift-y");
  }, { once: true });
};

const storedMatchLayoutKey = () => matchLayoutSurface?.dataset.matchRunId
  ? `worklifebalance:match-layout:${matchLayoutSurface.dataset.matchRunId}`
  : null;

const renderedMatchLayout = () => matchLayoutSurface
  ? [...matchLayoutSurface.querySelectorAll("[data-match-result-card]")].map((card) => ({
    record_id: card.dataset.matchRecordId,
    disposition: card.dataset.matchDisposition,
    position: Number.parseInt(card.dataset.matchPosition || "0", 10),
  }))
  : [];

const rememberMatchLayout = (items) => {
  const key = storedMatchLayoutKey();
  if (!key || !Array.isArray(items)) return;
  try {
    window.sessionStorage.setItem(key, JSON.stringify(items.map((item) => ({
      record_id: String(item.record_id),
      disposition: String(item.disposition),
      position: Number.parseInt(String(item.position), 10),
    }))));
  } catch (_error) {
    // The ranking itself remains server-authoritative when storage is unavailable.
  }
};

const animateLoadedMatchLayout = () => {
  const key = storedMatchLayoutKey();
  const current = renderedMatchLayout();
  if (!key || current.length === 0) return;
  let previous = null;
  try {
    previous = JSON.parse(window.sessionStorage.getItem(key) || "null");
  } catch (_error) {
    previous = null;
  }
  rememberMatchLayout(current);
  if (!Array.isArray(previous) || reducedMatchMotion.matches) return;
  const previousPositions = new Map(
    previous.map((item, index) => [String(item.record_id), { index, disposition: item.disposition }]),
  );
  window.requestAnimationFrame(() => {
    current.forEach((item, index) => {
      const old = previousPositions.get(String(item.record_id));
      if (!old || (old.index === index && old.disposition === item.disposition)) return;
      const direction = Math.sign(old.index - index) || 1;
      const card = [...matchLayoutSurface.querySelectorAll("[data-match-result-card]")]
        .find((candidate) => candidate.dataset.matchRecordId === String(item.record_id));
      if (card) animateMatchCard(card, 0, direction * 18);
    });
  });
};

const applyAuthoritativeMatchLayout = (layout) => {
  if (!matchLayoutSurface || !layout || !Array.isArray(layout.items)) return;
  if (
    matchLayoutSurface.dataset.matchRunId
    && String(layout.run_id) !== matchLayoutSurface.dataset.matchRunId
  ) {
    window.location.reload();
    return;
  }
  const cards = [...matchLayoutSurface.querySelectorAll("[data-match-result-card]")];
  const cardsById = new Map(cards.map((card) => [card.dataset.matchRecordId, card]));
  const authoritativeIds = new Set(layout.items.map((item) => String(item.record_id)));
  if (
    cards.length !== authoritativeIds.size
    || layout.items.some((item) => !cardsById.has(String(item.record_id)))
  ) {
    window.location.reload();
    return;
  }

  const before = new Map(cards.map((card) => [card.dataset.matchRecordId, {
    bounds: card.getBoundingClientRect(),
    disposition: card.dataset.matchDisposition,
  }]));
  for (const item of layout.items) {
    const recordId = String(item.record_id);
    const card = cardsById.get(recordId);
    const grid = matchLayoutSurface.querySelector(`[data-match-grid="${item.disposition}"]`);
    if (!card || !grid) continue;
    card.dataset.matchPosition = String(item.position);
    card.dataset.matchDisposition = item.disposition;
    grid.append(card);
  }

  for (const disposition of ["top", "stretch", "blocked"]) {
    const count = Number.parseInt(String(layout.counts?.[disposition] ?? 0), 10);
    const grid = matchLayoutSurface.querySelector(`[data-match-grid="${disposition}"]`);
    const empty = matchLayoutSurface.querySelector(`[data-match-empty="${disposition}"]`);
    if (grid) grid.hidden = count === 0;
    if (empty) empty.hidden = count !== 0;
    for (const output of document.querySelectorAll(
      `[data-match-summary-count="${disposition}"], [data-match-section-count="${disposition}"]`,
    )) {
      output.textContent = String(count);
    }
  }
  matchLayoutSurface.dispatchEvent(new Event("selection:refresh"));
  rememberMatchLayout(layout.items);
  if (reducedMatchMotion.matches) return;

  window.requestAnimationFrame(() => {
    for (const card of cards) {
      const old = before.get(card.dataset.matchRecordId);
      if (!old) continue;
      const current = card.getBoundingClientRect();
      const changedGroup = old.disposition !== card.dataset.matchDisposition;
      const clamp = (value, maximum) => Math.max(-maximum, Math.min(maximum, value));
      const horizontalShift = changedGroup ? 0 : clamp(old.bounds.left - current.left, 64);
      const verticalShift = changedGroup
        ? (Math.sign(old.bounds.top - current.top) || 1) * 22
        : clamp(old.bounds.top - current.top, 64);
      animateMatchCard(card, horizontalShift, verticalShift);
    }
  });
};

const applyOpportunityLayout = (layout) => {
  if (!layout || !Array.isArray(layout.items)) return;
  const itemsById = new Map(layout.items.map((item) => [String(item.record_id), item]));
  for (const surface of document.querySelectorAll("[data-ranked-opportunity-surface]")) {
    const mode = surface.dataset.rankedOpportunitySurface;
    const cards = [...surface.querySelectorAll("[data-opportunity-card]")];
    const cardsById = new Map(cards.map((card) => [card.dataset.opportunityRecordId, card]));
    const order = mode === "home" ? layout.home_order : layout.archive_order;
    if (!Array.isArray(order)) continue;
    if (
      mode === "home"
      && (
        order.length !== cards.length
        || order.some((recordId) => !cardsById.has(String(recordId)))
      )
    ) {
      window.location.reload();
      return;
    }
    const before = new Map(cards.map((card) => [card.dataset.opportunityRecordId, {
      bounds: card.getBoundingClientRect(),
      disposition: card.dataset.cardDisposition,
    }]));
    for (const card of cards) {
      const item = itemsById.get(card.dataset.opportunityRecordId);
      if (!item) continue;
      card.dataset.cardScore = item.score === null || item.score === undefined
        ? ""
        : String(item.score);
      card.dataset.cardDisposition = item.disposition || "";
      for (const score of card.querySelectorAll("[data-card-score]")) {
        if (item.score !== null && item.score !== undefined) score.textContent = String(item.score);
      }
      for (const label of card.querySelectorAll("[data-card-disposition-label]")) {
        label.classList.remove("top", "stretch", "blocked");
        if (item.disposition) label.classList.add(item.disposition);
        if (item.disposition_label) label.textContent = item.disposition_label;
      }
    }
    const orderedIds = new Set(order.map(String));
    for (const recordId of order) {
      const card = cardsById.get(String(recordId));
      if (card) surface.append(card);
    }
    for (const card of cards) {
      if (!orderedIds.has(card.dataset.opportunityRecordId)) surface.append(card);
    }
    if (reducedMatchMotion.matches) {
      surface.dispatchEvent(new Event("ranking:refresh", { bubbles: true }));
      continue;
    }
    window.requestAnimationFrame(() => {
      for (const card of cards) {
        const old = before.get(card.dataset.opportunityRecordId);
        if (!old) continue;
        const current = card.getBoundingClientRect();
        const changedGroup = old.disposition !== card.dataset.cardDisposition;
        const clamp = (value, maximum) => Math.max(-maximum, Math.min(maximum, value));
        animateMatchCard(
          card,
          changedGroup ? 0 : clamp(old.bounds.left - current.left, 64),
          changedGroup
            ? (Math.sign(old.bounds.top - current.top) || 1) * 22
            : clamp(old.bounds.top - current.top, 64),
        );
      }
      surface.dispatchEvent(new Event("ranking:refresh", { bubbles: true }));
    });
  }
};

const applyCompatibilityUpdates = (updates, layout = null, opportunityLayout = null) => {
  const authoritativeUpdates = layout && Array.isArray(layout.items) ? layout.items : updates;
  applyAuthoritativeMatchLayout(layout);
  updateCompatibilitySurfaces(authoritativeUpdates);
  applyOpportunityLayout(opportunityLayout);
};

if (matchLayoutSurface) {
  animateLoadedMatchLayout();
}
if (document.querySelector("[data-job-rating-control], [data-employer-rating-control]")) {
  window.addEventListener("pageshow", (event) => {
    if (event.persisted) window.location.reload();
  });
}

const syncRatingControls = (kind, recordIds, stars) => {
  if (!Array.isArray(recordIds)) return;
  const ids = new Set(recordIds.map(String));
  const selector = kind === "job" ? "[data-job-rating-control]" : "[data-employer-rating-control]";
  for (const peer of document.querySelectorAll(selector)) {
    if (ids.has(peer.dataset.ratingRecordId)) renderRatingControl(peer, kind, stars);
  }
};

const activeRatingScopes = new Set();

const ratingPeers = (control, kind) => {
  const selector = kind === "job" ? "[data-job-rating-control]" : "[data-employer-rating-control]";
  const scope = control.dataset.ratingScope;
  if (!scope) return [control];
  return [...document.querySelectorAll(selector)]
    .filter((candidate) => candidate.dataset.ratingScope === scope);
};

const setRatingPeerDisabled = (peers, kind, disabled) => {
  const buttonSelector = kind === "job"
    ? "[data-job-rating-value], [data-job-rating-clear]"
    : "[data-employer-rating-value], [data-employer-rating-clear]";
  for (const peer of peers) {
    for (const button of peer.querySelectorAll(buttonSelector)) button.disabled = disabled;
  }
};

const setRatingPeerStatus = (peers, kind, message) => {
  const selector = kind === "job" ? "[data-job-rating-status]" : "[data-employer-rating-status]";
  for (const peer of peers) {
    const status = peer.querySelector(selector);
    if (status) status.textContent = message;
  }
};

const saveRating = async (control, kind, url, stars) => {
  const scope = control.dataset.ratingScope || `${kind}:${control.dataset.ratingRecordId}`;
  if (activeRatingScopes.has(scope)) return;
  activeRatingScopes.add(scope);
  const peers = ratingPeers(control, kind);
  const previous = new Map(peers.map((peer) => [
    peer,
    peer.dataset.currentRating === ""
      ? null
      : Number.parseInt(peer.dataset.currentRating, 10),
  ]));
  const form = new FormData();
  if (stars !== null) form.set("stars", String(stars));
  setRatingPeerDisabled(peers, kind, true);
  setRatingPeerStatus(peers, kind, " · Saving…");
  for (const peer of peers) renderRatingControl(peer, kind, stars);

  let saved;
  try {
    const response = await fetch(url, {
      method: "POST",
      body: form,
      credentials: "same-origin",
      headers: { Accept: "application/json" },
    });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    saved = await response.json();
  } catch (_error) {
    for (const [peer, previousStars] of previous) {
      renderRatingControl(peer, kind, previousStars);
    }
    setRatingPeerStatus(peers, kind, " · Could not save — try again");
    setRatingPeerDisabled(peers, kind, false);
    activeRatingScopes.delete(scope);
    return;
  }

  const savedStars = saved.stars === null || saved.stars === undefined
    ? null
    : Number.parseInt(String(saved.stars), 10);
  for (const peer of peers) renderRatingControl(peer, kind, savedStars);
  syncRatingControls(kind, saved.rating_record_ids, savedStars);
  let rankingWarning = saved.ranking_warning || "";
  try {
    applyCompatibilityUpdates(
      saved.score_updates,
      saved.match_layout,
      saved.opportunity_layout,
    );
  } catch (_error) {
    rankingWarning = "The rating was saved, but the new ranking layout could not be shown. Refresh to load it.";
  }
  setRatingPeerStatus(
    peers,
    kind,
    ` · ${rankingWarning || saved.message || "Saved"}`,
  );
  setRatingPeerDisabled(peers, kind, false);
  activeRatingScopes.delete(scope);
};

for (const control of document.querySelectorAll("[data-job-rating-control]")) {
  const ratingButtons = [...control.querySelectorAll("[data-job-rating-value]")];
  const clearButton = control.querySelector("[data-job-rating-clear]");

  ratingButtons.forEach((button) => {
    button.addEventListener("click", () => {
      saveRating(
        control,
        "job",
        control.dataset.ratingUrl,
        Number.parseInt(button.dataset.jobRatingValue, 10),
      );
    });
  });
  clearButton?.addEventListener("click", () => (
    saveRating(control, "job", control.dataset.clearUrl, null)
  ));
}

for (const control of document.querySelectorAll("[data-employer-rating-control]")) {
  const ratingButtons = [...control.querySelectorAll("[data-employer-rating-value]")];
  const clearButton = control.querySelector("[data-employer-rating-clear]");

  ratingButtons.forEach((button) => {
    button.addEventListener("click", () => {
      saveRating(
        control,
        "employer",
        control.dataset.ratingUrl,
        Number.parseInt(button.dataset.employerRatingValue, 10),
      );
    });
  });
  clearButton?.addEventListener("click", () => (
    saveRating(control, "employer", control.dataset.clearUrl, null)
  ));
}

const evidenceBulkForm = document.querySelector("[data-evidence-bulk-form]");
const evidenceBulkActions = document.querySelector("[data-evidence-bulk-actions]");
for (const editor of document.querySelectorAll("[data-employer-types-editor]")) {
  const value = editor.querySelector("[data-employer-types-value]");
  const checkboxes = [...editor.querySelectorAll("[data-employer-type-checkbox]")];
  if (!value || checkboxes.length === 0) continue;
  const render = () => {
    const selected = new Set(value.value.split(",").map((item) => item.trim()).filter(Boolean));
    for (const checkbox of checkboxes) checkbox.checked = selected.has(checkbox.value);
  };
  const update = () => {
    value.value = checkboxes
      .filter((checkbox) => checkbox.checked)
      .map((checkbox) => checkbox.value)
      .sort()
      .join(",");
    value.dispatchEvent(new Event("input", { bubbles: true }));
  };
  for (const checkbox of checkboxes) checkbox.addEventListener("change", update);
  value.addEventListener("input", render);
  render();
}
if (evidenceBulkForm && evidenceBulkActions) {
  const edits = [...document.querySelectorAll("[data-evidence-edit]")]
    .map((element) => ({
      element,
      input: element.querySelector("[data-evidence-input]"),
      initial: element.querySelector(
        '[data-evidence-initial], input[name="evidence_initial"]',
      ),
    }))
    .filter(({ input, initial }) => input && initial);
  const count = evidenceBulkActions.querySelector("[data-evidence-change-count]");
  const evidenceValue = (input) =>
    input.type === "checkbox" ? String(input.checked) : input.value;

  const refreshEvidenceChanges = () => {
    let dirty = 0;
    for (const edit of edits) {
      const changed = evidenceValue(edit.input) !== edit.initial.value;
      edit.element.classList.toggle("is-dirty", changed);
      if (changed) dirty += 1;
    }
    if (count) count.textContent = String(dirty);
    evidenceBulkActions.hidden = dirty === 0;
    return dirty;
  };

  for (const { input } of edits) {
    input.addEventListener("input", refreshEvidenceChanges);
    input.addEventListener("change", refreshEvidenceChanges);
  }
  evidenceBulkActions.querySelector("[data-evidence-reset]")?.addEventListener("click", () => {
    for (const { input, initial } of edits) {
      if (input.type === "checkbox") input.checked = initial.value === "true";
      else {
        input.value = initial.value;
        input.dispatchEvent(new Event("input", { bubbles: true }));
      }
    }
    refreshEvidenceChanges();
  });
  evidenceBulkForm.addEventListener("submit", (event) => {
    if (refreshEvidenceChanges() === 0) event.preventDefault();
  });
  refreshEvidenceChanges();
}

for (const button of document.querySelectorAll("[data-suggestion-target]")) {
  button.addEventListener("click", () => {
    const textarea = document.getElementById(button.dataset.suggestionTarget);
    if (!textarea) return;
    const suggestion = button.dataset.suggestionText.trim();
    const existing = textarea.value.trimEnd();
    const separator = existing ? (existing.endsWith(".") ? "\n" : ".\n") : "";
    textarea.value = `${existing}${separator}${suggestion}: `;
    textarea.dispatchEvent(new Event("input", { bubbles: true }));
    textarea.focus();
    textarea.setSelectionRange(textarea.value.length, textarea.value.length);
  });
}

const busyOverlay = document.querySelector("[data-busy-overlay]");
const busyTitle = busyOverlay?.querySelector("[data-busy-title]");

const hideBusyOverlay = () => {
  if (!busyOverlay) return;
  busyOverlay.hidden = true;
  document.body.classList.remove("is-busy");
};

const resetBusyState = () => {
  hideBusyOverlay();
  for (const form of document.querySelectorAll("form[data-submitting]")) {
    delete form.dataset.submitting;
    form.dispatchEvent(new Event("selection:refresh"));
  }
};

for (const form of document.querySelectorAll("form")) {
  form.addEventListener("submit", (event) => {
    if (event.defaultPrevented) return;
    const submitter = event.submitter;
    const message = submitter?.dataset.busyMessage || form.dataset.busyMessage;
    if (!message || !busyOverlay || !busyTitle) return;
    if (form.dataset.submitting === "true") {
      event.preventDefault();
      return;
    }
    form.dataset.submitting = "true";
    busyTitle.textContent = message;
    busyOverlay.hidden = false;
    document.body.classList.add("is-busy");
  });
}

window.addEventListener("pageshow", hideBusyOverlay);
window.addEventListener("pageshow", resetBusyState);

const fragmentParameters = new URLSearchParams(window.location.hash.slice(1));
for (const tokenInput of document.querySelectorAll("[data-fragment-token]")) {
  const token = fragmentParameters.get("token");
  if (!token) continue;
  tokenInput.value = token;
  for (const control of document.querySelectorAll("[data-token-required]")) {
    control.disabled = false;
  }
  document.querySelector("[data-token-missing]")?.setAttribute("hidden", "");
  window.history.replaceState(null, "", `${window.location.pathname}${window.location.search}`);
}

for (const copyButton of document.querySelectorAll("[data-copy-button]")) {
  copyButton.addEventListener("click", async () => {
    const value = document.querySelector("[data-copy-value]")?.textContent?.trim();
    const status = document.querySelector("[data-copy-status]");
    if (!value) return;
    try {
      await navigator.clipboard.writeText(value);
      if (status) status.textContent = "Copied. Send it only to the intended person.";
    } catch (_error) {
      if (status) status.textContent = "Select and copy the link manually.";
    }
  });
}

const operationsRefresh = document.querySelector("[data-operations-auto-refresh]");
if (operationsRefresh) {
  const refreshSeconds = Math.max(
    3,
    Number.parseInt(operationsRefresh.dataset.refreshSeconds || "5", 10),
  );
  window.setTimeout(() => {
    if (document.visibilityState === "visible") {
      window.location.reload();
    }
  }, refreshSeconds * 1000);
}

const taskProgress = document.querySelector("[data-task-progress]");
if (taskProgress) {
  const progressBar = taskProgress.querySelector("[data-task-progress-bar]");
  const percent = taskProgress.querySelector("[data-task-percent]");
  const percentWrap = taskProgress.querySelector("[data-task-percent-wrap]");
  const indeterminate = taskProgress.querySelector("[data-task-indeterminate]");
  const phase = taskProgress.querySelector("[data-task-phase]");
  const message = taskProgress.querySelector("[data-task-message]");
  const attempt = taskProgress.querySelector("[data-task-attempt]");
  const updated = taskProgress.querySelector("[data-task-updated]");
  const error = taskProgress.querySelector("[data-task-error]");
  const errorMessage = taskProgress.querySelector("[data-task-error-message]");
  const workerError = taskProgress.querySelector("[data-task-worker-error]");
  const workerErrorTitle = taskProgress.querySelector("[data-task-worker-error-title]");
  const workerErrorMessage = taskProgress.querySelector("[data-task-worker-error-message]");
  const cancelled = taskProgress.querySelector("[data-task-cancelled]");
  const stopping = taskProgress.querySelector("[data-task-stopping]");
  const cancelForm = taskProgress.querySelector("[data-task-cancel-form]");
  const cancelButton = taskProgress.querySelector("[data-task-cancel-button]");
  const waitingMessage = taskProgress.querySelector("[data-task-waiting-message]");
  const explorePreview = document.querySelector("[data-explore-progress-preview]");
  const explorePreviewList = explorePreview?.querySelector("[data-explore-preview-list]");
  const explorePreviewCount = explorePreview?.querySelector("[data-explore-preview-count]");
  const titleCase = (value) => value
    .replaceAll("_", " ")
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
  let explorePreviewSignature = "";
  const configuredPreviewLimit = Number.parseInt(
    explorePreview?.dataset.previewLimit || "9",
    10,
  );
  const explorePreviewLimit = Number.isFinite(configuredPreviewLimit)
    ? Math.max(3, Math.min(12, configuredPreviewLimit))
    : 9;
  const EXPLORE_PROGRESS_CEILING = 94;
  const EXPLORE_PROGRESS_HORIZON_MS = 9 * 60 * 1000;

  // Explore providers expose useful phases and previews but no shared unit
  // count while their independent HTTP calls are in flight.  Reconstruct a
  // deliberately slow display estimate from the persisted task start time so
  // reloads and other tabs do not jump back to zero.  Stored progress always
  // wins when it is further ahead, and only terminal success can reach 100%.
  const exploreDisplayPercent = (task) => {
    const stored = Number.isFinite(Number(task.progress_percent))
      ? Math.max(0, Math.min(100, Number(task.progress_percent)))
      : 0;
    if (task.kind !== "explore_search" || task.status !== "running" || !task.started_at) {
      return { percent: stored, estimated: false };
    }
    const startedAt = Date.parse(task.started_at);
    if (!Number.isFinite(startedAt)) return { percent: stored, estimated: false };
    const elapsed = Math.max(0, Date.now() - startedAt);
    const position = Math.min(1, elapsed / EXPLORE_PROGRESS_HORIZON_MS);
    const estimate = Math.floor(
      EXPLORE_PROGRESS_CEILING * (1 - ((1 - position) ** 2)),
    );
    return {
      percent: Math.min(EXPLORE_PROGRESS_CEILING, Math.max(stored, estimate)),
      estimated: true,
    };
  };

  const previewPill = (text, className = "") => {
    const pill = document.createElement("span");
    pill.className = `explore-progress-preview-pill ${className}`.trim();
    pill.textContent = text;
    return pill;
  };
  const hasPreviewNumber = (value) => (
    value !== null && value !== undefined && value !== "" && Number.isFinite(Number(value))
  );

  const renderExplorePreview = (rawRows) => {
    if (!explorePreview || !explorePreviewList || !explorePreviewCount) return;
    const rows = Array.isArray(rawRows) ? rawRows.slice(0, explorePreviewLimit) : [];
    const signature = JSON.stringify(rows);
    if (signature === explorePreviewSignature) return;
    explorePreviewSignature = signature;
    explorePreviewList.replaceChildren();
    explorePreviewCount.textContent = String(rows.length);
    explorePreview.hidden = rows.length === 0;
    if (!rows.length) return;

    for (const row of rows) {
      const card = document.createElement("article");
      card.className = "explore-progress-preview-card";

      const lead = document.createElement("div");
      lead.className = "explore-progress-preview-lead";
      lead.append(previewPill(`#${row.rank}`, "is-rank"));
      const identity = document.createElement("div");
      const title = document.createElement("h3");
      title.textContent = row.title || "Job title pending";
      const company = document.createElement("p");
      company.textContent = `${row.company || "Employer pending"} · ${row.location || "Location pending"}${row.remote ? " · Remote" : ""}`;
      identity.append(title, company);
      lead.append(identity);
      card.append(lead);

      const evidence = document.createElement("div");
      evidence.className = "explore-progress-preview-evidence";
      if (hasPreviewNumber(row.search_score)) {
        evidence.append(previewPill(`${row.search_score}% current rank`));
      }
      if (hasPreviewNumber(row.role_relevance)) {
        evidence.append(previewPill(`${row.role_relevance}% role fit`));
      }
      if (hasPreviewNumber(row.seniority_relevance)) {
        evidence.append(previewPill(`${row.seniority_relevance}% seniority`));
      }
      if (hasPreviewNumber(row.distance_km)) {
        evidence.append(previewPill(`${Math.round(Number(row.distance_km))} km`));
      } else if (row.remote) {
        evidence.append(previewPill("Remote"));
      } else {
        evidence.append(previewPill("Distance pending", "is-pending"));
      }
      if (row.is_own) {
        evidence.append(previewPill("Own", "is-own"));
      }
      if (row.provider_label && (!row.is_own || row.provider_label !== "Own")) {
        evidence.append(previewPill(row.provider_label, "is-provider"));
      }
      if (row.readiness_label) {
        evidence.append(previewPill(row.readiness_label, `is-${row.readiness || "listed"}`));
      }
      for (const tag of Array.isArray(row.tags) ? row.tags : []) {
        evidence.append(previewPill(tag));
      }
      card.append(evidence);
      explorePreviewList.append(card);
    }
  };

  const pollTask = async () => {
    try {
      const response = await fetch(taskProgress.dataset.statusUrl, {
        headers: { Accept: "application/json" },
        cache: "no-store",
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const task = await response.json();
      const terminal = ["succeeded", "failed", "cancelled"].includes(task.status);
      const displayProgress = exploreDisplayPercent(task);
      if (task.progress_indeterminate && !displayProgress.estimated) {
        progressBar.removeAttribute("value");
        if (percentWrap) percentWrap.hidden = true;
        if (indeterminate) indeterminate.hidden = false;
      } else {
        progressBar.value = displayProgress.percent;
        percent.textContent = String(displayProgress.percent);
        if (percentWrap) percentWrap.hidden = false;
        if (indeterminate) indeterminate.hidden = true;
      }
      phase.textContent = titleCase(task.phase);
      message.textContent = task.message;
      attempt.textContent = `Attempt ${Math.max(1, task.attempt)} of ${task.max_attempts}. You can leave this page because the stored task will continue in the background.`;
      renderExplorePreview(task.preview);
      if (updated && task.updated_at) {
        const updatedAt = new Date(task.updated_at);
        updated.dateTime = task.updated_at;
        updated.textContent = Number.isNaN(updatedAt.valueOf())
          ? task.updated_at
          : updatedAt.toLocaleTimeString();
      }
      if (workerError) {
        workerError.hidden = task.worker_running || terminal;
        if (!workerError.hidden && task.status === "running" && task.lease_fresh === false) {
          if (workerErrorTitle) workerErrorTitle.textContent = "The worker lease expired.";
          if (workerErrorMessage) {
            workerErrorMessage.textContent = (
              "The task remains stored and is waiting for a worker to recover it safely."
            );
          }
        }
      }
      if (cancelForm) {
        cancelForm.hidden = terminal || Boolean(task.cancel_requested_at);
      }
      if (cancelButton) {
        cancelButton.disabled = terminal || Boolean(task.cancel_requested_at);
        cancelButton.textContent = "Abort task";
      }
      if (stopping) stopping.hidden = terminal || !task.cancel_requested_at;
      if (task.status === "succeeded" && task.result_url) {
        window.location.replace(task.result_url);
        return;
      }
      if (task.status === "failed") {
        error.hidden = false;
        errorMessage.textContent = task.error_message || "The workflow could not finish.";
        taskProgress.querySelector(".working-spinner")?.classList.add("is-stopped");
        if (waitingMessage) waitingMessage.hidden = true;
        return;
      }
      if (task.status === "cancelled") {
        if (cancelled) cancelled.hidden = false;
        taskProgress.querySelector(".working-spinner")?.classList.add("is-stopped");
        if (waitingMessage) waitingMessage.hidden = true;
        return;
      }
    } catch (_error) {
      message.textContent = "The progress connection paused, and the stored workflow is reconnecting…";
    }
    window.setTimeout(pollTask, 750);
  };
  cancelForm?.addEventListener("submit", () => {
    cancelForm.hidden = true;
    if (cancelButton) cancelButton.disabled = true;
    if (stopping) stopping.hidden = false;
  });
  window.setTimeout(pollTask, 250);
}

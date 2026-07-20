const categories = [
  ["knowledge", "Knowledge", "◫"], ["skills", "Skills", "◇"],
  ["progress", "Progress", "◷"], ["artifacts", "Artifacts", "↗"],
];
let state = { knowledge: [], skills: [], progress: [], artifacts: [] };
let activeCategory = "progress";
let selectedIndex = -1;

const byId = (id) => document.getElementById(id);
const escapeHtml = (value) => String(value ?? "").replace(/[&<>"']/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[char]);
const titleOf = (entry) => entry.title || entry.name || entry.id || "Untitled";
const bodyOf = (entry) => entry.summary || entry.description || entry.outcome || "No description yet.";

function filteredEntries() {
  const query = byId("search").value.trim().toLowerCase();
  const status = byId("filter").value;
  return (state[activeCategory] || []).filter((entry) => {
    const text = `${titleOf(entry)} ${bodyOf(entry)} ${entry.path || ""}`.toLowerCase();
    return (!query || text.includes(query)) && (status === "all" || entry.status === status);
  });
}

function renderNavigation() {
  byId("navigation").innerHTML = categories.map(([key, label, icon]) => `<button class="nav-item ${key === activeCategory ? "active" : ""}" data-category="${key}"><span class="nav-label"><span aria-hidden="true">${icon}</span>${label}</span><span class="nav-count">${(state[key] || []).length}</span></button>`).join("");
  document.querySelectorAll("[data-category]").forEach((button) => button.addEventListener("click", () => selectCategory(button.dataset.category)));
}

function renderList() {
  const entries = filteredEntries();
  byId("result-count").textContent = `${entries.length} ${entries.length === 1 ? "item" : "items"}`;
  byId("entry-list").innerHTML = entries.length ? entries.map((entry, index) => `<button class="entry ${index === selectedIndex ? "active" : ""}" data-index="${index}"><div class="entry-header"><span class="entry-title">${escapeHtml(titleOf(entry))}</span>${entry.status ? `<span class="status">${escapeHtml(entry.status.replaceAll("_", " "))}</span>` : ""}</div><div class="entry-meta">${escapeHtml(entry.path || entry.updated_at || "Project entry")}</div><div class="entry-summary">${escapeHtml(bodyOf(entry))}</div></button>`).join("") : `<div class="empty-detail" style="min-height:20rem"><p>No matching entries.</p></div>`;
  document.querySelectorAll("[data-index]").forEach((button) => button.addEventListener("click", () => selectEntry(Number(button.dataset.index))));
}

function selectCategory(category) {
  activeCategory = category; selectedIndex = -1;
  byId("page-title").textContent = categories.find(([key]) => key === category)?.[1] || category;
  byId("filter").hidden = category !== "progress";
  renderNavigation(); renderList(); renderDetail();
}

function selectEntry(index) { selectedIndex = index; renderList(); renderDetail(); }

function renderDetail() {
  const entry = filteredEntries()[selectedIndex];
  byId("detail").innerHTML = entry ? `<header><p class="eyebrow">${escapeHtml(activeCategory.toUpperCase())}</p><h2>${escapeHtml(titleOf(entry))}</h2><p class="detail-path">${escapeHtml(entry.path || entry.id || "")}</p></header><div class="detail-body">${escapeHtml(bodyOf(entry))}</div>` : `<div class="empty-detail"><span class="empty-icon" aria-hidden="true">◇</span><h2>Select an entry</h2><p>Choose an item to inspect its content, history, and artifacts.</p></div>`;
}

async function load() {
  const response = await fetch("/api/state");
  if (!response.ok) throw new Error("Could not load project state");
  state = await response.json();
  state.artifacts ||= state.progress.flatMap((entry) => (entry.artifacts || []).map((path) => ({ title: path, path, summary: `Produced by ${entry.title}` })));
  byId("project-root").textContent = state.root;
  renderNavigation(); renderList(); renderDetail();
}

byId("search").addEventListener("input", () => { selectedIndex = -1; renderList(); renderDetail(); });
byId("filter").addEventListener("change", () => { selectedIndex = -1; renderList(); renderDetail(); });
byId("new-entry").addEventListener("click", () => window.alert("[v0] Entry editor arrives in the full build."));
load().catch((error) => { byId("entry-list").innerHTML = `<div class="empty-detail"><p>${escapeHtml(error.message)}</p></div>`; });

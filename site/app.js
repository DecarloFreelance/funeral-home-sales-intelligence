const state = { records: [], filtered: [] };

const byId = (id) => document.getElementById(id);
const text = (value) => (value || "").toString().trim();

function labelFor(record) {
  return text(record.name) || `Unnamed ${record.entity_type || "business"}`;
}

function websiteLabel(record) {
  const labels = {
    candidate: "Website candidate",
    rejected: "Website rejected",
    review: "Website under review",
    selected: "Website selected",
  };
  return labels[record.website_status] || "No website signal";
}

function populateProvinces(records) {
  const values = [...new Set(records.map((record) => text(record.province)).filter(Boolean))].sort();
  const select = byId("province");
  values.forEach((value) => {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = value;
    select.appendChild(option);
  });
}

function updateStats(records, generatedAt) {
  byId("total-count").textContent = records.length.toLocaleString();
  byId("named-count").textContent = records.filter((record) => text(record.name)).length.toLocaleString();
  byId("website-count").textContent = records.filter((record) => text(record.website_url)).length.toLocaleString();
  byId("province-count").textContent = new Set(records.map((record) => text(record.province)).filter(Boolean)).size.toLocaleString();
  byId("generated").textContent = generatedAt ? `Snapshot generated ${new Date(generatedAt).toLocaleDateString()}` : "Snapshot date unavailable";
}

function matches(record) {
  const query = text(byId("search").value).toLocaleLowerCase();
  const province = byId("province").value;
  const website = byId("website").value;
  const haystack = [record.name, record.city, record.province, ...(record.source_names || [])].join(" ").toLocaleLowerCase();
  const queryMatch = !query || haystack.includes(query);
  const provinceMatch = !province || record.province === province;
  const websiteMatch = !website || (website === "yes" && text(record.website_url)) || (website === "no" && !text(record.website_url)) || record.website_status === website;
  return queryMatch && provinceMatch && websiteMatch;
}

function render() {
  state.filtered = state.records.filter(matches);
  const cards = byId("cards");
  cards.replaceChildren();
  byId("result-count").textContent = `${state.filtered.length.toLocaleString()} of ${state.records.length.toLocaleString()} records`;
  if (!state.filtered.length) {
    const empty = document.createElement("p");
    empty.className = "empty";
    empty.textContent = "No records match those filters.";
    cards.appendChild(empty);
    return;
  }
  state.filtered.forEach((record) => {
    const card = document.createElement("article");
    card.className = "card";
    const body = document.createElement("div");
    const heading = document.createElement("h3");
    heading.textContent = labelFor(record);
    const place = document.createElement("p");
    place.className = "place";
    place.textContent = [record.city, record.province].filter(Boolean).join(", ") || "Location not yet normalized";
    body.append(heading, place);
    const tags = document.createElement("div");
    tags.className = "tags";
    [record.entity_type === "branch" ? "Branch" : "Organization", websiteLabel(record)].forEach((value) => {
      const tag = document.createElement("span");
      tag.className = `tag ${record.website_status || ""}`;
      tag.textContent = value;
      tags.appendChild(tag);
    });
    body.appendChild(tags);
    card.appendChild(body);
    if (record.website_url) {
      const link = document.createElement("a");
      link.href = record.website_url;
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      link.textContent = "View website signal ↗";
      card.appendChild(link);
    }
    cards.appendChild(card);
  });
}

function clearFilters() {
  byId("search").value = "";
  byId("province").value = "";
  byId("website").value = "";
  render();
}

fetch("data/directory.json")
  .then((response) => {
    if (!response.ok) throw new Error(`Directory request failed: ${response.status}`);
    return response.json();
  })
  .then((payload) => {
    state.records = Array.isArray(payload.records) ? payload.records : [];
    populateProvinces(state.records);
    updateStats(state.records, payload.generated_at);
    render();
  })
  .catch((error) => {
    byId("cards").textContent = `The directory could not be loaded: ${error.message}`;
    byId("result-count").textContent = "Directory unavailable";
  });

["search", "province", "website"].forEach((id) => byId(id).addEventListener("input", render));
byId("clear").addEventListener("click", clearFilters);

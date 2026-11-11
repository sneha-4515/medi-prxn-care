const $ = s => document.querySelector(s);
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const S = { token: sessionStorage.token, role: sessionStorage.role, view: null, family: [], dash: [], sel: "all", D: {}, chatPid: null, draft: null, docId: null };

function toast(msg, err) { const t = $("#toast"); t.textContent = msg; t.className = "show" + (err ? " err" : ""); clearTimeout(toast.t); toast.t = setTimeout(() => t.className = "", 3200); }
async function api(path, o = {}) {
  const opt = { method: o.method || "GET", headers: { ...(S.token ? { Authorization: "Bearer " + S.token } : {}) } };
  if (o.json) { opt.method = o.method || "POST"; opt.headers["Content-Type"] = "application/json"; opt.body = JSON.stringify(o.json); }
  if (o.form) { opt.method = "POST"; opt.body = o.form; }
  const r = await fetch(path, opt);
  if (r.status === 401 && S.token) { logout(); throw new Error("Session expired"); }
  if (!r.ok) { let d = await r.json().catch(() => ({})); throw new Error(typeof d.detail === "string" ? d.detail : r.status >= 500 ? "Server error. Please try again." : "Please check what you entered"); }
  return o.text ? r.text() : r.json();
}
const guard = fn => async (...a) => { try { await fn(...a); } catch (e) { toast(e.message, true); } };

/* ---------- auth ---------- */
function authView(mode = "login") {
  $("#app").innerHTML = `<div class="auth">
  <section class="hero"><div class="auth-logo"><img src="/logo.png" alt="Medi-Prxn Care"></div>
    <h1>Smarter care for your whole family.</h1>
    <p>Ask the AI assistant about a symptom, keep every prescription and reminder in one place, and book a doctor with secure PayPal checkout.</p>
    <ul class="auth-points"><li>AI health assistant with emergency safety checks</li><li>Prescriptions, refills and family profiles</li><li>Consultations paid with PayPal</li></ul></section>
  <form onsubmit="return false">
    <img class="auth-mark" src="/logo-mark.png" alt=""><h2 class="auth-title">Welcome to Medi-Prxn Care</h2>
    <div class="tabs" role="tablist"><button role="tab" aria-selected="${mode==='login'}" onclick="authView('login')">Log in</button><button role="tab" aria-selected="${mode==='signup'}" onclick="authView('signup')">Sign up</button></div>
    ${mode === "signup" ? `<label for="n">Name</label><input id="n" autocomplete="name"><label for="ag">Age</label><input id="ag" type="number" min="0" max="120"><label for="ro">I am a</label><select id="ro"><option value="patient">Patient / family</option><option value="doctor">Doctor</option></select>` : ""}
    <label for="em">Email</label><input id="em" type="email" autocomplete="email"><label for="pw">Password</label><input id="pw" type="password" autocomplete="${mode==='login'?'current-password':'new-password'}">
    <p><button id="go" class="pill" style="margin-top:1rem">${mode === "login" ? "Log in" : "Create account"}</button></p>
    ${mode === "login" ? `<div class="demo-note small"><b>Demo accounts</b><br>Patient: patient@mediprxncare.app / patient123<br>Doctor: doctor@mediprxncare.app / doctor123<br>Admin: admin@mediprxncare.app / admin123</div>` : ""}
  </form></div>`;
  $("#go").onclick = guard(async () => {
    const body = { email: $("#em").value, password: $("#pw").value };
    const r = mode === "login" ? await api("/auth/login", { json: body })
      : await api("/auth/signup", { json: { ...body, name: $("#n").value, role: $("#ro").value, age: +$("#ag").value || null } });
    S.token = sessionStorage.token = r.token; S.role = sessionStorage.role = r.role; boot();
  });
}
function logout() { unmountAssistant?.(); sessionStorage.clear(); S.token = S.role = null; authView(); }

/* ---------- shell ---------- */
const NAV = {
  patient: [["dash", "Dashboard", "dash", "Overview"], ["book", "Consultations", "book"], ["pay", "Payments", "pay"],
    ["home", "Family & medicines", "family", "Family health"], ["remind", "Reminders", "remind"], ["checkups", "Check-ups", "check"], ["record", "Health records", "records"], ["qr", "My QR code", "qr"],
    ["bills", "Bills & spending", "bills", "Money & care"], ["care", "Find care", "care"], ["chat", "Ask about records", "chat"], ["settings", "Settings", "settings", "Account"]],
  doctor: [["consult", "Consultation", "user"], ["chat", "Ask about patient", "chat"]],
  admin: [["register", "Reception", "user"], ["billing", "Billing", "bills"], ["providers", "Providers", "building"], ["bookings", "Bookings", "book"]]
};
async function boot() {
  if (!S.token) return authView();
  const me = await api("/me").catch(() => null); if (!me) return;
  S.me = me; S.view = NAV[S.role][0][0];
  if (S.role === "patient") S.family = await api("/family");
  shell(); startAlarms();
}
function shell() {
  const cur = (NAV[S.role].find(([id]) => id === S.view) || [, ""])[1], insecure = !window.isSecureContext;
  $("#app").innerHTML = `${insecure ? `<div class="banner" role="alert">This link is not secure (http). Your browser blocks location, live camera and voice here. Use the https link for those, or use the alternatives shown on each screen.</div>` : ""}<div class="shell"><nav class="side" aria-label="Main"><a class="logo" href="/" aria-label="Medi-Prxn Care home"><img src="/logo.png" alt="Medi-Prxn Care"></a>
    <span class="curr" aria-hidden="true">${esc(cur)}</span><button class="menu-btn" aria-expanded="false" aria-controls="navlist" onclick="toggleMenu(this)">Menu ☰</button>
    <div class="navlist" id="navlist">${NAV[S.role].map(([id, l, ic, grp]) => `${grp ? `<div class="grp">${grp}</div>` : ""}<button class="nav" ${S.view === id ? 'aria-current="page"' : ""} onclick="go('${id}')">${ico(ic)}${l}</button>`).join("")}<button class="nav nav-logout" onclick="logout()">Log out</button></div>
    <div class="who"><span class="whoname">${esc(S.me.name)}<br>${S.role}<br></span><button class="ghost sm" style="color:#fff;border-color:#fff;margin-top:.5rem" onclick="logout()">Log out</button></div></nav>
    <main class="main" id="main"></main></div>`;
  mountAssistant(); guard(VIEWS[S.view])();
}
function go(v) { S.view = v; shell(); window.scrollTo(0, 0); }
function toggleMenu(btn) { const open = $(".side").classList.toggle("open"); btn.setAttribute("aria-expanded", open); btn.textContent = open ? "Close ✕" : "Menu ☰"; }

/* ---------- patient: family health ---------- */
async function pHome() {
  S.dash = await api("/dashboard"); const m = $("#main");
  const list = S.sel === "all" ? S.dash : S.dash.filter(d => d.patient.id == S.sel);
  const due = S.dash.flatMap(d => d.active_medicines.filter(x => x.refill_due_in_days <= 0).map(x => ({ ...x, who: d.patient.name })));
  m.innerHTML = `<h1>Family &amp; medicines</h1>
  ${due.length ? `<div class="card" style="border-color:var(--warn)"><h3>Refills due</h3>${due.map(x => `<p>${esc(x.who)}: <b>${esc(x.medicine)}</b> ends ${esc(x.ends_on)} <a href="${esc(x.order_url)}" target="_blank" rel="noopener"><button class="pill sm">Order via Tata 1mg</button></a></p>`).join("")}</div>` : ""}
  ${S.dash.reduce((n, d) => n + d.checkups_attention, 0) ? `<div class="card" style="border-color:var(--ink)"><div class="row"><div class="grow"><h3 style="margin:0">Check-ups need attention</h3><p class="muted small">${S.dash.reduce((n, d) => n + d.checkups_overdue, 0)} overdue, ${S.dash.reduce((n, d) => n + d.checkups_attention, 0)} to review across the family.</p></div><button class="ghost sm" onclick="go('checkups')">Review check-ups</button></div></div>` : ""}
  <div class="chips" role="group" aria-label="Family member"><button class="chip" aria-pressed="${S.sel==='all'}" onclick="S.sel='all';pHome()">Everyone</button>
  ${S.dash.map(d => `<button class="chip" aria-pressed="${S.sel==d.patient.id}" onclick="S.sel=${d.patient.id};pHome()">${esc(d.patient.name)}${d.patient.relation !== "self" ? " (" + esc(d.patient.relation) + ")" : ""}</button>`).join("")}
  <button class="chip" onclick="addMember()">+ Add family member</button></div>
  ${list.map(d => `<section class="card"><div class="row"><h2 class="grow">${esc(d.patient.name)}</h2><span class="muted small">${d.patient.age ?? ""} yrs${d.patient.allergies ? " · allergic to " + esc(d.patient.allergies) : ""}</span><button class="ghost sm" onclick="addMember(${d.patient.id})">Edit</button>${d.patient.relation !== "self" ? `<button class="ghost sm" onclick="delMember(${d.patient.id})">Remove</button>` : ""}</div>
    ${d.private ? `<p class="muted">The doctor has marked these records private.</p>` : `
    <h3>Current medicines</h3>
    <div class="caps">${d.active_medicines.map(capsule).join("") || `<p class="muted">No active medicines. Add a record or ask the doctor to save one after the next visit.</p>`}</div>
    <h3 style="margin-top:1rem">Next follow-up</h3>${d.upcoming_followups.length ? d.upcoming_followups.map(f => `<p>${esc(f.next_followup)}</p>`).join("") : `<p class="muted">None scheduled.</p>`}
    <details style="margin-top:.75rem"><summary>Medicine timeline</summary>${d.timeline.map(t => `<p class="small">${esc(t.start_date)}: ${esc(t.medicine)} ${esc(t.dosage || "")} for ${t.duration_days ?? "?"} days</p>`).join("") || "<p class='muted small'>Nothing yet.</p>"}</details>`}
    </section>`).join("")}`;
}
function capsule(x) {
  const total = x.duration_days || 1, left = Math.max(0, Math.ceil((new Date(x.ends_on) - new Date(new Date().toDateString())) / 864e5));
  const pct = Math.min(100, Math.max(4, ((total - left) / total) * 100)), due = x.refill_due_in_days <= 0;
  return `<div class="cap ${due ? "due" : ""}"><div class="fill" style="width:${pct}%"></div><div class="body">
    <div><span class="name">${esc(x.medicine)} ${esc(x.dosage || "")}</span><div class="meta">${x.frequency_per_day ? x.frequency_per_day + "× a day" : ""} ${esc(x.timing || "")} · ${left} day${left === 1 ? "" : "s"} left${(x.dose_times || []).length ? " · " + x.dose_times.join(", ") : ""}</div></div>
    <a href="${esc(x.order_url)}" target="_blank" rel="noopener"><button class="${due ? "pill" : "ghost"} sm">Order via Tata 1mg</button></a></div></div>`;
}
function addMember(id) {
  const e = id ? S.family.find(f => f.id === id) : null; S.editing = e ? id : null;
  $("#main").innerHTML = `<h1>${e ? "Edit" : "Add"} family member</h1><div class="card" style="max-width:520px">
  <label>Name</label><input id="fn" value="${esc(e?.name)}"><label>Age</label><input id="fa" type="number" value="${esc(e?.age)}"><label>Relation</label><input id="fr" placeholder="mother, father, son…" value="${esc(e?.relation)}" ${e?.relation === "self" ? "disabled" : ""}>
  <label>Medical history (for the doctor's information)</label><textarea id="fh" rows="3">${esc(e?.self_reported_history)}</textarea><label>Allergies</label><input id="fal" placeholder="e.g. Penicillin" value="${esc(e?.allergies)}">
  <p><button onclick="saveMember()">Save member</button> <button class="ghost" onclick="pHome()">Cancel</button></p></div>`;
}
const delMember = guard(async id => { if (!confirm("Remove this family member and all their records from this app?")) return; await api(`/family/${id}`, { method: "DELETE" }); S.family = await api("/family"); S.sel = "all"; toast("Profile removed"); pHome(); });
const saveMember = guard(async () => {
  const body = { name: $("#fn").value, age: +$("#fa").value, relation: $("#fr").value, medical_history: $("#fh").value, allergies: $("#fal").value };
  if (S.editing) await api(`/family/${S.editing}`, { method: "PUT", json: body }); else await api("/family", { json: body });
  S.family = await api("/family"); toast(S.editing ? "Profile updated" : "Family member added"); S.editing = null; pHome();
});

/* ---------- patient: add record ---------- */
function pRecord() {
  S.recFile = null;
  S.rtab = S.rtab || "table"; const T = (id, l) => `<button role="tab" aria-selected="${S.rtab === id}" onclick="S.rtab='${id}';pRecord()">${l}</button>`;
  const sel = `<label for="rm">For</label><select id="rm">${S.family.map(f => `<option value="${f.id}">${esc(f.name)}${f.relation !== "self" ? " (" + esc(f.relation) + ")" : ""}</option>`).join("")}</select>`;
  $("#main").innerHTML = `<h1>Add a record</h1><div class="tabs" role="tablist">${T("table", "Fill the table")}${T("paper", "Upload case paper")}${T("tx", "Upload transcript")}${T("explain", "Explain a report")}</div>
  <div class="card" style="max-width:640px">${sel}
  ${S.rtab === "explain" ? explainTab() : S.rtab === "table" ? `<label>Medicine name</label><input id="mn"><label>Doctor visited</label><input id="md"><label>Cause</label><input id="mc"><label>Next follow-up</label><input id="mf" type="date">
    <label>Lab test recommended</label><input id="mlt"><label>Lab result (type NA if not applicable)</label><input id="mlr" value="NA"><p><button class="ok" onclick="saveManual()">Save record</button></p>`
    : S.rtab === "paper" ? `<label>Photo or scan of the case paper</label><div class="row"><label class="fbtn">Take a photo<input type="file" accept="image/*" capture="environment" class="sr-only" onchange="setRec(this)"></label>
      <label class="fbtn">Choose file<input id="rf" type="file" accept="image/*,application/pdf" class="sr-only" onchange="setRec(this)"></label><span id="rfn" class="small muted"></span></div><p><button onclick="pExtract('case_paper')">Read with AI</button></p>`
    : `<label>Paste transcript or choose a text/audio file</label><textarea id="rt" rows="5"></textarea><label class="fbtn">Choose a text or audio file<input id="rf" type="file" accept="text/*,audio/*" class="sr-only" onchange="setRec(this)"></label><span id="rfn" class="small muted"></span><p><button onclick="pExtract('transcript')">Read with AI</button></p>`}
  </div><div id="review"></div>`;
}
const saveManual = guard(async () => {
  await api("/records/manual", { json: { patient_id: +$("#rm").value, medicine: $("#mn").value, doctor: $("#md").value, cause: $("#mc").value, next_followup: $("#mf").value || null, lab_test: $("#mlt").value, lab_result: $("#mlr").value || "NA" } });
  toast("Record saved"); S.view = "home"; shell();
});
const setRec = input => { S.recFile = input.files[0] || null; const n = $("#rfn"); if (n) n.textContent = S.recFile ? S.recFile.name : ""; };
const pExtract = guard(async kind => {
  const f = new FormData(); f.append("patient_id", $("#rm").value); f.append("kind", kind);
  if ($("#rt")?.value) f.append("transcript", $("#rt").value); if (S.recFile) f.append("file", S.recFile);
  const r = await api("/records/extract", { form: f }); S.draft = r.draft; S.docId = r.document_id; S.pid = +$("#rm").value;
  renderReview("patient", [], r.needs_input);
});

/* ---------- shared: review & approve draft ---------- */
const FIELDS = [["name", "Medicine"], ["dosage", "Dosage"], ["timing", "Timing"], ["frequency_per_day", "Times/day"], ["duration_days", "Days"], ["cause", "Cause"]];
function renderReview(mode, warnings = [], missing = []) {
  const d = S.draft, meds = d.medicines || [];
  $("#review").innerHTML = `<div class="card"><h2>Check what the AI found</h2>
   ${warnings.length ? `<h3>Safety checks</h3>${warnings.map(w => `<div class="alert ${esc(w.severity)}"><b>${esc(w.severity)}: ${esc(w.type.replace("_", " "))}</b>. ${esc(w.message)}</div>`).join("")}` : mode === "doctor" ? `<div class="alert low">No interactions, allergy clashes or duplicates found.</div>` : ""}
   ${meds.length ? "" : `<p class="muted">No medicines found. Add one below or try a clearer recording or photo.</p>`}
   <div class="tablewrap"><table class="stack"><thead><tr>${FIELDS.map(f => `<th>${f[1]}</th>`).join("")}<th></th></tr></thead><tbody id="rows">${meds.map(rowHtml).join("")}</tbody></table></div>
   <p><button class="ghost sm" onclick="addRow()">+ Add medicine</button></p>
   <label>Next follow-up</label><input id="rfu" type="date" value="${esc(d.next_followup || "")}" style="max-width:220px">
   ${(d.lab_tests || []).length ? `<p class="small muted">Lab tests mentioned: ${d.lab_tests.map(esc).join(", ")}</p>` : ""}
   ${missing.length ? `<p class="small" style="color:var(--pill)">Missing details are highlighted. Fill them in before saving.</p>` : ""}
   <p><button class="ok" onclick="${mode === "doctor" ? "approve()" : "confirmRec()"}">${mode === "doctor" ? "Approve & dispatch" : "Confirm and save"}</button></p></div>`;
  $("#review").scrollIntoView({ behavior: "smooth" });
}
const rowHtml = m => `<tr>${FIELDS.map(([k, label]) => `<td data-label="${label}" class="${m[k] == null || m[k] === "" ? "missing" : ""}"><input data-k="${k}" value="${esc(m[k])}" ${["frequency_per_day", "duration_days"].includes(k) ? 'type="number" min="0" style="width:5rem"' : ""}></td>`).join("")}<td data-label=""><button class="ghost sm" onclick="this.closest('tr').remove()" aria-label="Remove">✕</button></td></tr>`;
const addRow = () => $("#rows").insertAdjacentHTML("beforeend", rowHtml({}));
function collect() {
  return [...document.querySelectorAll("#rows tr")].map(tr => { const o = {}; tr.querySelectorAll("input").forEach(i => { const v = i.value.trim(); o[i.dataset.k] = v === "" ? null : (i.type === "number" ? +v : v); }); return o; }).filter(m => m.name);
}
const approve = guard(async () => {
  const r = await api("/doctor/approve", { json: { patient_id: S.D.patient.id, medicines: collect(), next_followup: $("#rfu").value || null, lab_tests: S.draft.lab_tests || [], document_id: S.docId } });
  toast(`Saved ${r.saved} medicine(s) to the patient's timeline`); $("#review").innerHTML = ""; $("#tx").value = ""; S.D.caseFile = null; await loadPatient(S.D.qr);
});
const confirmRec = guard(async () => {
  const r = await api("/records/confirm", { json: { patient_id: S.pid, medicines: collect(), next_followup: $("#rfu").value || null, document_id: S.docId } });
  toast(`Saved ${r.saved} medicine(s)`); S.view = "home"; shell();
});

/* ---------- patient: QR ---------- */
async function pQr() {
  const id = S.family[0]?.id; const svg = await api(`/patients/${id}/qr.svg`, { text: true });
  $("#main").innerHTML = `<h1>My QR code</h1><p class="muted">Show this at the clinic. The doctor scans it to open your history.</p>
  <div class="row"><div class="qr">${svg}</div><div><label>Show a family member's code</label><select id="qm" onchange="qrFor(this.value)">${S.family.map(f => `<option value="${f.id}">${esc(f.name)}</option>`).join("")}</select></div></div>`;
}
const qrFor = guard(async id => { $(".qr").innerHTML = await api(`/patients/${id}/qr.svg`, { text: true }); });

/* ---------- chat (both roles) ---------- */
const SUGGEST = ["When is the next follow-up for my mom?", "When should I order the next medicines for my mom?", "My mom suddenly has a fever. What can I give as an emergency?", "How much did I spend last month on hospital bills?"];
async function chatView() {
  const hist = await api("/chat/history");
  $("#main").innerHTML = `<h1>${S.role === "doctor" ? "Ask about this patient" : "Ask about your records"}</h1>
  ${S.role === "doctor" && !S.D.patient ? `<p class="muted">Scan or select a patient in Consultation first.</p>` : `
  ${S.role === "patient" ? `<label for="cs" class="small">About</label><select id="cs" style="max-width:260px;margin-bottom:.75rem"><option value="">The whole family</option>${S.family.map(f => `<option value="${f.id}">${esc(f.name)}</option>`).join("")}</select>` : `<p class="muted">Patient: <b>${esc(S.D.patient.name)}</b></p>`}
  <div class="chat"><aside class="card hist" aria-label="Past questions">${hist.map(h => `<button data-q="${esc(h.question)}" data-a="${esc(h.answer)}">${esc(h.question)}</button>`).join("") || `<p class="muted small">Your questions will appear here.</p>`}</aside>
  <section class="card pane"><div class="msgs" id="msgs"><p class="muted">Ask about medicines, follow-ups, refills or spending.</p></div>
  ${S.role === "patient" ? `<div class="suggest">${SUGGEST.map(q => `<button data-s="${esc(q)}">${esc(q)}</button>`).join("")}</div>` : ""}
  <div class="compose"><input id="cq" placeholder="Type your question" aria-label="Question"><button onclick="ask()">Ask</button></div></section></div>`}`;
  document.querySelectorAll(".hist button").forEach(b => b.onclick = () => { $("#msgs").innerHTML = ""; bubble("q", b.dataset.q); bubble("a", b.dataset.a); });
  document.querySelectorAll("[data-s]").forEach(b => b.onclick = () => { $("#cq").value = b.dataset.s; ask(); });
  $("#cq")?.addEventListener("keydown", e => e.key === "Enter" && ask());
}
function bubble(t, x) { const d = document.createElement("div"); d.className = "msg " + t; d.textContent = x; $("#msgs").append(d); $("#msgs").scrollTop = 1e9; return d; }
const ask = guard(async () => {
  const q = $("#cq").value.trim(); if (!q) return; $("#cq").value = ""; bubble("q", q); const w = bubble("a", "Thinking…");
  const pid = S.role === "doctor" ? S.D.patient.id : ($("#cs").value ? +$("#cs").value : null);
  try { w.textContent = (await api("/chat", { json: { question: q, patient_id: pid } })).answer; } catch (e) { w.textContent = e.message; }
});

/* ---------- doctor: consultation ---------- */
async function dConsult() {
  const pts = await api("/doctor/patients");
  $("#main").innerHTML = `<h1>Consultation</h1><div class="grid2" style="grid-template-columns:minmax(260px,1fr) minmax(300px,1.4fr)">
  <div><div class="card"><h3>Check in a patient</h3><video id="cam" hidden playsinline></video>
    <div class="row"><button onclick="scanCam()">Scan with camera</button><label class="fbtn">Take a photo of the QR<input type="file" accept="image/*" capture="environment" class="sr-only" onchange="qrFromFile(this)"></label>
      <label class="fbtn">Choose QR image<input type="file" accept="image/*" class="sr-only" onchange="qrFromFile(this)"></label><button id="cam-stop" class="ghost sm" onclick="stopCam()" hidden>Stop camera</button></div>
    <p class="small muted">"Take a photo" and "Choose image" work on any link. Live camera needs https.</p>
    <label for="qp">Or paste the QR code text</label><div class="row"><input id="qp" class="grow" placeholder="mediprxn:…"><button class="ghost" onclick="loadPatient($('#qp').value)">Open</button></div>
    <details style="margin-top:.75rem"><summary class="small muted">Demo: pick a registered patient</summary>${pts.map(p => `<p><button class="ghost sm" onclick="loadPatient('mediprxn:${esc(p.qr_token)}')">${esc(p.name)} · ${p.age ?? "?"}y · ${esc(p.relation)}</button></p>`).join("")}</details></div>
   <div id="pinfo"></div></div>
  <div id="capture"></div></div><div id="review" style="margin-top:1rem"></div>`;
  if (S.D.qr) loadPatient(S.D.qr);
}
const loadPatient = guard(async qr => {
  const r = await api("/doctor/scan?qr=" + encodeURIComponent(qr), { method: "POST" }); S.D = { patient: r.patient, qr, scan: r };
  const p = r.patient;
  $("#pinfo").innerHTML = `<div class="card"><div class="row"><h2 class="grow">${esc(p.name)}</h2><span class="tag">${p.age ?? "?"} yrs ${esc(p.gender || "")}</span></div>
   ${p.allergies ? `<p><span class="tag bad">Allergic to ${esc(p.allergies)}</span></p>` : ""}
   <p class="small muted">Self-reported history (not a source of truth): ${esc(p.self_reported_history || "none given")}</p>
   <h3 style="margin-top:.75rem">Taking now</h3><div class="caps">${r.active_medicines.map(m => `<div class="cap"><div class="body"><div><span class="name">${esc(m.medicine)} ${esc(m.dosage || "")}</span><div class="meta">since ${esc(m.start_date)} · ${m.duration_days ?? "?"} days · ${esc(m.cause || "")}</div></div></div></div>`).join("") || `<p class="muted">Nothing active.</p>`}</div>
   <details style="margin-top:.75rem"><summary>Full treatment history (${r.history.length})</summary>${r.history.map(m => `<p class="small">${esc(m.start_date)}: ${esc(m.medicine)} ${esc(m.dosage || "")}, ${esc(m.cause || "")}</p>`).join("")}</details>
   <details><summary>Family history (${r.family_history.length})</summary>${r.family_history.map(f => `<p class="small"><b>${esc(f.name)}</b> (${esc(f.relation)}): ${esc(f.self_reported_history || "none given")}</p>`).join("") || "<p class='small muted'>None on file.</p>"}</details>
   <label style="display:flex;gap:.5rem;align-items:center;margin-top:.75rem"><input type="checkbox" style="width:auto" ${p.private_from_family ? "checked" : ""} onchange="setPrivate(this.checked)"> Keep these records private from family members</label></div>`;
  $("#capture").innerHTML = `<div class="card"><h3>Record this visit</h3>
   <div class="row"><button id="rb" class="ghost" onclick="toggleRec()">Start transcript</button><span class="small muted" id="rs"></span></div>
   <label for="tx">Transcript or dictation (you can edit it)</label><textarea id="tx" rows="6" placeholder="e.g. Prescribe Paracetamol 650mg twice a day after food for 3 days"></textarea>
   <label for="cf">Or add the handwritten case paper</label><div class="row"><label class="fbtn">Take a photo<input type="file" accept="image/*" capture="environment" class="sr-only" onchange="setCase(this)"></label>
     <label class="fbtn">Choose file<input id="cf" type="file" accept="image/*,application/pdf" class="sr-only" onchange="setCase(this)"></label><span id="cfn" class="small muted"></span></div>
   <p><button class="pill" onclick="dExtract()">Extract prescription</button></p></div>`;
});
const setPrivate = guard(async v => { await api(`/patients/${S.D.patient.id}/privacy?private=${v}`, { method: "POST" }); toast(v ? "Records hidden from family" : "Records visible to family"); });
const dExtract = guard(async () => {
  const f = new FormData(); f.append("patient_id", S.D.patient.id); const file = S.D.caseFile, tx = $("#tx").value.trim();
  if (!file && !tx) throw new Error("Record, type or upload something first");
  f.append("kind", file ? "case_paper" : "transcript"); if (tx) f.append("transcript", tx); if (file) f.append("file", file);
  toast("Reading the consultation…"); const r = await api("/doctor/extract", { form: f });
  S.draft = r.draft; S.docId = r.document_id; renderReview("doctor", r.safety_warnings, r.draft.missing_fields || []);
});
function toggleRec() {
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!window.isSecureContext) return toast("Voice needs a secure (https) link. Type the dictation instead.", true);
  if (!SR) return toast("Live transcript isn't supported in this browser. Type or paste it instead.", true);
  if (S.rec) { S.rec.stop(); return; }
  const r = S.rec = new SR(); r.continuous = true; r.interimResults = false; r.lang = "en-IN";
  r.onresult = e => { for (let i = e.resultIndex; i < e.results.length; i++) if (e.results[i].isFinal) $("#tx").value += (($("#tx").value ? " " : "") + e.results[i][0].transcript.trim()); };
  r.onend = () => { S.rec = null; $("#rb").textContent = "Start transcript"; $("#rb").classList.remove("rec", "live"); $("#rs").textContent = ""; };
  r.start(); $("#rb").textContent = "Stop recording"; $("#rb").className = "rec live"; $("#rs").textContent = "Listening…";
}
function decodeQr(canvas) {
  const img = canvas.getContext("2d", { willReadFrequently: true }).getImageData(0, 0, canvas.width, canvas.height);
  const r = jsQR(img.data, img.width, img.height, { inversionAttempts: "attemptBoth" }); return r ? r.data : null;
}
async function qrFromImageFile(file) {
  const url = URL.createObjectURL(file), img = new Image();
  try {
    await new Promise((ok, bad) => { img.onload = ok; img.onerror = () => bad(new Error("Could not open that image")); img.src = url; });
    for (const max of [1000, 1600, 640]) {                       // try several sizes: phone photos are huge and the code may be small
      const k = Math.min(1, max / Math.max(img.naturalWidth, img.naturalHeight)), c = document.createElement("canvas");
      c.width = Math.round(img.naturalWidth * k); c.height = Math.round(img.naturalHeight * k);
      c.getContext("2d").drawImage(img, 0, 0, c.width, c.height); const d = decodeQr(c); if (d) return d;
    }
    return null;
  } finally { URL.revokeObjectURL(url); }
}
const qrFromFile = guard(async input => {
  const f = input.files[0]; input.value = ""; if (!f) return;
  toast("Reading the QR code…"); const data = await qrFromImageFile(f);
  if (!data) throw new Error("No QR code found in that picture. Fill the frame with the code, keep it flat and well lit, then try again.");
  if (!/^(mediprxn|smartprxn):/.test(data.trim())) throw new Error("That QR code is not a Medi-Prxn Care patient code.");
  stopCam(); await loadPatient(data);
});
function stopCam() { const v = $("#cam"); if (v && v.srcObject) { v.srcObject.getTracks().forEach(t => t.stop()); v.srcObject = null; } if (v) v.hidden = true; const s = $("#cam-stop"); if (s) s.hidden = true; }
const scanCam = guard(async () => {
  if (!window.isSecureContext) throw new Error("Live camera needs a secure (https) link. Use \"Take a photo of the QR\" instead, it works on any link.");
  if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) throw new Error("Live camera is not available in this browser. Use \"Take a photo of the QR\" instead.");
  const v = $("#cam"); let stream;
  try { stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: { ideal: "environment" } }, audio: false }); }
  catch (e) { throw new Error(e.name === "NotAllowedError" ? "Camera permission was denied. Allow the camera for this site in your browser settings, or use \"Take a photo of the QR\"." : "Could not start the camera. Use \"Take a photo of the QR\" instead."); }
  v.setAttribute("playsinline", ""); v.muted = true; v.srcObject = stream; v.hidden = false; $("#cam-stop").hidden = false; await v.play();
  const c = document.createElement("canvas");
  const tick = () => {
    if (!v.srcObject) return;
    if (v.videoWidth) { c.width = v.videoWidth; c.height = v.videoHeight; c.getContext("2d", { willReadFrequently: true }).drawImage(v, 0, 0); const d = decodeQr(c); if (d) { stopCam(); loadPatient(d); return; } }
    setTimeout(tick, 200);
  };
  tick();
});
const setCase = input => { S.D.caseFile = input.files[0] || null; const n = $("#cfn"); if (n) n.textContent = S.D.caseFile ? S.D.caseFile.name : ""; };

/* ---------- admin: reception ---------- */
async function aReg() {
  const pts = await api("/doctor/patients");
  $("#main").innerHTML = `<h1>Reception</h1><div class="grid2"><div class="card"><h3>Register a first-time patient</h3>
  <label>Name</label><input id="an"><label>Age</label><input id="aa" type="number"><label>Gender</label><select id="ag"><option>Female</option><option>Male</option><option>Other</option></select>
  <label>Family number</label><input id="af"><label>History (for the doctor's information only)</label><textarea id="ah" rows="3" placeholder="Leave blank if this is their first visit"></textarea>
  <p><button class="pill" onclick="regPatient()">Register patient</button></p></div>
  <div class="card"><h3>Recently registered</h3>${pts.map(p => `<p>${esc(p.name)} <span class="muted small">${p.age ?? "?"}y · family ${esc(p.family_number || "-")}</span></p>`).join("")}</div></div>`;
}
const regPatient = guard(async () => {
  await api("/reception/register", { json: { name: $("#an").value, age: +$("#aa").value, gender: $("#ag").value, family_number: $("#af").value, history: $("#ah").value } });
  toast("Patient registered"); aReg();
});

/* ---------- dose alarms ---------- */
const LS = { get(k) { try { return localStorage.getItem(k); } catch { return null; } }, set(k, v) { try { localStorage.setItem(k, v); } catch {} } };
const localDate = () => { const d = new Date(); return d.getFullYear() + "-" + String(d.getMonth() + 1).padStart(2, "0") + "-" + String(d.getDate()).padStart(2, "0"); };
const nowHM = () => { const d = new Date(); return String(d.getHours()).padStart(2, "0") + ":" + String(d.getMinutes()).padStart(2, "0"); };
const toMin = t => parseInt(t.slice(0, 2)) * 60 + parseInt(t.slice(3, 5));
const remKey = r => `${localDate()}|${r.patient_id}|${r.medicine}|${r.time}`;
let REM = [], alarmTimer = null, remTimer = null;
async function loadReminders() { REM = await api("/reminders"); }
async function startAlarms() {
  if (S.role !== "patient") return;
  if ("serviceWorker" in navigator) S.swReg = await navigator.serviceWorker.register("/sw.js").catch(() => null);
  await loadReminders().catch(() => {});
  clearInterval(alarmTimer); clearInterval(remTimer);
  alarmTimer = setInterval(checkAlarms, 20000); remTimer = setInterval(() => loadReminders().catch(() => {}), 300000); checkAlarms();
}
function checkAlarms() {
  const now = nowHM();
  REM.forEach(r => {
    const late = toMin(now) - toMin(r.time);
    if (late < 0 || late > 15) return;            // only ring inside a 15-minute window
    const k = "fired|" + remKey(r); if (LS.get(k)) return; LS.set(k, "1"); fireAlarm(r);
  });
}
async function fireAlarm(r) {
  const title = `Time for ${r.medicine} ${r.dosage || ""}`.trim(), body = `${r.patient}${r.timing ? " · " + r.timing : ""}`;
  toast(title + " · " + body);
  if ("Notification" in window && Notification.permission === "granted") {
    try { if (S.swReg) await S.swReg.showNotification(title, { body, tag: remKey(r), icon: "/icon-192.png", requireInteraction: true }); else new Notification(title, { body }); } catch {}
  }
}
async function pRemind() {
  await loadReminders(); const perm = "Notification" in window ? Notification.permission : "unsupported", now = nowHM();
  const msg = { granted: "Alarms are on. Keep Medi-Prxn Care open, or install it to your home screen.", denied: "Notifications are blocked in your browser settings. In-app alerts still work.",
    unsupported: "This browser can't show notifications. In-app alerts still work.", default: "Turn on notifications to get an alarm at every dose time." }[perm];
  $("#main").innerHTML = `<h1>Reminders</h1><div class="card"><div class="row"><div class="grow"><h3>Dose alarms</h3><p class="muted small">${msg}</p></div>
    ${perm === "default" ? `<button class="pill" onclick="enableAlarms()">Turn on alarms</button>` : ""}<button class="ghost" onclick="testAlarm()">Send test alarm</button></div></div>
  <div class="card"><h3>Today's doses</h3>${REM.length ? REM.map((r, i) => { const taken = LS.get("taken|" + remKey(r)), over = !taken && toMin(now) - toMin(r.time) > 15;
    return `<div class="row" style="padding:.5rem 0;border-bottom:1px solid var(--line)"><b style="width:3.5rem">${esc(r.time)}</b><div class="grow">${esc(r.medicine)} ${esc(r.dosage || "")}<div class="small muted">${esc(r.patient)}${r.timing ? " · " + esc(r.timing) : ""}</div></div>
      ${taken ? `<span class="tag ok">Taken</span>` : over ? `<span class="tag bad">Missed?</span>` : ""}<button class="ghost sm" onclick="takeDose(${i})">${taken ? "Undo" : "Mark taken"}</button></div>`; }).join("") : `<p class="muted">No active medicines, so nothing to remind you about today.</p>`}</div>`;
}
const takeDose = i => { const k = "taken|" + remKey(REM[i]); LS.set(k, LS.get(k) ? "" : "1"); pRemind(); };
const enableAlarms = async () => { await Notification.requestPermission(); pRemind(); };
const testAlarm = () => fireAlarm({ medicine: "Test dose", dosage: "", patient: "Medi-Prxn Care", timing: "", patient_id: 0, time: "00:00" });

/* ---------- preventive check-ups ---------- */
const every = m => m === 12 ? "every year" : m % 12 === 0 ? `every ${m / 12} years` : `every ${m} months`;
const TAG = { overdue: ["Overdue", "bad"], no_record: ["No record", "warn"], due_soon: ["Due soon", "warn"], ok: ["Up to date", "ok"] };
async function pCheckups() {
  const data = await api("/checkups");
  $("#main").innerHTML = `<h1>Preventive check-ups</h1><p class="muted small" style="max-width:62ch">General screening intervals based on age, sex and current medicines. Your doctor decides the right schedule for each person.</p>` +
    data.map(d => `<section class="card"><h2>${esc(d.patient.name)} <span class="muted small">${d.patient.age ?? ""} yrs</span></h2>${d.items.map(i => `<div class="row" style="padding:.5rem 0;border-bottom:1px solid var(--line)"><div class="grow"><b>${esc(i.name)}</b><div class="small muted">${esc(i.why)} · ${every(i.interval_months)}${i.last_done ? " · last done " + esc(i.last_done) : ""}${i.next_due ? " · next due " + esc(i.next_due) : ""}</div></div><span class="tag ${TAG[i.status][1]}">${TAG[i.status][0]}</span><button class="ghost sm" onclick="markDone(${d.patient.id},'${esc(i.key)}')">Mark done today</button></div>`).join("")}</section>`).join("");
}
const markDone = guard(async (pid, key) => { await api("/checkups/done", { json: { patient_id: pid, key } }); toast("Saved"); pCheckups(); });

/* ---------- helpers ---------- */
const inr = n => "₹" + Number(n || 0).toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const CAT = { consultation: "Consultation", lab_test: "Lab test", pharmacy: "Pharmacy", procedure: "Procedure", other: "Other" };
const monthNow = () => localDate().slice(0, 7);
async function downloadCsv(path, name) {
  const r = await fetch(path, { headers: { Authorization: "Bearer " + S.token } });
  if (!r.ok) throw new Error("Could not export the bills");
  const a = document.createElement("a"); a.href = URL.createObjectURL(await r.blob()); a.download = name; a.click(); URL.revokeObjectURL(a.href);
}

/* ---------- patient: bills ---------- */
async function pBills() {
  S.bm = S.bm || monthNow(); S.bpid = S.bpid || "";
  const q = `month=${S.bm}${S.bpid ? "&patient_id=" + S.bpid : ""}`;
  const [sum, rows] = await Promise.all([api(`/bills/summary?${q}`), api(`/bills?${q}`)]);
  const max = Math.max(1, ...Object.values(sum.by_category)), tmax = Math.max(1, ...sum.trend.map(t => t.spent));
  const change = sum.change_percent === null ? "no spend last month" : (sum.change_percent > 0 ? "up " : "down ") + Math.abs(sum.change_percent) + "% on " + sum.previous_month;
  $("#main").innerHTML = `<h1>Bills</h1>
  <div class="row" style="margin-bottom:1rem"><div><label for="bm" style="margin:0">Month</label><input id="bm" type="month" value="${esc(S.bm)}" max="${monthNow()}" style="width:11rem"></div>
    <div><label for="bp" style="margin:0">Member</label><select id="bp" style="width:12rem"><option value="">Everyone</option>${S.family.map(f => `<option value="${f.id}" ${S.bpid == f.id ? "selected" : ""}>${esc(f.name)}</option>`).join("")}</select></div>
    <span class="grow"></span><button class="ghost" onclick="exportBills()">Export CSV</button><button class="pill" onclick="billForm()">+ Add a bill</button></div>
  <div class="grid2" style="grid-template-columns:repeat(auto-fit,minmax(200px,1fr))">
    <div class="card"><p class="muted small">Spent in ${esc(sum.month)}</p><h2 style="font-size:1.7rem">${inr(sum.spent)}</h2><p class="small muted">${esc(change)}</p></div>
    <div class="card"><p class="muted small">Waiting to be paid</p><h2 style="font-size:1.7rem;color:${sum.pending_total ? "var(--warn)" : "var(--ink)"}">${inr(sum.pending_total)}</h2><p class="small muted">all months</p></div></div>
  <div class="grid2"><div class="card"><h3>By category</h3>${Object.entries(sum.by_category).map(([k, v]) => `<div style="margin:.5rem 0"><div class="row small"><span class="grow">${esc(CAT[k] || k)}</span><b>${inr(v)}</b></div><div class="bar"><span style="width:${v / max * 100}%"></span></div></div>`).join("") || `<p class="muted">No paid bills this month.</p>`}</div>
    <div class="card"><h3>Last 6 months</h3><div class="trend">${sum.trend.map(t => `<div title="${esc(t.month)}: ${inr(t.spent)}"><span style="height:${Math.max(2, t.spent / tmax * 100)}%"></span><small>${esc(t.month.slice(5))}</small></div>`).join("")}</div>
    ${Object.keys(sum.by_member).length > 1 ? `<h3 style="margin-top:1rem">By member</h3>${Object.entries(sum.by_member).map(([k, v]) => `<p class="small row"><span class="grow">${esc(k)}</span><b>${inr(v)}</b></p>`).join("")}` : ""}</div></div>
  <div class="card"><h3>Bills in ${esc(S.bm)}</h3><div class="tablewrap">${rows.length ? `<table class="stack"><thead><tr><th>Date</th><th>Member</th><th>Details</th><th>Amount</th><th>Status</th><th></th></tr></thead><tbody>${rows.map(r => `<tr>
    <td data-label="Date">${esc(r.date)}</td><td data-label="Member">${esc(r.member)}</td><td data-label="Details"><span><b>${esc(CAT[r.category] || r.category)}</b>${r.provider_name ? " · " + esc(r.provider_name) : ""}<div class="small muted">${esc(r.description)}${r.invoice_no ? " · " + esc(r.invoice_no) : ""}</div></span></td>
    <td data-label="Amount">${inr(r.amount)}</td><td data-label="Status"><span class="tag ${r.status === "paid" ? "ok" : "warn"}">${r.status === "paid" ? "Paid" : "Pending"}</span></td>
    <td data-label="" class="acts">${r.status === "pending" ? `<button class="ghost sm" onclick="payBill(${r.id})">Mark paid</button> ` : ""}${r.invoice_no ? `<button class="ghost sm" onclick="printBill(${r.id})">Print</button>` : `<button class="ghost sm" onclick="billForm(${r.id})">Edit</button> <button class="ghost sm" onclick="delBill(${r.id})">Delete</button>`}</td></tr>`).join("")}</tbody></table>` : `<p class="muted">No bills for this month.</p>`}</div></div>`;
  S.billRows = rows;
  $("#bm").onchange = e => { S.bm = e.target.value || monthNow(); pBills(); }; $("#bp").onchange = e => { S.bpid = e.target.value; pBills(); };
}
const exportBills = guard(() => downloadCsv(`/bills/export.csv?month=${S.bm}`, `bills-${S.bm}.csv`));
const payBill = guard(async id => { await api(`/bills/${id}/paid`, { method: "POST" }); toast("Marked as paid"); pBills(); });
const delBill = guard(async id => { if (!confirm("Delete this bill?")) return; await api(`/bills/${id}`, { method: "DELETE" }); toast("Bill deleted"); pBills(); });
function billForm(id) {
  const b = id ? S.billRows.find(x => x.id === id) : {};
  $("#main").innerHTML = `<h1>${id ? "Edit bill" : "Add a bill"}</h1><div class="card" style="max-width:560px">
  <label for="fb_p">For</label><select id="fb_p" ${id ? "disabled" : ""}>${S.family.map(f => `<option value="${f.id}" ${(b.patient_id || S.bpid) == f.id ? "selected" : ""}>${esc(f.name)}</option>`).join("")}</select>
  <label for="fb_d">Date</label><input id="fb_d" type="date" max="${localDate()}" value="${esc(b.date || localDate())}">
  <label for="fb_c">Category</label><select id="fb_c">${Object.entries(CAT).map(([k, v]) => `<option value="${k}" ${b.category === k ? "selected" : ""}>${v}</option>`).join("")}</select>
  <label for="fb_pr">Doctor, lab or pharmacy</label><input id="fb_pr" value="${esc(b.provider_name || "")}">
  <label for="fb_a">Amount (₹)</label><input id="fb_a" type="number" min="0.01" step="0.01" value="${b.amount ?? ""}">
  <label for="fb_ds">Note</label><input id="fb_ds" value="${esc(b.description || "")}">
  <label for="fb_s">Status</label><select id="fb_s"><option value="paid" ${b.status !== "pending" ? "selected" : ""}>Paid</option><option value="pending" ${b.status === "pending" ? "selected" : ""}>Pending</option></select>
  <p><button class="ok" onclick="saveBill(${id || 0})">Save bill</button> <button class="ghost" onclick="pBills()">Cancel</button></p></div>`;
}
const saveBill = guard(async id => {
  const body = { patient_id: +$("#fb_p").value, date: $("#fb_d").value, category: $("#fb_c").value, provider_name: $("#fb_pr").value, amount: $("#fb_a").value === "" ? null : +$("#fb_a").value, description: $("#fb_ds").value, status: $("#fb_s").value };
  await api(id ? `/bills/${id}` : "/bills", { json: body, method: id ? "PUT" : "POST" }); toast("Bill saved"); S.bm = body.date.slice(0, 7); pBills();
});
function printBill(id) {
  const r = S.billRows.find(x => x.id === id), w = window.open("", "_blank"); if (!w) return toast("Allow pop-ups to print", true);
  const items = (r.items || [{ description: r.description || r.category, quantity: 1, unit_price: r.amount }]);
  w.document.write(`<title>${esc(r.invoice_no)}</title><body style="font-family:sans-serif;max-width:560px;margin:2rem auto"><h2>Medi-Prxn Care invoice</h2><p>${esc(r.invoice_no)} · ${esc(r.date)}<br>${esc(r.member)}${r.provider_name ? " · " + esc(r.provider_name) : ""}</p>
    <table width="100%" style="border-collapse:collapse">${items.map(i => `<tr><td style="border-bottom:1px solid #ccc;padding:.3rem">${esc(i.description)} × ${i.quantity}</td><td style="border-bottom:1px solid #ccc;text-align:right">${inr(i.quantity * i.unit_price)}</td></tr>`).join("")}
    <tr><td><b>Total</b></td><td style="text-align:right"><b>${inr(r.amount)}</b></td></tr></table><p>Status: ${r.status}</p><script>window.print()<\/script></body>`); w.document.close();
}

/* ---------- patient: find a doctor or lab ---------- */
const DEMO_LOC = { lat: 28.738, lon: 77.08, accuracy: 0, label: "Demo location (Rohini, Delhi)" };
S.care = { kind: "doctor", loc: null, radius: 10, mode: "value", minRating: 3.5, maxPrice: "", specialty: "", test: "", results: null };
async function pCare() {
  const C = S.care, [specs, tests] = await Promise.all([api("/care/specialties"), api("/care/tests")]);
  const L = C.loc;
  if (!specs.length && !tests.length) return $("#main").innerHTML = `<h1>Find care nearby</h1><div class="card" style="max-width:560px"><h3>No doctors or labs in the directory yet</h3>
    <p>${S.role === "admin" ? "" : "Ask the clinic admin to add them on the Providers page. "}For testing, the admin can load fictional sample providers around Rohini, Delhi from the Providers page, or you can start the app with <code>DEMO_SEED=1</code> and restart.</p></div>`;
  $("#main").innerHTML = `<h1>Find care nearby</h1><p class="muted small" style="max-width:64ch">Doctors and labs within ${C.radius} km, ranked on price and rating together. Cheap options with poor ratings are filtered out.</p>
  <div class="tabs" role="tablist"><button role="tab" aria-selected="${C.kind === "doctor"}" onclick="S.care.kind='doctor';S.care.results=null;pCare()">Doctors</button><button role="tab" aria-selected="${C.kind === "lab"}" onclick="S.care.kind='lab';S.care.results=null;pCare()">Lab tests</button></div>
  <div class="grid2"><div class="card">
    ${C.kind === "doctor" ? `<label for="cs">Specialty</label><select id="cs"><option value="">Choose…</option>${specs.map(s => `<option ${C.specialty === s ? "selected" : ""}>${esc(s)}</option>`).join("")}</select>`
      : `<label for="ct">Lab test</label><select id="ct"><option value="">Choose…</option>${tests.map(t => `<option value="${esc(t.name)}" ${C.test === t.name ? "selected" : ""}>${esc(t.name)}</option>`).join("")}</select>`}
    <label for="cr">Distance: up to <b id="crv">${C.radius}</b> km (maximum 10)</label><input id="cr" type="range" min="1" max="10" step="1" value="${C.radius}">
    <label>What matters most</label><div class="chips" role="group">${[["value", "Best value"], ["cheapest", "Cheapest"], ["best", "Best rated"]].map(([k, v]) => `<button class="chip" aria-pressed="${C.mode === k}" onclick="S.care.mode='${k}';pCare()">${v}</button>`).join("")}</div>
    <div class="row"><div class="grow"><label for="cmr">Minimum rating</label><select id="cmr">${[3, 3.5, 4, 4.5].map(v => `<option ${C.minRating === v ? "selected" : ""}>${v}</option>`).join("")}</select></div>
      <div class="grow"><label for="cmp">Maximum price (₹, optional)</label><input id="cmp" type="number" min="1" value="${esc(C.maxPrice)}"></div></div></div>
  <div class="card"><h3>Your location</h3><p class="small">${L ? `<b>${esc(L.label || L.lat.toFixed(4) + ", " + L.lon.toFixed(4))}</b>${L.accuracy ? " · accurate to about " + Math.round(L.accuracy) + " m" : ""}` : `<span class="muted">Not set yet</span>`}</p>
    <p id="loc-msg" class="small" role="status"></p><div class="row"><button onclick="useMyLocation()">Use my location</button><button class="ghost" onclick="S.care.loc={...DEMO_LOC};pCare()">Use demo location</button></div>
    <div class="row"><div class="grow"><label for="cla">Latitude</label><input id="cla" type="number" step="any" value="${L ? L.lat : ""}"></div><div class="grow"><label for="clo">Longitude</label><input id="clo" type="number" step="any" value="${L ? L.lon : ""}"></div></div>
    <p class="small muted">Your location is sent only to run this search and is not stored.</p></div></div>
  <p><button class="pill" onclick="runCare()">Search</button></p><div id="care-out">${C.results ? careResults(C.results) : ""}</div>`;
  $("#cr").oninput = e => { C.radius = +e.target.value; $("#crv").textContent = C.radius; };
}
const useMyLocation = () => {
  const say = (m, bad) => { const o = $("#loc-msg"); o.textContent = m; o.style.color = bad ? "var(--bad)" : "var(--muted)"; };
  if (!window.isSecureContext) return say("Your browser blocks location on this link because it is not secure (http). Open the https link, or tap \"Use demo location\", or type the coordinates below.", true);
  if (!navigator.geolocation) return say("This browser can't share its location. Type the coordinates below instead.", true);
  say("Waiting for your phone... if a permission pop-up appears, tap Allow.");
  navigator.geolocation.getCurrentPosition(p => { S.care.loc = { lat: p.coords.latitude, lon: p.coords.longitude, accuracy: p.coords.accuracy || 0 }; pCare(); },
    e => say(e.code === 1 ? "Location is blocked for this site. In Chrome tap the lock icon next to the address, choose Permissions, set Location to Allow, then try again. Or use the demo location."
      : e.code === 3 ? "Finding your location took too long. Check that Location (GPS) is on in your phone settings and try again."
      : "Your phone could not work out its location. Turn on Location (GPS) in your phone settings and try again.", true),
    { enableHighAccuracy: true, timeout: 20000, maximumAge: 0 });
};
const runCare = guard(async () => {
  const C = S.care;
  const la = $("#cla").value, lo = $("#clo").value;
  if (la === "" || lo === "") throw new Error("Set your location first");
  if (!C.loc || +la !== C.loc.lat || +lo !== C.loc.lon) C.loc = { lat: +la, lon: +lo, accuracy: 0 };       // typed coordinates have no GPS error
  C.minRating = +$("#cmr").value; C.maxPrice = $("#cmp").value;
  if (C.kind === "doctor") { C.specialty = $("#cs").value; if (!C.specialty) throw new Error("Choose a specialty"); }
  else { C.test = $("#ct").value; if (!C.test) throw new Error("Choose a lab test"); }
  const body = { kind: C.kind, specialty: C.specialty || null, test: C.test || null, lat: C.loc.lat, lon: C.loc.lon, radius_km: C.radius, accuracy_m: C.loc.accuracy || 0, mode: C.mode, min_rating: C.minRating, max_price: C.maxPrice ? +C.maxPrice : null };
  C.results = await api("/care/search", { json: body }); $("#care-out").innerHTML = careResults(C.results); $("#care-out").scrollIntoView({ behavior: "smooth" });
});
function careResults(R) {
  const m = R.meta, notes = m.notes.map(n => `<p class="small muted">${esc(n)}</p>`).join("");
  if (!R.results.length) return `<div class="card"><h3>No matches</h3><p>Nothing within ${m.effective_radius_km} km meets your filters (${m.in_range} provider${m.in_range === 1 ? "" : "s"} in range).</p>${notes}</div>`;
  return `<div class="card flat"><p><b>${R.results.length}</b> result${R.results.length === 1 ? "" : "s"} within ${m.effective_radius_km} km · typical price here ${inr(m.median_price)}</p>${notes}</div>` + R.results.map(r => `
  <div class="card"><div class="row"><b style="font-size:1.4rem;color:var(--muted)">#${r.rank}</b><div class="grow"><h2 style="margin:0">${esc(r.name)}</h2><p class="small muted">${esc([r.specialty, r.clinic_name, r.address].filter(Boolean).join(" · "))}</p></div>
    <div style="text-align:right"><div style="font-size:1.5rem;font-weight:700;color:var(--ink)">${inr(r.price)}</div><div class="small muted">${r.test_name ? esc(r.test_name) : "consultation"}</div></div></div>
    <div class="row small" style="margin:.4rem 0"><span>★ <b>${r.rating.toFixed(1)}</b> (${r.review_count} review${r.review_count === 1 ? "" : "s"})</span><span><b>${r.distance_km.toFixed(1)} km</b> straight-line</span>${r.price_vs_median ? `<span>${r.price_vs_median <= 1 ? Math.round((1 - r.price_vs_median) * 100) + "% below" : Math.round((r.price_vs_median - 1) * 100) + "% above"} typical price</span>` : ""}
      ${r.badges.map(b => `<span class="tag ${b === "Few reviews" ? "warn" : "ok"}">${esc(b)}</span>`).join("")}</div>
    <div class="row"><a href="https://www.google.com/maps/dir/?api=1&destination=${r.lat},${r.lon}" target="_blank" rel="noopener"><button class="ghost sm">Directions</button></a>${r.phone ? `<a href="tel:${esc(r.phone)}"><button class="ghost sm">Call</button></a>` : ""}
      <span class="grow"></span><select id="rv${r.id}" style="width:5.5rem" aria-label="Your rating">${[5, 4, 3, 2, 1].map(n => `<option>${n}</option>`).join("")}</select><button class="ghost sm" onclick="rateProvider(${r.id})">Rate</button></div></div>`).join("") + `
  <details class="card"><summary><b>How results are ranked</b></summary><p class="small">Only providers inside your distance limit are considered, measured exactly on the globe and reduced by your GPS error. Ratings use a Bayesian average, so one perfect review cannot beat hundreds of good ones. Price is compared with the median price in range. Best value weighs both equally, Cheapest sorts by price, Best rated sorts by rating. The minimum rating applies to every mode. Distance only breaks ties. Distances are straight-line, so the road trip can be longer.</p></details>`;
}
const rateProvider = guard(async id => { await api(`/care/providers/${id}/review`, { json: { stars: +$("#rv" + id).value } }); toast("Thanks for rating"); });

/* ---------- admin: clinic billing ---------- */
async function aBilling() {
  const [pts, bills] = await Promise.all([api("/doctor/patients"), api("/bills")]);
  S.billRows = bills; S.items = S.items || [{ description: "Consultation", quantity: 1, unit_price: "" }];
  $("#main").innerHTML = `<h1>Billing</h1><div class="grid2"><div class="card"><h3>Create an invoice</h3>
  <label for="ab_p">Patient</label><select id="ab_p">${pts.map(p => `<option value="${p.id}">${esc(p.name)} · ${p.age ?? "?"}y</option>`).join("")}</select>
  <div class="row"><div class="grow"><label for="ab_d">Date</label><input id="ab_d" type="date" max="${localDate()}" value="${localDate()}"></div><div class="grow"><label for="ab_c">Category</label><select id="ab_c">${Object.entries(CAT).map(([k, v]) => `<option value="${k}">${v}</option>`).join("")}</select></div></div>
  <label for="ab_pr">Doctor or department</label><input id="ab_pr"><label>Line items</label><div id="ab_items"></div>
  <p><button class="ghost sm" onclick="S.items.push({description:'',quantity:1,unit_price:''});drawItems()">+ Add item</button></p>
  <p><b>Total: <span id="ab_t">₹0.00</span></b></p>
  <label for="ab_s">Payment</label><select id="ab_s"><option value="paid">Paid</option><option value="pending">Pending</option></select>
  <p><button class="pill" onclick="saveInvoice()">Create invoice</button></p></div>
  <div class="card"><h3>Recent invoices</h3>${bills.filter(b => b.invoice_no).slice(0, 12).map(b => `<p class="small row"><span class="grow"><b>${esc(b.invoice_no)}</b> · ${esc(b.member)}<br><span class="muted">${esc(b.date)} · ${esc(CAT[b.category] || b.category)}</span></span><span>${inr(b.amount)}</span><span class="tag ${b.status === "paid" ? "ok" : "warn"}">${b.status}</span><button class="ghost sm" onclick="printBill(${b.id})">Print</button></p>`).join("") || `<p class="muted">No invoices yet.</p>`}</div></div>`;
  drawItems();
}
function drawItems() {
  $("#ab_items").innerHTML = S.items.map((it, i) => `<div class="row" style="margin-bottom:.4rem"><input class="grow" placeholder="Description" aria-label="Description" value="${esc(it.description)}" oninput="S.items[${i}].description=this.value">
    <input type="number" min="1" style="width:4.5rem" aria-label="Quantity" value="${it.quantity}" oninput="S.items[${i}].quantity=+this.value;sumItems()"><input type="number" min="0" step="0.01" placeholder="Price" style="width:7rem" aria-label="Unit price" value="${esc(it.unit_price)}" oninput="S.items[${i}].unit_price=this.value;sumItems()">
    <button class="ghost sm" aria-label="Remove item" onclick="S.items.splice(${i},1);drawItems()">✕</button></div>`).join(""); sumItems();
}
const sumItems = () => { const paise = S.items.reduce((s, it) => s + Math.round((+it.unit_price || 0) * 100) * (+it.quantity || 0), 0); $("#ab_t").textContent = inr(paise / 100); };
const saveInvoice = guard(async () => {
  const items = S.items.filter(i => i.description.trim()).map(i => ({ description: i.description.trim(), quantity: +i.quantity, unit_price: +i.unit_price }));
  if (!items.length) throw new Error("Add at least one line item");
  const r = await api("/bills", { json: { patient_id: +$("#ab_p").value, date: $("#ab_d").value, category: $("#ab_c").value, provider_name: $("#ab_pr").value, items, status: $("#ab_s").value } });
  toast(`Invoice ${r.invoice_no} created`); S.items = null; aBilling();
});

/* ---------- admin: provider directory ---------- */
async function aProviders() {
  const list = await api("/care/providers"), labs = list.filter(p => p.kind === "lab");
  $("#main").innerHTML = `<h1>Provider directory</h1>${list.length ? "" : `<div class="card" style="border-color:var(--ink)"><h3>The directory is empty</h3><p class="small">Patients cannot search until it has doctors or labs. Add your own below, or load fictional sample providers around Rohini, Delhi for testing.</p><button onclick="loadSample()">Load sample providers</button></div>`}<p class="muted small" style="max-width:64ch">Doctors and labs that patients can find. Coordinates must be real (0, 0 is rejected); providers without valid coordinates are never shown in search.</p>
  <div class="grid2"><div class="card"><h3>Add a doctor or lab</h3>
  <label for="ap_k">Type</label><select id="ap_k" onchange="$('#ap_doc').hidden=this.value!=='doctor'"><option value="doctor">Doctor</option><option value="lab">Lab</option></select>
  <label for="ap_n">Name</label><input id="ap_n"><div id="ap_doc"><div class="row"><div class="grow"><label for="ap_s">Specialty</label><input id="ap_s" placeholder="e.g. General Physician"></div><div class="grow"><label for="ap_f">Consultation fee (₹)</label><input id="ap_f" type="number" min="1"></div></div></div>
  <label for="ap_a">Address</label><input id="ap_a"><label for="ap_ph">Phone</label><input id="ap_ph">
  <div class="row"><div class="grow"><label for="ap_la">Latitude</label><input id="ap_la" type="number" step="any"></div><div class="grow"><label for="ap_lo">Longitude</label><input id="ap_lo" type="number" step="any"></div></div>
  <div class="row"><div class="grow"><label for="ap_r">Rating (1-5, optional)</label><input id="ap_r" type="number" min="1" max="5" step="0.1"></div><div class="grow"><label for="ap_c">Number of reviews</label><input id="ap_c" type="number" min="0" value="0"></div></div>
  <p><button class="pill" onclick="saveProvider()">Add to directory</button></p></div>
  <div class="card"><h3>Set a lab test price</h3><label for="lt_l">Lab</label><select id="lt_l">${labs.map(l => `<option value="${l.id}">${esc(l.name)}</option>`).join("")}</select>
  <label for="lt_n">Test name</label><input id="lt_n" placeholder="e.g. HbA1c"><label for="lt_p">Price (₹)</label><input id="lt_p" type="number" min="1" step="0.01">
  <p><button onclick="saveTestPrice()">Save price</button></p><h3 style="margin-top:1.25rem">In the directory (${list.length})</h3>
  ${list.slice(0, 25).map(p => `<p class="small row"><span class="grow"><b>${esc(p.name)}</b> <span class="muted">${esc(p.kind === "doctor" ? p.specialty : "Lab")}</span></span>${p.fee ? inr(p.fee) : ""}<button class="ghost sm" onclick="toggleProvider(${p.id},${p.active ? "false" : "true"})">${p.active ? "Hide" : "Show"}</button></p>`).join("")}</div></div>`;
}
const loadSample = guard(async () => { await api("/care/load-sample", { method: "POST" }); toast("Sample providers loaded"); aProviders(); });
const saveProvider = guard(async () => {
  const doc = $("#ap_k").value === "doctor", r = $("#ap_r").value;
  await api("/care/providers", { json: { kind: $("#ap_k").value, name: $("#ap_n").value, specialty: doc ? $("#ap_s").value : null, fee: doc ? +$("#ap_f").value || null : null, address: $("#ap_a").value, phone: $("#ap_ph").value,
    lat: +$("#ap_la").value, lon: +$("#ap_lo").value, rating: r ? +r : null, review_count: +$("#ap_c").value || 0 } });
  toast("Added to the directory"); aProviders();
});
const saveTestPrice = guard(async () => { await api(`/care/providers/${$("#lt_l").value}/tests`, { json: { test_name: $("#lt_n").value, price: +$("#lt_p").value } }); toast("Price saved"); aProviders(); });
const toggleProvider = guard(async (id, on) => { await api(`/care/providers/${id}/active?active=${on}`, { method: "POST" }); aProviders(); });

const VIEWS = { bills: pBills, care: pCare, billing: aBilling, providers: aProviders, remind: pRemind, checkups: pCheckups, home: pHome, record: pRecord, chat: chatView, qr: pQr, consult: dConsult, register: aReg };

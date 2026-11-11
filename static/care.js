/* Medi-Prxn Care: dashboard, consultations + PayPal checkout, payments, settings, floating Medi AI Assistant.
   Loaded before app.js; uses its globals ($, esc, api, S, toast, guard, go, inr) only when functions run. */
const ICON = {
  dash: '<path d="M3 11l9-8 9 8"/><path d="M5 10v10h14V10"/>', book: '<rect x="3" y="5" width="18" height="16" rx="2"/><path d="M8 3v4M16 3v4M3 10h18"/>',
  pay: '<rect x="2" y="5" width="20" height="14" rx="2"/><path d="M2 10h20"/>', family: '<circle cx="9" cy="8" r="3"/><path d="M3 20c0-3.5 2.7-6 6-6s6 2.5 6 6"/><circle cx="17" cy="9" r="2.4"/><path d="M17 14c2.6 0 4 2 4 5"/>',
  remind: '<path d="M6 17V11a6 6 0 0112 0v6l1.5 2h-15z"/><path d="M10 21h4"/>', check: '<rect x="5" y="3" width="14" height="18" rx="2"/><path d="M9 12l2 2 4-4"/>',
  records: '<path d="M6 3h8l4 4v14H6z"/><path d="M14 3v4h4M9 13h6M9 17h6"/>', bills: '<path d="M6 3h12v18l-3-2-3 2-3-2-3 2z"/><path d="M9 8h6M9 12h6"/>',
  care: '<path d="M12 21s7-6.2 7-11a7 7 0 10-14 0c0 4.8 7 11 7 11z"/><circle cx="12" cy="10" r="2.5"/>', chat: '<path d="M4 5h16v11H9l-5 4z"/>',
  qr: '<rect x="4" y="4" width="6" height="6"/><rect x="14" y="4" width="6" height="6"/><rect x="4" y="14" width="6" height="6"/><path d="M14 14h3v3h3M14 20h6"/>',
  settings: '<circle cx="12" cy="12" r="3"/><path d="M12 3v3M12 18v3M3 12h3M18 12h3M5.6 5.6l2.1 2.1M16.3 16.3l2.1 2.1M18.4 5.6l-2.1 2.1M7.7 16.3l-2.1 2.1"/>',
  user: '<circle cx="12" cy="8" r="4"/><path d="M4 21c0-4 3.6-7 8-7s8 3 8 7"/>', plus: '<path d="M12 5v14M5 12h14"/>', building: '<path d="M4 21V5l8-2v18M12 9h8v12M7 9h2M7 13h2M7 17h2M15 13h2M15 17h2"/>'
};
const ico = n => `<svg viewBox="0 0 24 24" aria-hidden="true">${ICON[n] || ICON.dash}</svg>`;
const emptyBox = (icon, text, btn = "") => `<div class="empty">${ico(icon)}<p>${text}</p>${btn}</div>`;
const skel = () => `<div class="skeleton" style="width:55%"></div><div class="skeleton"></div><div class="skeleton" style="width:80%"></div>`;
const fmtSlot = s => { const d = new Date(s); return d.toLocaleDateString("en-IN", { weekday: "short", day: "numeric", month: "short" }) + ", " + d.toLocaleTimeString("en-IN", { hour: "numeric", minute: "2-digit" }); };
const fmtDay = s => new Date(s).toLocaleDateString("en-IN", { weekday: "long", day: "numeric", month: "long" });
const fmtTime = s => new Date(s).toLocaleTimeString("en-IN", { hour: "numeric", minute: "2-digit" });
const money = n => "₹" + Number(n).toLocaleString("en-IN", { maximumFractionDigits: 2 });
const stTag = b => `<span class="tag ${b.status === "paid" ? "ok" : ["refunded", "cancelled", "expired"].includes(b.status) ? "" : b.status === "needs_review" || b.status === "payment_failed" ? "bad" : "warn"}">${esc(b.status_label)}</span>`;
const sandboxNote = `<div class="demo-note" role="note"><b>Sandbox demo.</b> The doctors and appointment times here are sample data, and PayPal runs in Sandbox mode, so no real money moves and no real consultation is arranged.</div>`;

/* ---------------- dashboard ---------------- */
async function pDash() {
  $("#main").innerHTML = skel();
  const [dash, ov, rem, sum] = await Promise.all([api("/dashboard"), api("/consult/overview"), api("/reminders"), api("/bills/summary")]);
  const first = (S.me.name || "").split(" ")[0], h = new Date().getHours(), greet = h < 12 ? "Good morning" : h < 17 ? "Good afternoon" : "Good evening";
  const meds = dash.reduce((n, d) => n + d.active_medicines.length, 0), refills = dash.reduce((n, d) => n + d.active_medicines.filter(m => m.refill_due_in_days <= 0).length, 0);
  const attn = dash.reduce((n, d) => n + d.checkups_attention, 0), follow = dash.reduce((n, d) => n + d.upcoming_followups.length, 0);
  $("#main").innerHTML = `<section class="hero-card"><div><h1>${greet}, ${esc(first)}</h1><p>Medicines, check-ups and doctor visits for the whole family, in one place. Not sure what to do about a symptom? Ask the assistant first.</p></div>
    <div class="row"><button onclick="openAssistant()">Ask Medi AI Assistant</button><button class="ghost" onclick="go('book')">Book a consultation</button></div></section>
  <div class="stats"><div class="stat"><b>${dash.length}</b><span>Family members</span></div><div class="stat"><b>${meds}</b><span>Active medicines</span></div>
    <div class="stat"><b>${ov.upcoming.length}</b><span>Upcoming appointments</span></div><div class="stat"><b>${attn}</b><span>Check-ups to review</span></div><div class="stat"><b>${money(sum.spent)}</b><span>Spent this month</span></div></div>
  <div class="grid2"><section class="card"><h2>Upcoming appointments</h2>${ov.upcoming.length ? ov.upcoming.map(b => `<div class="list-row"><div><b>${esc(b.provider_name)}</b><div class="small muted">${esc(b.specialty || "")} · ${esc(b.patient_name)}</div></div><div class="small"><b>${fmtSlot(b.starts_at)}</b></div></div>`).join("")
      : emptyBox("book", "No appointments yet.", `<button class="sm" onclick="go('book')">Find a doctor</button>`)}</section>
    <section class="card"><h2>Health activity</h2><div class="list-row"><span>Doses scheduled today</span><b>${rem.length}</b></div><div class="list-row"><span>Refills due</span><b>${refills}</b></div>
      <div class="list-row"><span>Follow-ups coming up</span><b>${follow}</b></div><div class="list-row"><span>Check-ups overdue</span><b>${dash.reduce((n, d) => n + d.checkups_overdue, 0)}</b></div></section></div>
  <section class="card"><div class="row"><h2 class="grow">Family overview</h2><button class="ghost sm" onclick="addMember()">+ Add family member</button></div>
    ${dash.map(d => `<div class="list-row"><div><b>${esc(d.patient.name)}</b> <span class="muted small">${d.patient.relation !== "self" ? esc(d.patient.relation) + " · " : ""}${d.patient.age ?? ""} yrs</span></div>
      <div class="row small">${d.private ? `<span class="tag">Private</span>` : `<span class="tag info">${d.active_medicines.length} medicine${d.active_medicines.length === 1 ? "" : "s"}</span>`}${d.checkups_attention ? `<span class="tag warn">${d.checkups_attention} check-up${d.checkups_attention === 1 ? "" : "s"}</span>` : ""}
      <button class="ghost sm" onclick="S.sel=${d.patient.id};go('home')">Open</button></div></div>`).join("")}</section>
  <section class="card"><h2>Recent consultations</h2>${ov.recent.length ? ov.recent.map(b => `<div class="list-row"><div><b>${esc(b.provider_name)}</b><div class="small muted">${fmtSlot(b.starts_at)} · ${esc(b.patient_name)}</div></div>${stTag(b)}</div>`).join("") : `<p class="muted">Past consultations will appear here.</p>`}</section>`;
}

/* ---------------- consultations: browse, book, pay ---------------- */
S.bk = { step: 1, pid: null, spec: "", sort: "soon", prov: null, type: "first_visit", slot: null, quote: null, shareSummary: false, ref: null, done: null };
let PPCFG = null;
function bkReset() { Object.assign(S.bk, { step: 1, prov: null, slot: null, quote: null, ref: null, done: null, shareSummary: false }); }
async function pBook() {
  S.bkTab = S.bkTab || "new"; S.bk.pid = S.bk.pid || S.family[0]?.id;
  const T = (id, l) => `<button role="tab" aria-selected="${S.bkTab === id}" onclick="S.bkTab='${id}';pBook()">${l}</button>`;
  $("#main").innerHTML = `<div class="page-head"><div><h1>Consultations</h1><p class="muted">Book a doctor and pay securely with PayPal.</p></div></div>${sandboxNote}
    <div class="tabs" role="tablist">${T("new", "Book a consultation")}${T("mine", "My bookings")}</div><div id="bkbody">${skel()}</div>`;
  S.bkTab === "mine" ? await bkMine() : await bkStep();
}
const stepper = n => `<div class="steps" aria-label="Booking steps">${["1  Choose a doctor", "2  Pick a time", "3  Review and pay"].map((l, i) => `<span class="${n === i + 1 ? "on" : n > i + 1 ? "done" : ""}">${l}</span>`).join("")}</div>`;
async function bkStep() {
  const B = S.bk, el = $("#bkbody");
  if (B.step === 4) return bkDone();
  if (B.step === 1) {
    B.data = await api("/consult/providers");
    let rows = B.data.providers.filter(p => !B.spec || p.specialty === B.spec);
    rows.sort((a, b) => B.sort === "fee" ? a.fee - b.fee : B.sort === "rating" ? (b.rating || 0) - (a.rating || 0) : (a.next_slot || "9") < (b.next_slot || "9") ? -1 : 1);
    el.innerHTML = `${stepper(1)}<div class="card"><div class="row"><div class="grow"><label for="bm">Who is the consultation for?</label><select id="bm" onchange="S.bk.pid=+this.value">${S.family.map(f => `<option value="${f.id}" ${f.id == B.pid ? "selected" : ""}>${esc(f.name)}${f.relation !== "self" ? " (" + esc(f.relation) + ")" : ""}</option>`).join("")}</select></div>
      <div><label for="bs">Sort by</label><select id="bs" onchange="S.bk.sort=this.value;bkStep()"><option value="soon" ${B.sort === "soon" ? "selected" : ""}>Earliest time</option><option value="fee" ${B.sort === "fee" ? "selected" : ""}>Lowest fee</option><option value="rating" ${B.sort === "rating" ? "selected" : ""}>Top rated</option></select></div></div>
      <p><button class="ghost sm" onclick="openAssistant()">Not sure which doctor? Ask the assistant</button></p></div>
    <div class="chips" role="group" aria-label="Specialty"><button class="chip" aria-pressed="${!B.spec}" onclick="S.bk.spec='';bkStep()">All</button>${B.data.specialties.map(s => `<button class="chip" aria-pressed="${B.spec === s}" onclick="S.bk.spec='${esc(s)}';bkStep()">${esc(s)}</button>`).join("")}</div>
    ${rows.length ? `<div class="pgrid">${rows.map(p => `<article class="pcard"><h3>${esc(p.name)}</h3><span class="muted small">${esc(p.specialty || "")}${p.clinic ? " · " + esc(p.clinic) : ""}</span>
      <div class="fee">${money(p.fee)} <span class="small muted">consultation</span></div><div class="small">${p.rating ? "★ " + p.rating + " (" + p.reviews + " reviews)" : "No ratings yet"}</div>
      <div class="small ${p.open_slots ? "" : "muted"}">${p.next_slot ? "Next: " + fmtSlot(p.next_slot) : "No open times"}</div><button ${p.open_slots ? "" : "disabled"} onclick="bkPick(${p.id})">${p.open_slots ? "Choose times" : "Unavailable"}</button></article>`).join("")}</div>`
      : emptyBox("book", "No doctors are available for booking yet. Ask the clinic admin to load providers and sample appointment times.")}`;
  } else if (B.step === 2) {
    const slots = await api(`/consult/providers/${B.prov.id}/slots`), byDay = {}; slots.forEach(s => (byDay[s.starts_at.slice(0, 10)] ||= []).push(s));
    const types = B.data.types;
    el.innerHTML = `${stepper(2)}<div class="card"><div class="row"><div class="grow"><h2>${esc(B.prov.name)}</h2><span class="muted">${esc(B.prov.specialty || "")}</span></div><button class="ghost sm" onclick="S.bk.step=1;bkStep()">Change doctor</button></div>
      <h3 style="margin-top:1rem">Type of consultation</h3>${types.map(t => `<label class="radio"><input type="radio" name="ct" ${B.type === t.id ? "checked" : ""} onchange="S.bk.type='${t.id}'"> ${esc(t.label)} <b style="margin-left:auto">${money(B.prov.fee * t.percent / 100)}</b></label>`).join("")}
      <h3 style="margin-top:1rem">Choose a time</h3>${Object.keys(byDay).length ? Object.entries(byDay).map(([d, ss]) => `<div class="day">${fmtDay(d)}</div><div class="slots">${ss.map(s => `<button class="slot" aria-pressed="${B.slot?.id === s.id}" onclick="S.bk.slot={id:${s.id},starts_at:'${s.starts_at}'};bkStep()">${fmtTime(s.starts_at)}</button>`).join("")}</div>`).join("") : emptyBox("book", "No open times for this doctor right now.")}
      <p style="margin-top:1rem"><button ${B.slot ? "" : "disabled"} onclick="bkReview()">Continue</button></p></div>`;
  } else {
    const q = B.quote, sums = S.assist.summary ? [S.assist.summary] : [];
    PPCFG = PPCFG || await api("/paypal/config");
    el.innerHTML = `${stepper(3)}<div class="card"><h2>Review your booking</h2>
      <div class="list-row"><span>Doctor</span><b>${esc(q.provider)} · ${esc(q.specialty || "")}</b></div><div class="list-row"><span>For</span><b>${esc(S.family.find(f => f.id == B.pid)?.name || "")}</b></div>
      <div class="list-row"><span>When</span><b>${fmtSlot(q.starts_at)}</b></div>
      <div class="price" style="margin-top:.8rem"><div class="ln"><span>${esc(B.data.types.find(t => t.id === B.type).label)}</span><span>${money(q.consultation_fee)}</span></div><div class="ln"><span>Booking fee</span><span>${money(q.booking_fee)}</span></div><div class="ln tot"><span>Total</span><span>${money(q.total_inr)}</span></div></div>
      <p class="small muted">PayPal charges <b>${esc(q.charge_value)} ${esc(q.charge_currency)}</b>. ${esc(q.rate_note)}</p>
      ${sums.length ? `<label class="radio"><input type="checkbox" onchange="S.bk.shareSummary=this.checked"> Attach my Medi AI Assistant summary to this booking (it is saved to your account)</label>` : ""}
      <p class="small muted">The time is held for 15 minutes while you pay. If you cancel at least 24 hours before the visit you get a full refund.</p>
      ${PPCFG.enabled ? `<div id="paypal-buttons" aria-label="PayPal checkout"></div><div id="payerr" class="alert high" hidden></div>` : `<div class="alert medium">Payments are not switched on for this server yet (PayPal Sandbox keys are missing). An admin needs to add them.</div>`}
      <p><button class="ghost" onclick="S.bk.step=2;bkStep()">Back</button></p></div>`;
    if (PPCFG.enabled) renderPayPal();
  }
}
const bkPick = guard(async id => { S.bk.prov = S.bk.data.providers.find(p => p.id === id); S.bk.slot = null; S.bk.step = 2; await bkStep(); });
const bkReview = guard(async () => {
  const B = S.bk; B.quote = await api("/consult/quote", { json: { provider_id: B.prov.id, slot_id: B.slot.id, consult_type: B.type, patient_id: +B.pid } });
  if (!B.quote.available) throw new Error("That time was just taken. Please pick another."); B.step = 3; await bkStep();
});
function loadPayPal(cfg) {
  if (window.paypal) return Promise.resolve();
  return new Promise((res, rej) => { const s = document.createElement("script");
    s.src = `https://www.paypal.com/sdk/js?client-id=${encodeURIComponent(cfg.client_id)}&currency=${encodeURIComponent(cfg.currency)}&intent=capture&components=buttons&disable-funding=credit,paylater`;
    s.onload = res; s.onerror = () => rej(new Error("Could not load PayPal. Please check your connection and try again.")); document.head.append(s); });
}
const payErr = m => { const e = $("#payerr"); if (e) { e.textContent = m; e.hidden = !m; } };
async function renderPayPal() {
  try { await loadPayPal(PPCFG); } catch (e) { return payErr(e.message); }
  const B = S.bk;
  paypal.Buttons({
    style: { layout: "vertical", shape: "pill", label: "pay" },
    createOrder: async () => {
      payErr("");
      let sid = null;
      if (B.shareSummary && S.assist.summary) sid = (await api("/assistant/summaries", { json: { summary: S.assist.summary, patient_id: +B.pid } })).id;   // explicit consent: the box was ticked
      const r = await api("/consult/bookings", { json: { provider_id: B.prov.id, slot_id: B.slot.id, consult_type: B.type, patient_id: +B.pid, summary_id: sid } });
      B.ref = r.booking.ref; return r.order_id;
    },
    onApprove: async data => {
      $("#paypal-buttons").innerHTML = `<p class="muted">Confirming your payment with PayPal…</p>`;
      try { B.done = (await api(`/consult/bookings/${B.ref}/capture`, { json: { order_id: data.orderID } })).booking; B.step = 4; bkStep(); }
      catch (e) { payErr(e.message); renderPayPal(); }
    },
    onCancel: async () => { if (B.ref) await api(`/consult/bookings/${B.ref}/abandon`, { method: "POST" }).catch(() => {}); B.ref = null; toast("Payment cancelled. You were not charged."); },
    onError: async () => { payErr("PayPal had a problem and the payment did not complete. You were not charged. Please try again."); if (B.ref) api(`/consult/bookings/${B.ref}/abandon`, { method: "POST" }).catch(() => {}); B.ref = null; }
  }).render("#paypal-buttons");
}
function bkDone() {
  const b = S.bk.done;
  $("#bkbody").innerHTML = `<div class="card ok-panel"><h2>Booking confirmed (sandbox demo)</h2><p>Your payment was verified by our server with PayPal. This is a demonstration booking, so no real appointment was created.</p>
    <div class="list-row"><span>Reference</span><b>${esc(b.ref)}</b></div><div class="list-row"><span>Doctor</span><b>${esc(b.provider_name)}</b></div><div class="list-row"><span>When</span><b>${fmtSlot(b.starts_at)}</b></div>
    <div class="list-row"><span>Paid</span><b>${money(b.total_inr)} (${esc(b.charge_value)} ${esc(b.charge_currency)} on PayPal)</b></div><div class="list-row"><span>PayPal transaction</span><b>${esc(b.transaction_id || "")}</b></div>
    <div class="row" style="margin-top:1rem"><button onclick="printReceipt('${esc(b.ref)}')">Download or print receipt</button><button class="ghost" onclick="bkReset();S.bkTab='mine';pBook()">View my bookings</button><button class="ghost" onclick="bkReset();pBook()">Book another</button></div></div>`;
}
async function bkMine() {
  const rows = await api("/consult/bookings"); S.bkRows = rows;
  $("#bkbody").innerHTML = rows.length ? rows.map(b => `<div class="card"><div class="row"><div class="grow"><h3 style="margin:0">${esc(b.provider_name)}</h3><span class="muted small">${esc(b.specialty || "")} · for ${esc(b.patient_name)} · ${esc(b.consult_label)}</span></div>${stTag(b)}</div>
    <p><b>${fmtSlot(b.starts_at)}</b> · ${money(b.total_inr)} · <span class="small muted">Ref ${esc(b.ref)}</span></p>
    <div class="row">${["paid", "refunded"].includes(b.status) ? `<button class="ghost sm" onclick="printReceipt('${esc(b.ref)}')">Receipt</button>` : ""}
    ${b.status === "paid" ? (b.refund_eligible ? `<button class="ghost sm" onclick="cancelBooking('${esc(b.ref)}',true)">Cancel and refund</button>` : `<span class="small muted">Refunds close ${24} hours before the visit.</span>`) : ""}
    ${["pending_payment", "payment_failed"].includes(b.status) ? `<button class="ghost sm" onclick="cancelBooking('${esc(b.ref)}',false)">Cancel</button>` : ""}</div></div>`).join("")
    : emptyBox("book", "You have no bookings yet.", `<button class="sm" onclick="S.bkTab='new';pBook()">Book a consultation</button>`);
}
const cancelBooking = guard(async (ref, paid) => {
  if (!confirm(paid ? "Cancel this booking and refund the full amount to PayPal?" : "Cancel this unpaid booking?")) return;
  await api(`/consult/bookings/${ref}/cancel`, { method: "POST" }); toast(paid ? "Refund requested through PayPal" : "Booking cancelled"); S.view === "pay" ? pPay() : bkMine();
});
const printReceipt = guard(async ref => {
  const b = await api(`/consult/bookings/${ref}`), w = window.open("", "_blank"); if (!w) return toast("Allow pop-ups to print", true);
  w.document.write(`<title>Receipt ${esc(b.ref)}</title><body style="font-family:system-ui,sans-serif;max-width:560px;margin:2rem auto;color:#17323a"><img src="/logo.png" alt="Medi-Prxn Care" style="height:60px"><h2>Payment receipt</h2>
    <p style="background:#d5f0e8;padding:.5rem .8rem;border-radius:8px;font-size:.9rem">Sandbox demonstration. No real money was charged and no real consultation was arranged.</p>
    <table width="100%" style="border-collapse:collapse">${[["Reference", b.ref], ["Patient", b.patient_name], ["Doctor", b.provider_name + (b.specialty ? ", " + b.specialty : "")], ["Appointment", fmtSlot(b.starts_at)], ["Type", b.consult_label],
      ["Consultation fee", money(b.consultation_fee)], ["Booking fee", money(b.booking_fee)], ["Total (INR)", money(b.total_inr)], ["Charged on PayPal", b.charge_value + " " + b.charge_currency], ["PayPal transaction", b.transaction_id || "-"], ["Paid on", (b.paid_at || "").replace("T", " ") + " UTC"], ["Status", b.status_label]]
      .map(([k, v]) => `<tr><td style="border-bottom:1px solid #d6e4e5;padding:.4rem;color:#587076">${esc(k)}</td><td style="border-bottom:1px solid #d6e4e5;padding:.4rem;text-align:right">${esc(v)}</td></tr>`).join("")}</table>
    <p style="margin-top:1.5rem" class="noprint"><button onclick="window.print()">Print or save as PDF</button></p></body>`); w.document.close();
});

/* ---------------- payment history ---------------- */
async function pPay() {
  const rows = (await api("/consult/bookings")).filter(b => !["pending_payment", "cancelled", "expired"].includes(b.status)); S.bkRows = rows;
  const paid = rows.filter(b => b.status === "paid").reduce((n, b) => n + b.total_inr, 0), ref = rows.filter(b => b.status === "refunded").reduce((n, b) => n + b.total_inr, 0);
  $("#main").innerHTML = `<div class="page-head"><div><h1>Payment history</h1><p class="muted">Consultation payments made through PayPal.</p></div><button class="ghost" onclick="go('bills')">Open spending tracker</button></div>${sandboxNote}
    <div class="stats"><div class="stat"><b>${money(paid)}</b><span>Paid</span></div><div class="stat"><b>${money(ref)}</b><span>Refunded</span></div><div class="stat"><b>${rows.length}</b><span>Transactions</span></div></div>
    <section class="card">${rows.length ? `<div class="tablewrap"><table class="stack"><thead><tr><th>Date</th><th>Reference</th><th>Doctor</th><th>Amount</th><th>Status</th><th></th></tr></thead><tbody>${rows.map(b => `<tr><td data-label="Date">${esc((b.paid_at || b.created_at || "").slice(0, 10))}</td><td data-label="Reference">${esc(b.ref)}</td><td data-label="Doctor">${esc(b.provider_name)}</td>
      <td data-label="Amount">${money(b.total_inr)}<div class="small muted">${esc(b.charge_value)} ${esc(b.charge_currency)}</div></td><td data-label="Status">${stTag(b)}</td><td data-label="" class="acts">${["paid", "refunded"].includes(b.status) ? `<button class="ghost sm" onclick="printReceipt('${esc(b.ref)}')">Receipt</button>` : ""}
      ${b.refund_eligible ? `<button class="ghost sm" onclick="cancelBooking('${esc(b.ref)}',true)">Refund</button>` : ""}</td></tr>`).join("")}</tbody></table></div>` : emptyBox("pay", "No payments yet. Paid consultations will be listed here.", `<button class="sm" onclick="go('book')">Book a consultation</button>`)}</section>`;
}

/* ---------------- settings ---------------- */
async function pSettings() {
  const sums = await api("/assistant/summaries");
  $("#main").innerHTML = `<div class="page-head"><h1>Settings</h1></div>
  <div class="grid2"><section class="card"><h2>Account</h2><div class="list-row"><span>Name</span><b>${esc(S.me.name)}</b></div><div class="list-row"><span>Email</span><b>${esc(S.me.email)}</b></div><div class="list-row"><span>Role</span><b>${esc(S.role)}</b></div>
    <p style="margin-top:1rem"><button class="ghost" onclick="go('home')">Manage family profiles</button> <button class="ghost" onclick="logout()">Log out</button></p></section>
  <section class="card"><h2>Privacy</h2><p class="small">The Medi AI Assistant does not save your chat. A summary is stored only if you press <b>Save</b> or tick the box when booking. Family health details are shared with the assistant only for the person you choose in the chat window. Reports you ask it to explain are not stored.</p>
    <p class="small muted">Payments: PayPal handles card and account details. This app never sees or stores them.</p></section></div>
  <section class="card"><div class="row"><h2 class="grow">Saved assistant summaries</h2>${sums.length ? `<button class="ghost sm" onclick="delSummaries()">Delete all</button>` : ""}</div>
    ${sums.length ? sums.map(s => `<div class="list-row"><div><b>${esc(s.summary.concern || "Summary")}</b><div class="small muted">${esc(s.created_at)} · ${esc(s.summary.severity || "")}</div></div><button class="ghost sm" onclick="delSummaries(${s.id})">Delete</button></div>`).join("") : `<p class="muted">Nothing saved.</p>`}</section>`;
}
const delSummaries = guard(async id => { if (!confirm(id ? "Delete this summary?" : "Delete all saved summaries?")) return; await api(id ? `/assistant/summaries/${id}` : "/assistant/summaries", { method: "DELETE" }); toast("Deleted"); pSettings(); });

/* ---------------- health records: explain a report ---------------- */
function explainTab() {
  return `<p class="muted small">Upload or paste a lab report and get a plain-language explanation of the terms. It is general information, not a diagnosis, and nothing is stored.</p>
    <label>Paste report text</label><textarea id="ex-t" rows="5"></textarea><label class="fbtn" style="margin-top:.6rem">Or choose a photo or PDF<input id="ex-f" type="file" accept="image/*,application/pdf" class="sr-only" onchange="$('#ex-n').textContent=this.files[0]?.name||''"></label> <span id="ex-n" class="small muted"></span>
    <p><button onclick="runExplain()">Explain this report</button></p><div id="ex-out"></div>`;
}
const runExplain = guard(async () => {
  const f = new FormData(), t = $("#ex-t").value.trim(), file = $("#ex-f").files[0]; if (!t && !file) throw new Error("Paste the report or choose a file");
  if (t) f.append("text", t); if (file) f.append("file", file); $("#ex-out").innerHTML = skel();
  try { const r = await api("/records/explain", { form: f }); $("#ex-out").innerHTML = `<div class="card flat"><div style="white-space:pre-wrap">${esc(r.explanation)}</div><p class="small muted">General information only. Please discuss your results with a doctor.</p></div>`; }
  catch (e) { $("#ex-out").innerHTML = ""; throw e; }
});

/* ---------------- admin: bookings ---------------- */
async function aBookings() {
  const rows = await api("/consult/admin/bookings");
  $("#main").innerHTML = `<div class="page-head"><h1>Consultation bookings</h1><button onclick="makeSlots()">Create sample appointment times</button></div>${sandboxNote}
   <section class="card">${rows.length ? `<div class="tablewrap"><table class="stack"><thead><tr><th>Ref</th><th>Patient</th><th>Doctor</th><th>When</th><th>Total</th><th>Status</th></tr></thead><tbody>${rows.map(b => `<tr><td data-label="Ref">${esc(b.ref)}</td><td data-label="Patient">${esc(b.patient_name)}</td><td data-label="Doctor">${esc(b.provider_name)}</td><td data-label="When">${fmtSlot(b.starts_at)}</td><td data-label="Total">${money(b.total_inr)}</td><td data-label="Status">${stTag(b)}</td></tr>`).join("")}</tbody></table></div>` : emptyBox("book", "No bookings yet.")}</section>`;
}
const makeSlots = guard(async () => { const r = await api("/consult/admin/sample-slots", { method: "POST" }); toast(`${r.created} sample times created`); });

/* ---------------- floating Medi AI Assistant ---------------- */
S.assist = { open: false, big: false, msgs: [], quick: [], member: "", summary: null, emergency: false, busy: false, saved: false };
try { Object.assign(S.assist, JSON.parse(sessionStorage.assist || "{}"), { open: false, busy: false }); } catch (e) { /* ignore */ }
const persistAssist = () => { try { const { msgs, quick, member, summary, emergency } = S.assist; sessionStorage.assist = JSON.stringify({ msgs, quick, member, summary, emergency }); } catch (e) { /* ignore */ } };
function mountAssistant() {
  if (S.role !== "patient" || $("#cw")) return;
  document.body.insertAdjacentHTML("beforeend", `<button class="fab" id="fab" aria-label="Open Medi AI Assistant" onclick="openAssistant()"><img src="/logo-mark.png" alt=""><span class="fl">Ask Medi AI</span></button>
  <section class="cw" id="cw" role="dialog" aria-label="Medi AI Assistant" hidden><div class="cw-h"><img src="/logo-mark.png" alt=""><div class="t"><b>Medi AI Assistant</b><small id="cw-mode">General guidance. Not a doctor.</small></div>
    <button onclick="assistBig()" aria-label="Expand or shrink" title="Expand">⤢</button><button onclick="assistClear()" aria-label="Start a new chat" title="New chat">↺</button><button onclick="closeAssistant()" aria-label="Close">✕</button></div>
    <div class="cw-for"><label for="cw-m" style="margin:0">Chat is about</label><select id="cw-m" onchange="S.assist.member=this.value;persistAssist()"></select></div>
    <div class="cw-msgs" id="cw-msgs" aria-live="polite"></div><div class="cw-q" id="cw-q"></div>
    <div class="compose"><input id="cw-in" placeholder="Describe how you feel…" aria-label="Your message" maxlength="1000"><button onclick="assistSend()" id="cw-send">Send</button></div>
    <div class="cw-foot">In an emergency call <b>112</b>. Your chat is kept only in this browser tab.</div></section>`);
  $("#cw-in").addEventListener("keydown", e => e.key === "Enter" && assistSend());
  document.addEventListener("keydown", e => { if (e.key === "Escape" && S.assist.open) closeAssistant(); });
}
function unmountAssistant() { $("#cw")?.remove(); $("#fab")?.remove(); S.assist = { open: false, big: false, msgs: [], quick: [], member: "", summary: null, emergency: false, busy: false, saved: false }; }
function openAssistant() {
  mountAssistant(); const A = S.assist; A.open = true; $("#cw").hidden = false; $("#fab").hidden = true;
  $("#cw-m").innerHTML = `<option value="">Myself / general</option>` + S.family.map(f => `<option value="${f.id}" ${f.id == A.member ? "selected" : ""}>${esc(f.name)}${f.relation !== "self" ? " (" + esc(f.relation) + ")" : ""}</option>`).join("");
  if (!A.msgs.length) guard(assistStart)(); else drawAssist(); $("#cw-in").focus();
}
function closeAssistant() { S.assist.open = false; $("#cw").hidden = true; $("#fab").hidden = false; }
function assistBig() { S.assist.big = !S.assist.big; $("#cw").classList.toggle("big", S.assist.big); }
function assistClear() { Object.assign(S.assist, { msgs: [], quick: [], summary: null, emergency: false, saved: false }); persistAssist(); guard(assistStart)(); }
const setMode = m => { const e = $("#cw-mode"); if (e && m) e.textContent = m === "gemini" ? "Powered by Gemini AI · Not a doctor" : "Guided mode (no AI key) · Not a doctor"; };
async function assistStart() { const r = await api("/assistant/start"); setMode(r.mode); Object.assign(S.assist, { msgs: [{ role: "assistant", content: r.reply }], quick: r.quick_replies }); persistAssist(); drawAssist(); }
function drawAssist() {
  const A = S.assist, box = $("#cw-msgs"); if (!box) return;
  box.innerHTML = A.msgs.map(m => m.emergency ? `<div class="msg a emerg" role="alert"><b>Possible emergency</b><br>${esc(m.content)}<br><a href="tel:112">Call 112 now</a></div>` : `<div class="msg ${m.role === "user" ? "q" : "a"}">${esc(m.content)}</div>`).join("")
    + (A.busy ? `<div class="msg a typing" aria-label="Assistant is typing"><span></span><span></span><span></span></div>` : "") + (A.summary ? sumCard(A.summary) : "");
  $("#cw-q").innerHTML = A.busy || A.emergency ? (A.emergency ? `<button onclick="assistClear()">Start over</button>` : "") : A.quick.map(q => `<button onclick="assistQuick(this.dataset.q)" data-q="${esc(q)}">${esc(q)}</button>`).join("");
  box.scrollTop = 1e9;
}
function sumCard(s) {
  const L = (t, a) => a && a.length ? `<h4>${t}</h4><ul>${a.map(x => `<li>${esc(x)}</li>`).join("")}</ul>` : "";
  return `<div class="sumcard"><b>Summary</b> <span class="tag info">${esc(s.severity || "")}</span><p class="small muted" style="margin:.2rem 0">${esc(s.concern || "")} · ${esc(s.duration || "")} · ${esc(s.age_group || "")}</p>${L("Key points", s.key_points)}${L("General guidance", s.general_guidance)}${L("See a doctor if", s.when_to_seek_care)}
    <p class="small muted">${esc(s.disclaimer || "")}</p><div class="row"><button class="sm" onclick="assistSave()" ${S.assist.saved ? "disabled" : ""}>${S.assist.saved ? "Saved" : "Save summary"}</button><button class="ghost sm" onclick="assistCopy()">Copy</button>${s.suggested_specialty ? `<button class="ghost sm" onclick="assistBook()">Find a doctor</button>` : ""}</div></div>`;
}
const assistQuick = q => { if (q === "Start over") return assistClear(); if (q === "Book a consultation") return assistBook(); $("#cw-in").value = q; assistSend(); };
const assistBook = () => { closeAssistant(); if (S.view !== "book") { S.bkTab = "new"; bkReset(); go("book"); } };
const assistSave = guard(async () => { await api("/assistant/summaries", { json: { summary: S.assist.summary, patient_id: S.assist.member ? +S.assist.member : null } }); S.assist.saved = true; toast("Summary saved to your account"); drawAssist(); });
const assistCopy = () => { const s = S.assist.summary; navigator.clipboard?.writeText(`Medi AI Assistant summary\nConcern: ${s.concern}\nDuration: ${s.duration}\nSeverity: ${s.severity}\nAge group: ${s.age_group}\nHistory: ${s.history}\n\n${(s.general_guidance || []).join("\n")}\n\n${s.disclaimer}`).then(() => toast("Copied")); };
async function assistSend() {
  const A = S.assist, inp = $("#cw-in"), text = inp.value.trim(); if (!text || A.busy || A.emergency) return; inp.value = "";
  A.msgs.push({ role: "user", content: text }); A.quick = []; A.busy = true; drawAssist();
  try {
    const r = await api("/assistant/message", { json: { messages: A.msgs.filter(m => !m.emergency).map(({ role, content }) => ({ role, content })), patient_id: A.member ? +A.member : null } });
    A.busy = false; if (!r.emergency) setMode(r.mode); A.msgs.push({ role: "assistant", content: r.reply, emergency: r.emergency }); A.quick = r.quick_replies || []; A.emergency = r.emergency; A.summary = r.summary || A.summary; if (r.summary) A.saved = false;
  } catch (e) { A.busy = false; A.msgs.push({ role: "assistant", content: e.message || "Something went wrong. Please try again." }); }
  persistAssist(); drawAssist();
}

const CARE = { views: { dash: pDash, book: pBook, pay: pPay, settings: pSettings, bookings: aBookings } };
Object.assign(VIEWS, CARE.views);
boot();

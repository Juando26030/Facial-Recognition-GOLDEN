/* Selector de hora tipo reloj analógico — sin dependencias externas.
   Uso: attachClockPicker(inputEl) sobre un <input type="text"> que va a guardar "HH:MM" (24h). */
(function () {
  const NS = "http://www.w3.org/2000/svg";
  const RADIUS = 100;
  const CENTER = 110;
  const SIZE = 220;

  let popupEl = null;
  let currentInput = null;
  let state = { hour: 12, minute: 0, period: "AM", mode: "hour" };

  function polar(radius, indexOutOf12) {
    const angle = (indexOutOf12 / 12) * 2 * Math.PI - Math.PI / 2;
    return { x: CENTER + radius * Math.cos(angle), y: CENTER + radius * Math.sin(angle) };
  }

  function buildPopup() {
    const el = document.createElement("div");
    el.id = "clockPickerPopup";
    el.style.cssText = `
      position: absolute; z-index: 5000; background: white; border-radius: 20px;
      box-shadow: 0 15px 45px rgba(0,0,0,0.25); padding: 1.2rem; display: none;
      width: 260px; font-family: var(--font-body, sans-serif); user-select: none;
    `;
    el.innerHTML = `
      <div style="text-align:center; font-family: var(--font-heading-secondary, sans-serif); font-weight:700; font-size:1.6rem; color: var(--golden-dark, #0a0e2e); margin-bottom: 0.8rem;">
        <span id="cpHourLabel" style="cursor:pointer; padding: 4px 8px; border-radius: 8px;">12</span>
        <span>:</span>
        <span id="cpMinuteLabel" style="cursor:pointer; padding: 4px 8px; border-radius: 8px;">00</span>
        <span style="display:inline-flex; flex-direction:column; vertical-align:middle; margin-left:10px; font-size:0.7rem;">
          <button type="button" id="cpAM" style="border:1px solid #ccc; background:white; border-radius:6px 6px 0 0; padding:2px 8px; cursor:pointer;">AM</button>
          <button type="button" id="cpPM" style="border:1px solid #ccc; border-top:none; background:white; border-radius:0 0 6px 6px; padding:2px 8px; cursor:pointer;">PM</button>
        </span>
      </div>
      <svg id="cpFace" width="${SIZE}" height="${SIZE}" viewBox="0 0 ${SIZE} ${SIZE}" style="display:block; margin:auto;"></svg>
      <div style="text-align:right; margin-top:0.8rem;">
        <button type="button" id="cpCancel" style="border:none; background:none; color:#888; padding:8px 14px; cursor:pointer; font-weight:600;">Cancelar</button>
        <button type="button" id="cpDone" style="border:none; background: var(--golden-primary, #D4AF37); color: var(--golden-dark, #0a0e2e); padding:8px 18px; border-radius:20px; cursor:pointer; font-weight:700;">Listo</button>
      </div>
    `;
    document.body.appendChild(el);

    el.querySelector("#cpHourLabel").addEventListener("click", () => { state.mode = "hour"; renderFace(); });
    el.querySelector("#cpMinuteLabel").addEventListener("click", () => { state.mode = "minute"; renderFace(); });
    el.querySelector("#cpAM").addEventListener("click", () => { state.period = "AM"; renderFace(); });
    el.querySelector("#cpPM").addEventListener("click", () => { state.period = "PM"; renderFace(); });
    el.querySelector("#cpCancel").addEventListener("click", closePicker);
    el.querySelector("#cpDone").addEventListener("click", confirmAndClose);

    document.addEventListener("click", (e) => {
      if (popupEl && popupEl.style.display === "block" && !popupEl.contains(e.target) && e.target !== currentInput) {
        closePicker();
      }
    });

    return el;
  }

  function renderFace() {
    const svg = popupEl.querySelector("#cpFace");
    svg.innerHTML = "";

    const bg = document.createElementNS(NS, "circle");
    bg.setAttribute("cx", CENTER); bg.setAttribute("cy", CENTER); bg.setAttribute("r", RADIUS + 10);
    bg.setAttribute("fill", "#f8f6f0");
    svg.appendChild(bg);

    const centerDot = document.createElementNS(NS, "circle");
    centerDot.setAttribute("cx", CENTER); centerDot.setAttribute("cy", CENTER); centerDot.setAttribute("r", 4);
    centerDot.setAttribute("fill", "var(--golden-dark, #0a0e2e)");

    const isHourMode = state.mode === "hour";
    const selectedIndex = isHourMode ? (state.hour % 12) : (state.minute / 5) % 12;
    const target = polar(RADIUS, selectedIndex);

    const hand = document.createElementNS(NS, "line");
    hand.setAttribute("x1", CENTER); hand.setAttribute("y1", CENTER);
    hand.setAttribute("x2", target.x); hand.setAttribute("y2", target.y);
    hand.setAttribute("stroke", "var(--golden-primary, #D4AF37)");
    hand.setAttribute("stroke-width", 3);
    svg.appendChild(hand);

    for (let i = 0; i < 12; i++) {
      const p = polar(RADIUS, i);
      const value = isHourMode ? (i === 0 ? 12 : i) : i * 5;
      const isSelected = i === selectedIndex;

      const circle = document.createElementNS(NS, "circle");
      circle.setAttribute("cx", p.x); circle.setAttribute("cy", p.y); circle.setAttribute("r", 16);
      circle.setAttribute("fill", isSelected ? "var(--golden-primary, #D4AF37)" : "transparent");
      circle.style.cursor = "pointer";
      circle.addEventListener("click", () => selectValue(value));
      svg.appendChild(circle);

      const text = document.createElementNS(NS, "text");
      text.setAttribute("x", p.x); text.setAttribute("y", p.y + 5);
      text.setAttribute("text-anchor", "middle");
      text.setAttribute("font-size", "14");
      text.setAttribute("font-weight", isSelected ? "700" : "500");
      text.setAttribute("fill", isSelected ? "white" : "var(--golden-dark, #0a0e2e)");
      text.style.pointerEvents = "none";
      text.textContent = String(value).padStart(2, "0");
      svg.appendChild(text);
    }

    svg.appendChild(centerDot);

    popupEl.querySelector("#cpHourLabel").textContent = String(state.hour).padStart(2, "0");
    popupEl.querySelector("#cpHourLabel").style.background = isHourMode ? "#f8f6f0" : "transparent";
    popupEl.querySelector("#cpMinuteLabel").textContent = String(state.minute).padStart(2, "0");
    popupEl.querySelector("#cpMinuteLabel").style.background = !isHourMode ? "#f8f6f0" : "transparent";
    popupEl.querySelector("#cpAM").style.background = state.period === "AM" ? "var(--golden-primary, #D4AF37)" : "white";
    popupEl.querySelector("#cpPM").style.background = state.period === "PM" ? "var(--golden-primary, #D4AF37)" : "white";
  }

  function selectValue(value) {
    if (state.mode === "hour") {
      state.hour = value;
      state.mode = "minute";
    } else {
      state.minute = value;
    }
    renderFace();
  }

  function to24h() {
    let h = state.hour % 12;
    if (state.period === "PM") h += 12;
    return `${String(h).padStart(2, "0")}:${String(state.minute).padStart(2, "0")}`;
  }

  function parseFrom24h(value) {
    if (!value || !/^\d{2}:\d{2}$/.test(value)) {
      state = { hour: 12, minute: 0, period: "AM", mode: "hour" };
      return;
    }
    let [h, m] = value.split(":").map(Number);
    const period = h >= 12 ? "PM" : "AM";
    h = h % 12;
    if (h === 0) h = 12;
    state = { hour: h, minute: m, period, mode: "hour" };
  }

  function openPicker(input) {
    if (!popupEl) popupEl = buildPopup();
    currentInput = input;
    parseFrom24h(input.value);
    renderFace();
    const rect = input.getBoundingClientRect();
    popupEl.style.top = `${window.scrollY + rect.bottom + 6}px`;
    popupEl.style.left = `${window.scrollX + rect.left}px`;
    popupEl.style.display = "block";
  }

  function closePicker() {
    if (popupEl) popupEl.style.display = "none";
    currentInput = null;
  }

  function confirmAndClose() {
    if (currentInput) {
      currentInput.value = to24h();
      currentInput.dispatchEvent(new Event("change", { bubbles: true }));
    }
    closePicker();
  }

  window.attachClockPicker = function (input) {
    input.readOnly = true;
    input.style.cursor = "pointer";
    input.placeholder = "Seleccionar hora";
    input.addEventListener("click", () => openPicker(input));
  };
})();

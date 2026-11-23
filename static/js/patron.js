// Componente de patrón de desbloqueo de 9 puntos (mouse, touch o stylus).
// Guarda la secuencia como "1-2-3-6-9" en el input oculto #patron.
(function () {
  const grid = document.getElementById("patron-grid");
  const input = document.getElementById("patron");
  const canvas = document.getElementById("patron-canvas");
  const texto = document.getElementById("patron-texto");
  const borrar = document.getElementById("patron-borrar");
  if (!grid) return;

  const ctx = canvas.getContext("2d");
  const dots = Array.from(grid.querySelectorAll(".dot"));
  let seq = input.value ? input.value.split("-").map(Number) : [];
  let dibujando = false;
  let puntero = null;

  function centro(dot) {
    const g = grid.getBoundingClientRect();
    const r = dot.getBoundingClientRect();
    return { x: r.left - g.left + r.width / 2, y: r.top - g.top + r.height / 2 };
  }

  function pintar() {
    canvas.width = grid.clientWidth;
    canvas.height = grid.clientHeight;
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    if (seq.length) {
      ctx.strokeStyle = "#4f8cff";
      ctx.lineWidth = 4;
      ctx.lineCap = ctx.lineJoin = "round";
      ctx.beginPath();
      seq.forEach((n, i) => {
        const c = centro(dots[n - 1]);
        i ? ctx.lineTo(c.x, c.y) : ctx.moveTo(c.x, c.y);
      });
      if (dibujando && puntero) ctx.lineTo(puntero.x, puntero.y);
      ctx.stroke();
    }
    dots.forEach((d) => d.classList.toggle("on", seq.includes(Number(d.dataset.n))));
    input.value = seq.join("-");
    texto.textContent = seq.length ? seq.join(" → ") : "Sin patrón";
  }

  function leer(e) {
    const el = document.elementFromPoint(e.clientX, e.clientY);
    if (el && el.classList.contains("dot")) {
      const n = Number(el.dataset.n);
      if (!seq.includes(n)) seq.push(n);
    }
    const g = grid.getBoundingClientRect();
    puntero = { x: e.clientX - g.left, y: e.clientY - g.top };
  }

  grid.addEventListener("pointerdown", (e) => {
    e.preventDefault();
    seq = [];
    dibujando = true;
    grid.setPointerCapture(e.pointerId);
    leer(e);
    pintar();
  });
  grid.addEventListener("pointermove", (e) => {
    if (!dibujando) return;
    leer(e);
    pintar();
  });
  const fin = () => { dibujando = false; puntero = null; pintar(); };
  grid.addEventListener("pointerup", fin);
  grid.addEventListener("pointercancel", fin);
  borrar.addEventListener("click", () => { seq = []; pintar(); });
  window.addEventListener("resize", pintar);
  pintar();
})();

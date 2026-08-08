/* ─────────────────────────────────────────────────────────────
   LoveSprint — runtime compartido (Fase 0 PRO)
   · Contexto de persona ("soy Diego / soy X") con selector elegante
   · Chip de persona en el sidebar (cambiar con un toque)
   · Registro del service worker (PWA instalable)
   Se carga en todas las páginas del tablero. Todo vive bajo window.DD
   para no chocar con las variables propias de cada página.
   ───────────────────────────────────────────────────────────── */
(function () {
  const API = (location.hostname === 'localhost' || location.hostname === '127.0.0.1')
    ? 'http://localhost:5050/api' : '/api';

  const DD = {
    personas: [],
    api: API,

    async token() {
      let t = localStorage.getItem('organizador_token') || '';
      if (t) return t;
      try {
        const r = await fetch(API + '/local-token');
        if (r.ok) {
          const d = await r.json();
          if (d.token) { localStorage.setItem('organizador_token', d.token); return d.token; }
        }
      } catch (_) {}
      DD._irLogin();
      return '';
    },

    _irLogin() {
      if (location.pathname.endsWith('/login.html')) return;
      location.href = '/tablero/login.html?next=' + encodeURIComponent(location.pathname + location.search);
    },

    salir() {
      localStorage.removeItem('organizador_token');
      localStorage.removeItem('dd_persona_id');
      location.href = '/tablero/login.html';
    },

    async fetch(ruta, opts = {}) {
      const t = await DD.token();
      opts.headers = Object.assign({ 'X-API-Token': t }, opts.headers || {});
      if (opts.body && !opts.headers['Content-Type']) opts.headers['Content-Type'] = 'application/json';
      const r = await fetch(API + ruta, opts);
      if (!r.ok) throw new Error('API ' + r.status + ' en ' + ruta);
      return r.json();
    },

    /* ── Persona actual ── */
    personaId() { return localStorage.getItem('dd_persona_id') || ''; },

    persona() {
      const id = DD.personaId();
      return DD.personas.find(p => p.id === id) || null;
    },

    async cargarPersonas() {
      try {
        const d = await DD.fetch('/personas');
        DD.personas = (d.personas || []).filter(p => p.activo !== false);
      } catch (e) {
        console.warn('DD personas:', e.message);
        DD.personas = [];
      }
      return DD.personas;
    },

    elegir(id) {
      localStorage.setItem('dd_persona_id', id);
      document.dispatchEvent(new CustomEvent('dd:persona', { detail: { id } }));
      DD._pintarChip();
      DD._cerrarSelector();
    },

    iniciales(p) {
      return (p.nombre || '?').trim().split(/\s+/).map(w => w[0]).slice(0, 2).join('').toUpperCase();
    },

    /* ── Selector (overlay de bienvenida) ── */
    abrirSelector(forzar = false) {
      if (!forzar && DD.persona()) return;
      DD._cerrarSelector();
      const ov = document.createElement('div');
      ov.className = 'dd-persona-overlay';
      ov.id = 'dd-persona-overlay';
      const puedeCerrar = !!DD.persona();
      ov.innerHTML = `
        <div class="dd-persona-caja" role="dialog" aria-modal="true" aria-label="Elegir persona">
          <div class="dd-persona-marca"><img src="/tablero/lovesprint-mark.png" alt="LoveSprint" class="brand-logo" style="width:26px;height:26px;vertical-align:-6px;margin-right:8px;filter:drop-shadow(0 1px 2px rgba(0,0,0,.25))">Love<em>Sprint</em></div>
          <h2 class="dd-persona-titulo">¿Quién está aquí?</h2>
          <p class="dd-persona-sub">Elige tu perfil para ver tus proyectos, tus avisos y tu plan del día.</p>
          <div class="dd-persona-cards">
            ${DD.personas.map(p => `
              <button class="dd-persona-card" data-id="${p.id}" style="--pc:${p.color}">
                <span class="dd-persona-avatar">${p.emoji || DD.iniciales(p)}</span>
                <span class="dd-persona-nombre">${p.nombre}</span>
                <span class="dd-persona-hola">soy yo →</span>
              </button>`).join('')}
          </div>
          <div class="dd-persona-acciones">
            <button class="dd-persona-editar" id="dd-editar-nombres">✎ Editar perfiles y avisos</button>
            <button class="dd-persona-logout" id="dd-persona-logout">↪ Cerrar sesión</button>
          </div>
          ${puedeCerrar ? '<button class="dd-persona-cerrar" id="dd-persona-cerrar" aria-label="Cerrar">✕</button>' : ''}
        </div>`;
      document.body.appendChild(ov);
      requestAnimationFrame(() => ov.classList.add('visible'));

      ov.querySelectorAll('.dd-persona-card').forEach(b =>
        b.addEventListener('click', () => DD.elegir(b.dataset.id)));
      const btnEd = ov.querySelector('#dd-editar-nombres');
      if (btnEd) btnEd.addEventListener('click', () => DD._modoEdicion(ov));
      const btnOut = ov.querySelector('#dd-persona-logout');
      if (btnOut) btnOut.addEventListener('click', () => DD.salir());
      const btnX = ov.querySelector('#dd-persona-cerrar');
      if (btnX) btnX.addEventListener('click', () => DD._cerrarSelector());
    },

    _modoEdicion(ov) {
      const cont = ov.querySelector('.dd-persona-cards');
      cont.classList.add('editando-lista');
      cont.innerHTML = DD.personas.map(p => `
        <div class="dd-persona-fila" style="--pc:${p.color}">
          <div class="dd-fila-top">
            <input type="color" class="dd-persona-color" data-id="${p.id}" value="${p.color}" aria-label="Color">
            <input class="dd-persona-input" data-id="${p.id}" value="${p.nombre}" maxlength="20" aria-label="Nombre" placeholder="Nombre">
          </div>
          <label class="dd-fila-tg">
            <span>Telegram chat ID <small>(opcional)</small></span>
            <input class="dd-persona-tg" data-id="${p.id}" value="${p.telegram_chat_id || ''}" inputmode="numeric" placeholder="ej. 5654764212">
          </label>
          <button type="button" class="dd-btn-push" data-id="${p.id}">🔔 Recibir avisos en este celular</button>
          <span class="dd-push-estado" data-id="${p.id}"></span>
        </div>`).join('');

      cont.querySelectorAll('.dd-btn-push').forEach(b =>
        b.addEventListener('click', () => DD.activarPush(b.dataset.id, ov)));

      if (!cont.querySelector('.dd-cambiar-clave')) {
        const cc = document.createElement('button');
        cc.type = 'button'; cc.className = 'dd-cambiar-clave';
        cc.textContent = '🔒 Cambiar mi contraseña';
        cc.addEventListener('click', () => { DD._cerrarSelector(); DD.cambiarClave(); });
        cont.appendChild(cc);
      }
      if (!cont.querySelector('.dd-salir')) {
        const salir = document.createElement('button');
        salir.type = 'button'; salir.className = 'dd-salir';
        salir.textContent = '↪ Salir / cambiar de persona';
        salir.addEventListener('click', () => DD.salir());
        cont.appendChild(salir);
      }

      const btnEd = ov.querySelector('#dd-editar-nombres');
      btnEd.textContent = '✓ Guardar cambios';
      btnEd.onclick = async () => {
        btnEd.textContent = 'Guardando…';
        for (const p of DD.personas) {
          const inp = cont.querySelector(`.dd-persona-input[data-id="${p.id}"]`);
          const col = cont.querySelector(`.dd-persona-color[data-id="${p.id}"]`);
          const tg = cont.querySelector(`.dd-persona-tg[data-id="${p.id}"]`);
          const nombre = (inp?.value || '').trim() || p.nombre;
          const color = col?.value || p.color;
          const chat = (tg?.value || '').trim();
          if (nombre !== p.nombre || color !== p.color || chat !== (p.telegram_chat_id || '')) {
            try {
              await DD.fetch('/personas/' + p.id, { method: 'PUT',
                body: JSON.stringify({ nombre, color, telegram_chat_id: chat }) });
              p.nombre = nombre; p.color = color; p.telegram_chat_id = chat;
            } catch (e) { console.warn('DD guardar persona:', e.message); }
          }
        }
        DD._cerrarSelector();
        DD.abrirSelector(true);
      };
    },

    /* ── Web Push: suscribir este dispositivo a los avisos de una persona ── */
    async activarPush(personaId, ov) {
      const est = ov?.querySelector(`.dd-push-estado[data-id="${personaId}"]`);
      const set = (t, ok) => { if (est) { est.textContent = t; est.className = 'dd-push-estado' + (ok ? ' ok' : ' err'); } };
      try {
        if (!('serviceWorker' in navigator) || !('PushManager' in window)) {
          set('Este navegador no soporta avisos', false); return;
        }
        set('Pidiendo permiso…');
        const permiso = await Notification.requestPermission();
        if (permiso !== 'granted') { set('Permiso denegado en el navegador', false); return; }
        const reg = await navigator.serviceWorker.ready;
        const { clave, disponible } = await DD.fetch('/push/clave-publica');
        if (!disponible || !clave) { set('El servidor aún no tiene avisos push', false); return; }
        let sub = await reg.pushManager.getSubscription();
        if (!sub) {
          sub = await reg.pushManager.subscribe({
            userVisibleOnly: true,
            applicationServerKey: DD._urlB64ToUint8(clave),
          });
        }
        await DD.fetch('/push/suscribir', { method: 'POST',
          body: JSON.stringify({ persona_id: personaId, subscription: sub.toJSON() }) });
        await DD.fetch('/push/prueba', { method: 'POST', body: JSON.stringify({ persona_id: personaId }) });
        set('✓ Activado — te enviamos una prueba', true);
      } catch (e) {
        console.warn('activarPush:', e);
        set('No se pudo activar: ' + e.message, false);
      }
    },

    _urlB64ToUint8(base64) {
      const pad = '='.repeat((4 - (base64.length % 4)) % 4);
      const b64 = (base64 + pad).replace(/-/g, '+').replace(/_/g, '/');
      const raw = atob(b64);
      const arr = new Uint8Array(raw.length);
      for (let i = 0; i < raw.length; i++) arr[i] = raw.charCodeAt(i);
      return arr;
    },

    /* ── Toast simple compartido ── */
    toast(msg, ok) {
      let t = document.getElementById('dd-toast');
      if (!t) { t = document.createElement('div'); t.id = 'dd-toast'; t.className = 'dd-toast'; document.body.appendChild(t); }
      t.textContent = msg; t.className = 'dd-toast visible' + (ok === false ? ' err' : ok === true ? ' ok' : '');
      clearTimeout(DD._toastT); DD._toastT = setTimeout(() => t.classList.remove('visible'), 3000);
    },

    /* ── Rol: 'admin' = Diego (persona_diego). Oculta lo que no le sirve a la pareja ── */
    esAdmin() { return DD.personaId() === 'persona_diego'; },
    _aplicarRol() {
      const admin = DD.esAdmin();
      document.querySelectorAll('[data-solo-admin]').forEach(el => { el.style.display = admin ? '' : 'none'; });
    },

    /* ── Activar avisos para la persona actual en ESTE dispositivo ── */
    async pushActivo() {
      try {
        if (!('serviceWorker' in navigator) || !('PushManager' in window)) return false;
        const conLimite = Promise.race([
          navigator.serviceWorker.ready,
          new Promise((_, rej) => setTimeout(() => rej(new Error('sw timeout')), 3000)),
        ]);
        const reg = await conLimite;
        return !!(await reg.pushManager.getSubscription());
      } catch (_) { return false; }
    },
    async activarPushActual() {
      const pid = DD.personaId();
      if (!pid) { DD.abrirSelector(true); return; }
      try {
        if (!('serviceWorker' in navigator) || !('PushManager' in window)) { DD.toast('Este navegador no soporta avisos', false); return; }
        const permiso = await Notification.requestPermission();
        if (permiso !== 'granted') { DD.toast('Diste "no" al permiso de avisos', false); return; }
        const reg = await navigator.serviceWorker.ready;
        const { clave, disponible } = await DD.fetch('/push/clave-publica');
        if (!disponible || !clave) { DD.toast('El servidor no tiene avisos configurados', false); return; }
        let sub = await reg.pushManager.getSubscription();
        if (!sub) sub = await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: DD._urlB64ToUint8(clave) });
        await DD.fetch('/push/suscribir', { method: 'POST', body: JSON.stringify({ persona_id: pid, subscription: sub.toJSON() }) });
        await DD.fetch('/push/prueba', { method: 'POST', body: JSON.stringify({ persona_id: pid }) });
        DD.toast('✓ Avisos activados — te mandamos una prueba', true);
        const b = document.getElementById('dd-banner-avisos'); if (b) b.remove();
      } catch (e) { DD.toast('No se pudo: ' + e.message, false); }
    },
    async _bannerAvisos() {
      const esHoy = location.pathname === '/' || location.pathname.endsWith('/index.html');
      if (!esHoy || !DD.persona()) return;
      if (await DD.pushActivo()) return;
      if (document.getElementById('dd-banner-avisos')) return;
      const main = document.querySelector('main'); if (!main) return;
      const b = document.createElement('div');
      b.id = 'dd-banner-avisos'; b.className = 'dd-banner-avisos';
      b.innerHTML = `<span>🔔 Activa los avisos en este celular para no perderte reuniones, hábitos ni tu plan del día.</span>
        <button id="dd-banner-btn">Activar avisos</button>
        <button id="dd-banner-x" aria-label="Ahora no">✕</button>`;
      main.insertBefore(b, main.firstChild);
      b.querySelector('#dd-banner-btn').addEventListener('click', () => DD.activarPushActual());
      b.querySelector('#dd-banner-x').addEventListener('click', () => b.remove());
    },

    /* ── Cambiar contraseña de la persona actual ── */
    cambiarClave() {
      const p = DD.persona();
      if (!p) { DD.abrirSelector(true); return; }
      const ov = document.createElement('div');
      ov.className = 'dd-persona-overlay visible'; ov.id = 'dd-clave-overlay';
      ov.innerHTML = `
        <div class="dd-persona-caja" role="dialog" aria-modal="true" style="max-width:380px;text-align:left;">
          <button class="dd-persona-cerrar" id="dd-clave-x" aria-label="Cerrar">✕</button>
          <h2 class="dd-persona-titulo" style="font-size:24px;text-align:center;">Cambiar contraseña</h2>
          <p class="dd-persona-sub" style="text-align:center;">De ${p.nombre}</p>
          <label class="dd-clave-lbl">Contraseña actual</label>
          <input type="password" id="dd-clave-actual" class="dd-clave-inp" autocomplete="current-password">
          <label class="dd-clave-lbl">Nueva contraseña</label>
          <input type="password" id="dd-clave-nueva" class="dd-clave-inp" autocomplete="new-password">
          <label class="dd-clave-lbl">Repite la nueva</label>
          <input type="password" id="dd-clave-rep" class="dd-clave-inp" autocomplete="new-password">
          <button id="dd-clave-guardar" class="dd-clave-btn">Guardar</button>
          <div id="dd-clave-msg" class="dd-clave-msg"></div>
        </div>`;
      document.body.appendChild(ov);
      const cerrar = () => ov.remove();
      ov.querySelector('#dd-clave-x').addEventListener('click', cerrar);
      ov.addEventListener('click', e => { if (e.target === ov) cerrar(); });
      const msg = (t, ok) => { const m = ov.querySelector('#dd-clave-msg'); m.textContent = t; m.className = 'dd-clave-msg ' + (ok ? 'ok' : 'err'); };
      ov.querySelector('#dd-clave-guardar').addEventListener('click', async () => {
        const actual = ov.querySelector('#dd-clave-actual').value;
        const nueva = ov.querySelector('#dd-clave-nueva').value;
        const rep = ov.querySelector('#dd-clave-rep').value;
        if (nueva.length < 4) { msg('La nueva debe tener al menos 4 caracteres'); return; }
        if (nueva !== rep) { msg('Las contraseñas no coinciden'); return; }
        try {
          await DD.fetch('/auth/cambiar', { method: 'POST', body: JSON.stringify({ persona_id: p.id, actual, nueva }) });
          msg('✓ Contraseña actualizada', true);
          setTimeout(cerrar, 1200);
        } catch (e) { msg('La contraseña actual no es correcta'); }
      });
      setTimeout(() => ov.querySelector('#dd-clave-actual')?.focus(), 80);
    },

    _cerrarSelector() {
      const ov = document.getElementById('dd-persona-overlay');
      if (ov) { ov.classList.remove('visible'); setTimeout(() => ov.remove(), 220); }
    },

    /* ── Chip en el sidebar ── */
    _pintarChip() {
      const nav = document.querySelector('.sidebar .nav-section');
      if (!nav) return;
      let chip = document.getElementById('dd-chip-persona');
      const p = DD.persona();
      const contenido = p
        ? `<span class="dd-chip-avatar" style="--pc:${p.color}">${p.emoji || DD.iniciales(p)}</span>
           <span class="dd-chip-textos"><span class="dd-chip-quien">${p.nombre}</span><span class="dd-chip-cambiar">cambiar</span></span>`
        : `<span class="dd-chip-avatar" style="--pc:#7A746B">?</span>
           <span class="dd-chip-textos"><span class="dd-chip-quien">¿Quién eres?</span><span class="dd-chip-cambiar">elegir</span></span>`;
      if (!chip) {
        chip = document.createElement('button');
        chip.id = 'dd-chip-persona';
        chip.className = 'dd-chip-persona';
        chip.title = 'Cambiar de persona';
        chip.addEventListener('click', () => DD.abrirSelector(true));
        nav.appendChild(chip);
      }
      chip.innerHTML = contenido;
    },
  };

  /* ── estilos del runtime ── */
  const css = document.createElement('style');
  css.textContent = `
  .dd-persona-overlay{position:fixed;inset:0;z-index:9000;display:flex;align-items:center;justify-content:center;
    background:color-mix(in srgb, #241A38 62%, transparent);backdrop-filter:blur(8px);
    opacity:0;transition:opacity .22s ease;padding:20px;}
  .dd-persona-overlay.visible{opacity:1;}
  .dd-persona-caja{position:relative;background:#FBFAF6;border:1px solid #E8E4DA;border-radius:20px;
    padding:40px 36px 30px;max-width:520px;width:100%;text-align:center;
    box-shadow:0 24px 70px rgba(15,23,42,.35);transform:translateY(8px);transition:transform .22s ease;}
  .dd-persona-overlay.visible .dd-persona-caja{transform:none;}
  .dd-persona-marca{font-family:"Fraunces","Times New Roman",serif;font-style:italic;font-size:20px;color:#7A746B;}
  .dd-persona-titulo{font-family:"Fraunces","Times New Roman",serif;font-weight:500;font-size:34px;
    margin:10px 0 6px;color:#0E0D0B;letter-spacing:-.02em;}
  .dd-persona-sub{font-size:13.5px;color:#7A746B;margin:0 0 26px;}
  .dd-persona-cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:14px;}
  .dd-persona-card{display:flex;flex-direction:column;align-items:center;gap:10px;padding:22px 14px 16px;
    background:#FFFFFF;border:1.5px solid #E8E4DA;border-radius:16px;cursor:pointer;font-family:inherit;
    transition:transform .15s ease, border-color .15s ease, box-shadow .15s ease;}
  .dd-persona-card:hover{transform:translateY(-3px);border-color:var(--pc);box-shadow:0 10px 26px rgba(15,23,42,.10);}
  .dd-persona-card:focus-visible{outline:2px solid var(--pc);outline-offset:2px;}
  .dd-persona-avatar{width:58px;height:58px;border-radius:50%;display:flex;align-items:center;justify-content:center;
    font-size:24px;font-weight:600;color:#fff;background:var(--pc);
    box-shadow:inset 0 -8px 14px rgba(0,0,0,.12);}
  .dd-persona-nombre{font-size:15.5px;font-weight:600;color:#0E0D0B;}
  .dd-persona-hola{font-size:11.5px;color:var(--pc);font-weight:600;letter-spacing:.02em;}
  .dd-persona-acciones{margin-top:20px;display:flex;gap:8px;justify-content:center;flex-wrap:wrap;}
  .dd-persona-editar{background:none;border:none;color:#A8A29A;font-size:12.5px;cursor:pointer;
    font-family:inherit;padding:8px 12px;border-radius:8px;}
  .dd-persona-editar:hover{color:#3A3733;background:#F0ECE2;}
  .dd-persona-logout{background:#F4E5E3;border:none;color:#A8392F;font-size:12.5px;font-weight:600;cursor:pointer;
    font-family:inherit;padding:8px 14px;border-radius:8px;}
  .dd-persona-logout:hover{background:#EBD3D0;}
  .dd-persona-cerrar{position:absolute;top:14px;right:14px;background:none;border:none;color:#A8A29A;
    font-size:15px;cursor:pointer;padding:6px 9px;border-radius:8px;}
  .dd-persona-cerrar:hover{background:#F0ECE2;color:#3A3733;}
  .dd-persona-card.editando{cursor:default;}
  .dd-persona-cards.editando-lista{grid-template-columns:1fr;gap:12px;}
  .dd-persona-fila{border:1.5px solid #E8E4DA;border-left:3px solid var(--pc);border-radius:12px;
    padding:12px 14px;display:flex;flex-direction:column;gap:9px;text-align:left;background:#fff;}
  .dd-fila-top{display:flex;align-items:center;gap:10px;}
  .dd-fila-tg{display:flex;flex-direction:column;gap:3px;font-size:11px;color:#7A746B;text-transform:none;letter-spacing:0;}
  .dd-fila-tg small{color:#A8A29A;}
  .dd-persona-input{flex:1;font-family:inherit;font-size:14.5px;font-weight:600;
    border:1px solid #E8E4DA;border-radius:8px;padding:8px 10px;background:#FBFAF6;color:#0E0D0B;}
  .dd-persona-input:focus,.dd-persona-tg input:focus{outline:none;border-color:var(--pc);}
  .dd-persona-tg input{font-family:inherit;font-size:13px;border:1px solid #E8E4DA;border-radius:8px;padding:7px 10px;background:#FBFAF6;color:#0E0D0B;}
  .dd-persona-color{width:44px;height:36px;border:1px solid #E8E4DA;border-radius:8px;background:none;cursor:pointer;padding:2px;flex-shrink:0;}
  .dd-btn-push{font-family:inherit;font-size:12.5px;font-weight:600;cursor:pointer;
    border:1px solid var(--pc);color:var(--pc);background:color-mix(in srgb,var(--pc) 8%,#fff);
    border-radius:9px;padding:9px 12px;transition:background .15s;}
  .dd-btn-push:hover{background:color-mix(in srgb,var(--pc) 16%,#fff);}
  .dd-push-estado{font-size:11.5px;color:#7A746B;min-height:14px;}
  .dd-push-estado.ok{color:#5C8A6F;font-weight:600;}
  .dd-push-estado.err{color:#A8392F;}
  .dd-salir{margin-top:6px;background:none;border:none;color:#A8392F;font-family:inherit;font-size:12.5px;font-weight:600;cursor:pointer;padding:8px;border-radius:8px;}
  .dd-salir:hover{background:#F4E5E3;}

  .dd-chip-persona{display:flex;align-items:center;gap:10px;width:100%;margin-top:10px;padding:9px 10px;
    background:rgba(255,255,255,.06);border:1px solid rgba(255,255,255,.12);border-radius:10px;cursor:pointer;
    font-family:inherit;text-align:left;transition:background .15s ease;}
  .dd-chip-persona:hover{background:rgba(255,255,255,.12);}
  .dd-chip-avatar{width:30px;height:30px;border-radius:50%;flex-shrink:0;display:flex;align-items:center;justify-content:center;
    font-size:13px;font-weight:700;color:#fff;background:var(--pc);}
  .dd-chip-textos{display:flex;flex-direction:column;line-height:1.25;min-width:0;}
  .dd-chip-quien{font-size:12.5px;font-weight:600;color:#E2E8F0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
  .dd-chip-cambiar{font-size:10px;color:#94A3B8;letter-spacing:.06em;text-transform:uppercase;}
  @media (max-width:920px){ .dd-chip-persona{width:auto;margin-top:0;} .dd-chip-textos .dd-chip-cambiar{display:none;} }
  @media (prefers-reduced-motion: reduce){
    .dd-persona-overlay,.dd-persona-caja,.dd-persona-card{transition:none;}
  }
  .dd-cambiar-clave{background:none;border:none;color:#7A746B;font-family:inherit;font-size:12.5px;font-weight:600;cursor:pointer;padding:8px;border-radius:8px;}
  .dd-cambiar-clave:hover{background:#F0ECE2;color:#3A3733;}
  .dd-toast{position:fixed;bottom:26px;left:50%;transform:translateX(-50%) translateY(20px);background:#241A38;color:#fff;
    border-radius:12px;padding:11px 20px;font-size:13px;font-weight:500;opacity:0;pointer-events:none;transition:all .25s;z-index:9999;box-shadow:0 10px 30px rgba(15,10,25,.35);max-width:90vw;text-align:center;}
  .dd-toast.visible{opacity:1;transform:translateX(-50%);}
  .dd-toast.ok{background:#2E7D32;} .dd-toast.err{background:#A8392F;}
  .dd-banner-avisos{display:flex;align-items:center;gap:12px;flex-wrap:wrap;background:linear-gradient(135deg,#FCE7F3,#F3E8FF);
    border:1px solid #F9A8D4;border-radius:14px;padding:14px 16px;margin-bottom:20px;font-size:13.5px;color:#3A3733;}
  .dd-banner-avisos span{flex:1;min-width:180px;}
  .dd-banner-avisos #dd-banner-btn{background:linear-gradient(135deg,#EC4899,#9B5DE5);color:#fff;border:none;border-radius:10px;
    padding:9px 16px;font-family:inherit;font-size:13px;font-weight:600;cursor:pointer;white-space:nowrap;}
  .dd-banner-avisos #dd-banner-x{background:none;border:none;color:#A8A29A;font-size:15px;cursor:pointer;padding:4px 8px;border-radius:6px;}
  .dd-banner-avisos #dd-banner-x:hover{background:rgba(0,0,0,.06);color:#3A3733;}
  .dd-clave-lbl{display:block;font-size:11px;letter-spacing:.06em;text-transform:uppercase;font-weight:700;color:#7A746B;margin:12px 0 5px;}
  .dd-clave-inp{width:100%;font-family:inherit;font-size:15px;border:1.5px solid #E8E4DA;border-radius:10px;padding:11px 13px;background:#fff;color:#0E0D0B;}
  .dd-clave-inp:focus{outline:none;border-color:#EC4899;box-shadow:0 0 0 3px rgba(236,72,153,.15);}
  .dd-clave-btn{width:100%;margin-top:16px;border:none;border-radius:11px;padding:12px;font-family:inherit;font-size:15px;font-weight:600;
    color:#fff;cursor:pointer;background:linear-gradient(135deg,#EC4899,#9B5DE5);box-shadow:0 6px 18px rgba(155,93,229,.3);}
  .dd-clave-msg{font-size:12.5px;margin-top:10px;min-height:16px;text-align:center;}
  .dd-clave-msg.err{color:#C0392B;} .dd-clave-msg.ok{color:#2E7D32;}`;
  document.head.appendChild(css);

  /* ── PWA: manifest + service worker ── */
  if (!document.querySelector('link[rel="manifest"]')) {
    const l = document.createElement('link');
    l.rel = 'manifest'; l.href = '/tablero/manifest.webmanifest';
    document.head.appendChild(l);
  }
  if (!document.querySelector('meta[name="theme-color"]')) {
    const m = document.createElement('meta');
    m.name = 'theme-color'; m.content = '#241A38';
    document.head.appendChild(m);
  }
  if (!document.querySelector('link[rel="apple-touch-icon"]')) {
    const a = document.createElement('link');
    a.rel = 'apple-touch-icon'; a.href = '/tablero/iconos/apple-touch-icon.png';
    document.head.appendChild(a);
  }
  if ('serviceWorker' in navigator) {
    window.addEventListener('load', () => {
      navigator.serviceWorker.register('/tablero/sw.js').catch(e => console.warn('SW:', e.message));
    });
  }

  /* ── arranque ── */
  window.DD = DD;
  document.addEventListener('DOMContentLoaded', async () => {
    await DD.cargarPersonas();
    DD._pintarChip();
    DD._aplicarRol();
    if (!DD.persona() && DD.personas.length) DD.abrirSelector();
    else DD._bannerAvisos();
  });
  document.addEventListener('dd:persona', () => { DD._aplicarRol(); });
})();

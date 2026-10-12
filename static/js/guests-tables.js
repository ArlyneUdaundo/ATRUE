/* ============================================================
   ATRUE Guests & Tables selector (restaurant module)
   Floating white panel with Guests + Tables steppers, a summary
   shown in the field, and Done / × / outside / Escape behaviors.

   Markup contract (any page, any container):
     <div class="gd-field">
       <input type="text" class="gd-toggle" readonly aria-expanded="false">
       <div class="gd-panel" data-gd-panel>
         <div class="gd-head"><span class="gd-title">…</span>
           <button type="button" data-gd-close …></button></div>
         <div class="gd-row" data-gd-row>
           <span class="gd-label"><b>Guests</b><span>Number of guests</span></span>
           <span class="gd-step">
             <button type="button" data-gd-minus data-min="1">…</button>
             <span class="gd-num">2</span>
             <input type="hidden" name="guests" value="2" data-min="1" data-max="30">
             <button type="button" data-gd-plus data-max="30">…</button>
           </span>
         </div>
         … one .gd-row per count …
         <button type="button" class="gd-done" data-gd-done>Done</button>
       </div>
     </div>
   ============================================================ */
(function () {
  'use strict';

  var qs = function (sel, root) { return (root || document).querySelector(sel); };
  var qsa = function (sel, root) {
    return Array.prototype.slice.call((root || document).querySelectorAll(sel));
  };
  var SINGULAR = {
    'Guests': 'Guest',
    'Tables': 'Table',
    'Adults': 'Adult',
    'Children': 'Child',
    'Rooms': 'Room',
    'Units': 'Unit',
    'Tourists': 'Tourist',
    'Participants': 'Participant'
  };

  function noun(n, single, plural) {
    return n + ' ' + (n === 1 ? single : plural);
  }

  qsa('.gd-field').forEach(function (field) {
    if (field.getAttribute('data-gd-ready') === '1') return;
    field.setAttribute('data-gd-ready', '1');

    var panel = qs('[data-gd-panel]', field);
    var toggle = qs('.gd-toggle', field);
    if (!panel || !toggle) return;

    var rows = qsa('[data-gd-row]', panel);

    function inputOf(row) { return qs('input', row); }
    function numOf(row) { return qs('.gd-num', row); }
    function valueOf(row) {
      var input = inputOf(row);
      return input ? (parseInt(input.value, 10) || 0) : 0;
    }

    function syncRow(row) {
      var input = inputOf(row);
      var num = numOf(row);
      if (!input || !num) return;
      var v = parseInt(input.value, 10) || 0;
      num.textContent = String(v);
      var min = parseInt(input.getAttribute('data-min') || '0', 10);
      var maxRaw = input.getAttribute('data-max');
      var minus = qs('[data-gd-minus]', row);
      var plus = qs('[data-gd-plus]', row);
      if (minus) minus.disabled = v <= min;
      if (plus && maxRaw != null) plus.disabled = v >= parseInt(maxRaw, 10);
    }

    function syncAll() { rows.forEach(syncRow); }

    function snapshot() {
      return rows.map(function (row) { return valueOf(row); });
    }

    function restore(list) {
      rows.forEach(function (row, i) {
        var input = inputOf(row);
        if (input && list[i] != null) input.value = list[i];
      });
      syncAll();
    }

    function summaryLabel(row) {
      var label = qs('.gd-label b', row);
      return label ? label.textContent.trim() : 'Guests';
    }

    function summaryText() {
      return rows.map(function (row) {
        var n = valueOf(row);
        var skip = row.getAttribute('data-gd-skipzero') != null && n === 0;
        if (skip) return null;
        var word = summaryLabel(row);
        return noun(n, SINGULAR[word] || word, word);
      }).filter(Boolean).join(' · ');
    }

    var saved = null;

    function isOpen() { return panel.classList.contains('open'); }

    function setAria(open) {
      if (toggle) toggle.setAttribute('aria-expanded', open ? 'true' : 'false');
    }

    function openPanel() {
      saved = snapshot();
      panel.classList.add('open');
      setAria(true);
    }

    function closePanel(discard) {
      if (discard && saved) restore(saved);
      saved = null;
      panel.classList.remove('open');
      setAria(false);
    }

    function commitPanel() {
      if (toggle) toggle.value = summaryText();
      saved = null;
      panel.classList.remove('open');
      setAria(false);
    }

    function togglePanel() {
      if (isOpen()) closePanel(true);
      else openPanel();
    }

    function bump(btn, delta) {
      var row = btn.closest('[data-gd-row]');
      if (!row) return;
      var input = inputOf(row);
      if (!input) return;
      var min = parseInt(input.getAttribute('data-min') || '0', 10);
      var maxRaw = input.getAttribute('data-max');
      var v = (parseInt(input.value, 10) || min) + delta;
      if (v < min) v = min;
      if (maxRaw != null && v > parseInt(maxRaw, 10)) v = parseInt(maxRaw, 10);
      input.value = String(v);
      syncRow(row);
    }

    toggle.addEventListener('click', function (e) {
      e.preventDefault();
      togglePanel();
    });

    panel.addEventListener('click', function (e) {
      if (e.target.closest('[data-gd-close]')) { closePanel(true); return; }
      if (e.target.closest('[data-gd-done]')) { commitPanel(); return; }
      var minus = e.target.closest('[data-gd-minus]');
      if (minus) { bump(minus, -1); return; }
      var plus = e.target.closest('[data-gd-plus]');
      if (plus) { bump(plus, 1); return; }
    });

    document.addEventListener('click', function (e) {
      if (!isOpen()) return;
      if (field.contains(e.target)) return;
      closePanel(true);
    });

    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape' && isOpen()) closePanel(true);
    });
  });
})();
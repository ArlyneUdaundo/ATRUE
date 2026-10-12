/* ============================================================
   ATRUE booking / search pages — interactions
   Vanilla JS, no dependencies.
   ============================================================ */
(function () {
  'use strict';

  var doc = document;

  /* ---- helpers ------------------------------------------------- */
  function qs(sel, root) { return (root || doc).querySelector(sel); }
  function qsa(sel, root) { return Array.prototype.slice.call((root || doc).querySelectorAll(sel)); }
  function pad(n) { return (n < 10 ? '0' : '') + n; }
  function fmtDate(d) {
    return d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate());
  }

  /* ---- guest selector popup ------------------------------------ */
  var guestsField = qs('.bk-guests-field');
  if (guestsField) {
    var pop = qs('.bk-gpop', guestsField);
    var toggle = qs('.bk-guests-toggle', guestsField);

    function syncGuestNums() {
      qsa('.bk-grow', guestsField).forEach(function (row) {
        var input = qs('input', row);
        var num = qs('.bk-num', row);
        var minus = qs('[data-minus]', row);
        if (input && num) {
          num.textContent = input.value;
          if (minus) minus.disabled = parseInt(input.value, 10) <= parseInt(minus.getAttribute('data-min'), 10);
        }
      });
    }

    function setVal(input, delta) {
      var min = parseInt(input.getAttribute('data-min'), 10);
      var maxAttr = input.getAttribute('data-max');
      var max = maxAttr === null ? Number.POSITIVE_INFINITY : parseInt(maxAttr, 10);
      var next = Math.min(max, Math.max(min, parseInt(input.value, 10) + delta));
      input.value = next;
      syncGuestNums();
      var summary = qs('.bk-guests-summary', guestsField);
      if (summary) {
        var parts = [];
        parts.push(next || (qsa('.bk-grow input', guestsField).length ? String(qsa('.bk-grow input', guestsField)[0].value || 0) : ''));
        qsa('.bk-grow input', guestsField).forEach(function (inp, i) {
          if (i === 0) return;
          var v = parseInt(inp.value, 10);
          if (v > 0) parts.push(v);
        });
        summary.textContent = parts.join(' · ');
      }
    }

    if (toggle && pop) {
      qsa('button[data-plus], button[data-minus]', guestsField).forEach(function (btn) {
        btn.addEventListener('click', function (e) {
          e.preventDefault();
          var row = btn.closest('.bk-grow');
          if (!row) return;
          var input = qs('input', row) || qs('.bk-gstepper-val', row);
          if (!input) return;
          var delta = btn.hasAttribute('data-plus') ? 1 : -1;
          setVal(input, delta);
        });
      });

      toggle.addEventListener('click', function (e) {
        e.preventDefault();
        e.stopPropagation();
        pop.classList.toggle('open');
      });

      doc.addEventListener('click', function (e) {
        if (!pop.contains(e.target) && !toggle.contains(e.target)) pop.classList.remove('open');
      });

      doc.addEventListener('keydown', function (e) {
        if (e.key === 'Escape') pop.classList.remove('open');
      });

      /* seed adults default so the summary reads correctly */
      var first = qs('.bk-grow input', guestsField);
      if (first && first.value === '') first.value = '2';
      syncGuestNums();
    }
  }

  /* ---- default dates ------------------------------------------- */
  var checkIn = qs('[name="check_in"]');
  var checkOut = qs('[name="check_out"]');
  var today = new Date();
  if (checkIn && !checkIn.value) checkIn.value = fmtDate(today);
  if (checkOut && !checkOut.value) {
    var tmrw = new Date();
    tmrw.setDate(tmrw.getDate() + 1);
    checkOut.value = fmtDate(tmrw);
  }
  function enforceDates() {
    if (checkIn && checkOut && checkIn.value && checkOut.value && checkIn.value >= checkOut.value) {
      var d = new Date(checkIn.value);
      d.setDate(d.getDate() + 1);
      checkOut.value = fmtDate(d);
    }
  }
  if (checkIn && checkIn.min) checkIn.min = fmtDate(today);
  if (checkOut && checkOut.min) checkOut.min = fmtDate(today);
  if (checkIn) checkIn.addEventListener('change', enforceDates);
  if (checkOut) checkOut.addEventListener('change', enforceDates);

  /* ---- live filtering (no page reload) -------------------------- */
  // Every filter control already lives inside the one listing form and the
  // server already filters from request.GET, so a filter click just asks the
  // SAME url for the results region and swaps that region in. The filtering
  // itself stays on the server: no client-side copy of it exists.
  var results = qs('[data-results]');
  var liveSeq = 0;
  var priceTimer = null;
  var searchForm = qs('.bk-search-form');

  function formQuery() {
    if (!searchForm) return '';
    var pairs = [];
    new FormData(searchForm).forEach(function (value, key) {
      if (value == null) return;
      pairs.push(encodeURIComponent(key) + '=' + encodeURIComponent(value));
    });
    return pairs.join('&');
  }

  function liveUrlFromQuery(query) {
    return window.location.pathname + '?_live=1' + (query ? '&' + query : '');
  }

  function setFilterBadges(count) {
    var clear = qs('.bk-sidebar-h a');
    if (clear) {
      // keep the existing "Clear" link and its label, only refresh the count
      clear.innerHTML = 'Clear' + (count ? ' (' + count + ')' : '');
    }
    var fabCount = qs('.bk-fab-count');
    var fab = qs('.bk-fab');
    if (fabCount) {
      if (count) {
        fabCount.textContent = count;
      } else if (fabCount.parentNode) {
        fabCount.parentNode.removeChild(fabCount);
      }
    }
    if (fab && count && !fabCount) {
      var badge = doc.createElement('span');
      badge.className = 'bk-fab-count';
      badge.textContent = count;
      fab.appendChild(badge);
    }
  }

  function applyLive(data, addHistoryEntry) {
    if (!results) return;
    results.innerHTML = data.html;
    // option counts follow the current result set so the numbers stay honest
    Object.keys(data.option_counts || {}).forEach(function (param) {
      var counts = data.option_counts[param];
      qsa('.bk-filter input[type="checkbox"][name="' + param + '"]', doc).forEach(function (box) {
        var label = box.closest('.bk-opt');
        var out = label ? qs('.bk-on', label) : null;
        var n = counts[box.value];
        if (out && n !== undefined) out.textContent = n;
      });
    });
    setFilterBadges(data.active_filters);
    bindGalleries(results);
    var q = data.query || '';
    var nextUrl = data.path + (q ? '?' + q : '') + window.location.hash;
    var currentUrl = window.location.pathname + window.location.search + window.location.hash;
    if (addHistoryEntry && nextUrl !== currentUrl) {
      window.history.pushState({ searchFilters: true }, '', nextUrl);
    }
  }

  function liveFetch(url, addHistoryEntry) {
    if (!results) { window.location.href = url; return; }
    var seq = ++liveSeq;
    results.setAttribute('aria-busy', 'true');
    results.style.opacity = '.55';
    fetch(url, { headers: { 'X-Requested-With': 'XMLHttpRequest' }, credentials: 'same-origin' })
      .then(function (r) {
        if (!r.ok) throw new Error('HTTP ' + r.status);
        return r.json();
      })
      .then(function (data) {
        if (seq !== liveSeq) return;   // a newer filter click already won
        applyLive(data, addHistoryEntry !== false);
      })
      .catch(function () {
        if (seq === liveSeq) window.location.href = url.replace('?_live=1', '');  // degrade to a normal load
      })
      .then(function () {
        if (seq !== liveSeq) return;
        results.removeAttribute('aria-busy');
        results.style.opacity = '';
      });
  }

  function liveFromForm() {
    liveFetch(liveUrlFromQuery(formQuery()));
  }

  function liveFromHref(href) {
    if (!href) return;
    // the server already builds these urls with every current filter applied
    var target = new URL(href, window.location.href);
    var pairs = target.searchParams.toString();
    liveFetch(target.pathname + '?_live=1' + (pairs ? '&' + pairs : ''));
  }

  function restoreSearchFormFromUrl() {
    if (!searchForm) return;
    var params = new URLSearchParams(window.location.search);
    qsa('input, select, textarea', searchForm).forEach(function (field) {
      if (!field.name || field.name === 'ctx'
          || field.name === 'csrfmiddlewaretoken'
          || field.type === 'submit' || field.type === 'button') return;
      var values = params.getAll(field.name);
      if (field.type === 'checkbox' || field.type === 'radio') {
        field.checked = values.indexOf(field.value) !== -1;
      } else if (field.multiple) {
        Array.prototype.forEach.call(field.options, function (option) {
          option.selected = values.indexOf(option.value) !== -1;
        });
      } else if (values.length) {
        field.value = values[0];
      } else {
        field.value = '';
      }
    });
  }

  window.addEventListener('popstate', function () {
    if (!searchForm || !results) return;
    restoreSearchFormFromUrl();
    var query = window.location.search.replace(/^\?/, '');
    liveFetch(window.location.pathname + '?_live=1' + (query ? '&' + query : ''), false);
  });

  function priceRangeValid(el) {
    var min = qs('[name="price_min"]', searchForm);
    var max = qs('[name="price_max"]', searchForm);
    if (min && max && min.value !== '' && max.value !== ''
        && parseFloat(min.value) > parseFloat(max.value)) return false;
    return true;
  }

  if (searchForm) {
    qsa('.bk-auto-submit', searchForm).forEach(function (el) {
      el.addEventListener('change', function () {
        var val = el.value;
        if (el.name === 'price_min' || el.name === 'price_max') {
          if (val !== '' && isNaN(parseFloat(val))) return;
          if (!priceRangeValid(el)) return;
        }
        liveFromForm();
      });
      // typing a price filters as you settle, not on every keystroke
      el.addEventListener('input', function () {
        if (el.name !== 'price_min' && el.name !== 'price_max') return;
        if (el.value !== '' && isNaN(parseFloat(el.value))) return;
        if (!priceRangeValid(el)) return;
        if (priceTimer) clearTimeout(priceTimer);
        priceTimer = setTimeout(liveFromForm, 450);
      });
    });

    // Enter in a price box filters immediately instead of submitting the form
    qsa('input.bk-auto-submit', searchForm).forEach(function (el) {
      el.addEventListener('keyup', function (e) {
        if (e.key !== 'Enter') return;
        e.preventDefault();
        if (priceTimer) clearTimeout(priceTimer);
        if (!priceRangeValid(el)) return;
        liveFromForm();
      });
    });
  }

  /* ---- sort (updates in place, no reload) ----------------------- */
  if (results) {
    // delegated, because the sort controls are inside the swapped region
    results.addEventListener('change', function (e) {
      if (!e.target.matches || !e.target.matches('select[name="sort"]')) return;
      var pairs = formQuery().split('&').filter(function (p) {
        return p && p.split('=')[0] !== 'sort';
      });
      pairs.push('sort=' + encodeURIComponent(e.target.value));
      liveFetch(liveUrlFromQuery(pairs.join('&')));
    });
    // sort tabs and the empty-state "Clear all filters" link are real links
    results.addEventListener('click', function (e) {
      var sortLink = e.target.closest ? e.target.closest('.bk-sort') : null;
      if (sortLink) {
        e.preventDefault();
        liveFromHref(sortLink.getAttribute('href'));
        return;
      }
      var clearLink = e.target.closest ? e.target.closest('a[href]') : null;
      if (clearLink && clearLink.closest('.bk-empty')) {
        e.preventDefault();
        clearAllFilters();
      }
    });
  }

  /* ---- clear / reset filters (no reload) ------------------------- */
  function clearAllFilters() {
    if (priceTimer) clearTimeout(priceTimer);
    qsa('.bk-auto-submit', searchForm).forEach(function (el) {
      if (el.type === 'checkbox') el.checked = false;
      else el.value = '';
    });
    // keep the search the user made, drop only the filters
    var pairs = formQuery().split('&').filter(function (p) {
      if (!p) return false;
      var k = decodeURIComponent(p.split('=')[0]);
      return !filterParams[k];
    });
    liveFetch(liveUrlFromQuery(pairs.join('&')));
  }

  // the parameter names that belong to the filter panel, used when clearing so
  // the destination / dates / guests the user picked are preserved
  var filterParams = {};
  qsa('.bk-filter', doc).forEach(function (group) {
    qsa('input', group).forEach(function (el) { if (el.name) filterParams[el.name] = true; });
  });

  var sidebarClear = qs('.bk-sidebar-h a');
  if (sidebarClear) {
    sidebarClear.addEventListener('click', function (e) {
      e.preventDefault();
      clearAllFilters();
    });
  }
  var resetBtn = qs('.bk-reset');
  if (resetBtn) {
    resetBtn.addEventListener('click', function (e) {
      e.preventDefault();
      clearAllFilters();
    });
  }

  /* ---- destination suggestion chips ---------------------------- */
  qsa('.bk-sug').forEach(function (chip) {
    chip.addEventListener('click', function (e) {
      e.preventDefault();
      var form = chip.closest('form') || searchForm;
      var text = chip.getAttribute('data-tip') || chip.textContent.trim();
      var loc = window.ATRUE_LocPicker ? window.ATRUE_LocPicker.resolve(text) : null;
      if (loc) {
        if (window.ATRUE_LocPicker) window.ATRUE_LocPicker.applySuggestion(form, text);
      } else {
        var input = qs('[name="q"]', form);
        if (input) input.value = text;
      }
      if (form) form.submit();
    });
  });

  /* ---- filter group collapse / expand -------------------------- */
  qsa('.bk-filter').forEach(function (group) {
    var head = qs('.bk-filter-h', group);
    if (!head) return;
    head.addEventListener('click', function () {
      group.classList.toggle('closed');
    });
  });

  /* ---- mobile filter drawer ------------------------------------ */
  var sidebar = qs('.bk-sidebar');
  var backdrop = qs('.bk-backdrop');
  var fab = qs('.bk-fab');
  var drawerClose = qs('.bk-drawer-close');

  function openDrawer() {
    if (!sidebar || !backdrop) return;
    sidebar.classList.add('open');
    backdrop.classList.add('show');
    doc.body.style.overflow = 'hidden';
  }
  function closeDrawer() {
    if (!sidebar || !backdrop) return;
    sidebar.classList.remove('open');
    backdrop.classList.remove('show');
    doc.body.style.overflow = '';
  }
  if (fab) fab.addEventListener('click', openDrawer);
  if (backdrop) backdrop.addEventListener('click', closeDrawer);
  if (drawerClose) drawerClose.addEventListener('click', closeDrawer);
  doc.addEventListener('keydown', function (e) {
    if (e.key === 'Escape') {
      closeDrawer();
      closeLightbox();
    }
  });

  /* ---- gallery + lightbox -------------------------------------- */
  var lightbox = qs('.bk-lightbox');
  var lbImg = qs('.bk-lb-img');
  var lbCount = qs('.bk-lb-count');
  var lbPrev = qs('.bk-lb-prev');
  var lbNext = qs('.bk-lb-next');
  var lbClose = qs('.bk-lb-close') || qs('button', lightbox);
  var currentGallery = [];
  var currentIndex = 0;
  var lbOpener = null;

  function openLightbox(gallery, index, opener) {
    if (!lightbox || !lbImg || (gallery || []).length < 1) return;
    currentGallery = gallery;
    currentIndex = index;
    lbOpener = opener || null;
    lightbox.classList.add('open');
    renderLightbox();
    doc.body.style.overflow = 'hidden';
  }
  function closeLightbox() {
    if (!lightbox) return;
    lightbox.classList.remove('open');
    doc.body.style.overflow = '';
    // Hand focus back to the thumbnail that opened the gallery, with
    // preventScroll so the listing does not jump back to the top.
    var last = lbOpener;
    lbOpener = null;
    if (last && last.focus) {
      try { last.focus({ preventScroll: true }); }
      catch (err) { last.focus(); }
    }
  }
  function renderLightbox() {
    if (!lbImg || !lbCount) return;
    lbImg.src = currentGallery[currentIndex];
    lbCount.textContent = (currentIndex + 1) + ' / ' + currentGallery.length;
    if (lbPrev) lbPrev.style.visibility = currentGallery.length > 1 ? 'visible' : 'hidden';
    if (lbNext) lbNext.style.visibility = currentGallery.length > 1 ? 'visible' : 'hidden';
  }
  function stepLightbox(dir) {
    if (!currentGallery.length) return;
    currentIndex = (currentIndex + dir + currentGallery.length) % currentGallery.length;
    renderLightbox();
  }

  if (lightbox && lbImg) {
    if (lbClose) lbClose.addEventListener('click', closeLightbox);
    if (lbPrev) lbPrev.addEventListener('click', function () { stepLightbox(-1); });
    if (lbNext) lbNext.addEventListener('click', function () { stepLightbox(1); });
    lightbox.addEventListener('click', function (e) {
      if (e.target === lightbox) closeLightbox();
    });
    doc.addEventListener('keydown', function (e) {
      if (!lightbox.classList.contains('open')) return;
      if (e.key === 'ArrowLeft') stepLightbox(-1);
      if (e.key === 'ArrowRight') stepLightbox(1);
    });
  }

  // Bound by function because live filtering replaces the card markup; the
  // galleries in the new cards have to be wired up again after each update.
  function bindGalleries(root) {
    qsa('.bk-gallery', root).forEach(function (gal) {
      if (gal.getAttribute('data-gallery-bound') === '1') return;
      var main = qs('.bk-gmain, .bk-cover', gal);
      if (!main || !main.hasAttribute('data-gallery')) return;
      var gallery;
      try { gallery = JSON.parse(main.getAttribute('data-gallery') || '[]'); } catch (e) { return; }
      if (!gallery.length) return;
      gal.setAttribute('data-gallery-bound', '1');
      main.style.cursor = 'zoom-in';
      main.addEventListener('click', function () { openLightbox(gallery, 0, main); });
      qsa('.bk-thumb', gal).forEach(function (th) {
        th.addEventListener('click', function () {
          var idx = th.getAttribute('data-index');
          if (idx !== null) openLightbox(gallery, parseInt(idx, 10), th);
        });
      });
    });
  }
  bindGalleries(doc);
})();
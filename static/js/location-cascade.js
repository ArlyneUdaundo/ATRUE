/* ============================================================
   ATRUE - inline cascading Country -> Region -> Province
   -> Municipality/City -> Barangay dropdowns for establishment /
   booking address forms. All 252 countries are supported.

   Enhances every block marked `[data-loc-cascade]`:

     <div class="loc-cascade" data-loc-cascade
          data-country="country" data-province="province"
          data-municipality="municipality" data-barangay="barangay"
          data-init-country="..." data-init-region="..."
          data-init-province="..." data-init-municipality="..."
          data-init-barangay="..." data-required="1">
       <select data-cascade="country" ...></select>
       <select data-cascade="region" ...></select>
       <select data-cascade="province" ...></select>
       <select data-cascade="municipality" ...></select>
       <select data-cascade="barangay" ...></select>
       <input data-cascade="barangay-text" ...></input>
     </div>

   Region narrows the province list. It only submits where a model actually
   stores a region (the template passes `region_name`); otherwise it carries
   no `name` and needs no column, because a province belongs to exactly one
   region, so the saved province already identifies it.

   Barangay is Philippine only. GeoNames has no barangay level outside the
   Philippines, so for every other country the whole Barangay group is hidden
   and its value cleared, ending the cascade at Municipality/City. Switching
   away from the Philippines therefore cannot leave a stale barangay behind.

   Behaviour matches the booking-platform spec:
     - Barangay is disabled until a Municipality/City is picked.
     - Municipality/City is disabled until a Province is picked.
     - Province is narrowed by the Region/State filter.
     - The dependent lists only contain entries that belong to the
       parent selection, so invalid combinations are impossible.
     - Changing the Country reloads that country's whole tree and resets
       Region / Province / Municipality/City / Barangay.
     - Changing the Region resets Province + Municipality/City + Barangay.
     - Changing the Province resets Municipality/City + Barangay.
     - Changing the Municipality/City resets Barangay.
     - A Philippine Municipality/City with no barangays on file falls back to
       a free-text Barangay field so data entry is never blocked.

   The country select's value is the Country NAME (what the model stores);
   the JS keeps it in sync with the ISO code used to fetch trees. Only the
   platform's own country is inlined (window.ATRUE_LOC_DATA, else
   /locations/api/); every other country is fetched on demand from
   /locations/api/?country=XX, the same pattern location-picker.js uses.

   Barangay lists are not inlined except for municipalities listings already
   use, so municipalities without one fetch theirs from
   /locations/api/barangays/?country=PH&province=..&municipality=.. - or fall
   back to the free-text field.
   ============================================================ */
(function () {
  'use strict';

  var DATA_URL = '/locations/api/';
  var BARANGAY_URL = '/locations/api/barangays/';

  // The inlined tree only carries the platform's own country, so every other
  // country is fetched on demand. ``base`` is that inlined tree (never
  // swapped), ``countryCache`` holds fetched trees, and ``countryLoads`` keeps
  // one in-flight request per country so a repeated click does not re-request.
  var base = null;
  var countryCache = {};
  var countryLoads = {};
  // country|province|municipality -> promise of barangay names.
  var barangayCache = {};

  function homeCountry() {
    return (base && base.country_code) || 'PH';
  }

  function inHomeCountry(code) {
    return !code || code === homeCountry();
  }

  function norm(s) {
    return String(s || '').toLowerCase()
      .replace(/city/gi, ' ')
      .replace(/[^a-z0-9\s]/g, '')
      .replace(/\s+/g, ' ')
      .trim();
  }

  function addOption(sel, value, label) {
    var opt = document.createElement('option');
    opt.value = value;
    opt.textContent = label;
    sel.appendChild(opt);
    return opt;
  }

  function findValue(sel, raw) {
    var key = norm(raw);
    for (var i = 0; i < sel.options.length; i++) {
      if (norm(sel.options[i].value) === key) return sel.options[i].value;
    }
    return null;
  }

  function ensureValueOption(sel, value) {
    if (!value) return null;
    var match = findValue(sel, value);
    if (match) { sel.value = match; return match; }
    // Keep unknown/custom values so editing an existing record never
    // silently drops a previously-saved location.
    addOption(sel, value, value);
    sel.value = value;
    return value;
  }

  function setRequired(el, on) {
    if (!el) return;
    if (on) { el.setAttribute('required', ''); } else { el.removeAttribute('required'); }
  }

  /* ---- data helpers -------------------------------------------- */

  function countries() {
    if (!base) return [];
    var list = (base.countries) || [];
    if (!list.length && base.country) {
      list = [{ name: base.country, code: base.country_code || 'PH' }];
    }
    return list;
  }

  function countryByValue(value) {
    var key = norm(value);
    var list = countries();
    for (var i = 0; i < list.length; i++) {
      if (norm(list[i].name) === key ||
          (list[i].code || '').toLowerCase() === (value || '').toLowerCase()) {
        return list[i];
      }
    }
    return null;
  }

  function ensureBase(cb) {
    if (base) { cb(base); return; }
    if (window.ATRUE_LOC_DATA && window.ATRUE_LOC_DATA.provinces) {
      base = window.ATRUE_LOC_DATA;
      cb(base);
      return;
    }
    fetch(DATA_URL).then(function (r) { return r.json(); }).then(function (j) {
      base = (j && j.provinces)
        ? j
        : { country: 'Philippines', country_code: 'PH', provinces: [], countries: [], aliases: {} };
      cb(base);
    }).catch(function () {
      base = { country: 'Philippines', country_code: 'PH', provinces: [], countries: [], aliases: {} };
      cb(base);
    });
  }

  function loadCountry(code, cb) {
    if (inHomeCountry(code)) { cb(base); return; }
    if (countryCache[code]) { cb(countryCache[code]); return; }
    if (countryLoads[code]) { countryLoads[code].then(cb); return; }
    countryLoads[code] = fetch(DATA_URL + '?country=' + encodeURIComponent(code))
      .then(function (r) {
        if (!r.ok) throw new Error(r.status);
        return r.json();
      })
      .then(function (j) {
        if (!j || !j.provinces) throw new Error('empty');
        countryCache[code] = j;
        return j;
      })
      .catch(function () {
        countryCache[code] = {
          country: code, country_code: code, provinces: [], countries: countries(), aliases: {}
        };
        return countryCache[code];
      });
    countryLoads[code].then(cb);
  }

  function fetchBarangays(countryCode, province, municipality) {
    var key = (countryCode || homeCountry()) + '|' + norm(province) + '|' + norm(municipality);
    if (Object.prototype.hasOwnProperty.call(barangayCache, key)) {
      return barangayCache[key];
    }
    var promise = fetch(BARANGAY_URL +
        '?country=' + encodeURIComponent(countryCode || '') +
        '&province=' + encodeURIComponent(province || '') +
        '&municipality=' + encodeURIComponent(municipality || ''))
      .then(function (r) { return r.ok ? r.json() : Promise.reject(new Error(r.status)); })
      .then(function (j) { return (j && j.barangays) || []; })
      .catch(function () { return []; });
    barangayCache[key] = promise;
    return promise;
  }

  var activeLocationDropdown = null;
  var dropdownSequence = 0;

  function enhanceLocationSelect(select, kind) {
    if (!select || select.dataset.locUiEnhanced) return null;
    select.dataset.locUiEnhanced = '1';
    var fieldNames = {
      country: ['Country', 'fa-globe'],
      region: ['Region / State', 'fa-map'],
      province: ['Province', 'fa-map-marker-alt'],
      municipality: ['Municipality / City', 'fa-city'],
      barangay: ['Barangay', 'fa-home']
    };
    var meta = fieldNames[kind] || ['Location', 'fa-map-marker-alt'];
    var group = select.closest('.form-group');
    var label = group && group.querySelector('label');
    var root = document.createElement('div');
    root.className = 'loc-dropdown';
    var trigger = document.createElement('button');
    trigger.type = 'button';
    trigger.className = 'loc-dropdown__trigger';
    trigger.id = (select.id || ('loc-select-' + (++dropdownSequence))) + '-control';
    trigger.setAttribute('role', 'combobox');
    trigger.setAttribute('aria-haspopup', 'listbox');
    trigger.setAttribute('aria-expanded', 'false');
    var icon = document.createElement('i');
    icon.className = 'fas ' + meta[1] + ' loc-dropdown__icon';
    icon.setAttribute('aria-hidden', 'true');
    var value = document.createElement('span');
    value.className = 'loc-dropdown__value is-placeholder';
    var caret = document.createElement('i');
    caret.className = 'fas fa-chevron-down loc-dropdown__caret';
    caret.setAttribute('aria-hidden', 'true');
    trigger.append(icon, value, caret);

    var panel = document.createElement('div');
    panel.className = 'loc-dropdown__panel';
    panel.hidden = true;
    var searchWrap = document.createElement('div');
    searchWrap.className = 'loc-dropdown__search-wrap';
    var searchIcon = document.createElement('i');
    searchIcon.className = 'fas fa-search loc-dropdown__search-icon';
    searchIcon.setAttribute('aria-hidden', 'true');
    var search = document.createElement('input');
    search.type = 'search';
    search.className = 'loc-dropdown__search';
    search.autocomplete = 'off';
    search.setAttribute('aria-label', 'Search ' + meta[0]);
    search.placeholder = 'Search ' + meta[0].toLowerCase() + '...';
    searchWrap.append(searchIcon, search);
    var options = document.createElement('div');
    options.className = 'loc-dropdown__options';
    options.id = 'loc-options-' + (++dropdownSequence);
    options.setAttribute('role', 'listbox');
    panel.append(searchWrap, options);
    trigger.setAttribute('aria-controls', options.id);

    select.parentNode.insertBefore(root, select);
    root.append(trigger, select);
    document.body.appendChild(panel);
    select.classList.add('loc-dropdown__native');
    select.tabIndex = -1;
    select.setAttribute('aria-hidden', 'true');
    if (label) {
      if (!label.id) label.id = trigger.id + '-label';
      trigger.setAttribute('aria-labelledby', label.id);
      label.htmlFor = trigger.id;
    } else {
      trigger.setAttribute('aria-label', meta[0]);
    }

    function placePanel() {
      var rect = trigger.getBoundingClientRect();
      var maxHeight = Math.min(340, window.innerHeight - 24);
      var roomBelow = window.innerHeight - rect.bottom;
      var openAbove = roomBelow < Math.min(250, maxHeight) && rect.top > roomBelow;
      panel.style.left = Math.max(10, Math.min(rect.left, window.innerWidth - rect.width - 10)) + 'px';
      panel.style.width = rect.width + 'px';
      panel.style.maxHeight = maxHeight + 'px';
      panel.style.top = openAbove
        ? Math.max(10, rect.top - Math.min(panel.offsetHeight || maxHeight, maxHeight) - 6) + 'px'
        : Math.min(window.innerHeight - 10, rect.bottom + 6) + 'px';
    }

    function close() {
      panel.hidden = true;
      root.classList.remove('is-open');
      trigger.setAttribute('aria-expanded', 'false');
      if (activeLocationDropdown === api) activeLocationDropdown = null;
    }

    function renderOptions() {
      var query = search.value.trim().toLocaleLowerCase();
      options.replaceChildren();
      var count = 0;
      Array.prototype.forEach.call(select.options, function (option) {
        var labelText = option.textContent || option.value;
        if (query && labelText.toLocaleLowerCase().indexOf(query) === -1) return;
        var item = document.createElement('button');
        item.type = 'button';
        item.className = 'loc-dropdown__option';
        item.setAttribute('role', 'option');
        item.setAttribute('aria-selected', String(select.selectedIndex >= 0 && select.options[select.selectedIndex] === option));
        item.disabled = !!option.disabled;
        var itemLabel = document.createElement('span');
        itemLabel.className = 'loc-dropdown__option-label';
        itemLabel.textContent = labelText;
        var check = document.createElement('i');
        check.className = 'fas fa-check loc-dropdown__option-check';
        check.setAttribute('aria-hidden', 'true');
        item.append(itemLabel, check);
        item.addEventListener('click', function () {
          select.value = option.value;
          select.dispatchEvent(new Event('change', { bubbles: true }));
          sync();
          close();
          trigger.focus();
        });
        item.addEventListener('keydown', function (event) {
          if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
            event.preventDefault();
            var list = Array.prototype.filter.call(options.querySelectorAll('.loc-dropdown__option:not(:disabled)'), function (entry) { return entry.offsetParent !== null; });
            var at = list.indexOf(item) + (event.key === 'ArrowDown' ? 1 : -1);
            if (list[at]) list[at].focus();
            else search.focus();
          }
          if (event.key === 'Escape') { event.preventDefault(); close(); trigger.focus(); }
        });
        options.appendChild(item);
        count++;
      });
      if (!count) {
        var empty = document.createElement('div');
        empty.className = 'loc-dropdown__empty';
        empty.textContent = 'No matching locations';
        options.appendChild(empty);
      }
    }

    function sync() {
      var selected = select.options[select.selectedIndex];
      value.textContent = selected ? selected.textContent : (select.options[0] ? select.options[0].textContent : 'Select ' + meta[0]);
      value.classList.toggle('is-placeholder', !selected || !selected.value);
      trigger.disabled = select.disabled;
      root.hidden = !!select.hidden;
      if (root.hidden && !panel.hidden) close();
      if (!panel.hidden) renderOptions();
    }

    var api = { close: close };
    trigger.addEventListener('click', function () {
      if (trigger.disabled) return;
      if (!panel.hidden) { close(); return; }
      if (activeLocationDropdown && activeLocationDropdown !== api) activeLocationDropdown.close();
      activeLocationDropdown = api;
      search.value = '';
      renderOptions();
      panel.hidden = false;
      root.classList.add('is-open');
      trigger.setAttribute('aria-expanded', 'true');
      placePanel();
      search.focus();
    });
    search.addEventListener('input', renderOptions);
    search.addEventListener('keydown', function (event) {
      if (event.key === 'Escape') { event.preventDefault(); close(); trigger.focus(); }
      if (event.key === 'ArrowDown') {
        event.preventDefault();
        var first = options.querySelector('.loc-dropdown__option:not(:disabled)');
        if (first) first.focus();
      }
      if (event.key === 'Enter') {
        var firstMatch = options.querySelector('.loc-dropdown__option:not(:disabled)');
        if (firstMatch) { event.preventDefault(); firstMatch.click(); }
      }
    });
    document.addEventListener('click', function (event) {
      if (!root.contains(event.target) && !panel.contains(event.target)) close();
    });
    window.addEventListener('resize', function () { if (!panel.hidden) placePanel(); });
    window.addEventListener('scroll', function () { if (!panel.hidden) placePanel(); }, true);
    select.addEventListener('change', sync);
    select.addEventListener('invalid', function (event) { event.preventDefault(); trigger.focus(); trigger.click(); });
    if (window.MutationObserver) {
      new MutationObserver(sync).observe(select, { childList: true, subtree: true, attributes: true, attributeFilter: ['disabled', 'hidden', 'selected'] });
    }
    sync();
    return api;
  }
  /* ---- per-wrap behaviour ------------------------------------- */

  function build(wrap) {
    var cSel = wrap.querySelector('select[data-cascade="country"]');
    var rSel = wrap.querySelector('select[data-cascade="region"]');
    var pSel = wrap.querySelector('select[data-cascade="province"]');
    var mSel = wrap.querySelector('select[data-cascade="municipality"]');
    var bSel = wrap.querySelector('select[data-cascade="barangay"]');
    var bTxt = wrap.querySelector('input[data-cascade="barangay-text"]');
    var bGroup = wrap.querySelector('[data-cascade-group="barangay"]');
    if (!pSel || !mSel) return;
    enhanceLocationSelect(cSel, 'country');
    enhanceLocationSelect(rSel, 'region');
    enhanceLocationSelect(pSel, 'province');
    enhanceLocationSelect(mSel, 'municipality');
    enhanceLocationSelect(bSel, 'barangay');
    if (wrap.dataset.locCascadeBuilt) return;
    wrap.dataset.locCascadeBuilt = '1';

    var required = wrap.getAttribute('data-required') === '1';
    var init = {
      country: wrap.getAttribute('data-init-country') || '',
      region: wrap.getAttribute('data-init-region') || '',
      province: wrap.getAttribute('data-init-province') || '',
      municipality: wrap.getAttribute('data-init-municipality') || '',
      barangay: wrap.getAttribute('data-init-barangay') || ''
    };
    var begun = false;
    // Bumped on every refresh so a slow response for a previously selected
    // municipality cannot overwrite the current selection.
    var requestToken = 0;

    var tree = null; // the full current tree ({provinces, country_code, ...})
    var code = '';   // its ISO code

    function provinces() { return (tree && tree.provinces) || []; }

    // GeoNames hangs every province off a region (a Philippine region, a US
    // state, a Brazilian state), so the region list is derived from the tree
    // rather than fetched separately.
    function regions() {
      var seen = {}, out = [];
      provinces().forEach(function (p) {
        var r = (p.region || '').trim();
        if (!r) return;
        var key = norm(r);
        if (seen[key]) return;
        seen[key] = 1;
        out.push(r);
      });
      out.sort(function (a, b) { return a.localeCompare(b); });
      return out;
    }

    // The provinces the region filter currently allows.
    function visibleProvinces() {
      var want = rSel ? norm(rSel.value) : '';
      if (!want) return provinces();
      return provinces().filter(function (p) {
        return norm(p.region || '') === want;
      });
    }

    function refreshRegion(applyInit) {
      if (!rSel) return;
      var keep = rSel.value;
      var list = regions();
      rSel.innerHTML = '';
      addOption(rSel, '', 'All Regions');
      list.forEach(function (r) { addOption(rSel, r, r); });
      // Nothing to narrow by (a country with a single region, or none at all).
      rSel.disabled = !list.length;
      var want = applyInit ? init.region : keep;
      if (!want) return;
      for (var i = 0; i < list.length; i++) {
        if (norm(list[i]) === norm(want)) { rSel.value = list[i]; return; }
      }
      // A saved region GeoNames no longer lists must survive an edit, so it
      // stays selectable instead of being silently dropped.
      if (applyInit) {
        addOption(rSel, want, want);
        rSel.value = want;
      }
    }

    function provinceByName(name) {
      if (!name) return null;
      var key = norm(name);
      for (var i = 0; i < provinces().length; i++) {
        if (norm(provinces()[i].name) === key) return provinces()[i];
      }
      return null;
    }

    function muniByName(prov, name) {
      if (!prov || !name) return null;
      var key = norm(name);
      for (var i = 0; i < prov.municipalities.length; i++) {
        if (norm(prov.municipalities[i].name) === key) return prov.municipalities[i];
      }
      return null;
    }

    function setTree(newTree) {
      tree = newTree;
      code = (newTree && newTree.country_code) || homeCountry();
      if (cSel) {
        var label = (newTree && newTree.country) || code || '';
        if (label) {
          ensureValueOption(cSel, label);
          cSel.value = findValue(cSel, label) || label;
        }
      }
    }

    function fillBarangayOptions(brgys, applyInit) {
      if (!brgys.length) {
        // No barangays on file -> free-text Barangay field remains usable.
        bSel.disabled = true;
        bSel.hidden = true;
        bTxt.disabled = false;
        bTxt.hidden = false;
        setRequired(bSel, false);
        setRequired(bTxt, false);
        if (applyInit && init.barangay) bTxt.value = init.barangay;
        return;
      }

      brgys.forEach(function (b) { addOption(bSel, b, b); });
      addOption(bSel, '__other__', 'Other: enter manually');
      bSel.disabled = false;
      bSel.hidden = false;
      bTxt.disabled = true;
      bTxt.hidden = true;
      setRequired(bSel, required);
      setRequired(bTxt, false);

      var want = applyInit ? init.barangay : '';
      if (!want) return;
      var matched = brgys.some(function (b) { return norm(b) === norm(want); });
      if (matched) {
        bSel.value = want;
        return;
      }
      // Saved barangay is not in the pick-list -> go free-text.
      bSel.value = '__other__';
      bSel.disabled = true;
      bSel.hidden = true;
      bTxt.disabled = false;
      bTxt.hidden = false;
      bTxt.value = want;
      setRequired(bSel, false);
      setRequired(bTxt, required);
    }

    // A barangay is a Philippine administrative level. GeoNames carries one only
    // for the Philippines, so for every other country the level is hidden
    // entirely rather than shown as an empty or free-text box, and the cascade
    // ends at Municipality/City.
    function usesBarangays() {
      return String(code || '').toUpperCase() === 'PH';
    }

    function clearBarangay() {
      bSel.innerHTML = '';
      addOption(bSel, '', 'Select Barangay');
      bSel.value = '';
      bTxt.value = '';
    }

    function hideBarangay() {
      if (bGroup) bGroup.hidden = true;
      clearBarangay();
      bSel.disabled = true;
      bSel.hidden = true;
      bTxt.disabled = true;
      bTxt.hidden = true;
      setRequired(bSel, false);
      setRequired(bTxt, false);
    }

    function refreshBarangay(muni, applyInit, provinceLabel) {
      if (!usesBarangays()) { hideBarangay(); return; }
      if (bGroup) bGroup.hidden = false;

      clearBarangay();
      var token = ++requestToken;

      if (!muni) {
        bSel.disabled = true;
        bSel.hidden = false;
        bTxt.disabled = true;
        bTxt.hidden = true;
        setRequired(bSel, false);
        setRequired(bTxt, false);
        return;
      }

      var inlined = muni.barangays || [];
      if (inlined.length) {
        fillBarangayOptions(inlined, applyInit);
        return;
      }

      // Not inlined: ask the server, showing a busy state meanwhile.
      bSel.innerHTML = '';
      addOption(bSel, '', 'Loading barangays...');
      bSel.disabled = true;
      bSel.hidden = false;
      bTxt.disabled = true;
      bTxt.hidden = true;
      setRequired(bSel, false);
      setRequired(bTxt, false);

      fetchBarangays(code, provinceLabel || pSel.value, muni.name).then(function (brgys) {
        if (token !== requestToken) return; // superseded by a newer selection
        bSel.innerHTML = '';
        addOption(bSel, '', brgys.length ? 'Select Barangay' : 'No barangay on file');
        fillBarangayOptions(brgys, applyInit);
      });
    }

    function refreshMunicipality(applyInit) {
      var prov = provinceByName(pSel.value);
      mSel.innerHTML = '';
      addOption(mSel, '', 'Select Municipality/City');
      mSel.value = '';

      if (!tree || !prov) {
        mSel.disabled = true;
        refreshBarangay(null, false);
        return;
      }
      prov.municipalities.forEach(function (m) { addOption(mSel, m.name, m.name); });
      mSel.disabled = false;

      if (applyInit && init.municipality) ensureValueOption(mSel, init.municipality);
      var muni = muniByName(prov, mSel.value);
      refreshBarangay(muni, applyInit && !!mSel.value, pSel.value);
    }

    function refreshProvince(applyInit) {
      pSel.innerHTML = '';
      pSel.disabled = true;

      var list = visibleProvinces();
      if (!list.length) {
        addOption(pSel, '', rSel && rSel.value
          ? 'No province in this region'
          : 'Loading provinces...');
        refreshMunicipality(applyInit);
        return;
      }
      addOption(pSel, '', 'Select Province');
      list.forEach(function (p) { addOption(pSel, p.name, p.name); });
      pSel.disabled = false;
      if (applyInit && init.province) ensureValueOption(pSel, init.province);
      refreshMunicipality(applyInit);
    }

    function populateCountry() {
      if (!cSel) return;
      cSel.disabled = true;
      cSel.innerHTML = '';
      addOption(cSel, '', 'Select Country');
      countries().forEach(function (c) { addOption(cSel, c.name, c.name); });
      cSel.disabled = false;
    }

    function resolveCountry(cb) {
      if (init.country) {
        var match = countryByValue(init.country);
        var name = (match && match.name) || init.country;
        var startCode = (match && match.code) || '';
        if (cSel) ensureValueOption(cSel, name);
        if (startCode && !inHomeCountry(startCode)) {
          loadCountry(startCode, function (t) { setTree(t); cb(); });
          return;
        }
      }
      // No country on file (legacy rows) -> the province pins the tree to the
      // platform's own country unless it belongs to another one.
      if (!tree) setTree(base);
      cb();
    }

    if (cSel) {
      cSel.addEventListener('change', function () {
        var match = countryByValue(cSel.value);
        clearBarangay();
        // The region list belongs to the country we are leaving.
        if (rSel) rSel.value = '';
        if (!match) {
          // Country cleared -> disable the lower steps until one is chosen.
          tree = null;
          code = '';
          pSel.innerHTML = '';
          addOption(pSel, '', 'Select a country first');
          pSel.disabled = true;
          refreshRegion(true);
          refreshMunicipality(false);
          return;
        }
        var nextCode = match.code;
        if (inHomeCountry(nextCode)) {
          setTree(base);
          refreshRegion(true);
          refreshProvince(false);
        } else {
          loadCountry(nextCode, function (t) {
            setTree(t);
            refreshRegion(true);
            refreshProvince(false);
          });
        }
      });
    }

    if (rSel) {
      rSel.addEventListener('change', function () {
        // Narrowing by region re-lists the provinces and, because the chosen
        // province may fall outside the new region, clears the lower steps.
        pSel.value = '';
        mSel.value = '';
        clearBarangay();
        refreshProvince(false);
      });
    }

    pSel.addEventListener('change', function () {
      // Changing the province clears the Municipality/City and Barangay
      // selections and keeps Barangay disabled until a new City is picked.
      mSel.value = '';
      refreshMunicipality(false);
    });

    mSel.addEventListener('change', function () {
      var prov = provinceByName(pSel.value);
      var muni = muniByName(prov, mSel.value);
      refreshBarangay(muni, false, pSel.value);
    });

    bSel.addEventListener('change', function () {
      if (bSel.value === '__other__') {
        bSel.disabled = true;
        bSel.hidden = true;
        bTxt.disabled = false;
        bTxt.hidden = false;
        bTxt.focus();
        setRequired(bSel, false);
        setRequired(bTxt, required);
      }
    });

    function begin() {
      if (begun) return;
      begun = true;
      ensureBase(function () {
        populateCountry();
        resolveCountry(function () {
          refreshRegion(true);
          refreshProvince(true);
        });
      });
    }

    ensureBase(begin);
  }

  // ---- init ----------------------------------------------------

  function init() {
    Array.prototype.forEach.call(document.querySelectorAll('[data-loc-cascade]'), function (w) {
      if (w.dataset.locCascadeInit) return;
      w.dataset.locCascadeInit = '1';
      build(w);
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }

  // Enhance dynamically-added forms (management modals etc.).
  if (window.MutationObserver) {
    var mo = new MutationObserver(function (muts) {
      muts.forEach(function (m) {
        m.addedNodes.forEach(function (n) {
          if (n.nodeType !== 1) return;
          if (n.matches && n.matches('[data-loc-cascade]')) build(n);
          if (n.querySelectorAll) {
            n.querySelectorAll('[data-loc-cascade]').forEach(function (w) { build(w); });
          }
        });
      });
    });
    document.addEventListener('DOMContentLoaded', function () {
      mo.observe(document.body, { childList: true, subtree: true });
    });
  }

  window.atrueLocationCascade = {
    init: init,
    refresh: function (root) {
      Array.prototype.forEach.call(
        (root || document).querySelectorAll('[data-loc-cascade]'),
        function (w) { build(w); }
      );
    }
  };
})();
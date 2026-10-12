/* ============================================================
   ATRUE — reusable hierarchical location picker.
   Country -> Province -> City/Municipality -> Barangay

   Usage (any page, any form):
     <div class="atrue-loc-wrap" data-loc-picker>
       <button type="button" class="atrue-loc-trigger" data-loc-toggle>
         <span class="atrue-loc-value"><i class="fas fa-location-dot"></i>
           <span class="atrue-loc-text">Cagayan, Baggao</span></span>
         <span class="atrue-loc-placeholder">Where are you going?</span>
       </button>
       <input type="hidden" name="loc_province" value="">
       <input type="hidden" name="loc_municipality" value="">
       <input type="hidden" name="loc_barangay" value="">
     </div>

   Exposes window.ATRUE_LocPicker:
     .open(trigger), .close(), .set(province, municipality, barangay)
     .applySuggestion(form, text)  -> resolves text like "Baggao, Cagayan"
                                      and sets the loc fields on the form
   ============================================================ */
(function () {
  'use strict';

  var DATA_URL = '/locations/api/';
  var modal, panel, head, backBtn, closeBtn, crumb, searchInput, listEl;
  var data = null;
  var wraps = [];
  // The inlined tree only carries the platform's own country, so every other
  // country is fetched on demand from /locations/api/?country=XX. ``base`` is
  // that inlined tree (never swapped), ``countryCache`` holds the fetched
  // trees, and ``countryLoads`` keeps one in-flight request per country so a
  // repeated click does not re-request.
  var base = null;
  var countryCache = {};
  var countryLoads = {};
  var searchTimer = null;
  var searchRequest = null;
  function homeCountry() {
    return (base && base.country_code) || 'PH';
  }
  function inHomeCountry() {
    return !state.countryCode || state.countryCode === homeCountry();
  }
  // A barangay is a Philippine administrative level and GeoNames only holds one
  // for the Philippines, so the picker ends at Municipality/City everywhere
  // else instead of offering an empty barangay step.
  function usesBarangays() {
    var code = state.countryCode || (countryByName(state.country) || {}).code || '';
    return String(code).toUpperCase() === 'PH';
  }
  function blankLoc() { return { country: '', countryCode: '', province: '', municipality: '', barangay: '' }; }
  var state = blankLoc();      // pre-open preview
  var committed = blankLoc();

  // Field-name mapping. Defaults to the search Picker's loc_* names; a wrap may
  // override them via data attributes, e.g.
  //   data-loc-province="province" data-loc-municipality="municipality" data-loc-barangay="barangay"
  function countryField(wrap) { return (wrap && wrap.getAttribute('data-loc-country')) || 'loc_country'; }
  function provField(wrap) { return (wrap && wrap.getAttribute('data-loc-province')) || 'loc_province'; }
  function muniField(wrap) { return (wrap && wrap.getAttribute('data-loc-municipality')) || 'loc_municipality'; }
  function brgyField(wrap) { return (wrap && wrap.getAttribute('data-loc-barangay')) || 'loc_barangay'; }
  function fieldIn(wrap, name) { return wrap ? wrap.querySelector('input[name="' + name + '"]') : null; }

  function qs(sel, root) { return (root || document).querySelector(sel); }
  function qsa(sel, root) { return Array.prototype.slice.call((root || document).querySelectorAll(sel)); }

  function norm(s) {
    return String(s || '').toLowerCase()
      .replace(/city/gi, ' ')
      .replace(/[^a-z0-9\s]/g, '')
      .replace(/\s+/g, ' ').trim();
  }

  function esc(s) {
    var d = document.createElement('div');
    d.textContent = s == null ? '' : String(s);
    return d.innerHTML;
  }

  function fmt(country, province, municipality, barangay) {
    return [country, province, municipality, barangay].filter(Boolean).join(', ');
  }

  /* ---- data helpers -------------------------------------------- */
  function ensureData(cb) {
    if (base) { data = base; cb(base); return; }
    if (window.ATRUE_LOC_DATA && window.ATRUE_LOC_DATA.provinces) {
      base = data = window.ATRUE_LOC_DATA;
      cb(base);
      return;
    }
    fetch(DATA_URL).then(function (r) { return r.json(); }).then(function (j) {
      base = data = j;
      cb(base);
    }).catch(function () {
      base = data = { country: 'Philippines', provinces: [], popular: [], aliases: {} };
      cb(base);
    });
  }

  /* ---- on-demand countries ------------------------------------ */
  /* Only the home country is inlined; the pick list of countries, however, is
     complete, so selecting any other country must load its data before its
     province step can render. */

  function showLoading(message) {
    listEl.innerHTML = '<div class="atrue-loc-empty">' + esc(message || 'Loading…') + '</div>';
  }

  function loadCountryProvinces(code, cb) {
    if (!code || code === homeCountry()) { cb(data.provinces || []); return; }
    if (countryCache[code] && countryCache[code].provinces) {
      cb(countryCache[code].provinces);
      return;
    }
    if (countryLoads[code]) {
      countryLoads[code].then(function (p) { cb(p); });
      return;
    }
    countryLoads[code] = fetch(DATA_URL + '?country=' + encodeURIComponent(code))
      .then(function (r) { return r.ok ? r.json() : Promise.reject(new Error(r.status)); })
      .then(function (j) { return (j && j.provinces) || []; })
      .catch(function () { return []; });
    countryLoads[code].then(function (p) {
      countryCache[code] = { provinces: p };
      cb(p);
    });
  }

  function foreignTrees() {
    var trees = [];
    for (var code in countryCache) {
      if (countryCache[code] !== data) trees.push(countryCache[code]);
    }
    return trees;
  }

  /* ---- lazy barangays ------------------------------------------ */
  /* The inlined tree only carries barangays for municipalities that listings
     already use -- inlining all ~41,000 would add roughly a megabyte to every
     page. Anything else is fetched on demand from /locations/api/barangays/. */

  var BARANGAY_URL = '/locations/api/barangays/';
  var barangayCache = {};
  // Bumped per request so a slow response cannot overwrite a newer selection.
  var barangayToken = 0;

  function fetchBarangays(province, municipality, country) {
    var key = norm(province) + '|' + norm(municipality) + '|' + (country || '');
    if (Object.prototype.hasOwnProperty.call(barangayCache, key)) {
      return barangayCache[key];
    }
    var promise = fetch(BARANGAY_URL +
        '?province=' + encodeURIComponent(province || '') +
        '&municipality=' + encodeURIComponent(municipality || '') +
        '&country=' + encodeURIComponent(country || ''))
      .then(function (r) { return r.ok ? r.json() : Promise.reject(new Error(r.status)); })
      .then(function (j) { return (j && j.barangays) || []; })
      .catch(function () { return []; });
    barangayCache[key] = promise;
    return promise;
  }

  function countryList() {
    if (!data) return [];
    if (data.countries && data.countries.length) return data.countries;
    // Defensive: an older payload with no countries array. Derive one from the
    // country_code already repeated on each province.
    var byCode = {};
    (data.provinces || []).forEach(function (p) {
      var code = p.country_code || '';
      if (!code) return;
      if (!byCode[code]) byCode[code] = { code: code, name: p.country || code, count: 0 };
      byCode[code].count++;
    });
    data.countries = Object.keys(byCode).map(function (k) { return byCode[k]; });
    return data.countries;
  }

  function countryByName(name) {
    var key = norm(name);
    var list = countryList();
    for (var i = 0; i < list.length; i++) {
      if (norm(list[i].name) === key || norm(list[i].code) === key) return list[i];
    }
    return null;
  }

  // The country a province belongs to, so the picker can restore the right
  // first step from a saved province alone (listings store no country).
  function countryOfProvince(provinceName) {
    var p = provinceByName(provinceName);
    if (!p) return null;
    if (p.country_code) return { code: p.country_code, name: p.country || p.country_code };
    return null;
  }

  function provincesInCountry() {
    if (!data) return [];
    var code = state.countryCode;
    if (!code && state.country) {
      var named = countryByName(state.country);
      if (named) code = named.code;
    }
    if (!code || code === homeCountry()) return data.provinces || [];
    var tree = countryCache[code];
    return tree ? (tree.provinces || []) : [];
  }

  function provinceByName(name) {
    if (!data || !name) return null;
    var key = norm(name);
    var trees = [data].concat(foreignTrees());
    for (var i = 0; i < trees.length; i++) {
      for (var j = 0; j < trees[i].provinces.length; j++) {
        if (norm(trees[i].provinces[j].name) === key) return trees[i].provinces[j];
      }
    }
    // Aliases are a Philippine editorial concept and make no sense for any
    // other country.
    if (inHomeCountry()) {
      for (var alias in (data.aliases || {})) {
        var t = data.aliases[alias];
        if (norm(alias) === key) {
          for (var k = 0; k < data.provinces.length; k++) {
            if (data.provinces[k].name === t.province) return data.provinces[k];
          }
        }
      }
    }
    return null;
  }

  function muniByName(prov, name) {
    if (!prov || !name) return null;
    var key = norm(name);
    for (var i = 0; i < prov.municipalities.length; i++) {
      var m = prov.municipalities[i];
      if (norm(m.name) === key) return m;
      if ((m.name || '').replace(/\s/g, '') === name.replace(/\s/g, '')) return m;
    }
    return null;
  }

  // Canonical municipality name within a province, or '' when unrecognised.
  // Also resolves a top-level alias ("Siargao" -> Surigao del Norte / Siargao).
  function muniNameOf(prov, name) {
    var m = muniByName(prov, name);
    if (m) return m.name;
    if (!prov || !name) return '';
    var key = norm(name);
    if (!inHomeCountry()) return '';
    for (var alias in (data.aliases || {})) {
      var t = data.aliases[alias];
      if (norm(alias) === key && prov.name === t.province) return t.municipality || '';
    }
    return '';
  }

  /* ---- resolve free text -> structured loc ---------------------- */
  // Build a result from an ordered [province, municipality, barangay] tail.
  function fromOrdered(prov, mun, brgy, country) {
    return {
      country: country ? (country.name || '') : (prov.country || ''),
      country_code: country ? (country.code || '') : (prov.country_code || ''),
      province: prov.name, municipality: mun || '', barangay: brgy || '',
    };
  }

  function resolve(text) {
    if (!data || !text) return null;
    var raw = String(text).trim();

    // Comma-separated. The picker itself writes "Country, Province, City", but
    // these fields are free text too (restaurants) and people usually write the
    // city first ("Baggao, Cagayan"), so both orders are accepted.
    if (raw.indexOf(',') >= 0) {
      var parts = raw.split(',').map(function (s) { return s.trim(); })
        .filter(function (s) { return s.length; });
      if (!parts.length) return null;

      // A country may lead ("Philippines, Cagayan, Baggao") or trail
      // ("Baggao, Cagayan, Philippines").
      var country = null;
      var lead = countryByName(parts[0]);
      if (lead) { country = lead; parts.shift(); }
      else {
        var trail = countryByName(parts[parts.length - 1]);
        if (trail) { country = trail; parts.pop(); }
      }

      if (!parts.length) {
        return { country: country.name, country_code: country.code, province: '', municipality: '', barangay: '' };
      }

      if (parts.length === 1) {
        var one = provinceByName(parts[0]);
        if (one) return fromOrdered(one, '', '', country);
        // fall through to the single-name lookups below
      } else {
        // canonical: province, municipality[, barangay]
        var fwd = provinceByName(parts[0]);
        if (fwd) {
          return fromOrdered(fwd, muniNameOf(fwd, parts[1]), parts[2] || '', country);
        }
        // legacy: municipality, province[, barangay] -- i.e. the tail is
        // reversed, so [barangay, municipality, province]
        var rev = provinceByName(parts[parts.length - 1]);
        if (rev) {
          return fromOrdered(rev, muniNameOf(rev, parts[parts.length - 2]), parts.length > 2 ? parts[0] : '', country);
        }
      }

      if (country) {
        return { country: country.name, country_code: country.code, province: '', municipality: '', barangay: '' };
      }
    }

    // country name or ISO code on its own ("Philippines", "PH")
    var asCountry = countryByName(raw);
    if (asCountry && !provinceByName(raw)) {
      return { country: asCountry.name, country_code: asCountry.code, province: '', municipality: '', barangay: '' };
    }

    // strict province name first ("Cebu" -> the whole province, "Cagayan",
    // "Davao del Sur", "Metro Manila")
    var trees = [data].concat(foreignTrees());
    var key = norm(raw);
    for (var t = 0; t < trees.length; t++) {
      var provinces = trees[t].provinces;
      for (var i = 0; i < provinces.length; i++) {
        if (norm(provinces[i].name) === key) {
          return {
            country: provinces[i].country || '', country_code: provinces[i].country_code || '',
            province: provinces[i].name, municipality: '', barangay: '',
          };
        }
      }
    }

    // municipality name that is unique across all provinces (e.g. "Baggao",
    // "Davao City", "Mactan", "Baguio"); names like "San Juan" that appear in
    // many provinces are ignored to avoid guessing wrong.
    var exact = [];
    for (var t2 = 0; t2 < trees.length; t2++) {
      var known = trees[t2].provinces;
      for (var j = 0; j < known.length; j++) {
        var p = known[j];
        var m = muniByName(p, raw);
        if (m) exact.push({ province: p.name, municipality: m.name, country: p.country || '', country_code: p.country_code || '' });
      }
    }
    if (exact.length === 1) {
      return {
        country: exact[0].country, country_code: exact[0].country_code,
        province: exact[0].province, municipality: exact[0].municipality, barangay: '',
      };
    }

    // aliases ("Boracay" -> Aklan / Malay, "Davao" -> Davao del Sur)
    if (inHomeCountry()) {
      for (var alias in (data.aliases || {})) {
        if (norm(alias) === key) {
          var t = data.aliases[alias];
          var host = provinceByName(t.province);
          return {
            country: host ? (host.country || '') : '', country_code: host ? (host.country_code || '') : '',
            province: t.province, municipality: t.municipality || '', barangay: '',
          };
        }
      }
    }
    return null;
  }

  /* ---- rendering ------------------------------------------------ */
  function buildPanel() {
    if (modal) return;
    modal = document.createElement('div');
    modal.className = 'atrue-loc-modal';
    modal.setAttribute('role', 'dialog');
    modal.setAttribute('aria-modal', 'true');
    modal.innerHTML =
      '<div class="atrue-loc-panel">' +
        '<div class="atrue-loc-head">' +
          '<button type="button" class="atrue-loc-back" aria-label="Back"><i class="fas fa-arrow-left"></i></button>' +
          '<h3>Where to?</h3>' +
          '<button type="button" class="atrue-loc-close" aria-label="Close"><i class="fas fa-times"></i></button>' +
        '</div>' +
        '<div class="atrue-loc-crumb"></div>' +
        '<div class="atrue-loc-search"><i class="fas fa-magnifying-glass"></i>' +
          '<input type="text" placeholder="Search a country, province or city" autocomplete="off">' +
        '</div>' +
        '<div class="atrue-loc-list"></div>' +
      '</div>';
    document.body.appendChild(modal);
    panel = qs('.atrue-loc-panel', modal);
    head = qs('.atrue-loc-head', modal);
    backBtn = qs('.atrue-loc-back', modal);
    closeBtn = qs('.atrue-loc-close', modal);
    crumb = qs('.atrue-loc-crumb', modal);
    searchInput = qs('.atrue-loc-search input', modal);
    listEl = qs('.atrue-loc-list', modal);

    backBtn.addEventListener('click', stepBack);
    closeBtn.addEventListener('click', close);
    modal.addEventListener('click', function (e) {
      if (e.target === modal) close();
    });
    searchInput.addEventListener('input', renderSearch);
    searchInput.addEventListener('keydown', function (e) { e.stopPropagation(); });
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape' && modal.classList.contains('open')) close();
    });
  }

  function clearPreview() {
    state = blankLoc();
    searchInput.value = '';
  }

  function locFromResolved(r) {
    return {
      country: r.country || '', countryCode: r.country_code || '',
      province: r.province || '', municipality: r.municipality || '',
      barangay: r.barangay || '',
    };
  }

  // Fill in whichever parts of the location are missing but derivable, so the
  // picker opens on the right step. Listings store province/municipality/barangay
  // but no country, so a saved province is what restores the country step.
  //
  // Deliberately no fallback to the primary country: a blank selection must show
  // the country list, otherwise the country would be a step the user never sees.
  function ensureCountryConsistent(loc) {
    if (!loc) return loc;
    if (!loc.countryCode && loc.country) {
      var fromName = countryByName(loc.country);
      if (fromName) loc.countryCode = fromName.code;
    }
    if (!loc.countryCode) {
      var fromProvince = loc.province ? countryOfProvince(loc.province) : null;
      if (fromProvince) { loc.countryCode = fromProvince.code; if (!loc.country) loc.country = fromProvince.name; }
    }
    if (!loc.country) {
      var named = loc.countryCode ? countryByName(loc.countryCode) : null;
      if (named) loc.country = named.name;
    }
    return loc;
  }

  function open(trigger) {
    buildPanel();
    var wrap = trigger && trigger.closest('[data-loc-picker]');
    if (wrap && wrap.getAttribute('data-loc-combine')) {
      var c = fieldIn(wrap, wrap.getAttribute('data-loc-combine'));
      var resolved = c && c.value ? resolve(c.value) : null;
      committed = resolved ? locFromResolved(resolved) : blankLoc();
    } else {
      committed = {
        country: wrap ? (fieldIn(wrap, countryField(wrap)) || {}).value || '' : '',
        countryCode: '',
        province: wrap ? (fieldIn(wrap, provField(wrap)) || {}).value || '' : '',
        municipality: wrap ? (fieldIn(wrap, muniField(wrap)) || {}).value || '' : '',
        barangay: wrap ? (fieldIn(wrap, brgyField(wrap)) || {}).value || '' : '',
      };
    }
    ensureCountryConsistent(committed);
    state = {
      country: committed.country, countryCode: committed.countryCode,
      province: committed.province, municipality: committed.municipality,
      barangay: committed.barangay,
    };
    searchInput.value = '';
    modal.classList.add('open');
    document.body.style.overflow = 'hidden';
    renderLevel();
    renderCrumb();
    searchInput.focus();
  }

  function close() {
    if (!modal) return;
    modal.classList.remove('open');
    document.body.style.overflow = '';
  }

  function renderLevel() {
    listEl.innerHTML = '';
    if (!state.country) {
      renderCountriesList();
      return;
    }
    // A foreign country restored from saved fields (or chosen elsewhere) may
    // not have its provinces loaded yet: fetch them before drawing this step.
    var want = state.countryCode || (countryByName(state.country) || {}).code || '';
    if (want && want !== homeCountry() && !countryCache[want]) {
      var pending = want;
      showLoading('Loading ' + state.country + ' provinces…');
      loadCountryProvinces(pending, function () {
        if (state.country && (state.countryCode === pending ||
            (countryByName(state.country) || {}).code === pending)) {
          renderLevel();
        }
      });
      return;
    }
    if (state.province && state.municipality) {
      if (usesBarangays()) {
        renderBarangaysList();
      } else {
        // Municipality/City is the last level outside the Philippines.
        state.barangay = '';
        commit();
      }
    } else if (state.province) {
      renderMunicipalitiesList();
    } else {
      renderProvincesList();
    }
  }

  function countryName() { return state.country || (data && data.country) || ''; }

  function renderCountriesList() {
    listEl.innerHTML = '';
    var list = countryList();
    if (!list.length) { renderProvincesList(); return; }

    list.forEach(function (c) {
      var item = document.createElement('button');
      item.type = 'button';
      item.className = 'atrue-loc-item';
      item.innerHTML =
        '<span class="atrue-loc-item-ico"><i class="fas fa-globe"></i></span>' +
        '<span class="atrue-loc-item-txt">' +
          '<span class="atrue-loc-item-name">' + esc(c.name) + '</span>' +
          '<span class="atrue-loc-item-sub">' +
            // `count` is how many provinces the country owns, not regions.
            (c.count ? c.count + (c.count === 1 ? ' province' : ' provinces') : 'Country') +
          '</span>' +
        '</span>';
      item.addEventListener('click', function () {
        state.country = c.name; state.countryCode = c.code;
        state.province = ''; state.municipality = ''; state.barangay = '';
        var scoped = provincesInCountry();
        if (scoped && scoped.length) { renderLevel(); renderCrumb(); return; }
        // Not loaded yet: fetch this country's provinces, then show its list.
        var chosen = c.code;
        showLoading('Loading ' + c.name + ' provinces…');
        loadCountryProvinces(chosen, function () {
          if (state.countryCode === chosen) { renderLevel(); renderCrumb(); }
        });
      });
      listEl.appendChild(item);
    });
  }

  function muniByNameInState() {
    var p = provinceByName(state.province);
    return p ? muniByName(p, state.municipality) : null;
  }

  function renderProvincesList() {
    listEl.innerHTML = '';
    var scoped = provincesInCountry();
    // "Popular destinations" is a Philippine editorial list; it means nothing
    // for any other country.
    var pop = inHomeCountry() ? (data.popular || []) : [];
    var popIdx = pop.map(norm);

    // Stopping point for the country. Lives here rather than on the country
    // list so it works no matter how many countries are loaded.
    if (state.country) {
      var all = document.createElement('button');
      all.type = 'button';
      all.className = 'atrue-loc-item all';
      all.innerHTML =
        '<span class="atrue-loc-item-ico"><i class="fas fa-globe"></i></span>' +
        '<span class="atrue-loc-item-txt">' +
          '<span class="atrue-loc-item-name">All of ' + esc(state.country) + '</span>' +
          '<span class="atrue-loc-item-sub">Everywhere in the country</span>' +
        '</span>';
      all.addEventListener('click', function () {
        state.province = ''; state.municipality = ''; state.barangay = '';
        commit();
      });
      listEl.appendChild(all);
    }

    function addProvince(p, popular) {
      var item = document.createElement('button');
      item.type = 'button';
      item.className = 'atrue-loc-item';
      item.innerHTML =
        '<span class="atrue-loc-item-ico"><i class="fas ' + (popular ? 'fa-star' : 'fa-map-pin') + '"></i></span>' +
        '<span class="atrue-loc-item-txt">' +
          '<span class="atrue-loc-item-name">' + esc(p.name) + '</span>' +
          '<span class="atrue-loc-item-sub">' + (popular ? 'Popular destination' : (p.region || 'Province')) + '</span>' +
        '</span>';
      item.addEventListener('click', function () {
        state.province = p.name; state.municipality = ''; state.barangay = '';
        // Keep the country in step with the province, in case the province was
        // reached by typing or by a search result.
        if (p.country_code) { state.countryCode = p.country_code; state.country = p.country || state.country; }
        renderLevel(); renderCrumb();
      });
      listEl.appendChild(item);
    }

    if (pop.length) {
      var popList = document.createElement('div');
      popList.innerHTML = '<div class="atrue-loc-empty" style="text-align:left;padding:2px 6px 8px;font-size:12px;color:#7b8698;font-weight:700;letter-spacing:.04em">POPULAR DESTINATIONS</div>';
      listEl.appendChild(popList.firstChild);
    }
    var shown = {};
    for (var i = 0; i < pop.length; i++) {
      var p = provinceByName(pop[i]);
      if (p && inScope(p, scoped) && !shown[norm(p.name)]) { addProvince(p, true); shown[norm(p.name)] = 1; }
    }
    for (var j = 0; j < scoped.length; j++) {
      if (!shown[norm(scoped[j].name)]) addProvince(scoped[j], false);
    }
    if (!scoped.length) {
      var none = document.createElement('div');
      none.className = 'atrue-loc-empty';
      none.textContent = 'No provinces on file for ' + (state.country || homeCountry()) + ' yet.';
      listEl.appendChild(none);
    }
  }

  function inScope(province, scoped) {
    for (var i = 0; i < scoped.length; i++) {
      if (scoped[i] === province) return true;
    }
    return false;
  }

  function renderMunicipalitiesList() {
    listEl.innerHTML = '';
    var p = provinceByName(state.province);
    if (!p) { renderProvincesList(); return; }

    var all = document.createElement('button');
    all.type = 'button';
    all.className = 'atrue-loc-item all';
    all.innerHTML =
      '<span class="atrue-loc-item-ico"><i class="fas fa-map"></i></span>' +
      '<span class="atrue-loc-item-txt">' +
        '<span class="atrue-loc-item-name">All of ' + esc(p.name) + '</span>' +
        '<span class="atrue-loc-item-sub">Every spot across the province</span>' +
      '</span>';
    all.addEventListener('click', function () {
      state.municipality = ''; state.barangay = '';
      commit();
    });
    listEl.appendChild(all);

    p.municipalities.forEach(function (m) {
      var item = document.createElement('button');
      item.type = 'button';
      item.className = 'atrue-loc-item' + (state.municipality === m.name ? ' active' : '');
      item.innerHTML =
        '<span class="atrue-loc-item-ico"><i class="fas fa-location-dot"></i></span>' +
        '<span class="atrue-loc-item-txt">' +
          '<span class="atrue-loc-item-name">' + esc(m.name) + '</span>' +
          '<span class="atrue-loc-item-sub">' + esc(p.name) + '</span>' +
        '</span>';
      item.addEventListener('click', function () {
        state.municipality = m.name; state.barangay = '';
        renderLevel(); renderCrumb();
      });
      listEl.appendChild(item);
    });
  }

  function renderBarangaysList() {
    listEl.innerHTML = '';
    var p = provinceByName(state.province);
    var m = muniByNameInState();
    if (!p || !m) { commit(); return; }

    function addAllOption() {
      var all = document.createElement('button');
      all.type = 'button';
      all.className = 'atrue-loc-item all';
      all.innerHTML =
        '<span class="atrue-loc-item-ico"><i class="fas fa-map"></i></span>' +
        '<span class="atrue-loc-item-txt">' +
          '<span class="atrue-loc-item-name">All of ' + esc(m.name) + '</span>' +
          '<span class="atrue-loc-item-sub">' + esc(p.name) + '</span>' +
        '</span>';
      all.addEventListener('click', function () { state.barangay = ''; commit(); });
      listEl.appendChild(all);
    }

    function addBarangayOptions(brgys) {
      addAllOption();
      brgys.forEach(function (b) {
        var item = document.createElement('button');
        item.type = 'button';
        item.className = 'atrue-loc-item';
        item.innerHTML =
          '<span class="atrue-loc-item-ico"><i class="fas fa-house"></i></span>' +
          '<span class="atrue-loc-item-txt">' +
            '<span class="atrue-loc-item-name">' + esc(b) + '</span>' +
            '<span class="atrue-loc-item-sub">' + esc(m.name) + ', ' + esc(p.name) + '</span>' +
          '</span>';
        item.addEventListener('click', function () { state.barangay = b; commit(); });
        listEl.appendChild(item);
      });
    }

    var inlined = m.barangays || [];
    if (inlined.length) {
      addBarangayOptions(inlined);
      return;
    }

    // Not inlined: fetch the full list for this municipality.
    var token = ++barangayToken;
    var loading = document.createElement('div');
    loading.className = 'atrue-loc-empty';
    loading.textContent = 'Loading barangays…';
    listEl.appendChild(loading);
    addAllOption();

    fetchBarangays(p.name, m.name, p.country_code || state.countryCode || homeCountry()).then(function (brgys) {
      if (token !== barangayToken) return; // a newer selection superseded this
      if (norm(state.province) !== norm(p.name) ||
          norm(state.municipality) !== norm(m.name)) return;
      listEl.innerHTML = '';
      if (!brgys.length) {
        var none = document.createElement('div');
        none.className = 'atrue-loc-empty';
        none.textContent = 'No barangay on file for ' + m.name + ' — use "All of ' + m.name + '".';
        listEl.appendChild(none);
      }
      addBarangayOptions(brgys);
      renderCrumb();
    });
  }

  function renderSearch() {
    var rawQuery = searchInput.value.trim();
    var q = norm(rawQuery);
    if (!q) {
      if (searchRequest) { searchRequest.abort(); searchRequest = null; }
      renderLevel();
      renderCrumb();
      return;
    }
    clearTimeout(searchTimer);
    if (searchRequest) { searchRequest.abort(); searchRequest = null; }
    if (q.length < 2) {
      listEl.innerHTML = '<div class="atrue-loc-empty">Type at least 2 characters to search worldwide.</div>';
      return;
    }

    listEl.innerHTML = '<div class="atrue-loc-empty">Searching worldwide places…</div>';
    searchTimer = setTimeout(function () {
      var xhr = new XMLHttpRequest();
      searchRequest = xhr;
      xhr.open('GET', '/locations/api/search/?q=' + encodeURIComponent(rawQuery), true);
      xhr.onload = function () {
        if (searchRequest !== xhr) return;
        searchRequest = null;
        if (xhr.status !== 200) {
          renderGlobalSearch([], 'Worldwide place suggestions are unavailable. Please try again.');
          return;
        }
        try {
          var results = (JSON.parse(xhr.responseText).results || []).map(function (result) {
            result.countryCode = result.country_code || '';
            return result;
          });
          if (inHomeCountry()) {
            Object.keys(data.aliases || {}).forEach(function (alias) {
              if (norm(alias).indexOf(q) < 0) return;
              var target = data.aliases[alias];
              results.push({
                level: 'city', alias: true, name: alias,
                sub: target.province + ', ' + homeCountry(),
                country: countryName(), country_code: homeCountry(), countryCode: homeCountry(),
                province: target.province, municipality: target.municipality || '',
                barangay: ''
              });
            });
          }
          renderGlobalSearch(results);
        } catch (error) {
          renderGlobalSearch([], 'Worldwide place suggestions could not be read. Please try again.');
        }
      };
      xhr.onerror = function () {
        if (searchRequest !== xhr) return;
        searchRequest = null;
        renderGlobalSearch([], 'Worldwide place suggestions are unavailable. Check your connection and try again.');
      };
      xhr.send();
    }, 160);
    renderCrumb();
  }

  function renderGlobalSearch(results, errorMessage) {
    listEl.innerHTML = '';
    if (!results.length) {
      listEl.innerHTML = '<div class="atrue-loc-empty">' +
        esc(errorMessage || 'No matching worldwide places found.') + '</div>';
      return;
    }
    results.forEach(function (s) {
      var item = document.createElement('button');
      item.type = 'button';
      item.className = 'atrue-loc-item';
      item.innerHTML =
        '<span class="atrue-loc-item-ico"><i class="fas ' + (s.level === 'city' || s.level === 'barangay' ? 'fa-location-dot' : 'fa-map-pin') + '"></i></span>' +
        '<span class="atrue-loc-item-txt">' +
          '<span class="atrue-loc-item-name">' + esc(s.name) + '</span>' +
          '<span class="atrue-loc-item-sub">' + esc(s.sub || s.country || '') + '</span>' +
        '</span>';
      item.addEventListener('click', function () { chooseSearchResult(s); });
      listEl.appendChild(item);
    });
  }

  function chooseSearchResult(s) {
    if (s.level === 'country' || (s.country && !s.province)) {
      // A country was picked: go to its province list, loading the country's
      // provinces on demand when it is not the inlined home country.
      state.country = s.name; state.countryCode = s.countryCode || '';
      state.province = ''; state.municipality = ''; state.barangay = '';
      if (provincesInCountry().length) { renderLevel(); renderCrumb(); return; }
      var chosen = s.countryCode || '';
      showLoading('Loading ' + s.name + ' provinces…');
      loadCountryProvinces(chosen, function (provinces) {
        if (state.countryCode !== chosen) return;
        // A country with no provinces on file commits outright; otherwise show
        // its province step.
        if (provinces.length) { renderLevel(); renderCrumb(); }
        else commit();
      });
      return;
    }
    state.country = s.country || state.country;
    state.countryCode = s.countryCode || state.countryCode;
    if (s.alias) {
      state.province = s.province; state.municipality = s.municipality; state.barangay = '';
      commit();
      return;
    }
    if (s.level === 'barangay' || s.barangay) {
      state.province = s.province;
      state.municipality = s.municipality;
      state.barangay = s.barangay || s.name;
      commit();
      return;
    }
    if (s.municipality) {
      state.province = s.province; state.municipality = s.municipality; state.barangay = '';
      renderLevel(); renderCrumb();
      return;
    }
    state.province = s.province; state.municipality = ''; state.barangay = '';
    renderLevel(); renderCrumb();
  }

  function stepBack() {
    if (searchInput.value) { searchInput.value = ''; renderLevel(); renderCrumb(); return; }
    if (state.barangay) state.barangay = '';
    else if (state.municipality) state.municipality = '';
    else if (state.province) state.province = '';
    else if (state.country) { state.country = ''; state.countryCode = ''; }
    if (!searchInput.value) { renderLevel(); renderCrumb(); }
  }

  function renderCrumb() {
    crumb.innerHTML = '';
    function btn(label, fn) {
      var b = document.createElement('button');
      b.type = 'button';
      b.textContent = label;
      b.addEventListener('click', fn);
      crumb.appendChild(b);
      return b;
    }
    btn(countryName() || 'Philippines', function () {
      state.country = ''; state.countryCode = '';
      state.province = ''; state.municipality = ''; state.barangay = '';
      renderLevel();
    });
    if (state.province) {
      var s = document.createElement('span'); s.className = 'sep'; s.textContent = '>';
      crumb.appendChild(s);
      btn(state.province, function () {
        state.municipality = ''; state.barangay = ''; renderLevel();
      });
    }
    if (state.municipality) {
      var s2 = document.createElement('span'); s2.className = 'sep'; s2.textContent = '>';
      crumb.appendChild(s2);
      btn(state.municipality, function () {
        state.barangay = ''; renderLevel();
      });
    }
    backBtn.disabled = !(state.country || state.province || searchInput.value);
  }

  /* ---- committing a selection ------------------------------------ */
  function setActiveWrap(wrap) {
    keyWrap = wrap;
  }
  var keyWrap = null;

  function commit() {
    // Never carry a barangay out of the Philippines: the level does not exist
    // there, so a stale value must not reach the search filters.
    if (!usesBarangays()) state.barangay = '';
    var wrap = keyWrap || document.activeElement && document.activeElement.closest('[data-loc-picker]');
    if (wrap) {
      applyTo(wrap, state.country, state.countryCode, state.province, state.municipality, state.barangay);
      var form = wrap.closest('form');
      if (form) syncFormPick(form);
    }
    close();
    if (wrap) {
      var form2 = wrap.closest('form');
      if (form2) {
        var change = document.createEvent('Event'); change.initEvent('change', true, true);
        form2.dispatchEvent(change);
      }
    }
  }

  function syncFormPick(form) {
    qsa('[data-loc-picker]', form).forEach(function (wrap) {
      applyTo(wrap, committed.country, committed.countryCode, committed.province, committed.municipality, committed.barangay);
    });
  }

  function applyTo(wrap, country, countryCode, province, municipality, barangay) {
    // Resolve first, so a value that only carries a province (how listings are
    // saved) still displays and stores the country it belongs to.
    var loc = ensureCountryConsistent({
      country: country || '', countryCode: countryCode || '',
      province: province || '', municipality: municipality || '', barangay: barangay || '',
    });
    country = loc.country; countryCode = loc.countryCode;
    province = loc.province; municipality = loc.municipality; barangay = loc.barangay;

    var label = fmt(country, province, municipality, barangay);
    // "combined text" mode: a single free-text field like a restaurant's
    // `location` gets the formatted "Philippines, Baggao, Cagayan" string
    // (data-loc-combine="location")
    var combine = wrap && wrap.getAttribute('data-loc-combine');
    if (combine) {
      var c = fieldIn(wrap, combine);
      if (c) c.value = label;
      committed = { country: country, countryCode: countryCode, province: province, municipality: municipality, barangay: barangay };
      var val0 = qs('.atrue-loc-value', wrap);
      var txt0 = qs('.atrue-loc-text', wrap);
      var ph0 = qs('.atrue-loc-placeholder', wrap);
      if (val0 && txt0) txt0.textContent = label;
      if (wrap) wrap.classList.toggle('has-loc', !!(country || province || municipality || barangay));
      if (ph0) ph0.style.display = (country || province || municipality || barangay) ? 'none' : '';
      return;
    }
    var ctry = fieldIn(wrap, countryField(wrap));
    var p = fieldIn(wrap, provField(wrap));
    var m = fieldIn(wrap, muniField(wrap));
    var b = fieldIn(wrap, brgyField(wrap));
    if (ctry) ctry.value = country;
    if (p) p.value = province;
    if (m) m.value = municipality;
    if (b) b.value = barangay;
    committed = { country: country, countryCode: countryCode, province: province, municipality: municipality, barangay: barangay };
    var val = qs('.atrue-loc-value', wrap);
    var txt = qs('.atrue-loc-text', wrap);
    var ph = qs('.atrue-loc-placeholder', wrap);
    if (val && txt) txt.textContent = label;
    if (wrap) wrap.classList.toggle('has-loc', !!(country || province || municipality || barangay));
    if (ph) ph.style.display = (country || province || municipality || barangay) ? 'none' : '';
  }

  function applyToWrap(wrap) {
    applyTo(wrap,
      (fieldIn(wrap, countryField(wrap)) || {}).value || '', '',
      (fieldIn(wrap, provField(wrap)) || {}).value || '',
      (fieldIn(wrap, muniField(wrap)) || {}).value || '',
      (fieldIn(wrap, brgyField(wrap)) || {}).value || '');
  }

  function clear(wrap) {
    if (!wrap) return;
    committed = blankLoc();
    state = blankLoc();
    applyTo(wrap, '', '', '', '', '');
    var form = wrap.closest('form');
    if (form) {
      var change = document.createEvent('Event'); change.initEvent('change', true, true);
      form.dispatchEvent(change);
    }
  }

  /* ---- public API ------------------------------------------------- */
  window.ATRUE_LocPicker = {
    ensureData: ensureData,
    resolve: resolve,
    set: function (wrap, country, countryCode, province, municipality, barangay) {
      buildPanel();
      applyTo(wrap, country, countryCode, province, municipality, barangay);
    },
    applySuggestion: function (form, text) {
      // Used by suggestion chips: resolve text and set the form's loc fields.
      var wrap = form && form.querySelector('[data-loc-picker]');
      var loc = resolve(text);
      if (loc && (wrap || form)) {
        if (wrap) {
          applyTo(wrap, loc.country, loc.country_code, loc.province, loc.municipality, loc.barangay);
        } else {
          var country = form.querySelector('input[name="loc_country"]');
          if (country) country.value = loc.country || '';
          var hidden = form.querySelector('input[name="loc_province"]');
          if (loc.province && hidden) {
            hidden.value = loc.province || '';
            var mm = form.querySelector('input[name="loc_municipality"]');
            if (mm) mm.value = loc.municipality || '';
            var bb = form.querySelector('input[name="loc_barangay"]');
            if (bb) bb.value = loc.barangay || '';
          }
        }
        return loc;
      }
      return null;
    },
    syncFromForm: function (form) {
      // called on load so serverside-rendered loc values reflect in the UI
      for (var i = 0; i < wraps.length; i++) {
        var wrap = wraps[i];
        if (wrap.closest('form') !== form) continue;
        applyToWrap(wrap);
      }
    },
  };

  /* ---- init ------------------------------------------------------- */
  function init() {
    buildPanel();
    wraps = qsa('[data-loc-picker]');
    qsa('[data-loc-toggle]').forEach(function (tr) {
      tr.addEventListener('click', function (e) {
        if (e.target.closest && e.target.closest('[data-loc-clear]')) {
          e.preventDefault(); e.stopPropagation();
          var w = tr.closest('[data-loc-picker]');
          if (w) clear(w);
          return;
        }
        e.preventDefault(); e.stopPropagation();
        var wrap = tr.closest('[data-loc-picker]');
        if (wrap) setActiveWrap(wrap);
        ensureData(function () { open(tr); });
      });
    });
    ensureData(function (d) { data = d; });

    // reflect server-side loc values on load
    wraps.forEach(function (wrap) {
      applyToWrap(wrap);
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
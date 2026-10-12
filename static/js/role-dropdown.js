(() => {
  const categoryFor = (value) => {
    const code = value.toUpperCase();
    if (/(^|_)(ADMINISTRATOR|SYSTEM_ADMINISTRATOR|INSTRUCTOR)(_|$)/.test(code)) return 'Administration';
    if (/(^|_)(MANAGER|SUPERVISOR)(_|$)/.test(code)) return 'Management';
    if (/(^|_)(GUEST|CUSTOMER|PASSENGER)(_|$)/.test(code)) return 'Guests and Customers';
    return 'Operations';
  };

  const iconFor = {
    'Administration': 'fa-user-shield',
    'Management': 'fa-briefcase',
    'Operations': 'fa-clipboard-check',
    'Guests and Customers': 'fa-user'
  };

  function initialize(select) {
    if (!select || select.dataset.rolePickerReady) return;
    select.dataset.rolePickerReady = 'true';

    const wrapper = document.createElement('div');
    wrapper.className = 'role-picker';
    select.parentNode.insertBefore(wrapper, select);
    wrapper.appendChild(select);
    select.classList.add('role-picker-native');
    select.tabIndex = -1;
    select.setAttribute('aria-hidden', 'true');

    const trigger = document.createElement('button');
    trigger.type = 'button';
    trigger.className = 'role-picker-trigger';
    trigger.setAttribute('aria-haspopup', 'listbox');
    trigger.setAttribute('aria-expanded', 'false');
    trigger.setAttribute('aria-label', 'Select a user role');
    trigger.innerHTML = '<span class="role-picker-trigger-icon" aria-hidden="true"><i class="fas fa-user-tag"></i></span><span class="role-picker-trigger-label"></span><i class="fas fa-chevron-down role-picker-chevron" aria-hidden="true"></i>';
    wrapper.appendChild(trigger);

    const panel = document.createElement('div');
    panel.className = 'role-picker-panel';
    panel.hidden = true;
    panel.innerHTML = '<label class="role-picker-search-wrap"><i class="fas fa-search" aria-hidden="true"></i><input class="role-picker-search" type="search" placeholder="Search roles..." autocomplete="off" aria-label="Search roles"></label><div class="role-picker-list" role="listbox"></div><div class="role-picker-empty" hidden>No roles match your search.</div>';
    document.body.appendChild(panel);

    const input = panel.querySelector('.role-picker-search');
    const list = panel.querySelector('.role-picker-list');
    const empty = panel.querySelector('.role-picker-empty');
    const triggerLabel = trigger.querySelector('.role-picker-trigger-label');

    function options() {
      return Array.from(select.options).filter(option => option.value);
    }

    function sync() {
      const selected = select.options[select.selectedIndex];
      triggerLabel.textContent = selected && selected.value ? selected.textContent : 'Select role';
      trigger.classList.toggle('has-value', Boolean(selected && selected.value));
      trigger.setAttribute('aria-label', selected && selected.value ? 'Selected role: ' + selected.textContent : 'Select a user role');
      render();
    }

    function render() {
      const query = input.value.trim().toLocaleLowerCase();
      const groups = new Map();
      options().forEach(option => {
        if (query && !(option.textContent + ' ' + option.value).toLocaleLowerCase().includes(query)) return;
        const category = categoryFor(option.value);
        if (!groups.has(category)) groups.set(category, []);
        groups.get(category).push(option);
      });

      list.replaceChildren();
      const categoryOrder = ['Administration', 'Management', 'Operations', 'Guests and Customers'];
      Array.from(groups.entries()).sort((a, b) => categoryOrder.indexOf(a[0]) - categoryOrder.indexOf(b[0])).forEach(([category, items]) => {
        const section = document.createElement('section');
        section.className = 'role-picker-group';
        const heading = document.createElement('h3');
        heading.className = 'role-picker-group-title';
        heading.innerHTML = '<i class="fas ' + iconFor[category] + '" aria-hidden="true"></i><span>' + category + '</span><span class="role-picker-group-count">' + items.length + '</span>';
        section.appendChild(heading);
        items.forEach(option => {
          const item = document.createElement('button');
          item.type = 'button';
          item.className = 'role-picker-option';
          item.setAttribute('role', 'option');
          item.setAttribute('aria-selected', option.value === select.value ? 'true' : 'false');
          item.dataset.value = option.value;
          item.innerHTML = '<span class="role-picker-option-icon"><i class="fas ' + iconFor[category] + '" aria-hidden="true"></i></span><span class="role-picker-option-copy"><strong></strong><small></small></span><i class="fas fa-check role-picker-check" aria-hidden="true"></i>';
          item.querySelector('strong').textContent = option.textContent;
          item.querySelector('small').textContent = category;
          item.addEventListener('click', () => {
            select.value = option.value;
            select.dispatchEvent(new Event('change', { bubbles: true }));
            sync();
            close();
            trigger.focus();
          });
          section.appendChild(item);
        });
        list.appendChild(section);
      });
      empty.hidden = list.children.length !== 0;
    }

    function placePanel() {
      const rect = trigger.getBoundingClientRect();
      const margin = 12;
      const width = Math.min(Math.max(rect.width, 300), window.innerWidth - margin * 2);
      const left = Math.min(Math.max(margin, rect.left), window.innerWidth - width - margin);
      const below = window.innerHeight - rect.bottom - margin;
      const above = rect.top - margin;
      const openUp = below < 250 && above > below;
      const available = Math.max(180, (openUp ? above : below) - 8);
      panel.style.width = width + 'px';
      panel.style.left = left + 'px';
      panel.style.maxHeight = Math.min(390, available) + 'px';
      if (openUp) {
        panel.style.top = 'auto';
        panel.style.bottom = (window.innerHeight - rect.top + 6) + 'px';
      } else {
        panel.style.bottom = 'auto';
        panel.style.top = (rect.bottom + 6) + 'px';
      }
    }

    function open() {
      sync();
      panel.hidden = false;
      trigger.setAttribute('aria-expanded', 'true');
      placePanel();
      input.value = '';
      render();
      input.focus();
    }

    function close() {
      panel.hidden = true;
      trigger.setAttribute('aria-expanded', 'false');
    }

    trigger.addEventListener('click', () => panel.hidden ? open() : close());
    input.addEventListener('input', render);
    input.addEventListener('keydown', event => {
      if (event.key === 'Escape') {
        close();
        trigger.focus();
      } else if (event.key === 'ArrowDown') {
        const first = list.querySelector('.role-picker-option');
        if (first) { event.preventDefault(); first.focus(); }
      }
    });
    panel.addEventListener('keydown', event => {
      if (event.key === 'Escape') {
        close();
        trigger.focus();
      }
    });
    document.addEventListener('click', event => {
      if (!wrapper.contains(event.target) && !panel.contains(event.target)) close();
    });
    window.addEventListener('resize', () => { if (!panel.hidden) placePanel(); });
    window.addEventListener('scroll', () => { if (!panel.hidden) placePanel(); }, true);

    const form = select.form;
    const wasRequired = select.required;
    select.required = false;
    if (form) {
      form.addEventListener('submit', event => {
        if (wasRequired && !select.value) {
          event.preventDefault();
          event.stopImmediatePropagation();
          trigger.classList.add('is-invalid');
          trigger.setAttribute('aria-invalid', 'true');
          open();
        }
      }, true);
    }
    select.addEventListener('change', () => {
      trigger.classList.remove('is-invalid');
      trigger.removeAttribute('aria-invalid');
      sync();
    });

    sync();
  }

  function getPicker(select) {
    return select && select.parentElement && select.parentElement.classList.contains('role-picker')
      ? select.parentElement : null;
  }

  window.syncRolePicker = select => {
    const wrapper = getPicker(select);
    if (!wrapper) return;
    const label = wrapper.querySelector('.role-picker-trigger-label');
    const selected = select.options[select.selectedIndex];
    if (label) label.textContent = selected && selected.value ? selected.textContent : 'Select role';
    wrapper.querySelector('.role-picker-trigger').classList.toggle('has-value', Boolean(selected && selected.value));
  };
  window.focusRolePicker = select => {
    const wrapper = getPicker(select);
    const trigger = wrapper && wrapper.querySelector('.role-picker-trigger');
    if (trigger) trigger.focus();
  };

  document.querySelectorAll('[data-role-picker]').forEach(initialize);
})();

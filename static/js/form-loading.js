// ============================================================
// ATRUE - Form submission feedback
// ------------------------------------------------------------
// Forms marked with data-submit-loading show an inline spinner on
// the submit button, disable the button(s) so a booking cannot be
// submitted twice, and expose a busy state to assistive tech.
// The disabling is deferred by one tick so the browser still
// includes the clicked button's name/value in the form payload.
// ============================================================
(function () {
    'use strict';

    var FORM_SELECTOR = 'form[data-submit-loading]';

    function submitButtons(form, submitter) {
        var buttons = Array.prototype.slice.call(
            form.querySelectorAll('button[type="submit"], input[type="submit"]')
        );
        if (submitter && buttons.indexOf(submitter) === -1) buttons.push(submitter);
        return buttons;
    }

    function showLoading(button) {
        if (!button || button.dataset.atrueLoading === '1') return;
        button.dataset.atrueLoading = '1';

        if (button.tagName === 'INPUT') {
            if (button.dataset.atrueLabelValue === undefined) {
                button.dataset.atrueLabelValue = button.value;
            }
            button.disabled = true;
            button.classList.add('is-loading');
            button.setAttribute('aria-busy', 'true');
            return;
        }

        if (button.dataset.atrueLabelHtml === undefined) {
            button.dataset.atrueLabelHtml = button.innerHTML;
        }
        var spinner = '<span class="atrue-btn-spinner" aria-hidden="true"></span>';
        button.innerHTML = spinner + (button.dataset.loadingLabel || button.dataset.atrueLabelHtml);
        button.disabled = true;
        button.classList.add('is-loading');
        button.setAttribute('aria-busy', 'true');
    }

    function resetButton(button) {
        if (button.dataset.atrueLoading !== '1') return;
        delete button.dataset.atrueLoading;
        button.disabled = false;
        button.classList.remove('is-loading');
        button.removeAttribute('aria-busy');
        if (button.tagName === 'INPUT') {
            if (button.dataset.atrueLabelValue !== undefined) {
                button.value = button.dataset.atrueLabelValue;
            }
        } else if (button.dataset.atrueLabelHtml !== undefined) {
            button.innerHTML = button.dataset.atrueLabelHtml;
        }
    }

    function resetForm(form) {
        form.classList.remove('is-submitting');
        form.removeAttribute('aria-busy');
        delete form.dataset.atrueSubmitting;
        delete form.dataset.atrueSubmitPending;
        form.querySelectorAll('[data-atrue-loading="1"]').forEach(resetButton);
    }

    document.addEventListener('submit', function (event) {
        var form = event.target;
        if (!form || !form.matches || !form.matches(FORM_SELECTOR)) return;

        if (form.dataset.atrueSubmitting === '1' || form.dataset.atrueSubmitPending === '1') {
            event.preventDefault();
            return;
        }

        form.dataset.atrueSubmitPending = '1';
        var submitter = event.submitter || null;

        window.setTimeout(function () {
            if (event.defaultPrevented) {
                delete form.dataset.atrueSubmitPending;
                return;
            }
            delete form.dataset.atrueSubmitPending;
            form.dataset.atrueSubmitting = '1';
            form.classList.add('is-submitting');
            form.setAttribute('aria-busy', 'true');
            submitButtons(form, submitter).forEach(showLoading);
        }, 0);
    }, false);

    // Restore interactive state when the browser returns via history.
    window.addEventListener('pageshow', function (event) {
        if (!event.persisted) return;
        document.querySelectorAll('form.is-submitting').forEach(resetForm);
    });

    // Allow AJAX flows to re-enable their form after a response.
    document.addEventListener('atrue:form-reset', function (event) {
        var form = event.target;
        if (form && form.matches && form.matches(FORM_SELECTOR)) resetForm(form);
    });

    // ------------------------------------------------------------
    // Required-field highlighting
    // ------------------------------------------------------------
    // Empty required fields (native `required` or `aria-required`)
    // get a red `.is-invalid` state on submit. This also covers forms
    // using `novalidate`, where the browser would not show anything.
    var IGNORED_TYPES = {
        hidden: true,
        submit: true,
        button: true,
        reset: true,
        image: true
    };

    function isEmptyValue(field) {
        if (field.type === 'radio') {
            if (!field.name) return !field.checked;
            var group = field.form ? field.form.elements[field.name] : null;
            if (group && group.length !== undefined) {
                for (var i = 0; i < group.length; i++) {
                    if (group[i].checked) return false;
                }
                return true;
            }
            return !field.checked;
        }
        if (field.type === 'checkbox') return !field.checked;
        if (field.type === 'file') return !field.files || field.files.length === 0;
        return String(field.value == null ? '' : field.value).trim() === '';
    }

    function isRequired(field) {
        return field.required === true || field.getAttribute('aria-required') === 'true';
    }

    function needsHighlight(field) {
        if (!field || !field.classList || field.disabled) return false;
        if (IGNORED_TYPES[field.type]) return false;
        if (typeof field.checkValidity === 'function' && !field.checkValidity()) return true;
        return isRequired(field) && isEmptyValue(field);
    }

    function markInvalid(field) {
        if (!field || !field.classList) return;
        field.classList.add('is-invalid');
        field.setAttribute('aria-invalid', 'true');
    }

    function clearInvalid(field) {
        if (!field || !field.classList) return;
        if (needsHighlight(field)) return;
        field.classList.remove('is-invalid');
        field.removeAttribute('aria-invalid');
    }

    function fieldsInForm(form) {
        return Array.prototype.slice.call(form.querySelectorAll('input, select, textarea'));
    }

    document.addEventListener('invalid', function (event) {
        markInvalid(event.target);
    }, true);

    // Shared validator: marks every unfinished/invalid field, focuses the
    // first one and returns it (or null when the form is complete).
    function validateForm(form) {
        if (!form || !form.querySelectorAll) return null;
        var firstInvalid = null;
        fieldsInForm(form).forEach(function (field) {
            if (!needsHighlight(field)) return;
            markInvalid(field);
            if (!firstInvalid) firstInvalid = field;
        });
        if (!firstInvalid) return null;
        try {
            firstInvalid.focus();
        } catch (error) {
            /* Hidden or custom widgets may not be focusable. */
        }
        if (typeof firstInvalid.scrollIntoView === 'function') {
            firstInvalid.scrollIntoView({ block: 'center', behavior: 'smooth' });
        }
        return firstInvalid;
    }

    window.ATRUE_validateForm = validateForm;

    document.addEventListener('submit', function (event) {
        var form = event.target;
        if (!form || !form.matches || !form.matches('form')) return;
        if (validateForm(form)) event.preventDefault();
    }, true);

    function revalidate(event) {
        var field = event.target;
        if (!field || !field.classList) return;
        if (field.type === 'radio' || field.type === 'checkbox') {
            var group = field.name && field.form ? field.form.elements[field.name] : null;
            if (group && group.length !== undefined) {
                Array.prototype.forEach.call(group, clearInvalid);
                return;
            }
        }
        clearInvalid(field);
    }

    document.addEventListener('input', revalidate, true);
    document.addEventListener('change', revalidate, true);

    document.addEventListener('reset', function (event) {
        var form = event.target;
        if (!form || !form.querySelectorAll) return;
        form.querySelectorAll('.is-invalid').forEach(function (field) {
            field.classList.remove('is-invalid');
            field.removeAttribute('aria-invalid');
        });
    }, true);
})();

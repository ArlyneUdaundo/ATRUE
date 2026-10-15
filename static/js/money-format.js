/* Shared Philippine money input and display formatting. */
(function () {
    'use strict';

    var inputValue = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value');
    if (!inputValue || !inputValue.get || !inputValue.set) return;

    var moneyName = /(?:^|[_-])(?:price|amount|rate|fare|fee|cost|discount|subtotal|balance|deposit|charge|refund|bill|tax(?:es)?|commission|budget|tip)(?:$|[_-])/i;
    var exactMoneyName = /^(?:total|payment|(?:booking_)?total_(?:amount|bill|price|fare|cost|fee))$/i;
    var moneyLabel = /(₱|\bphp\b|price|amount|rate|fare|fee|cost|discount|subtotal|balance|deposit|charge|refund|bill|tax|commission|budget|tip)/i;
    var nonMoneyNumber = /^(?:baggage|passengers?|participants?|capacity|guests?|adults?|children|infants?|units?|travelers?|visitors?|nights?|seats?|duration(?:_.*)?|.*_minutes|.*_hours|distance_km|quantity|qty|headcount|connection_minutes)$/i;
    var explicitCurrencyLabel = /(₱|\bphp\b)/i;
    var percentValue = /(?:percent(?:age)?|_pct|\(%\)|\bpercentage\b|%)/i;
    var currencyText = /(₱\s*|(?:PHP|PhP)\s*)(-?\d[\d,]*(?:\.\d+)?)/g;
    var numericText = /^-?\d[\d,]*(?:\.\d+)?$/;
    var displayClass = /(?:price|money|currency|fcard-amount|payment-amount|bill-amount|field-(?:price|amount|rate|fare|fee|cost|discount|total|balance|deposit|charge|refund|bill|tax)(?:_|\s|$))/i;
    var fields = new Set();

    function groupNumber(value) {
        var text = String(value == null ? '' : value).replace(/,/g, '').trim();
        if (!text || text === '-' || text === '.' || text === '-.') return text;
        var negative = text.charAt(0) === '-';
        if (negative) text = text.slice(1);
        var parts = text.split('.');
        var integer = parts[0].replace(/\D/g, '').replace(/^0+(?=\d)/, '') || '0';
        integer = integer.replace(/\B(?=(\d{3})+(?!\d))/g, ',');
        return (negative ? '-' : '') + integer + (parts.length > 1 ? '.' + parts.slice(1).join('') : '');
    }

    function cleanNumber(value, allowNegative, precision) {
        var numericSource = String(value == null ? '' : value).replace(/,/g, '').replace(/[^\d.\-]/g, '');
        var negative = allowNegative && numericSource.charAt(0) === '-';
        var original = String(value == null ? '' : value).replace(/,/g, '');
        var dotAt = original.indexOf('.');
        var integerSource = original.slice(0, dotAt < 0 ? original.length : dotAt).replace(/[^\d]/g, '');
        var decimalSource = dotAt < 0 ? '' : original.slice(dotAt + 1).replace(/[^\d]/g, '');
        if (!allowNegative) integerSource = integerSource.replace(/-/g, '');
        integerSource = integerSource.replace(/^0+(?=\d)/, '');
        if (!integerSource && (decimalSource || dotAt >= 0)) integerSource = '0';
        if (precision >= 0) decimalSource = decimalSource.slice(0, precision);
        if (!integerSource && !decimalSource && dotAt < 0) return negative ? '-' : '';
        return (negative ? '-' : '') + (integerSource || (dotAt >= 0 ? '0' : ''))
            + (dotAt >= 0 && precision !== 0 ? '.' + decimalSource : '');
    }

    function decimalPlaces(input) {
        var step = input.getAttribute('step');
        if (step === 'any') return 2;
        if (step && step.indexOf('.') >= 0) return Math.min(8, step.split('.')[1].length);
        if (input.dataset.moneyPrecision) return Math.max(0, Number(input.dataset.moneyPrecision));
        return input.type === 'number' ? 0 : 2;
    }

    function allowNegative(input) {
        return input.dataset.allowNegative === 'true'
            || (input.hasAttribute('min') && Number(input.getAttribute('min')) < 0);
    }

    function countEditableChars(value) {
        return (value.match(/[\d.\-]/g) || []).length;
    }

    function caretAfterEditableChars(value, count) {
        if (count <= 0) return 0;
        var found = 0;
        for (var i = 0; i < value.length; i++) {
            if (/[\d.\-]/.test(value.charAt(i))) found++;
            if (found >= count) return i + 1;
        }
        return value.length;
    }

    function validityMessage(input, raw) {
        if (!raw) return '';
        if (raw === '-' || raw.endsWith('.')) return 'Complete entering the amount.';
        var value = Number(raw);
        if (!Number.isFinite(value)) return 'Enter a valid amount.';
        var min = input.getAttribute('min');
        var max = input.getAttribute('max');
        if (min !== null && value < Number(min)) return 'Enter an amount of at least ' + min + '.';
        if (max !== null && value > Number(max)) return 'Enter an amount no greater than ' + max + '.';
        var step = input.getAttribute('step');
        if (step && step !== 'any' && Number(step) > 0) {
            var base = min !== null ? Number(min) : 0;
            var remainder = (value - base) / Number(step);
            if (Math.abs(remainder - Math.round(remainder)) > 1e-7) return 'Enter an amount using increments of ' + step + '.';
        }
        return '';
    }

    function isMoneyInput(input) {
        if (!input || input.dataset.moneyReady || input.type === 'hidden'
            || input.type === 'checkbox' || input.type === 'radio' || input.type === 'file') return false;
        if (input.type !== 'number' && input.type !== 'text' && input.type !== 'search') return false;
        if (input.hasAttribute('data-no-money-format')) return false;
        if (input.hasAttribute('data-money-input')) return true;
        var labels = input.labels ? Array.prototype.map.call(input.labels, function (label) { return label.textContent; }).join(' ') : '';
        var parentLabel = input.closest('label');
        if (parentLabel) labels += ' ' + parentLabel.textContent;
        var current = inputValue.get.call(input).trim();
        var numericValue = !current || /^-?[\d,]*(?:\.\d*)?$/.test(current);
        var fieldName = input.name || input.id;
        if (percentValue.test(fieldName + ' ' + labels)) return false;
        if (input.type === 'number') {
            if (nonMoneyNumber.test(fieldName)) return false;
            return moneyName.test(fieldName) || exactMoneyName.test(fieldName) || moneyLabel.test(labels);
        }
        return numericValue && (input.dataset.moneyInput || moneyName.test(fieldName) || exactMoneyName.test(fieldName) || explicitCurrencyLabel.test(labels));
    }

    function attachForm(form) {
        if (!form || form.dataset.moneyFormReady) return;
        form.dataset.moneyFormReady = '1';
        form.addEventListener('formdata', function (event) {
            var grouped = new Map();
            fields.forEach(function (input) {
                if (!input.isConnected || input.form !== form || !input.name || input.matches(':disabled')) return;
                if (!grouped.has(input.name)) grouped.set(input.name, []);
                grouped.get(input.name).push(input.value);
            });
            grouped.forEach(function (values, name) {
                event.formData.delete(name);
                values.forEach(function (value) { event.formData.append(name, value); });
            });
        });
        // Fallback for native submission paths that do not expose FormDataEvent.
        form.addEventListener('submit', function () {
            fields.forEach(function (input) {
                if (input.form !== form || !input.isConnected) return;
                var raw = input.value;
                inputValue.set.call(input, raw);
                window.setTimeout(function () { inputValue.set.call(input, groupNumber(raw)); }, 0);
            });
        }, true);
        form.addEventListener('reset', function () {
            window.setTimeout(function () {
                fields.forEach(function (input) {
                    if (input.form !== form || !input.isConnected) return;
                    input.value = inputValue.get.call(input);
                });
            }, 0);
        });
    }

    function initInput(input) {
        if (!isMoneyInput(input)) return;
        var previousType = input.type;
        var precision = decimalPlaces(input);
        var negative = allowNegative(input);
        var raw = cleanNumber(inputValue.get.call(input), negative, precision);
        var initialFormatted = groupNumber(raw);
        if (previousType === 'number') input.type = 'text';
        input.inputMode = input.dataset.inputmode || 'decimal';
        input.autocomplete = input.autocomplete || 'off';
        input.dataset.moneyReady = '1';
        input.dataset.moneyOriginalType = previousType;

        function setRaw(value, updateDisplay) {
            raw = cleanNumber(value, negative, precision);
            if (updateDisplay !== false) inputValue.set.call(input, groupNumber(raw));
            input.setCustomValidity(validityMessage(input, raw));
        }

        Object.defineProperty(input, 'value', {
            configurable: true,
            get: function () { return raw; },
            set: function (value) { setRaw(value, true); }
        });
        setRaw(raw, false);
        inputValue.set.call(input, initialFormatted);

        input.addEventListener('input', function () {
            var visible = inputValue.get.call(input);
            var oldCaret = input.selectionStart;
            var editableBefore = oldCaret == null ? 0 : countEditableChars(visible.slice(0, oldCaret));
            setRaw(visible, false);
            var formatted = groupNumber(raw);
            inputValue.set.call(input, formatted);
            input.setCustomValidity(validityMessage(input, raw));
            if (oldCaret != null && document.activeElement === input) {
                var caret = caretAfterEditableChars(formatted, editableBefore);
                input.setSelectionRange(caret, caret);
            }
        }, true);
        input.addEventListener('blur', function () {
            var latest = cleanNumber(inputValue.get.call(input), negative, precision);
            if (latest === '-' || latest.endsWith('.')) latest = latest.slice(0, -1);
            setRaw(latest, true);
        });
        input.addEventListener('change', function () {
            input.dispatchEvent(new Event('input', { bubbles: true }));
        });
        input.addEventListener('paste', function (event) {
            event.preventDefault();
            var pasted = (event.clipboardData || window.clipboardData).getData('text');
            var start = input.selectionStart == null ? input.value.length : input.selectionStart;
            var end = input.selectionEnd == null ? start : input.selectionEnd;
            var visible = inputValue.get.call(input);
            input.value = visible.slice(0, start) + pasted + visible.slice(end);
            var caret = caretAfterEditableChars(groupNumber(input.value), countEditableChars(visible.slice(0, start) + pasted));
            input.focus();
            input.setSelectionRange(caret, caret);
            input.dispatchEvent(new Event('input', { bubbles: true }));
        });
        input.addEventListener('keydown', function (event) {
            if (event.ctrlKey || event.metaKey || event.altKey || event.key.length !== 1) return;
            if (!/[\d.\-]/.test(event.key)) { event.preventDefault(); return; }
            if (event.key === '-' && (!negative || (input.selectionStart !== 0 && input.selectionEnd !== input.value.length))) event.preventDefault();
            if (event.key === '.' && precision === 0 && !input.value.includes('.')) event.preventDefault();
        });
        fields.add(input);
        attachForm(input.form);
    }

    function formatMoneyText(text) {
        return text.replace(currencyText, function (match, prefix, amount) {
            return prefix + groupNumber(amount);
        });
    }

    function hasMoneyDisplayClass(element) {
        for (var node = element; node && node !== document.body; node = node.parentElement) {
            if (displayClass.test(typeof node.className === 'string' ? node.className : '')) return true;
        }
        return false;
    }

    function formatDisplayText(root) {
        var walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
            acceptNode: function (node) {
                if (!node.nodeValue || !node.nodeValue.trim() || node.parentElement.closest('script,style,textarea,input,select,option')) return NodeFilter.FILTER_REJECT;
                return NodeFilter.FILTER_ACCEPT;
            }
        });
        var nodes = [];
        while (walker.nextNode()) nodes.push(walker.currentNode);
        nodes.forEach(function (node) {
            var original = node.nodeValue;
            var formatted = formatMoneyText(original);
            if (formatted !== original) { node.nodeValue = formatted; return; }
            var trimmed = original.trim();
            if (!numericText.test(trimmed)) return;
            var parent = node.parentElement;
            var currencyContext = false;
            for (var depth = 0; parent && parent !== document.body && depth < 5; depth++, parent = parent.parentElement) {
                if (/(₱|\bphp\b)/i.test(parent.textContent) || hasMoneyDisplayClass(parent)) {
                    currencyContext = true;
                    break;
                }
            }
            if (currencyContext) {
                var grouped = groupNumber(trimmed);
                // MutationObserver watches characterData too. Writing the same
                // value still queues another observer callback in some
                // browsers, so leave already-formatted numbers untouched.
                if (grouped !== trimmed) {
                    node.nodeValue = original.replace(trimmed, grouped);
                }
            }
        });
    }

    function init(root) {
        if (root && root.nodeType === 1 && root.matches('input')) initInput(root);
        (root || document).querySelectorAll('input').forEach(initInput);
        attachForm(root && root.nodeType === 1 && root.matches('form') ? root : null);
        formatDisplayText(root && root.nodeType === 1 ? root : document.body);
    }

    window.ATRUEMoney = {
        parse: function (value) {
            var cleaned = String(value == null ? '' : value).replace(/,/g, '').replace(/[^\d.\-]/g, '');
            var number = Number(cleaned);
            return Number.isFinite(number) ? number : 0;
        },
        format: groupNumber,
        init: init
    };

    function start() {
        init(document);
        if (window.MutationObserver) {
            var observer = new MutationObserver(function (records) {
                records.forEach(function (record) {
                    if (record.type === 'childList') record.addedNodes.forEach(function (node) {
                        if (node.nodeType === 1) init(node);
                        else if (node.nodeType === 3 && node.parentElement) formatDisplayText(node.parentElement);
                    });
                    else if (record.type === 'characterData' && record.target.parentElement) formatDisplayText(record.target.parentElement);
                });
            });
            observer.observe(document.body, { childList: true, subtree: true, characterData: true });
        }
    }

    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start);
    else start();
})();

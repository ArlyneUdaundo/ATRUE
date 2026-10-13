(function () {
    'use strict';
    var phoneName = /(?:^|_)(?:emergency_)?contact(?:_number)?$/i;
    function setup(input) {
        var name = input.name || '';
        if (!phoneName.test(name)) return;
        var isPayer = /(?:^|_)payer_contact$/i.test(name);
        if (!isPayer) {
            input.setAttribute('inputmode', 'numeric');
            input.maxLength = 11;
            input.setAttribute('pattern', '[0-9]{11}');
        } else {
            input.maxLength = 254;
        }
        function validate() {
            var value = input.value.trim();
            var valid = !value || (/^\d{11}$/.test(value)) ||
                (isPayer && /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value));
            input.setCustomValidity(valid ? '' : 'Enter exactly 11 digits' + (isPayer ? ' or a valid email address.' : '.'));
        }
        input.addEventListener('input', function () {
            if (!isPayer) {
                input.value = input.value.replace(/[^0-9]/g, '').slice(0, 11);
            }
            validate();
        });
        input.addEventListener('change', validate);
        input.addEventListener('invalid', validate);
        validate();
    }
    function init(root) {
        (root || document).querySelectorAll('input[name]').forEach(setup);
    }
    function start() {
        init();
        new MutationObserver(function (changes) {
            changes.forEach(function (change) {
                change.addedNodes.forEach(function (node) {
                    if (node.nodeType !== 1) return;
                    if (node.matches && node.matches('input[name]')) setup(node);
                    init(node);
                });
            });
        }).observe(document.body, { childList: true, subtree: true });
    }
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start);
    else start();
    window.atruePhoneValidation = { init: init };
})();
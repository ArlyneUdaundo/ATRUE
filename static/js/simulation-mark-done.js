(function () {
    'use strict';

    var modal = document.getElementById('markRoleDoneModal');
    if (!modal || modal.dataset.ready === '1') return;
    modal.dataset.ready = '1';

    var message = document.getElementById('markRoleDoneMessage');
    var error = document.getElementById('markRoleDoneError');
    var confirmButton = document.getElementById('confirmMarkRoleDone');
    var pendingForm = null;
    var defaultMessage = 'Are you sure you want to mark this assignment as done? You can still view it later if needed.';

    function closeModal() {
        if (modal.open) modal.close();
        pendingForm = null;
        confirmButton.disabled = false;
    }

    document.addEventListener('submit', function (event) {
        var form = event.target;
        if (!(form instanceof HTMLFormElement) || !form.matches('form[data-mark-role-done]')) return;
        event.preventDefault();
        if (pendingForm || confirmButton.disabled) return;

        pendingForm = form;
        message.textContent = defaultMessage;
        error.hidden = true;
        error.textContent = '';
        confirmButton.disabled = false;
        modal.showModal();
    });

    document.getElementById('cancelMarkRoleDone').addEventListener('click', closeModal);
    document.getElementById('closeMarkRoleDone').addEventListener('click', closeModal);
    modal.addEventListener('click', function (event) {
        if (event.target === modal) closeModal();
    });
    modal.addEventListener('close', function () {
        pendingForm = null;
        confirmButton.disabled = false;
    });

    confirmButton.addEventListener('click', async function () {
        if (!pendingForm || confirmButton.disabled) return;
        confirmButton.disabled = true;
        error.hidden = true;
        error.textContent = '';

        try {
            var response = await fetch(pendingForm.action, {
                method: 'POST',
                body: new FormData(pendingForm),
                headers: { 'X-Requested-With': 'XMLHttpRequest' },
                credentials: 'same-origin'
            });
            var result;
            try {
                result = await response.json();
            } catch (parseError) {
                throw new Error('The server returned an unexpected response. Please try again.');
            }
            if (!response.ok || !result.ok) {
                throw new Error(result.message || 'Could not mark this assignment as done. Please try again.');
            }

            var completionEvent = new CustomEvent('simulation-assignment-completed', {
                bubbles: true,
                cancelable: true,
                detail: result
            });
            pendingForm.dispatchEvent(completionEvent);
            modal.close();
            pendingForm = null;
            if (!completionEvent.defaultPrevented) window.location.reload();
        } catch (requestError) {
            error.textContent = requestError.message || 'Could not mark this assignment as done. Please try again.';
            error.hidden = false;
            confirmButton.disabled = false;
        }
    });
})();

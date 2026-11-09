(function () {
  'use strict';

  document.querySelectorAll('[data-hbd-gallery]').forEach(function (gallery) {
    var images = Array.prototype.slice.call(gallery.querySelectorAll('[data-hbd-image]'));
    var currentLabel = gallery.querySelector('[data-hbd-current]');
    var buttons = gallery.querySelectorAll('[data-hbd-step]');
    var active = 0;
    if (images.length < 2 || !buttons.length) return;

    buttons.forEach(function (button) {
      button.addEventListener('click', function () {
        active = (active + Number(button.dataset.hbdStep) + images.length) % images.length;
        images.forEach(function (image, index) {
          image.classList.toggle('is-active', index === active);
        });
        if (currentLabel) currentLabel.textContent = String(active + 1);
      });
    });
  });
}());

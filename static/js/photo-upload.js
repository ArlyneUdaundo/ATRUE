(() => {
  'use strict';

  const MAX_BYTES = 5 * 1024 * 1024;
  const MAX_PHOTOS = 5;
  const INVALID_MESSAGE = 'Please upload a valid JPG, JPEG, or PNG image.';
  const OVERSIZED_MESSAGE = 'Image size must not exceed 5 MB.';
  const EMPTY_MESSAGE = 'The selected image is empty. Please choose a different file.';
  const JPEG_EXTENSION = /\.jpe?g$/i;
  const PNG_EXTENSION = /\.png$/i;
  const ALLOWED_TYPES = new Set(['image/jpeg', 'image/png']);

  const imageType = async file => {
    const bytes = new Uint8Array(await file.slice(0, 8).arrayBuffer());
    if (bytes.length >= 3 && bytes[0] === 0xff && bytes[1] === 0xd8 && bytes[2] === 0xff) {
      return 'image/jpeg';
    }
    const png = [0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a];
    if (bytes.length >= png.length && png.every((value, index) => bytes[index] === value)) {
      return 'image/png';
    }
    return '';
  };

  document.querySelectorAll('[data-photo-upload]').forEach(input => {
    const section = input.closest('[data-establishment-photo-section]')
      || input.closest('.photo-upload-section')
      || input.closest('.profile-photo-fields')
      || input.parentElement;
    const drop = input.closest('[data-photo-drop]');
    const preview = section.querySelector('[data-photo-preview]');
    const count = section.querySelector('[data-photo-count]');
    const error = section.querySelector('[data-photo-error]');
    const livePreview = document.querySelector('[data-profile-live-preview]');
    const clearSelection = section.querySelector('[data-photo-clear-selection]');
    const isProfile = input.dataset.photoKind === 'profile';
    const originalProfilePreview = livePreview?.innerHTML || '';
    const existingPhotos = section.querySelectorAll('[data-photo-existing] .photo-upload-existing-card').length;
    const selected = [];
    const objectUrls = new Set();
    let errorTimer = null;

    const showError = message => {
      if (error) {
        error.textContent = message;
        error.hidden = !message;
      }
      if (errorTimer) window.clearTimeout(errorTimer);
      if (message) {
        errorTimer = window.setTimeout(() => {
          if (error) error.hidden = true;
        }, 8000);
      }
    };

    const revokeUrls = () => {
      objectUrls.forEach(url => URL.revokeObjectURL(url));
      objectUrls.clear();
    };

    const update = () => {
      revokeUrls();
      const removed = section.querySelectorAll('[data-photo-existing] input[name="delete_photos"]:checked').length;
      const remaining = Math.max(0, existingPhotos - removed);
      const max = isProfile ? 1 : Number(input.dataset.maxCount || MAX_PHOTOS);
      const total = isProfile ? selected.length : remaining + selected.length;
      if (count) count.textContent = `${total} of ${max} photos`;
      input.disabled = !isProfile && remaining + selected.length >= max;
      if (clearSelection) clearSelection.hidden = selected.length === 0;
      if (preview) {
        preview.replaceChildren();
        selected.forEach((file, index) => {
          const card = document.createElement('div');
          card.className = 'photo-upload-card';
          const img = document.createElement('img');
          img.alt = file.name;
          const url = URL.createObjectURL(file);
          objectUrls.add(url);
          img.src = url;
          const name = document.createElement('span');
          name.className = 'photo-upload-filename';
          name.textContent = file.name;
          const remove = document.createElement('button');
          remove.type = 'button';
          remove.className = 'photo-upload-remove';
          remove.textContent = 'Remove';
          remove.addEventListener('click', () => {
            selected.splice(index, 1);
            writeFiles();
          });
          card.append(img, name, remove);
          preview.append(card);
        });
      }
      if (isProfile && livePreview) {
        if (selected.length) {
          let img = livePreview.querySelector('img');
          if (!img) {
            img = document.createElement('img');
            livePreview.replaceChildren(img);
          }
          const url = URL.createObjectURL(selected[0]);
          objectUrls.add(url);
          img.src = url;
          img.alt = 'Selected profile photo preview';
          livePreview.classList.remove('profile-photo-empty');
        } else {
          livePreview.innerHTML = originalProfilePreview;
          livePreview.classList.toggle('profile-photo-empty', !livePreview.querySelector('img'));
        }
      }
    };

    const writeFiles = () => {
      const transfer = new DataTransfer();
      selected.forEach(file => transfer.items.add(file));
      input.files = transfer.files;
      update();
    };

    const validateFile = async file => {
      if (!file || file.size === 0) return EMPTY_MESSAGE;
      if (file.size > MAX_BYTES) return OVERSIZED_MESSAGE;
      const actualType = await imageType(file).catch(() => '');
      if (!actualType || !ALLOWED_TYPES.has(actualType)) return INVALID_MESSAGE;
      if (file.type && !ALLOWED_TYPES.has(file.type)) return INVALID_MESSAGE;
      if (actualType === 'image/jpeg' && !JPEG_EXTENSION.test(file.name)) return INVALID_MESSAGE;
      if (actualType === 'image/png' && !PNG_EXTENSION.test(file.name)) return INVALID_MESSAGE;
      return '';
    };

    const addFiles = async files => {
      showError('');
      const accepted = [];
      const max = isProfile ? 1 : Number(input.dataset.maxCount || MAX_PHOTOS);
      const removed = section.querySelectorAll('[data-photo-existing] input[name="delete_photos"]:checked').length;
      const capacity = isProfile ? 1 : Math.max(0, max - existingPhotos + removed);
      for (const file of files) {
        const message = await validateFile(file);
        if (message) {
          showError(message);
          continue;
        }
        if (accepted.length + selected.length >= capacity) {
          showError(isProfile ? 'Only one profile photo can be selected.' : 'You can upload a maximum of 5 establishment photos.');
          break;
        }
        accepted.push(file);
      }
      selected.push(...accepted);
      writeFiles();
    };

    input.addEventListener('change', () => {
      const files = Array.from(input.files || []);
      if (isProfile) selected.splice(0);
      addFiles(files);
    });
    if (drop) {
      ['dragenter', 'dragover'].forEach(name => drop.addEventListener(name, event => {
        event.preventDefault();
        drop.classList.add('is-dragover');
      }));
      ['dragleave', 'drop'].forEach(name => drop.addEventListener(name, event => {
        event.preventDefault();
        drop.classList.remove('is-dragover');
      }));
      drop.addEventListener('drop', event => addFiles(Array.from(event.dataTransfer.files || [])));
    }
    section.querySelectorAll('[data-photo-existing] input[name="delete_photos"]').forEach(box => {
      box.addEventListener('change', update);
    });
    clearSelection?.addEventListener('click', () => {
      selected.splice(0);
      writeFiles();
      showError('');
    });
    update();
  });
})();

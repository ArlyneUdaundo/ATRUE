// ============================================================
// ATRUE — Frontend Interactions
// ============================================================

document.addEventListener('DOMContentLoaded', () => {

    // ----- Preloader -----
    const preloader = document.getElementById('preloader');
    const hidePreloader = () => preloader && preloader.classList.add('done');
    const preloaderDuration = 3000;
    const preloaderStartedAt = Date.now();
    const schedulePreloaderHide = () => {
        const remaining = Math.max(0, preloaderDuration - (Date.now() - preloaderStartedAt));
        setTimeout(hidePreloader, remaining);
    };
    window.addEventListener('load', schedulePreloaderHide, { once: true });
    setTimeout(hidePreloader, preloaderDuration);

    // ----- Navbar scrolled state -----
    const navbar = document.getElementById('navbar');
    const backTop = document.getElementById('backTop');
    const onScroll = () => {
        const y = window.scrollY;
        navbar && navbar.classList.toggle('scrolled', y > 40);
        backTop && backTop.classList.toggle('show', y > 600);
    };
    window.addEventListener('scroll', onScroll, { passive: true });
    onScroll();

    // ----- Mobile drawer -----
    const drawer = document.getElementById('mobileDrawer');
    const backdrop = document.getElementById('backdrop');
    const mToggle = document.getElementById('mobileToggle');

    const closeDrawer = () => {
        drawer && drawer.classList.remove('open');
        backdrop && backdrop.classList.remove('show');
        mToggle && mToggle.classList.remove('active');
        document.body.style.overflow = '';
    };
    const openDrawer = () => {
        drawer && drawer.classList.add('open');
        backdrop && backdrop.classList.add('show');
        mToggle && mToggle.classList.add('active');
        document.body.style.overflow = 'hidden';
    };

    if (mToggle) {
        mToggle.addEventListener('click', () => {
            drawer.classList.contains('open') ? closeDrawer() : openDrawer();
        });
    }
    backdrop && backdrop.addEventListener('click', closeDrawer);
    drawer && drawer.querySelectorAll('a').forEach(a => a.addEventListener('click', closeDrawer));

    // ----- Establishment dropdown (show only when clicked) -----
    document.querySelectorAll('.has-dropdown').forEach(dd => {
        const trigger = dd.querySelector(':scope > .nav-link');
        if (!trigger) return;
        trigger.addEventListener('click', e => {
            e.stopPropagation();
            const wasOpen = dd.classList.contains('open');
            document.querySelectorAll('.has-dropdown.open').forEach(d => d.classList.remove('open'));
            if (!wasOpen) dd.classList.add('open');
        });
    });
    document.addEventListener('click', e => {
        document.querySelectorAll('.has-dropdown.open').forEach(dd => {
            if (!dd.contains(e.target)) dd.classList.remove('open');
        });
    });

    // ----- Back to top -----
    backTop && backTop.addEventListener('click', () => window.scrollTo({ top: 0, behavior: 'smooth' }));

    // ----- Scroll reveal -----
    const revealEls = document.querySelectorAll('[data-reveal]');
    const revealOpts = { threshold: 0.12, rootMargin: '0px 0px -40px 0px' };
    if ('IntersectionObserver' in window) {
        const io = new IntersectionObserver((entries, obs) => {
            entries.forEach((entry, i) => {
                if (entry.isIntersecting) {
                    setTimeout(() => entry.target.classList.add('revealed'), i * 60);
                    obs.unobserve(entry.target);
                }
            });
        }, revealOpts);
        revealEls.forEach(el => io.observe(el));
    } else {
        revealEls.forEach(el => el.classList.add('revealed'));
    }

    // ----- Active nav link -----
    const sections = document.querySelectorAll('section[id]');
    const navLinks = document.querySelectorAll('.nav-link');
    window.addEventListener('scroll', () => {
        let cur = '';
        sections.forEach(s => {
            if (window.scrollY >= s.offsetTop - 140) cur = s.getAttribute('id');
        });
        navLinks.forEach(l => {
            const href = l.getAttribute('href') || '';
            l.classList.toggle('active', href === '#' + cur);
        });
        // home stays active when at top
        if (window.scrollY < 100) {
            navLinks.forEach(l => l.classList.toggle('active', (l.getAttribute('href') || '').length <= 6 && (l.getAttribute('href')||'').includes('home')));
        }
    }, { passive: true });

    // ----- Smooth scroll for anchors -----
    document.querySelectorAll('a[href^="#"]').forEach(anchor => {
        anchor.addEventListener('click', e => {
            const id = anchor.getAttribute('href');
            if (id.length < 2) return;
            const t = document.querySelector(id);
            if (t) {
                e.preventDefault();
                const top = t.getBoundingClientRect().top + window.scrollY - 74;
                window.scrollTo({ top, behavior: 'smooth' });
            }
        });
    });

    // ----- Contact form (real POST — success flash shown server-side) -----
    const form = document.getElementById('contactForm');
    if (form) {
        form.addEventListener('submit', () => {
            const btn = form.querySelector('button[type="submit"]');
            if (form.dataset.submitting) return;
            form.dataset.submitting = '1';
            if (btn) { btn.disabled = true; btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Sending...'; }
        });
    }

    // ----- Hero parallax on mouse move -----
    document.addEventListener('mousemove', e => {
        if (window.innerWidth < 768) return;
        const x = (e.clientX / window.innerWidth - 0.5);
        const y = (e.clientY / window.innerHeight - 0.5);
        document.querySelectorAll('.hero-visual .glass-panel').forEach((el, i) => {
            const f = (i + 1) * 1.2;
            el.style.translate = `${x * f}px ${y * f}px`;
        });
        document.querySelectorAll('.hero-orb').forEach((el, i) => {
            const f = (i + 1) * 2;
            el.style.marginLeft = `${x * f}px`;
            el.style.marginTop = `${y * f}px`;
        });
    });

    // ----- Landing-page search tabs -----
    document.querySelectorAll('[data-search-tab]').forEach(label => {
        label.addEventListener('click', () => {
            const form = label.closest('form');
            if (!form) return;
            const radio = document.getElementById(label.getAttribute('for'));
            if (radio) radio.checked = true;
            setTimeout(() => form.requestSubmit(), 0);
        });
    });
    const searchResults = document.getElementById('live');
    if (searchResults && new URLSearchParams(window.location.search).get('q')) {
        setTimeout(() => searchResults.scrollIntoView({ behavior: 'smooth', block: 'start' }), 150);
    }

    // ----- Agoda-style image galleries -----
    document.querySelectorAll('[data-gallery]').forEach(gallery => {
        const images = Array.from(gallery.querySelectorAll('.agoda-gallery-image'));
        if (!images.length) return;
        let index = Math.max(0, images.findIndex(img => img.classList.contains('is-active')));
        const dots = gallery.querySelector('[data-gallery-dots]');
        const render = () => {
            images.forEach((img, i) => img.classList.toggle('is-active', i === index));
            if (dots) {
                dots.innerHTML = images.map((_, i) => `<button type=\"button\" class=\"agoda-gallery-dot ${i === index ? 'active' : ''}\" data-gallery-index=\"${i}\" aria-label=\"Photo ${i+1}\"></button>`).join('');
                dots.querySelectorAll('[data-gallery-index]').forEach(btn => btn.addEventListener('click', () => { index = Number(btn.dataset.galleryIndex); render(); }));
            }
        };
        gallery.querySelector('[data-gallery-prev]')?.addEventListener('click', () => { index = (index - 1 + images.length) % images.length; render(); });
        gallery.querySelector('[data-gallery-next]')?.addEventListener('click', () => { index = (index + 1) % images.length; render(); });
        render();
    });

    // ----- Inline image carousel on hotel cards (Agoda style) -----
    // Wire the arrows + loop + counter that appear on feature/listing hotel
    // cards. data-images is the JSON serialized by the usable_urls filter, so
    // only images whose file actually exists are ever shown. First image is
    // already rendered server-side; we just need to drive the rest.
    document.querySelectorAll('[data-carousel]').forEach(car => {
        let list = [];
        try { list = JSON.parse(car.getAttribute('data-images') || '[]'); } catch (e) { list = []; }
        const count = list.length;
        if (!count) return; // placeholder branch already rendered server-side
        let index = 0;
        const img = car.querySelector('img[data-car-img]') || car.querySelector('img');
        const counter = car.querySelector('[data-car-count]');
        const update = () => {
            if (img && list[index]) { img.src = list[index]; }
            if (counter) { counter.textContent = (index + 1) + ' / ' + count; }
        };
        const prev = car.querySelector('[data-car-prev]');
        const next = car.querySelector('[data-car-next]');
        if (prev) prev.addEventListener('click', () => { index = (index - 1 + count) % count; update(); });
        if (next) next.addEventListener('click', () => { index = (index + 1) % count; update(); });
        if (count > 1) { if (prev) prev.style.display = ''; if (next) next.style.display = ''; }
        update();
    });

    // ----- Password visibility toggle -----
    document.querySelectorAll('.pw-toggle').forEach(btn => {
        btn.addEventListener('click', () => {
            const input = btn.closest('.input-wrap').querySelector('input');
            const show = input.type === 'password';
            input.type = show ? 'text' : 'password';
            btn.innerHTML = show ? '<i class="fas fa-eye-slash"></i>' : '<i class="fas fa-eye"></i>';
        });
    });

    // ----- Click ripple (teal/cyan tourism glow) -----
    const rippleTargets = document.querySelectorAll(
        '.hm-card, .hm-item, .hm-role, .hm-contact-card, .hm-float, .hm-chip, .hm-more, ' +
        '.service-card, .live-card, .role-card, .feature-item, .contact-card, .stat-pill, ' +
        '.btn, .hm-btn, .socials a, .dropdown-item, .back-top, ' +
        '.stat-card, .scard, .cms-card, .user-chip'
    );
    const colors = ['', 'cyan', 'emerald'];
    rippleTargets.forEach(el => {
        el.addEventListener('click', e => {
            el.style.position = el.style.position || 'relative';
            el.style.overflow = 'hidden';
            const rect = el.getBoundingClientRect();
            const size = Math.max(rect.width, rect.height) * 0.6;
            const ring = document.createElement('span');
            ring.className = 'ripple-ring ' + colors[Math.floor(Math.random() * colors.length)];
            ring.style.width = ring.style.height = size + 'px';
            ring.style.left = (e.clientX - rect.left - size / 2) + 'px';
            ring.style.top = (e.clientY - rect.top - size / 2) + 'px';
            el.appendChild(ring);
            ring.addEventListener('animationend', () => ring.remove());
        });
    });

    // ----- Enable scroll reveal only when nothing failed above -----
    document.documentElement.classList.add('js-ready');
});

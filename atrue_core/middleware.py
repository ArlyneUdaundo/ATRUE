"""Middleware for independent per-tab authenticated contexts.

``accounts.models.AuthContext`` binds a per-tab token (kept in each tab's own
``sessionStorage``) to a real Django session. Every request from a tab carries
that token via ``?ctx=`` / ``X-ATRUE-CTX`` / a hidden ``ctx`` form field, and
this middleware activates the Django session stored for the token. Requests
without a token behave exactly like a stock Django app (sticky session cookie),
so nothing existing is affected.

The token must travel with the request *itself* (URL, header or form body) -
never via a plain cookie, because cookies are shared by every tab in the same
browser profile.

Why the tab session must never be the cookie session
----------------------------------------------------
``django.contrib.auth.login()`` calls ``session.cycle_key()``, which *deletes*
the current session row and creates a new one. If a tab's context pointed at
the shared cookie session, then signing in a second tab would cycle - and
therefore destroy - the first tab's authenticated session, silently logging the
first tab out. So this middleware always hands a tab a session of its own, and
it saves that session itself and restores the cookie session before
``SessionMiddleware`` gets a chance to repoint the shared cookie at it.

Where this middleware has to sit
--------------------------------
It must run directly after ``SessionMiddleware`` and *before*
``CsrfViewMiddleware``, ``AuthenticationMiddleware`` and
``MessageMiddleware``. Everything that middleware derives from ``request.session``
is then computed against the tab's own session instead of the browser-wide one:

  * ``request.user`` comes from the tab's session, so roles and permissions are
    per tab (and this middleware no longer has to patch ``request.user``
    itself - ``AuthenticationMiddleware`` does it correctly, further down);
  * ``CSRF_USE_SESSIONS`` puts the CSRF secret in the tab's session, so
    ``login()``'s rotation of the token stays inside the tab that signed in
    instead of invalidating the forms already rendered in every other tab;
  * the message queue lives in the tab's session, so a "signed out" banner in
    one tab never pops up in another.

Running *below* those three would leave all of that state shared, which is the
bug this arrangement exists to prevent.
"""
import importlib

from django.conf import settings
from django.contrib.auth import (
    BACKEND_SESSION_KEY,
    SESSION_KEY,
    get_user,
    get_user_model,
)
from django.http.response import HttpResponseRedirectBase
from django.urls import Resolver404, resolve

from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


class StorageUploadErrorMiddleware:
    """Return a clear, credential-safe response when remote image storage fails."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_exception(self, request, exception):
        from botocore.exceptions import BotoCoreError, ClientError
        from django.core.exceptions import ImproperlyConfigured
        from django.http import HttpResponse
        from atrue_core.image_utils import InvalidImageUpload

        if isinstance(exception, InvalidImageUpload):
            return HttpResponse(str(exception), status=400,
                                content_type='text/plain; charset=utf-8')

        missing_storage_config = (
            isinstance(exception, ImproperlyConfigured)
            and 'SUPABASE' in str(exception).upper()
        )
        if isinstance(exception, (BotoCoreError, ClientError)) or missing_storage_config:
            return HttpResponse(
                'Image storage is unavailable. The image was not saved; please '
                'try again later or contact an administrator.',
                status=503,
                content_type='text/plain; charset=utf-8',
            )
        return None


class ContactNumberValidationMiddleware:
    """Reject malformed contact numbers on every POST, including raw-view forms."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.method == 'POST':
            import re
            from django.core.validators import validate_email
            from django.core.exceptions import ValidationError
            from django.http import HttpResponseBadRequest
            phone_field = re.compile(r'(?:^|_)(?:emergency_)?contact(?:_number)?$', re.I)
            for name in request.POST:
                if not phone_field.search(name):
                    continue
                value = (request.POST.get(name) or '').strip()
                if not value:
                    continue
                if re.fullmatch(r'\d{11}', value):
                    continue
                if name.lower().endswith('payer_contact'):
                    try:
                        validate_email(value)
                        continue
                    except ValidationError:
                        pass
                return HttpResponseBadRequest(
                    'Invalid contact number. Enter exactly 11 digits.'
                )
        return self.get_response(request)


class PaymentMethodValidationMiddleware:
    """Reject forged payment-method values before a booking view can save them."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.method == 'POST':
            from atrue_core.payment_methods import is_supported_payment_method
            for field in ('payment_method', 'mode_of_payment', 'method'):
                value = request.POST.get(field)
                if value is not None and not is_supported_payment_method(value):
                    from django.http import HttpResponseBadRequest
                    return HttpResponseBadRequest('Choose a supported payment method.')
        return self.get_response(request)


# Keys ``django.contrib.auth`` uses to remember the signed-in user in a session.
AUTH_SESSION_KEYS = (
    SESSION_KEY,
    BACKEND_SESSION_KEY,
    '_auth_user_hash',
    '_auth_user_id_hash',
)

# Per-browser bookkeeping that still has to travel with a tab when a new session
# is created for it.
#
# With ``CSRF_USE_SESSIONS`` the CSRF secret lives in the session, so a freshly
# created tab session must inherit the secret used by the form that bootstrapped
# it. Workflow data and one-shot messages are deliberately not copied.
CARRIED_KEYS = ('_csrftoken',)


def _load_session(session_key):
    engine = importlib.import_module(settings.SESSION_ENGINE)
    return engine.SessionStore(session_key)


def _carry_over(target, source):
    """Copy the keys a new tab session must not lose.

    Without this a brand new tab session starts blank, and the CSRF secret that
    ``CsrfViewMiddleware`` looks for lives nowhere - so the form the browser
    rendered before the session was created would be rejected as a forged
    request. No workflow data or messages are copied from the shared cookie.
    """
    for key in CARRIED_KEYS:
        value = source.get(key)
        if value is not None:
            target[key] = value


def _request_ctx_token(request):
    """Resolve the per-tab token carried by this request itself.

    The token is never read from a plain cookie: cookies are shared by every
    tab in the same browser profile, so a cookie transport would let one tab
    hijack another. It travels in the URL (``?ctx=``), a custom header, or a
    hidden ``ctx`` form field.
    """
    token = request.headers.get('X-ATRUE-CTX')
    if token:
        return token
    token = request.GET.get('ctx')
    if token:
        return token
    if request.method in ('POST', 'PUT', 'PATCH'):
        token = request.POST.get('ctx')
        if token:
            return token
    return None


def _is_login_submission(request):
    """True when this POST is the sign-in form being submitted.

    Such a request must never run against the shared cookie session, because
    ``login()`` would cycle (and destroy) whichever session that is.
    """
    if request.method != 'POST':
        return False
    try:
        match = resolve(request.path_info)
    except Resolver404:
        return False
    return (match.url_name or '') == 'login'


def _preserve_ctx_on_redirect(response, token):
    """Keep the tab token when the server issues a redirect.

    Django views build redirects with ``redirect('name')`` producing a bare
    relative ``Location`` (e.g. ``/dashboard/``). Without the token the next
    request would fall back to the shared cookie and could resolve a different
    tab's context. Only same-site relative redirects are rewritten; the token
    is never leaked to external absolute URLs.
    """
    if not isinstance(response, HttpResponseRedirectBase):
        return
    location = response.get('Location') or ''
    parts = urlsplit(location)
    if parts.scheme or parts.netloc:
        return
    query = parse_qsl(parts.query, keep_blank_values=True)
    if any(key == 'ctx' for key, _ in query):
        return
    query.append(('ctx', token))
    response['Location'] = urlunsplit((parts.scheme, parts.netloc,
                                       parts.path, urlencode(query), parts.fragment))


class TabSessionMiddleware:
    """Resolve which authenticated context a tab belongs to.

    Runs directly after ``SessionMiddleware``: when a context token is supplied,
    ``request.session`` is switched to the session registered for that token, so
    every piece of per-request state below this middleware (identity, roles,
    CSRF token, messages) is derived from the tab rather than from the cookie
    shared by the whole browser. The context is re-validated against the user it
    is bound to before it is honoured. A request without a token behaves exactly
    like a stock Django app.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    # -- request phase ----------------------------------------------------
    def __call__(self, request):
        from accounts.models import AuthContext

        token = _request_ctx_token(request)
        if not token:
            return self.get_response(request)

        cookie_session = request.session
        tab_session = self._activate(AuthContext, request, token)
        if tab_session is None:
            return self.get_response(request)

        request.session = tab_session
        try:
            response = self.get_response(request)
        finally:
            # Persist the tab's own session, then hand the cookie session back so
            # SessionMiddleware never repoints the shared cookie at this tab.
            # This runs in a finally block: if the view raises, leaving the tab
            # session installed would let SessionMiddleware below hand the whole
            # browser this tab's session key on the way out of a 500.
            if tab_session.modified:
                tab_session.save()
            self._resync_binding(AuthContext, token, tab_session)
            request.session = cookie_session

        _preserve_ctx_on_redirect(response, token)
        return response

    def _activate(self, AuthContext, request, token):
        """Return the session this tab must use, or None to stay on the cookie."""
        ctx = (AuthContext.objects
               .filter(token=token)
               .select_related('user')
               .first())

        if ctx is not None:
            session = _load_session(ctx.session_key)
            if ctx.user_id is None:
                # A tab that has signed out keeps its own anonymous workspace so
                # the "signed out" notice queued there is still delivered to it.
                # It carries no identity, so honouring it grants no access.
                if session.get(SESSION_KEY) is None:
                    return session
            elif (session.get(SESSION_KEY) == str(ctx.user_id)
                    and ctx.user.is_active):
                return session
            # The bound session is gone or no longer matches (expired, signed
            # out elsewhere, or destroyed by an older buggy cycle). Forget the
            # stale binding; this tab continues on the cookie session for this
            # one request.
            AuthContext.objects.filter(pk=ctx.pk).delete()
            return None

        if _is_login_submission(request):
            # A tab signing in needs a session of its own, otherwise login()
            # would cycle the shared cookie session and sign every other tab
            # out. The binding itself is written after login() has finished,
            # by _resync_binding, so the recycled key is always recorded.
            session = _load_session(None)
            _carry_over(session, request.session)
            session.save()
            return session

        # Every new tab gets its own session, including anonymous tabs. Booking
        # carts and in-progress workflows are stored in request.session by
        # their views, so leaving an anonymous tab on the cookie session would
        # let a second tab overwrite its state before either one signs in.
        # AuthenticationMiddleware has not run yet, so resolve the existing
        # cookie identity directly and copy only its auth keys; never copy its
        # workflow data into the new tab.
        session = _load_session(None)
        user = None
        source_token = request.GET.get('source_ctx')
        source = None
        if source_token and source_token != token:
            source = (AuthContext.objects
                      .filter(token=source_token)
                      .select_related('user')
                      .first())

        if source is not None:
            source_session = _load_session(source.session_key)
            if (source.user_id
                    and source_session.get(SESSION_KEY) == str(source.user_id)
                    and source.user.is_active):
                user = source.user
                for auth_key in AUTH_SESSION_KEYS:
                    value = source_session.get(auth_key)
                    if value is not None:
                        session[auth_key] = value
        elif (request.session.get(SESSION_KEY)
                and request.session.get(BACKEND_SESSION_KEY)):
            candidate = get_user(request)
            if candidate.is_authenticated:
                user = candidate
                for auth_key in AUTH_SESSION_KEYS:
                    value = request.session.get(auth_key)
                    if value is not None:
                        session[auth_key] = value

        _carry_over(session, request.session)
        session.save()
        AuthContext.objects.create(
            token=token,
            user=user,
            session_key=session.session_key,
        )
        return session

    # -- response phase ---------------------------------------------------
    def _resync_binding(self, AuthContext, token, session):
        """Record the token against whatever session the request ended up with.

        ``login()`` recycles the session key, so the key observed before the
        view ran is stale by the time the view returns. Re-deriving the binding
        here means the token always points at the session that is actually
        live.

        A sign-out clears the auth keys but keeps the row, pointing at the tab's
        now-anonymous session, so the notice the view queued is still delivered
        to that tab and to no other. Dropping the row instead would strand the
        message in a session the tab can no longer reach.
        """
        user_id = session.get(SESSION_KEY)
        if not user_id:
            AuthContext.objects.update_or_create(
                token=token,
                defaults={'user': None, 'session_key': session.session_key},
            )
            return
        user = get_user_model().objects.filter(pk=user_id).first()
        if user is None or not user.is_active:
            AuthContext.objects.filter(token=token).delete()
            return
        AuthContext.objects.update_or_create(
            token=token,
            defaults={'user': user, 'session_key': session.session_key},
        )

# Brevo email setup

The application is Django-based and sends transactional mail server-side to Brevo's `POST /v3/smtp/email` endpoint. The `notifications` app stores a booking email outbox and hashed, expiring password reset tokens in PostgreSQL. An outbox status of `SENT` means Brevo accepted the request and returned a message ID; it does not guarantee inbox delivery.

## Render environment

Set these values in the Render web service environment (never commit the API key):

| Variable | Value |
| --- | --- |
| `BREVO_API_KEY` | A Brevo transactional API key, stored as a secret |
| `BREVO_SENDER_EMAIL` | An email address registered and verified as a Brevo sender |
| `BREVO_SENDER_NAME` | Sender display name, e.g. ATRUE Simulation Portal |
| `APP_BASE_URL` | Canonical public HTTPS origin, e.g. `https://atrue-performance-staging.onrender.com` |

Verify the sender and sending domain in Brevo before enabling live sends. Configure the SPF/DKIM DNS records shown by Brevo for the sending domain. Set `APP_BASE_URL` to the production service origin when deploying production. Do not use a request Host header to construct reset links.

Deploy the migration with the application and confirm Render's build/start migration step applies it. The existing database URL and start/build commands are unchanged. To retry failed booking confirmations after configuring/fixing Brevo, run:

```sh
python manage.py retry_failed_emails
```

Password reset requests are rate-limited by HMAC digests of email and IP, with a generic browser response for known and unknown accounts. Reset tokens are stored as SHA-256 hashes, expire after 30 minutes, and are single-use. The raw token only exists temporarily in the post-commit sender callback and in the reset URL fragment submitted by the user.

Brevo transactional email docs: [send a transactional email](https://developers.brevo.com/docs/send-a-transactional-email). The API returns a message ID on acceptance; delivery events require a separately configured Brevo webhook if actual delivery tracking is needed.

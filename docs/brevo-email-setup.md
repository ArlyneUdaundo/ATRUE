# Brevo email setup

The application is Django-based and sends transactional mail server-side to Brevo's `POST /v3/smtp/email` endpoint. The `notifications` app stores a booking email outbox and hashed, expiring password reset tokens in PostgreSQL. An outbox status of `SENT` means Brevo accepted the request and returned a message ID; it does not guarantee inbox delivery.

## Render environment

Set these values in the Render web service environment (never commit the API key):

| Variable | Value |
| --- | --- |
| `BREVO_API_KEY` | A Brevo transactional API key, stored as a secret |
| `BREVO_SENDER_EMAIL` | An email address registered and verified as a Brevo sender |
| `BREVO_SENDER_NAME` | Sender display name, e.g. ATRUE Simulation Portal |
| `APP_BASE_URL` | Optional canonical public HTTPS origin. Set this to the site's custom domain when one is configured; otherwise the app uses Render's `RENDER_EXTERNAL_URL`. |

Create a dedicated restricted API key in Brevo's **SMTP & API → API keys & MCP** section. It needs permission to send transactional email (`POST /v3/smtp/email`) and list senders (`GET /v3/senders`, used by `check_brevo`). Do not paste the key into chat, source code, or logs. Replace `BREVO_API_KEY` in the Render service's Environment page and save; Render will redeploy/restart the service. Keep the old key active until the new key passes the checks below and existing email flows are confirmed.

Verify the sender and sending domain in Brevo before enabling live sends. Configure the SPF/DKIM DNS records shown by Brevo for the sending domain. For a custom domain, set `APP_BASE_URL` to that domain in Render and remove any stale value; otherwise reset links use Render's service URL. Do not use a request Host header to construct reset links.

Deploy the migration with the application and confirm Render's build/start migration step applies it. The existing database URL and start/build commands are unchanged. To retry failed booking confirmations after configuring/fixing Brevo, run:

```sh
python manage.py retry_failed_emails
```

Password reset requests are rate-limited by HMAC digests of email and IP, with a generic browser response for known and unknown accounts. They use the Brevo API directly; failures are recorded as failed and are not hidden by an SMTP fallback. Reset tokens are stored as SHA-256 hashes, expire after 30 minutes, and are single-use. The raw token only exists temporarily in the post-commit sender callback and in the reset URL fragment submitted by the user.

After updating the key, run `python manage.py check_brevo` in an environment that uses the Render settings. It confirms the key can list senders and that `BREVO_SENDER_EMAIL` is active. Then submit a reset request for a registered test account and check Render logs for `Password reset email accepted by Brevo API` plus its provider message ID. Confirm that ID in Brevo Transactional Logs and check the recipient's inbox and spam folder. A Brevo accepted event is not proof of inbox delivery; use the log's delivery events for that check. Do not revoke the old key until the reset flow and booking confirmation emails have been tested with the replacement key.

Brevo transactional email docs: [send a transactional email](https://developers.brevo.com/docs/send-a-transactional-email). The API returns a message ID on acceptance; delivery events require a separately configured Brevo webhook if actual delivery tracking is needed.

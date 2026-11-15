# Forgot Password email providers

The password reset flow can send through Brevo or Resend. `PASSWORD_RESET_EMAIL_PROVIDER` selects the provider and defaults to `brevo`. This selection is used only by Forgot Password; booking confirmations continue to use the existing Brevo path. Provider failures are recorded as failed and are not retried through another provider automatically.

Reset tokens are stored as SHA-256 hashes, expire after 30 minutes, and are single-use. The reset URL uses `APP_BASE_URL`, or falls back to Render's `RENDER_EXTERNAL_URL`. API acceptance and a provider message ID mean the provider accepted the request; they do not prove inbox delivery.

## Configure Resend as the password-reset provider

1. Create a Resend account and add a sending domain you control in **Domains**.
2. Add the SPF and DKIM records Resend provides at your DNS host. Wait until Resend reports the domain as verified with sending enabled. Do not select Resend before this step; an unverified sender will be rejected.
3. Create a restricted API key with email sending access for the verified domain. Keep it in Render only; never commit or paste it into chat.
4. In the Render staging service's **Environment** page, set:

   | Variable | Value |
   | --- | --- |
   | `PASSWORD_RESET_EMAIL_PROVIDER` | `resend` |
   | `RESEND_API_KEY` | New Resend API key, stored as a secret |
   | `RESEND_SENDER_EMAIL` | Verified sender, for example `no-reply@mail.your-domain.example` |
   | `RESEND_SENDER_NAME` | `ATRUE Simulation Portal` |
   | `APP_BASE_URL` | The staging HTTPS domain |

5. Save and redeploy the staging service. Submit one reset request for an authorized test account. Confirm the provider message ID in Render logs and the message in Resend's **Emails** page. Then verify inbox delivery and use the link to change the password and sign in. Keep `PASSWORD_RESET_EMAIL_PROVIDER=resend` only after the domain is verified and the live test succeeds.

Resend's current free plan lists 3,000 transactional emails per month with a 100-per-day limit; check the [current pricing page](https://resend.com/pricing) for changes. The implementation calls Resend's official `POST https://api.resend.com/emails` API with a bearer API key and idempotency key. See [Send Email API](https://resend.com/docs/api-reference/emails/send-email) and [List Domains API](https://resend.com/docs/api-reference/domains/list-domains).

## Switch back to Brevo

Set `PASSWORD_RESET_EMAIL_PROVIDER=brevo` in Render and redeploy. Existing `BREVO_API_KEY`, `BREVO_SENDER_EMAIL`, and `BREVO_SENDER_NAME` remain the Brevo configuration. The application does not silently fall back between providers, so logs identify which configured provider accepted or rejected a reset request.

## Safe diagnostics

Successful API requests log the selected provider, reset row ID, and provider message ID. Failures log only a sanitized provider/status code. Neither API keys, recipient addresses, nor reset tokens are logged. Check provider event logs and the recipient inbox separately to confirm delivery; an API response alone is not delivery proof.

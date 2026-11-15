# Forgot Password email providers

The password reset flow can send through Brevo, Resend, or Gmail SMTP. `PASSWORD_RESET_EMAIL_PROVIDER` selects the provider and defaults to `brevo`. This selection is used only by Forgot Password; booking confirmations continue to use the existing Brevo path. Provider failures are recorded as failed and are not retried through another provider automatically.

Reset tokens are stored as SHA-256 hashes, expire after 30 minutes, and are single-use. The reset URL uses `APP_BASE_URL`, or falls back to Render's `RENDER_EXTERNAL_URL`. API acceptance and a provider message ID mean the provider accepted the request; they do not prove inbox delivery.

## Use Gmail SMTP without owning a domain

For low-volume staging, Gmail SMTP can send as the Gmail mailbox that authenticates to Google; it does not let the application spoof an unrelated sender. The current local sender is a Gmail address, but the existing Brevo SMTP credentials do not authenticate that mailbox.

1. The mailbox owner must confirm they control the exact Gmail address to be used as the sender and enable 2-Step Verification.
2. In that Google Account, create an App Password for this application. Google says App Passwords are less secure and recommends Sign in with Google where supported. App Passwords are unavailable for some managed, Advanced Protection, or security-key-only accounts. Never use the account's normal password.
3. In the Render staging service's **Environment** page, set:

   | Variable | Value |
   | --- | --- |
   | `PASSWORD_RESET_EMAIL_PROVIDER` | `gmail_smtp` |
   | `GMAIL_SMTP_USER` | The authorized Gmail mailbox; this is also the From address |
   | `GMAIL_SMTP_APP_PASSWORD` | The App Password, stored as a secret |
   | `GMAIL_SENDER_NAME` | `ATRUE Simulation Portal` |
   | `APP_BASE_URL` | `https://atrue-performance-staging.onrender.com` |

4. Save and redeploy. In Render **Logs**, a reset attempt records the selected provider without logging the recipient address or reset token. Failures are recorded with a sanitized code such as `GMAIL_SMTP_CONFIGURATION_MISSING`, `GMAIL_SMTP_AUTH_FAILED`, `GMAIL_SMTP_CONNECTION_FAILED`, `GMAIL_SMTP_TLS_FAILED`, or `GMAIL_SMTP_RECIPIENT_REJECTED`. Fix the corresponding Render setting or Gmail account issue, then redeploy and retry with an authorized test account.
5. A `Password reset email accepted by gmail_smtp SMTP relay` log means Gmail accepted the message from the application; it does not prove inbox delivery. Gmail SMTP has no transactional-provider message ID. Confirm actual receipt in the recipient's inbox or spam folder, then test the reset link and sign in with the changed password.

This is a no-purchase option for modest staging traffic, not a high-volume transactional service. Google currently documents a limit of 500 emails per day for personal Gmail accounts; account-specific anti-abuse limits may be lower. Do not use it for bulk mail. For dependable production-scale password resets, use a domain you control with a transactional provider.

## Configure Resend as the password-reset provider

1. Create a Resend account and add a sending domain you control in **Domains**. Resend requires a verified domain for sending; its `resend.dev` addresses are test addresses, not a production sender for arbitrary ATRUE users.
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

Resend's current free plan lists 3,000 transactional emails per month with a 100-per-day limit; check the [current pricing page](https://resend.com/pricing) for changes. The implementation calls Resend's official `POST https://api.resend.com/emails` API with a bearer API key and idempotency key. See [Verified Domains](https://resend.com/docs/dashboard/domains/introduction), [Send Email API](https://resend.com/docs/api-reference/emails/send-email), and [List Domains API](https://resend.com/docs/api-reference/domains/list-domains).

Other options do not remove the authentication problem: SendGrid's single-sender verification can verify a mailbox without DNS, but SendGrid warns that large inbox providers may fail DMARC for such senders. Amazon SES can verify individual email identities, but new accounts are sandboxed to verified recipients and production access requires review. Neither is as quick or dependable for this domain-less staging setup as sending through the actual Gmail account.

## Switch back to Brevo

Set `PASSWORD_RESET_EMAIL_PROVIDER=brevo` in Render and redeploy. Existing `BREVO_API_KEY`, `BREVO_SENDER_EMAIL`, and `BREVO_SENDER_NAME` remain the Brevo configuration. The application does not silently fall back between providers, so logs identify which configured provider accepted or rejected a reset request.

## Safe diagnostics

Successful API requests log the selected provider, reset row ID, and provider message ID. Gmail SMTP logs relay acceptance without inventing a provider ID. Failures log only a sanitized provider/status code. Neither credentials, recipient addresses, nor reset tokens are logged. Check provider event logs and the recipient inbox separately to confirm delivery; API or SMTP acceptance alone is not delivery proof.

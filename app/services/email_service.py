import html
import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import logging
import datetime

def send_otp_email(recipient_email, otp_code, recipient_name="User", verify_url=None):

    # One-click link first, code as the fallback. If no public base URL is
    # configured _build_verify_url returns None and the email degrades to the
    # code-only version it has always been.
    verify_block = ""
    # The code label has to follow the link: "Or enter this code" reads as a
    # non-sequitur when there is no link above it to be an alternative to.
    code_label = "Your verification code:"
    if verify_url:
        code_label = "Or enter this code:"
        verify_block = (
            '<a href="' + verify_url + '" '
            'style="display:inline-block;background:#22D3EE;color:#04121a;'
            'text-decoration:none;padding:14px 28px;border-radius:10px;'
            'font-weight:600;font-size:16px;">Verify my email</a>'
            '<p style="margin:14px 0 0;color:#94a3b8;font-size:12px;">'
            'This link can be used once and expires with the code below.</p>'
        )
    """
    Sends an OTP verification code via Gmail SMTP.
    """
    sender_email = os.getenv("SMTP_SENDER_EMAIL")
    sender_password = os.getenv("SMTP_APP_PASSWORD")

    if not sender_email or not sender_password:
        logging.warning("SMTP credentials missing in .env. OTP email not sent.")
        return False

    subject = "Verify your Volleo account"
    
    # Premium HTML email template
    html_content = f"""
    <html>
      <body style="font-family: Arial, sans-serif; background-color: #f4f4f5; padding: 40px 0; margin: 0; color: #333;">
        <div style="max-width: 500px; margin: 0 auto; background: white; border-radius: 12px; overflow: hidden; box-shadow: 0 4px 15px rgba(0,0,0,0.1);">
          <div style="background-color: #060A12; padding: 24px; text-align: center;">
            <h2 style="color: #22D3EE; margin: 0; font-size: 24px; letter-spacing: -0.5px;">Volleo</h2>
          </div>
          <div style="padding: 32px;">
            <h3 style="margin-top: 0; font-size: 20px; color: #1e293b;">Email Verification</h3>
            <p style="font-size: 16px; line-height: 1.5; color: #475569;">
              Hi {recipient_name},<br><br>
              Thank you for registering. To complete your account setup, please use the verification code below:
            </p>
            <div style="background-color: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px; padding: 16px; text-align: center; margin: 24px 0;">
              {verify_block}<p style="margin:18px 0 6px;color:#64748b;font-size:14px;">{code_label}</p><span style="font-size: 32px; font-weight: bold; letter-spacing: 4px; color: #0E7490;">{otp_code}</span>
            </div>
            <p style="font-size: 14px; color: #64748b;">
              This code will expire in 10 minutes. If you didn't request this, you can safely ignore this email.
            </p>
          </div>
          <div style="background-color: #f8fafc; padding: 16px; text-align: center; font-size: 12px; color: #94a3b8; border-top: 1px solid #e2e8f0;">
            &copy; {datetime.datetime.now().year if 'datetime' in globals() else 2026} Volleo. All rights reserved.
          </div>
        </div>
      </body>
    </html>
    """

    message = MIMEMultipart("alternative")
    message["Subject"] = subject
    message["From"] = f"Volleo <{sender_email}>"
    message["To"] = recipient_email

    # Add HTML content
    part = MIMEText(html_content, "html")
    message.attach(part)

    try:
        # Create a secure SSL context and send email
        server = smtplib.SMTP("smtp.gmail.com", 587)
        server.starttls()
        server.login(sender_email, sender_password)
        server.sendmail(sender_email, recipient_email, message.as_string())
        server.quit()
        logging.info(f"OTP email sent successfully to {recipient_email}")
        return True
    except Exception as e:
        logging.error(f"Failed to send OTP email to {recipient_email}: {e}")
        return False


def send_reset_email(recipient_email, otp_code, recipient_name="User"):
    """
    Sends a Password Reset OTP code via Gmail SMTP.
    """
    sender_email = os.getenv("SMTP_SENDER_EMAIL")
    sender_password = os.getenv("SMTP_APP_PASSWORD")

    if not sender_email or not sender_password:
        logging.warning("SMTP credentials missing in .env. Reset email not sent.")
        return False

    subject = "Reset your Volleo password"
    
    html_content = f"""
    <html>
      <body style="font-family: Arial, sans-serif; background-color: #f4f4f5; padding: 40px 0; margin: 0; color: #333;">
        <div style="max-width: 500px; margin: 0 auto; background: white; border-radius: 12px; overflow: hidden; box-shadow: 0 4px 15px rgba(0,0,0,0.1);">
          <div style="background-color: #060A12; padding: 24px; text-align: center;">
            <h2 style="color: #22D3EE; margin: 0; font-size: 24px; letter-spacing: -0.5px;">Volleo</h2>
          </div>
          <div style="padding: 32px;">
            <h3 style="margin-top: 0; font-size: 20px; color: #1e293b;">Password Reset Request</h3>
            <p style="font-size: 16px; line-height: 1.5; color: #475569;">
              Hi {recipient_name},<br><br>
              We received a request to reset your account password. Please use the verification code below to complete the reset process:
            </p>
            <div style="background-color: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px; padding: 16px; text-align: center; margin: 24px 0;">
              <span style="font-size: 32px; font-weight: bold; letter-spacing: 4px; color: #0E7490;">{otp_code}</span>
            </div>
            <p style="font-size: 14px; color: #64748b;">
              This code will expire in 10 minutes. If you did not request a password reset, you can safely ignore this email and your password will remain unchanged.
            </p>
          </div>
          <div style="background-color: #f8fafc; padding: 16px; text-align: center; font-size: 12px; color: #94a3b8; border-top: 1px solid #e2e8f0;">
            &copy; {datetime.datetime.now().year if 'datetime' in globals() else 2026} Volleo. All rights reserved.
          </div>
        </div>
      </body>
    </html>
    """

    message = MIMEMultipart("alternative")
    message["Subject"] = subject
    message["From"] = f"Volleo <{sender_email}>"
    message["To"] = recipient_email

    part = MIMEText(html_content, "html")
    message.attach(part)

    try:
        server = smtplib.SMTP("smtp.gmail.com", 587)
        server.starttls()
        server.login(sender_email, sender_password)
        server.sendmail(sender_email, recipient_email, message.as_string())
        server.quit()
        logging.info(f"Reset email sent successfully to {recipient_email}")
        return True
    except Exception as e:
        logging.error(f"Failed to send reset email to {recipient_email}: {e}")
        return False

def send_invite_email(recipient_email, invite_link, recipient_name="User"):
    """
    Sends an invitation email via Resend SDK.
    Falls back to SMTP if Resend is not configured.
    Returns True if sent, False otherwise.
    """
    resend_api_key = os.getenv("RESEND_API_KEY")

    if resend_api_key:
        try:
            import resend

            resend.api_key = resend_api_key

            sender = os.getenv("RESEND_SENDER", "AI System <onboarding@yourdomain.com>")

            html_content = f"""
            <html>
              <body style="font-family: Arial, sans-serif; background-color: #f4f4f5; padding: 40px 0; margin: 0; color: #333;">
                <div style="max-width: 500px; margin: 0 auto; background: white; border-radius: 12px; overflow: hidden; box-shadow: 0 4px 15px rgba(0,0,0,0.1);">
                  <div style="background-color: #3b82f6; padding: 24px; text-align: center;">
                    <h2 style="color: white; margin: 0; font-size: 24px;">AI CHATBOT</h2>
                  </div>
                  <div style="padding: 32px;">
                    <h3 style="margin-top: 0; font-size: 20px; color: #1e293b;">You're Invited!</h3>
                    <p style="font-size: 16px; line-height: 1.5; color: #475569;">
                      Hi {recipient_name},<br><br>
                      You have been invited to join our platform. Click the button below to create your account and get started.
                    </p>
                    <div style="text-align: center; margin: 32px 0;">
                      <a href="{invite_link}" style="background-color: #3b82f6; color: white; padding: 14px 36px; border-radius: 8px; text-decoration: none; font-size: 16px; font-weight: bold; display: inline-block;">Accept Invitation</a>
                    </div>
                    <p style="font-size: 14px; color: #64748b;">
                      Or copy and paste this link in your browser:<br>
                      <span style="color: #3b82f6; word-break: break-all;">{invite_link}</span>
                    </p>
                    <p style="font-size: 13px; color: #94a3b8; margin-top: 24px;">
                      This invitation expires in 72 hours. If you were not expecting this invite, you can safely ignore this email.
                    </p>
                  </div>
                  <div style="background-color: #f8fafc; padding: 16px; text-align: center; font-size: 12px; color: #94a3b8; border-top: 1px solid #e2e8f0;">
                    &copy; AI CHATBOT. All rights reserved.
                  </div>
                </div>
              </body>
            </html>
            """

            params = {
                "from": sender,
                "to": recipient_email,
                "subject": "You're invited to join our platform",
                "html": html_content,
            }

            response = resend.Emails.send(params)
            logging.info(f"Invite email sent via Resend to {recipient_email}: {response}")
            return True

        except Exception as e:
            logging.error(f"Failed to send invite email via Resend to {recipient_email}: {e}")
            # Fall through to SMTP fallback

    # SMTP fallback
    sender_email = os.getenv("SMTP_SENDER_EMAIL")
    sender_password = os.getenv("SMTP_APP_PASSWORD")

    if not sender_email or not sender_password:
        logging.warning("No email provider configured (Resend or SMTP). Invite email not sent.")
        return False

    try:
        import smtplib
        from email.mime.text import MIMEText
        from email.mime.multipart import MIMEMultipart

        frontend_url = os.getenv("FRONTEND_URL", "")

        html_content = f"""
        <html>
          <body style="font-family: Arial, sans-serif; background-color: #f4f4f5; padding: 40px 0; margin: 0; color: #333;">
            <div style="max-width: 500px; margin: 0 auto; background: white; border-radius: 12px; overflow: hidden; box-shadow: 0 4px 15px rgba(0,0,0,0.1);">
              <div style="background-color: #3b82f6; padding: 24px; text-align: center;">
                <h2 style="color: white; margin: 0; font-size: 24px;">AI CHATBOT</h2>
              </div>
              <div style="padding: 32px;">
                <h3 style="margin-top: 0; font-size: 20px; color: #1e293b;">You're Invited!</h3>
                <p style="font-size: 16px; line-height: 1.5; color: #475569;">
                  Hi {recipient_name},<br><br>
                  You have been invited to join our platform. Click the button below to create your account and get started.
                </p>
                <div style="text-align: center; margin: 32px 0;">
                  <a href="{invite_link}" style="background-color: #3b82f6; color: white; padding: 14px 36px; border-radius: 8px; text-decoration: none; font-size: 16px; font-weight: bold; display: inline-block;">Accept Invitation</a>
                </div>
                <p style="font-size: 14px; color: #64748b;">
                  Or copy and paste this link in your browser:<br>
                  <span style="color: #3b82f6; word-break: break-all;">{invite_link}</span>
                </p>
                <p style="font-size: 13px; color: #94a3b8; margin-top: 24px;">
                  This invitation expires in 72 hours. If you were not expecting this invite, you can safely ignore this email.
                </p>
              </div>
              <div style="background-color: #f8fafc; padding: 16px; text-align: center; font-size: 12px; color: #94a3b8; border-top: 1px solid #e2e8f0;">
                &copy; AI CHATBOT. All rights reserved.
              </div>
            </div>
          </body>
        </html>
        """

        message = MIMEMultipart("alternative")
        message["Subject"] = "You're invited to join our platform"
        message["From"] = f"AI CHATBOT <{sender_email}>"
        message["To"] = recipient_email

        part = MIMEText(html_content, "html")
        message.attach(part)

        server = smtplib.SMTP("smtp.gmail.com", 587)
        server.starttls()
        server.login(sender_email, sender_password)
        server.sendmail(sender_email, recipient_email, message.as_string())
        server.quit()
        logging.info(f"Invite email sent via SMTP to {recipient_email}")
        return True

    except Exception as e:
        logging.error(f"Failed to send invite email via SMTP to {recipient_email}: {e}")
        return False

def send_handoff_notification_email(company_id, conversation, chatbot_id):
    """
    Sends an email notification to all staff members of a company 
    when a customer requests to speak with a real human.
    """
    try:
        from app.database.user_repository import get_users_by_company
        users = get_users_by_company(company_id)
        
        # Only notify active admins and members
        staff_emails = [u.get("email") for u in users if u.get("email") and u.get("status") == "active"]
        
        if not staff_emails:
            logging.warning(f"No active staff found for company_id={company_id} to send handoff notification.")
            return False

        sender_email = os.getenv("SMTP_SENDER_EMAIL")
        sender_password = os.getenv("SMTP_APP_PASSWORD")

        if not sender_email or not sender_password:
            logging.warning("SMTP credentials missing in .env. Handoff notification email not sent.")
            return False

        customer_identifier = conversation.get("customer_phone") or conversation.get("customer_name") or conversation.get("platform_user_id") or "A customer"
        channel = (conversation.get("source_channel") or "Unknown").capitalize()
        
        subject = f"Action Required: Customer Handoff Request on {channel}"
        frontend_url = os.getenv("FRONTEND_URL", "http://localhost:5000") # Replace with actual logic to get frontend URL if needed
        conversation_url = f"{frontend_url}/conversations.html?bot_id={chatbot_id}&conversation_id={conversation.get('id')}"

        html_content = f"""
        <html>
          <body style="font-family: Arial, sans-serif; background-color: #f4f4f5; padding: 40px 0; margin: 0; color: #333;">
            <div style="max-width: 500px; margin: 0 auto; background: white; border-radius: 12px; overflow: hidden; box-shadow: 0 4px 15px rgba(0,0,0,0.1);">
              <div style="background-color: #f59e0b; padding: 24px; text-align: center;">
                <h2 style="color: white; margin: 0; font-size: 24px;">AI CHATBOT - Action Required</h2>
              </div>
              <div style="padding: 32px;">
                <h3 style="margin-top: 0; font-size: 20px; color: #1e293b;">Customer Handoff Request</h3>
                <p style="font-size: 16px; line-height: 1.5; color: #475569;">
                  Hello Team,<br><br>
                  <strong>{customer_identifier}</strong> has requested to speak with a real staff member on <strong>{channel}</strong>.
                </p>
                <div style="text-align: center; margin: 32px 0;">
                  <a href="{conversation_url}" style="background-color: #3b82f6; color: white; padding: 14px 36px; border-radius: 8px; text-decoration: none; font-size: 16px; font-weight: bold; display: inline-block;">View Conversation</a>
                </div>
                <p style="font-size: 13px; color: #94a3b8; margin-top: 24px;">
                  Please reply to them as soon as possible via the Inbox dashboard.
                </p>
              </div>
              <div style="background-color: #f8fafc; padding: 16px; text-align: center; font-size: 12px; color: #94a3b8; border-top: 1px solid #e2e8f0;">
                &copy; AI CHATBOT. All rights reserved.
              </div>
            </div>
          </body>
        </html>
        """

        server = smtplib.SMTP("smtp.gmail.com", 587)
        server.starttls()
        server.login(sender_email, sender_password)

        for email in staff_emails:
            message = MIMEMultipart("alternative")
            message["Subject"] = subject
            message["From"] = f"AI CHATBOT <{sender_email}>"
            message["To"] = email
            part = MIMEText(html_content, "html")
            message.attach(part)
            server.sendmail(sender_email, email, message.as_string())

        server.quit()
        logging.info(f"Handoff notification email sent successfully to {len(staff_emails)} staff members.")
        return True

    except Exception as e:
        logging.error(f"Failed to send handoff notification email: {e}")
        return False


# The other senders here inherit the process-wide socket timeout, which is None
# by default: a hung SMTP server would pin the caller forever. This one runs on
# a daemon thread, so a hang leaks a thread instead of a request - bound it.
SUPPORT_NOTIFICATION_SMTP_TIMEOUT_SECONDS = 20


def send_tenant_support_request_notification_email(
    recipient_email,
    *,
    request_id,
    company_id,
    category,
    status,
    submitted_at,
    redacted_description,
):
    """
    Tells the platform support inbox that a tenant escalated an FAQ, so a human
    picks the ticket up instead of it waiting to be noticed in the admin console.

    Every field here is caller-supplied and already redacted; `redacted_description`
    is the only free text and is HTML-escaped because passing FORBIDDEN_TERMS says
    nothing about markup. Returns False rather than raising - the caller has
    already created the ticket and must not be able to fail because of this.
    """
    sender_email = os.getenv("SMTP_SENDER_EMAIL")
    sender_password = os.getenv("SMTP_APP_PASSWORD")

    if not sender_email or not sender_password:
        logging.warning(
            "SMTP credentials missing in .env. Tenant support notification not sent."
        )
        return False

    safe_description = html.escape(str(redacted_description))
    subject = f"New tenant support request #{request_id} ({category})"

    html_content = f"""
    <html>
      <body style="font-family: Arial, sans-serif; background-color: #f4f4f5; padding: 40px 0; margin: 0; color: #333;">
        <div style="max-width: 560px; margin: 0 auto; background: white; border-radius: 12px; overflow: hidden; box-shadow: 0 4px 15px rgba(0,0,0,0.1);">
          <div style="background-color: #f59e0b; padding: 24px; text-align: center;">
            <h2 style="color: white; margin: 0; font-size: 24px;">AI CHATBOT - Support Escalation</h2>
          </div>
          <div style="padding: 32px;">
            <h3 style="margin-top: 0; font-size: 20px; color: #1e293b;">A tenant submitted a support request</h3>
            <table style="width: 100%; border-collapse: collapse; font-size: 15px; color: #475569;">
              <tr><td style="padding: 6px 0; color: #64748b;">Request ID</td><td style="padding: 6px 0;"><strong>{request_id}</strong></td></tr>
              <tr><td style="padding: 6px 0; color: #64748b;">Category</td><td style="padding: 6px 0;"><strong>{category}</strong></td></tr>
              <tr><td style="padding: 6px 0; color: #64748b;">Status</td><td style="padding: 6px 0;"><strong>{status}</strong></td></tr>
              <tr><td style="padding: 6px 0; color: #64748b;">Company ID</td><td style="padding: 6px 0;"><strong>{company_id}</strong></td></tr>
              <tr><td style="padding: 6px 0; color: #64748b;">Submitted (UTC)</td><td style="padding: 6px 0;"><strong>{submitted_at}</strong></td></tr>
            </table>
            <div style="background-color: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px; padding: 16px; margin: 24px 0; font-size: 14px; line-height: 1.6; color: #334155; white-space: pre-wrap;">{safe_description}</div>
            <p style="font-size: 13px; color: #94a3b8; margin-top: 24px;">
              Open request {request_id} in the platform admin console to review it. This
              notice carries no requester identity and no customer conversation content.
            </p>
          </div>
          <div style="background-color: #f8fafc; padding: 16px; text-align: center; font-size: 12px; color: #94a3b8; border-top: 1px solid #e2e8f0;">
            &copy; AI CHATBOT. All rights reserved.
          </div>
        </div>
      </body>
    </html>
    """

    try:
        message = MIMEMultipart("alternative")
        message["Subject"] = subject
        message["From"] = f"AI CHATBOT <{sender_email}>"
        message["To"] = recipient_email
        message.attach(MIMEText(html_content, "html"))

        server = smtplib.SMTP(
            "smtp.gmail.com", 587, timeout=SUPPORT_NOTIFICATION_SMTP_TIMEOUT_SECONDS
        )
        server.starttls()
        server.login(sender_email, sender_password)
        server.sendmail(sender_email, recipient_email, message.as_string())
        server.quit()
        logging.info(
            f"Tenant support notification sent for request {request_id}."
        )
        return True

    except Exception as e:
        logging.error(
            f"Failed to send tenant support notification for request {request_id}: {e}"
        )
        return False
def send_tenant_support_reply_notification_email(recipient_email, *, request_id):
    """
    Tells a tenant requester that platform staff replied, so the reply is read
    instead of waiting to be stumbled on in Support History.

    The signature is the guarantee: there is nowhere to put the reply, the
    subject, the title or the description, so no caller can leak ticket content
    into a mailbox. The notice is a nudge to open the app and nothing else -
    which is what lets the support page keep promising that internal notes are
    not exposed. Returns False rather than raising; the reply row already
    exists and must not be able to fail because of this.
    """
    sender_email = os.getenv("SMTP_SENDER_EMAIL")
    sender_password = os.getenv("SMTP_APP_PASSWORD")

    if not sender_email or not sender_password:
        logging.warning(
            "SMTP credentials missing in .env. Tenant reply notice not sent."
        )
        return False

    reference = html.escape(str(request_id))
    subject = f"A reply is waiting on your support request #{reference}"

    app_url = (os.getenv("FRONTEND_URL") or "").strip().rstrip("/")
    if app_url:
        safe_url = html.escape(app_url, quote=True)
        action = f"""
            <div style="text-align: center; margin: 32px 0;">
              <a href="{safe_url}/support.html" style="background-color: #3e9c89; color: white; padding: 14px 36px; border-radius: 8px; text-decoration: none; font-size: 16px; font-weight: bold; display: inline-block;">Open Support</a>
            </div>
    """
    else:
        # No configured app URL, so no link at all. A half-built href is worse
        # than a sentence telling the reader where to look.
        action = ""

    html_content = f"""
    <html>
      <body style="font-family: Arial, sans-serif; background-color: #f4f4f5; padding: 40px 0; margin: 0; color: #333;">
        <div style="max-width: 560px; margin: 0 auto; background: white; border-radius: 12px; overflow: hidden; box-shadow: 0 4px 15px rgba(0,0,0,0.1);">
          <div style="background-color: #3e9c89; padding: 24px; text-align: center;">
            <h2 style="color: white; margin: 0; font-size: 24px;">AI CHATBOT - Support</h2>
          </div>
          <div style="padding: 32px;">
            <h3 style="margin-top: 0; font-size: 20px; color: #1e293b;">A reply is waiting</h3>
            <p style="font-size: 16px; line-height: 1.6; color: #475569;">
              Our support team has replied to your support request
              <strong>#{reference}</strong>. Open the Support page in your
              dashboard to read it.
            </p>{action}
            <p style="font-size: 13px; color: #94a3b8; margin-top: 24px;">
              This notice deliberately carries no part of your request or of the
              reply. Everything is in the app.
            </p>
          </div>
          <div style="background-color: #f8fafc; padding: 16px; text-align: center; font-size: 12px; color: #94a3b8; border-top: 1px solid #e2e8f0;">
            &copy; AI CHATBOT. All rights reserved.
          </div>
        </div>
      </body>
    </html>
    """

    try:
        message = MIMEMultipart("alternative")
        message["Subject"] = subject
        message["From"] = f"AI CHATBOT <{sender_email}>"
        message["To"] = recipient_email
        message.attach(MIMEText(html_content, "html"))

        server = smtplib.SMTP(
            "smtp.gmail.com", 587, timeout=SUPPORT_NOTIFICATION_SMTP_TIMEOUT_SECONDS
        )
        server.starttls()
        server.login(sender_email, sender_password)
        server.sendmail(sender_email, recipient_email, message.as_string())
        server.quit()
        logging.info(f"Tenant reply notice sent for request {request_id}.")
        return True

    except Exception as e:
        logging.error(
            f"Failed to send tenant reply notice for request {request_id}: {e}"
        )
        return False

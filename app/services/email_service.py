import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import logging
import datetime

def send_otp_email(recipient_email, otp_code, recipient_name="User"):
    """
    Sends an OTP verification code via Gmail SMTP.
    """
    sender_email = os.getenv("SMTP_SENDER_EMAIL")
    sender_password = os.getenv("SMTP_APP_PASSWORD")

    if not sender_email or not sender_password:
        logging.warning("SMTP credentials missing in .env. OTP email not sent.")
        return False

    subject = "Verify Your Account - AI CHATBOT"
    
    # Premium HTML email template
    html_content = f"""
    <html>
      <body style="font-family: Arial, sans-serif; background-color: #f4f4f5; padding: 40px 0; margin: 0; color: #333;">
        <div style="max-width: 500px; margin: 0 auto; background: white; border-radius: 12px; overflow: hidden; box-shadow: 0 4px 15px rgba(0,0,0,0.1);">
          <div style="background-color: #3b82f6; padding: 24px; text-align: center;">
            <h2 style="color: white; margin: 0; font-size: 24px;">AI CHATBOT</h2>
          </div>
          <div style="padding: 32px;">
            <h3 style="margin-top: 0; font-size: 20px; color: #1e293b;">Email Verification</h3>
            <p style="font-size: 16px; line-height: 1.5; color: #475569;">
              Hi {recipient_name},<br><br>
              Thank you for registering. To complete your account setup, please use the verification code below:
            </p>
            <div style="background-color: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px; padding: 16px; text-align: center; margin: 24px 0;">
              <span style="font-size: 32px; font-weight: bold; letter-spacing: 4px; color: #3b82f6;">{otp_code}</span>
            </div>
            <p style="font-size: 14px; color: #64748b;">
              This code will expire in 10 minutes. If you didn't request this, you can safely ignore this email.
            </p>
          </div>
          <div style="background-color: #f8fafc; padding: 16px; text-align: center; font-size: 12px; color: #94a3b8; border-top: 1px solid #e2e8f0;">
            &copy; {datetime.datetime.now().year if 'datetime' in globals() else 2026} AI CHATBOT. All rights reserved.
          </div>
        </div>
      </body>
    </html>
    """

    message = MIMEMultipart("alternative")
    message["Subject"] = subject
    message["From"] = f"AI CHATBOT <{sender_email}>"
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

    subject = "Reset Your Password - AI CHATBOT"
    
    html_content = f"""
    <html>
      <body style="font-family: Arial, sans-serif; background-color: #f4f4f5; padding: 40px 0; margin: 0; color: #333;">
        <div style="max-width: 500px; margin: 0 auto; background: white; border-radius: 12px; overflow: hidden; box-shadow: 0 4px 15px rgba(0,0,0,0.1);">
          <div style="background-color: #ef4444; padding: 24px; text-align: center;">
            <h2 style="color: white; margin: 0; font-size: 24px;">AI CHATBOT</h2>
          </div>
          <div style="padding: 32px;">
            <h3 style="margin-top: 0; font-size: 20px; color: #1e293b;">Password Reset Request</h3>
            <p style="font-size: 16px; line-height: 1.5; color: #475569;">
              Hi {recipient_name},<br><br>
              We received a request to reset your account password. Please use the verification code below to complete the reset process:
            </p>
            <div style="background-color: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px; padding: 16px; text-align: center; margin: 24px 0;">
              <span style="font-size: 32px; font-weight: bold; letter-spacing: 4px; color: #ef4444;">{otp_code}</span>
            </div>
            <p style="font-size: 14px; color: #64748b;">
              This code will expire in 10 minutes. If you did not request a password reset, you can safely ignore this email and your password will remain unchanged.
            </p>
          </div>
          <div style="background-color: #f8fafc; padding: 16px; text-align: center; font-size: 12px; color: #94a3b8; border-top: 1px solid #e2e8f0;">
            &copy; {datetime.datetime.now().year if 'datetime' in globals() else 2026} AI CHATBOT. All rights reserved.
          </div>
        </div>
      </body>
    </html>
    """

    message = MIMEMultipart("alternative")
    message["Subject"] = subject
    message["From"] = f"AI CHATBOT <{sender_email}>"
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

def send_provider_failover_email(company_id, primary_provider, backup_provider, chatbot_id):
    """
    Sends an email notification to all staff members of a company 
    when the primary AI provider fails and falls back to a backup provider.
    """
    try:
        from app.database.user_repository import get_users_by_company
        users = get_users_by_company(company_id)
        
        staff_emails = [u.get("email") for u in users if u.get("email") and u.get("status") == "active"]
        
        if not staff_emails:
            logging.warning(f"No active staff found for company_id={company_id} to send failover notification.")
            return False

        sender_email = os.getenv("SMTP_SENDER_EMAIL")
        sender_password = os.getenv("SMTP_APP_PASSWORD")

        if not sender_email or not sender_password:
            logging.warning("SMTP credentials missing in .env. Failover notification email not sent.")
            return False

        subject = f"System Alert: AI Provider Failover Triggered"
        
        html_content = f"""
        <html>
          <body style="font-family: Arial, sans-serif; background-color: #f4f4f5; padding: 40px 0; margin: 0; color: #333;">
            <div style="max-width: 500px; margin: 0 auto; background: white; border-radius: 12px; overflow: hidden; box-shadow: 0 4px 15px rgba(0,0,0,0.1);">
              <div style="background-color: #f59e0b; padding: 24px; text-align: center;">
                <h2 style="color: white; margin: 0; font-size: 24px;">AI CHATBOT - System Alert</h2>
              </div>
              <div style="padding: 32px;">
                <h3 style="margin-top: 0; color: #1f2937;">Provider Failover Triggered</h3>
                <p>Hello,</p>
                <p>Your primary AI provider (<strong>{primary_provider.upper()}</strong>) experienced a timeout or error while generating a response for Bot ID {chatbot_id}.</p>
                <p>To ensure high availability and prevent downtime, we have automatically routed the request to the backup provider (<strong>{backup_provider.upper()}</strong>).</p>
                <p>You may want to check your primary provider's status page. No immediate action is required.</p>
                <hr style="border: 0; border-top: 1px solid #e5e7eb; margin: 24px 0;">
                <p style="font-size: 12px; color: #9ca3af; text-align: center; margin: 0;">AI Chatbot System Notification</p>
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
        logging.info(f"Failover notification email sent successfully to {len(staff_emails)} staff members.")
        return True

    except Exception as e:
        logging.error(f"Failed to send failover notification email: {e}")
        return False
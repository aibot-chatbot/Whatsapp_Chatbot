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

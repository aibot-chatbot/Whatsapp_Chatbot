"""receipt_email_service.py - Purchase receipt emails (plan purchases and AI-credit top-ups).

Kept out of email_service.py on purpose: that file is at its size cap, and the SMTP
sender in here is the piece expected to be swapped for another provider later, so
replacing it means editing one small file. Callers hand over already-formatted
(label, value) rows; this module only renders and sends.
"""

import datetime
import html
import logging
import os
import re
import smtplib
import ssl
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from app.services.email_service import SUPPORT_NOTIFICATION_SMTP_TIMEOUT_SECONDS

_MYT = datetime.timezone(datetime.timedelta(hours=8))  # Malaysia has no DST
_SINGLE_MAILBOX = re.compile(r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+")


def is_single_mailbox(address):
    """True only for one plain ASCII address: no whitespace, control characters,
    list separators or display name.

    Recipients come from the users table, but they end up in mail headers, so a
    stored value containing a line break must never be able to add a Bcc. ASCII
    only, because a non-ASCII address passes a looser check and then fails at
    sendmail, after the owner fallback has already been ruled out.
    """
    return isinstance(address, str) and _SINGLE_MAILBOX.fullmatch(address) is not None


def format_sen(sen):
    """Exact 'RM 1,234.56' from integer sen; money never passes through a float."""
    sen = int(sen or 0)
    whole, cents = divmod(abs(sen), 100)
    return f"{'-' if sen < 0 else ''}RM {whole:,}.{cents:02d}"


def format_micro_myr(micro):
    """Exact 'RM 10.50' from integer micro-MYR (1 RM = 1,000,000), rounded half up to the sen."""
    return format_sen((int(micro or 0) + 5000) // 10000)


def format_paid_at(value):
    """'30 Sep 2026, 1:12 pm MYT' from an ISO-8601 timestamp; the raw text if unparseable."""
    if not value:
        return "-"
    try:
        moment = datetime.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return str(value)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=datetime.timezone.utc)
    moment = moment.astimezone(_MYT)
    meridiem = "am" if moment.hour < 12 else "pm"
    return f"{moment.day} {moment:%b %Y}, {moment.hour % 12 or 12}:{moment:%M} {meridiem} MYT"


def render_receipt_email(rows, *, order_reference, recipient_name, summary, notice, action_url=None):
    """Return (subject, html, text) for a receipt.

    Every value is escaped before it reaches the HTML: plan and company names
    are stored user-controlled text. Rows with an empty value are dropped.
    """
    order_reference = str(order_reference or "")
    rows = [(str(label), str(value)) for label, value in rows if value]
    notice = str(notice or "")
    name = str(recipient_name or "there")

    table_rows = "".join(
        '<tr><td style="padding:10px 0;color:#64748b;font-size:14px;border-bottom:1px solid #e2e8f0;">'
        f"{html.escape(label)}</td>"
        '<td style="padding:10px 0;color:#1e293b;font-size:15px;font-weight:600;text-align:right;'
        f'border-bottom:1px solid #e2e8f0;">{html.escape(value)}</td></tr>'
        for label, value in rows
    )
    action_block = ""
    if action_url:
        action_block = (
            '<p style="margin:26px 0 0;"><a href="' + html.escape(str(action_url)) + '" '
            'style="display:inline-block;background:#22D3EE;color:#04121a;text-decoration:none;'
            'padding:13px 26px;border-radius:10px;font-weight:600;font-size:15px;">View in billing</a></p>'
        )
    html_content = f"""
    <html>
      <body style="font-family: Arial, sans-serif; background-color: #f4f4f5; padding: 40px 0; margin: 0; color: #333;">
        <div style="max-width: 520px; margin: 0 auto; background: white; border-radius: 12px; overflow: hidden; box-shadow: 0 4px 15px rgba(0,0,0,0.1);">
          <div style="background-color: #060A12; padding: 24px; text-align: center;">
            <h2 style="color: #22D3EE; margin: 0; font-size: 24px; letter-spacing: -0.5px;">Omnexa</h2>
          </div>
          <div style="padding: 32px;">
            <p style="margin:0 0 6px;font-size:12px;letter-spacing:.08em;text-transform:uppercase;color:#0E7490;font-weight:700;">Payment receipt</p>
            <h3 style="margin-top: 0; font-size: 20px; color: #1e293b;">Thank you for your purchase</h3>
            <p style="font-size: 16px; line-height: 1.55; color: #475569;">Hi {html.escape(name)}, {html.escape(summary)} Keep this email as your record.</p>
            <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="margin-top:18px;border-top:1px solid #e2e8f0;">{table_rows}</table>
            {action_block}
            <p style="font-size: 13px; color: #64748b; margin-top:28px;">{html.escape(notice)}</p>
          </div>
          <div style="background-color: #f8fafc; padding: 16px; text-align: center; font-size: 12px; color: #94a3b8; border-top: 1px solid #e2e8f0;">
            &copy; {datetime.datetime.now().year} Omnexa. All rights reserved.
          </div>
        </div>
      </body>
    </html>
    """
    text_content = "\n".join(
        [f"Hi {name}, {summary}", ""] + [f"{label}: {value}" for label, value in rows] + ["", notice]
    )
    subject = " ".join(f"Omnexa receipt - {order_reference}".split())  # no line breaks in a header
    return subject, html_content, text_content


def _deliver(message_obj, sender_email, sender_password, recipients, what):
    """Hand one built message to the SMTP server. True on success, never raises."""
    try:
        # Bounded: callers run inside payment callbacks and chat replies, and a stalled
        # server must not hold those requests open. The `with` closes the socket even when
        # a step fails. starttls() with no context does not verify the server's certificate,
        # which would send the SMTP password to whoever answers on the port.
        with smtplib.SMTP("smtp.gmail.com", 587, timeout=SUPPORT_NOTIFICATION_SMTP_TIMEOUT_SECONDS) as server:
            server.starttls(context=ssl.create_default_context())
            server.login(sender_email, sender_password)
            server.sendmail(sender_email, recipients, message_obj.as_string())
        return True
    except Exception as e:
        # Type only: SMTPRecipientsRefused carries the recipient address.
        logging.error("Failed to send %s email (%s)", what, type(e).__name__)
        return False


def send_receipt_email(
    recipient_email, *, order_reference, rows, recipient_name, summary, notice,
    cc_email=None, action_url=None,
):
    """Email a receipt. Returns True when handed to the SMTP server.

    Callers must treat False as "not delivered" and carry on: the payment and
    its in-app notice are already recorded, and mail trouble must never undo them.
    """
    sender_email = os.getenv("SMTP_SENDER_EMAIL")
    sender_password = os.getenv("SMTP_APP_PASSWORD")
    if not sender_email or not sender_password:
        logging.warning("SMTP credentials missing in .env. Receipt email not sent.")
        return False
    if not is_single_mailbox(recipient_email) or (cc_email and not is_single_mailbox(cc_email)):
        logging.warning("Receipt email skipped: recipient is not a single plain address.")
        return False

    subject, html_content, text_content = render_receipt_email(
        rows, order_reference=order_reference, recipient_name=recipient_name,
        summary=summary, notice=notice, action_url=action_url,
    )
    message_obj = MIMEMultipart("alternative")
    message_obj["Subject"] = subject
    message_obj["From"] = f"Omnexa <{sender_email}>"
    message_obj["To"] = recipient_email
    if cc_email:
        message_obj["Cc"] = cc_email
    message_obj.attach(MIMEText(text_content, "plain"))
    message_obj.attach(MIMEText(html_content, "html"))

    sent = _deliver(message_obj, sender_email, sender_password,
                    [recipient_email] + ([cc_email] if cc_email else []), "receipt")
    if sent:
        logging.info("Receipt email sent (order=%s)", order_reference)
    return sent


def send_notice_email(
    recipient_email, *, title, message, label, footer, recipient_name="there",
    action_label=None, action_url=None,
):
    """Email an account owner a short notice with an optional button. True when handed to SMTP.

    Callers must treat False as "not delivered" and carry on. Every value is escaped, and
    the subject is collapsed to one line so a title can never add a header.
    """
    sender_email = os.getenv("SMTP_SENDER_EMAIL")
    sender_password = os.getenv("SMTP_APP_PASSWORD")
    if not sender_email or not sender_password:
        logging.warning("SMTP credentials missing in .env. Notice email not sent.")
        return False
    if not is_single_mailbox(recipient_email):
        logging.warning("Notice email skipped: recipient is not a single plain address.")
        return False

    name = str(recipient_name or "there")
    button = ""
    if action_label and action_url:
        button = (
            '<p style="margin:26px 0 0;"><a href="' + html.escape(str(action_url)) + '" '
            'style="display:inline-block;background:#22D3EE;color:#04121a;text-decoration:none;'
            'padding:13px 26px;border-radius:10px;font-weight:600;font-size:15px;">'
            + html.escape(str(action_label)) + "</a></p>"
        )
    html_content = f"""
    <html>
      <body style="font-family: Arial, sans-serif; background-color: #f4f4f5; padding: 40px 0; margin: 0; color: #333;">
        <div style="max-width: 520px; margin: 0 auto; background: white; border-radius: 12px; overflow: hidden; box-shadow: 0 4px 15px rgba(0,0,0,0.1);">
          <div style="background-color: #060A12; padding: 24px; text-align: center;">
            <h2 style="color: #22D3EE; margin: 0; font-size: 24px; letter-spacing: -0.5px;">Omnexa</h2>
          </div>
          <div style="padding: 32px;">
            <p style="margin:0 0 6px;font-size:12px;letter-spacing:.08em;text-transform:uppercase;color:#0E7490;font-weight:700;">{html.escape(str(label))}</p>
            <h3 style="margin-top: 0; font-size: 20px; color: #1e293b;">{html.escape(str(title))}</h3>
            <p style="font-size: 16px; line-height: 1.55; color: #475569;">Hi {html.escape(name)},<br><br>{html.escape(str(message))}</p>
            {button}
            <p style="font-size: 13px; color: #64748b; margin-top:28px;">{html.escape(str(footer))}</p>
          </div>
          <div style="background-color: #f8fafc; padding: 16px; text-align: center; font-size: 12px; color: #94a3b8; border-top: 1px solid #e2e8f0;">
            &copy; {datetime.datetime.now().year} Omnexa. All rights reserved.
          </div>
        </div>
      </body>
    </html>
    """
    text_lines = [f"Hi {name},", "", str(message)]
    if action_label and action_url:
        text_lines += ["", f"{action_label}: {action_url}"]
    text_lines += ["", str(footer)]

    message_obj = MIMEMultipart("alternative")
    message_obj["Subject"] = " ".join(f"Omnexa: {title}".split())
    message_obj["From"] = f"Omnexa <{sender_email}>"
    message_obj["To"] = recipient_email
    message_obj.attach(MIMEText("\n".join(text_lines), "plain"))
    message_obj.attach(MIMEText(html_content, "html"))
    return _deliver(message_obj, sender_email, sender_password, [recipient_email], "notice")

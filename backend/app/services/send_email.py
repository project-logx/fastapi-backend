import os
import secrets
import hashlib
from brevo import Brevo
from brevo.transactional_emails import SendTransacEmailRequestSender, SendTransacEmailRequestToItem
from dotenv import load_dotenv
from app.constants import (
    PASSWORD_CHANGE_SUCCESS_EMAIL_HTML_TEMPLATE,
    VERIFICATION_EMAIL_HTML_TEMPLATE,
    PASSWORD_RESET_EMAIL_HTML_TEMPLATE
)
from app.config import settings
load_dotenv()


def send_verification_email(token: str,email:str) -> None:

    client  = Brevo(api_key=os.getenv("BREVO_API_KEY"))
    sender=SendTransacEmailRequestSender(
        name="LogX Team",
        email="support@logxapp.in",
    )
    to=SendTransacEmailRequestToItem(
        email=email,
    )
    html_content = build_verification_email_html(token)
    try:
        client.transactional_emails.send_transac_email(html_content=html_content, sender=sender, to=[to], subject="Verify your email for LogX")
        print(f"Verification email sent to {email} using Brevo API")
    except Exception as e:
        print(f"Failed to send verification email to {email} using Brevo API: {e}")
        print(f"Email verification link for {email}: {verification_link(token)}")
    # EMAIL_USER = os.getenv("SMTP_USER", "").strip()
    # EMAIL_PASSWORD = os.getenv("SMTP_PASSWORD", "").strip()

    # to_email=email

    # message = MIMEMultipart("alternative")
    # message["Subject"]="Verify your email for LogX"
    # message["From"]=EMAIL_USER
    # message["To"]=to_email

    # html_content = html_body(token)

    # message.attach(MIMEText(html_content, "html"))

    # try:
    #     print(f"Attempting to send verification email to {to_email} using SMTP server...")
    #     server = smtplib.SMTP_SSL("smtp.titan.email", 465)
    #     # server.starttls()
    #     # print("SMTP connection established. Logging in...")
    #     server.login(EMAIL_USER, EMAIL_PASSWORD)
    #     print("Logged in to SMTP server. Sending email...")
    #     server.sendmail(EMAIL_USER, to_email, message.as_string())
    #     server.quit()
    #     print(f"Verification email sent to {to_email}")
    # except Exception as e:
    #     print(f"Failed to send verification email to {to_email}: {e}")


def send_password_change_success_email(email: str) -> None:

    client = Brevo(api_key=os.getenv("BREVO_API_KEY"))
    sender = SendTransacEmailRequestSender(
        name="LogX Team",
        email="support@logxapp.in",
    )
    to = SendTransacEmailRequestToItem(
        email=email,
    )
    html_content = build_password_change_success_email_html(email)
    try:
        client.transactional_emails.send_transac_email(
            html_content=html_content,
            sender=sender,
            to=[to],
            subject="Password changed for LogX",
        )
        print(f"Password change confirmation email sent to {email} using Brevo API")
    except Exception as e:
        print(f"Failed to send password change confirmation email to {email} using Brevo API: {e}")


def send_password_reset_email(token: str, email: str) -> None:
    client = Brevo(api_key=os.getenv("BREVO_API_KEY"))
    sender = SendTransacEmailRequestSender(
        name="LogX Team",
        email="support@logxapp.in",
    )
    to = SendTransacEmailRequestToItem(
        email=email,
    )
    html_content = build_password_reset_email_html(token)
    try:
        client.transactional_emails.send_transac_email(
            html_content=html_content,
            sender=sender,
            to=[to],
            subject="Reset your LogX password",
        )
        print(f"Password reset email sent to {email} using Brevo API")
    except Exception as e:
        print(f"Failed to send password reset email to {email} using Brevo API: {e}")
        print(f"Password reset link for {email}: {password_reset_link(token)}")




def build_verification_email_html(token: str) -> str:
    link = verification_link(token)
    return VERIFICATION_EMAIL_HTML_TEMPLATE.format(link=link)


def build_password_change_success_email_html(email: str) -> str:
    return PASSWORD_CHANGE_SUCCESS_EMAIL_HTML_TEMPLATE.format(email=email)


def build_password_reset_email_html(token: str) -> str:
    link = password_reset_link(token)
    return PASSWORD_RESET_EMAIL_HTML_TEMPLATE.format(link=link)


def verification_link(token: str) -> str:
    frontend_url=settings.frontend_base_url
    return f"{frontend_url}/verify?token={token}" 

def password_reset_link(token: str) -> str:
    frontend_url=settings.frontend_base_url
    return f"{frontend_url}/reset-password?token={token}"


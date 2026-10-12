import smtplib
from email.message import EmailMessage

from app.core.config import settings
from app.utils.logger import logger


def send_password_reset_email(to_email: str, reset_url: str) -> None:
    """Send a password reset email using SMTP when the app is in production."""
    if settings.ENVIRONMENT != "production":
        return

    missing = [
        name
        for name, value in {
            "SMTP_HOST": settings.SMTP_HOST,
            "SMTP_USERNAME": settings.SMTP_USERNAME,
            "SMTP_PASSWORD": settings.SMTP_PASSWORD,
            "SMTP_FROM_EMAIL": settings.SMTP_FROM_EMAIL,
        }.items()
        if not value
    ]
    if missing:
        raise RuntimeError(
            "SMTP is not configured for production password reset emails. Missing: "
            + ", ".join(missing)
        )

    message = EmailMessage()
    message["Subject"] = "Reset your Asiatech Sentiment password"
    message["From"] = settings.SMTP_FROM_EMAIL
    message["To"] = to_email
    message.set_content(
        "Use the following link to reset your password:\n\n"
        f"{reset_url}\n\n"
        "If you did not request this, you can ignore this email."
    )

    try:
        with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT) as smtp:
            if settings.SMTP_USE_TLS:
                smtp.starttls()
            smtp.login(settings.SMTP_USERNAME, settings.SMTP_PASSWORD)
            smtp.send_message(message)
    except smtplib.SMTPException as exc:
        logger.exception("Failed to send password reset email to %s", to_email)
        raise RuntimeError("Password reset email could not be sent. Please try again later.") from exc

    logger.info(f"Password reset email sent to {to_email}")

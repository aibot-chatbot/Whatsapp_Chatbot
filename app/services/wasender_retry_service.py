import logging
import threading
import time

from app.database.message_repository import (
    get_retryable_failed_wasender_messages,
    mark_message_retrying,
    mark_message_sent_after_retry,
    mark_message_retry_failed,
)
from app.database.wasender_channel_repository import get_wasender_channels_by_chatbot
from app.services.wasender_service import send_wasender_text_message


MAX_RETRIES = 3
RETRY_DELAY_SECONDS = 60
CHECK_INTERVAL_SECONDS = 60

_worker_started = False


def get_active_wasender_channel(chatbot_id: int):
    channels = get_wasender_channels_by_chatbot(chatbot_id)

    for channel in channels:
        if channel.get("is_active") and channel.get("connection_status") == "connected":
            return channel

    return None


def retry_failed_wasender_messages_once():
    """
    Retry only 1 failed Wasender message per cycle.
    This is safer for WasenderAPI free trial rate limit.
    """
    failed_messages = get_retryable_failed_wasender_messages(
        limit=1,
        max_retries=MAX_RETRIES,
    )

    if not failed_messages:
        return 0

    retried_count = 0

    for message in failed_messages:
        message_id = message.get("id")
        message_text = message.get("message_text")
        retry_count = int(message.get("retry_count") or 0) + 1
        conversation = message.get("conversation") or {}

        chatbot_id = conversation.get("chatbot_id")
        customer_phone = conversation.get("customer_phone")

        if not message_id or not message_text or not chatbot_id or not customer_phone:
            # The record holds message_text and, via conversation,
            # customer_phone. Name the missing fields instead - it is both
            # safer and more useful than dumping the row.
            missing = [
                name
                for name, value in (
                    ("id", message_id),
                    ("message_text", message_text),
                    ("chatbot_id", chatbot_id),
                    ("customer_phone", customer_phone),
                )
                if not value
            ]
            logging.warning(
                "Wasender retry skipped invalid message: missing %s",
                ", ".join(missing),
            )
            continue

        channel = get_active_wasender_channel(chatbot_id)

        if not channel:
            mark_message_retry_failed(
                message_id=message_id,
                retry_count=retry_count,
                error_message="No active WasenderAPI channel found for retry.",
                max_retries=MAX_RETRIES,
                delay_seconds=RETRY_DELAY_SECONDS,
            )
            continue

        api_key = channel.get("api_key")

        logging.info(
            f"Retrying Wasender message_id={message_id}, "
            f"retry_count={retry_count}, customer={customer_phone}"
        )

        mark_message_retrying(message_id)

        send_result = send_wasender_text_message(
            api_key=api_key,
            to=customer_phone,
            text=message_text,
        )

        if send_result and send_result.get("success"):
            mark_message_sent_after_retry(
                message_id=message_id,
                retry_count=retry_count,
            )

            logging.info(f"Wasender retry success for message_id={message_id}")

        else:
            error_message = (
                send_result.get("error")
                if send_result
                else "Wasender retry failed."
            )

            mark_message_retry_failed(
                message_id=message_id,
                retry_count=retry_count,
                error_message=error_message,
                max_retries=MAX_RETRIES,
                delay_seconds=RETRY_DELAY_SECONDS,
            )

            logging.warning(
                f"Wasender retry failed for message_id={message_id}: {error_message}"
            )

        retried_count += 1

    return retried_count


def wasender_retry_loop():
    logging.info("Wasender retry worker started.")

    while True:
        try:
            retry_failed_wasender_messages_once()

        except Exception as e:
            logging.error(f"Wasender retry worker error: {e}")

        time.sleep(CHECK_INTERVAL_SECONDS)


def start_wasender_retry_worker():
    global _worker_started

    if _worker_started:
        logging.info("Wasender retry worker already running.")
        return

    worker = threading.Thread(
        target=wasender_retry_loop,
        daemon=True,
    )

    worker.start()
    _worker_started = True
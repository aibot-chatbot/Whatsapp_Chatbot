import logging
import threading
import time

from app.database.message_repository import (
    get_retryable_failed_wasender_messages,
    mark_message_retrying,
    mark_message_sent_after_retry,
    mark_message_retry_failed,
)
from app.services.wasender_service import send_wasender_text_message
from app.services.channel_delivery_service import get_bound_channel, ChannelDeliveryError, delivery_accepted
from app.database.agent_action_repository import is_conversation_escalated
from app.services.conversation_delivery_lock import conversation_delivery_lock


MAX_RETRIES = 3
RETRY_DELAY_SECONDS = 60
CHECK_INTERVAL_SECONDS = 60

_worker_started = False


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

        if is_conversation_escalated(conversation.get("id"), chatbot_id, conversation=conversation):
            continue
        if not mark_message_retrying(message_id):
            continue

        # The scan can be stale. Only the worker holding the claim may change
        # delivery state, and it must check the original channel after claiming.
        try:
            channel = get_bound_channel(conversation)
        except ChannelDeliveryError:
            channel = None

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
            "Retrying Wasender message_id=%s, retry_count=%s",
            message_id,
            retry_count,
        )

        with conversation_delivery_lock(conversation["id"]):
            if is_conversation_escalated(conversation["id"], chatbot_id, conversation=conversation):
                mark_message_retry_failed(
                    message_id=message_id,
                    retry_count=retry_count - 1,
                    error_message="Human handoff is active; automatic reply remains paused.",
                    max_retries=MAX_RETRIES,
                    delay_seconds=RETRY_DELAY_SECONDS,
                )
                continue

            send_result = send_wasender_text_message(
                api_key=api_key,
                to=customer_phone,
                text=message_text,
            )

        if delivery_accepted("wasender", send_result):
            mark_message_sent_after_retry(
                message_id=message_id,
                retry_count=retry_count,
            )

            logging.info(f"Wasender retry success for message_id={message_id}")

        else:
            # Pass the attempt we just made, not the cap. Passing MAX_RETRIES
            # makes mark_message_retry_failed take its permanent_failed branch on
            # the first miss, so MAX_RETRIES/RETRY_DELAY_SECONDS never apply.
            mark_message_retry_failed(
                message_id=message_id,
                retry_count=retry_count,
                error_message="Provider did not confirm delivery; review before retrying.",
                max_retries=MAX_RETRIES,
                delay_seconds=RETRY_DELAY_SECONDS,
            )

            if retry_count >= MAX_RETRIES:
                # The one send failure that needs a human: the retry budget is
                # spent and this reply will never reach the customer. Every
                # attempt before this one is a warning, so the report is raised
                # once per lost message instead of once per attempt.
                logging.error(
                    "Wasender reply permanently undelivered for message_id=%s after %s attempts",
                    message_id,
                    retry_count,
                )
            else:
                logging.warning(
                    "Wasender retry failed for message_id=%s", message_id
                )

        retried_count += 1

    return retried_count


def wasender_retry_loop():
    logging.info("Wasender retry worker started.")

    while True:
        try:
            retry_failed_wasender_messages_once()

        except Exception as e:
            # No exc_info here either: see wasender_routes.wasender_webhook_post.
            logging.error("Wasender retry worker error (%s)", type(e).__name__)

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

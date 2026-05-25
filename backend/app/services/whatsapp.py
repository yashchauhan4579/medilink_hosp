import logging
import requests
from app import database as db

logger = logging.getLogger(__name__)


def send_whatsapp_alert(message: str, image_path: str) -> dict:
    """Send alert with snapshot to WhatsApp via Green API. Supports multiple comma-separated recipients."""
    settings = db.get_all_settings()

    if settings.get("whatsapp_enabled") != "true":
        return {"status": "disabled", "detail": "WhatsApp notifications disabled"}

    instance_id = settings.get("whatsapp_instance_id", "")
    api_token = settings.get("whatsapp_api_token", "")
    phones_raw = settings.get("whatsapp_recipient_phone", "")

    if not all([instance_id, api_token, phones_raw]):
        return {"status": "error", "detail": "WhatsApp not configured (missing instance_id, api_token, or phone)"}

    phones = [p.strip() for p in phones_raw.split(",") if p.strip()]
    if not phones:
        return {"status": "error", "detail": "No recipient phone numbers configured"}

    url = f"https://api.greenapi.com/waInstance{instance_id}/sendFileByUpload/{api_token}"
    results = []

    for phone in phones:
        try:
            # Detect file type for correct MIME
            if image_path.endswith(".mp4"):
                fname, mime = "alert.mp4", "video/mp4"
            else:
                fname, mime = "alert.jpg", "image/jpeg"

            with open(image_path, "rb") as f:
                resp = requests.post(
                    url,
                    data={
                        "chatId": f"{phone}@c.us",
                        "caption": message,
                    },
                    files={"file": (fname, f, mime)},
                    timeout=60,
                )

            if resp.status_code == 200:
                logger.info(f"WhatsApp alert sent to {phone}: {message[:50]}...")
                results.append({"phone": phone, "status": "sent"})
            else:
                logger.error(f"WhatsApp send to {phone} failed: {resp.status_code} {resp.text}")
                results.append({"phone": phone, "status": "error"})
        except Exception as e:
            logger.error(f"WhatsApp send to {phone} exception: {e}")
            results.append({"phone": phone, "status": "error"})

    all_sent = all(r["status"] == "sent" for r in results)
    return {"status": "sent" if all_sent else "partial", "results": results}

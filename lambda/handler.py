"""AWS Email Image Moderation V2: SES -> S3 -> Rekognition -> SES.

Supported original attachments: JPEG, PNG, WebP, GIF, BMP.
Images are converted to JPEG for Rekognition; approved originals are forwarded.
Animated GIFs with more than MAX_GIF_FRAMES are routed for manual review.
"""

import hashlib
import io
import logging
import os
import re
from email import policy
from email.message import EmailMessage
from email.parser import BytesParser
from urllib.parse import unquote_plus

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError
from PIL import Image, ImageOps, UnidentifiedImageError

log = logging.getLogger(__name__)
log.setLevel(logging.INFO)
CONFIG = Config(retries={"max_attempts": 2, "mode": "standard"}, read_timeout=20)
s3 = boto3.client(
    "s3",
    region_name="eu-west-2",
    endpoint_url="https://s3.eu-west-2.amazonaws.com",
    config=Config(signature_version="s3v4")
)
rekognition = boto3.client("rekognition", config=CONFIG)
ses = boto3.client("sesv2", config=CONFIG)

MAX_EMAIL_BYTES = 35 * 1024 * 1024
MAX_IMAGE_BYTES = 10 * 1024 * 1024
MAX_APPROVED_BYTES = 24 * 1024 * 1024
MAX_IMAGES = 10
MAX_IMAGE_PIXELS = 20_000_000
MAX_GIF_FRAMES = 10
MAX_REKOGNITION_BYTES = 5 * 1024 * 1024
SUPPORTED_FORMATS = {"JPEG", "PNG", "WEBP", "GIF", "BMP"}
MIME_TYPES = {
    "JPEG": "image/jpeg", "PNG": "image/png", "WEBP": "image/webp",
    "GIF": "image/gif", "BMP": "image/bmp",
}
Image.MAX_IMAGE_PIXELS = MAX_IMAGE_PIXELS

# Moderation policy retained from Version 1.
MODERATION_CATEGORIES = {
    "Explicit Nudity", "Explicit Sexual Activity", "Sexual Activity",
    "Suggestive", "Non-Explicit Nudity of Intimate parts and Kissing",
    "Graphic Violence", "Violence", "Visually Disturbing",
    "Alcohol", "Alcoholic Beverages", "Drinking",
}
MODERATION_TERMS = (
    "explicit nudity", "sexual activity", "suggestive", "intimate parts",
    "kissing", "graphic violence", "violence", "gore", "blood",
    "visually disturbing", "alcohol", "drinking",
)
ALCOHOL_VISUAL_LABELS = {
    "alcohol", "alcoholic beverage", "alcoholic beverages", "beer", "wine",
    "whiskey", "whisky", "vodka", "liquor", "cocktail",
}
POLITICAL_VISUAL_LABELS = {
    "political rally", "political campaign", "election campaign", "campaign poster",
}
RALLY_VISUAL_LABELS = {"rally", "protest", "demonstration", "placard", "banner", "crowd"}
POLITICAL_TEXT = re.compile(
    r"\b(?:vote\s+(?:for|against|yes|no)|vote\s+\d{4}|re[- ]?elect|"
    r"election\s+(?:campaign|rally)|political\s+(?:campaign|rally|party)|"
    r"campaign\s+(?:rally|poster)|presidential\s+(?:candidate|election)|"
    r"parliamentary\s+(?:candidate|election)|ballot\s+paper|"
    r"party\s+candidate|manifesto)\b", re.IGNORECASE,
)
POLITICAL_CONTEXT = re.compile(
    r"\b(?:election|electoral|candidate|campaign|political|politician|"
    r"parliament|president|senator|governor|ballot|voters|voting)\b", re.IGNORECASE,
)


def attachments(message):
    """Yield non-body MIME parts, including unsupported attachments."""
    if message.is_multipart():
        for part in message.iter_parts():
            yield from attachments(part)
    elif (message.get_content_maintype() != "text" or message.get_filename()
          or message.get_content_disposition() == "attachment"):
        yield message


def safe_name(name, index):
    value = re.sub(r"[^A-Za-z0-9._-]", "_", name or f"image-{index}")[:100]
    return value.strip(".") or f"image-{index}"


def prepare_image_frames(data):
    """Return (Pillow format, list of JPEG bytes) or raise ValueError.

    Reject animations that cannot be fully scanned within the frame limit.
    """
    if len(data) > MAX_IMAGE_BYTES:
        raise ValueError("Attachment exceeds 10 MiB")
    try:
        with Image.open(io.BytesIO(data)) as image:
            fmt = image.format
            if fmt not in SUPPORTED_FORMATS:
                raise ValueError("Unsupported image format")
            frame_count = getattr(image, "n_frames", 1)
            if frame_count > MAX_GIF_FRAMES:
                raise ValueError("Animation exceeds 10 frames; manual review required")
            if image.width * image.height > MAX_IMAGE_PIXELS:
                raise ValueError("Image dimensions exceed safety limit")
            frames = []
            for index in range(frame_count):
                image.seek(index)
                frame = ImageOps.exif_transpose(image.convert("RGBA"))
                if frame.width * frame.height > MAX_IMAGE_PIXELS:
                    raise ValueError("Frame dimensions exceed safety limit")
                background = Image.new("RGB", frame.size, (255, 255, 255))
                background.paste(frame, mask=frame.getchannel("A"))
                # Keep original resolution for moderation; do not downsample
                # potentially important details merely to fit the API limit.
                output = io.BytesIO()
                background.save(output, format="JPEG", quality=85)
                jpeg = output.getvalue()
                if len(jpeg) > MAX_REKOGNITION_BYTES:
                    raise ValueError("Converted frame exceeds Rekognition size limit")
                frames.append(jpeg)
            return fmt, frames
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError,
            Image.DecompressionBombWarning) as exc:
        raise ValueError("Image could not be safely decoded") from exc


def scan_frame(jpeg, threshold):
    """Run all three Rekognition checks on one converted frame."""
    image = {"Bytes": jpeg}
    reasons = []
    moderation = rekognition.detect_moderation_labels(
        Image=image, MinConfidence=threshold)
    for label in moderation.get("ModerationLabels", []):
        name = label.get("Name", "")
        parent = label.get("ParentName", "")
        confidence = label.get("Confidence", 0)
        if confidence < threshold:
            continue
        if (name in MODERATION_CATEGORIES or parent in MODERATION_CATEGORIES
                or any(term in value.lower() for value in (name, parent)
                       for term in MODERATION_TERMS)):
            reasons.append(f"Moderation: {name} ({confidence:.1f}%)")

    visual = rekognition.detect_labels(Image=image, MaxLabels=50, MinConfidence=75)
    names = set()
    for label in visual.get("Labels", []):
        name = label.get("Name", "").lower()
        names.add(name)
        if name in ALCOHOL_VISUAL_LABELS:
            reasons.append("Potential alcohol-related image")
        if name in POLITICAL_VISUAL_LABELS:
            reasons.append("Potential political campaign/rally image")

    text_result = rekognition.detect_text(Image=image)
    lines = [item.get("DetectedText", "")
             for item in text_result.get("TextDetections", [])
             if item.get("Type") == "LINE" and item.get("Confidence", 0) >= 80]
    detected_text = " ".join(lines)
    # Do not log OCR text; it can contain personal information.
    if POLITICAL_TEXT.search(detected_text):
        reasons.append("Potential political campaign text")
    elif names.intersection(RALLY_VISUAL_LABELS) and POLITICAL_CONTEXT.search(detected_text):
        reasons.append("Possible political rally (visual and text indicators)")
    return list(dict.fromkeys(reasons))


def scan_image(data, threshold):
    """Any incomplete scan is flagged, never approved."""
    try:
        fmt, frames = prepare_image_frames(data)
        reasons = []
        for index, frame in enumerate(frames, 1):
            for reason in scan_frame(frame, threshold):
                reasons.append(f"Frame {index}: {reason}" if len(frames) > 1 else reason)
        return fmt, list(dict.fromkeys(reasons))
    except ValueError as exc:
        return None, [str(exc)]
    except (ClientError, BotoCoreError):
        log.exception("Rekognition scan incomplete")
        return None, ["Image scan incomplete; manual review required"]


def signed_link(bucket, key):
    return s3.generate_presigned_url(
        "get_object",
        Params={"Bucket": bucket, "Key": key,
                "ResponseContentDisposition": "attachment",
                "ResponseContentType": "application/octet-stream"},
        ExpiresIn=int(os.environ.get("LINK_EXPIRY_SECONDS", "3600")),
    )


def send_email(to_address, subject, body, approved=None):
    message = EmailMessage(policy=policy.SMTP)
    message["From"] = os.environ["SENDER_EMAIL"]
    message["To"] = to_address
    message["Subject"] = subject
    message.set_content(body)
    for name, data, mime in approved or []:
        main_type, sub_type = mime.split("/", 1)
        message.add_attachment(data, maintype=main_type,
                               subtype=sub_type, filename=name)
    response = ses.send_email(
        FromEmailAddress=os.environ["SENDER_EMAIL"],
        Destination={"ToAddresses": [to_address]},
        Content={"Raw": {"Data": message.as_bytes()}},
    )
    return response["MessageId"]


def send_results(reference, approved, flagged):
    """Send separate emails; no empty approved email."""
    sent = []
    if approved:
        sent.append(send_email(
            os.environ["APPROVED_EMAIL"],
            f"Approved images: {len(approved)} | {reference}",
            f"Submission: {reference}\nApproved image attachments: {len(approved)}",
            approved=approved,
        ))
    if flagged:
        lines = [f"Submission: {reference}",
                 f"Files requiring manual review: {len(flagged)}", "",
                 "Temporary download links (anyone with a link can access the file):"]
        for name, reason, link in flagged:
            lines.extend(["", f"{name}: {reason}", link])
        lines.extend(["", "Links may expire earlier if AWS signing credentials expire."])
        sent.append(send_email(
            os.environ["FLAGGED_EMAIL"],
            f"Images for review: {len(flagged)} | {reference}",
            "\n".join(lines),
        ))
    log.info("Submission %s: approved=%d flagged=%d", reference,
             len(approved), len(flagged))
    return sent


def process_email(bucket, key):
    reference = hashlib.sha256(key.encode("utf-8")).hexdigest()[:20]
    obj = s3.get_object(Bucket=bucket, Key=key)
    with obj["Body"] as stream:
        raw = stream.read(MAX_EMAIL_BYTES + 1)
    if len(raw) > MAX_EMAIL_BYTES:
        return send_results(reference, [], [
            ("Original email", "Email exceeds 35 MiB", signed_link(bucket, key))])

    message = BytesParser(policy=policy.default).parsebytes(raw)
    if any(part.defects for part in message.walk()):
        return send_results(reference, [], [
            ("Original email", "Malformed email; manual review required",
             signed_link(bucket, key))])

    parts = list(attachments(message))
    approved, flagged = [], []
    approved_bytes = 0
    threshold = float(os.environ.get("MODERATION_THRESHOLD", "80"))
    for index, part in enumerate(parts, 1):
        name = safe_name(part.get_filename(), index)
        data = part.get_payload(decode=True)
        if data is None:
            # Do not accidentally approve MIME parts that could not be decoded.
            flagged.append((name, "Attachment could not be decoded",
                            signed_link(bucket, key)))
            continue
        if index > MAX_IMAGES:
            flagged.append((name, "More than 10 attachments; not scanned",
                            signed_link(bucket, key)))
            continue
        if len(data) > MAX_IMAGE_BYTES:
            flagged.append((name, "Attachment exceeds 10 MiB",
                            signed_link(bucket, key)))
            continue

        # Store the original attachment for review, including unsupported files.
        # Do not use the original email link unless storage is unavailable.
        image_key = f"images/{reference}/{index}-{name}"
        s3.put_object(Bucket=bucket, Key=image_key, Body=data,
                      ContentType="application/octet-stream")
        fmt, reasons = scan_image(data, threshold)
        if not reasons and approved_bytes + len(data) > MAX_APPROVED_BYTES:
            reasons = ["Approved by moderation but exceeds outbound email size budget"]
        if reasons:
            flagged.append((name, "; ".join(reasons), signed_link(bucket, image_key)))
            log.info("Flagged attachment %s: %s", index, "; ".join(reasons))
        else:
            approved.append((name, data, MIME_TYPES[fmt]))
            approved_bytes += len(data)

    if not parts:
        flagged.append(("Original email", "No image attachments found",
                        signed_link(bucket, key)))
    return send_results(reference, approved, flagged)


def handler(event, context):
    sent_ids = []
    for record in event.get("Records", []):
        bucket = record["s3"]["bucket"]["name"]
        key = unquote_plus(record["s3"]["object"]["key"])
        if bucket == os.environ["BUCKET"] and key.startswith("incoming/"):
            sent_ids.extend(process_email(bucket, key))
    return {"sent_message_ids": sent_ids}

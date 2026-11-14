"""Offline unit tests for AWS Email Image Moderation V2."""
import importlib.util
import io
from email.message import EmailMessage
from pathlib import Path
from unittest.mock import MagicMock, patch

import boto3
import pytest
from PIL import Image


@pytest.fixture
def app():
    """Import the handler with mocked AWS clients; no AWS calls are made."""
    path = Path(__file__).resolve().parents[1] / "lambda" / "handler.py"
    with patch.object(boto3, "client", side_effect=lambda *args, **kwargs: MagicMock()):
        spec = importlib.util.spec_from_file_location("email_moderation_handler_test", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    return module


def image_bytes(fmt, size=(48, 48)):
    output = io.BytesIO()
    Image.new("RGB", size, "blue").save(output, format=fmt)
    return output.getvalue()


@pytest.mark.parametrize("fmt", ["JPEG", "PNG", "WEBP", "GIF", "BMP"])
def test_supported_image_formats(app, fmt):
    detected, frames = app.prepare_image_frames(image_bytes(fmt))
    assert detected == fmt
    assert len(frames) == 1
    assert frames[0].startswith(b"\xff\xd8\xff")


def test_animated_gif_all_frames_are_prepared(app):
    frames = [Image.new("RGB", (24, 24), color) for color in ("red", "green", "blue")]
    output = io.BytesIO()
    frames[0].save(output, format="GIF", save_all=True, append_images=frames[1:], duration=100, loop=0)
    fmt, converted = app.prepare_image_frames(output.getvalue())
    assert fmt == "GIF"
    assert len(converted) == 3


def test_gif_over_frame_limit_requires_review(app):
    frames = [Image.new("RGB", (16, 16), (i * 20, 0, 0)) for i in range(11)]
    output = io.BytesIO()
    frames[0].save(output, format="GIF", save_all=True, append_images=frames[1:], duration=100, loop=0)
    fmt, reasons = app.scan_image(output.getvalue(), 80)
    assert fmt is None
    assert any("10 frames" in reason for reason in reasons)


def test_unsupported_file_is_flagged(app):
    fmt, reasons = app.scan_image(b"%PDF-1.7 not an image", 80)
    assert fmt is None
    assert reasons


def test_oversized_file_is_flagged(app):
    fmt, reasons = app.scan_image(b"x" * (app.MAX_IMAGE_BYTES + 1), 80)
    assert fmt is None
    assert any("10 MiB" in reason for reason in reasons)


def test_clean_rekognition_result(app):
    app.rekognition.detect_moderation_labels.return_value = {"ModerationLabels": []}
    app.rekognition.detect_labels.return_value = {"Labels": []}
    app.rekognition.detect_text.return_value = {"TextDetections": []}
    fmt, reasons = app.scan_image(image_bytes("PNG"), 80)
    assert fmt == "PNG"
    assert reasons == []
    assert app.rekognition.detect_moderation_labels.called
    assert app.rekognition.detect_labels.called
    assert app.rekognition.detect_text.called


def test_moderation_label_flags_image(app):
    app.rekognition.detect_moderation_labels.return_value = {
        "ModerationLabels": [{"Name": "Graphic Violence", "ParentName": "Violence", "Confidence": 95.0}]
    }
    app.rekognition.detect_labels.return_value = {"Labels": []}
    app.rekognition.detect_text.return_value = {"TextDetections": []}
    _, reasons = app.scan_image(image_bytes("JPEG"), 80)
    assert any("Graphic Violence" in reason for reason in reasons)


def test_rekognition_error_requires_review(app):
    from botocore.exceptions import ClientError
    app.rekognition.detect_moderation_labels.side_effect = ClientError(
        {"Error": {"Code": "InternalServerError", "Message": "test failure"}}, "DetectModerationLabels"
    )
    fmt, reasons = app.scan_image(image_bytes("PNG"), 80)
    assert fmt is None
    assert any("manual review" in reason for reason in reasons)


def test_separate_mailbox_routing(app, monkeypatch):
    monkeypatch.setenv("APPROVED_EMAIL", "approved@example.com")
    monkeypatch.setenv("FLAGGED_EMAIL", "flagged@example.com")
    monkeypatch.setenv("SENDER_EMAIL", "moderation@example.com")
    app.ses.send_email.return_value = {"MessageId": "test-id"}
    approved = [("clean.png", image_bytes("PNG"), "image/png")]
    flagged = [("review.webp", "Review required", "https://example.com/review")]
    result = app.send_results("reference", approved, flagged)
    assert len(result) == 2
    calls = app.ses.send_email.call_args_list
    assert calls[0].kwargs["Destination"]["ToAddresses"] == ["approved@example.com"]
    assert calls[1].kwargs["Destination"]["ToAddresses"] == ["flagged@example.com"]
    assert b"clean.png" in calls[0].kwargs["Content"]["Raw"]["Data"]
    assert b"https://example.com/review" in calls[1].kwargs["Content"]["Raw"]["Data"]


def test_only_approved_sends_one_email(app, monkeypatch):
    monkeypatch.setenv("APPROVED_EMAIL", "approved@example.com")
    monkeypatch.setenv("FLAGGED_EMAIL", "flagged@example.com")
    monkeypatch.setenv("SENDER_EMAIL", "moderation@example.com")
    app.ses.send_email.return_value = {"MessageId": "test-id"}
    app.send_results("reference", [("clean.jpg", image_bytes("JPEG"), "image/jpeg")], [])
    assert app.ses.send_email.call_count == 1
    assert app.ses.send_email.call_args.kwargs["Destination"]["ToAddresses"] == ["approved@example.com"]


def test_no_attachments_routes_to_review(app, monkeypatch):
    monkeypatch.setenv("SENDER_EMAIL", "moderation@example.com")
    monkeypatch.setenv("APPROVED_EMAIL", "approved@example.com")
    monkeypatch.setenv("FLAGGED_EMAIL", "flagged@example.com")
    app.s3.get_object.return_value = {"Body": io.BytesIO(b"From: a@example.com\r\nTo: b@example.com\r\nSubject: Test\r\n\r\nHello")}
    app.s3.generate_presigned_url.return_value = "https://example.com/original"
    app.ses.send_email.return_value = {"MessageId": "review-id"}
    ids = app.process_email("test-bucket", "incoming/message")
    assert ids == ["review-id"]
    assert app.ses.send_email.call_args.kwargs["Destination"]["ToAddresses"] == ["flagged@example.com"]

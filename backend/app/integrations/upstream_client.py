import aiohttp
import base64
import json
import copy
from collections.abc import Callable
from typing import Any
from urllib.parse import urlparse

from ..core import settings as config
from ..core import validators as ssrf
from ..repositories import storage
from ..schemas.models import EditRequest, GenerateRequest

ProgressCallback = Callable[[str, str], None]


OUTPUT_FORMATS = {
    "png": {"extension": "png", "media_type": "image/png"},
    "jpeg": {"extension": "jpg", "media_type": "image/jpeg"},
    "webp": {"extension": "webp", "media_type": "image/webp"},
}


UPSTREAM_TIMEOUT = aiohttp.ClientTimeout(
    total=600,
    connect=30,
    sock_connect=30,
    sock_read=600,
)

DEFAULT_UPSTREAM_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/145.0.0.0 Safari/537.36"
)
DEFAULT_SEC_CH_UA = (
    '"Google Chrome";v="145", '
    '"Not:A-Brand";v="8", '
    '"Chromium";v="145"'
)
PROTECTED_EXTRA_HEADERS = {"authorization", "content-length", "host"}


def get_output_format_info(output_format: str) -> dict[str, str]:
    return OUTPUT_FORMATS.get(output_format, OUTPUT_FORMATS["png"])


def parse_extra_headers(raw_headers: str) -> dict[str, str]:
    raw_headers = (raw_headers or "").strip()
    if not raw_headers:
        return {}

    try:
        parsed = json.loads(raw_headers)
    except json.JSONDecodeError:
        parsed = None

    if isinstance(parsed, dict):
        return {
            str(key).strip(): str(value).strip()
            for key, value in parsed.items()
            if str(key).strip() and value is not None
        }

    headers: dict[str, str] = {}
    for item in raw_headers.replace("\n", ";").split(";"):
        if not item.strip() or ":" not in item:
            continue
        key, value = item.split(":", 1)
        key = key.strip()
        value = value.strip()
        if key and value:
            headers[key] = value
    return headers


def build_upstream_headers(
    api_key: str,
    *,
    api_url: str = "",
    content_type: str | None = None,
) -> dict[str, str]:
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7",
        "User-Agent": config.UPSTREAM_USER_AGENT or DEFAULT_UPSTREAM_USER_AGENT,
        "sec-ch-ua": DEFAULT_SEC_CH_UA,
        "sec-ch-ua-mobile": "?0",
    }
    if content_type:
        headers["Content-Type"] = content_type

    parsed_api_url = urlparse(api_url)
    default_origin = (
        f"{parsed_api_url.scheme}://{parsed_api_url.netloc}"
        if parsed_api_url.scheme and parsed_api_url.netloc
        else ""
    )
    origin = config.UPSTREAM_ORIGIN or default_origin
    referer = config.UPSTREAM_REFERER or origin
    if origin:
        headers["Origin"] = origin
    if referer:
        headers["Referer"] = referer

    for key, value in parse_extra_headers(config.UPSTREAM_EXTRA_HEADERS).items():
        if key.lower() in PROTECTED_EXTRA_HEADERS:
            continue
        headers[key] = value

    return headers


def extract_response_image_result(value: Any) -> dict[str, str] | None:
    if isinstance(value, str) and value:
        if value.startswith(("http://", "https://")):
            return {"url": value}
        return {"b64_json": value}

    if isinstance(value, dict):
        for key in ("url", "b64_json", "base64", "data", "result"):
            image = extract_response_image_result(value.get(key))
            if image:
                return image

    if isinstance(value, list):
        for item in value:
            image = extract_response_image_result(item)
            if image:
                return image

    return None


def extract_response_image_results(result: dict[str, Any]) -> list[dict[str, str]]:
    image_results: list[dict[str, str]] = []

    for item in result.get("output", []):
        if not isinstance(item, dict) or item.get("type") != "image_generation_call":
            continue

        image = extract_response_image_result(item.get("result"))
        if image:
            image_results.append(image)

    return image_results


def get_image_transfer_stage(image_data: dict) -> tuple[str, str]:
    if image_data.get("b64_json"):
        return ("decoding_b64_json", "Decoding b64_json image")
    if image_data.get("url"):
        return ("downloading_image_url", "Downloading image URL")
    return ("extracting_image_bytes", "Extracting image bytes")


async def extract_image_bytes(
    session: aiohttp.ClientSession,
    image_data: dict,
    response_text: str,
) -> bytes:
    if "b64_json" in image_data and image_data["b64_json"]:
        return base64.b64decode(image_data["b64_json"])

    if "url" in image_data and image_data["url"]:
        image_url = image_data["url"]
        ssrf.validate_image_url(image_url)
        async with session.get(
            image_url,
            headers={"User-Agent": config.UPSTREAM_USER_AGENT or DEFAULT_UPSTREAM_USER_AGENT},
        ) as img_resp:
            if img_resp.status != 200:
                raise Exception(
                    f"Failed to download image from {image_url}: {img_resp.status}"
                )
            return await img_resp.read()

    raise Exception(
        f"No image data (b64_json or url) in upstream response: {response_text}"
    )


def build_images_request_data(payload: GenerateRequest) -> dict[str, Any]:
    request_data: dict[str, Any] = {
        "model": payload.model,
        "prompt": payload.prompt,
        "size": payload.size,
        "n": payload.n,
        "quality": payload.quality,
        "output_format": payload.output_format,
    }
    if payload.response_format is not None:
        request_data["response_format"] = payload.response_format
    if payload.output_format != "png" and payload.output_compression is not None:
        request_data["output_compression"] = payload.output_compression
    return request_data


def build_images_edit_form_data(payload: EditRequest) -> dict[str, Any]:
    form_data: dict[str, Any] = {
        "model": payload.model,
        "prompt": payload.prompt,
        "size": payload.size,
        "n": payload.n,
        "quality": payload.quality,
        "output_format": payload.output_format,
    }
    if payload.response_format is not None:
        form_data["response_format"] = payload.response_format
    if payload.output_format != "png" and payload.output_compression is not None:
        form_data["output_compression"] = payload.output_compression
    return form_data


def build_responses_request_data(payload: GenerateRequest) -> dict[str, Any]:
    return {"prompt": payload.prompt, "model": payload.model}


def normalize_api_path(api_path: str) -> str:
    if api_path in {"/v1/images/generations", "/v1/responses"}:
        return api_path
    return "/v1/images/generations"


def get_upstream_error_message(
    status: int,
    response_text: str,
    is_json_response: bool,
) -> str:
    if is_json_response:
        try:
            error_body = json.loads(response_text)
            return error_body.get("error", {}).get("message", response_text)
        except Exception:
            return response_text
    if "<!doctype html" in response_text.lower() or "<html" in response_text.lower():
        return (
            f"HTTP {status}: upstream returned an HTML error page instead of JSON. "
            "Please check that API URL is the real API base URL, not a website/CDN/proxy page."
        )
    return f"HTTP {status}: {response_text[:200]}"


def validate_api_base_url(api_url: str) -> None:
    parsed = urlparse(api_url)
    if parsed.path.rstrip("/") in {
        "/v1/images/generations",
        "/v1/images/edits",
        "/v1/responses",
    }:
        raise ValueError(
            "API URL should be the base URL only, for example https://api.openai.com. "
            "Select the endpoint in API path instead."
        )


def raise_upstream_error(
    status: int,
    response_text: str,
    is_json_response: bool,
    api_path: str,
):
    error_msg = get_upstream_error_message(status, response_text, is_json_response)
    unsupported_markers = (
        "not support",
        "not_supported",
        "unsupported",
        "not found",
        "unknown endpoint",
        "no route",
    )
    if api_path == "/v1/images/edits" and (
        status in {404, 405, 501}
        or any(marker in error_msg.lower() for marker in unsupported_markers)
    ):
        raise Exception(
            f"Upstream API does not support /v1/images/edits ({status}): {error_msg}"
        )
    raise Exception(f"Upstream API error ({status}): {error_msg}")


async def call_image_generation_api(
    api_url: str,
    api_key: str,
    api_path: str,
    payload: GenerateRequest,
    api_preset_name: str | None = None,
    progress: ProgressCallback | None = None,
) -> list[storage.GalleryEntry]:
    api_path = normalize_api_path(api_path)
    validate_api_base_url(api_url)
    upstream_url = f"{api_url.rstrip('/')}{api_path}"

    ssrf.validate_upstream_url(upstream_url, config.UPSTREAM_HOST_ALLOWLIST)

    headers = build_upstream_headers(
        api_key,
        api_url=api_url,
        content_type="application/json",
    )

    if api_path == "/v1/responses":
        if progress:
            progress("building_responses_payload", "Building Responses API payload")
        request_data = build_responses_request_data(payload)
        request_count = 1
    else:
        if progress:
            progress("building_generation_payload", "Building image generation payload")
        request_data = build_images_request_data(payload)
        request_count = 1

    format_info = get_output_format_info(payload.output_format)
    entries: list[storage.GalleryEntry] = []
    gallery_metadata = {
        "model": payload.model,
        "quality": payload.quality,
        "output_format": payload.output_format,
        "output_compression": payload.output_compression,
        "response_format": payload.response_format,
        "n": payload.n,
        "api_path": api_path,
        "api_preset_name": api_preset_name,
    }

    async with aiohttp.ClientSession(timeout=UPSTREAM_TIMEOUT) as session:
        for request_index in range(request_count):
            if progress:
                progress(
                    "waiting_for_api",
                    f"Waiting for upstream API response ({request_index + 1}/{request_count})",
                )
            request_body = copy.deepcopy(request_data)
            async with session.post(
                upstream_url, json=request_body, headers=headers
            ) as resp:
                status = resp.status
                response_text = await resp.text()
                if progress:
                    progress("received_api_response", "Received upstream API response")

                content_type = resp.headers.get("Content-Type", "")
                is_json_response = "application/json" in content_type

                if status >= 400:
                    raise_upstream_error(status, response_text, is_json_response, api_path)

                if is_json_response:
                    if progress:
                        progress("parsing_json_response", "Parsing JSON response")
                    try:
                        result = json.loads(response_text)
                    except json.JSONDecodeError:
                        raise Exception(f"Upstream returned non-JSON ({status}): {response_text[:200]}")
                else:
                    raise Exception(f"Upstream returned non-JSON content-type ({status}): {response_text[:200]}")

                if api_path == "/v1/responses":
                    if progress:
                        progress(
                            "extracting_response_image_output",
                            "Extracting image_generation_call output",
                        )
                    data = extract_response_image_results(result)
                else:
                    if progress:
                        progress("extracting_generation_data", "Extracting image data array")
                    data = result.get("data", [])
                if not data:
                    text_preview = response_text[:200] if isinstance(response_text, str) else str(response_text)[:200]
                    raise Exception(f"No image data in upstream response: {text_preview}")

                if api_path == "/v1/responses" and len(data) > 1:
                    entries_data: list[tuple] = []
                    for image_index, image_data in enumerate(data):
                        transfer_stage, transfer_message = get_image_transfer_stage(image_data)
                        if progress:
                            progress(
                                transfer_stage,
                                f"{transfer_message} ({image_index + 1}/{len(data)})",
                            )
                        image_bytes = await extract_image_bytes(session, image_data, response_text)
                        if progress:
                            progress(
                                "validating_image_bytes",
                                f"Validating decoded image ({image_index + 1}/{len(data)})",
                            )
                        max_bytes = 50 * 1024 * 1024
                        if len(image_bytes) > max_bytes:
                            raise Exception(
                                f"Image too large: {len(image_bytes)} bytes (max {max_bytes})"
                            )
                        image_id = storage.generate_image_id()
                        filename = f"{image_id}.{format_info['extension']}"
                        entries_data.append(
                            (image_bytes, image_id, payload.prompt, payload.size, filename, gallery_metadata)
                        )
                    if progress:
                        progress("saving_images", "Saving generated images")
                    batch_entries = await storage.batch_save_and_update_gallery(entries_data)
                    entries.extend(batch_entries)
                else:
                    for image_index, image_data in enumerate(data):
                        transfer_stage, transfer_message = get_image_transfer_stage(image_data)
                        if progress:
                            progress(
                                transfer_stage,
                                f"{transfer_message} ({image_index + 1}/{len(data)})",
                            )
                        image_bytes = await extract_image_bytes(session, image_data, response_text)

                        if progress:
                            progress(
                                "validating_image_bytes",
                                f"Validating decoded image ({image_index + 1}/{len(data)})",
                            )
                        max_bytes = 50 * 1024 * 1024
                        if len(image_bytes) > max_bytes:
                            raise Exception(
                                f"Image too large: {len(image_bytes)} bytes (max {max_bytes})"
                            )

                        image_id = storage.generate_image_id()
                        filename = f"{image_id}.{format_info['extension']}"
                        if progress:
                            progress(
                                "saving_image_file",
                                "Saving image file and gallery metadata "
                                f"({image_index + 1}/{len(data)})",
                            )
                        entry = await storage.add_to_gallery_async(
                            image_bytes=image_bytes,
                            image_id=image_id,
                            prompt=payload.prompt,
                            size=payload.size,
                            filename=filename,
                            metadata=gallery_metadata,
                        )
                        entries.append(entry)

    return entries


async def call_images_api(
    api_url: str,
    api_key: str,
    payload: GenerateRequest,
) -> list[storage.GalleryEntry]:
    return await call_image_generation_api(
        api_url,
        api_key,
        "/v1/images/generations",
        payload,
    )


async def call_image_edit_api(
    api_url: str,
    api_key: str,
    payload: EditRequest,
    image_bytes: bytes,
    image_filename: str,
    image_content_type: str,
    api_preset_name: str | None = None,
    progress: ProgressCallback | None = None,
) -> list[storage.GalleryEntry]:
    api_path = "/v1/images/edits"
    validate_api_base_url(api_url)
    upstream_url = f"{api_url.rstrip('/')}{api_path}"

    ssrf.validate_upstream_url(upstream_url, config.UPSTREAM_HOST_ALLOWLIST)

    headers = build_upstream_headers(api_key, api_url=api_url)
    format_info = get_output_format_info(payload.output_format)
    gallery_metadata = {
        "model": payload.model,
        "quality": payload.quality,
        "output_format": payload.output_format,
        "output_compression": payload.output_compression,
        "response_format": payload.response_format,
        "n": payload.n,
        "api_path": api_path,
        "api_preset_name": api_preset_name,
    }

    if progress:
        progress("building_edit_form", "Building multipart edit request")
    form = aiohttp.FormData()
    form.add_field(
        "image",
        image_bytes,
        filename=image_filename or "image.png",
        content_type=image_content_type or "application/octet-stream",
    )
    for key, value in build_images_edit_form_data(payload).items():
        form.add_field(key, str(value))

    async with aiohttp.ClientSession(timeout=UPSTREAM_TIMEOUT) as session:
        if progress:
            progress("uploading_edit_image", "Uploading source image and edit parameters")
        async with session.post(upstream_url, data=form, headers=headers) as resp:
            status = resp.status
            response_text = await resp.text()
            if progress:
                progress("received_api_response", "Received upstream API response")

            content_type = resp.headers.get("Content-Type", "")
            is_json_response = "application/json" in content_type

            if status >= 400:
                raise_upstream_error(status, response_text, is_json_response, api_path)

            if is_json_response:
                if progress:
                    progress("parsing_json_response", "Parsing JSON response")
                try:
                    result = json.loads(response_text)
                except json.JSONDecodeError:
                    raise Exception(
                        f"Upstream returned non-JSON ({status}): {response_text[:200]}"
                    )
            else:
                raise Exception(
                    f"Upstream returned non-JSON content-type ({status}): {response_text[:200]}"
                )

            if progress:
                progress("extracting_edit_data", "Extracting edited image data array")
            data = result.get("data", [])
            if not data:
                raise Exception(f"No image data in upstream response: {response_text[:200]}")

            entries_data: list[tuple] = []
            max_bytes = config.MAX_FILE_SIZE_MB * 1024 * 1024
            for image_index, image_data in enumerate(data):
                transfer_stage, transfer_message = get_image_transfer_stage(image_data)
                if progress:
                    progress(
                        transfer_stage,
                        f"{transfer_message} ({image_index + 1}/{len(data)})",
                    )
                edited_image_bytes = await extract_image_bytes(
                    session,
                    image_data,
                    response_text,
                )
                if progress:
                    progress(
                        "validating_image_bytes",
                        f"Validating decoded image ({image_index + 1}/{len(data)})",
                    )
                if len(edited_image_bytes) > max_bytes:
                    raise Exception(
                        f"Image too large: {len(edited_image_bytes)} bytes (max {max_bytes})"
                    )

                image_id = storage.generate_image_id()
                filename = f"{image_id}.{format_info['extension']}"
                entries_data.append(
                    (
                        edited_image_bytes,
                        image_id,
                        payload.prompt,
                        payload.size,
                        filename,
                        gallery_metadata,
                    )
                )

            if progress:
                progress("saving_images", "Saving edited images")
            return await storage.batch_save_and_update_gallery(entries_data)

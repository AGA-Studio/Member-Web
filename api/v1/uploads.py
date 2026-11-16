"""HTTP side of every image upload: size limit and stable error codes.

Shared by /logo, /customer/{customer_id}/photo and /user/photo, so the
frontend gets the same 413, 422 and 503 codes from all of them.
"""

from collections.abc import Iterator
from contextlib import contextmanager

from fastapi import UploadFile, status

from core.errors import ApiError, ErrorCode
from services import image_service, storage_service


def read_image(file: UploadFile) -> bytes:
    """Read the upload, one byte past the limit: enough to know it is too big."""
    data = file.file.read(image_service.MAX_UPLOAD_BYTES + 1)
    if len(data) > image_service.MAX_UPLOAD_BYTES:
        raise ApiError(
            status.HTTP_413_CONTENT_TOO_LARGE,
            "The image is larger than 2 MB",
            ErrorCode.IMAGE_TOO_LARGE,
        )
    return data


@contextmanager
def image_errors() -> Iterator[None]:
    """Turn image and storage failures into ApiError with a stable code."""
    try:
        yield
    except image_service.ImageRejected as error:
        raise ApiError(
            status.HTTP_422_UNPROCESSABLE_CONTENT, str(error), ErrorCode.IMAGE_INVALID
        ) from None
    except storage_service.StorageUnavailable:
        raise ApiError(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Image storage is not available",
            ErrorCode.STORAGE_UNAVAILABLE,
        ) from None

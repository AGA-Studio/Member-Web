"""Shared steps to store or remove one image referenced by a table column.

Used by the business logo, the customer photo and the user profile photo, so
the three follow the exact same rules:

- the upload is validated and re-encoded by image_service (WebP, 512 px, no
  metadata) before anything is stored;
- the column keeps the storage *key*, never a URL;
- the previous file is deleted only after the commit, so a failed commit never
  leaves the row pointing at a file that no longer exists.
"""

from sqlmodel import Session, SQLModel

from services import image_service, storage_service


def replace_image(
    session: Session,
    row: SQLModel,
    field: str,
    key: str,
    data: bytes,
    max_dimension: int = image_service.MAX_DIMENSION,
) -> None:
    """Store `data` under `key` and point `row.<field>` at it.

    `max_dimension` is the size the stored copy is shrunk to: 512 px for
    photos, bigger for the business logo, which also becomes the Google Wallet
    pass logo.

    Raises image_service.ImageRejected or storage_service.StorageUnavailable,
    in both cases before touching the row.
    """
    webp = image_service.to_webp(data, max_dimension)
    storage_service.put_object(key, webp, image_service.CONTENT_TYPE)

    previous = getattr(row, field)
    setattr(row, field, key)
    session.add(row)
    session.commit()
    session.refresh(row)
    delete_stored(previous)


def remove_image(session: Session, row: SQLModel, field: str) -> None:
    """Clear `row.<field>` and delete its file. Without an image, changes nothing."""
    previous = getattr(row, field)
    if previous is None:
        return
    setattr(row, field, None)
    session.add(row)
    session.commit()
    session.refresh(row)
    delete_stored(previous)


def delete_stored(reference: str | None) -> None:
    """Delete the file behind a stored key. External URLs and None are ignored."""
    if storage_service.is_storage_key(reference):
        storage_service.delete_object(reference)

"""/api/v1/public/logo/{business_id}.png: the logo Google Wallet and email load.

The URL is public and never expires (a signed storage URL lasts an hour), so the
API serves the square PNG itself and the bucket stays private.
"""

from io import BytesIO

from fastapi.testclient import TestClient
from PIL import Image
from sqlmodel import Session

from models import Business, BusinessStatus
from tests.conftest import TEST_S3_BUCKET, bucket_keys, login, make_image

LOGO_URL = "/api/v1/public/logo"
UPDATE = "/api/v1/logo/update"
EXTERNAL = "https://cdn.example.com/aurora.png"


def upload_logo(client: TestClient, size: tuple[int, int] = (1200, 600)) -> None:
    """Upload a logo through the real endpoint, then drop the session cookie."""
    login(client, "admin.a@demo.mx")
    response = client.post(
        UPDATE, files={"file": ("logo.png", make_image("PNG", size=size), "image/png")}
    )
    assert response.status_code == 200, response.text
    client.cookies.clear()


def get_logo(client: TestClient, business_id: int):
    return client.get(f"{LOGO_URL}/{business_id}.png")


def as_png(response) -> Image.Image:
    assert response.headers["content-type"] == "image/png"
    return Image.open(BytesIO(response.content))


class TestNoLogo:
    def test_unknown_business(self, client: TestClient) -> None:
        assert get_logo(client, 999).status_code == 404

    def test_business_without_a_logo(self, client: TestClient, two_businesses) -> None:
        assert get_logo(client, two_businesses["business_a"].id).status_code == 404

    def test_external_logo_is_not_proxied(
        self, client: TestClient, session: Session, two_businesses
    ):
        """An https logo is already public: the pass and the email use it as is."""
        business = two_businesses["business_a"]
        business.logo_url = EXTERNAL
        session.add(business)
        session.commit()
        assert get_logo(client, business.id).status_code == 404

    def test_suspended_business(
        self, client: TestClient, session: Session, two_businesses, storage
    ) -> None:
        business = two_businesses["business_a"]
        upload_logo(client)
        business.status = BusinessStatus.SUSPENDED
        session.add(business)
        session.commit()
        assert get_logo(client, business.id).status_code == 404

    def test_storage_off(self, client: TestClient, session: Session, two_businesses) -> None:
        """Without S3 the key cannot be read: the same 404, not a 500."""
        business = two_businesses["business_a"]
        business.logo_url = f"businesses/{business.id}/logo/missing.webp"
        session.add(business)
        session.commit()
        assert get_logo(client, business.id).status_code == 404

    def test_missing_file_in_storage(
        self, client: TestClient, session: Session, two_businesses, storage
    ) -> None:
        business = two_businesses["business_a"]
        business.logo_url = f"businesses/{business.id}/logo/missing.webp"
        session.add(business)
        session.commit()
        assert get_logo(client, business.id).status_code == 404


class TestThePng:
    def test_no_session_needed_and_cacheable(
        self, client: TestClient, two_businesses, storage
    ) -> None:
        upload_logo(client)
        response = get_logo(client, two_businesses["business_a"].id)
        assert response.status_code == 200
        assert "immutable" in response.headers["cache-control"]
        assert "max-age=86400" in response.headers["cache-control"]

    def test_is_square_and_masked_with_a_margin(
        self, client: TestClient, two_businesses, storage
    ) -> None:
        upload_logo(client)
        image = as_png(get_logo(client, two_businesses["business_a"].id))
        assert image.mode == "RGBA"
        assert image.width == image.height
        # Google masks the logo into a circle: the artwork keeps a 15% margin on
        # its longest side and stays centered, without being stretched.
        left, top, right, bottom = image.getchannel("A").getbbox()
        assert abs(left - (image.width - right)) <= 1
        assert abs(top - (image.height - bottom)) <= 1
        width, height = right - left, bottom - top
        assert max(width / image.width, height / image.height) <= 0.71
        assert 0.69 <= max(width / image.width, height / image.height) <= 0.71
        # The uploaded 1200x600 logo keeps its 2:1 shape instead of being squared.
        assert abs(width / height - 2) < 0.01

    def test_logo_is_stored_bigger_than_a_photo(
        self, client: TestClient, two_businesses, storage
    ) -> None:
        """660 px is Google's minimum, so the logo is not shrunk to 512."""
        upload_logo(client)
        [key] = bucket_keys(storage)
        data = storage.get_object(Bucket=TEST_S3_BUCKET, Key=key)["Body"].read()
        assert Image.open(BytesIO(data)).size == (1024, 512)

    def test_uploading_again_changes_the_url(
        self, client: TestClient, session: Session, two_businesses, storage
    ) -> None:
        """The `v` query is the cache key: a new logo is a new URL."""
        business = two_businesses["business_a"]
        upload_logo(client)
        first = session.get(Business, business.id).logo_url
        upload_logo(client)
        session.expire_all()
        assert session.get(Business, business.id).logo_url != first

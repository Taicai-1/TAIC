"""Unit tests for google_drive_client.extract_drive_folder_id()."""

import pytest
from google_drive_client import extract_drive_folder_id


class TestExtractDriveFolderId:
    def test_full_url(self):
        url = "https://drive.google.com/drive/folders/1AbC_dEf-GhIjKlMnOpQrStUv"
        assert extract_drive_folder_id(url) == "1AbC_dEf-GhIjKlMnOpQrStUv"

    def test_full_url_with_query_params(self):
        url = "https://drive.google.com/drive/folders/1AbC_dEf-GhIjKlMnOpQrStUv?usp=sharing"
        assert extract_drive_folder_id(url) == "1AbC_dEf-GhIjKlMnOpQrStUv"

    def test_url_with_u_prefix(self):
        url = "https://drive.google.com/drive/u/0/folders/1AbCdEfGhIjKlMnOpQrStUv"
        assert extract_drive_folder_id(url) == "1AbCdEfGhIjKlMnOpQrStUv"

    def test_raw_folder_id(self):
        folder_id = "1AbCdEfGhIjKlMnOpQrStUvWxYz"
        assert extract_drive_folder_id(folder_id) == folder_id

    def test_raw_id_with_dashes_underscores(self):
        folder_id = "1A-bC_dEfGhIjKlMnO"
        assert extract_drive_folder_id(folder_id) == folder_id

    def test_whitespace_trimmed(self):
        url = "  https://drive.google.com/drive/folders/abc123def456  "
        assert extract_drive_folder_id(url) == "abc123def456"

    def test_invalid_short_id_raises(self):
        with pytest.raises(ValueError):
            extract_drive_folder_id("abc")

    def test_empty_string_raises(self):
        with pytest.raises(ValueError):
            extract_drive_folder_id("")

    def test_random_url_raises(self):
        with pytest.raises(ValueError):
            extract_drive_folder_id("https://example.com/not-a-drive-link")

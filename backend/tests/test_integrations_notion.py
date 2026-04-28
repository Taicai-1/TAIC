"""Unit tests for notion_client.py integration module."""

import pytest
from unittest.mock import Mock, patch


class TestNotionClientImport:
    def test_import_notion_client(self):
        """Verify the notion_client module can be imported."""
        import notion_client

        # Verify key functions are exposed
        assert hasattr(notion_client, 'extract_notion_id')
        assert hasattr(notion_client, 'fetch_page_title')
        assert hasattr(notion_client, 'fetch_database_title')
        assert hasattr(notion_client, 'fetch_page_content')
        assert hasattr(notion_client, 'fetch_database_entries')
        assert hasattr(notion_client, 'blocks_to_text')
        assert hasattr(notion_client, 'database_entries_to_text')


class TestNotionPageFetchMocked:
    @patch('notion_client.requests.get')
    @patch('notion_client.get_notion_token')
    def test_notion_page_fetch_mocked(self, mock_get_token, mock_requests_get):
        """Mock requests.get and verify the module can process a Notion API response format."""
        from notion_client import fetch_page_title

        # Mock the token retrieval
        mock_get_token.return_value = "mock-notion-token"

        # Mock Notion API response for a page
        mock_response = Mock()
        mock_response.raise_for_status = Mock()
        mock_response.json.return_value = {
            "object": "page",
            "id": "abc123",
            "properties": {
                "title": {
                    "type": "title",
                    "title": [
                        {
                            "type": "text",
                            "text": {"content": "Test Page Title"},
                            "plain_text": "Test Page Title"
                        }
                    ]
                }
            }
        }
        mock_requests_get.return_value = mock_response

        # Call the function
        result = fetch_page_title("abc123", company_id=1)

        # Verify the result
        assert result == "Test Page Title"

        # Verify requests.get was called with correct parameters
        mock_requests_get.assert_called_once()
        call_args = mock_requests_get.call_args
        assert "https://api.notion.com/v1/pages/abc123" in call_args[0]
        assert call_args[1]["headers"]["Authorization"] == "Bearer mock-notion-token"
        assert call_args[1]["headers"]["Notion-Version"] == "2022-06-28"

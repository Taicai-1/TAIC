"""Google Docs plugin."""

from plugins.base import BasePlugin, ActionDefinition, ActionResult
from plugins.google_docs import actions, schemas


class GoogleDocsPlugin(BasePlugin):
    name = "google_docs"
    display_name = "Google Docs"
    description = "Create and manage Google Docs documents"
    icon = "file-text"
    required_scopes = [
        "https://www.googleapis.com/auth/documents",
        "https://www.googleapis.com/auth/drive.file",
    ]

    def get_actions(self):
        return {
            "create_doc": ActionDefinition(
                name="create_doc",
                description="Create a new Google Docs document with an optional title and content",
                parameters_schema=schemas.CREATE_DOC,
                display_name="Create Document",
                icon="file-plus",
                side_effect=True,
            ),
            "update_doc": ActionDefinition(
                name="update_doc",
                description="Append content to an existing Google Docs document",
                parameters_schema=schemas.UPDATE_DOC,
                display_name="Update Document",
                icon="file-edit",
                side_effect=True,
            ),
            "share_doc": ActionDefinition(
                name="share_doc",
                description="Share a Google Docs document with another user by email",
                parameters_schema=schemas.SHARE_DOC,
                display_name="Share Document",
                icon="share",
                side_effect=True,
            ),
        }

    def execute(self, action_name, args, credentials):
        action_map = {
            "create_doc": actions.create_doc,
            "update_doc": actions.update_doc,
            "share_doc": actions.share_doc,
        }
        fn = action_map.get(action_name)
        if not fn:
            return ActionResult(
                success=False, data={}, display_message="", resource_url=None,
                error_message=f"Unknown action: {action_name}",
            )
        return fn(args, credentials)


# Used by PluginManager auto-discovery
plugin_class = GoogleDocsPlugin

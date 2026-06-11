"""Google Sheets plugin."""

from plugins.base import BasePlugin, ActionDefinition, ActionResult
from plugins.google_sheets import actions, schemas


class GoogleSheetsPlugin(BasePlugin):
    name = "google_sheets"
    display_name = "Google Sheets"
    description = "Create and manage Google Sheets spreadsheets"
    icon = "table"
    required_scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive.file",
    ]

    def get_actions(self):
        return {
            "create_sheet": ActionDefinition(
                name="create_sheet",
                description="Create a new spreadsheet with optional sheets, headers and data",
                parameters_schema=schemas.CREATE_SHEET,
                display_name="Create Spreadsheet",
                icon="table",
                side_effect=True,
            ),
            "update_sheet": ActionDefinition(
                name="update_sheet",
                description="Update cell values in an existing spreadsheet",
                parameters_schema=schemas.UPDATE_SHEET,
                display_name="Update Spreadsheet",
                icon="edit",
                side_effect=True,
            ),
            "read_sheet": ActionDefinition(
                name="read_sheet",
                description="Read cell values from a spreadsheet",
                parameters_schema=schemas.READ_SHEET,
                display_name="Read Spreadsheet",
                icon="eye",
                side_effect=False,
            ),
        }

    def execute(self, action_name, args, credentials):
        action_map = {
            "create_sheet": actions.create_sheet,
            "update_sheet": actions.update_sheet,
            "read_sheet": actions.read_sheet,
        }
        fn = action_map.get(action_name)
        if not fn:
            return ActionResult(
                success=False,
                data={},
                display_message="",
                resource_url=None,
                error_message=f"Unknown action: {action_name}",
            )
        return fn(args, credentials)


plugin_class = GoogleSheetsPlugin

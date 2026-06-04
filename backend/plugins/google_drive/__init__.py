"""Google Drive plugin."""
from plugins.base import BasePlugin, ActionDefinition, ActionResult
from plugins.google_drive import actions, schemas

class GoogleDrivePlugin(BasePlugin):
    name = "google_drive"
    display_name = "Google Drive"
    description = "Manage files and folders in Google Drive"
    icon = "hard-drive"
    required_scopes = [
        "https://www.googleapis.com/auth/drive.file",
        "https://www.googleapis.com/auth/drive.readonly",
    ]
    def get_actions(self):
        return {
            "create_folder": ActionDefinition(name="create_folder", description="Create a new folder in Google Drive",
                                             parameters_schema=schemas.CREATE_FOLDER, display_name="Create Folder", icon="folder-plus", side_effect=True),
            "move_file": ActionDefinition(name="move_file", description="Move a file to a different folder",
                                        parameters_schema=schemas.MOVE_FILE, display_name="Move File", icon="folder-input", side_effect=True),
            "share_file": ActionDefinition(name="share_file", description="Share a file or folder with another user by email",
                                          parameters_schema=schemas.SHARE_FILE, display_name="Share File", icon="share", side_effect=True),
            "search_files": ActionDefinition(name="search_files", description="Search for files and folders in Google Drive",
                                           parameters_schema=schemas.SEARCH_FILES, display_name="Search Files", icon="search", side_effect=False),
        }
    def execute(self, action_name, args, credentials):
        action_map = {"create_folder": actions.create_folder, "move_file": actions.move_file,
                      "share_file": actions.share_file, "search_files": actions.search_files}
        fn = action_map.get(action_name)
        if not fn:
            return ActionResult(success=False, data={}, display_message="", resource_url=None, error_message=f"Unknown action: {action_name}")
        return fn(args, credentials)

plugin_class = GoogleDrivePlugin

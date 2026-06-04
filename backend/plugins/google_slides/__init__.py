"""Google Slides plugin."""
from plugins.base import BasePlugin, ActionDefinition, ActionResult
from plugins.google_slides import actions, schemas

class GoogleSlidesPlugin(BasePlugin):
    name = "google_slides"
    display_name = "Google Slides"
    description = "Create and manage Google Slides presentations"
    icon = "presentation"
    required_scopes = [
        "https://www.googleapis.com/auth/presentations",
        "https://www.googleapis.com/auth/drive.file",
    ]
    def get_actions(self):
        return {
            "create_presentation": ActionDefinition(name="create_presentation", description="Create a new Google Slides presentation with optional slides",
                                                   parameters_schema=schemas.CREATE_PRESENTATION, display_name="Create Presentation", icon="plus-square", side_effect=True),
            "add_slide": ActionDefinition(name="add_slide", description="Add a new slide to an existing presentation",
                                        parameters_schema=schemas.ADD_SLIDE, display_name="Add Slide", icon="layers", side_effect=True),
        }
    def execute(self, action_name, args, credentials):
        action_map = {"create_presentation": actions.create_presentation, "add_slide": actions.add_slide}
        fn = action_map.get(action_name)
        if not fn:
            return ActionResult(success=False, data={}, display_message="", resource_url=None, error_message=f"Unknown action: {action_name}")
        return fn(args, credentials)

plugin_class = GoogleSlidesPlugin

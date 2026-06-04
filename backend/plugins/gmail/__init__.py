"""Gmail plugin."""
from plugins.base import BasePlugin, ActionDefinition, ActionResult
from plugins.gmail import actions, schemas

class GmailPlugin(BasePlugin):
    name = "gmail"
    display_name = "Gmail"
    description = "Send and manage emails via Gmail"
    icon = "mail"
    required_scopes = [
        "https://www.googleapis.com/auth/gmail.send",
        "https://www.googleapis.com/auth/gmail.readonly",
    ]
    def get_actions(self):
        return {
            "send_email": ActionDefinition(name="send_email", description="Send an email from the user's Gmail account",
                                          parameters_schema=schemas.SEND_EMAIL, display_name="Send Email", icon="send", side_effect=True),
            "reply_email": ActionDefinition(name="reply_email", description="Reply to an existing email thread",
                                           parameters_schema=schemas.REPLY_EMAIL, display_name="Reply to Email", icon="reply", side_effect=True),
            "search_emails": ActionDefinition(name="search_emails", description="Search for emails in Gmail",
                                             parameters_schema=schemas.SEARCH_EMAILS, display_name="Search Emails", icon="search", side_effect=False),
        }
    def execute(self, action_name, args, credentials):
        action_map = {"send_email": actions.send_email, "reply_email": actions.reply_email, "search_emails": actions.search_emails}
        fn = action_map.get(action_name)
        if not fn:
            return ActionResult(success=False, data={}, display_message="", resource_url=None, error_message=f"Unknown action: {action_name}")
        return fn(args, credentials)

plugin_class = GmailPlugin

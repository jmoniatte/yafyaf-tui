from ouikit.dialog import Dialog, DialogButton

EDIT_AGAIN = "edit"
RETRY = "retry"
DISCARD = "discard"


class NotSavedDialog(Dialog):
    """After a failed save: the error and what to do about the edit.

    Returns EDIT_AGAIN (the default, on Enter), RETRY (only offered when the server, not the
    text, was the problem) or DISCARD. There is no Escape: the edit is only in the draft, so
    the user has to choose what becomes of it.
    """

    def __init__(self, error: str, retry: bool) -> None:
        buttons = [DialogButton("Discard", DISCARD, "confirm-btn", kind="danger")]
        if retry:
            buttons.append(DialogButton("Retry", RETRY, "retry-btn", kind="action"))
        buttons.append(DialogButton("Edit again", EDIT_AGAIN, "edit-btn", kind="action"))
        super().__init__("Error saving the Yaf", error, buttons, focus="edit-btn")

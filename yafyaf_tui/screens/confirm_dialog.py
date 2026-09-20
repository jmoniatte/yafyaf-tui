from .dialog import Dialog, DialogButton


class ConfirmDialog(Dialog):
    """Yes or no, returned as True or False; Escape is no.

    Focus starts on the cancel button, so a reflexive Enter never confirms a deletion.
    """

    def __init__(
        self,
        message: str,
        title: str = "Confirm",
        confirm_label: str = "Yes",
        cancel_label: str = "No",
        detail: str = "",
    ) -> None:
        super().__init__(
            title,
            message,
            [
                DialogButton(cancel_label, False, "cancel-btn"),
                DialogButton(confirm_label, True, "confirm-btn", kind="danger"),
            ],
            detail=detail,
            escape=False,
        )

"""The NOT_GIVEN sentinel for settings left unset."""


class NotGiven:
    pass


NOT_GIVEN = NotGiven()


def is_given(value) -> bool:
    return not isinstance(value, NotGiven)

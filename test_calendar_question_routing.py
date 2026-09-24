from features.memory import is_calendar_question


def test_calendar_questions_bypass_memory_extraction():
    assert is_calendar_question("What meetings do I have this week?")
    assert is_calendar_question("Am I free at 4?")
    assert is_calendar_question("What's tomorrow like?")


def test_non_calendar_message_is_not_routed_as_calendar():
    assert not is_calendar_question("Remember my brother Rahul")

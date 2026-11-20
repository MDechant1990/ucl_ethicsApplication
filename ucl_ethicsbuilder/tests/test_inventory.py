"""Offline tests for the form inventory parser (no browser needed)."""
import json

from filler.inventory import dependencies, questions, resolve


def row(items, qid="row1", help_=""):
    return {"question_id": qid, "panel_id": "panel1", "items": items, "help": help_,
            "mandatory": True, "repeatable": False, "visible_now": False}


def radio(label, bit):
    return {"type": "radio", "label": label, "bit": bit, "options": None}


def test_row_with_two_numbered_questions_is_split():
    qs = questions(row([{"text": "A2.1) Which organisation?"}, {"type": "textarea", "label": "", "bit": None,
                                                                 "options": None},
                        {"text": "A2.2) Why UCL review?"}, {"type": "textarea", "label": "", "bit": None,
                                                           "options": None}]))
    assert [(q["number"], q["text"], q["n_text_boxes"]) for q in qs] == [
        ("A2.1", "Which organisation?", 1), ("A2.2", "Why UCL review?", 1)]


def test_number_and_text_in_separate_labels_and_help_that_repeats_the_question_is_dropped():
    q = questions(row([{"text": "A2)"}, {"text": "Is UCL the lead sponsor?"}, radio("Yes", "1"), radio("No", "2")],
                      help_="Is UCL the lead sponsor? The sponsor is ..."))[0]
    assert (q["number"], q["text"], q["kinds"], q["help"]) == ("A2", "Is UCL the lead sponsor?", ["radio"], "")
    assert [o["label"] for o in q["options"]] == ["Yes", "No"]


def test_rules_are_resolved_to_question_numbers_and_option_labels():
    a2 = questions(row([{"text": "A2) Lead sponsor?"}, radio("Yes", "1"), radio("No", "2")], qid="src"))
    a21 = questions(row([{"text": "A2.1) Which organisation?"}], qid="tgt"))
    pages = {"1599": {"name": "A", "questions": a2 + a21}}
    rules = resolve(pages, [{"SourceQuestionId": "src", "TargetQuestionId": "tgt", "ConditionTrueJson": "[2]",
                             "AndGroupId": 1, "DependencyActionId": 1, "DependencyOperatorId": 1}])
    assert [(r["target"], r["source"], r["when"]) for r in rules] == [("A2.1", "A2", ["No"])]


def test_dependencies_are_read_from_both_json_blocks():
    dep = {"SourceQuestionId": "s", "TargetQuestionId": "t", "ConditionTrueJson": "[1]"}
    group = {"Contracts": [{"SourceQuestionId": "s2", "DependentQuestionId": "t2", "DependentPanelId": "p2",
                            "RequiredValuesJson": "[2]", "AndId": 1, "Action": 1, "Operator": 1}]}
    html = (f"var dependencies = JSON.parse('{json.dumps([dep])}');\n"
            f"var groups = JSON.parse('{json.dumps([group])}');")
    found = dependencies(html)
    assert [(d["SourceQuestionId"], d["TargetQuestionId"]) for d in found] == [("s", "t"), ("s2", "t2")]

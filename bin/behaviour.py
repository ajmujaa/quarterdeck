#!/usr/bin/env python3
"""behaviour: does an acceptance check, or a test file, make the thing DO something, or only prove that it exists? (#86)

    behaviour.py accept < text      exit 0 when the check exercises behaviour (or says nothing about existence), 1 when it only looks for a thing
    behaviour.py test FILE          the same for a test file

A heuristic on purpose: it rejects the plain cases (grep for an id, the string is in the page, querySelector is not null) and lets
anything it cannot tell through. Standard library only.
"""
import re
import sys

# words that describe a person or program doing something and seeing a result
ACTION = re.compile(r"\b(click|clicks|clicked|press|presses|tap|taps|type|types|enter|submit|submits|selects|hover|drag|focuses|toggles?|call|calls|"
                    r"invoke[sd]?|run|runs|send|sends|posts|requests|after|when|then|navigates?|within|equals?|is (?:empty|disabled|enabled|hidden|shown))\b", re.I)
EXIST = re.compile(r"(\bgrep\b|\bexists?\b|\bis present\b|\bis defined\b|\bis in the (?:page|html|source|file)\b|\bcontains (?:the |a |an )?(?:string|text|selector|element|id|class|word|label)\b|"
                   r"queryselector|getelementbyid|\bselector\b|\bis rendered\b|\bis visible on the page\b)", re.I)

T_ACTION = re.compile(r"(\.click\(|\bclick\(|dispatchEvent|fireEvent|userEvent|\.press\(|\.type\(|\.fill\(|\.check\(|\.hover\(|\.focus\(|\.keyboard|\.submit\(|sendKeys|"
                      r"subprocess|spawn|execSync|exec\(|fetch\(|\.post\(|\.request\(|client\.|\.invoke\(|\.trigger\(|\.value\s*=|\.select_option|\.dispatch|"
                      r"\bimport\b|\brequire\(|\bfrom \w+ import\b|\w+\([^)]*\)\s*(?:==|!=|\)\.(?:toBe|toEqual)))", re.I)
T_EXIST = re.compile(r"(toBeInTheDocument|toBeVisible|toBeTruthy|toBeDefined|not\.toBeNull|is not None|querySelector|getElementById|getByRole|getByText|"
                     r"\"[^\"]+\"\s+in\s+\w+|'[^']+'\s+in\s+\w+|\.includes\(|toContain\(|toMatch\(|grep|\.exists\(|existsSync|open\([^)]*\)\.read\(\)|readFileSync)", re.I)


def accept_exercises_behaviour(text):
    return bool(ACTION.search(text)) or not EXIST.search(text)


def test_exercises_behaviour(text):
    if not T_EXIST.search(text):
        return True
    # a file that reads another file as text and looks inside it is a grep, even if it also imports something
    reads_source = re.search(r"open\([^)]*\)\.read\(\)|readFileSync|read_text\(\)|\.read\(\)", text)
    if reads_source and not re.search(r"(\.click\(|dispatchEvent|fireEvent|userEvent|subprocess|spawn|execSync|fetch\(|\.post\(|client\.)", text):
        return False
    return bool(T_ACTION.search(text))


if __name__ == "__main__":
    if sys.argv[1:2] == ["accept"]:
        sys.exit(0 if accept_exercises_behaviour(sys.stdin.read()) else 1)
    if sys.argv[1:2] == ["test"] and len(sys.argv) > 2:
        sys.exit(0 if test_exercises_behaviour(open(sys.argv[2], errors="replace").read()) else 1)
    sys.exit(2)

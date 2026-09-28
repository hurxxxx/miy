"""Lossless compact observations: the model must keep seeing all public facts."""

import re

import pytest

from open_work_hub_api.domains.tetris import ai
from open_work_hub_api.domains.tetris.schemas import TetrisCandidate, TetrisObservation


def _fields(text):
    return dict(re.findall(r"(\w+)=([^\s]+)", text))


def _assert_landing(fields, source):
    decoded = {
        "target": {
            "kind": fields["piece"], "x": int(fields["x"]), "y": int(fields["y"]),
            "shape": [[int(cell) for cell in row] for row in fields["shape"].split("/")],
        },
        "piece": fields["piece"],
        "uses_hold": fields["hold"] == "1",
        "hold_after": None if fields["reserve"] == "-" else fields["reserve"],
        **{
            name: int(fields[label])
            for name, label in {
                "cleared_lines": "clear", "holes": "holes", "max_height": "height",
                "aggregate_height": "sum_height", "bumpiness": "roughness", "key_presses": "keys",
            }.items()
        },
    }
    assert decoded == source
    assert int(fields["attack"]) == max(0, source["cleared_lines"] - 1)


def test_board_and_active_pose_round_trip_without_losing_public_cells():
    cells = [None, "I", "J", "L", "O", "S", "T", "Z", "garbage"]
    board = [[cells[(y * 10 + x) % len(cells)] for x in range(10)] for y in range(20)]
    source = {
        "board": board,
        "active": {"kind": "T", "shape": [[0, 1, 0], [0, 1, 1], [0, 1, 0]], "x": -1, "y": 12},
        "next": "I", "hold": "O", "can_hold": False, "score": 3456, "lines": 23, "level": 3,
    }
    compact = ai._observation(TetrisObservation.model_validate(source))
    assert len(compact["board"]) == 20
    assert all(len(row) == 10 for row in compact["board"])
    compact["board"] = [
        [None if cell == "." else "garbage" if cell == "G" else cell for cell in row]
        for row in compact["board"]
    ]
    compact["active"]["shape"] = [[int(cell) for cell in row] for row in compact["active"]["shape"]]
    assert compact == source


def test_all_32_candidates_keep_metrics_and_both_exclusive_forecasts():
    # Distinct extremes catch omissions, swapped columns and accidental pruning.
    descriptions = []
    for index in range(32):
        landing = {
            "piece": "T", "uses_hold": bool(index % 2), "hold_after": "O",
            "target": {"kind": "T", "shape": [[0, 1, 0], [1, 1, 1], [0, 0, 0]], "x": index % 8, "y": 18},
            "cleared_lines": index % 5, "holes": 200 - index, "max_height": 20,
            "aggregate_height": 200 - index, "bumpiness": 180 - index, "key_presses": 64 - index,
        }
        future = [
            {**landing, "piece": "I", "uses_hold": False, "cleared_lines": 4, "key_presses": 2,
             "target": {"kind": "I", "shape": [[0, 0, 0, 0], [1, 1, 1, 1], [0, 0, 0, 0], [0, 0, 0, 0]], "x": 3, "y": 18}},
            {**landing, "piece": "O", "uses_hold": True, "hold_after": "I", "cleared_lines": 2,
             "target": {"kind": "O", "shape": [[1, 1], [1, 1]], "x": 8, "y": 18}},
        ]
        candidate = TetrisCandidate(
            **landing, action="hold" if landing["uses_hold"] else "left",
            next_piece="I", next_spawn_blocked=False, follow_ups=future,
        )
        description = ai._candidate_description(candidate)
        descriptions.append(description)
        lines = description.splitlines()
        assert len(lines) == 4
        _assert_landing(_fields(lines[0]), landing)
        assert _fields(lines[1]) == {"next": "I", "spawn_blocked": "0"}
        for line, expected in zip(lines[2:], future, strict=True):
            fields = _fields(line)
            _assert_landing(fields, expected)
            assert int(fields["total_clear"]) == landing["cleared_lines"] + expected["cleared_lines"]
            assert int(fields["total_attack"]) == (
                max(0, landing["cleared_lines"] - 1) + max(0, expected["cleared_lines"] - 1)
            )
    # Representation-growth guard, not a tokenizer-independent context guarantee.
    assert sum(len(text.encode()) for text in descriptions) < 18_000


@pytest.mark.parametrize("next_piece, blocked", [(None, None), ("I", True)])
def test_unknown_next_and_top_out_are_distinct(next_piece, blocked):
    candidate = TetrisCandidate(
        piece="T", uses_hold=True, hold_after="O", cleared_lines=0, holes=2,
        target={"kind": "T", "shape": [[0, 1, 0], [1, 1, 1], [0, 0, 0]], "x": 0, "y": 18},
        max_height=20, aggregate_height=40, bumpiness=4, key_presses=1,
        action="hold", next_piece=next_piece, next_spawn_blocked=blocked, follow_ups=[],
    )
    lines = ai._candidate_description(candidate).splitlines()
    assert len(lines) == 2
    assert _fields(lines[1]) == {
        "next": "unknown" if next_piece is None else "I",
        "spawn_blocked": "unknown" if blocked is None else "1",
    }

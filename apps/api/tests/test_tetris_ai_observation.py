"""Lossless compact observations: the model must keep seeing all public facts."""

import re


def _fields(text):
    return dict(re.findall(r"(\w+)=([^\s]+)", text))


def _assert_landing(fields, source):
    decoded = {
        "target": {
            "kind": fields["piece"],
            "x": int(fields["x"]),
            "y": int(fields["y"]),
            "shape": [[int(cell) for cell in row] for row in fields["shape"].split("/")],
        },
        "piece": fields["piece"],
        "uses_hold": fields["hold"] == "1",
        "hold_after": None if fields["reserve"] == "-" else fields["reserve"],
        "wells": []
        if fields["wells"] == "-"
        else [
            dict(
                zip(
                    ("column", "depth", "ready_rows", "filled_cells"),
                    map(int, well.split(":")),
                    strict=True,
                )
            )
            for well in fields["wells"].split(",")
        ],
        **{
            name: int(fields[label])
            for name, label in {
                "cleared_lines": "clear",
                "holes": "holes",
                "max_height": "height",
                "aggregate_height": "sum_height",
                "bumpiness": "roughness",
                "key_presses": "keys",
            }.items()
        },
    }
    assert decoded == source
    assert int(fields["attack"]) == max(0, source["cleared_lines"] - 1)

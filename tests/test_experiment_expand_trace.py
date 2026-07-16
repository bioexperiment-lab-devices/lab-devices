"""Source-map tests for expand_dict_traced (design 2026-07-16 §5.3)."""

from lab_devices.experiment.expand import expand_dict, expand_dict_traced


def test_traced_output_matches_untraced():
    wf = {
        "schema_version": 1,
        "blocks": [
            {"for_each": {"var": "t", "in": [1, 2], "body": [{"wait": {"duration": "1s"}}]}}
        ],
    }
    expanded, _ = expand_dict_traced(wf)
    assert expanded == expand_dict(wf)


def test_for_each_copies_all_trace_to_the_one_authored_body_block():
    wf = {
        "schema_version": 1,
        "blocks": [
            {"for_each": {"var": "t", "in": [1, 2, 3], "body": [{"wait": {"duration": "{t}s"}}]}}
        ],
    }
    expanded, trace = expand_dict_traced(wf)
    assert len(expanded["blocks"]) == 3
    for i in range(3):
        assert trace[f"blocks[{i}]"] == "blocks[0].body[0]"


def test_blocks_after_a_splice_trace_to_their_shifted_authored_index():
    wf = {
        "schema_version": 1,
        "blocks": [
            {"for_each": {"var": "t", "in": [1, 2], "body": [{"wait": {"duration": "{t}s"}}]}},
            {"wait": {"duration": "9s"}},
        ],
    }
    expanded, trace = expand_dict_traced(wf)
    assert len(expanded["blocks"]) == 3
    # The trailing wait is authored blocks[1] but lands at expanded blocks[2].
    assert trace["blocks[2]"] == "blocks[1]"


def test_container_children_trace_through():
    wf = {
        "schema_version": 1,
        "blocks": [
            {
                "parallel": {
                    "children": [
                        {
                            "for_each": {
                                "var": "t", "in": [1, 2],
                                "body": [{"wait": {"duration": "{t}s"}}],
                            }
                        }
                    ]
                }
            }
        ],
    }
    expanded, trace = expand_dict_traced(wf)
    lanes = expanded["blocks"][0]["parallel"]["children"]
    assert len(lanes) == 2  # sole child of a parallel -> N lanes
    assert trace["blocks[0]"] == "blocks[0]"
    for i in range(2):
        assert trace[f"blocks[0].children[{i}]"] == "blocks[0].children[0].body[0]"


def test_parametrized_group_ref_body_traces_into_the_groups_dict():
    wf = {
        "schema_version": 1,
        "groups": {"service": {"params": ["tube"], "body": [{"wait": {"duration": "{tube}s"}}]}},
        "blocks": [{"group_ref": {"name": "service", "args": {"tube": 1}}}],
    }
    expanded, trace = expand_dict_traced(wf)
    # A parametrized group_ref inlines as a single Serial carrying the ref's block-level keys.
    assert "serial" in expanded["blocks"][0]
    assert trace["blocks[0]"] == "blocks[0]"
    assert trace["blocks[0].children[0]"] == "groups['service'].body[0]"


def test_nested_for_each_inside_a_parametrized_group_traces_to_the_group_body():
    wf = {
        "schema_version": 1,
        "groups": {
            "svc": {
                "params": ["tube"],
                "body": [
                    {
                        "for_each": {
                            "var": "i", "in": [1, 2],
                            "body": [{"wait": {"duration": "{i}s"}}],
                        }
                    }
                ],
            }
        },
        "blocks": [{"group_ref": {"name": "svc", "args": {"tube": 1}}}],
    }
    expanded, trace = expand_dict_traced(wf)
    kids = expanded["blocks"][0]["serial"]["children"]
    assert len(kids) == 2
    for i in range(2):
        assert trace[f"blocks[0].children[{i}]"] == "groups['svc'].body[0].body[0]"


def test_plain_group_body_indices_shift_when_a_for_each_inside_it_splices():
    wf = {
        "schema_version": 1,
        "groups": {
            "wash": {
                "body": [
                    {
                        "for_each": {
                            "var": "i", "in": [1, 2],
                            "body": [{"wait": {"duration": "{i}s"}}],
                        }
                    },
                    {"wait": {"duration": "9s"}},
                ]
            }
        },
        "blocks": [{"group_ref": {"name": "wash"}}],
    }
    expanded, trace = expand_dict_traced(wf)
    # A plain (param-less) group_ref is preserved for lazy inlining, but its body IS expanded.
    assert "group_ref" in expanded["blocks"][0]
    assert len(expanded["groups"]["wash"]["body"]) == 3
    assert trace["groups['wash'].body[2]"] == "groups['wash'].body[1]"


def test_a_macro_free_workflow_traces_every_block_to_itself():
    wf = {
        "schema_version": 1,
        "blocks": [{"serial": {"children": [{"wait": {"duration": "1s"}}]}}],
    }
    _, trace = expand_dict_traced(wf)
    assert trace["blocks[0]"] == "blocks[0]"
    assert trace["blocks[0].children[0]"] == "blocks[0].children[0]"

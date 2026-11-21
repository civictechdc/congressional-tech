"""CPU/model-lane verification of `per_doc_grammar_v6`, `TelemetryPerDocWrapperV6`, leading-whitespace rejection, and `:` vs `: `."""

from __future__ import annotations

import json
from typing import Any

import pytest

pytest.importorskip("fast_gemma4", reason="needs the fast-gemma4 engine; run scripts/dev.py test docmeta-model")


def test_per_doc_grammar_v6_leading_whitespace_and_separators() -> None:
    """Verify `per_doc_grammar_v6` + `TelemetryPerDocWrapperV6` reject leading whitespace and honor `upfront_ff_for_doc` across `:` vs `: `."""
    from fast_gemma4.grammar import GrammarHelper
    from fast_gemma4.paths import resolve_paths
    from fast_gemma4.tokenizer import FastGemma4Tokenizer, VocabRemapper

    from congress_docmeta.compact_wire_v6 import DOCMETA_V6_COMPACT_SCHEMA_STR
    from congress_docmeta.pythonic_v6 import SCHEMA_V4_STR, per_doc_grammar_v6
    from congress_docmeta.telemetry_v6 import TelemetryMatcherProxyV6, TelemetryPerDocWrapperV6

    paths = resolve_paths()
    tok_json = paths.resolve_tokenizer_json(local_files_only=True)
    tok = FastGemma4Tokenizer(tok_json)
    rem = VocabRemapper.load_or_build(tok_json, paths.vocab_remap_npz)

    compact_payload = {
        "st": "usable",
        "tq": "native",
        "ch": "house",
        "cg": 118,
        "cm": ["Committee on Energy and Commerce"],
        "pk": "witness_statement",
        "ps": [{"n": "Jane Doe", "r": "witness", "e": "non_gov_person"}],
        "ct": "Statement of Jane Doe",
        "gi": "Jane Doe testifies.",
        "tp": ["energy"],
    }
    v4_payload = {
        "status": "usable",
        "text_quality": "native",
        "chamber": "house",
        "congress": 118,
        "committees": ["Committee on Energy and Commerce"],
        "primary_kind": "witness_statement",
        "personas": [{"name": "Jane Doe", "role": "witness", "entity_type": "non_gov_person"}],
        "composed_title": "Statement of Jane Doe",
        "gist": "Jane Doe testifies.",
        "topics": ["energy"],
    }
    leading_ws_toks = tok.encode("  \n{", add_special_tokens=False)

    for wire_fmt, schema_str, payload in (
        ("compact", DOCMETA_V6_COMPACT_SCHEMA_STR, compact_payload),
        ("v4", SCHEMA_V4_STR, v4_payload),
    ):
        for wf_arg, expected_sep in ((False, (",", ":")), (None, (",", ": "))):
            gh_std = GrammarHelper(tok, schema_str, rem.kept_old_ids, whitespace_flexible=wf_arg)
            assert gh_std.separators == expected_sep
            assert not gh_std.new_matcher().validate_tokens(leading_ws_toks)

            cache: dict[object, tuple[Any, ...]] = {}
            targets = {0: "witness_statement", 2: "witness_statement|qfr_response"}
            order = [0, 1, 2]
            pdg = per_doc_grammar_v6(
                gh_std,
                order,
                wire_format=wire_fmt,
                doc_target_kinds=targets,
                grammar_cache=cache,
                sync_ff_with_std=True,
            )
            wrapped = TelemetryPerDocWrapperV6(pdg, force_greedy=True)

            sample_ids = tok.encode(json.dumps(payload, separators=expected_sep), add_special_tokens=False)
            other_sep = (",", ": ") if expected_sep == (",", ":") else (",", ":")
            other_ids = tok.encode(json.dumps(payload, separators=other_sep), add_special_tokens=False)

            for d in order:
                up = wrapped.upfront_ff_for_doc(d)
                assert up == pdg.upfront_ff_for_doc(d)
                assert sample_ids[: len(up)] == up

                m = wrapped.new_matcher_for_doc(d)
                assert isinstance(m, TelemetryMatcherProxyV6)
                assert m.doc_idx == d
                assert not m.validate_tokens(leading_ws_toks)
                consumed = m.try_consume_tokens(sample_ids[len(up) :])
                assert consumed == len(sample_ids) - len(up)
                assert m.is_accepting()

                m_other = pdg.new_matcher_for_doc(d)
                ok_other = other_ids[: len(up)] == up and (
                    m_other.try_consume_tokens(other_ids[len(up) :]) == len(other_ids) - len(up)
                )
                assert not ok_other

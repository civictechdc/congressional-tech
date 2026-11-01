"""Unit tests for fold_pdf_text (ct-jinw)."""

from pathlib import Path

from congress_api.lake import appearance_records, readings
from congress_api.lake.pdf_text import fold_pdf_text
from congress_api.parsers import text as parsers_text
from congress_api.parsers.text import fold_pdf_text as parser_fold_pdf_text


def test_fold_pdf_text_folds_ligatures_and_hyphens_and_preserves_legal_punctuation():
    assert fold_pdf_text is parser_fold_pdf_text
    assert fold_pdf_text.__module__ == "congress_api.parsers.text"
    sample = (
        "The \ufb01rst o\ufb03cial \ufb02oating e\ufb00ect, wa\ufb04e, \ufb05ate, and \ufb06op "
        "in H.R.\u20101234 and S.\u2011567 \u2014 see \u00a7 101\u2013102 (\u00bd share, x\u00b2)."
    )
    folded = fold_pdf_text(sample)
    assert folded == (
        "The first official floating effect, waffle, state, and stop "
        "in H.R.-1234 and S.-567 \u2014 see \u00a7 101\u2013102 (\u00bd share, x\u00b2)."
    )
    assert fold_pdf_text("") == ""
    assert readings.current_version("sniff")


def test_appearance_records_versions_do_not_depend_on_fold_pdf_text(monkeypatch):
    baseline = appearance_records.current_versions()
    orig_ast_digest = appearance_records.source_ast_digest
    text_file = Path(parsers_text.__file__).resolve()
    queried_text_symbols: list[tuple[str, ...]] = []

    def tracking_ast_digest(path, symbols):
        if Path(path).resolve() == text_file:
            queried_text_symbols.append(tuple(symbols))
            assert "fold_pdf_text" not in symbols
            assert "_PDF_TEXT_FOLD_TABLE" not in symbols
        return orig_ast_digest(path, symbols)

    monkeypatch.setattr(appearance_records, "source_ast_digest", tracking_ast_digest)
    assert appearance_records.current_versions() == baseline
    assert queried_text_symbols


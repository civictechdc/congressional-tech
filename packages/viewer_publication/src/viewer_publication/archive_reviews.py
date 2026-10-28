"""Native duplicate review edges and display decisions after final grouping."""
from pathlib import Path

ROOT=Path(__file__).parents[4]


def _steps(names,root):
    return [dict(name=name.replace('-','_'),sql=(Path(root)/'model/sql'/('reviews-'+name+'.sql')).read_text(),materialize=True)
            for name in names]


def duplicate_steps(*,root=ROOT):
    """Resolve duplicate reviews over initial keys before the second native graph.

    Inputs: current_reviews, initial_document_link_keys(component,link_key),
    component_members(component). The caller must refuse document_link_key_conflicts;
    review_link_diagnostics reports unresolved records without discarding evidence.
    """
    return _steps(['document-link-key-conflicts','duplicate-component-edges','review-link-diagnostics'],root)


def application_steps(*,root=ROOT):
    """Apply latest remaining review values against final document membership.

    Inputs: current_reviews, final document_link_keys(component,link_key), and
    document_identities(component,document_id). The caller must refuse
    review_value_diagnostics before accepting a release; review_overrides supplies
    one row per component with nullable title/kind replacements and explicit hide.
    """
    return _steps(['review-selected','review-kind-items','review-value-diagnostics',
                   'review-kind-overrides','review-overrides'],root)

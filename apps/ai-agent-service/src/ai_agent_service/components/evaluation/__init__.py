"""Evaluation: the measures. ``docs/design.md`` section 9.

The official numbers are the organisers' ``eval/reference_eval.py`` over our
trace; running the scenarios is ``src/pipeline/eval``. This package holds
the instruments the trace needs and the ones the design adds:

- :mod:`.scorers`: the extractor that labels each agent turn's questions and
  claims, with fixed vocabularies and a shared cache (section 9.4);
- :mod:`.rubric`: the organisers' rubric J01 to J12, one measure used by the
  QaAgent on every call, by the judge and by people (section 9.7). Not built;
- :mod:`.calibration`: agreement between the judge and a person, as Cohen's
  kappa (section 9.7). Not built.
"""

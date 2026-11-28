"""Evaluation: the measures.

The official numbers are the organisers' ``eval/reference_eval.py`` over our
trace; running the scenarios is ``src/pipeline/eval``. This package holds
the instrument the trace needs: :mod:`.scorers`, the extractor that labels
each agent turn's questions and claims, with fixed vocabularies and a shared
cache.
"""

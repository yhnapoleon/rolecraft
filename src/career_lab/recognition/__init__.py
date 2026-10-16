"""Pattern-recognition layer: the recognizers that decide or annotate every LLM input.

Each recognizer returns a ``RecognitionRecord`` (``contracts/v2/recognition.py``). Every
recognizer has a rule fallback, so the product runs unchanged when
``CAREER_LAB_RECOGNIZERS`` is unset or a weight directory fails its hash check.

Modules: ``units``/``retrieval`` (C2), ``relation`` (C1 via ``models/v3``), ``decision``
(C6 and the arbiter), ``scope`` (C4 and drift), ``intent`` (C11), ``behavior`` (C5),
``reply`` (C10), ``provenance`` (N5), ``registry`` (loading).
"""

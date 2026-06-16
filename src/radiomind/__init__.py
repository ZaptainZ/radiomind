"""RadioMind — Bionic memory core for AI agents.

Two methodology primitives are exported at the package root so they
are reachable from anywhere with a single import — both are intended
to be ubiquitous, not buried under refinement/.

  trinity   — N-party / multi-round / multi-layer debate primitive.
              `from radiomind import trinity` then call any of:
                  trinity.debate(task, evidence, llm, ...)   # full control
                  trinity.fast(task, evidence, llm)          # 1-round, 3 stances
                  trinity.balanced(task, evidence, llm)      # 2 rounds
                  trinity.deep(task, evidence, llm)          # 3 rounds + depth-1 sub
                  trinity.parties(N, task, evidence, llm)    # N-party
  attention — query attention signature (`analyze(query)` → wants /
              focus / aux_flags). Use to route off intent.
              `from radiomind import attention` then `attention.analyze(...)`.
"""

__version__ = "0.2.1"

from radiomind.core.mind import RadioMind
from radiomind.simple import SimpleRadioMind, connect
from radiomind.protocol import MemoryProtocol, Memory, AddResult, RefineResult
from radiomind.refinement import trinity
from radiomind.core import attention

__all__ = [
    "RadioMind",
    "SimpleRadioMind",
    "connect",
    "MemoryProtocol",
    "Memory",
    "AddResult",
    "RefineResult",
    # Core methodology primitives — call from anywhere.
    "trinity",
    "attention",
]

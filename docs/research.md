# Research and design context

The Data Parasite is an applied research prototype. The papers below provide context for its design; they are not claims of equivalence, reproduction, or comparative performance. The project implementation and its evaluation determine what the system actually does.

## Architecture and memory

- **CoALA** describes language agents through modular memory, action spaces, and decision processes. It offers a useful vocabulary for discussing an agent that coordinates memory and tools: Sumers et al., [“Cognitive Architectures for Language Agents”](https://arxiv.org/abs/2309.02427) (2023).
- **Generative Agents** explores storing experiences, forming reflections, and retrieving memories to guide later behavior. It is relevant background for separating remembered events from higher-level knowledge: Park et al., [“Generative Agents: Interactive Simulacra of Human Behavior”](https://arxiv.org/abs/2304.03442) (2023).
- **GraphRAG** builds a graph index and community summaries for query-focused summarization over document collections. It motivates graph-based retrieval as a research direction, but does not by itself describe this project's memory model: Edge et al., [“From Local to Global: A Graph RAG Approach to Query-Focused Summarization”](https://arxiv.org/abs/2404.16130) (2024).

## Related memory systems

- **MemGPT** studies virtual context management across memory tiers for long conversations and document analysis. It is related work on context and memory management; The Data Parasite does not claim to implement MemGPT: Packer et al., [“MemGPT: Towards LLMs as Operating Systems”](https://arxiv.org/abs/2310.08560) (2023).
- **A-MEM** proposes agentic notes, links between memories, and updates to existing memory representations as new memories arrive. Its temporal update ideas are relevant background for this project's evolving semantic memory, without implying a reproduction of A-MEM: Xu et al., [“A-MEM: Agentic Memory for LLM Agents”](https://arxiv.org/abs/2502.12110) (2025).

These references are cited for conceptual context. Use the linked papers for their methods, results, and bibliographic details.

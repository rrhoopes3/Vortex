# The Presidential Council - Grok 4.20 Multi-Agent Think Tank

## Overview

This is a novel multi-agent wrapper using xAI's Grok 4.20 multi-agent experimental API. Instead of generic roles, it frames the agents as Olympian gods from Greek mythology. This creates natural role differentiation, memorable personalities, and productive tension between different modes of thinking.

## Agent Roles (The Core Council)

**Zeus** (Lead/Synthesis)
- Strategic oversight
- Final decision making
- Ethical boundaries
- High-level synthesis

**Athena** (Wisdom & Strategy)
- Structured reasoning
- Long-term planning
- Clarity and wisdom
- Battle tactics (metaphorical)

**Hephaestus** (The Forge)
- Practical implementation
- Code and tool usage
- Building working artifacts
- Craftsmanship and engineering

**Hermes** (The Messenger)
- Rapid research (web_search, x_search)
- Communication between agents
- Connecting ideas across domains
- Speed and adaptability

**Wildcard** (dynamic)
- The 4 agents will invoke additional divine perspectives (Dionysus for chaos, Apollo for pattern recognition, Hades for risk) as needed

## How It Works

1. **System Prompt**: A single unified prompt defines all divine roles and behavioral guidelines. The multi-agent model internally coordinates between them.

2. **Persistent History**: Conversations are saved to `pantheon_history.json` so the gods "remember" previous sessions.

3. **Streaming Feedback**: Shows reasoning tokens ("gods debating") and then the synthesized response.

4. **Tool Access**: All agents share access to web search, X search, and code execution.

5. **Ethical Guardrails**: Explicitly restricts to authorised pentesting, CTF, research, and creative work.

## Usage

```bash
python lads_war_room.py
```

The script has been updated to use the Pantheon theme. Type your queries and the gods will deliberate.

## Why This Concept Works Well

- **Memorable personalities** make agent contributions easier to track
- **Natural role specialization** leverages the multi-agent architecture
- **Mythological framing** encourages creative, high-quality outputs
- **Easy to extend** — currently limited to 4 or 16 agents by the API. 16-agent mode can summon the full pantheon

## Future Improvements

- YAML-based persona system for easily swapping between different "councils"
- Dynamic agent summoning mid-conversation
- Role-specific streaming output
- Meta-agent that can call for specific gods

The Pantheon is particularly effective for complex problem solving, system design, creative strategy, and technical architecture.

**Note**: Switched to 16-agent mode as you have access. This allows the full pantheon to participate.

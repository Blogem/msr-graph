## ADDED Requirements

### Requirement: Server LLM configuration for the analysis agent
The `server` service SHALL be configured with the analysis-agent LLM settings so it can reach DeepSeek V4 Pro at runtime: `DEEPSEEK_BASE_URL` (the OpenAI-compatible base URL) and `LLM_MODEL_ANALYSIS` (the analysis model identifier). These are additive environment changes to the `server` service in `docker-compose.yml`. The LLM client SHALL be constructed from this configuration behind an injected interface, and no API secret SHALL be committed to the repository.

#### Scenario: Server has the analysis LLM configuration
- **WHEN** the Compose stack is brought up
- **THEN** the `server` service environment provides `DEEPSEEK_BASE_URL` and `LLM_MODEL_ANALYSIS` used to construct the analysis LLM client

#### Scenario: No API secret committed
- **WHEN** the repository is inspected for the DeepSeek API key
- **THEN** the key is supplied at runtime via environment/secret and is not committed to the repository

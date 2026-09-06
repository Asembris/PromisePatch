"""The semantic boundary: bounded questions to a model, validated answers, no authority.

The model understands; the deterministic protocol authorizes. Everything reachable from here
is a proposal, and nothing here can write a row, record a consent decision, attest a physical
fact, select a recovery or send a message.
"""

from promisepatch.semantic.contracts import (
    ApparentIntent,
    CandidateBinding,
    CandidateCommitment,
    CandidateCommitmentLine,
    CandidateEquipment,
    CandidateNodeType,
    CandidateResource,
    ClarificationContext,
    ClassifyReplyIntentRequest,
    EvidenceFact,
    InterpretUtteranceRequest,
    ObservationInterpretation,
    ReplyIntentReading,
    SemanticJob,
    SemanticMetadata,
    SemanticRequest,
    SemanticValue,
    UntrustedText,
    Verbalisation,
    VerbaliseRequest,
)
from promisepatch.semantic.errors import (
    SemanticError,
    SemanticProviderError,
    SemanticTimeoutError,
    SemanticValidationError,
    ValidationFailure,
)
from promisepatch.semantic.fake import FakeSemanticProvider
from promisepatch.semantic.jobs import JOB_SPECS, JobSpec, spec_for, validate
from promisepatch.semantic.provider import (
    Attempt,
    SemanticProvider,
    SemanticResult,
    SemanticTelemetry,
    SemanticUsage,
    StructuredSemanticProvider,
    tool_definition,
)

__all__ = [
    "JOB_SPECS",
    "ApparentIntent",
    "Attempt",
    "CandidateBinding",
    "CandidateCommitment",
    "CandidateCommitmentLine",
    "CandidateEquipment",
    "CandidateNodeType",
    "CandidateResource",
    "ClarificationContext",
    "ClassifyReplyIntentRequest",
    "EvidenceFact",
    "FakeSemanticProvider",
    "InterpretUtteranceRequest",
    "JobSpec",
    "ObservationInterpretation",
    "ReplyIntentReading",
    "SemanticError",
    "SemanticJob",
    "SemanticMetadata",
    "SemanticProvider",
    "SemanticProviderError",
    "SemanticRequest",
    "SemanticResult",
    "SemanticTelemetry",
    "SemanticTimeoutError",
    "SemanticUsage",
    "SemanticValidationError",
    "SemanticValue",
    "StructuredSemanticProvider",
    "UntrustedText",
    "ValidationFailure",
    "Verbalisation",
    "VerbaliseRequest",
    "spec_for",
    "tool_definition",
    "validate",
]

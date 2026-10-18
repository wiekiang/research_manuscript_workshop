"""Model gateway (PRODUCT_SPEC §4): one typed interface for generation/review calls.

Every call is (1) authorized by the API against provider gates, data classification, the project owner's
data-flow attestation, input rights and the cost ceiling; (2) executed by the configured provider with a
token ceiling and timeout; (3) schema-validated, with exactly one repair attempt; (4) reported back to the API
with tokens/cost so the ledger and budget stay authoritative. A completed call is cached by idempotency key,
so a retried activity never re-bills or changes its answer.
"""

from .core import GatewayError, ModelCall, ModelGateway, ModelResult, strict_json_schema

__all__ = ["GatewayError", "ModelCall", "ModelResult", "ModelGateway", "strict_json_schema"]

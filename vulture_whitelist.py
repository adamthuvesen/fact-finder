# Real false positives only. Vulture cannot see these uses.
# Pydantic reads declared fields from the JSON schema and from `model_dump`.
route  # evidence.Source field
accessed_at  # evidence.Source field
independence_group  # evidence.Source field
consequence  # evidence.Coverage field
schema_version  # evidence.Evidence and evidence.Review field
objection  # evidence.Objection field
resolution  # evidence.Objection field
strongest_alternative  # evidence.Review field
weakest_claim  # evidence.Review field
fragile_dependency  # evidence.Review field
accepted_at  # validation.Override field, written to overrides.json
# decimal.localcontext reads this attribute.
prec  # evidence._calculation_error

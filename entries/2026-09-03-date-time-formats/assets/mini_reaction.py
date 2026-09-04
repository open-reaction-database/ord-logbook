# Copyright 2026 Open Reaction Database Project Authors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""A cut-down Reaction proto holding only the paths that reach a DateTime.

Reaction has seven positions where a ``DateTime`` can appear. Parsing the full
message to read them costs far more than the values are worth over a 2.4M-row
corpus, so this module builds a message whose fields are exactly those paths,
with the schema's own field numbers. The wire format makes everything else an
unknown field, which the parser skips at C speed.

The seven positions, as reported by walking the real descriptors::

    inputs{}.components[].analyses{}.instrument_last_calibrated
    workups[].input.components[].analyses{}.instrument_last_calibrated
    outcomes[].products[].measurements[].authentic_standard
        .analyses{}.instrument_last_calibrated
    outcomes[].analyses{}.instrument_last_calibrated
    provenance.experiment_start
    provenance.record_created.time
    provenance.record_modified[].time

Map fields (``inputs``, ``analyses``) are modeled as the repeated key/value
entry messages they are on the wire.
"""

from google.protobuf import descriptor_pb2, descriptor_pool, message_factory

_FIELD = descriptor_pb2.FieldDescriptorProto
_STRING, _MESSAGE = _FIELD.TYPE_STRING, _FIELD.TYPE_MESSAGE
_OPTIONAL, _REPEATED = _FIELD.LABEL_OPTIONAL, _FIELD.LABEL_REPEATED

# name -> [(field name, field number, type, label, message type or None)]
_MESSAGES = {
    "DateTime": [("value", 1, _STRING, _OPTIONAL, None)],
    "Person": [("email", 5, _STRING, _OPTIONAL, None)],
    "RecordEvent": [
        ("time", 1, _MESSAGE, _OPTIONAL, "DateTime"),
        ("person", 2, _MESSAGE, _OPTIONAL, "Person"),
        ("details", 3, _STRING, _OPTIONAL, None),
    ],
    "Analysis": [("instrument_last_calibrated", 7, _MESSAGE, _OPTIONAL, "DateTime")],
    "AnalysisEntry": [
        ("key", 1, _STRING, _OPTIONAL, None),
        ("value", 2, _MESSAGE, _OPTIONAL, "Analysis"),
    ],
    "Compound": [("analyses", 8, _MESSAGE, _REPEATED, "AnalysisEntry")],
    "ReactionInput": [("components", 1, _MESSAGE, _REPEATED, "Compound")],
    "ReactionInputEntry": [
        ("key", 1, _STRING, _OPTIONAL, None),
        ("value", 2, _MESSAGE, _OPTIONAL, "ReactionInput"),
    ],
    "ReactionWorkup": [("input", 4, _MESSAGE, _OPTIONAL, "ReactionInput")],
    "ProductMeasurement": [("authentic_standard", 7, _MESSAGE, _OPTIONAL, "Compound")],
    "ProductCompound": [("measurements", 3, _MESSAGE, _REPEATED, "ProductMeasurement")],
    "ReactionOutcome": [
        ("products", 3, _MESSAGE, _REPEATED, "ProductCompound"),
        ("analyses", 4, _MESSAGE, _REPEATED, "AnalysisEntry"),
    ],
    "ReactionProvenance": [
        ("experiment_start", 3, _MESSAGE, _OPTIONAL, "DateTime"),
        ("record_created", 7, _MESSAGE, _OPTIONAL, "RecordEvent"),
        ("record_modified", 8, _MESSAGE, _REPEATED, "RecordEvent"),
    ],
    "Reaction": [
        ("inputs", 2, _MESSAGE, _REPEATED, "ReactionInputEntry"),
        ("workups", 7, _MESSAGE, _REPEATED, "ReactionWorkup"),
        ("outcomes", 8, _MESSAGE, _REPEATED, "ReactionOutcome"),
        ("provenance", 9, _MESSAGE, _OPTIONAL, "ReactionProvenance"),
    ],
}

EXPERIMENT_START = "provenance.experiment_start"
RECORD_CREATED = "provenance.record_created.time"
RECORD_MODIFIED = "provenance.record_modified[].time"
INPUT_CALIBRATION = "inputs{}.components[].analyses{}.instrument_last_calibrated"
WORKUP_CALIBRATION = (
    "workups[].input.components[].analyses{}.instrument_last_calibrated"
)
OUTCOME_CALIBRATION = "outcomes[].analyses{}.instrument_last_calibrated"
STANDARD_CALIBRATION = (
    "outcomes[].products[].measurements[].authentic_standard"
    ".analyses{}.instrument_last_calibrated"
)

# What ord_schema.updates stamps on a reaction it modifies. It writes
# ``datetime.datetime.now(datetime.UTC).ctime()``, so an event carrying both of
# these is the one case where the corpus knows a value's time zone.
PIPELINE_EMAIL = "github-actions@github.com"
PIPELINE_DETAILS = "Automatic updates from the submission pipeline."


def pipeline_authored(event) -> bool:
    """Returns whether a RecordEvent was written by the submission pipeline.

    Args:
        event: A ``RecordEvent`` parsed by this module's message classes.

    Returns:
        True if the event carries the pipeline's identity and details.
    """
    return (
        event.person.email == PIPELINE_EMAIL and event.details == PIPELINE_DETAILS
    )


def _build_reaction_class():
    """Compiles the cut-down schema and returns its Reaction message class."""
    file_proto = descriptor_pb2.FileDescriptorProto()
    file_proto.name = "ord_mini.proto"
    file_proto.package = "ord_mini"
    file_proto.syntax = "proto3"
    for message_name, fields in _MESSAGES.items():
        message = file_proto.message_type.add()
        message.name = message_name
        for field_name, number, field_type, label, type_name in fields:
            field = message.field.add()
            field.name = field_name
            field.number = number
            field.type = field_type
            field.label = label
            if type_name is not None:
                field.type_name = f".ord_mini.{type_name}"
    pool = descriptor_pool.DescriptorPool()
    pool.Add(file_proto)
    return message_factory.GetMessageClass(
        pool.FindMessageTypeByName("ord_mini.Reaction")
    )


Reaction = _build_reaction_class()


def date_times(reaction):
    """Yields ``(schema position, value)`` for every DateTime in a Reaction.

    Args:
        reaction: A ``Reaction`` parsed by this module's message class.

    Yields:
        Pairs of the dotted schema position and the raw string value.
    """
    for position, value, _ in date_times_with_zone(reaction):
        yield position, value


def date_times_with_zone(reaction):
    """Yields ``(schema position, value, utc_known)`` for every DateTime.

    Positions whose containing message is absent are skipped; a position whose
    message is present but whose DateTime is unset yields an empty value, which
    is how an always-empty field is told apart from an absent one.
    ``utc_known`` is True only where the corpus identifies the writer as one
    that works in UTC.

    Args:
        reaction: A ``Reaction`` parsed by this module's message class.

    Yields:
        Triples of the dotted schema position, the raw string value, and
        whether the value is known to be UTC.
    """
    provenance = reaction.provenance
    if provenance.HasField("experiment_start"):
        yield EXPERIMENT_START, provenance.experiment_start.value, False
    if provenance.HasField("record_created"):
        yield RECORD_CREATED, provenance.record_created.time.value, False
    for record in provenance.record_modified:
        yield RECORD_MODIFIED, record.time.value, pipeline_authored(record)
    for entry in reaction.inputs:
        for component in entry.value.components:
            for analysis in component.analyses:
                yield (
                    INPUT_CALIBRATION,
                    analysis.value.instrument_last_calibrated.value,
                    False,
                )
    for workup in reaction.workups:
        for component in workup.input.components:
            for analysis in component.analyses:
                yield (
                    WORKUP_CALIBRATION,
                    analysis.value.instrument_last_calibrated.value,
                    False,
                )
    for outcome in reaction.outcomes:
        for analysis in outcome.analyses:
            yield (
                OUTCOME_CALIBRATION,
                analysis.value.instrument_last_calibrated.value,
                False,
            )
        for product in outcome.products:
            for measurement in product.measurements:
                for analysis in measurement.authentic_standard.analyses:
                    yield (
                        STANDARD_CALIBRATION,
                        analysis.value.instrument_last_calibrated.value,
                    )
